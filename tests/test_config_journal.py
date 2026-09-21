"""Offline redo-transaction failure contracts; synthetic files only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config_journal import ConfigJournal, RecoveryRequired


class ConfigJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.tmp)
        self.journal = ConfigJournal(self.root / "config.json", self.root / "runtime_state.json", {"raw"})
        self.old = {"endpoint": "old.invalid"}
        self.new = {"endpoint": "new.invalid"}
        for key, data in (("config", self.old), ("runtime", {"raw": 120})):
            self.journal.targets[key].write_text(json.dumps(data), encoding="utf-8")

    def assert_stores(self, config, raw):
        self.assertEqual(json.loads(self.journal.targets["config"].read_text()), config)
        self.assertEqual(json.loads(self.journal.targets["runtime"].read_text()), {"raw": raw})

    def test_complete_values_and_repeated_recovery(self):
        self.journal.commit(self.new, {"raw": None})
        self.assert_stores(self.new, None)
        self.assertFalse(self.journal.recover())

    def test_each_replace_failure_and_interrupted_replay(self):
        original = ConfigJournal._replace
        for failure in (1, 2, 3, 4, 5):
            with self.subTest(failure=failure):
                self.setUp()
                calls = []
                def replace(path, value):
                    calls.append(path)
                    if len(calls) == failure:
                        raise OSError("injected replacement failure")
                    return original(path, value)
                with patch.object(ConfigJournal, "_replace", side_effect=replace):
                    with self.assertRaises((OSError, RecoveryRequired)):
                        self.journal.commit(self.new, {"raw": None})
                if failure == 1:
                    self.assert_stores(self.old, 120)
                    self.journal.require_clear()
                else:
                    with self.assertRaises(RecoveryRequired):
                        self.journal.require_clear()
                    with self.assertRaises(RecoveryRequired):
                        self.journal.recover(persist=False)
                    with patch.object(ConfigJournal, "_replace", side_effect=OSError("interrupted replay")):
                        with self.assertRaises(RecoveryRequired):
                            self.journal.recover()
                    self.assertTrue(self.journal.recover())
                    self.assert_stores(self.new, None)
                    self.assertFalse(self.journal.recover())

    def test_fsync_and_rename_before_commit_preserve_originals(self):
        for name in ("fsync", "replace"):
            with self.subTest(name=name), patch("app.config_journal.os." + name, side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    self.journal.commit(self.new, {"raw": None})
            self.assert_stores(self.old, 120)
            self.journal.require_clear()

    def test_serialization_write_failure_before_and_after_commit(self):
        original = json.dump
        for failure in (1, 2, 3, 4, 5):
            with self.subTest(failure=failure):
                self.setUp()
                calls = []
                def dump(*args, **kwargs):
                    calls.append(1)
                    if len(calls) == failure:
                        raise OSError("injected file write")
                    return original(*args, **kwargs)
                with patch("app.config_journal.json.dump", side_effect=dump):
                    with self.assertRaises((OSError, RecoveryRequired)):
                        self.journal.commit(self.new, {"raw": None})
                if failure == 1:
                    self.assert_stores(self.old, 120)
                else:
                    self.assertTrue(self.journal.recover())
                    self.assert_stores(self.new, None)

    def test_fsync_failure_after_intent_commit_is_recoverable(self):
        original = ConfigJournal._replace
        def replace(path, value):
            if path == self.journal.targets["runtime"]:
                with patch("app.config_journal.os.fsync", side_effect=OSError("injected fsync")):
                    return original(path, value)
            return original(path, value)
        with patch.object(ConfigJournal, "_replace", side_effect=replace):
            with self.assertRaises(RecoveryRequired):
                self.journal.commit(self.new, {"raw": None})
        self.assertTrue(self.journal.recover())
        self.assert_stores(self.new, None)

    def test_bad_schema_never_follows_paths_or_overwrites_originals(self):
        self.journal.path.parent.mkdir()
        for value in ({"version": 99, "values": {}},
                      {"version": 1, "values": {"../../config.json": self.new, "runtime": {"raw": None}}},
                      {"version": 1, "values": {"config": [], "runtime": {"raw": None}}}):
            self.journal.path.write_text(json.dumps(value))
            with self.assertRaises(RecoveryRequired):
                self.journal.recover()
            self.assert_stores(self.old, 120)
        self.journal.path.write_text("{broken")
        with self.assertRaises(RecoveryRequired):
            self.journal.recover()
        self.assert_stores(self.old, 120)

    def test_unlink_failure_keeps_replayable_committed_intent(self):
        original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path == self.journal.path:
                raise OSError("injected unlink")
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", unlink):
            with self.assertRaises(RecoveryRequired):
                self.journal.commit(self.new, {"raw": None})
        self.assert_stores(self.new, None)
        self.assertTrue(self.journal.recover())

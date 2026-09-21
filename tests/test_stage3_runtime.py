"""Stage 3 runtime contracts, executed only by the protected offline runner."""
import asyncio
import unittest
from unittest.mock import Mock, patch

from offline_fixtures import guarded_runtime, isolated_runtime
from test_runtime_bootstrap import complete_without_loop

runtime = guarded_runtime()


class Stage3RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))

    def test_unkeyed_live_save_never_opens_database(self):
        with patch.object(runtime, "get_db_conn") as connect:
            self.assertEqual(runtime.save_to_db({"accumulated_flow_l": 100})["error"], "measurement_identity_required")
            connect.assert_not_called()

    def test_sqlite_display_reset_new_measurement_and_savings_share_usage(self):
        import tempfile
        from pathlib import Path
        from datetime import datetime, timezone, timedelta
        from zoneinfo import ZoneInfo
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(runtime, "DB_DIR", directory))
        cfg = runtime.config_store
        cfg.update(device_profiles={"AMS01": {"transport": "opcua"}}, device_profiles_explicit=True,
                   site_timezone="Asia/Seoul", measurement_epochs={}, measurement_display_offsets={})
        source = runtime._measurement_sources(cfg)["AMS01"]
        now = datetime.now(timezone.utc) - timedelta(seconds=20)
        def save(raw, offset):
            epoch = str((cfg.get("measurement_epochs") or {}).get("AMS01", "initial"))
            return runtime.save_to_db({"device_id": "AMS01", "source_key": source,
                "measurement_generation": epoch, "sample_id": str(offset),
                "timestamp": (now + timedelta(seconds=offset)).isoformat(),
                "accumulated_flow_l": raw, "device_connected": True, "ams_code": 3})
        self.assertIsNone(save(100, 0)["delta_flow_l"])
        self.assertEqual(save(110, 5)["delta_flow_l"], 10)
        runtime.savings.remember("AMS01", {"operation_kpa": 600, "standby_kpa": 300})
        estimate = runtime.savings.today("AMS01", directory / "unused.db", None, 10, 1, 1,
                                         source=source, generation="initial")
        self.assertEqual(estimate["standby_litres"], 10)
        with (patch.object(runtime, "_config_journal"), patch.object(runtime, "save_runtime_state"),
              patch.object(runtime, "get_device_hub") as hub):
            runtime.ctrl_data_total_reset("AMS01")
            self.assertEqual(runtime._committed_measurement_totals(cfg)["AMS01"]["dashboard_total_flow_l"], 0)
            self.assertEqual(save(115, 10)["delta_flow_l"], 5)
            self.assertEqual(runtime._committed_measurement_totals(cfg)["AMS01"]["dashboard_total_flow_l"], 5)
            runtime.api_new_measurement("AMS01")
            self.assertIsNone(save(1000, 15)["delta_flow_l"])
            hub.assert_not_called()
        day = now.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        rows = runtime.query_history(day, day, "day", "accumulated", "AMS01")
        self.assertEqual(rows[0]["usage"], 15)
        self.assertIn("15.0", runtime.export_history_query_csv(day, day, "day", "accumulated", remote_id="AMS01").getvalue())

    def test_epoch_commit_failure_does_not_publish_identity(self):
        import copy
        before = copy.deepcopy(runtime.config_store)
        with (patch.object(runtime, "_config_journal") as journal,
              patch.object(runtime, "_validate_config_candidate"),
              patch.object(runtime, "_measurement_sources", side_effect=lambda c: {"AMS01": c.get("test_source", "A")})):
            journal.return_value.commit.side_effect = OSError("synthetic commit failure")
            with self.assertRaises(OSError):
                runtime.update_config_values(_build_changes=lambda c: {"test_source": "B"})
        self.assertEqual(runtime.config_store, before)

    def test_save_rejects_inactive_source_and_epoch_before_database(self):
        row = {"device_id": "AMS01", "source_key": "old", "measurement_generation": "epoch1"}
        with (patch.object(runtime, "_measurement_sources", return_value={"AMS01": "active"}),
              patch.dict(runtime.config_store, {"measurement_epochs": {"AMS01": "epoch2"}}),
              patch.object(runtime.history_contract, "save") as save):
            self.assertEqual(runtime.save_to_db(row)["error"], "inactive_measurement_identity")
            row["source_key"] = "active"
            self.assertEqual(runtime.save_to_db(row)["error"], "inactive_measurement_identity")
            save.assert_not_called()
            row["measurement_generation"] = "epoch2"
            runtime.save_to_db(row)
            save.assert_called_once()

    def test_history_and_raw_csv_share_timezone_and_exclusive_day_boundary(self):
        import tempfile
        import csv
        import io
        from pathlib import Path
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(runtime, "DB_DIR", directory))
        conn = runtime.get_db_conn(runtime.sample_time("2026-08-31T15:00:00+00:00"))
        conn.executemany("INSERT INTO ams_log(timestamp,remote_id,delta_flow,flow) VALUES(?,?,?,?)", [
            ("2026-08-31T14:59:59+00:00", "AMS01", 100, 100),
            ("2026-08-31T15:00:00+00:00", "AMS01", 2, 20),
            ("2026-09-01T14:59:59.999999+00:00", "AMS01", 3, 30),
            ("2026-09-01T15:00:00+00:00", "AMS01", 100, 100)])
        conn.commit()
        conn.close()
        with patch.dict(runtime.config_store, {"site_timezone": "Asia/Seoul"}):
            buckets = runtime.query_history("2026-09-01", "2026-09-01", "day", "accumulated", "AMS01")
            raw = list(csv.DictReader(io.StringIO("".join(runtime.iter_export_csv(
                "2026-09-01", "2026-09-01", "AMS01")))))
        self.assertEqual(buckets[0]["usage"], 5)
        self.assertEqual(sum(float(row["delta_flow"]) for row in raw), 5)
        self.assertEqual(len(raw), 2)

    def test_identity_a_b_a_rotates_epochs_but_rename_does_not(self):
        import copy
        cfg = copy.deepcopy(runtime.config_store)
        with (patch.object(runtime, "config_store", cfg),
              patch.object(runtime, "_config_journal") as journal,
              patch.object(runtime, "_validate_config_candidate"),
              patch.object(runtime, "save_config"),
              patch.object(runtime, "save_runtime_state"),
              patch.object(runtime, "_measurement_sources", side_effect=lambda c: {"AMS01": c.get("test_source", "A")})):
            runtime.update_config_values(_build_changes=lambda c: {"test_source": "B"})
            first = cfg["measurement_epochs"]["AMS01"]
            runtime.update_config_values(_build_changes=lambda c: {"test_source": "A"})
            second = cfg["measurement_epochs"]["AMS01"]
            self.assertNotEqual(first, second)
            runtime.update_config_values(_build_changes=lambda c: {"test_label": "renamed"})
            self.assertEqual(second, cfg["measurement_epochs"]["AMS01"])
            self.assertEqual(journal.return_value.commit.call_count, 2)

    def test_display_reset_only_persists_offset_without_device_read(self):
        with (patch.object(runtime, "_committed_measurement_totals", return_value={
                "AMS01": {"key": "AMS01:source:epoch", "committed_total_flow_l": 123}}),
              patch.object(runtime, "update_config_values") as update,
              patch.object(runtime, "get_device_hub") as hub):
            result = runtime.ctrl_data_total_reset("AMS01")
            changes = update.call_args.kwargs["_build_changes"]({})
            self.assertEqual(changes, {"measurement_display_offsets": {"AMS01:source:epoch": 123}})
            self.assertEqual(result["basis"], "display_offset_only")
            hub.assert_not_called()

    def test_missing_measurement_time_cannot_become_good(self):
        from app.device_hub import DeviceProfile
        profile = DeviceProfile("AMS01", "synthetic", "remote", "simulator")
        row = runtime._stamp_measurement(profile, {"device_connected": True, "accumulated_flow_l": 100})
        self.assertFalse(row["device_connected"])
        self.assertEqual(row["error"], "measurement_timestamp_missing")

    def test_collection_stores_identified_invalid_rows_not_combined(self):
        valid = {"device_id": "AMS01", "source_key": "synthetic-source",
                 "sample_id": "one", "timestamp": "2026-09-12T00:00:00+00:00",
                 "device_connected": True, "accumulated_flow_l": 100}
        invalid = {**valid, "sample_id": "two", "device_connected": False,
                   "timestamp": "2026-09-12T00:00:01+00:00",
                   "accumulated_flow_l": None, "error": "synthetic disconnect"}
        hub = Mock()
        hub.read_all.return_value = {
            "devices": [valid, invalid, {"device_id": "AMS02", "device_connected": True}],
            "combined": {"device_id": "COMBINED", "device_connected": True,
                         "accumulated_flow_l": 999},
        }
        with patch.object(runtime, "save_to_db") as save:
            runtime._save_collected_snapshot(hub.read_all.return_value)
        hub.read_all.assert_not_called()
        self.assertEqual([call.args[0] for call in save.call_args_list], [valid, invalid])

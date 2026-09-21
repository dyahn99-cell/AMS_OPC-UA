"""Private redo intent for the two configuration stores (never a device journal).

The commit point is replacement of the fsynced intent. After that point failures
mean pending recovery, not rollback. Replay writes complete values idempotently.
This guarantees process-crash recovery, NOT power-loss durability on any OS.
POSIX replacements sync their parent directory, but final intent removal does
not: a power failure could resurrect stale intent after subsequent saves.
Windows likewise has no asserted directory-metadata persistence guarantee.
This is not protection from another process running as the same OS user.
"""
import json
import os
from pathlib import Path


class RecoveryRequired(ValueError):
    pass


class ConfigJournal:
    def __init__(self, config_path, state_path, state_keys):
        self.targets = {"config": Path(config_path), "runtime": Path(state_path)}
        self.path = Path(config_path).parent / ".ams-private" / "config-transaction.json"
        self.state_keys = frozenset(state_keys)

    @staticmethod
    def _sync_directory(path):
        if os.name != "nt":
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    @classmethod
    def _replace(cls, path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_name(path.name + ".pending")
        try:
            with open(tmp, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            cls._sync_directory(path.parent)
        finally:
            if tmp.exists():
                tmp.unlink()

    def require_clear(self):
        if self.path.exists():
            raise RecoveryRequired("configuration recovery required; completion unknown; restart with recovery enabled")

    def _validate(self, value):
        if (not isinstance(value, dict) or set(value) != {"version", "values"}
                or type(value["version"]) is not int or value["version"] != 1
                or not isinstance(value["values"], dict)
                or set(value["values"]) != set(self.targets)):
            raise ValueError("invalid journal schema")
        config, state = value["values"]["config"], value["values"]["runtime"]
        if (not isinstance(config, dict) or not isinstance(state, dict)
                or set(state) != self.state_keys or set(config) & self.state_keys):
            raise ValueError("invalid journal stores")
        json.dumps(value, allow_nan=False)
        return value["values"]

    def recover(self, *, persist=True):
        if not self.path.exists():
            return False
        if not persist:
            raise RecoveryRequired("configuration recovery required; persist=False forbids replay")
        try:
            with open(self.path, encoding="utf-8") as stream:
                values = self._validate(json.load(stream))
            # Validate every target before touching either original. Paths come
            # only from bootstrap, never from journal content.
            for name, target in self.targets.items():
                self._replace(target, values[name])
            # Backup loading must not resurrect the previous route paired with
            # the new measurement baseline after a successful mixed commit.
            for name, target in self.targets.items():
                self._replace(target.with_suffix(target.suffix + ".bak"), values[name])
            # Intent removal is the final operation; if unlink fails the intact
            # intent blocks admission. Power-loss persistence of removal is
            # outside this process-crash contract (see module documentation).
            self.path.unlink()
        except BaseException as exc:
            raise RecoveryRequired("configuration recovery failed; originals retained where not yet replayed; completion unknown") from exc
        return True

    def commit(self, config, runtime):
        self.require_clear()
        intent = {"version": 1, "values": {"config": config, "runtime": runtime}}
        self._validate(intent)
        try:
            self._replace(self.path, intent)
        except BaseException as exc:
            if self.path.exists():
                raise RecoveryRequired("configuration intent committed; recovery required; completion unknown") from exc
            raise
        self.recover()

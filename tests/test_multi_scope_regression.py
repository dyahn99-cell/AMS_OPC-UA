import sqlite3
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.device_hub import DeviceProfile, DeviceRegistry
from app.hub_adapters import OpcuaHubAdapter


class MultiScopeTests(unittest.TestCase):
    def test_legacy_alias_is_not_registered_twice(self):
        registry = DeviceRegistry.from_config({"data_source": "opcua"}, opcua_device_ids=["AMS00", "AMS01", "AMS_01"])
        self.assertEqual([p.device_id for p in registry.all()], ["AMS00", "AMS01"])

    def test_explicit_duplicate_alias_rejected(self):
        with self.assertRaises(ValueError):
            DeviceRegistry([DeviceProfile("AMS01", "a", "remote", "opcua"), DeviceProfile("AMS_01", "b", "remote", "opcua")])

    def test_remote_settings_never_call_base_web_service(self):
        read, write = Mock(), Mock()
        adapter = OpcuaHubAdapter({"read_web_settings": read, "write_web_settings": write}, Mock())
        profile = DeviceProfile("AMS_02", "remote", "remote", "opcua")
        self.assertFalse(adapter.read_settings(profile)["ok"])
        self.assertFalse(adapter.write_settings(profile, {"operation_kpa": 400})["ok"])
        read.assert_not_called()
        write.assert_not_called()

    def test_all_flow_sums_before_averaging_and_energy_uses_usage(self):
        from offline_fixtures import guarded_runtime, isolated_runtime
        runtime = guarded_runtime()
        self.enterContext(isolated_runtime(runtime))
        import tempfile
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(runtime, "DB_DIR", directory))
        def database(*args):
            conn = sqlite3.connect(directory / "ams_data_2026_09.db")
            conn.execute("CREATE TABLE ams_log(timestamp TEXT, remote_id TEXT, flow REAL, delta_flow REAL, accumulated REAL, ams_status TEXT, diagnostic TEXT)")
            conn.executemany("INSERT INTO ams_log VALUES(?,?,?,?,?,?,?)", [
                ("2026-09-01T12:00:00", "AMS00", 10, 1, 100, "", ""),
                ("2026-09-01T12:00:00", "AMS01", 20, 2, 200, "", ""),
                ("2026-09-01T12:00:05", "AMS00", 30, 3, 103, "", ""),
                ("2026-09-01T12:00:05", "AMS01", 40, 4, 204, "", ""),
                ("2026-09-01T12:00:00", "COMBINED", 999, 999, 999, "", "")])
            return conn
        conn = database()
        conn.commit()
        conn.close()
        with patch.object(runtime, "get_kwh_per_m3", return_value=1):
            rows = runtime.query_history("2026-09-01", "2026-09-01", "hour", "flow", "ALL")
            row = next(r for r in rows if r["count"])
            self.assertEqual((row["avg"], row["max"], row["min"]), (50, 70, 30))
            rows = runtime.query_history("2026-09-01", "2026-09-01", "hour", "energy_kwh", "ALL")
            row = next(r for r in rows if r["count"])
            self.assertEqual(row["avg"], 0.01)


if __name__ == "__main__":
    unittest.main()

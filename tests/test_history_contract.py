import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from offline_fixtures import guarded_runtime, isolated_runtime

runtime = guarded_runtime()


class HistoryContractTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(runtime, "DB_DIR", Path(self.temp)))

    def save(self, raw, second, source="real-source", **extra):
        # Admission is tested separately; this fixture supplies the active synthetic route.
        with patch.object(runtime, "_measurement_sources", return_value={"AMS01": source}):
            return runtime.save_to_db({"device_id": "AMS01", "transport": "modbus", "source_key": source,
                "sample_id": str(second), "timestamp": f"2026-09-12T00:00:{second:02d}+00:00",
                "accumulated_flow_l": raw, "device_connected": True, **extra})

    def test_bad_counter_never_advances_baseline(self):
        self.save(100000, 0)
        self.save(None, 1)
        recovered = self.save(100010, 2)
        self.assertEqual(recovered["delta_flow_l"], 10)
        self.assertTrue(recovered["gap"])
        following = self.save(100015, 3)
        self.assertEqual(following["delta_flow_l"], 5)
        self.assertFalse(following["gap"])

    def test_source_change_and_duplicate_do_not_create_usage(self):
        self.save(100, 0)
        self.assertIsNone(self.save(1000, 1, "replacement")["delta_flow_l"])
        self.assertEqual(self.save(1010, 2, "replacement")["delta_flow_l"], 10)
        self.assertIn("ignored", self.save(9000, 2, "replacement"))
        self.assertIn("ignored", self.save(9000, 1, "replacement"))

    def test_utc_sample_month_and_invalid_energy_preserve_raw(self):
        with (patch.dict(runtime.config_store, {"energy_tree_per_co2": 0}),
              patch.object(runtime, "_measurement_sources", return_value={"AMS01": "s"})):
            result = runtime.save_to_db({"device_id": "AMS01", "source_key": "s", "sample_id": "boundary",
                "timestamp": "2026-09-01T00:00:00+09:00", "accumulated_flow_l": 100})
        self.assertTrue(result["ok"])
        self.assertTrue((Path(self.temp) / "ams_data_2026_08.db").exists())

    def test_derivation_failure_on_second_valid_sample_preserves_raw_and_baseline(self):
        self.assertTrue(self.save(100, 0)["ok"])
        with patch.object(runtime, "calculate_energy", side_effect=RuntimeError("synthetic derivation failure")):
            result = self.save(110, 1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["energy_error"], "energy_derivation_failed")
        conn = runtime.get_db_conn(runtime.sample_time("2026-09-12T00:00:01+00:00"))
        try:
            row = conn.execute("SELECT raw_accumulated,delta_flow,energy_kwh FROM ams_log ORDER BY timestamp DESC LIMIT 1").fetchone()
            self.assertEqual(tuple(row), (110, 10, None))
        finally:
            conn.close()
        self.assertEqual(self.save(115, 2)["delta_flow_l"], 5)

    def test_invalid_existing_energy_on_second_sample_still_stores_raw(self):
        self.save(100, 0)
        with patch.dict(runtime.config_store, {"energy_tree_per_co2": 0}):
            result = self.save(110, 1)
        self.assertTrue(result["ok"])
        self.assertIn("energy_error", result)
        self.assertEqual(self.save(115, 2)["delta_flow_l"], 5)

    def test_legacy_rows_do_not_restore_an_unverified_source(self):
        conn = runtime.get_db_conn()
        conn.execute("INSERT INTO ams_log(timestamp,remote_id,raw_accumulated) VALUES('2026-09-01','AMS01',10)")
        conn.commit()
        conn.close()
        self.assertIsNone(self.save(1000, 1)["delta_flow_l"])

"""Synthetic Stage 3 core contracts; no runtime, config or device I/O."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app import history_contract as history


class HistoryCoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def connect(self, measured):
        conn = sqlite3.connect(self.directory / measured.strftime("ams_data_%Y_%m.db"))
        conn.execute("""CREATE TABLE IF NOT EXISTS ams_log (
            timestamp TEXT, remote_id TEXT, pressure REAL, temperature REAL, flow REAL,
            accumulated REAL, raw_accumulated REAL, delta_flow REAL, reset_detected INTEGER,
            ams_status TEXT, ams_code INTEGER, diagnostic TEXT, energy_kwh REAL,
            energy_cost REAL, energy_co2 REAL)""")
        return conn

    def save(self, raw, stamp, sample=None, **extra):
        data = dict(device_id="AMS01", source_key="source", measurement_generation="one",
                    timestamp=stamp, sample_id=sample or stamp, accumulated_flow_l=raw)
        data.update(extra)
        return history.save(self.directory, self.connect, data, lambda litres: {"kwh": litres / 1000})

    def test_generation_and_simulation_are_baseline_boundaries(self):
        self.save(100, "2026-08-31T23:59:00Z")
        result = self.save(120, "2026-09-01T00:00:00Z")
        self.assertEqual(result["delta_flow_l"], 20)
        self.assertEqual(result["committed_total_flow_l"], 20)
        self.assertIsNone(self.save(1000, "2026-09-01T00:01:00Z", measurement_generation="two")["delta_flow_l"])
        self.assertIsNone(self.save(10000, "2026-09-01T00:02:00Z", simulated=True)["delta_flow_l"])

    def test_cross_partition_duplicate_and_invalid_watermark(self):
        self.save(100, "2026-08-31T23:59:00Z", "same")
        duplicate = self.save(999, "2026-09-01T00:00:00Z", "same")
        self.assertFalse(duplicate["committed"])
        self.assertIsNone(duplicate["delta_flow_l"])
        self.save(None, "2026-09-01T00:02:00Z")
        self.assertEqual(self.save(110, "2026-09-01T00:01:00Z")["ignored"], "out_of_order")
        recovered = self.save(120, "2026-09-01T00:03:00Z")
        self.assertEqual(recovered["delta_flow_l"], 20)
        self.assertTrue(recovered["gap"])

    def test_commit_failure_restores_only_committed_raw(self):
        self.save(100, "2026-09-01T00:00:00Z")
        real_connect = self.connect
        class FailedCommit:
            def __init__(self, conn): self.conn = conn
            def execute(self, *args): return self.conn.execute(*args)
            def commit(self): raise sqlite3.OperationalError("synthetic commit failure")
            def close(self): self.conn.close()
        self.connect = lambda measured: FailedCommit(real_connect(measured))
        with self.assertRaises(sqlite3.OperationalError):
            self.save(120, "2026-09-01T00:01:00Z")
        self.connect = real_connect
        self.assertEqual(self.save(150, "2026-09-01T00:02:00Z")["delta_flow_l"], 50)

    def test_source_descriptor_excludes_names_credentials_outputs_and_epoch(self):
        profile = SimpleNamespace(transport="opcua", endpoint="opc.tcp://user:secret@HOST:4840/",
                                  channel=1, model=40, device_id="AMS01",
                                  metadata={"output_start": 100, "input_start": 20, "scale": 1})
        first = history.source_key(profile, {}, {"flow": "ns=2;i=1", "p4_do": "output"})
        profile.endpoint = "opc.tcp://host"
        profile.metadata["output_start"] = 200
        profile.name = "renamed"
        second = history.source_key(profile, {"measurement_epochs": {"AMS01": "new"}},
                                    {"flow": "ns=2;i=1", "p4_do": "changed"})
        self.assertEqual(first, second)
        self.assertNotIn("secret", str(history.source_descriptor(profile, {})))
        profile.metadata["scale"] = 2
        self.assertNotEqual(first, history.source_key(profile, {}, {"flow": "ns=2;i=1"}))

    def test_read_only_legacy_misplaced_partition_half_open_and_weighted(self):
        # A legacy local sample is intentionally stored in the wrong partition.
        conn = self.connect(datetime(2026, 7, 1))
        conn.executemany("INSERT INTO ams_log(timestamp,remote_id,flow,delta_flow) VALUES(?,?,?,?)", [
            ("2026-09-01T09:00:00", "AMS01", 10, 1),
            ("2026-09-01T09:01:00", "AMS01", 20, 2),
            ("2026-09-02T00:00:00", "AMS01", 999, 999)])
        conn.commit()
        conn.close()
        self.save(100, "2026-09-01T00:02:00Z", instant_flow_l_min=60)
        before = {path: path.read_bytes() for path in self.directory.glob("*.db")}
        start, end = datetime(2026, 9, 1), datetime(2026, 9, 2)
        zone = timezone(timedelta(hours=9))
        rows = list(history.rows(self.directory, start, end, "AMS01", site_timezone=zone))
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(row["legacy"] for row in rows), 2)
        result = history.query(self.directory, start, end, "day", "flow", "AMS01", None,
                               lambda value: {}, site_timezone=zone)[0]
        self.assertEqual(result["avg"], 30)
        self.assertEqual((result["value_sum"], result["value_count"]), (90, 3))
        self.assertEqual(before, {path: path.read_bytes() for path in self.directory.glob("*.db")})
        filtered = list(history.rows(self.directory, start, end, "AMS01", site_timezone=zone,
                                     source="source", generation="one"))
        self.assertEqual(len(filtered), 1)

    def test_all_and_individual_energy_share_period_deltas(self):
        self.save(100, "2026-09-01T00:00:00Z")
        self.save(110, "2026-09-01T00:01:00Z")
        self.save(500, "2026-09-01T00:02:00Z", source_key="demo", simulated=True)
        self.save(600, "2026-09-01T00:03:00Z", source_key="demo", simulated=True)
        args = (self.directory, datetime(2026, 9, 1), datetime(2026, 9, 2), "day", "energy_kwh")
        for device in ("ALL", "AMS01"):
            row = history.query(*args, device, None, lambda value: {"kwh": value / 1000},
                                site_timezone=timezone.utc, include_simulated=False)[0]
            self.assertEqual(row["usage"], 10)
            self.assertEqual(row["avg"], .01)
            self.assertEqual(row["quality"], "partial")

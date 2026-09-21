"""Bounded endpoint and automatic-output contracts, synthetic physical client."""
import copy
import concurrent.futures
import threading
import time
import unittest
from unittest.mock import patch
from offline_fixtures import guarded_runtime, isolated_runtime


class Stage4OutputsTests(unittest.TestCase):
    def setUp(self):
        self.r = guarded_runtime()
        context = isolated_runtime(self.r)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.r.config_store.update(data_source="modbus", modbus_process_byte_swap=True)

    def test_independent_gateways_progress_same_endpoint_serializes(self):
        r = self.r
        gateway = copy.deepcopy(r.config_store["modbus_gateways"]["FIXTURE-EXW1"])
        gateway.update(host="second.invalid", slots=[{**gateway["slots"][0], "device_id": "AMS03"}])
        r.config_store["modbus_gateways"]["SECOND"] = gateway
        entered, release, other = threading.Event(), threading.Event(), threading.Event()
        active, peak = [0], [0]
        lock = threading.Lock()
        class Client:
            def read_holding_registers(self, address, count):
                with lock:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                if not entered.is_set():
                    entered.set()
                    if not release.wait(3):
                        raise AssertionError("blocked gateway never released")
                with lock:
                    active[0] -= 1
                return [0]
            def write_registers(self, address, values):
                pass
        first = Client()
        class Other(Client):
            def read_holding_registers(self, address, count):
                other.set()
                return [0]
        second = Other()
        def client(**kwargs):
            return second if kwargs.get("remote_id") == "AMS03" else first
        with patch.object(r, "_modbus_client_for", side_effect=client):
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                a = pool.submit(r.set_port4_do, 0, "AMS01")
                self.assertTrue(entered.wait(2))
                b = pool.submit(r.set_port4_do, 0, "AMS02")
                c = pool.submit(r.set_port4_do, 0, "AMS03")
                try:
                    self.assertTrue(other.wait(2), "independent gateway blocked globally")
                    self.assertFalse(b.done())
                finally:
                    release.set()
                self.assertTrue(all(f.result(3)["ok"] for f in (a, b, c)))
        self.assertEqual(peak[0], 1)

    def test_owner_blocks_control_but_not_port4(self):
        r = self.r
        r.config_store["dio_links"] = {"AMS01": {"enabled": True}}
        with patch.object(r, "_modbus_read_registers", return_value=[0]) as read, patch.object(r, "_modbus_write_registers") as write:
            for command, payload in (("mode", {"mode": 1}), ("standby", {"enabled": True}),
                                     ("forced_standby", {"enabled": True}), ("air_supply", {"enabled": True})):
                result = r._legacy_hub_command("AMS01", command, payload)
                self.assertFalse(result["ok"])
                self.assertIn("automatic_output_owned", result["error"])
            scheduled = r._run_schedule_hub_command("AMS01", 1)
            self.assertFalse(scheduled["ok"])
            self.assertIn("automatic_output_owned", scheduled["results"]["AMS01"]["error"])
            read.assert_not_called()
            write.assert_not_called()
            self.assertTrue(r.set_port4_do(0, "AMS01")["ok"])

    def payload(self):
        return {"config_generation": self.r.current_config_generation(), "devices": [
            {"device_id": "IO13", "online": True, "timestamp": "2026-09-01T00:00:00+00:00", "dio_code": 1},
            {"device_id": "AMS01", "online": True, "timestamp": "2026-09-01T00:00:00+00:00", "ams_code": 3}]}

    def test_unconfirmed_dio_and_old_generation_zero_writes(self):
        r = self.r
        r.config_store["dio_links"] = {"AMS01": {"enabled": True}}
        with patch.object(r.time, "time", return_value=1788220801), patch.object(r, "_modbus_write_registers") as write:
            r._apply_dio_links(self.payload())
            self.assertTrue(r._dio_link_runtime["AMS01"]["recovery_required"])
            payload = self.payload()
            payload["config_generation"] = -1
            r._apply_ch1_status_lamp(payload)
            write.assert_not_called()

    def test_lamp_fresh_rmw_readback_preserves_other_bits_and_dedups(self):
        r = self.r
        value = [0xFDAB]
        def write(address, values, **kwargs):
            value[0] = values[0]
        with patch.object(r.time, "time", return_value=1788220801), patch.object(r, "_modbus_read_registers", side_effect=lambda *a, **k: [value[0]]) as read, patch.object(r, "_modbus_write_registers", side_effect=write) as writes:
            r._apply_ch1_status_lamp(self.payload())
            self.assertEqual(value[0], 0xFEAB)
            self.assertEqual(read.call_count, 2)
            r._apply_ch1_status_lamp(self.payload())
            self.assertEqual(writes.call_count, 1)
            payload = self.payload()
            payload["devices"][0]["connection_generation"] = 2
            r._apply_ch1_status_lamp(payload)
            self.assertEqual(writes.call_count, 2)

    def test_lamp_failed_current_read_zero_writes(self):
        r = self.r
        with patch.object(r.time, "time", return_value=1788220801), patch.object(r, "_modbus_read_registers", side_effect=ValueError("missing current")), patch.object(r, "_modbus_write_registers") as write:
            r._apply_ch1_status_lamp(self.payload())
            write.assert_not_called()
            self.assertNotIn("last_written_bits", r._CH1_LAMP_STATE["IO13"])

    def test_lamp_mismatch_not_deduplicated_as_success(self):
        r = self.r
        with patch.object(r.time, "time", return_value=1788220801), patch.object(r, "_modbus_read_registers", return_value=[0]), patch.object(r, "_modbus_write_registers") as write:
            r._apply_ch1_status_lamp(self.payload())
            self.assertEqual(write.call_count, 1)
            self.assertIn("readback_mismatch", r._CH1_LAMP_STATE["IO13"]["error"])
            self.assertNotIn("last_written_bits", r._CH1_LAMP_STATE["IO13"])

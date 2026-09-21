"""Real runtime/adapters, synthetic transports; run only in protected checkout."""
import concurrent.futures
import threading
import time
import unittest
from unittest.mock import patch

from offline_fixtures import guarded_runtime, isolated_runtime


class Port4PinIntentTests(unittest.TestCase):
    def setUp(self):
        self.r = guarded_runtime()
        context = isolated_runtime(self.r)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        # A fixture routing mistake must fail locally, before any DNS/socket call.
        blocked = patch.object(self.r, "_modbus_read_registers", side_effect=AssertionError("unmocked Modbus route"))
        blocked.start()
        self.addCleanup(blocked.stop)

    def test_invalid_intents_no_hub(self):
        r = self.r
        with patch.object(r, "get_device_hub") as hub:
            for payload in ({}, {"pin": 2}, {"pin": True, "enabled": True},
                            {"pin": 3, "enabled": True}, {"pin": 2, "enabled": 1},
                            {"pin": 2, "enabled": "false"}, {"value": 0, "pin": 2, "enabled": True},
                            {"value": None}, {"value": 256}, {"value": 0, "extra": 1}):
                self.assertFalse(r._legacy_hub_command("AMS01", "port4_do", payload)["ok"])
            hub.assert_not_called()

    def configure(self, transport):
        r = self.r
        r.config_store["data_source"] = transport
        if transport == "opcua":
            r.config_store["modbus_gateways"] = {}
            r.config_store["device_profiles"] = {"AMS01": {
                "transport": "opcua", "endpoint": "opc.tcp://ams-base.invalid:4840", "enabled": True}}
        else:
            r.config_store["modbus_process_byte_swap"] = True

    def exercise(self, transport, failure=None):
        r = self.r
        self.configure(transport)
        state = [0x2535 if transport == "modbus" else 0x35]
        calls = []
        def read(*args, **kwargs):
            calls.append("read")
            if failure == "read":
                raise ValueError("synthetic read failure")
            time.sleep(.005)
            value = state[0] ^ (1 if failure == "mismatch" and "write" in calls else 0)
            return [value] if transport == "modbus" else ({"ok": True, "value": value}, None)
        def write(*args, **kwargs):
            calls.append("write")
            state[0] = args[1][0] if transport == "modbus" else kwargs["json_body"]["value"]
            return None if transport == "modbus" else ({"ok": True}, None)
        def request(method, path, **kwargs):
            return read() if path == "/read" else write(json_body=kwargs["json_body"])
        from contextlib import ExitStack
        with ExitStack() as stack:
            if transport == "modbus":
                stack.enter_context(patch.object(r, "_modbus_read_registers", side_effect=read))
                stack.enter_context(patch.object(r, "_modbus_write_registers", side_effect=write))
            else:
                stack.enter_context(patch.object(r, "ensure_node_worker_ready", return_value=True))
                stack.enter_context(patch.object(r, "_owned_worker_request", side_effect=request))
            if failure:
                result = r.set_port4_do_pin(2, True, "AMS01")
                self.assertFalse(result["ok"], result)
                self.assertEqual(calls.count("write"), 0 if failure == "read" else 1)
                if failure == "mismatch":
                    self.assertIn("readback_mismatch", result["error"])
            else:
                barrier = threading.Barrier(2)
                def command(pin):
                    barrier.wait(timeout=2)
                    return r.ctrl_port4_do(r.Port4DoRequest(remote_id="AMS01", pin=pin, enabled=True))
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(command, [2, 4]))
                self.assertTrue(all(item["ok"] for item in results), results)
                self.assertEqual(state[0], 0x25F5 if transport == "modbus" else 0xF5)
                self.assertEqual(calls, ["read", "write", "read"] * 2)
                result = r.set_port4_do_pin(2, False, "AMS01")
                self.assertTrue(result["ok"], result)
                self.assertEqual(state[0] & 255, 0x75)
                result = r.set_port4_do(0x12, "AMS01")
                self.assertTrue(result["ok"], result)
                self.assertEqual(state[0] & 255, 0x12)

    def test_modbus_concurrent_pins(self):
        self.exercise("modbus")

    def test_opcua_concurrent_pins(self):
        self.exercise("opcua")

    def test_modbus_read_failure_zero_writes(self):
        self.exercise("modbus", "read")

    def test_opcua_read_failure_zero_writes(self):
        self.exercise("opcua", "read")

    def test_modbus_readback_mismatch_no_retry(self):
        self.exercise("modbus", "mismatch")

    def test_opcua_readback_mismatch_no_retry(self):
        self.exercise("opcua", "mismatch")

    def test_opcua_missing_bad_current_zero_writes(self):
        r = self.r
        self.configure("opcua")
        for response in ({"ok": False, "value": 0}, {"ok": True}, {"ok": True, "value": None},
                         {"ok": True, "value": False}, {"ok": True, "value": "0"}):
            with patch.object(r, "ensure_node_worker_ready", return_value=True), patch.object(
                    r, "_owned_worker_request", return_value=(response, None)) as request:
                self.assertFalse(r.set_port4_do_pin(2, True, "AMS01")["ok"])
                self.assertEqual(request.call_count, 1)
                self.assertEqual(request.call_args.args[1], "/read")

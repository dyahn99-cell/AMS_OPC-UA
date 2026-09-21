"""Offline regression tests: runtime functions are extracted without importing runtime."""
import ast
import copy
from concurrent.futures import ThreadPoolExecutor
from offline_fixtures import FrozenDatetime as datetime
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from typing import Optional
from unittest.mock import Mock, patch
from offline_fixtures import guarded_runtime, isolated_runtime

from app.connection_context import ConnectionContextManager
from app.device_hub import DeviceProfile, DeviceRegistry
from app.hub_adapters import ModbusHubAdapter, WebHubAdapter

SOURCE = ast.parse((Path(__file__).resolve().parents[1] / "app/runtime.py").read_text(encoding="utf-8-sig"))


def functions(names, env):
    nodes = [copy.deepcopy(n) for n in SOURCE.body if isinstance(n, ast.FunctionDef) and n.name in names]
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "runtime_AST", "exec"), env)
    return env


class RoutingFixTests(unittest.TestCase):
    def test_modbus_modes_ignore_global_source_and_keep_explicit_legacy_target(self):
        # Stage 1 replaces the old unsafe expectation that a non-Modbus global
        # source sends an explicit AMS02 request to the HTTP base instead.
        runtime = guarded_runtime()
        with isolated_runtime(runtime):
            for source in ("opcua", "web", "demo", "modbus"):
                for mode in (0, 1, 2, 3):
                    with self.subTest(source=source, mode=mode), patch.dict(runtime.config_store, {
                        "data_source": source, "device_profiles": {"AMS02": {"transport": "modbus"}}
                    }), patch.object(runtime, "set_ams_mode") as web, patch.object(runtime, "_modbus_set_bit", return_value={"ok": True}) as bit, patch.object(runtime, "_modbus_set_air", return_value={"ok": True}) as air:
                        self.assertTrue(runtime.set_source_ams_mode(mode, "AMS02")["ok"])
                        web.assert_not_called()
                        self.assertEqual(bit.call_args_list[0].args, ("AMS02", 0, False))
                        self.assertEqual(bit.call_args_list[1].args, ("AMS02", 1, mode == 2))
                        if mode != 2:
                            air.assert_called_once_with("AMS02", mode != 3, "NC")
                        runtime._hub_instance = None  # Mock transports change per iteration.

    def test_modbus_invalid_mode_and_target_do_not_write(self):
        # Exercise the real target validator; AST extraction omitted its new dependency.
        runtime = guarded_runtime()
        with isolated_runtime(runtime), patch.object(runtime, "_modbus_set_bit") as bit, \
                patch.object(runtime, "_modbus_set_air") as air:
            for mode, target in ((9, "AMS01"), (1, "UNKNOWN")):
                self.assertFalse(runtime.set_modbus_ams_mode(mode, target)["ok"])
            bit.assert_not_called()
            air.assert_not_called()

    def test_runtime_wiring_is_transport_specific(self):
        node = next(n for n in SOURCE.body if isinstance(n, ast.FunctionDef) and n.name == "_runtime_adapter_services")
        text = ast.unparse(node)
        self.assertIn("'set_modbus_mode': set_modbus_ams_mode", text)
        self.assertNotIn("set_source_ams_mode", text)

    def test_web_registry_rejects_wrong_target_or_endpoint_even_disabled(self):
        for device, role, endpoint in (("REMOTE_B", "remote", None), ("AMS00", "base", "http://other.invalid"), ("AMS00", "remote", None)):
            for enabled in (True, False):
                with self.subTest(device=device, endpoint=endpoint, enabled=enabled), self.assertRaises(ValueError):
                    DeviceRegistry.from_config({"ams_host": "https://base.invalid", "device_profiles": {device: {"role": role, "transport": "web", "endpoint": endpoint, "enabled": enabled}}})

    def test_web_default_and_explicit_configured_endpoint_allowed(self):
        for endpoint in (None, "https://base.invalid", "https://base.invalid/"):
            registry = DeviceRegistry.from_config({"ams_host": "https://base.invalid", "device_profiles": {"AMS00": {"transport": "web", "endpoint": endpoint}}})
            write = Mock(return_value={"ok": True})
            adapter = WebHubAdapter({"write_web_settings": write, "get_config": lambda *a: "https://base.invalid"}, ConnectionContextManager())
            self.assertTrue(adapter.write_settings(registry.require("AMS00"), {"operation_kpa": 500})["ok"])
            write.assert_called_once_with({"operation_kpa": 500})
        self.assertEqual(DeviceRegistry.from_config({"data_source": "web", "ams_host": "https://base.invalid"}).require("AMS00").endpoint, "https://base.invalid")

    def test_web_execution_guard_protects_all_paths_and_stale_profiles(self):
        callbacks = {name: Mock(return_value={"ok": True, "device_connected": True}) for name in ("fetch_web_data", "read_web_settings", "write_web_settings", "warmup_web", "post_control")}
        adapter = WebHubAdapter({**callbacks, "get_config": lambda *a: "https://base.invalid"}, ConnectionContextManager())
        for profile in (DeviceProfile("REMOTE_B", "r", "remote", "web"), DeviceProfile("AMS00", "b", "base", "web", endpoint="https://old.invalid")):
            self.assertFalse(adapter.read_telemetry(profile).online)
            self.assertFalse(adapter.read_settings(profile)["ok"])
            self.assertFalse(adapter.write_settings(profile, {})["ok"])
            for command in ("mode", "flow_reset"):
                self.assertFalse(adapter.execute_command(profile, command, {"mode": 3})["ok"])
        for callback in callbacks.values():
            callback.assert_not_called()

    def test_web_valid_base_reads_mode_and_reset(self):
        callbacks = {name: Mock(return_value={"ok": True, "device_connected": True}) for name in ("fetch_web_data", "read_web_settings", "warmup_web", "post_control")}
        adapter = WebHubAdapter({**callbacks, "mode_parameter": 10, "control_trigger": 11}, ConnectionContextManager())
        profile = DeviceProfile("AMS00", "base", "base", "web")
        self.assertTrue(adapter.read_telemetry(profile).online)
        self.assertTrue(adapter.read_settings(profile)["ok"])
        self.assertTrue(adapter.execute_command(profile, "mode", {"mode": 3})["ok"])
        self.assertEqual([c.args for c in callbacks["post_control"].call_args_list], [(10, "03"), (11, "01")])
        self.assertTrue(adapter.execute_command(profile, "flow_reset", {})["ok"])
        self.assertEqual(callbacks["post_control"].call_args.args, (0x8103, "be"))

    def test_web_api_uses_configured_endpoint_and_rejects_before_save(self):
        runtime = guarded_runtime()
        with isolated_runtime(runtime), patch.object(runtime, "save_config") as save, patch.object(runtime, "save_runtime_state") as state, patch.object(runtime, "start_node_worker") as start:
            for profiles in ({"REMOTE": {"transport": "web"}}, {"AMS00": {"transport": "web", "endpoint": "https://other.invalid"}}):
                with self.subTest(profiles=profiles):
                    before = copy.deepcopy(runtime.config_store)
                    generation = runtime.current_config_generation()
                    req = runtime.HubProfilesRequest(device_profiles=profiles)
                    self.assertFalse(runtime.api_hub_update_devices(req)["ok"])
                    save.assert_not_called()
                    state.assert_not_called()
                    start.assert_not_called()
                    self.assertEqual(runtime.config_store, before)
                    self.assertEqual(runtime.current_config_generation(), generation)


class HistoryFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        runtime = guarded_runtime()
        self.enterContext(isolated_runtime(runtime))
        self.enterContext(patch.object(runtime, "DB_DIR", self.directory))
        self.enterContext(patch.object(runtime, "get_db_conn", runtime.get_db_conn))
        self.e = runtime.__dict__  # Real module and dependencies, including commit failures.
        self.connect = self.e["get_db_conn"]

    def save(self, raw, device="AMS01"):
        self.e["_legacy_save_to_db_for_tests"]({"device_id": device, "transport": "modbus", "accumulated_flow_l": raw, "timestamp": "2026-09-12T10:00:00"})

    def rows(self):
        conn = self.connect()
        try:
            return [tuple(row) for row in conn.execute("SELECT remote_id,raw_accumulated,delta_flow,reset_detected FROM ams_log ORDER BY id")]
        finally:
            conn.close()

    def test_failed_insert_does_not_advance_baseline(self):
        self.save(100)
        conn = self.connect()
        conn.execute("CREATE TRIGGER reject_sample BEFORE INSERT ON ams_log WHEN NEW.raw_accumulated=120 BEGIN SELECT RAISE(ABORT,'test disk failure'); END")
        conn.commit()
        conn.close()
        self.save(120)
        self.assertEqual(self.e["_history_last_raw_by_device"]["AMS01"], 100)
        self.save(150)
        self.assertEqual(self.rows()[-1], ("AMS01", 150, 50, 0))

    def test_failed_commit_does_not_advance_baseline(self):
        self.save(100)
        class FailCommit:
            def __init__(self, real): self.real = real
            def execute(self, *args): return self.real.execute(*args)
            def commit(self): raise sqlite3.OperationalError("test commit failure")
            def close(self): self.real.close()
        self.e["get_db_conn"] = lambda *args: FailCommit(self.connect(*args))
        self.save(120)
        self.e["get_db_conn"] = self.connect
        self.assertEqual(self.e["_history_last_raw_by_device"]["AMS01"], 100)
        self.save(150)
        self.assertEqual(self.rows()[-1][2], 50)

    def test_restart_recovers_raw_not_adjusted_total_per_device(self):
        self.save(100)
        self.save(120)
        self.save(900, "AMS02")
        conn = self.connect()
        conn.execute("UPDATE ams_log SET accumulated=99999")
        conn.commit()
        conn.close()
        self.e["_history_last_raw_by_device"].clear()
        self.save(150)
        self.save(925, "AMS02")
        self.assertEqual(self.rows()[-2:], [("AMS01", 150, 30, 0), ("AMS02", 925, 25, 0)])

    def test_restart_previous_month_and_reset(self):
        now = datetime.now()
        previous = datetime(now.year - (now.month == 1), (now.month - 2) % 12 + 1, 1)
        conn = self.connect(previous)
        conn.execute("INSERT INTO ams_log(timestamp,remote_id,accumulated,raw_accumulated) VALUES(?,?,?,?)", (previous.isoformat(), "AMS01", 99999, 120))
        conn.commit()
        conn.close()
        self.save(150)
        self.assertEqual(self.rows()[-1][2], 30)
        self.e["_history_last_raw_by_device"].clear()
        self.save(5)
        self.save(8)
        self.assertEqual(self.rows()[-2:], [("AMS01", 5, 0, 1), ("AMS01", 8, 3, 0)])

    def test_no_history_unknown_raw_and_zero_raw(self):
        self.save(10)
        self.assertEqual(self.rows()[-1][2], 0)
        conn = self.connect()
        conn.execute("INSERT INTO ams_log(timestamp,remote_id,accumulated,raw_accumulated) VALUES('x','AMS01',99999,NULL)")
        conn.commit()
        conn.close()
        self.e["_history_last_raw_by_device"].clear()
        self.save(20)
        self.assertEqual(self.rows()[-1][2], 0)
        self.save(0, "AMS02")
        self.e["_history_last_raw_by_device"].clear()
        self.save(3, "AMS02")
        self.assertEqual(self.rows()[-1][2], 3)

    def test_concurrent_save_serializes_entire_commit(self):
        self.save(100)
        events = []
        event_lock = threading.Lock()
        class Observed:
            def __init__(self, real): self.real = real
            def execute(self, sql, *args):
                if "INSERT INTO ams_log" in sql:
                    with event_lock: events.append(("insert", threading.get_ident()))
                return self.real.execute(sql, *args)
            def commit(self):
                with event_lock: events.append(("commit", threading.get_ident()))
                self.real.commit()
            def close(self): self.real.close()
        self.e["get_db_conn"] = lambda *args: Observed(self.connect(*args))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(self.save, [110] * 12))
        self.assertEqual(sum(row[2] for row in self.rows()), 10)
        self.assertEqual(len(events), 24)
        for i in range(0, len(events), 2):
            self.assertEqual(events[i][0], "insert")
            self.assertEqual(events[i + 1], ("commit", events[i][1]))


class SignedIoddTests(unittest.TestCase):
    def decode(self, raw, width=16, offset=0, kind="IntegerT", **extra):
        field = {"name": "value", "bit_offset": offset, "bit_length": width, "data_type": kind, **extra}
        e = functions({"_hex_bytes_to_int", "_extract_pd_bits", "decode_iodd_pdin", "_format_display_value", "_resolve_state_name", "_to_int_or_none"}, {
            "Optional": Optional, "_get_iodd_by_id": lambda _: {"process_data_in_fields": [field]},
        })
        return e["decode_iodd_pdin"](raw, "test")[0][0]

    def test_signed_scaling_and_unsigned_hex(self):
        row = self.decode(["FF", "9C"], gradient=0.1, offset=0, display_format="Dec.1")
        self.assertEqual((row["value"], row["hex"], row["scaled"], row["display_value"]), (-100, "0xFF9C", -10, "-10.0"))

    def test_signed_limits_non_byte_width_and_enum(self):
        for raw, expected in ((["80", "00"], -32768), (["7F", "FF"], 32767), (["00", "00"], 0)):
            self.assertEqual(self.decode(raw)["value"], expected)
        self.assertEqual(self.decode(["0F", "F0"], width=8, offset=4)["value"], -1)
        row = self.decode(["FF", "FF"], single_values=[{"value": "-1", "name": "negative"}])
        self.assertEqual(row["state_name"], "negative")

    def test_unsigned_and_port4_big_endian_unchanged(self):
        self.assertEqual(self.decode(["FF", "9C"], kind="UIntegerT")["value"], 65436)
        self.assertEqual(self.decode(["00", "00", "00", "00", "0F", "A0", "30", "00"], offset=16, kind="UIntegerT")["value"], 4000)


if __name__ == "__main__":
    unittest.main()

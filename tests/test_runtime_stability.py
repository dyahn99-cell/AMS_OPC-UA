import concurrent.futures
import contextlib
import copy
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from offline_fixtures import guarded_runtime, isolated_runtime

runtime = guarded_runtime()


class RuntimeStabilityTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))
        self.config = copy.deepcopy(runtime.config_store)
        self.demo_state = copy.deepcopy(runtime._demo_live_state)
        self.migrated_dbs = set(runtime._migrated_dbs)
        runtime.config_store.update({
            "data_source": "demo",
            "force_mode": "01",
            "dashboard_total_flow_l": 0.0,
            "dashboard_last_raw_accumulated_l": 0.0,
            "iodd_assignments": {},
        })
        with runtime.demo_live_lock:
            runtime._demo_live_state.update({
                "started_at": None,
                "raw_accumulated_l": 0.0,
                "last_tick": None,
                "mode": None,
                "flow": None,
                "pressure": None,
                "temperature": None,
            })

    def tearDown(self):
        runtime.config_store.clear()
        runtime.config_store.update(self.config)
        with runtime.demo_live_lock:
            runtime._demo_live_state.clear()
            runtime._demo_live_state.update(self.demo_state)
        with runtime.db_migration_lock:
            runtime._migrated_dbs.clear()
            runtime._migrated_dbs.update(self.migrated_dbs)

    def test_demo_accumulator_depends_on_elapsed_time_not_request_count(self):
        runtime.fetch_process_data_demo()
        with runtime.demo_live_lock:
            start_raw = runtime._demo_live_state["raw_accumulated_l"]
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            list(executor.map(lambda _: runtime.fetch_process_data_demo(), range(320)))
        elapsed = time.perf_counter() - started
        with runtime.demo_live_lock:
            added = runtime._demo_live_state["raw_accumulated_l"] - start_raw
        physical_upper_bound = 120.0 * elapsed / 60.0 + 0.02
        self.assertLessEqual(added, physical_upper_bound)

    def test_demo_worker_status_does_not_touch_opcua_worker(self):
        with mock.patch.object(runtime.requests, "get", side_effect=AssertionError("unexpected worker request")):
            status = runtime._get_worker_status()
        self.assertTrue(status["disabled"])
        self.assertEqual(status["reason"], "demo_mode")

    def test_atomic_json_recovers_from_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            runtime._atomic_write_json(path, {"version": 1}, backup=True)
            runtime._atomic_write_json(path, {"version": 2}, backup=True)
            path.write_text("{broken", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                loaded = runtime._load_json_with_backup(path, {})
        self.assertEqual(loaded, {"version": 1})

    def test_runtime_counters_are_stored_separately_from_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            state_path = Path(temp_dir) / "runtime_state.json"
            with (
                mock.patch.object(runtime, "CONFIG_FILE", config_path),
                mock.patch.object(runtime, "RUNTIME_STATE_FILE", state_path),
            ):
                before = copy.deepcopy(runtime.config_store)
                generation = runtime.current_config_generation()
                # A durable redo intent now coordinates both separate stores.
                runtime.update_config_values(
                    energy_price_per_kwh=180.0,
                    dashboard_total_flow_l=123.0,
                    dashboard_last_raw_accumulated_l=45.0,
                )
                self.assertEqual(runtime.current_config_generation(), generation)
                self.assertTrue(config_path.exists())
                self.assertTrue(state_path.exists())
                self.assertFalse(runtime._config_journal().path.exists())

                runtime.update_config_values(energy_price_per_kwh=180.0)
                config_bytes = config_path.read_bytes()
                with mock.patch.object(runtime, "save_config") as config_save:
                    runtime.update_config_values(
                        dashboard_total_flow_l=123.0,
                        dashboard_last_raw_accumulated_l=45.0,
                    )
                    config_save.assert_not_called()
                self.assertEqual(config_path.read_bytes(), config_bytes)
                self.assertEqual(runtime.current_config_generation(), generation)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertTrue(runtime.RUNTIME_STATE_KEYS.isdisjoint(config))
        self.assertEqual(config["energy_price_per_kwh"], 180.0)
        self.assertEqual(set(state), runtime.RUNTIME_STATE_KEYS)
        self.assertEqual(state["dashboard_total_flow_l"], 123.0)
        self.assertEqual(state["dashboard_last_raw_accumulated_l"], 45.0)

    def test_raw_csv_streams_rows_from_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_dir = Path(temp_dir)
            with mock.patch.object(runtime, "DB_DIR", db_dir):
                with runtime.db_migration_lock:
                    runtime._migrated_dbs.clear()
                conn = runtime.get_db_conn(runtime.datetime(2026, 8, 1))
                conn.executemany(
                    """
                    INSERT INTO ams_log
                      (timestamp,remote_id,pressure,temperature,flow,accumulated,
                       raw_accumulated,delta_flow,reset_detected,ams_status,ams_code,diagnostic)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        ("2026-08-01T00:00:00", "AMS01", 0.6, 28.0, 10.0, 1, 1.0, 1.0, 0, "DEMO", 17, "test"),
                        ("2026-08-01T00:00:01", "AMS01", 0.6, 28.0, 11.0, 2, 2.0, 1.0, 0, "DEMO", 17, "test"),
                    ],
                )
                conn.commit()
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                indexes = {row[1] for row in conn.execute("PRAGMA index_list(ams_log)")}
                conn.close()
                csv_text = "".join(runtime.iter_export_csv("2026-08-01", "2026-08-01", "AMS01"))
        self.assertEqual(journal_mode.lower(), "wal")
        self.assertIn("idx_remote_ts", indexes)
        self.assertIn("timestamp,remote_id", csv_text)
        self.assertEqual(csv_text.count("AMS01"), 2)

    def test_history_period_limit_rejects_oversized_query(self):
        with self.assertRaisesRegex(ValueError, "maximum"):
            runtime._validated_history_range("2026-01-01", "2026-01-02", "second")

    def test_aggregate_csv_passes_remote_id(self):
        captured = []
        with mock.patch.object(
            runtime,
            "query_history",
            side_effect=lambda start, end, unit, field, remote_id="AMS00": captured.append(remote_id) or [],
        ):
            runtime.export_history_query_csv(
                "2026-08-01", "2026-08-02", "hour", "flow", "avg", "AMS01"
            )
        self.assertEqual(captured, ["AMS01"])

    def test_hub_history_counters_are_isolated_per_device(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_dir = Path(temp_dir)
            with (
                mock.patch.object(runtime, "DB_DIR", db_dir),
                mock.patch.object(runtime, "update_config_values") as update_config,
            ):
                with runtime.db_migration_lock:
                    runtime._migrated_dbs.clear()
                with runtime._history_counter_lock:
                    runtime._history_last_raw_by_device.clear()
                common = {
                    "device_connected": True, "pressure_mpa": 0.5,
                    "temperature_c": 25, "instant_flow_l_min": 10,
                    "ams_status": "Operation", "diagnostic": "No error",
                }
                runtime._legacy_save_to_db_for_tests({**common, "timestamp": "2026-08-30T00:00:00", "remote_id": "AMS01", "transport": "opcua", "accumulated_flow_l": 100})
                runtime._legacy_save_to_db_for_tests({**common, "timestamp": "2026-08-30T00:00:01", "remote_id": "AMS02", "transport": "web", "accumulated_flow_l": 50})
                runtime._legacy_save_to_db_for_tests({**common, "timestamp": "2026-08-30T00:00:02", "remote_id": "AMS01", "transport": "opcua", "accumulated_flow_l": 110})
                conn = runtime.get_db_conn()
                rows = conn.execute("SELECT remote_id,delta_flow FROM ams_log ORDER BY id").fetchall()
                conn.close()
        self.assertEqual([tuple(row) for row in rows], [("AMS01", 0.0), ("AMS02", 0.0), ("AMS01", 10.0)])
        update_config.assert_not_called()

    def test_manual_combined_schedule_rejects_unknown_restoration(self):
        from app.schedule_execution import ScheduleExecution
        from types import SimpleNamespace
        profile = runtime.get_device_hub().registry.require("AMS01")
        hub = mock.Mock()
        hub.registry.targets.return_value = [profile]
        hub.registry.require.return_value = profile
        hub.cached.return_value = {"ams_code": 1}  # no usable source/quality
        with (
            mock.patch.object(runtime, "schedules_store", [{
                "id": "hub-test", "name": "Hub test", "mode": 2,
                "remote_id": "COMBINED", "repeat": "once", "active": True,
                "start_time": "00:00", "end_time": "23:59",
            }]),
            mock.patch.object(runtime, "_schedule_execution", ScheduleExecution()),
            mock.patch.object(runtime, "get_device_hub", return_value=hub),
            mock.patch.object(runtime, "_resolve_command_target", return_value=SimpleNamespace()),
            mock.patch.object(runtime, "save_schedules"),
        ):
            result = runtime.execute_schedule("hub-test")
        self.assertFalse(result["ok"])
        self.assertEqual(result["result"]["results"]["AMS01"]["error"], "schedule_input_unavailable")
        hub.execute.assert_not_called()

    def test_direct_schedule_group_dispatch_helper_remains_supported(self):
        hub = mock.Mock()
        hub.execute.return_value = {"ok": True}
        with mock.patch.object(runtime, "get_device_hub", return_value=hub):
            self.assertTrue(runtime._run_schedule_hub_command("COMBINED", 2)["ok"])
        hub.execute.assert_called_once_with("COMBINED", "mode", {"mode": 2})

    def test_manual_explicit_device_schedule_captures_fresh_restore_mode(self):
        from app.schedule_execution import ScheduleExecution
        from types import SimpleNamespace
        profile = runtime.get_device_hub().registry.require("AMS01")
        hub = mock.Mock()
        hub.registry.targets.return_value = [profile]
        hub.registry.require.return_value = profile
        hub.cached.return_value = {"online": True, "ams_code": 35, "source_key": "synthetic",
                                   "timestamp": "2026-09-01T00:00:00+00:00"}
        hub.execute.return_value = {"ok": True}
        target = SimpleNamespace(transport="modbus", endpoint="fixture.invalid", channel=1,
                                 unit_id=1, mapping={}, encoding={})
        with (
            mock.patch.object(runtime, "schedules_store", [{
                "id": "fresh", "mode": 3, "remote_id": "AMS01", "active": True,
                "start_time": "00:00", "end_time": "23:59", "repeat": "once",
            }]),
            mock.patch.object(runtime, "_schedule_execution", ScheduleExecution()),
            mock.patch.object(runtime, "get_device_hub", return_value=hub),
            mock.patch.object(runtime, "_resolve_command_target", return_value=target),
            mock.patch.object(runtime, "_schedule_target", return_value="AMS01"),
            mock.patch.object(runtime.time, "time", return_value=1788220801),
            mock.patch.object(runtime, "save_schedules"),
        ):
            result = runtime.execute_schedule("fresh")
            self.assertTrue(result["ok"])
            self.assertEqual(result["run"]["targets"][0]["return_mode"], 2)
            self.assertEqual(runtime.schedules_store[0]["status"], runtime.STATUS_RUNNING)

    def test_hub_live_payload_does_not_call_legacy_fetch(self):
        class FakeHub:
            def read_all(self):
                raise AssertionError("observer must not collect")

            def cached(self):
                return {"ok": True, "scope": "hub", "devices": [], "combined": {}}

        with (
            mock.patch.object(runtime, "get_device_hub", return_value=FakeHub()),
            mock.patch.object(runtime, "fetch_process_data_web", side_effect=AssertionError("legacy fetch called")),
        ):
            payload = runtime._hub_live_payload()
        self.assertEqual(payload["scope"], "hub")
        self.assertIn("energy_config", payload)
        self.assertIn("save_interval_s", payload)

    def test_modbus_output_control_uses_wire_low_byte_when_base_swap_is_disabled(self):
        raw_input = [0] * 18
        raw_output = [0x0004] + [0] * 8
        with mock.patch.dict(runtime.config_store, {"modbus_process_byte_swap": False}):
            decoded = runtime._decode_modbus_exa1("AMS01", raw_input, raw_output)
        self.assertTrue(decoded["air_nc"])
        self.assertFalse(decoded["air_no"])
        self.assertFalse(decoded["standby_signal"])

    def test_modbus_output_control_uses_wire_high_byte_when_base_swap_is_enabled(self):
        raw_input = [0] * 18
        raw_output = [0x0400] + [0] * 8
        with mock.patch.dict(runtime.config_store, {"modbus_process_byte_swap": True}):
            decoded = runtime._decode_modbus_exa1("AMS01", raw_input, raw_output)
        self.assertTrue(decoded["air_nc"])
        self.assertFalse(decoded["air_no"])

    def test_modbus_output_control_writes_and_verifies_wire_low_byte_without_base_swap(self):
        mapping = {"AMS01": {"device_kind": "exa1", "output_start": 0}}
        with mock.patch.dict(runtime.config_store, {"modbus_process_byte_swap": False}):
            with mock.patch.object(runtime, "MODBUS_AMS_CHANNEL_MAP", mapping):
                with mock.patch.object(runtime, "_modbus_read_registers", side_effect=[[0x0000], [0x0004]]):
                    with mock.patch.object(runtime, "_modbus_write_registers") as writer:
                        result = runtime._modbus_set_bit("AMS01", 2, True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["readback_output_control"], 0x0400)
        writer.assert_called_once_with(0, [0x0004], remote_id="AMS01")

    def test_modbus_output_control_writes_and_verifies_wire_high_byte_with_base_swap(self):
        mapping = {"AMS01": {"device_kind": "exa1", "output_start": 0}}
        with mock.patch.dict(runtime.config_store, {"modbus_process_byte_swap": True}):
            with mock.patch.object(runtime, "MODBUS_AMS_CHANNEL_MAP", mapping):
                with mock.patch.object(runtime, "_modbus_read_registers", side_effect=[[0x0000], [0x0400]]):
                    with mock.patch.object(runtime, "_modbus_write_registers") as writer:
                        result = runtime._modbus_set_bit("AMS01", 2, True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified"])
        writer.assert_called_once_with(0, [0x0400], remote_id="AMS01")
    def test_modbus_topology_fetch_decodes_exa1_and_remote_io(self):
        class FakeClient:
            def read_holding_registers(self, address, count):
                if (address, count) == (2048, 5):
                    return [0, 0, 0x2006, 0, 0]
                if (address, count) == (2053, 36):
                    return [0] * 36
                if (address, count) == (0, 18):
                    return [0] * 18
                if (address, count) == (2269, 4):
                    return [0x0102, 0x0304, 0x0506, 0x0708]
                if (address, count) == (108, 4):
                    return [0x1112, 0x1314, 0x1516, 0x1718]
                raise AssertionError(f"unexpected read: {address}/{count}")

        cache = copy.deepcopy(runtime._modbus_live_cache)
        cache_at = runtime._modbus_live_at
        try:
            with mock.patch.object(runtime, "_modbus_client_for", return_value=FakeClient()):
                result = runtime.fetch_modbus_remotes(True)
        finally:
            runtime._modbus_live_cache = cache
            runtime._modbus_live_at = cache_at
        self.assertEqual(sorted(result), ["AMS01", "AMS02", "IO13"])
        self.assertTrue(result["AMS01"]["device_connected"])
        self.assertEqual(result["IO13"]["process_input_hex"], ["01", "02", "03", "04", "05", "06", "07", "08"])
        self.assertEqual(result["IO13"]["modbus_map"]["input_start"], 2269)

    def test_history_remote_filter_helper(self):
        specific_sql, specific_params = runtime._history_remote_filter("AMS01")
        self.assertEqual(specific_sql, "AND remote_id=?")
        self.assertEqual(specific_params, ("AMS01",))
        for token in ["", "ALL", "ALL DEVICES", "all", "  all  "]:
            all_sql, all_params = runtime._history_remote_filter(token)
            self.assertEqual(all_sql, "AND remote_id NOT IN (?,?)")
            self.assertEqual(all_params, ("COMBINED", "IO13"))

    def test_query_history_all_devices_sums_real_rows_and_excludes_combined_io13(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_dir = Path(temp_dir)
            with mock.patch.object(runtime, "DB_DIR", db_dir):
                with runtime.db_migration_lock:
                    runtime._migrated_dbs.clear()
                conn = runtime.get_db_conn(runtime.datetime(2026, 8, 1))
                conn.executemany(
                    """
                    INSERT INTO ams_log
                      (timestamp,remote_id,pressure,temperature,flow,accumulated,
                       raw_accumulated,delta_flow,reset_detected,ams_status,ams_code,diagnostic)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        ("2026-08-01T00:00:00", "AMS01", 0.6, 28.0, 10.0, 100, 100.0, 10.0, 0, "RUN", 17, "test"),
                        ("2026-08-01T00:00:05", "AMS02", 0.6, 28.0, 5.0, 50, 50.0, 5.0, 0, "RUN", 17, "test"),
                        # A stored COMBINED aggregate row landed here by _periodic_save_loop().
                        # If the ALL filter ever regresses back to "no remote_id filter",
                        # this row alone would double the summed usage below.
                        ("2026-08-01T00:00:05", "COMBINED", 0.6, 28.0, 15.0, 150, 150.0, 15.0, 0, "Combined", 17, "test"),
                        # IO13 is a remote-I/O module, not an air-flow device; it must never
                        # contribute to a plant-wide usage total.
                        ("2026-08-01T00:00:05", "IO13", 0.0, 0.0, 0.0, 0, 0.0, 9999.0, 0, "RUN", 17, "test"),
                    ],
                )
                conn.commit()
                conn.close()
                data = runtime.query_history("2026-08-01", "2026-08-01", "day", "accumulated", "ALL")
        self.assertEqual(len(data), 1)
        self.assertAlmostEqual(data[0]["usage"], 15.0)  # 10.0 (AMS01) + 5.0 (AMS02) only
        self.assertEqual(data[0]["count"], 2)

    def test_raw_csv_all_devices_excludes_combined_and_io13(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_dir = Path(temp_dir)
            with mock.patch.object(runtime, "DB_DIR", db_dir):
                with runtime.db_migration_lock:
                    runtime._migrated_dbs.clear()
                conn = runtime.get_db_conn(runtime.datetime(2026, 8, 1))
                conn.executemany(
                    """
                    INSERT INTO ams_log
                      (timestamp,remote_id,pressure,temperature,flow,accumulated,
                       raw_accumulated,delta_flow,reset_detected,ams_status,ams_code,diagnostic)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        ("2026-08-01T00:00:00", "AMS01", 0.6, 28.0, 10.0, 1, 1.0, 1.0, 0, "RUN", 17, "test"),
                        ("2026-08-01T00:00:01", "AMS02", 0.6, 28.0, 11.0, 2, 2.0, 1.0, 0, "RUN", 17, "test"),
                        ("2026-08-01T00:00:02", "COMBINED", 0.6, 28.0, 21.0, 3, 3.0, 2.0, 0, "Combined", 17, "test"),
                        ("2026-08-01T00:00:03", "IO13", 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0, "RUN", 17, "test"),
                    ],
                )
                conn.commit()
                conn.close()
                csv_text = "".join(runtime.iter_export_csv("2026-08-01", "2026-08-01", "ALL"))
        self.assertIn("AMS01", csv_text)
        self.assertIn("AMS02", csv_text)
        self.assertNotIn("COMBINED", csv_text)
        self.assertNotIn("IO13", csv_text)

class RuntimeSafetyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))
        for name in ("_modbus_live_cache", "_modbus_live_at", "_modbus_live_error",
                     "device_connected", "_modbus_sequence", "_dio_link_runtime"):
            patcher = mock.patch.object(runtime, name, copy.deepcopy(getattr(runtime, name)))
            patcher.start()
            self.addCleanup(patcher.stop)
        runtime._dio_link_runtime.clear()

    def fetch_with_diagnostics(self, diagnostics):
        client = mock.Mock()
        def read(address, count):
            if (address, count) == (2048, 5):
                if isinstance(diagnostics, Exception):
                    raise diagnostics
                return diagnostics
            return [0] * count
        client.read_holding_registers.side_effect = read
        with mock.patch.object(runtime, "_modbus_client_for", return_value=client):
            return runtime.fetch_modbus_remotes(True), client

    def test_wireless_diagnostics_timeout_fails_closed_for_both_device_kinds(self):
        devices, client = self.fetch_with_diagnostics(TimeoutError("mock diagnostics timeout"))
        self.assertGreater(client.read_holding_registers.call_count, 1)
        self.assertEqual(set(devices), {"AMS01", "AMS02", "IO13"})
        for device in devices.values():
            self.assertFalse(device["online"])
            self.assertFalse(device["device_connected"])
            self.assertIsNone(device["wireless_connected"])
            self.assertIn("mock diagnostics timeout", device["error"])
        self.assertFalse(runtime.device_connected)
        self.assertIn("mock diagnostics timeout", runtime._modbus_live_error)

    def test_wireless_short_diagnostics_fails_closed(self):
        for words in ([], [0, 0], [0, 0, 0x2006]):
            with self.subTest(words=words):
                devices, _ = self.fetch_with_diagnostics(words)
                for device in devices.values():
                    self.assertFalse(device["online"])
                    self.assertIn("Incomplete wireless diagnostics", device["error"])

    def test_wireless_unknown_channel_fails_closed(self):
        with mock.patch.object(runtime, "_read_gateway_wireless_diagnostics", return_value={"channel_connected": {}}):
            devices, _ = self.fetch_with_diagnostics([])
        for device in devices.values():
            self.assertFalse(device["online"])
            self.assertIn("status unknown", device["error"])

    def test_wireless_valid_connected_and_disconnected_channels(self):
        devices, _ = self.fetch_with_diagnostics([0, 0, 0x2002, 0, 0])
        for device_id, connected in (("AMS01", True), ("AMS02", False), ("IO13", True)):
            self.assertEqual(devices[device_id]["online"], connected)
            self.assertEqual(devices[device_id]["device_connected"], connected)
            self.assertEqual(devices[device_id]["wireless_connected"], connected)
        self.assertIsNone(runtime._modbus_live_error)

    def test_nonadvanced_diagnostics_preserves_process_read_connectivity(self):
        from dataclasses import replace
        topology = copy.deepcopy(runtime.get_exw1_topology())
        for mode in ("none", "basic"):
            with self.subTest(mode=mode):
                for gateway_id, gateway in topology.gateways.items():
                    topology.gateways[gateway_id] = replace(gateway, diagnostics=mode)
                with mock.patch.object(runtime, "get_exw1_topology", return_value=topology):
                    devices, client = self.fetch_with_diagnostics(AssertionError("diagnostics must not be read"))
                self.assertNotIn(mock.call(2048, 5), client.read_holding_registers.call_args_list)
                for device in devices.values():
                    self.assertTrue(device["online"])
                    self.assertIsNone(device["wireless_connected"])

    def apply_dio(self, hub, now, code=1, force=False):
        fresh = {"online": True, "timestamp": "2026-09-01T00:00:00+00:00"}
        payload = {"devices": [{**fresh, "device_id": "IO13", "dio_code": code},
                               {**fresh, "device_id": "AMS01"}]}
        with (mock.patch.dict(runtime.config_store, {"dio_links": {"AMS01": {"enabled": True}}}),
              mock.patch.object(runtime, "get_device_hub", return_value=hub),
              mock.patch.object(runtime, "_dio_transition_supported", return_value=True),
              mock.patch.object(runtime.time, "monotonic", return_value=now),
              mock.patch.object(runtime.time, "time", return_value=1788220801)):
            return runtime._apply_dio_links(payload, force_target="AMS01" if force else None)

    def test_dio_failure_throttles_same_and_changed_codes_until_three_seconds(self):
        hub = mock.Mock()
        hub.execute.return_value = {"ok": False, "error": "mock write timeout"}
        self.apply_dio(hub, 0.0)
        self.assertEqual(hub.execute.call_count, 1)
        self.apply_dio(hub, 0.1)
        self.apply_dio(hub, 2.999, code=2)
        self.assertEqual(hub.execute.call_count, 1)
        hub.execute.return_value = {"ok": True, "results": {"AMS01": {"ok": True}}}
        self.apply_dio(hub, 3.0, code=2)
        self.assertEqual(hub.execute.call_count, 2)
        self.assertEqual(runtime._dio_link_runtime["AMS01"]["last_applied_code"], 2)
        self.apply_dio(hub, 3.1, code=2)
        self.assertEqual(hub.execute.call_count, 2)
        self.apply_dio(hub, 3.2, code=1)
        self.assertEqual(hub.execute.call_count, 3)

    def test_dio_force_bypasses_failed_attempt_throttle(self):
        hub = mock.Mock()
        hub.execute.return_value = {"ok": False, "results": {"AMS01": {"ok": False, "error": "timeout"}}}
        self.apply_dio(hub, 100)
        self.apply_dio(hub, 100.1, code=2, force=True)
        self.assertEqual(hub.execute.call_count, 2)
        self.apply_dio(hub, 103.0, code=1)
        self.assertEqual(hub.execute.call_count, 2)
        self.apply_dio(hub, 103.1, code=1)
        self.assertEqual(hub.execute.call_count, 3)

    def test_settings_invalid_later_value_never_starts_service(self):
        for invalid in (1051, -1, "not-an-integer"):
            with self.subTest(invalid=invalid), mock.patch.object(runtime, "_exa1_service") as service:
                with self.assertRaises(ValueError):
                    runtime.write_modbus_exa1_settings("AMS01", {"operation_kpa": "500", "standby_kpa": invalid})
                service.assert_not_called()

    def test_settings_valid_batch_normalizes_and_reads_back(self):
        with mock.patch.object(runtime, "_exa1_service", side_effect=[None, None, 500, 1]) as service:
            result = runtime.write_modbus_exa1_settings("AMS01", {
                "operation_kpa": "500", "ar_itv_active": "ignored", "unknown": "ignored",
                "standby_kpa": None, "isolation_enabled": "1"})
        self.assertEqual(service.call_args_list, [
            mock.call("AMS01", 0x65, write_value=500, value_type="u16"),
            mock.call("AMS01", 0x6C, write_value=1, value_type="u8"),
            mock.call("AMS01", 0x65, value_type="u16"),
            mock.call("AMS01", 0x6C, value_type="u8")])
        self.assertEqual(result["written"], ["operation_kpa", "isolation_enabled"])
        self.assertEqual(result["settings"], {"operation_kpa": 500, "isolation_enabled": 1})

    def test_settings_readonly_only_does_not_call_service(self):
        with mock.patch.object(runtime, "_exa1_service") as service:
            result = runtime.write_modbus_exa1_settings("AMS01", {"ar_itv_active": "invalid"})
        service.assert_not_called()
        self.assertEqual(result["written"], [])
        self.assertTrue(result["ok"])

    def service_response(self, kind, size, words=112, write=False):
        def response(*args, **kwargs):
            data = [0] * words
            if words > 0: data[0] = runtime._modbus_sequence
            if words > 2: data[2] = 0xB3 if write else 0xB2
            if words > 8: data[8] = size
            if words > 9: data[9] = 0x1234
            return data
        with (mock.patch.object(runtime, "_modbus_write_registers"),
              mock.patch.object(runtime, "_modbus_read_registers", side_effect=response)):
            return runtime._exa1_service("AMS01", 101, value_type=kind, write_value=1 if write else None)

    def test_service_rejects_truncated_payloads_and_headers(self):
        for kind, size, words in (("u8", 0, 112), ("u16", 0, 112), ("u16", 1, 112),
                                  ("u8", 3, 10), ("u16", 3, 10), ("u16", 207, 112),
                                  ("u8", 1, 9), ("u16", 2, 8), ("u16", 2, 2), ("u8", 1, 0)):
            with self.subTest(kind=kind, size=size, words=words):
                with self.assertRaisesRegex(ValueError, "Truncated BMTAC"):
                    self.service_response(kind, size, words)

    def test_service_valid_u8_u16_and_write_ack(self):
        self.assertEqual(self.service_response("u8", 1, 10), 0x12)
        self.assertEqual(self.service_response("u16", 2, 10), 0x1234)
        self.assertEqual(self.service_response("u16", 2), 0x1234)
        self.assertIsNone(self.service_response("u16", 0, write=True))


if __name__ == "__main__":
    unittest.main()






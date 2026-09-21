"""Actual-module transaction contracts; run only through the protected runner."""
from concurrent.futures import ThreadPoolExecutor
import copy
import threading
import unittest
from unittest.mock import patch

from offline_fixtures import guarded_runtime, isolated_runtime
from test_local_access import finish_immediate

runtime = guarded_runtime()


class CandidateTransactionTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))
        self.save = self.enterContext(patch.object(runtime, "save_config"))
        self.state = self.enterContext(patch.object(runtime, "save_runtime_state"))
        self.start = self.enterContext(patch.object(runtime, "start_node_worker"))
        self.stop = self.enterContext(patch.object(runtime, "stop_node_worker"))
        self.restart = self.enterContext(patch.object(runtime, "restart_node_worker"))
        self.connect = self.enterContext(patch.object(runtime, "try_connect"))
        self.transport = self.enterContext(patch.object(runtime, "fetch_modbus_remotes"))

    def assert_no_side_effects(self):
        for mock in (self.save, self.state, self.start, self.stop, self.restart, self.connect, self.transport):
            mock.assert_not_called()

    def test_invalid_profile_rejected_at_durable_boundary(self):
        before = copy.deepcopy(runtime.config_store)
        generation = runtime.current_config_generation()
        response = runtime.api_hub_update_devices(runtime.HubProfilesRequest(
            device_profiles={"BAD": {"transport": "web"}}))
        self.assertFalse(response["ok"])
        self.assertEqual(runtime.config_store, before)
        self.assertEqual(runtime.current_config_generation(), generation)
        self.assert_no_side_effects()

    def test_endpoint_change_cannot_break_previously_healthy_profile(self):
        runtime.config_store.update(device_profiles={"AMS00": {
            "transport": "opcua", "endpoint": runtime.config_store["opcua_endpoint"]}},
            device_profiles_explicit=True)
        response = finish_immediate(runtime.update_connection(runtime.ConnectionConfig(ams_host="https://other.invalid")))
        self.assertFalse(response["ok"])
        self.assert_no_side_effects()

    def test_topology_removal_cannot_strand_healthy_modbus_profile(self):
        runtime.config_store.update(device_profiles={"AMS01": {"transport": "modbus"}},
                                    device_profiles_explicit=True, data_source="modbus")
        response = runtime.api_hub_update_topology(runtime.HubTopologyRequest(modbus_gateways={}))
        self.assertFalse(response["ok"])
        self.assert_no_side_effects()

    def test_unchanged_quarantine_survives_partial_repair(self):
        raw = {"BAD1": {"transport": "web"}, "BAD2": {"transport": "web"}}
        runtime.config_store.update(device_profiles=copy.deepcopy(raw), device_profiles_explicit=True)
        fixed = {"BAD1": {"transport": "simulator"}, "BAD2": raw["BAD2"]}
        runtime.update_config_values(device_profiles=fixed)
        self.assertEqual(runtime.config_store["device_profiles"], fixed)
        self.save.assert_called_once()
        self.state.assert_not_called()
        with self.assertRaises(ValueError):
            runtime.update_config_values(device_profiles={**fixed, "BAD2": {"transport": "web", "name": "changed"}})
        self.assertEqual(self.save.call_count, 1)

    def test_config_only_does_not_create_missing_state_store(self):
        with patch.object(type(runtime.RUNTIME_STATE_FILE), "exists", return_value=False):
            runtime.update_config_values(energy_price_per_kwh=987.0)
        self.save.assert_called_once()
        self.state.assert_not_called()

    def test_durable_failure_preserves_live_and_generation(self):
        before = copy.deepcopy(runtime.config_store)
        generation = runtime.current_config_generation()
        self.save.side_effect = OSError("synthetic replacement failure")
        with self.assertRaises(OSError):
            runtime.update_config_values(ams_password="synthetic-change")
        self.assertEqual(runtime.config_store, before)
        self.assertEqual(runtime.current_config_generation(), generation)
        self.state.assert_not_called()

    def test_state_only_inside_command_does_not_transition(self):
        generation = runtime.current_config_generation()
        with runtime._command_generation():
            runtime.update_config_values(dashboard_total_flow_l=987.0)
        self.state.assert_called_once()
        self.save.assert_not_called()
        self.assertEqual(runtime.current_config_generation(), generation)

    def test_state_failure_preserves_live(self):
        before = copy.deepcopy(runtime.config_store)
        self.state.side_effect = OSError("synthetic state failure")
        with self.assertRaises(OSError):
            runtime.update_config_values(dashboard_total_flow_l=987.0)
        self.assertEqual(runtime.config_store, before)
        self.save.assert_not_called()

    def test_mixed_change_uses_joint_journal(self):
        with patch.object(runtime.ConfigJournal, "commit") as commit:
            runtime.update_config_values(ams_password="synthetic-change", dashboard_total_flow_l=987.0)
        commit.assert_called_once()
        self.assertEqual(runtime.config_store["dashboard_total_flow_l"], 987.0)
        self.save.assert_not_called()
        self.state.assert_not_called()

    def test_non_none_baseline_source_change_uses_joint_journal(self):
        runtime.config_store.update(data_source="opcua", dashboard_last_raw_accumulated_l=100.0)
        with patch.object(runtime.ConfigJournal, "commit") as commit:
            response = runtime.update_data_source_config(runtime.DataSourceConfig(data_source="demo"))
        self.assertTrue(response["ok"], response)
        commit.assert_called_once()
        self.assertIsNone(runtime.config_store["dashboard_last_raw_accumulated_l"])

    def test_non_none_baseline_modbus_endpoint_change_uses_joint_journal(self):
        runtime.config_store["dashboard_last_raw_accumulated_l"] = 100.0
        with patch.object(runtime.ConfigJournal, "commit") as commit:
            response = runtime.update_modbus_config(runtime.ModbusConnectionConfig(host="changed.invalid"))
        self.assertTrue(response["ok"], response)
        commit.assert_called_once()
        self.assertIsNone(runtime.config_store["dashboard_last_raw_accumulated_l"])

    def test_legacy_baseline_is_not_source_keyed(self):
        runtime.config_store.update(dashboard_last_raw_accumulated_l=100.0, dashboard_total_flow_l=0.0)
        result = runtime.apply_usage_tracking({"accumulated_flow_l": 500.0}, persist=False)
        self.assertEqual(result["delta_flow_l"], 400.0)
        self.assert_no_side_effects()

    def test_builder_observes_latest_state_after_command_drains(self):
        seen = []
        errors = []
        started = threading.Event()
        def update():
            started.set()
            try:
                runtime.update_config_values(_build_changes=lambda current: (
                    seen.append(current["dashboard_total_flow_l"]) or {"ams_password": "synthetic-change"}))
            except BaseException as exc:
                errors.append(exc)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with runtime._command_generation():
                future = executor.submit(update)
                self.assertTrue(started.wait(2))
                runtime.update_config_values(dashboard_total_flow_l=987.0)
            future.result(timeout=2)
        self.assertEqual(errors, [])
        self.assertEqual(seen, [987.0])
        self.assertEqual(runtime.config_store["dashboard_total_flow_l"], 987.0)

    def test_explicit_empty_topology_is_not_repopulated_by_modbus_form(self):
        runtime.config_store.update(modbus_gateways={}, modbus_gateways_explicit=True)
        response = runtime.update_modbus_config(runtime.ModbusConnectionConfig(host="changed.invalid"))
        self.assertFalse(response["ok"])
        self.assertEqual(runtime.config_store["modbus_gateways"], {})
        self.assert_no_side_effects()

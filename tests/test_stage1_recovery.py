"""Actual-module target/recovery regressions; transports and persistence are mocks."""
import copy
import unittest
from unittest.mock import Mock, patch, call

from offline_fixtures import guarded_runtime, isolated_runtime
from app.connection_context import ConnectionContextManager
from app.device_hub import DeviceProfile, DeviceRegistry, DeviceHub
from app.exw1_topology import load_exw1_topology
from app.hub_adapters import OpcuaHubAdapter

runtime = guarded_runtime()


class Stage1RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))

    def test_all_invalid_profiles_remain_recovery_only_and_preserve_raw(self):
        raw = {"BROKEN": {"transport": "web", "enabled": False}, "BAD_SHAPE": [1, 2]}
        with patch.dict(runtime.config_store, {"device_profiles": raw}), patch.object(runtime, "_modbus_client_for") as client, patch.object(runtime, "_fetch_worker_data") as worker:
            hub = runtime.get_device_hub()
            self.assertEqual(hub.read_all()["devices"], [])
            api = runtime.api_hub_devices()
            self.assertTrue(api["recovery"]["recovery_only"])
            self.assertEqual(api["raw_device_profiles"], raw)
            self.assertEqual({row["device_id"] for row in api["recovery"]["quarantined_profiles"]}, set(raw))
            self.assertEqual(runtime.fetch_modbus_remotes(True), {})
            self.assertEqual(runtime.config_store["device_profiles"], raw)
            client.assert_not_called()
            worker.assert_not_called()

    def test_bad_profile_shape_identifier_and_enabled_quarantine_not_coerce(self):
        for key, value in (("X' onclick='bad", {}), ("ß", {}), ("A" * 65, {}), ("BAD", {"enabled": "false"}), ("BAD", {"enabled": 0}), ("BAD", {"metadata": []}), ("BAD", {"channel": 1.5}), ("BAD", None)):
            with self.subTest(key=key, value=value):
                cfg = {"device_profiles": {key: value}}
                with self.assertRaises(ValueError):
                    DeviceRegistry.from_config(cfg)
                registry = DeviceRegistry.from_config(cfg, strict=False)
                self.assertEqual(registry.all(), [])
                self.assertEqual(registry.quarantined[0]["raw"], value)
        for raw in (None, [], "broken"):
            with self.subTest(raw=raw):
                registry = DeviceRegistry.from_config({"device_profiles": raw}, strict=False)
                self.assertEqual(registry.all(), [])
                self.assertEqual(registry.quarantined[0]["raw"], raw)

    def test_alias_conflicts_quarantine_both_claimants(self):
        raw = {"AMS01": {"transport": "opcua"}, "AMS_01": {"transport": "opcua"}}
        registry = DeviceRegistry.from_config({"device_profiles": raw}, strict=False)
        self.assertEqual(registry.all(), [])
        self.assertEqual(len(registry.quarantined), 2)

    def test_mixed_transport_ids_are_not_opcua_alias_conflicts(self):
        raw = {
            "AMS01": {"transport": "modbus", "channel": 1},
            "AMS02": {"transport": "modbus", "channel": 2},
            "AMS_01": {"transport": "opcua"},
            "AMS_02": {"transport": "opcua"},
        }
        before = copy.deepcopy(raw)
        for strict in (True, False):
            with self.subTest(strict=strict):
                registry = DeviceRegistry.from_config({"device_profiles": raw}, strict=strict)
                self.assertEqual({p.device_id for p in registry.all()}, set(raw))
                self.assertEqual(registry.quarantined, [])
        self.assertEqual(raw, before)
        with patch.dict(runtime.config_store, {"device_profiles": raw}):
            registry = runtime.get_device_hub().registry
            self.assertTrue(set(raw).issubset({p.device_id for p in registry.all()}))
            self.assertEqual(registry.require("AMS01").transport, "modbus")
            self.assertEqual(registry.require("AMS02").transport, "modbus")

    def test_exact_id_conflicts_across_transports_still_rejected(self):
        raw = {"ams01": {"transport": "modbus"}, "AMS01": {"transport": "opcua"}}
        with self.assertRaises(ValueError):
            DeviceRegistry.from_config({"device_profiles": raw})
        registry = DeviceRegistry.from_config({"device_profiles": raw}, strict=False)
        self.assertEqual(registry.all(), [])
        self.assertEqual({p["device_id"] for p in registry.quarantined}, set(raw))

    def test_invalid_gateway_isolated_without_address_guesses_or_config_rewrite(self):
        healthy = copy.deepcopy(runtime.config_store["modbus_gateways"]["FIXTURE-EXW1"])
        broken = copy.deepcopy(healthy)
        for slot in broken["slots"]:
            if slot.get("device_id"):
                slot["device_id"] = "BAD_" + slot["device_id"]
        broken["slots"][0]["input_bytes"] = 35
        gateways = {"GOOD": healthy, "BROKEN": broken}
        before = copy.deepcopy(gateways)
        with patch.dict(runtime.config_store, {"modbus_gateways": gateways, "data_source": "modbus"}):
            topology = runtime.get_exw1_topology()
            self.assertEqual(set(topology.gateways), {"GOOD"})
            self.assertEqual(topology.recovery()["quarantined_gateways"][0]["raw"], broken)
            api = runtime.api_hub_topology()
            self.assertEqual(api["raw_modbus_gateways"], before)
            self.assertNotIn("BAD_AMS01", api["channel_map"])
            self.assertEqual([p.device_id for p in runtime.get_device_hub().registry.all()], ["AMS01", "AMS02", "IO13"])
            with patch.object(runtime._modbus_client_pool, "get") as client:
                with self.assertRaises((KeyError, ValueError)):
                    runtime._modbus_client_for(remote_id="BAD_AMS01")
                client.assert_not_called()
            self.assertEqual(runtime.config_store["modbus_gateways"], before)

    def test_all_invalid_topology_is_recovery_only_including_stale_profiles(self):
        broken = copy.deepcopy(runtime.config_store["modbus_gateways"])
        broken["FIXTURE-EXW1"]["slots"][0]["channel"] = 99
        for profiles in ({}, {"AMS01": {"transport": "modbus", "enabled": True}}):
            with self.subTest(profiles=profiles), patch.dict(runtime.config_store, {"data_source": "modbus", "modbus_gateways": broken, "device_profiles": profiles}), patch.object(runtime, "_modbus_client_for") as client:
                self.assertEqual(runtime.get_device_hub().read_all()["devices"], [])
                self.assertEqual(runtime.fetch_modbus_remotes(True), {})
                self.assertTrue(runtime.api_hub_devices()["recovery"]["recovery_only"])
                self.assertIsNone(runtime.get_modbus_config()["host"])
                client.assert_not_called()

    def test_invalid_topology_shapes_do_not_fall_back(self):
        for gateways in (None, [], "broken", {"BROKEN": None}):
            with self.subTest(gateways=gateways):
                topology = load_exw1_topology({"modbus_gateways": gateways}, strict=False)
                self.assertEqual(topology.gateways, {})
                self.assertTrue(topology.recovery()["required"])
                with self.assertRaises(ValueError):
                    load_exw1_topology({"modbus_gateways": gateways})

    def test_new_profile_batch_invalid_rejects_before_save_or_start(self):
        candidates = [
            {"AMS00": {"transport": "opcua"}, "BAD": {"transport": "web"}},
            {"AMS00": {"transport": "opcua", "endpoint": "opc.tcp://other.invalid:4840"}},
            {"AMS00": {"transport": "opcua", "enabled": "false"}},
            {"MISSING": {"transport": "modbus"}},
        ]
        for profiles in candidates:
            with self.subTest(profiles=profiles), patch.object(runtime, "save_config") as save, patch.object(runtime, "save_runtime_state") as state, patch.object(runtime, "start_node_worker") as worker, patch.object(runtime, "_modbus_client_for") as client:
                before = copy.deepcopy(runtime.config_store)
                generation = runtime.current_config_generation()
                self.assertFalse(runtime.api_hub_update_devices(runtime.HubProfilesRequest(device_profiles=profiles))["ok"])
                save.assert_not_called()
                state.assert_not_called()
                self.assertEqual(runtime.config_store, before)
                self.assertEqual(runtime.current_config_generation(), generation)
                worker.assert_not_called()
                client.assert_not_called()

    def test_empty_profile_save_is_authoritative_without_legacy_fallback(self):
        with (patch.object(runtime, "save_config") as save,
              patch.object(runtime, "save_runtime_state") as state,
              patch.object(runtime, "_config_journal") as journal,
              patch.object(runtime, "start_node_worker") as worker):
            generation = runtime.current_config_generation()
            self.assertTrue(runtime.api_hub_update_devices(runtime.HubProfilesRequest(device_profiles={}))["ok"])
            self.assertEqual(runtime.get_device_hub().registry.all(), [])
            # Removal ends measurement continuity; route and epoch now commit together.
            journal.return_value.commit.assert_called_once()
            config, state_values = journal.return_value.commit.call_args.args
            self.assertEqual(config["device_profiles"], {})
            self.assertTrue(config["device_profiles_explicit"])
            self.assertEqual({k: v for k, v in runtime.config_store.items() if k not in runtime.RUNTIME_STATE_KEYS}, config)
            self.assertEqual({k: runtime.config_store.get(k) for k in runtime.RUNTIME_STATE_KEYS}, state_values)
            self.assertTrue(state_values["measurement_epochs"])
            save.assert_not_called()
            self.assertEqual(runtime.current_config_generation(), generation + 1)
            state.assert_not_called()
            worker.assert_not_called()

    def test_topology_disabled_and_profile_disabled_each_prevent_resurrection(self):
        for disabled_in in ("profile", "slot"):
            gateways = copy.deepcopy(runtime.config_store["modbus_gateways"])
            if disabled_in == "slot":
                gateways["FIXTURE-EXW1"]["slots"][0]["enabled"] = False
            raw = {"AMS01": {"transport": "modbus", "enabled": disabled_in == "slot"}}
            with self.subTest(disabled_in=disabled_in), patch.dict(runtime.config_store, {"data_source": "modbus", "device_profiles": raw, "modbus_gateways": gateways}), patch.object(runtime, "_modbus_client_for") as client:
                registry = runtime.get_device_hub().registry
                self.assertFalse(registry.get("AMS01").enabled)
                self.assertEqual(registry.targets("COMBINED"), [])
                self.assertFalse(runtime._legacy_hub_command("AMS01", "mode", {"mode": 3})["ok"])
                self.assertEqual(runtime.fetch_modbus_remotes(True), {})
                self.assertEqual(runtime.api_hub_devices()["devices"][0]["capabilities"]["telemetry"], False)
                client.assert_not_called()

    def test_disabled_middle_slot_is_not_in_modbus_block_or_short_cache(self):
        gateway = copy.deepcopy(runtime.config_store["modbus_gateways"]["FIXTURE-EXW1"])
        gateway["slots"][2] = {"channel": 3, "kind": "exa1", "device_id": "AMS03", "model": 40, "input_bytes": 36, "output_bytes": 18}
        profiles = {f"AMS{i:02d}": {"transport": "modbus", "enabled": i != 2} for i in (1, 2, 3)}
        client = Mock()
        client.read_holding_registers.side_effect = lambda address, count: [0, 0, 0x200E, 0, 0] if (address, count) == (2048, 5) else [0] * count
        with patch.dict(runtime.config_store, {"modbus_gateways": {"FIXTURE-EXW1": gateway}, "device_profiles": profiles}), patch.object(runtime, "_modbus_client_for", return_value=client):
            rows = runtime.fetch_modbus_remotes(True)
            self.assertEqual(set(rows), {"AMS01", "AMS03"})
            calls = [item.args for item in client.read_holding_registers.call_args_list]
            self.assertIn((2053, 18), calls)
            self.assertIn((2089, 18), calls)
            self.assertNotIn((2053, 54), calls)
            self.assertNotIn((2071, 18), calls)
            self.assertNotIn((9, 9), calls)
            self.assertEqual(runtime.get_device_hub().read_all()["combined"]["device_count"], 2)
            runtime._modbus_live_cache["AMS02"] = {"online": True}
            self.assertNotIn("AMS02", runtime.fetch_modbus_remotes())

    def test_modbus_connection_merge_preserves_disabled_and_invalid_rejects_early(self):
        with patch.dict(runtime.config_store, {"device_profiles": {"AMS01": {"transport": "modbus", "enabled": False}}}), patch.object(runtime, "save_config") as save, patch.object(runtime, "save_runtime_state") as state, patch.object(runtime, "stop_node_worker") as stop, patch.object(runtime, "fetch_modbus_remotes", return_value={}) as fetch:
            generation = runtime.current_config_generation()
            self.assertTrue(runtime.update_modbus_config(runtime.ModbusConnectionConfig(host="replacement.invalid"))["ok"])
            save.assert_called_once()
            self.assertFalse(save.call_args.args[0]["device_profiles"]["AMS01"]["enabled"])
            registry = runtime.get_device_hub().registry
            self.assertIsNotNone(registry.get("AMS01"))
            self.assertFalse(registry.get("AMS01").enabled)
            with self.assertRaises(KeyError):
                registry.require("AMS01")
            self.assertEqual(runtime.config_store, save.call_args.args[0])
            self.assertEqual(runtime.current_config_generation(), generation + 1)
            state.assert_not_called()
            stop.assert_called_once()
            fetch.assert_called_once_with(True)
        broken = {"BROKEN": {"host": "invalid.invalid", "slots": [{"channel": 20}]}}
        with patch.dict(runtime.config_store, {"modbus_gateways": broken}), patch.object(runtime, "save_config") as save, patch.object(runtime, "save_runtime_state") as state, patch.object(runtime, "stop_node_worker") as stop, patch.object(runtime, "fetch_modbus_remotes") as fetch:
            before = copy.deepcopy(runtime.config_store)
            generation = runtime.current_config_generation()
            self.assertFalse(runtime.update_modbus_config(runtime.ModbusConnectionConfig(host="replacement.invalid"))["ok"])
            save.assert_not_called()
            state.assert_not_called()
            self.assertEqual(runtime.config_store, before)
            self.assertEqual(runtime.current_config_generation(), generation)
            stop.assert_not_called()
            fetch.assert_not_called()

    def test_explicit_absent_disabled_settings_and_omitted_controls_never_fallback(self):
        adapter = Mock()
        adapter.execute_command.return_value = {"ok": True}
        hub = DeviceHub(DeviceRegistry([DeviceProfile("AMS01", "only", "remote", "modbus")]), {"modbus": adapter})
        with patch.object(runtime, "get_device_hub", return_value=hub):
            for target in ("AMS00", "MISSING", "", None):
                self.assertFalse(runtime._legacy_hub_command(target, "mode", {"mode": 3})["ok"])
            for function in (runtime.read_device_settings, runtime.read_pf3a_settings):
                self.assertFalse(function("AMS00")["ok"])
            requests = [
                (runtime.ctrl_ams_mode, runtime.AMSModeRequest(mode=3)),
                (runtime.ctrl_standby_signal, runtime.StandbySignalRequest(enabled=True)),
                (runtime.ctrl_forced_standby, runtime.ForcedStandbyRequest(enabled=True)),
                (runtime.ctrl_air_supply, runtime.AirSupplyRequest(enabled=True)),
                (runtime.ctrl_port4_pdout, runtime.Port4PdoutRequest(bytes=[1])),
                (runtime.ctrl_port4_do, runtime.Port4DoRequest(value=1)),
                (runtime.ctrl_flow_reset, runtime.FlowResetRequest()),
                (runtime.ctrl_itv_pressure, runtime.ITVPressureRequest(operation_kpa=500)),
                (runtime.ctrl_pf3a_param, runtime.PF3AParamRequest(standby_threshold_lmin=50)),
            ]
            for function, request in requests:
                with self.subTest(function=function.__name__):
                    self.assertFalse(function(request)["ok"])
            adapter.execute_command.assert_not_called()
            adapter.write_settings.assert_not_called()
            adapter.read_settings.assert_not_called()

    def test_modbus_lower_mode_does_not_alias_ams00_or_allow_disabled(self):
        with patch.object(runtime, "_modbus_set_bit") as bit:
            for target in (None, "", "AMS00", "MISSING"):
                self.assertFalse(runtime.set_modbus_ams_mode(3, target)["ok"])
            bit.assert_not_called()
        with patch.dict(runtime.config_store, {"device_profiles": {"AMS01": {"transport": "modbus", "enabled": False}}}), patch.object(runtime, "_modbus_read_registers") as read, patch.object(runtime, "_modbus_write_registers") as write:
            self.assertFalse(runtime.set_modbus_ams_mode(3, "AMS01")["ok"])
            with self.assertRaises(ValueError):
                runtime._exa1_service("AMS01", 0x65)
            with self.assertRaises(ValueError):
                runtime._modbus_set_port4_pdout("AMS01", [1])
            read.assert_not_called()
            write.assert_not_called()


class Stage1OpcuaRoutingTests(unittest.TestCase):
    def setUp(self):
        self.config = {"opcua_endpoint": "opc.tcp://base.invalid:4840", "ams_host": "https://base.invalid", "ams_channel": 0}
        self.callbacks = {key: Mock(return_value={"ok": True, "online": True}) for key in (
            "fetch_worker_data", "get_cached_remote", "write_bool_node", "write_byte_node", "write_bytes_node", "read_web_settings", "write_web_settings")}
        self.callbacks["signal_node"] = Mock(return_value="ns=2;s=fake.node")
        self.adapter = OpcuaHubAdapter({**self.callbacks, "get_config": lambda key, default=None: self.config.get(key, default)}, ConnectionContextManager())

    def test_opcua_execution_rejects_wrong_endpoint_and_disabled_before_every_callback(self):
        for profile in (DeviceProfile("AMS00", "base", "base", "opcua", endpoint="opc.tcp://other.invalid:4840"), DeviceProfile("AMS00", "base", "base", "opcua", enabled=False)):
            self.assertFalse(self.adapter.read_telemetry(profile).online)
            self.assertFalse(self.adapter.read_settings(profile)["ok"])
            self.assertFalse(self.adapter.write_settings(profile, {})["ok"])
            payloads = {"mode": {"mode": 3}, "standby": {"enabled": True},
                        "forced_standby": {"enabled": True}, "air_supply": {"enabled": True},
                        "port4_do": {"value": 1}, "port4_pdout": {"bytes": [0] * 16}}
            for command, payload in payloads.items():
                self.assertFalse(self.adapter.execute_command(profile, command, payload)["ok"])
            with self.assertRaises(ValueError):
                self.adapter.execute_command(profile, "standby", {"enabled": "false"})
        for callback in self.callbacks.values():
            callback.assert_not_called()

    def test_omitted_endpoint_resolves_at_admission_and_stale_profile_is_rejected(self):
        registry = DeviceRegistry.from_config({**self.config, "device_profiles": {"AMS00": {"transport": "opcua"}}})
        profile = registry.require("AMS00")
        self.assertEqual(profile.endpoint, self.config["opcua_endpoint"])
        self.assertTrue(self.adapter.execute_command(profile, "standby", {"enabled": True})["ok"])
        self.config["opcua_endpoint"] = "opc.tcp://changed.invalid:4840"
        self.callbacks["write_bool_node"].reset_mock()
        self.assertFalse(self.adapter.execute_command(profile, "standby", {"enabled": True})["ok"])
        self.callbacks["write_bool_node"].assert_not_called()

    def test_opcua_http_fallback_requires_verified_pair_and_capabilities_agree(self):
        base = DeviceProfile("AMS00", "base", "base", "opcua")
        self.assertTrue(self.adapter.capabilities(base)["settings_read"])
        self.assertTrue(self.adapter.read_settings(base)["ok"])
        self.assertTrue(self.adapter.write_settings(base, {"operation_kpa": 500})["ok"])
        self.callbacks["read_web_settings"].reset_mock()
        self.callbacks["write_web_settings"].reset_mock()
        for changes in ({"ams_host": "https://different.invalid"}, {"opcua_endpoint": "opc.tcp://base.invalid:4841"}, {"opcua_endpoint": "opc.tcp://base.invalid:4840/server"}, {"ams_channel": 1}):
            with self.subTest(changes=changes), patch.dict(self.config, changes):
                self.assertFalse(self.adapter.capabilities(base)["settings_write"])
                self.assertFalse(self.adapter.read_settings(base)["ok"])
                self.assertFalse(self.adapter.write_settings(base, {})["ok"])
        for profile in (DeviceProfile("AMS00", "wrong role", "remote", "opcua"), DeviceProfile("AMS01", "remote", "remote", "opcua")):
            self.assertFalse(self.adapter.capabilities(profile)["settings_read"])
            self.assertFalse(self.adapter.read_settings(profile)["ok"])
        self.callbacks["read_web_settings"].assert_not_called()
        self.callbacks["write_web_settings"].assert_not_called()

    def test_invalid_opcua_admission_does_not_accept_disabled_wrong_endpoint(self):
        for endpoint in ("opc.tcp://other.invalid:4840", "http://base.invalid", "", "opc.tcp://base.invalid:0"):
            config = {**self.config, "device_profiles": {"AMS00": {"transport": "opcua", "endpoint": endpoint, "enabled": False}}}
            if endpoint == "":
                config["opcua_endpoint"] = ""
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                DeviceRegistry.from_config(config)


if __name__ == "__main__":
    unittest.main()

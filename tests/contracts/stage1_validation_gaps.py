"""Stage-1 acceptance contracts: invalid JSON and an in-flight topology change.

Run with scripts/check_offline.py. These assert the required behavior, without
xfail or real transports; failures identify product gaps rather than bless them.
"""
import copy
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError
from offline_fixtures import guarded_runtime, isolated_runtime

runtime = guarded_runtime()


class Stage1ValidationGaps(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))

    def test_legacy_json_types_are_rejected_before_hub_execution(self):
        cases = [
            (runtime.StandbySignalRequest, runtime.ctrl_standby_signal, {"enabled": "false"}),
            (runtime.ForcedStandbyRequest, runtime.ctrl_forced_standby, {"enabled": 1}),
            (runtime.AMSModeRequest, runtime.ctrl_ams_mode, {"mode": True}),
            (runtime.AMSModeRequest, runtime.ctrl_ams_mode, {"mode": "2"}),
            (runtime.Port4PdoutRequest, runtime.ctrl_port4_pdout, {"bytes": [True]}),
            (runtime.Port4PdoutRequest, runtime.ctrl_port4_pdout, {"bytes": ["255"]}),
            (runtime.AirSupplyRequest, runtime.ctrl_air_supply, {"enabled": "true"}),
            (runtime.Port4DoRequest, runtime.ctrl_port4_do, {"value": True}),
            (runtime.Port4DoRequest, runtime.ctrl_port4_do, {"pin": "2", "enabled": True}),
            (runtime.Port4DoRequest, runtime.ctrl_port4_do, {"pin": 2, "enabled": 1}),
        ]
        for model, route, payload in cases:
            with self.subTest(model=model.__name__, payload=payload):
                hub = runtime.get_device_hub()
                with patch.object(runtime, "get_device_hub", return_value=hub), \
                        patch.object(hub, "execute", return_value={"ok": True, "results": {}}) as execute:
                    try:
                        request = model.model_validate({"remote_id": "AMS01", **payload})
                    except ValidationError:
                        continue
                    route(request)
                    execute.assert_not_called()

    def test_valid_legacy_json_still_reaches_hub_once(self):
        cases = [
            (runtime.StandbySignalRequest, runtime.ctrl_standby_signal, {"enabled": False}),
            (runtime.ForcedStandbyRequest, runtime.ctrl_forced_standby, {"enabled": True}),
            (runtime.AirSupplyRequest, runtime.ctrl_air_supply, {"enabled": True, "contact_mode": "NO"}),
            (runtime.AMSModeRequest, runtime.ctrl_ams_mode, {"mode": 2}),
            (runtime.Port4PdoutRequest, runtime.ctrl_port4_pdout, {"bytes": [0, 255] * 8}),
            (runtime.Port4DoRequest, runtime.ctrl_port4_do, {"value": 255}),
        ]
        for model, route, payload in cases:
            with self.subTest(model=model.__name__):
                hub = runtime.get_device_hub()
                with patch.object(runtime, "get_device_hub", return_value=hub), \
                        patch.object(hub, "execute", return_value={"ok": True, "results": {}}) as execute:
                    self.assertTrue(route(model.model_validate({"remote_id": "AMS01", **payload}))["ok"])
                    self.assertEqual(execute.call_count, 1)

    def test_modbus_command_never_writes_old_address_to_new_endpoint(self):
        old_host = runtime.config_store["modbus_gateways"]["FIXTURE-EXW1"]["host"]
        new_host = "replacement-fixture.invalid"
        old_address = runtime.MODBUS_AMS_CHANNEL_MAP["AMS01"]["output_start"]
        old_client, new_client = Mock(), Mock()
        changed = []
        new_client.read_holding_registers.return_value = [0]

        def change_configuration_during_read(address, count):
            if not changed:
                gateways = copy.deepcopy(runtime.config_store["modbus_gateways"])
                gateway = gateways["FIXTURE-EXW1"]
                gateway["host"] = new_host
                gateway["slots"][0]["device_id"] = "AMS02"
                gateway["slots"][1]["device_id"] = "AMS01"
                runtime.update_config_values(modbus_gateways=gateways)
                changed.append(runtime.current_config_generation())
            return [0]

        old_client.read_holding_registers.side_effect = change_configuration_during_read

        def client_for(endpoint):
            self.assertIn(endpoint.host, (old_host, new_host))
            return old_client if endpoint.host == old_host else new_client

        with patch.object(runtime._modbus_client_pool, "get", side_effect=client_for), \
                patch.object(runtime, "save_config"), patch.object(runtime, "save_runtime_state"):
            result = runtime._legacy_hub_command("AMS01", "standby", {"enabled": True})
        self.assertEqual(changed, [], "an active command must not change its own route")
        runtime.get_exw1_topology()
        self.assertEqual(runtime.MODBUS_AMS_CHANNEL_MAP["AMS01"]["output_start"], old_address)
        self.assertEqual(runtime.config_store["modbus_gateways"]["FIXTURE-EXW1"]["host"], old_host)
        self.assertEqual(new_client.write_registers.call_args_list, [],
                         f"old address {old_address} was sent to the replacement endpoint; result={result}")
        old_client.write_registers.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertIn("cannot change device routing from an active command", result["error"])
        self.assertIsNone(runtime._active_command_generation.get())

    def test_mode_stops_after_configuration_changes_during_first_write(self):
        client = Mock()
        client.read_holding_registers.return_value = [0]

        def change_after_write(address, values):
            runtime.update_config_values(modbus_process_byte_swap=True)

        client.write_registers.side_effect = change_after_write
        with patch.object(runtime._modbus_client_pool, "get", return_value=client), \
                patch.object(runtime, "save_config"), patch.object(runtime, "save_runtime_state"):
            result = runtime._legacy_hub_command("AMS01", "mode", {"mode": 3})
            self.assertFalse(result["ok"])
            self.assertEqual(client.write_registers.call_count, 1, "no remaining writes or retries after a generation change")
            self.assertEqual(client.read_holding_registers.call_count, 1)
            self.assertIsNone(runtime._active_command_generation.get())
            # Self-mutation was rejected: the original byte order/generation
            # remains usable once the failed command's lease unwinds.
            self.assertFalse(runtime.config_store["modbus_process_byte_swap"])
            client.write_registers.side_effect = None
            client.read_holding_registers.side_effect = [[0], [runtime._modbus_wire_word(0x0100)]]
            next_result = runtime._legacy_hub_command("AMS01", "standby", {"enabled": True})
            self.assertTrue(next_result["ok"])

    def test_configuration_publication_waits_for_a_started_write(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading

        writing, release, updating = threading.Event(), threading.Event(), threading.Event()
        old_host = runtime.config_store["modbus_gateways"]["FIXTURE-EXW1"]["host"]
        old_address = runtime.MODBUS_AMS_CHANNEL_MAP["AMS01"]["output_start"]
        gateways = copy.deepcopy(runtime.config_store["modbus_gateways"])
        gateway = gateways["FIXTURE-EXW1"]
        gateway["host"] = "replacement-fixture.invalid"
        gateway["slots"][0]["device_id"] = "AMS02"
        gateway["slots"][1]["device_id"] = "AMS01"
        client, replacement = Mock(), Mock()
        registers = {}
        client.read_holding_registers.side_effect = lambda address, count: [registers.get(address, 0)]

        def write(address, values):
            registers[address] = values[0]
            writing.set()
            if not release.wait(3):
                raise AssertionError("test write was not released")

        def update():
            updating.set()
            runtime.update_config_values(modbus_gateways=gateways)

        client.write_registers.side_effect = write
        with patch.object(runtime._modbus_client_pool, "get", side_effect=lambda endpoint: client if endpoint.host == old_host else replacement), \
                patch.object(runtime, "save_config"), patch.object(runtime, "save_runtime_state"), \
                ThreadPoolExecutor(max_workers=2) as pool:
            command = pool.submit(runtime._legacy_hub_command, "AMS01", "standby", {"enabled": True})
            try:
                self.assertTrue(writing.wait(2))
                publication = pool.submit(update)
                self.assertTrue(updating.wait(2))
                self.assertFalse(publication.done(), "configuration must not publish during the write")
                self.assertEqual(runtime.config_store["modbus_gateways"]["FIXTURE-EXW1"]["host"], old_host)
            finally:
                release.set()
            self.assertTrue(command.result(timeout=3)["ok"])
            publication.result(timeout=3)
        self.assertEqual(runtime.config_store["modbus_gateways"]["FIXTURE-EXW1"]["host"], "replacement-fixture.invalid")
        runtime.get_exw1_topology()
        self.assertNotEqual(runtime.MODBUS_AMS_CHANNEL_MAP["AMS01"]["output_start"], old_address)
        self.assertEqual(client.write_registers.call_count, 1)
        self.assertEqual(client.write_registers.call_args.args[0], old_address)
        replacement.write_registers.assert_not_called()
        replacement.read_holding_registers.assert_not_called()

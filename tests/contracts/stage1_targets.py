"""Desired stage-1 contracts, separate from the established 63 regressions.

These are executable failures until product code is repaired, not xfail tests or
assertions of today's unsafe behavior. All device callbacks are mocks; actual
runtime/registry/adapter implementations handle the routing.
"""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from offline_fixtures import guarded_runtime, isolated_runtime
from app.connection_context import ConnectionContextManager
from app.device_hub import DeviceHub, DeviceProfile, DeviceRegistry
from app.hub_adapters import OpcuaHubAdapter

runtime = guarded_runtime()


class Stage1TargetContracts(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))

    def test_invalid_persisted_profile_does_not_block_healthy_device(self):
        config = copy.deepcopy(runtime.config_store)
        config.update(data_source="opcua", modbus_gateways={}, device_profiles={
            "BROKEN_WEB": {"role": "remote", "transport": "web", "endpoint": "https://other.invalid"},
            "AMS01": {"role": "remote", "transport": "modbus", "endpoint": "exw1-fixture.invalid:502", "channel": 1},
        })
        original = copy.deepcopy(config)
        with patch.dict(runtime.config_store, config, clear=True):
            try:
                hub = runtime.get_device_hub()
            except ValueError as exc:
                self.fail(f"persisted invalid profile blocks registry recovery: {exc}")
            self.assertEqual([p.device_id for p in hub.registry.all()], ["AMS01"])
            with self.assertRaises(KeyError):
                hub.registry.require("BROKEN_WEB")
            self.assertEqual(runtime.config_store, original, "recovery must not rewrite invalid source config")

    def test_explicit_missing_ams00_never_falls_back_to_another_device(self):
        adapter = Mock()
        adapter.supports_command.return_value = True
        adapter.execute_command.return_value = {"ok": True}
        hub = DeviceHub(DeviceRegistry([DeviceProfile("AMS01", "Synthetic", "remote", "modbus")]), {"modbus": adapter})
        with patch.object(runtime, "get_device_hub", return_value=hub):
            try:
                result = runtime._legacy_hub_command("AMS00", "mode", {"mode": 3})
            except (KeyError, ValueError):
                result = {"ok": False}
        adapter.execute_command.assert_not_called()
        self.assertFalse(result["ok"])

    def test_topology_address_generation_preserves_user_disabled_intent(self):
        with patch.dict(runtime.config_store, {"data_source": "modbus", "device_profiles": {
            "AMS01": {"transport": "modbus", "role": "remote", "enabled": False},
        }}):
            effective = runtime._effective_device_registry_config()
            self.assertFalse(effective["device_profiles"]["AMS01"]["enabled"])
            registry = DeviceRegistry.from_config(effective)
            self.assertNotIn("AMS01", [p.device_id for p in registry.targets("COMBINED")])
            with self.assertRaises(KeyError):
                registry.require("AMS01")

    def test_opcua_other_endpoint_is_rejected_before_worker_write(self):
        writer = Mock(return_value={"ok": True})
        node = Mock(return_value="ns=2;s=offline.AMS01.standby")
        adapter = OpcuaHubAdapter({
            "get_config": lambda key, default=None: runtime.config_store.get(key, default),
            "signal_node": node, "write_bool_node": writer,
        }, ConnectionContextManager())
        profile = DeviceProfile("AMS01", "Wrong endpoint", "remote", "opcua", endpoint="opc.tcp://other.invalid:4840")
        result = adapter.execute_command(profile, "standby", {"enabled": True})
        writer.assert_not_called()
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()

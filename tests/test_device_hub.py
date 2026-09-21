import unittest

from app.device_hub import (
    DeviceHealth,
    DeviceHub,
    DeviceProfile,
    DeviceRegistry,
    DeviceSnapshot,
    aggregate_snapshots,
    batch_result,
)


class FakeAdapter:
    name = "opcua"

    def __init__(self, fail_ids=()):
        self.fail_ids = set(fail_ids)

    def health(self, profile):
        return DeviceHealth(connected=profile.device_id not in self.fail_ids)

    def read_telemetry(self, profile):
        online = profile.device_id not in self.fail_ids
        return DeviceSnapshot(
            profile.device_id,
            profile.transport,
            online,
            {"instant_flow_l_min": 10, "accumulated_flow_l": 100},
            DeviceHealth(connected=online),
        )

    def read_settings(self, profile):
        return {"ok": True, "value": profile.device_id}

    def write_settings(self, profile, values):
        return {"ok": True, "written": dict(values)}

    def execute_command(self, profile, command, payload):
        return {"ok": profile.device_id not in self.fail_ids, "command": command}


class DeviceHubTests(unittest.TestCase):
    def test_group_result_treats_unsupported_device_as_skipped(self):
        result = batch_result("mode", {
            "AMS01": {"ok": True},
            "IO13": {"ok": True, "skipped": True, "unsupported": True},
        })
        self.assertTrue(result["ok"])
        self.assertFalse(result["partial"])
        self.assertEqual(result["succeeded_devices"], ["AMS01"])
        self.assertEqual(result["skipped_devices"], ["IO13"])
    def test_explicit_registry_supports_mixed_transports(self):
        registry = DeviceRegistry.from_config({"device_profiles": {
            "AMS00": {"role": "base", "transport": "web"},
            "AMS01": {"role": "remote", "transport": "modbus", "channel": 1},
            "AMS02": {"role": "remote", "transport": "opcua"},
        }})
        self.assertEqual([p.transport for p in registry.all()], ["web", "modbus", "opcua"])

    def test_combined_excludes_simulator_from_production_totals(self):
        combined = aggregate_snapshots([
            {"device_id": "AMS01", "online": True, "instant_flow_l_min": 100, "accumulated_flow_l": 1000},
            {"device_id": "AMS02", "online": True, "simulated": True, "instant_flow_l_min": 50, "accumulated_flow_l": 500},
        ])
        self.assertEqual(combined["instant_flow_l_min"], 100)
        self.assertEqual(combined["simulated_instant_flow_l_min"], 50)
        self.assertTrue(combined["read_only"])

    def test_group_command_preserves_partial_failure(self):
        registry = DeviceRegistry([
            DeviceProfile("AMS01", "One", "remote", "opcua"),
            DeviceProfile("AMS02", "Two", "remote", "opcua"),
        ])
        hub = DeviceHub(registry, {"opcua": FakeAdapter(fail_ids={"AMS02"})})
        result = hub.execute("COMBINED", "mode", {"mode": 2})
        self.assertFalse(result["ok"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["succeeded_devices"], ["AMS01"])
        self.assertEqual(result["failed_devices"], ["AMS02"])

    def test_snapshots_are_isolated_by_device(self):
        registry = DeviceRegistry([
            DeviceProfile("AMS01", "One", "remote", "opcua"),
            DeviceProfile("AMS02", "Two", "remote", "opcua"),
        ])
        hub = DeviceHub(registry, {"opcua": FakeAdapter()})
        hub.read_all()
        first = hub.cached("AMS01")
        first["instant_flow_l_min"] = 999
        self.assertEqual(hub.cached("AMS01")["instant_flow_l_min"], 10)
        self.assertEqual(hub.cached("AMS02")["instant_flow_l_min"], 10)


if __name__ == "__main__":
    unittest.main()


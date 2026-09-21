import unittest

from app.exw1_topology import default_topology_config, load_exw1_topology
from app.modbus_client import ModbusClientPool, ModbusEndpoint


class Exw1TopologyTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "modbus_host": "192.168.0.1",
            "modbus_port": 502,
            "modbus_unit_id": 1,
            "modbus_timeout_s": 1.5,
            "modbus_exa1_ch1_model": 40,
            "modbus_exa1_ch2_model": 40,
        }

    def test_site_layout_calculates_expected_addresses(self):
        topology = load_exw1_topology(self.config)
        ch1 = topology.slot_for_device("AMS01")
        ch2 = topology.slot_for_device("AMS02")
        io = topology.slot_for_device("IO13")
        self.assertEqual((ch1.input_start, ch1.output_start, ch1.input_words, ch1.output_words), (2053, 0, 18, 9))
        self.assertEqual((ch2.input_start, ch2.output_start), (2071, 9))
        self.assertEqual((io.input_start, io.output_start, io.input_words, io.output_words), (2269, 108, 4, 4))
        self.assertEqual(len(topology.slots), 15)
        self.assertEqual([slot.kind for slot in topology.slots[2:12]], ["dummy"] * 10)

    def test_device_profiles_include_gateway_ownership(self):
        profiles = load_exw1_topology(self.config).device_profiles()
        self.assertEqual(sorted(profiles), ["AMS01", "AMS02", "IO13"])
        self.assertEqual(profiles["IO13"]["metadata"]["device_kind"], "remote_io")
        self.assertEqual(profiles["IO13"]["endpoint"], "192.168.0.1:502")

    def test_multiple_gateways_keep_endpoints_isolated(self):
        first = default_topology_config(self.config)["gateways"]["EXW1-01"]
        second = default_topology_config({**self.config, "modbus_host": "192.168.0.2"})["gateways"]["EXW1-01"]
        for slot in second["slots"]:
            if slot.get("device_id"):
                slot["device_id"] = "B" + slot["device_id"]
        topology = load_exw1_topology({"modbus_gateways": {"EXW1-A": first, "EXW1-B": second}})
        profiles = topology.device_profiles()
        self.assertEqual(profiles["AMS01"]["endpoint"], "192.168.0.1:502")
        self.assertEqual(profiles["BAMS01"]["endpoint"], "192.168.0.2:502")

    def test_client_pool_reuses_only_matching_endpoint(self):
        pool = ModbusClientPool()
        first = pool.get(ModbusEndpoint("192.168.0.1", 502, 1, 1.5))
        same = pool.get(ModbusEndpoint("192.168.0.1", 502, 1, 1.5))
        second = pool.get(ModbusEndpoint("192.168.0.2", 502, 1, 1.5))
        self.assertIs(first, same)
        self.assertIsNot(first, second)


if __name__ == "__main__":
    unittest.main()

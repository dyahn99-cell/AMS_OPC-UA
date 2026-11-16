import unittest
from app.device_hub import DeviceProfile
from app.device_models import model_for
from app.hub_adapters import ModbusHubAdapter, OpcuaHubAdapter, SimulatorHubAdapter, WebHubAdapter
from app.connection_context import ConnectionContextManager

class ModelPolicyTests(unittest.TestCase):
    def test_legacy_and_explicit_ams_preserved(self):
        for metadata in ({}, {'device_kind': 'exa1'}):
            p = DeviceProfile('AMS01', 'Alias', 'remote', 'modbus', metadata=metadata)
            adapter = ModbusHubAdapter({}, ConnectionContextManager())
            self.assertTrue(adapter.capabilities(p)['mode'])
            self.assertEqual((model_for(p).input_bytes, model_for(p).output_bytes), (36, 18))
            self.assertEqual(p.device_id, 'AMS01')
            self.assertEqual(p.name, 'Alias')

    def test_unverified_models_never_call_output_services(self):
        for cls in (ModbusHubAdapter, OpcuaHubAdapter, SimulatorHubAdapter, WebHubAdapter):
            for kind in ('remote_io', 'iolink_master', 'EXW1-RLAPA8C', '', None, 'unknown'):
                with self.subTest(adapter=cls.name, kind=kind):
                    p = DeviceProfile('AMS00', 'Alias', 'base', cls.name, metadata={'device_kind': kind})
                    adapter = cls({}, ConnectionContextManager())
                    self.assertFalse(adapter.capabilities(p)['mode'])
                    self.assertFalse(adapter.supports_command(p, 'mode'))
                    # Empty services make any accidental output dispatch fail this test.
                    self.assertTrue(adapter.execute_command(p, 'mode', {'mode': 1}).get('unsupported'))
                    self.assertTrue(adapter.write_settings(p, {'operation_kpa': 600}).get('unsupported'))

    def test_transport_limits_remain(self):
        p = DeviceProfile('AMS00', 'Base', 'base', 'web')
        adapter = WebHubAdapter({}, ConnectionContextManager())
        self.assertTrue(adapter.supports_command(p, 'mode'))
        self.assertFalse(adapter.supports_command(p, 'port4_do'))
        self.assertFalse(adapter.supports_command(p, 'unknown'))

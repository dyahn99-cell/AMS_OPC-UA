import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from test_workspace import plan

spec = importlib.util.spec_from_file_location('read_binding_test', Path(__file__).resolve().parents[2] / 'app/iolink_read_binding.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class ReadBindingTests(unittest.TestCase):
    def setup(self):
        c = plan(); c['input'] = 4
        gateway = NS(diagnostics='advanced', max_slots=15)
        slot = NS(gateway_id='BASE', channel=1, kind='remote_io', enabled=True, input_bytes=4,
                  output_bytes=2, input_start=2053, metadata={'part_no':c['model'],
                  'iolink_input_mapping':{'confirmed':True,'wordByteOrder':'low-high'}})
        topology = NS(gateway=lambda name:gateway, slots=[slot])
        return c, gateway, slot, topology

    def test_read_only_binding(self):
        c, _, _, topology = self.setup(); calls=[]
        def reader(address, count):
            calls.append((address,count));return [0x0102,0x803e]
        result=module.read(c,topology,reader)
        self.assertEqual(calls,[(2053,2)])
        self.assertEqual(result['mapping']['functionCode'],3)
        self.assertEqual(result['response']['words'],[0x0102,0x803e])

    def test_fail_closed_before_read(self):
        for field,value in [('kind','exa1'),('input_bytes',6),('input_start',2767),('enabled',False)]:
            c,_,slot,topology=self.setup();setattr(slot,field,value)
            with self.assertRaises(ValueError):module.read(c,topology,lambda *a:self.fail('unexpected read'))
        c,_,slot,topology=self.setup();slot.metadata['iolink_input_mapping']['confirmed']=False
        with self.assertRaises(ValueError):module.read(c,topology,lambda *a:self.fail('unexpected read'))
        c,gateway,_,topology=self.setup();gateway.max_slots=31
        with self.assertRaises(ValueError):module.resolve(c,topology)

    def test_short_response(self):
        c,_,_,topology=self.setup()
        with self.assertRaises(ValueError):module.read(c,topology,lambda *a:[1])

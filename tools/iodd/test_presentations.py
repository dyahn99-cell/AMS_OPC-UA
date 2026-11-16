import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT/'outputs/iodd/catalog.json').read_text(encoding='utf8'))
        cls.data = json.loads((ROOT/'outputs/iodd/product-presentations.json').read_text(encoding='utf8'))

    def test_every_binding_uses_original_item_and_layout(self):
        for m in self.catalog['models']:
            p = self.data['definitions'][m['sha256']]
            original = {i['id']: i for i in m['items']}
            self.assertEqual(len(p['pd']), sum(i['source'] in ('PD IN', 'PD OUT') for i in m['items']))
            for binding in p['pd']:
                item = original[binding['item']]
                self.assertEqual(binding['source'], item['source'])
                self.assertEqual(binding['layout'], item['layout'])
            for binding in p['settings']:
                item = original[binding['item']]
                self.assertEqual(item['source'], 'ACYCLIC')
                self.assertIn(item['accessRights'], ('ro', 'rw'))
                self.assertEqual(binding['index'], int(item['index']))
                if binding['subindex']:
                    self.assertNotEqual(item['datatype'].get('subindexAccessSupported'), 'false')
                    self.assertTrue(any(int(c['subindex']) == binding['subindex'] for c in item['datatype']['items']))
                self.assertIn(binding['access'], ('ro', 'rw'))
            self.assertTrue(set(p['default_pins']) <= {b['key'] for b in p['settings']})

    def test_pfuw_priorities_and_command_exclusion(self):
        m = next(m for m in self.catalog['models'] if m['sha256'].startswith('b920'))
        p = self.data['definitions'][m['sha256']]
        measurements = [b for b in p['pd'] if b['role'] == 'measurement']
        self.assertEqual(measurements[0]['iodd_name'], 'Flow')
        self.assertIn('V_OUT1_set_value|1', p['default_pins'])
        self.assertIn('V_OUT1_set_value|2', p['default_pins'])
        self.assertFalse(any(s['item'] == 'V_OUT_TEST' for s in p['settings']))

    def test_pressure_thresholds_available(self):
        m = next(m for m in self.catalog['models'] if m['name'] == 'ISE20C-L')
        self.assertIn('V_P1L|0', self.data['definitions'][m['sha256']]['default_pins'])

    def test_versions_remain_distinct_and_output_is_map_guarded(self):
        p = [self.data['definitions'][m['sha256']] for m in self.catalog['models'] if m['name'] == 'PF3A701H-xx-L3x-xxx']
        self.assertEqual(len(p), 2)
        self.assertNotEqual(p[0]['definition'], p[1]['definition'])
        self.assertEqual(p[0]['product_key'], p[1]['product_key'])
        for d in self.data['definitions'].values():
            self.assertFalse(d['verification']['hardware_verified'])
            if d['verification']['pd_output_transport']:
                self.assertEqual(d['verification']['pd_output_transport'], 'EXW1_live_map_guarded')
                self.assertTrue(d['verification']['writable_pd_fields'])


if __name__ == '__main__': unittest.main()

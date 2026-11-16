"""Only the isolated plan store. Never import app.runtime or start equipment."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('workspace_unit', ROOT / 'app/device_workspace.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def plan():
    return {'schema': 1, 'base': 'BASE', 'channel': 1, 'model': 'EXW1-RLAPA8C',
            'protocol': '2.0', 'input': 2, 'output': 2, 'y1': False, 'y2': False,
            'ports': [{'id': n, 'enabled': False, 'mode': 'deactivated', 'input': 0,
                       'output': 0, 'swap': 'direct', 'definition': None, 'layout': None,
                       'alias': ''} for n in range(1, 5)]}


class StoreTests(unittest.TestCase):
    def test_persistence_conflict_and_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = module.WorkspaceStore(Path(tmp) / 'plans.db', {})
            a = {'id': 'one', 'config': plan()}
            b = copy.deepcopy(a); b['id'] = 'two'; b['config']['channel'] = 2
            self.assertEqual(store.load()['revision'], 0)
            store.save(0, [a, b])
            reopened = module.WorkspaceStore(store.path, {})
            self.assertEqual(reopened.load()['masters'], [a, b])
            with self.assertRaises(module.Conflict): reopened.save(0, [])
            b['config']['channel'] = 1
            with self.assertRaises(ValueError): reopened.save(1, [a, b])
            self.assertEqual(reopened.load()['revision'], 1)

    def test_all_layouts_and_small_allocation(self):
        catalog = {m['sha256']: m for m in json.loads((ROOT / 'assets/iodd-layouts.json').read_text())}
        count = 0
        for key, model in catalog.items():
            for layout in model['layouts']:
                c = plan(); p = c['ports'][0]
                p.update(enabled=True, mode='manual', definition=key, layout=layout['id'])
                for direction, source in (('input', 'PD IN'), ('output', 'PD OUT')):
                    d = next((d for d in layout['directions'] if d['source'] == source), None)
                    p[direction] = (int(d['bitLength']) + 7) // 8 if d else 0
                    c[direction] = 2 + p[direction]
                module.validate([{'id': 'one', 'config': c}], catalog)
                for direction in ('input', 'output'):
                    if p[direction]:
                        p[direction] -= 1
                        with self.assertRaises(ValueError): module.validate([{'id': 'one', 'config': c}], catalog)
                        p[direction] += 1
                count += 1
        self.assertEqual(count, 432)


if __name__ == '__main__':
    unittest.main()

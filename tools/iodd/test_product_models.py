import collections
import hashlib
import math
import unittest
from pathlib import Path
from prepare_product_models import read_glb, accessor_values, PARTS
import json

ROOT = Path(__file__).resolve().parents[2] / 'assets/product-models'


def surfaces(doc, binary):
    """Per-CAD-face area, area-weighted centroid and oriented area vector."""
    values = collections.defaultdict(lambda: [0.] * 7)
    for mi, mesh in enumerate(doc['meshes']):
        for prim in mesh['primitives']:
            if prim.get('mode', 4) != 4:
                continue
            positions = accessor_values(doc, binary, prim['attributes']['POSITION'])
            features = accessor_values(doc, binary, prim['attributes']['_FEATURE_IDS'])
            indices = [x[0] for x in accessor_values(doc, binary, prim['indices'])] if 'indices' in prim else range(len(positions))
            for j in range(0, len(indices), 3):
                idx = indices[j:j+3]
                a, b, c = [positions[i] for i in idx]
                u, v = [b[k]-a[k] for k in range(3)], [c[k]-a[k] for k in range(3)]
                cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
                area = math.sqrt(sum(x*x for x in cross)) / 2
                row = values[mi, int(features[idx[0]][0])]
                row[0] += area
                for k in range(3):
                    row[k+1] += area * (a[k]+b[k]+c[k]) / 3
                    row[k+4] += cross[k] / 2
    return values


class ModelAssets(unittest.TestCase):
    def test_uploaded_models_match_supplied_hashes(self):
        manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf8'))
        self.assertEqual(len(manifest['assets']), 3)
        for asset in manifest['assets']:
            self.assertEqual(hashlib.sha256((ROOT / asset['file']).read_bytes()).hexdigest(), asset['sha256'])
            _, doc, _ = read_glb(ROOT / asset['file'])
            self.assertTrue(doc['meshes'])
            self.assertFalse(any(b.get('uri') for b in doc['buffers']))

    def test_colour_partition_preserves_cad_surface_and_assembly(self):
        for part in PARTS:
            _, original, binary = read_glb(ROOT / (part+'.glb'))
            _, display, after = read_glb(ROOT / (part+'.display.glb'))
            self.assertEqual(binary, after[:len(binary)])
            for key in ('nodes', 'scenes'):
                self.assertEqual(original.get(key), display.get(key))
            for key in ('materials', 'accessors', 'bufferViews'):
                self.assertEqual(original[key], display[key][:len(original[key])])
            before, current = surfaces(original, binary), surfaces(display, after)
            self.assertEqual(before.keys(), current.keys())
            for face, row in before.items():
                for left, right in zip(row, current[face]):
                    self.assertAlmostEqual(left, right, delta=max(0.005, abs(left)*0.00002), msg=f'{part} face {face}')
            for mesh in display['meshes']:
                self.assertTrue(mesh['primitives'])
                for prim in mesh['primitives']:
                    self.assertEqual(prim['mode'], 4)
                    self.assertEqual(display['accessors'][prim['attributes']['POSITION']]['count'] % 3, 0)

    def test_outline_keeps_original_cad_surface_and_edge_geometry(self):
        for part in PARTS:
            _, original, binary = read_glb(ROOT / (part+'.glb'))
            _, outline, after = read_glb(ROOT / (part+'.outline.glb'))
            self.assertEqual(binary, after)
            for key in ('nodes', 'scenes', 'accessors', 'bufferViews', 'buffers'):
                self.assertEqual(original.get(key), outline.get(key))
            for source_mesh, target_mesh in zip(original['meshes'], outline['meshes']):
                self.assertEqual(len(source_mesh['primitives']), len(target_mesh['primitives']))
                for source, target in zip(source_mesh['primitives'], target_mesh['primitives']):
                    self.assertEqual(source.get('mode', 4), target.get('mode', 4))
                    self.assertEqual(source.get('indices'), target.get('indices'))
                    expected = dict(source['attributes'])
                    if source.get('mode', 4) == 1:
                        expected.pop('COLOR_0', None)
                        expected.pop('NORMAL', None)
                    self.assertEqual(expected, target['attributes'])
                    self.assertIn('KHR_materials_unlit', outline['materials'][target['material']]['extensions'])

    def test_models_use_product_colours_without_invented_telemetry(self):
        for part in PARTS:
            _, doc, _ = read_glb(ROOT / (part+'.display.glb'))
            used = {doc['materials'][p['material']]['name'] for m in doc['meshes'] for p in m['primitives']}
            self.assertGreaterEqual(len(used), 5)
            self.assertIn('ivory-housing', used)
            self.assertIn('connector-steel', used)
            if part == 'EXW1-RLAPA8C':
                self.assertIn('blue-port-cover', used)
            if part == 'PFUW760-L1':
                self.assertTrue({'display-glass', 'display-blue', 'bracket-steel', 'button-rubber'} <= used)
            self.assertFalse(doc.get('images'))
            self.assertIn('Blank display is not telemetry', doc['asset']['extras']['displayPreparation'])


if __name__ == '__main__':
    unittest.main()

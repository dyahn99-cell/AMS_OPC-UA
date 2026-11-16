"""Derive photo-referenced coloured GLBs; preserve the original supplied CAD."""
import collections
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / 'assets/product-models'
PARTS = ('EXW1-BMTAC', 'EXW1-RLAPA8C', 'PFUW760-L1')
REFERENCES = {
    'EXW1': 'https://www.smcworld.com/newproducts/en-jp/22/exw1/',
    'PFUW': 'https://www.smcworld.com/newproducts/en-my/24/pfuw/',
}
# sRGB source palette, converted to linear values for glTF.
PALETTE = {
    'ivory-housing': ('#e3e6de', 0, .48),
    'blue-port-cover': ('#0876b8', 0, .35),
    'label-ivory': ('#eef0e9', 0, .65),
    'charcoal-label': ('#384448', 0, .55),
    'connector-steel': ('#bbc3c7', .85, .28),
    'connector-insulator': ('#303638', 0, .5),
    'contact-metal': ('#c6b889', .8, .3),
    'button-rubber': ('#555b59', 0, .72),
    'display-glass': ('#141e25', .05, .22),
    'display-blue': ('#254c91', 0, .3),
    'cable-polymer': ('#7c8580', 0, .7),
    'bracket-steel': ('#c3c9ca', .9, .34),
}


def read_glb(path):
    raw = path.read_bytes()
    if struct.unpack_from('<4sII', raw) != (b'glTF', 2, len(raw)):
        raise ValueError('invalid GLB')
    length, kind = struct.unpack_from('<II', raw, 12)
    if kind != 0x4e4f534a:
        raise ValueError('missing GLB JSON')
    doc = json.loads(raw[20:20 + length])
    size, kind = struct.unpack_from('<II', raw, 20 + length)
    if kind != 0x004e4942:
        raise ValueError('missing embedded GLB buffer')
    return raw, doc, raw[28 + length:28 + length + size]


def accessor_values(doc, binary, index):
    a = doc['accessors'][index]
    view = doc['bufferViews'][a['bufferView']]
    counts = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}
    fmt = {5126: 'f', 5125: 'I', 5123: 'H', 5121: 'B'}[a['componentType']]
    fmt = '<' + fmt * counts[a['type']]
    stride = view.get('byteStride', struct.calcsize(fmt))
    offset = view.get('byteOffset', 0) + a.get('byteOffset', 0)
    return [struct.unpack_from(fmt, binary, offset + i * stride) for i in range(a['count'])]


def material(name):
    hex_color, metal, roughness = PALETTE[name]
    rgb = [int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    rgb = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in rgb]
    return {'name': name, 'doubleSided': True, 'pbrMetallicRoughness': {
        'baseColorFactor': rgb + [1], 'metallicFactor': metal, 'roughnessFactor': roughness}}


def clip(poly, axis, boundary, lower):
    """Split on the existing surface plane, interpolating vertex attributes."""
    result = []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        av, bv = a['POSITION'][axis], b['POSITION'][axis]
        ai = av <= boundary if lower else av >= boundary
        bi = bv <= boundary if lower else bv >= boundary
        if ai:
            result.append(a)
        if ai != bi:
            t = (boundary - av) / (bv - av)
            result.append({key: tuple(x + t * (y - x) for x, y in zip(a[key], b[key])) for key in a})
    return result


def label_rectangle(triangle):
    # Base CAD has no separate label mesh. Partition its existing front face.
    inside = triangle
    outside = []
    for axis, boundary, lower in ((0, 12, False), (0, 88, True), (1, 22, False), (1, 53, True)):
        if not inside:
            break
        outside.append(('ivory-housing', clip(inside, axis, boundary, not lower)))
        inside = clip(inside, axis, boundary, lower)
    if inside:
        outside.extend((('label-ivory', clip(inside, 1, 47.5, True)),
                        ('charcoal-label', clip(inside, 1, 47.5, False))))
    return outside


def regions(part, mi, triangle, face_bounds):
    feature = int(triangle[0]['_FEATURE_IDS'][0])
    lo, hi = face_bounds[feature]
    if part.startswith('EXW1'):
        if part == 'EXW1-BMTAC' and feature == 3:
            return label_rectangle(triangle)
        if hi[1] <= .001 and lo[1] < -.01:
            if lo[0] >= 72 and hi[0] <= 85:
                if lo[0] >= 74.3 and hi[0] <= 82.7 and lo[2] >= 6.1 and hi[2] <= 14.5:
                    colour = 'contact-metal' if hi[0] - lo[0] < 1.5 else 'connector-insulator'
                else:
                    colour = 'blue-port-cover' if part == 'EXW1-RLAPA8C' else 'ivory-housing'
            elif any(lo[0] >= x - 4.05 and hi[0] <= x + 4.05 and lo[2] >= 6.25 and hi[2] <= 14.35 for x in (31, 54)):
                colour = 'contact-metal' if hi[0] - lo[0] < 1.5 else 'connector-insulator'
            else:
                colour = 'connector-steel'
            return [(colour, triangle)]
        if lo[1] >= 54 and hi[0] - lo[0] < 3 and hi[2] >= 20:
            return [('charcoal-label', triangle)]
        if part == 'EXW1-RLAPA8C':
            if feature == 262:
                return [('button-rubber', triangle)]
            if feature == 265:
                return [('label-ivory', clip(triangle, 1, 47.5, True)),
                        ('charcoal-label', clip(triangle, 1, 47.5, False))]
            if lo[2] >= 19.75 and lo[1] < 20.5:
                return [('blue-port-cover', clip(triangle, 1, 20.5, True)),
                        ('ivory-housing', clip(triangle, 1, 20.5, False))]
        return [('ivory-housing', triangle)]
    if mi in (2, 3):
        return [('bracket-steel', triangle)]
    if mi == 1:
        return [('connector-steel' if lo[2] >= -15 else 'cable-polymer', triangle)]
    if 239 <= feature <= 269 or feature in (346, 347, 348):
        return [('button-rubber', triangle)]
    if 315 <= feature <= 322:
        return [('display-glass', triangle)]
    if feature == 314:
        return [('display-blue', clip(triangle, 2, -1.5, True)),
                ('display-glass', clip(triangle, 2, -1.5, False))]
    return [('ivory-housing', triangle)]


def append_attribute(doc, binary, values, kind):
    binary.extend(b'\0' * (-len(binary) % 4))
    offset = len(binary)
    for row in values:
        binary.extend(struct.pack('<' + 'f' * len(row), *row))
    view_index = len(doc['bufferViews'])
    doc['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(binary) - offset, 'target': 34962})
    accessor = {'bufferView': view_index, 'componentType': 5126, 'count': len(values), 'type': kind}
    if kind == 'VEC3':
        accessor['min'] = [min(v[i] for v in values) for i in range(3)]
        accessor['max'] = [max(v[i] for v in values) for i in range(3)]
    doc['accessors'].append(accessor)
    return len(doc['accessors']) - 1


def prepare(path):
    raw, doc, source = read_glb(path)
    binary = bytearray(source)
    materials = {name: len(doc['materials']) + i for i, name in enumerate(PALETTE)}
    doc['materials'].extend(material(name) for name in PALETTE)
    removed = 0
    counts = collections.Counter()
    for mi, mesh in enumerate(doc['meshes']):
        coloured = []
        for prim in mesh['primitives']:
            if prim.get('mode', 4) != 4:
                removed += 1
                continue
            attrs = {key: accessor_values(doc, source, value) for key, value in prim['attributes'].items()}
            faces = collections.defaultdict(list)
            for point, feature in zip(attrs['POSITION'], attrs['_FEATURE_IDS']):
                faces[int(feature[0])].append(point)
            face_bounds = {f: ([min(p[i] for p in points) for i in range(3)],
                               [max(p[i] for p in points) for i in range(3)]) for f, points in faces.items()}
            indices = [v[0] for v in accessor_values(doc, source, prim['indices'])] if 'indices' in prim else range(len(attrs['POSITION']))
            grouped = collections.defaultdict(list)
            for i in range(0, len(indices), 3):
                triangle = [{key: values[index] for key, values in attrs.items()} for index in indices[i:i+3]]
                for name, polygon in regions(path.stem, mi, triangle, face_bounds):
                    for j in range(1, len(polygon) - 1):
                        grouped[name].extend((polygon[0], polygon[j], polygon[j+1]))
            for name, vertices in grouped.items():
                attributes = {}
                for key, original_index in prim['attributes'].items():
                    attributes[key] = append_attribute(doc, binary, [v[key] for v in vertices], doc['accessors'][original_index]['type'])
                coloured.append({'attributes': attributes, 'mode': 4, 'material': materials[name]})
                counts[name] += len(vertices) // 3
        if not coloured:
            raise ValueError('mesh has no surface geometry')
        mesh['primitives'] = coloured
    doc['buffers'][0]['byteLength'] = len(binary)
    doc.setdefault('asset', {}).setdefault('extras', {})['displayPreparation'] = 'Photo-referenced representative colours; original surface locations and assembly transforms preserved; CAD lines hidden. Blank display is not telemetry.'
    encoded = json.dumps(doc, separators=(',', ':')).encode()
    encoded += b' ' * (-len(encoded) % 4)
    binary.extend(b'\0' * (-len(binary) % 4))
    total = 28 + len(encoded) + len(binary)
    result = struct.pack('<4sII', b'glTF', 2, total) + struct.pack('<II', len(encoded), 0x4e4f534a) + encoded + struct.pack('<II', len(binary), 0x004e4942) + binary
    target = path.with_name(path.stem + '.display.glb')
    target.write_bytes(result)
    return {'original': path.name, 'original_sha256': hashlib.sha256(raw).hexdigest(),
            'display': target.name, 'display_sha256': hashlib.sha256(result).hexdigest(),
            'hidden_line_primitives': removed, 'colour_triangles': dict(counts),
            'reference': REFERENCES['EXW1' if path.stem.startswith('EXW1') else 'PFUW']}


if __name__ == '__main__':
    entries = [prepare(DIRECTORY / (name + '.glb')) for name in PARTS]
    (DIRECTORY / 'display-manifest.json').write_text(json.dumps({
        'preparation': 'Representative product colours; original CAD files retained without alteration.',
        'palette_srgb': {k: v[0] for k, v in PALETTE.items()}, 'assets': entries}, indent=2), encoding='utf8')
    print(json.dumps(entries, indent=2))

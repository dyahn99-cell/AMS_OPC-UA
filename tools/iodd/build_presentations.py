"""Build presentation bindings; never invent addresses, units or write rights."""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LABELS = {'Flow': '순간 유량', 'Accumulated': '누적 유량', 'Pressure': '압력',
          'Temperature': '온도', 'Humidity': '습도', 'Unit': '단위',
          'Filter': '필터', 'Response time': '응답 시간', 'System Error': '시스템 오류',
          'Error': '오류', 'Fixed output': '강제 출력 상태', 'ULS level': '초음파 신호 수준'}


def role(item):
    if item['source'] == 'PD OUT': return 'output'
    name = item['name'].lower()
    if re.search(r'error|alarm|diagnos|warning|hhh|lll|uls|fixed|quality', name): return 'diagnostic'
    if item['datatype']['type'] == 'BooleanT' or item['widget'] in ('enum', 'status'): return 'state'
    if item['widget'] == 'number': return 'measurement'
    return 'information'


def signal_kind(item):
    """Display candidates from named Boolean signals; numeric codes stay neutral."""
    if item['datatype']['type'] != 'BooleanT': return 'neutral'
    name = item['name'].lower()
    if re.search(r'error|alarm|fault', name): return 'alert'
    if re.search(r'warning', name): return 'warning'
    if re.search(r'fixed|test|hold', name): return 'notice'
    return 'state'


def rank(binding):
    name = binding['label'].lower()
    original = binding['iodd_name'].lower()
    return (0 if re.search(r'^flow$|^pressure$|^temperature$|^humidity$|position', original)
            else 1 if re.search(r'accum|total', original) else 2, name)


def readable_settings(model):
    bindings = []
    for item in model['items']:
        if item['source'] != 'ACYCLIC' or item.get('accessRights') not in ('ro', 'rw'): continue
        dt = item['datatype']
        children = dt.get('items') if dt['type'] == 'RecordT' and dt.get('subindexAccessSupported') != 'false' else None
        for child in children or [None]:
            if child and child.get('accessRightRestriction', item['accessRights']) not in ('ro', 'rw'): continue
            sub = int(child['subindex']) if child else 0
            name = item['name'] + (' / ' + child['name'] if child else '')
            binding = {'key': item['id']+'|'+str(sub), 'item': item['id'], 'subindex': sub,
                       'label': LABELS.get(item['name'], item['name']) + (' / '+child['name'] if child else ''),
                       'iodd_name': name, 'index': int(item['index']),
                       'access': 'ro' if item['accessRights'] == 'ro' else (child or {}).get('accessRightRestriction', item['accessRights']),
                       'datatype': (child or {}).get('datatype', dt)['type'], 'source': 'ACYCLIC',
                       'widget': 'parameter', 'selection_basis': 'iodd_name_rule', 'review': 'display_candidate'}
            token = (item['id']+' '+item['name']+' '+(child or {}).get('name', '')).lower()
            # Explicit field-name rules, not numeric address or command guesses.
            if re.search(r'(^v_unit$|unit$)', item['id'], re.I): score = 0
            elif re.search(r'out[12].*mode|response|filter', token) or re.fullmatch(r'V_oUt[12]', item['id'], re.I): score = 1
            elif re.search(r'hys\(p|hys\(h|set.?point|threshold|switch.*point', token) or re.fullmatch(r'V_[PNH][12](L|H)?|V_WH[12]', item['id'], re.I): score = 2
            elif re.search(r'wind\(|set.?value', token): score = 3
            else: score = 10
            binding['priority'] = score
            bindings.append(binding)
    return bindings


def build(catalog, library, engineering):
    lookup = {r['definition_key']: p for p in library['products'] for r in p['revisions']}
    definitions = {}
    for m in catalog['models']:
        product = lookup.get(m['sha256'], {})
        fields = [{'item': i['id'], 'layout': i.get('layout'), 'source': i['source'],
                   'role': role(i), 'signal_kind': signal_kind(i), 'label': LABELS.get(i['name'], i['name']), 'iodd_name': i['name'],
                   'widget': 'number' if i['widget'] == 'number' else 'state' if i['datatype']['type'] == 'BooleanT' or i['widget'] in ('enum', 'status') else 'information',
                   'default_view': 'counter' if re.search(r'accum|total', i['name'], re.I) and i['widget'] == 'number' else 'numeric' if i['widget'] == 'number' else 'state',
                   'review': 'iodd_structure_verified_semantics_candidate'}
                  for i in m['items'] if i['source'] in ('PD IN', 'PD OUT')]
        fields.sort(key=lambda b: ({'measurement': 0, 'state': 1, 'diagnostic': 2, 'information': 3, 'output': 4}[b['role']], rank(b)))
        settings = readable_settings(m)
        from pd_output import field_spec
        writable = []
        for i in m['items']:
            if i['source'] != 'PD OUT' or re.search('reserved', i['name'], re.I): continue
            try:
                direction = next(d for l in m['layouts'] if l['id'] == i['layout'] for d in l['directions'] if d['source'] == 'PD OUT')
                field_spec(i, direction); writable.append(i['id'])
            except (ValueError, KeyError, StopIteration): pass
        defaults = sorted((b for b in settings if b['priority'] < 10), key=lambda b: (b['priority'], b['index'], b['subindex']))[:8]
        definitions[m['sha256']] = {'definition': m['sha256'], 'product_key': 'iolink:'+m['vendorId']+':'+m['deviceId'],
            'model': m['name'], 'version': m['document'], 'categories': product.get('categories', []),
            'families': product.get('families', []), 'pd': fields, 'settings': settings,
            'display_policy': {'version': 1, 'order': ['primary', 'secondary', 'states', 'diagnostics', 'settings'], 'primary': 'first_non_counter_measurement', 'settings': 'user_selected', 'signal_colors': 'named_boolean_candidates', 'normal_range': 'explicit_verified_binding_only'},
            'default_pins': [b['key'] for b in defaults],
            'capabilities': {'measurements': sum(b['role'] == 'measurement' for b in fields),
                             'states': sum(b['role'] == 'state' for b in fields),
                             'diagnostics': sum(b['role'] == 'diagnostic' for b in fields),
                             'pd_outputs': sum(b['role'] == 'output' for b in fields), 'readable_settings': len(settings)},
            'engineering_rules': [{'item': r['item_id'], 'unit': r['unit'], 'unit_code': r['unit_code'],
                                   'evidence': r['evidence']} for r in engineering if r['definition_key'] == m['sha256']],
            'verification': {'iodd_bindings': True, 'display_semantics': 'rule_candidates',
                             'automatic_unit_conversion': 'live_ISDU_and_reviewed_rules' if any(r['definition_key'] == m['sha256'] for r in engineering) else False,
                             'pd_output_transport': 'EXW1_live_map_guarded' if writable else False,
                             'writable_pd_fields': writable, 'hardware_verified': False}}
    return {'schema': 1, 'widgets': ['number', 'counter', 'state', 'diagnostic', 'parameter', 'output'],
            'summary': {'definitions': len(definitions), 'products': len({d['product_key'] for d in definitions.values()}),
                        'with_output': sum(bool(d['capabilities']['pd_outputs']) for d in definitions.values()),
                        'with_default_pins': sum(bool(d['default_pins']) for d in definitions.values())}, 'definitions': definitions}


if __name__ == '__main__':
    read = lambda name: json.loads((ROOT/'outputs/iodd'/name).read_text(encoding='utf8'))
    data = build(read('catalog.json'), read('product-library.json'), read('engineering-rules.json'))
    (ROOT/'outputs/iodd/product-presentations.json').write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf8')
    print(json.dumps(data['summary']))

"""IO-Link PD OUT: IODD masks + EXW1 actual configuration mailbox.

The configured unit ID, rather than firmware-dependent unit position, locates
the port. Never write the SIO/PQI header or allocation padding.
"""
import connection_profile
import json
import re
import socket
import time
from pathlib import Path
from manual_output import Modbus, Conflict

ROOT = Path(__file__).resolve().parents[2]
REMOTE_IDS = {'rla': 0x1017, 'rla1': 0x1017, 'rlb': 0x1018, 'rlb1': 0x1018}

def normalize(data, mode):
    data = list(data)
    if mode == 'direct': return data
    if mode == 'swapAll': return data[::-1]
    if mode == 'swap32' and len(data) == 2: return data
    size = {'swap16': 2, 'swap32': 4}.get(mode)
    if not size or len(data) % size: raise ValueError('byte swap alignment')
    return [b for i in range(0, len(data), size) for b in data[i:i+size][::-1]]

def field_spec(item, direction):
    dt = item['datatype']; kind = dt['type']
    if kind not in ('BooleanT', 'IntegerT', 'UIntegerT', 'OctetStringT'):
        raise ValueError('unsupported PD output datatype')
    bits = 1 if kind == 'BooleanT' else int(dt['fixedLength'])*8 if kind == 'OctetStringT' else int(dt['bitLength'])
    offset = item.get('bitOffset')
    # Only a whole scalar direction has an implicit zero offset.
    if offset is None and direction['datatype']['type'] == kind: offset = 0
    if offset is None: raise ValueError('missing PD field offset')
    offset = int(offset)
    if not 1 <= bits <= 32 or offset < 0 or offset+bits > int(direction['bitLength']):
        raise ValueError('invalid PD field size')
    return kind, bits, offset

def decode(data, item, direction):
    kind, bits, offset = field_spec(item, direction)
    value = (int.from_bytes(bytes(data), 'big') >> offset) & ((1 << bits)-1)
    if kind == 'BooleanT': return bool(value)
    if kind == 'OctetStringT': return value.to_bytes(bits//8, 'big').hex(' ').upper()
    if kind == 'IntegerT' and value & (1 << (bits-1)): value -= 1 << bits
    return value

def encode(data, item, direction, value):
    kind, bits, offset = field_spec(item, direction)
    dt = item['datatype']
    if kind == 'BooleanT':
        if type(value) is not bool: raise ValueError('Boolean output required')
        value = int(value)
    elif kind == 'OctetStringT':
        if not isinstance(value, str): raise ValueError('hexadecimal output bytes required')
        compact = re.sub(r'\s+', '', value)
        if len(compact) != bits//4 or not re.fullmatch(r'[0-9A-Fa-f]+', compact):
            raise ValueError('exact IODD hexadecimal byte length required')
        value = int(compact, 16)
    else:
        if type(value) is not int: raise ValueError('integer output required')
        lo = -(1 << (bits-1)) if kind == 'IntegerT' else 0
        hi = (1 << (bits-1))-1 if kind == 'IntegerT' else (1 << bits)-1
        if not lo <= value <= hi: raise ValueError('outside datatype range')
        choices = [int(c['value']) for c in dt.get('choices', [])]
        ranges = dt.get('ranges', [])
        if (choices or ranges) and value not in choices and not any(int(r['lowerValue']) <= value <= int(r['upperValue']) for r in ranges):
            raise ValueError('outside IODD output range')
    mask = ((1 << bits)-1) << offset
    whole = int.from_bytes(bytes(data), 'big')
    return list(((whole & ~mask) | ((value & ((1 << bits)-1)) << offset)).to_bytes(len(data), 'big'))

def test_contacts(items, direction):
    contacts = []
    for item in items:
        try: kind, bits, offset = field_spec(item, direction)
        except (ValueError, KeyError): continue
        # Actuator commands, reset, safety flags and reserved fields are never
        # inferred to be lamp contacts. Only explicitly named digital outputs.
        if kind == 'BooleanT' and re.fullmatch(r'Output\s*\d+', item['name'], re.I):
            contacts.append({'key': item['id'], 'item': item['id'], 'bit': None, 'label': item['name']})
        group = re.fullmatch(r'OUT(\d+)_(\d+)', item['name'], re.I)
        if group and kind == 'UIntegerT' and bits == int(group[2])-int(group[1])+1:
            for bit in range(bits):
                contacts.append({'key': item['id']+':'+str(bit), 'item': item['id'], 'bit': bit, 'label': 'OUT '+str(int(group[1])+bit)})
    return contacts

def definition(q):
    models = json.loads((ROOT/'outputs/iodd/catalog.json').read_text(encoding='utf8'))['models']
    model = next((m for m in models if m['sha256'] == q.get('definition')), None)
    if model is None: raise ValueError('unknown IODD definition')
    layout = next((l for l in model['layouts'] if l['id'] == q.get('layout')), None)
    direction = next((d for d in (layout or {}).get('directions', []) if d['source'] == 'PD OUT'), None)
    if direction is None: raise ValueError('no PD output layout')
    if not str(direction.get('bitLength', '')).isdigit(): raise ValueError('unresolved PD output length')
    items = [i for i in model['items'] if i['source'] == 'PD OUT' and i['layout'] == layout['id']]
    return model, layout, direction, items

def output_request(q, write=False):
    channel, port, remote = q.get('channel'), q.get('port'), q.get('model')
    if type(channel) is not int or not 1 <= channel <= 15 or remote not in REMOTE_IDS:
        raise ValueError('invalid IO-Link target')
    if type(port) is not int or not 1 <= port <= (2 if remote.startswith('rlb') else 4):
        raise ValueError('invalid IO-Link port')
    model, layout, direction, items = definition(q)
    needed = (int(direction['bitLength'])+7)//8
    total, base, offset, size = (q.get(k) for k in ('totalOutput','outputOffset','portOutputOffset','portOutputBytes'))
    if any(type(n) is not int for n in (total, base, offset, size)) or not 2 <= total <= 130 or base < 0 or base % 2 or base+total > 1440 or not 2 <= offset or not 1 <= needed <= size <= 32 or offset+size > total:
        raise ValueError('invalid port output allocation')
    mode = q.get('swap', 'direct'); normalize([0]*size, mode)
    item = None
    if write:
        item = next((i for i in items if i['id'] == q.get('item')), None)
        if item is None or re.search(r'reserved', item['name'], re.I): raise ValueError('invalid writable PD field')
        expected = q.get('expected')
        if not isinstance(expected, list) or len(expected) != size or any(type(b) is not int or not 0 <= b <= 255 for b in expected):
            raise ValueError('read output before writing')
        # Validate requested value before any device communication.
        encode([0]*needed, item, direction, q.get('value'))
    sock,connection=connection_profile.connect()
    with sock:
        mb = Modbus(sock,connection['unit'])
        mb.write(0x1700, [channel]+[0]*15)
        config = mb.read(0x1700, 96)
        if config[0] != channel or config[1] != REMOTE_IDS[remote] or config[3]*2 != base or config[5] != total:
            raise Conflict('IO-Link 리모트의 실제 채널·모델·출력 할당과 구성표가 다릅니다.')
        # EXW1 firmware uses different unit positions. Match the documented
        # port unit ID (0054..0057), never assume P1 is unit 3 or unit 4.
        matches = [config[n:n+8] for n in range(8, 96, 8) if config[n+1] == 0x53+port]
        if len(matches) != 1: raise Conflict('장비의 포트 출력 맵을 확인할 수 없습니다.')
        unit = matches[0]
        absolute = base+offset
        if unit[3]*2 != absolute or unit[5] != size:
            raise Conflict('포트 출력 시작·할당 크기가 장비와 다릅니다. 구성표를 확인하세요.')
        if write:
            header = mb.read(config[2], 1)[0]
            shift = 2*(port-1)
            if not (header & (1 << (shift+1))) or not (header & (1 << (8+shift))):
                raise Conflict('선택 포트의 통신·PD 유효 상태를 확인할 수 없습니다.')
        # Conditional layouts must be matched with live ISDU settings.
        for condition in layout['condition']:
            a = condition.get('attributes', {})
            setting = next((i for i in model['items'] if i['id'] == a.get('variableId') and i['source'] == 'ACYCLIC' and i.get('accessRights') in ('ro', 'rw')), None)
            if condition.get('tag') != 'Condition' or not setting or setting['datatype']['type'] not in ('UIntegerT','IntegerT'):
                raise Conflict('조건부 출력 레이아웃의 실제 설정을 확인할 수 없습니다.')
            from isdu_reader import read_isdu
            response = read_isdu(port, int(setting['index']), channel=channel)
            dt = setting['datatype']; setting_size = int(dt['bitLength'])//8
            if len(response['bytes']) != setting_size or str(int.from_bytes(bytes(response['bytes']), 'big', signed=dt['type']=='IntegerT')) != a.get('value'):
                raise Conflict('실제 제품 설정과 선택한 출력 레이아웃이 다릅니다.')
        # Preserve a neighbor byte when allocation length is odd.
        address, count = absolute//2, (size+1)//2
        words = mb.read(address, count)
        raw = [b for w in words for b in (w & 255, w >> 8)]
        slot = raw[:size]; ordered = normalize(slot, mode)
        result = {'channel': channel, 'port': port, 'model': remote, 'definition': model['sha256'], 'layout': layout['id'], 'outputOffset': base, 'portOutputOffset': offset, 'portOutputBytes': size}
        if write:
            if slot != expected: raise Conflict('조회 후 포트 출력값이 변경됐습니다. 다시 조회하세요.')
            changed = encode(ordered[:needed], item, direction, q['value'])+ordered[needed:]
            target = normalize(changed, mode)+raw[size:]
            wanted = [target[i] | (target[i+1] << 8) for i in range(0, len(target), 2)]
            # Only changed words are written; unrelated header/port words stay untouched.
            changed_words = [i for i, (before, after) in enumerate(zip(words, wanted)) if before != after]
            if changed_words:
                first, last = min(changed_words), max(changed_words)+1
                mb.write(address+first, wanted[first:last])
            after = mb.read(address, count)
            result.update(verified=after == wanted, item=item['id'], requested=q['value'])
            slot = [b for w in after for b in (w & 255, w >> 8)][:size]
            ordered = normalize(slot, mode)
        fields = []
        for i in items:
            try: fields.append({'item': i['id'], 'value': decode(ordered[:needed], i, direction), 'writable': not bool(re.search(r'reserved', i['name'], re.I))})
            except (ValueError, KeyError): fields.append({'item': i['id'], 'value': None, 'writable': False})
        return dict(result, bytes=slot, fields=fields, contacts=test_contacts(items, direction), timestamp=int(time.time()*1000))

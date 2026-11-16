"""Offline IODD inventory. Preserves unresolved definitions; never accesses devices."""
import argparse
import collections
import hashlib
import io
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET


def tag(e):
    return e.tag.rsplit('}', 1)[-1]


def tree(e):
    return {'tag': tag(e), 'attributes': {k.rsplit('}', 1)[-1]: v for k, v in e.attrib.items()},
            'children': [tree(c) for c in e]}


def parse(data, source):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('DTD/entity declarations are not supported')
    root = ET.fromstring(data)
    identity = next((e for e in root.iter() if tag(e) == 'DeviceIdentity'), None)
    if identity is None:
        return None
    language = next((e for e in root.iter() if tag(e) == 'PrimaryLanguage'), None)
    texts = {e.get('id'): e.get('value') for e in language.iter() if tag(e) == 'Text'} if language is not None else {}
    types = {e.get('id'): e for e in root.iter() if tag(e) == 'Datatype' and e.get('id')}
    warnings = set()

    def name(e, which='Name'):
        child = next((c for c in e if tag(c) == which), None)
        if child is None:
            return e.get('id', '') if which == 'Name' else ''
        ref = child.get('textId', '')
        return texts.get(ref, ref)

    def datatype(e, seen=()):
        dt = next((c for c in e if tag(c) in ('Datatype', 'SimpleDatatype', 'DatatypeRef')), None)
        if dt is None:
            return {'type': 'unresolved'}
        if tag(dt) == 'DatatypeRef':
            ref = dt.get('datatypeId')
            if ref not in types or ref in seen:
                warnings.add('Unresolved datatype: '+str(ref))
                return {'type': 'unresolved', 'reference': ref}
            dt = types[ref]
        attrs = {k.rsplit('}', 1)[-1]: v for k, v in dt.attrib.items()}
        result = {'type': attrs.pop('type', 'unresolved'), **attrs}
        result['choices'] = [{'value': c.get('value'), 'label': name(c)} for c in dt if tag(c) == 'SingleValue']
        result['ranges'] = [dict(c.attrib) for c in dt if tag(c) == 'ValueRange']
        result['items'] = [{'name': name(c), **dict(c.attrib), 'datatype': datatype(c, seen+(dt.get('id'),))}
                           for c in dt if tag(c) == 'RecordItem']
        if result['type'] not in ('IntegerT', 'UIntegerT', 'Float32T', 'Float64T', 'BooleanT', 'StringT', 'OctetStringT', 'RecordT'):
            result['definition'] = tree(dt)
        return result

    def widget(dt):
        if dt.get('items') or dt['type'] in ('RecordT', 'ArrayT'):
            return 'structure'
        if dt.get('choices') and not dt.get('ranges'):
            return 'enum'
        if dt['type'] == 'BooleanT':
            return 'status'
        if dt['type'] in ('IntegerT', 'UIntegerT', 'Float32T', 'Float64T'):
            return 'number'
        return 'text' if dt['type'] in ('StringT', 'OctetStringT') else 'unresolved'

    items = []
    for e in root.iter():
        if tag(e) == 'Variable':
            dt = datatype(e)
            items.append({'source': 'ACYCLIC', **dict(e.attrib), 'name': name(e),
                          'description': name(e, 'Description'), 'datatype': dt, 'widget': widget(dt)})
    layouts = []
    for n, pd in enumerate(e for e in root.iter() if tag(e) == 'ProcessData'):
        condition = [tree(c) for c in pd if tag(c) == 'Condition']
        layout = {'id': n, 'condition': condition, 'definition_attributes': dict(pd.attrib), 'directions': []}
        for direction in pd:
            if tag(direction) not in ('ProcessDataIn', 'ProcessDataOut'):
                continue
            dt = datatype(direction)
            source_kind = 'PD IN' if tag(direction) == 'ProcessDataIn' else 'PD OUT'
            layout['directions'].append({'source': source_kind, **dict(direction.attrib), 'name': name(direction), 'datatype': dt})
            records = dt.get('items') or [{'name': name(direction), 'datatype': dt}]
            for j, record in enumerate(records):
                items.append({'source': source_kind, 'layout': n, 'condition': condition,
                              'id': f'{source_kind}:{n}:{j}', **record, 'widget': widget(record['datatype'])})
        layouts.append(layout)
    standard = [tree(e) for e in root.iter() if tag(e) == 'StdVariableRef']
    if standard:
        warnings.add('Standard variable references retained; standard definitions not resolved')
    doc = next((e for e in root.iter() if tag(e) == 'DocumentInfo'), None)
    return {'sha256': hashlib.sha256(data).hexdigest(), 'sources': [source], **dict(identity.attrib),
            'name': name(identity, 'DeviceName'), 'document': dict(doc.attrib) if doc is not None else {},
            'variants': [dict(e.attrib) for e in identity.iter() if tag(e) == 'DeviceVariant'],
            'items': items, 'layouts': layouts, 'standard_references': standard,
            'presentation_references': [tree(e) for e in root.iter() if tag(e) in ('VariableRef', 'RecordItemRef')],
            'warnings': sorted(warnings), 'status': 'parsed_only_not_hardware_verified'}


def build(archive):
    models, errors = [], []
    budget = [0]
    def scan(data, path, depth=0):
        if depth > 6:
            raise ValueError('ZIP nesting limit')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for entry in z.infolist():
                if entry.is_dir() or not entry.filename.lower().endswith(('.zip', '.xml')):
                    continue
                budget[0] += entry.file_size
                if entry.file_size > 64*1024*1024 or budget[0] > 512*1024*1024:
                    raise ValueError('Archive size limit')
                source = path+'!/'+entry.filename
                content = z.read(entry)
                if entry.filename.lower().endswith('.zip'):
                    scan(content, source, depth+1)
                else:
                    try:
                        model = parse(content, source)
                        if model: models.append(model)
                    except (ET.ParseError, ValueError) as exc:
                        errors.append({'source': source, 'error': str(exc)})
    scan(Path(archive).read_bytes(), Path(archive).name)
    unique = {}
    for model in models:
        if model['sha256'] in unique:
            unique[model['sha256']]['sources'] += model['sources']
        else:
            unique[model['sha256']] = model
    models = sorted(unique.values(), key=lambda m: (m['name'], m['document'].get('releaseDate','')))
    counts = collections.Counter(i['widget'] for m in models for i in m['items'])
    return {'schema_version': 1, 'archive_sha256': hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
            'summary': {'xml_documents': sum(len(m['sources']) for m in models), 'unique_documents': len(models),
                        'device_ids': len({(m['vendorId'], m['deviceId']) for m in models}),
                        'widget_candidates': dict(counts), 'errors': len(errors)},
            'limitations': ['No device communication or write support', 'Units/scaling/conditions are not automatically applied',
                           'Historical and current versions remain selectable', 'No XSD or IODD checker validation'],
            'models': models, 'errors': errors}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive'); parser.add_argument('output')
    args = parser.parse_args()
    result = build(args.archive)
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    template = Path(__file__).with_name('explorer.template.html').read_text(encoding='utf-8-sig')
    preview = {**result, 'models': [{**m, 'presentation_references': [], 'layouts': []} for m in result['models']]}
    payload = json.dumps(preview, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    target.with_name('explorer.html').write_text(template.replace('__CATALOG__', payload), encoding='utf-8')
    print(json.dumps(result['summary']))

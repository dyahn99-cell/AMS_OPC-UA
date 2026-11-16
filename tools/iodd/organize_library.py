"""Group parsed IODDs by device identity without choosing a hardware revision."""
import argparse
import collections
import csv
import io
import json
from pathlib import Path
import zipfile


def organize(catalog, manifest):
    by_path = collections.defaultdict(list)
    for row in manifest:
        by_path[row.get('local_path', '')].append(row)
    groups = {}
    for model in catalog['models']:
        key = f"iolink:{int(model['vendorId'])}:{int(model['deviceId'])}"
        product = groups.setdefault(key, {'product_key': key, 'vendor_id': int(model['vendorId']),
            'device_id': int(model['deviceId']), 'names': [], 'product_ids': [], 'families': [],
            'categories': [], 'revisions': [], 'transport_binding': None,
            'verification': {'parsed': True, 'decoded': False, 'hardware_read': False, 'hardware_write': False}})
        product['names'].append(model['name'])
        product['product_ids'].extend(v.get('productId', '') for v in model['variants'])
        provenance = []
        for source in model['sources']:
            for path, rows in by_path.items():
                if path and ('!/'+path+'!/') in source:
                    for row in rows:
                        product['families'].append(row.get('catalog_series', ''))
                        product['categories'].append(row.get('category', ''))
                        provenance.append({k: row.get(k, '') for k in ('local_path','version_role','download_url','catalog_series','category')})
        widget_counts = collections.Counter(i['widget'] for i in model['items'])
        source_counts = collections.Counter(i['source'] for i in model['items'])
        conditional = sum(bool(layout['condition']) for layout in model['layouts'])
        product['revisions'].append({'definition_key': model['sha256'], 'release_date': model['document'].get('releaseDate'),
            'version': model['document'].get('version'), 'sources': model['sources'], 'provenance': provenance,
            'item_counts': dict(source_counts), 'widget_candidates': dict(widget_counts),
            'pd_layouts': len(model['layouts']), 'conditional_layouts': conditional,
            'unresolved_standard_references': len(model['standard_references']),
            'blockers': ['unit_scaling_and_conditions_not_evaluated', 'hardware_mapping_not_verified'] +
                (['standard_definitions_required'] if model['standard_references'] else []) +
                (['compound_type_interpretation_required'] if widget_counts['structure'] else []),
            'suggested_widgets': sorted({w for kind in widget_counts for w in {
                'number': ['numeric','gauge','trend'], 'enum': ['state_label','parameter_select'],
                'status': ['digital_state'], 'text': ['information'], 'structure': ['structured_inspector'],
                'unresolved': ['raw_definition']}[kind]}),
            'write_enabled': False})
    products = sorted(groups.values(), key=lambda p:(sorted(p['categories']),p['names'][0],p['device_id']))
    for p in products:
        for k in ('names','product_ids','families','categories'):
            p[k] = sorted(set(v for v in p[k] if v))
        p['revisions'].sort(key=lambda r:(r['release_date'] or '',r['definition_key']),reverse=True)
        p['revision_selection'] = 'explicit_selection_required' if len(p['revisions'])>1 else 'single_definition_not_hardware_verified'
    return {'schema_version': 1, 'archive_sha256': catalog['archive_sha256'],
        'principle': 'Product definitions and widget bindings are independent of gateway/channel/port and instance IDs.',
        'summary': {'products':len(products), 'definitions':sum(len(p['revisions']) for p in products),
                    'multiple_revision_products':sum(len(p['revisions'])>1 for p in products),
                    'uncategorized_products':sum(not p['categories'] for p in products)},
        'products':products}


def report(library):
    lines=['# SMC 공통 장비 라이브러리 — 1단계','',
        '제품 정의를 Vendor ID + Device ID로 묶었습니다. 장비 인스턴스 ID·별칭·게이트웨이/CH/Port는 별도 구성으로 유지합니다.',
        '같은 제품 정의와 위젯을 다른 연결 위치에서 재사용할 수 있습니다. 직접 연결 장비는 별도 어댑터 검증이 필요합니다.',
        '', '## 현황','', *[f'- {k}: {v}' for k,v in library['summary'].items()], '',
        '위젯은 자료형에 따른 후보입니다. 단위·배율·조건을 확인하기 전 자동 연결하거나 쓰기를 허용하지 않습니다.',
        '여러 버전은 보존하며 가장 최근 날짜라는 이유만으로 자동 적용하지 않습니다.', '',
        '## 제품군별 목록','', '| 제품군 | 모델 이름 | Device ID | 정의 수 | 위젯 후보 |','|---|---|---:|---:|---|']
    def safe(v): return str(v).replace('|','/').replace('\n',' ')
    for p in library['products']:
        lines.append('| '+' | '.join(map(safe,[', '.join(p['families']) or '미분류', ', '.join(p['names']),p['device_id'],len(p['revisions']),', '.join(sorted({w for r in p['revisions'] for w in r['suggested_widgets']}))]))+' |')
    lines += ['', '## 다음 단계','',
        '1. 표준 변수 정의를 결합해 식별·진단 항목을 완성합니다.',
        '2. 조건부 PD, 단위·배율, 복합 항목을 제품군별로 검증합니다.',
        '3. 검증된 항목에 공용 위젯 기본 구성을 연결합니다.',
        '4. 마스터 수동 구성에서 장비 인스턴스와 제품 정의를 연결합니다.']
    return '\n'.join(lines)+'\n'


if __name__ == '__main__':
    ap=argparse.ArgumentParser();ap.add_argument('catalog');ap.add_argument('archive');ap.add_argument('output');args=ap.parse_args()
    with zipfile.ZipFile(args.archive) as z:
        manifest=list(csv.DictReader(io.StringIO(z.read('manifest.csv').decode('utf-8-sig'))))
    lib=organize(json.loads(Path(args.catalog).read_text(encoding='utf-8')),manifest)
    out=Path(args.output);out.write_text(json.dumps(lib,ensure_ascii=False,indent=2),encoding='utf-8')
    out.with_suffix('.md').write_text(report(lib),encoding='utf-8')
    print(json.dumps(lib['summary']))

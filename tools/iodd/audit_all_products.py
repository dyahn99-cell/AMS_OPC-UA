"""Inventory every definition; distinguish structural audit from manual verification."""
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/iodd'


def main():
    catalog = json.loads((OUT / 'catalog.json').read_text(encoding='utf-8'))
    library = json.loads((OUT / 'product-library.json').read_text(encoding='utf-8'))
    rules = json.loads((OUT / 'engineering-rules.json').read_text(encoding='utf-8'))
    profiles = json.loads((ROOT / 'tools/iodd/manual_review_profiles.json').read_text(encoding='utf-8'))
    downloads = {d['file']: d for d in json.loads((OUT / 'manuals/download-manifest.json').read_text(encoding='utf-8'))}
    by_package = {p: profile for profile in profiles for p in profile['packages']}
    models = {m['sha256']: m for m in catalog['models']}
    rows = []
    for product in library['products']:
        for revision in product['revisions']:
            m = models[revision['definition_key']]
            matched = [r for r in rules if r['definition_key'] == m['sha256']]
            packages = sorted({p['local_path'] for p in revision['provenance']})
            reviews = []
            for package in packages:
                profile = by_package.get(Path(package).name)
                if profile is None:
                    raise ValueError('Missing package review: ' + package)
                document = downloads.get(profile['manual'], {})
                reviews.append({**profile, 'url': profile.get('url', document.get('url')),
                    'document_sha256': document.get('sha256'),
                    'scope': 'dashboard_relevant_sections_reviewed; item_by_item_parameter_validation_pending',
                    'historical_definition': package.startswith('historical/')})
            fields = []
            for item in m['items']:
                dt = item['datatype']
                rule = next((r for r in matched if r['item_id'] == item['id']), None)
                fields.append({
                    'id': item['id'], 'name': item['name'], 'source': item['source'],
                    'index': item.get('index'), 'subindex': item.get('subindex'),
                    'layout': item.get('layout'), 'bit_offset': item.get('bitOffset'),
                    'type': dt.get('type'), 'bits': dt.get('bitLength'),
                    'access': item.get('accessRights'), 'condition': item.get('condition', []),
                    'ranges': dt.get('ranges', []), 'special_or_enum_values': dt.get('choices', []),
                    'widget_type': item['widget'],
                    'manual_status': 'conversion_crosschecked' if rule else 'pending',
                    'evidence': rule['evidence'] if rule else None,
                })
            layouts = [{'id': l['id'], 'condition': l['condition'],
                        'directions': [{'source': d['source'], 'bits': d.get('bitLength')}
                                       for d in l['directions']]} for l in m['layouts']]
            rows.append({
                'product_key': product['product_key'], 'model': m['name'],
                'families': product['families'], 'definition_key': m['sha256'],
                'document': m['document'], 'packages': packages, 'manual_reviews': reviews,
                'layouts': layouts, 'counts': dict(collections.Counter(f['source'] for f in fields)),
                'conditional_layouts': sum(bool(l['condition']) for l in layouts),
                'compound_fields': sum(f['widget_type'] == 'structure' for f in fields),
                'unresolved_standard_refs': len(m['standard_references']),
                'crosschecked_conversion_fields': len(matched),
                'manual_review_complete': False, 'hardware_verified': False,
                'fields': fields,
            })
    summary = {
        'products': len(library['products']), 'definitions': len(rows),
        'packages': len({p for r in rows for p in r['packages']}),
        'fields': sum(len(r['fields']) for r in rows),
        'definitions_with_pd_out': sum(bool(r['counts'].get('PD OUT')) for r in rows),
        'definitions_with_conditional_pd': sum(bool(r['conditional_layouts']) for r in rows),
        'definitions_with_compound_fields': sum(bool(r['compound_fields']) for r in rows),
        'definitions_with_unresolved_standard_refs': sum(bool(r['unresolved_standard_refs']) for r in rows),
        'definitions_with_some_manual_conversion_evidence': sum(bool(r['crosschecked_conversion_fields']) for r in rows),
        'fully_manual_reviewed_definitions': 0,
        'definitions_with_family_manual_review': sum(bool(r['manual_reviews']) for r in rows),
    }
    assert len(rows) == len(models)
    assert {r['definition_key'] for r in rows} == set(models)
    report = {'summary': summary, 'definitions': rows}
    (OUT / 'full-product-review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# SMC 전체 제품 검토 현황', '',
             '범위: 제공된 ZIP 전체. 모든 패키지의 대시보드 관련 매뉴얼을 검토했습니다. 각 비주기 항목의 조건·쓰기 동작까지 전부 구현/검증했다는 의미는 아닙니다.',
             '부분 확인을 전체 확인으로 확대하지 않습니다. 미확인 변환은 raw로 유지합니다.', '',
             *[f'- {k}: {v}' for k, v in summary.items()], '',
             '## 검토 기준', '',
             '각 정의마다 모델/Device ID/버전, PD 길이·비트·부호·조건, 단위/배율/특수값, 비주기 Index/Subindex·접근권한·명령, 진단과 공용 위젯 연결을 공식 매뉴얼과 대조해야 합니다.',
             '값을 읽지 못하는 초기 설정에서는 제품과 IODD 버전을 수동 선택합니다. 기본값은 실제 장비 설정이나 측정값으로 취급하지 않습니다.', '',
             '## 모든 제품 및 버전', '',
             '| 제품 | 식별 키 | 버전 | 패키지 | PD IN/OUT 항목 | 비주기 항목 | 조건부 레이아웃 | 복합 항목 | 변환 근거 항목 | 매뉴얼 전체 검토 |',
             '|---|---|---|---|---:|---:|---:|---:|---:|---|']
    for r in rows:
        values = [r['model'], r['product_key'], r['document'].get('version', ''),
                  ', '.join(r['packages']), f"{r['counts'].get('PD IN', 0)}/{r['counts'].get('PD OUT', 0)}",
                  r['counts'].get('ACYCLIC', 0), r['conditional_layouts'], r['compound_fields'],
                  r['crosschecked_conversion_fields'], '미완료']
        lines.append('| ' + ' | '.join(str(v).replace('|', '/') for v in values) + ' |')
    lines += ['', '기계 판독용 JSON에는 239개 정의의 모든 항목과 해당 항목의 근거 유무를 보존합니다.',
              'PD 항목 수는 바이트 길이가 아닙니다. 정확한 비트 길이는 JSON layouts.directions.bits에 있습니다.',
              '동일 제품의 구버전도 별도 검토 대상이며 최신 파일로 자동 대체하지 않습니다.']
    lines += ['', '## 패키지별 매뉴얼 검토 결과', '']
    for profile in profiles:
        document = downloads.get(profile['manual'], {})
        url = profile.get('url', document.get('url'))
        lines += ['### ' + ', '.join(profile['packages']), '',
                  f"근거: [{profile['manual']}]({url}), PDF 페이지 {', '.join(map(str,profile['pages']))}.", '',
                  profile['note'], '', '남은 확인: ' + '; '.join(profile['open']) + '.', '']
    (OUT / 'FULL_PRODUCT_REVIEW.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()

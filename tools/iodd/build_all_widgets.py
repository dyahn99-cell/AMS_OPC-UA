import json
from pathlib import Path
c=json.loads(Path('outputs/iodd/catalog.json').read_text(encoding='utf-8'))
l=json.loads(Path('outputs/iodd/product-library.json').read_text(encoding='utf-8'))
models=[{k:m[k] for k in ('sha256','name','items','sources','warnings','layouts','standard_references')} for m in c['models']]
rules=json.loads(Path('outputs/iodd/engineering-rules.json').read_text(encoding='utf-8'))
reviews={r['definition_key']:r['manual_reviews'] for r in json.loads(Path('outputs/iodd/full-product-review.json').read_text(encoding='utf-8'))['definitions']}
conflicts=json.loads(Path('outputs/iodd/engineering-conflicts.json').read_text(encoding='utf-8'))
diagnostics={r['definition_key']:r for r in json.loads(Path('outputs/iodd/diagnostic-review.json').read_text(encoding='utf-8'))['definitions']}
for m in models:
    m['diagnostic_review']=diagnostics[m['sha256']]
    m['engineering_rules']=[r for r in rules if r['definition_key']==m['sha256']]
    m['manual_reviews']=reviews[m['sha256']]
    m['engineering_conflicts']=[r for r in conflicts if r['definition_key']==m['sha256']]
d={'models':models,'products':l['products'],'limitations':c['limitations']}
payload=json.dumps(d,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
t=Path('tools/iodd/all-widgets.template.html').read_text(encoding='utf-8-sig')
t=t.replace('__DATA__',payload).replace('__WIDGETS__',Path('assets/iodd-engineering.js').read_text(encoding='utf-8-sig')+';'+Path('assets/iodd-widgets.js').read_text(encoding='utf-8-sig')+';'+Path('assets/iodd-device-dashboard.js').read_text(encoding='utf-8-sig')+';'+Path('assets/iodd-master-config.js').read_text(encoding='utf-8-sig')+';'+Path('assets/iodd-master-editor.js').read_text(encoding='utf-8-sig')+';'+Path('assets/iodd-workspace.js').read_text(encoding='utf-8-sig')+';'+Path('assets/iodd-diagnostic-profiles.js').read_text(encoding='utf-8-sig')+';'+Path('assets/iodd-pd-decoder.js').read_text(encoding='utf-8-sig')+';'+Path('assets/iodd-packet-lab.js').read_text(encoding='utf-8-sig')+';'+Path('assets/iodd-register-input.js').read_text(encoding='utf-8-sig')+';'+Path('assets/iodd-acyclic-diagnostics.js').read_text(encoding='utf-8-sig'))
Path('outputs/iodd/all-widgets.html').write_text(t,encoding='utf-8')
print('Built',len(models),'definitions;',sum(len(m['items']) for m in models),'items;',len(t),'characters')

Path('assets/iodd-workspace.html').write_text(t,encoding='utf-8')
Path('assets/iodd-layouts.json').write_text(json.dumps([{'sha256':m['sha256'],'layouts':[{'id':l['id'],'directions':[{'source':d['source'],'bitLength':d.get('bitLength')} for d in l['directions']]} for l in m['layouts']]} for m in models],separators=(',',':')),encoding='utf-8')

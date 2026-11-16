"""Build a small gallery bound to exact fields from the supplied catalog."""
import json
from pathlib import Path
c=json.loads(Path('outputs/iodd/catalog.json').read_text(encoding='utf-8'))
bindings=[]
for model_name,source,field,view in [
 ('PF3W704-LT-X445','PD IN','Flow','numeric'),
 ('ISE70','PD IN','Pressure Value','gauge'),
 ('PF3W704-LT-X445','PD IN','Temp','numeric'),
 ('ISE70','PD IN','Switch State (OUT1)','state'),
 ('ISE70','ACYCLIC','Unit','parameter-select'),
 ('ISE70','ACYCLIC','P_1','parameter-number')]:
 m=next(m for m in c['models'] if m['name']==model_name)
 i=next(i for i in m['items'] if i['name']==field and i['source']==source)
 dt=i['datatype'];ranges=dt.get('ranges') or []
 sample=dt['choices'][0]['value'] if i['widget']=='enum' else int((float(ranges[0]['lowerValue'])+float(ranges[0]['upperValue']))/2) if ranges else 100
 bindings.append({'model':m['name'],'definition_key':m['sha256'],'source_files':m['sources'],'item':i,'view':view,'sample':sample})
out=Path('outputs/iodd');out.joinpath('widget-bindings.json').write_text(json.dumps(bindings,ensure_ascii=False,indent=2),encoding='utf-8')
style='''body{margin:0;padding:32px;background:#101720;color:#e7eef7;font:14px/1.5 system-ui}h1{font-size:26px;margin:0}header p{color:#a2b4c8}#gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;max-width:1200px}.iw-card{background:#1b2735;border:1px solid #334356;border-radius:16px;padding:24px;min-width:0}h3{margin:0 0 6px;font-size:17px}small,.iw-status,.iw-note{color:#a2b4c8;font-size:12px}.iw-value{font-size:32px;margin:26px 0;font-variant-numeric:tabular-nums}.iw-value[data-quality=invalid]{color:#ffa993}.iw-value[data-quality=special]{color:#efd091}progress{width:100%;accent-color:#73d7cc}label{display:grid;gap:6px;font-size:12px;margin:20px 0}input,select{background:#111c29;color:#e7eef7;border:1px solid #40556a;border-radius:6px;padding:9px;font:16px system-ui}details{font-size:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}'''
script=Path('assets/iodd-widgets.js').read_text(encoding='utf-8-sig')
payload=json.dumps(bindings,ensure_ascii=False).replace('<','\\u003c')
html='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>IODD 공용 위젯</title><style>'+style+'</style><header><h1>실제 IODD에 연결한 공용 위젯</h1><p>PF3W704-LT-X445 / ISE70 · 독립 위젯 6개 · 원시값 시뮬레이션</p></header><main id="gallery"></main><script>'+script+'</script><script>const bindings='+payload+';bindings.forEach(b=>IoddWidgets.mount(document.getElementById("gallery"),b));</script></html>'
out.joinpath('verified-widget-gallery.html').write_text(html,encoding='utf-8')
print('Created 6 definition-bound widgets; no hardware verification claimed')

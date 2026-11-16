"""Bind reviewed diagnostic tables to exact IODD definitions and shapes."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[2]
out=root/'outputs/iodd'
models=json.loads((out/'catalog.json').read_text(encoding='utf-8'))['models']
rules=json.loads((out/'engineering-rules.json').read_text(encoding='utf-8'))
docpages={'OM_ISE7x-L2_OMV0004EN-J.pdf':62,'OM_ISE70Gx-L2_OMV0009EN-I.pdf':65,'OM_ISE79S-L2_MY0007EN-E.pdf':63,'OM_ZSE20B-L_ISE20B-L_OMU0006EN-H.pdf':76,'OM_ZSE20C-L_ISE20C-L_OMX0002EN-F.pdf':66,'OM_PF3W7_OMW0010EN-I.pdf':72,'OM_PF3W7-X445_OMV0006EN-C.pdf':74}
profiles={}
for m in models:
    candidates=[r for r in rules if r['definition_key']==m['sha256'] and r['evidence']['document'] in docpages]
    if not candidates:continue
    evidence=dict(candidates[0]['evidence']);doc=evidence['document'];evidence['pdf_pages']=[docpages[doc]]
    flow=doc.startswith('OM_PF3W');old=doc.startswith('OM_PF3W7-X445')
    expected={'Error':8 if old else 15,'HHH':9 if old else 8,'tHHH or tLLL':10 if old else 9} if flow else {'Error':2}
    requirement={'V_diAG':'1'} if not flow or old else {}
    if requirement:
        variable=next((i for i in m['items'] if i['id']=='V_diAG' and i.get('index')=='1003'),None)
        assert variable and any(x['value']=='1' for x in variable['datatype']['choices']),m['name']
    for layout in m['layouts']:
        fields=[i for i in m['items'] if i['source']=='PD IN' and i['layout']==layout['id']]
        for name,bit in expected.items():
            assert any(i['name']==name and i.get('bitOffset')==str(bit) and i['datatype']['type']=='BooleanT' for i in fields),(m['name'],name)
    profiles[m['sha256']]={'model':m['name'],'bits':list(expected.values()),'required_configuration':requirement,'evidence':evidence}
# Flow and temperature range diagnostics invalidate only the corresponding field.
for sha,profile in profiles.items():
 if not profile['evidence']['document'].startswith('OM_PF3W'):continue
 old=profile['evidence']['document'].startswith('OM_PF3W7-X445')
 model=next(m for m in models if m['sha256']==sha)
 profile['field_checks']={i['id']:{'zero_bits':[8 if old else 15, (9 if old else 8) if i['name']=='Flow' else (10 if old else 9)],'one_bits':[]} for i in model['items'] if i['source']=='PD IN' and i['widget']=='number'}
# Decisions cover every exact definition; pending does not mean runtime support.
reviews=json.loads((out/'full-product-review.json').read_text(encoding='utf-8'))['definitions']
by_sha={m['sha256']:m for m in models}
policies={
 'OM_D-MH2':('apply',48,'위치의 시스템·범위 오류'),
 'OM_PF2M7_':('apply',73,'유량 오류·고정출력·범위 진단'),
 'OM_PF2MC':('evidence_conflict',78,'고정출력 비트: 매뉴얼 표 9, IODD 14; 변환 계수 충돌도 미해결'),
 'OM_PFA3A':('apply',75,'유량 오류·고정출력·범위 진단'),
 'OM_PF3A7x':('apply',74,'유량 오류·고정출력·범위 진단'),
 'OM_PFCA':('apply',55,'유량과 누적값의 범위 진단을 각각 적용'),
 'OM_PFUW':('apply',84,'초음파 공통 오류와 유량·누적 범위 진단 분리'),
 'OM_ITV':('apply',9,'압력 오류·경고 동안 수치 보류하는 보수적 정책; F1/F2 공학 변환은 별도'),
 'OM_PSH':('evidence_conflict',75,'매뉴얼 고정출력 비트 13이 IODD에 없음'),
 'OM_FC3W':('apply',28,'유량 범위 오류와 밸브 원점 검출을 별도 적용'),
 'OM_IN502':('evidence_conflict',53,'비트 11 출력 오류/예약 표기 충돌; 462 변형은 별도 근거 필요'),
 'OM_IZS51':('evidence_conflict',43,'Ion Balance: 매뉴얼 signed 10비트, IODD signed 11비트 충돌'),
 'OM_IZT':('apply',14,'채널별 초기 설정·이온 생성 확인 및 공통/채널별 오류 차단'),
 'OM_EX260-MIL':('apply',21,'1바이트 입력 상태의 진단 비트 0–4; 출력 폭 4/8/12/16 별도 확인'),
 'OM_EX260-PIL':('evidence_conflict',24,'Device ID와 4/14 바이트 모델 대응 확인 필요'),
 'OM_EX430':('acyclic_required',27,'PD 상태 ByteArray 순서 미확정; Index 36 조회 필요'),
 'OM_D-MP_':('acyclic_required',19,'PD 스위치로 정상 판정 불가; Index 36 및 229/2 위치 qualifier 필요'),
 'OM_D-MPG':('acyclic_required',21,'Index 36 진단 및 동적 MDC scale 해석 필요'),
 'OM_ISA3':('evidence_conflict',91,'매뉴얼 unsigned와 IODD signed 표현 충돌'),
 'PSxx-':('apply',2,'전용 PSxx-PSV0007 PDF 2,6쪽 재확인: bit2 및 V_diAG=1 필수'),
 'OM_PSE200':('apply',77,'4채널별 진단과 전체 오류 분리'),
 'OM_PSE54':('evidence_conflict',19,'매뉴얼 고정출력 비트 13이 IODD에 없음'),
 'OM_PSE57':('evidence_conflict',23,'매뉴얼 고정출력 비트 13이 IODD에 없음'),
 'OM_EX260-IO':('acyclic_required',27,'Index 36 조회 필요; 선택형 PD ByteArray 해석 미확정'),
 'OM_JXCL':('acyclic_required',29,'Index 36 조회 필요; 원점/초기화/OL 상태 대응 미확정'),
 'OM_EX600':('acyclic_required',17,'PD는 디지털 입력; Index 36/0 및 37/0 전체 레코드 조회 필요'),
 'OM_ZK2':('evidence_conflict',None,'음수 범위와 unsigned 표현 및 변환 표 충돌'),
 'OM_EX260-VIL':('evidence_conflict',None,'출력 선택에 따른 센서 연결과 signed/unsigned 충돌'),
 'OM_EQ':('apply',36,'알람·경고 중 위치 수치를 보류하는 보수적 표시 정책; BUSY는 오류가 아님'),
}
audit=[]
for review in reviews:
 sha=review['definition_key'];m=by_sha[sha];manual=review['manual_reviews'][0];doc=manual['manual']
 if sha in profiles:
  status='pd_applied';page=profiles[sha]['evidence']['pdf_pages'][0];reason='기존 정확한 정의별 진단 적용'
 else:
  matches=[v for k,v in policies.items() if doc.startswith(k)]
  assert len(matches)==1,(doc,m['name'])
  status,page,reason=matches[0]
  if status=='apply' and manual.get('historical_definition') and not doc.startswith(('OM_PFA3A','OM_PF3A7x')):
   status='evidence_pending';reason='과거 개정에 맞는 진단 근거 필요; 최신 형식에서 자동 상속하지 않음'
  if status=='apply':
   gates={}
   for item in m['items']:
    if item['source']!='PD IN' or item['widget']!='number':continue
    name=item['name'];offset=int(item['bitOffset']);one=[]
    if name in ('ULS level','Control mode','Unused'):continue
    if doc.startswith('OM_D-MH2'):zero=[15,14,8];assert offset==16
    elif doc.startswith(('OM_PF2M7_','OM_PFA3A','OM_PF3A7x')):zero=[15,14,8];assert name=='Flow' and offset==16
    elif doc.startswith(('OM_PFCA','OM_PFUW')):
     assert name in ('Flow','Accumulated');assert offset==({'Flow':16,'Accumulated':32}[name])
     zero=[15,14,13]+([12] if doc.startswith('OM_PFUW') else [])+[9 if name=='Flow' else 8]
    elif doc.startswith('OM_FC3W'):
     assert name in ('Flow','Valve');assert offset==({'Flow':32,'Valve':16}[name])
     zero=[15,14]+([8] if name=='Flow' else []);one=[7] if name=='Valve' else []
    elif doc.startswith('OM_PSE200'):
     assert offset in (64,48,32,16);zero=[15,8+(64-offset)//16]
    elif doc.startswith('PSxx-'):
     assert offset==3 and item['datatype']['type']=='UIntegerT' and item['datatype']['bitLength']=='13';zero=[2]
    elif doc.startswith('OM_ITV'):
     assert offset==16 and item['datatype']['type']=='UIntegerT';zero=list(range(4,16))
    elif doc.startswith('OM_EQ'):
     assert offset==0 and item['datatype']['type']=='IntegerT';zero=[30,31]
    elif doc.startswith('OM_IZT'):
     assert offset in (80,64,48,32) and item['datatype']['bitLength']=='10'
     ch=(80-offset)//16;zero=[31,30,29,28,27]+[b-ch for b in (23,19,15,11,7)];one=[103-ch,99-ch]
    else:raise AssertionError(doc)
    for bit in zero+one:
     assert any(i['source']=='PD IN' and i['layout']==item['layout'] and i.get('bitOffset')==str(bit) and i['datatype']['type']=='BooleanT' for i in m['items']),(m['name'],bit)
    gates[item['id']]={'zero_bits':zero,'one_bits':one}
   status_only=doc.startswith('OM_EX260-MIL')
   if status_only:
    for layout in m['layouts']:
     assert any(d['source']=='PD IN' and d['bitLength']=='8' for d in layout['directions'])
     assert any(d['source']=='PD OUT' and int(d['bitLength']) in (32,64,96,128) for d in layout['directions'])
     assert {int(i['bitOffset']) for i in m['items'] if i['source']=='PD IN' and i['layout']==layout['id'] and i['datatype']['type']=='BooleanT'}==set(range(5))
   assert gates or status_only,m['name']
   profiles[sha]={'model':m['name'],'bits':list(range(5)) if status_only else sorted({b for g in gates.values() for b in g['zero_bits']}),'field_checks':gates,'required_configuration':{},'evidence':{'document':doc,'sha256':manual.get('document_sha256'),'url':manual['url'],'pdf_pages':[page]},'scope':'raw measurement validity; engineering units require separate confirmation'}
   if manual.get('historical_definition') and doc.startswith(('OM_PFA3A','OM_PF3A7x')):
    import hashlib
    small=doc.startswith('OM_PFA3A')
    legacy='om_pfxx_omx0007en.pdf' if small else 'om_pf3a7xh-l_omx0002en-e.pdf'
    assert int(m['deviceId']) in (range(394,400) if small else range(400,409))
    pages=[37,40] if small else [72,75]
    profiles[sha]['evidence']={'document':legacy,'sha256':hashlib.sha256((out/'manuals'/legacy).read_bytes()).hexdigest(),'pdf_pages':pages,'url':'https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/'+legacy}
    reason='구형 공식 매뉴얼의 Device ID와 32비트 PD 구조를 해당 과거 IODD에 직접 대조'
   if 'X731' in m['name']:
    profiles[sha]['evidence']['pdf_pages']=[15,73,81]
    reason='매뉴얼 15/81쪽에서 X731 사양 범위 확인, 73쪽 PD 비트와 각 IODD 대조; 원시 진단만 적용'
   if doc.startswith('PSxx-'):
    assert any(i['id']=='V_diAG' and i.get('index')=='1003' and any(c['value']=='1' for c in i['datatype']['choices']) for i in m['items'])
    profiles[sha]['required_configuration']={'V_diAG':'1'}
    profiles[sha]['evidence'].update({'pdf_pages':[2,6],'source_kind':'official_pdf_web_extraction','verified_date':'2026-09-29','sha256':None,'note':'공식 PDF의 웹 추출로 확인; 직접 다운로드 HTTP 403, 로컬 PDF 해시 없음'})
   status='pd_applied'
 row={'definition_key':sha,'model':m['name'],'status':status,'reason':reason,'manual':doc,'document_sha256':manual.get('document_sha256'),'pdf_pages':[page] if page else manual['pages'],'hardware_verified':False}
 if status=='pd_applied':
  e=profiles[sha]['evidence'];row.update({'manual':e['document'],'document_sha256':e['sha256'],'pdf_pages':e['pdf_pages'],'url':e['url']})
 if status=='acyclic_required':
  row['implementation']={'payload_decoder':True,'widget':True,'transport':False,'hardware_verified':False}
  row['required_reads']=[{'index':36,'subindex':0}]
  if doc.startswith('OM_D-MP_'):row['required_reads'].append({'index':229,'subindex':2})
  if doc.startswith('OM_EX600'):row['required_reads'].append({'index':37,'subindex':0})
 audit.append(row)
assert len(audit)==239 and len({r['definition_key'] for r in audit})==239
from collections import Counter
summary=dict(Counter(r['status'] for r in audit))
(out/'diagnostic-review.json').write_text(json.dumps({'summary':summary,'definitions':audit},ensure_ascii=False,indent=2),encoding='utf8')
lines=['# 제품별 진단 검토','', '239개 정확한 IODD 정의 분류. PD 적용은 원시 측정값 유효성 범위이며 실기 검증·전체 비주기 기능 완료를 뜻하지 않습니다.','',str(summary),'','| 제품 | 정의 SHA 앞 12자리 | 상태 | 근거 | 판단 |','|---|---|---|---|---|']
for r in audit:lines.append('| '+ ' | '.join([r['model'],r['definition_key'][:12],r['status'],r['manual']+' PDF '+str(r['pdf_pages']),r['reason']])+' |')
(out/'diagnostic-review.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
(out/'diagnostic-profiles.json').write_text(json.dumps(profiles,ensure_ascii=False,indent=2),encoding='utf-8')
payload=json.dumps(profiles,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
(root/'assets/iodd-diagnostic-profiles.js').write_text('(function(g){const p='+payload+';if(typeof module!=="undefined")module.exports=p;else g.IoddDiagnosticProfiles=p;})(globalThis);',encoding='utf-8')
print('Diagnostic definitions:',len(profiles))

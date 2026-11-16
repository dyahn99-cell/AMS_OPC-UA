import json
from pathlib import Path
c=json.loads(Path('outputs/iodd/catalog.json').read_text(encoding='utf-8'))
rules=[]
for modelname in ['ISE70','PF3W704-LT-X445']:
 m=next(m for m in c['models'] if m['name']==modelname)
 for i in m['items']:
  if i['source']!='PD IN':continue
  code=i['condition'][0]['attributes']['value']
  if modelname=='ISE70' and i['name']=='Pressure Value':
   unit,a,b={'0':('MPa',.00025,-.25),'1':('kPa',.25,-250),'2':('kgf/cm²',.002549,-2.549),'3':('bar',.0025,-2.5),'4':('psi',.03626,-36.26)}[code]
   doc='PSxx-OMV0004-D';pages=[61,62,63];url='https://www.smcworld.com/upfiles/_manual/e/PSxx-OMV0004.pdf';special=[0]
  elif modelname=='PF3W704-LT-X445' and i['name'] in ['Flow','Temp']:
   unit,a,b=('°C',.1,0) if i['name']=='Temp' else ('L/min',.004,0) if code=='0' else ('G/min',.001057,0)
   doc='PFxx-OMV0006-C';pages=[74,75,76];url='https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_pf3w7-x445_omv0006en-c.pdf';special=[]
  else:continue
  rg=i['datatype']['ranges'][0]
  rules.append({'model':modelname,'device_id':m['deviceId'],'definition_key':m['sha256'],'item_id':i['id'],'unit_code':code,'unit':unit,'scale':a,'offset':b,'raw_min':int(rg['lowerValue']),'raw_max':int(rg['upperValue']),'special_values':special,'bit_offset':int(i['bitOffset']),'bit_length':int(i['datatype']['bitLength']),'signed':i['datatype']['type']=='IntegerT','evidence':{'document':doc,'printed_pages':pages,'url':url},'status':'manual_and_iodd_crosschecked_not_hardware_verified'})
Path('outputs/iodd/engineering-rules.json').write_text(json.dumps(rules,ensure_ascii=False,indent=2),encoding='utf-8');print('Rules:',len(rules))

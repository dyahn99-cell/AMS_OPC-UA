"""Explicit manual coefficients, bound to each exact IODD and checked field shape.

Unconditional layouts expose the documented SI unit only, with explicit V_Unit=0.
No inferred sibling coefficients, write commands, or transport decoding.
"""
import json
import re
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / 'outputs/iodd'

def main():
    models = json.loads((OUT / 'catalog.json').read_text(encoding='utf-8'))['models']
    docs = json.loads((OUT / 'manuals/download-manifest.json').read_text(encoding='utf-8'))
    old = json.loads((OUT / 'engineering-rules.json').read_text(encoding='utf-8'))
    rules = {(r['definition_key'], r['item_id']): r for r in old}
    conflicts = []
    def evidence(prefix, pages):
        doc = next(d for d in docs if d['file'].startswith(prefix))
        return {'document': doc['file'], 'pdf_pages': pages, 'url': doc['url'], 'sha256': doc['sha256']}
    def add(m, i, unit, a, b, ev, bit, length=16, signed=True, code='0'):
        dt = i['datatype']
        if i['source'] != 'PD IN' or i.get('bitOffset') != str(bit): return
        if dt.get('type') != ('IntegerT' if signed else 'UIntegerT') or dt.get('bitLength') != str(length): return
        cond = i.get('condition', [])
        if cond and (len(cond) != 1 or cond[0]['attributes'] != {'variableId': 'V_Unit', 'value': code}): return
        unitdef = next((x for x in m['items'] if x['id'] == 'V_Unit'), None)
        if unitdef is None or code not in [c['value'] for c in unitdef['datatype']['choices']]: return
        if len(dt['ranges']) != 1: return
        unit_codes = {'MPa':'1132','kPa':'1133','kgf/cm²':'1145','bar':'1137','psi':'1141',
                      'L/min':'1352','G/min':'1363','L':'1038','°C':'1001'}
        refs = [x['attributes'] for x in m['presentation_references']
                if x['attributes'].get('variableId') == 'V_ProcessDataInput'
                and x['attributes'].get('subindex') == i.get('subindex')
                and (unit not in unit_codes or x['attributes'].get('unitCode') == unit_codes[unit])]
        agreeing = [x for x in refs if math.isclose(float(x.get('gradient',1)),a,rel_tol=1e-10)
                    and math.isclose(float(x.get('offset',0)),b,abs_tol=1e-9)]
        if not agreeing:
            rules.pop((m['sha256'], i['id']), None)
            conflicts.append({'model':m['name'],'definition_key':m['sha256'],'item_id':i['id'],
                'unit':unit,'manual_scale':a,'manual_offset':b,'iodd_presentations':refs,'evidence':ev})
            return
        r = dt['ranges'][0]
        rules[m['sha256'], i['id']] = {
            'model': m['name'], 'device_id': m['deviceId'], 'definition_key': m['sha256'],
            'item_id': i['id'], 'unit_code': code, 'unit': unit, 'scale': a, 'offset': b,
            'raw_min': int(r['lowerValue']), 'raw_max': int(r['upperValue']),
            'special_values': [int(c['value']) for c in dt['choices']],
            'bit_offset': bit, 'bit_length': length, 'signed': signed, 'evidence': ev,
            'status': 'manual_and_iodd_crosschecked_not_hardware_verified',
            'iodd_presentation_evidence': agreeing,
        }
    # Coefficients in V_Unit order: MPa, kPa, kgf/cm2, bar, psi, inchHg, mmHg.
    tables = {
        'ISE70': [.00025,.25,.002549,.0025,.03626],
        'ISE71': [.0004,.4,.004079,.004,.05802],
        'ISE70G': [.00025,.25,.002549,.0025,.03626],
        'ISE75G': [.0005,.5,.0050985,.005,.07252],
        'ISE76G': [.00125,None,.0127475,.0125,.1813],
        'ISE77G': [.0025,None,.0254925,.025,.3626],
        'ISE78G': [.004,None,.0407875,.04,.58015],
        'ISE79S': [.0125,None,.127475,.125,1.813],
        'ISE20B': [.00025,.25,.00254925,.0025,.03626],
        'ISE20C': [.00025,.25,.00254925,.0025,.03626],
        'ISE20CH': [.0005,.5,.0050985,.005,.07252],
        'ZSE20B': [-.000025,-.025,-.000254925,-.00025,-.003626,-.0073825,-.187525],
        'ZSE20C': [-.000025,-.025,-.000254925,-.00025,-.003626,-.0073825,-.187525],
        'ZSE20BF': [.00005,.05,.00050985,.0005,.007252,.014765,.37505],
        'ZSE20CF': [.00005,.05,.00050985,.0005,.007252,.014765,.37505],
    }
    units = ['MPa','kPa','kgf/cm²','bar','psi','inchHg','mmHg']
    for m in models:
        n = m['name']; base = n.split('-')[0]
        for i in m['items']:
            if i['source'] != 'PD IN': continue
            if base in tables and i['name'] == 'Pressure Value':
                cond = i.get('condition', [])
                if not cond: continue
                code = cond[0]['attributes'].get('value'); k = int(code)
                if k >= len(tables[base]) or tables[base][k] is None: continue
                a = tables[base][k]; b = -a * (3000 if base in ('ZSE20BF','ZSE20CF') else 1000)
                if n.endswith('-T'):
                    ev = {'document':'PSxx-PSV0007','pdf_pages':[2,3,4], 'url':'https://www.smcworld.com/upfiles/_manual/e/PSxx-PSV0007.pdf'}
                elif '20B' in base: ev = evidence('OM_ZSE20B-L',[76,77,78])
                elif '20C' in base: ev = evidence('OM_ZSE20C-L',[66,67,68])
                elif base == 'ISE79S': ev = evidence('OM_ISE79S',[63,64,65])
                elif base.endswith('G'): ev = evidence('OM_ISE70Gx',[65,66,67])
                else: ev = evidence('OM_ISE7x-L2',[62,63,64])
                add(m,i,units[k],a,b,ev,3,13,False,code)
            elif n.startswith('PF2M7') and 'X731' not in n and i['name']=='Flow':
                a={'01':.00025,'02':.0005,'05':.00125,'10':.0025,'25':.00625,'50':.0125,'11':.025}.get(n[5:7])
                if a is not None:add(m,i,'L/min',a,0,evidence('OM_PF2M7',[73,74,75,77]),16)
            elif n.startswith('PF3A7') and i['name']=='Flow':
                key=n[5:7];a={'R5':.125,'01':.25,'02':.5,'04':1,'08':2,'03':.75,'06':1.5,'12':3}.get(key)
                if a is not None:
                    ev=evidence('OM_PF3A7xH-L',[74,75,76]) if key in ('03','06','12') else evidence('OM_PFA3A7xx',[75,76,77])
                    add(m,i,'L/min',a,0,ev,16)
            elif n.startswith('PF3W7') and i['name'] in ('Flow','Temp'):
                oldmodel=int(m['deviceId']) in (310,317,330,331,332)
                ev=evidence('OM_PF3W7-X445',[74,75,76]) if oldmodel else evidence('OM_PF3W7_OMW',[72,73,74])
                codes=[c['attributes']['value'] for c in i.get('condition',[])] or ['0']
                for code in codes:
                    key=n[5:7]
                    a=({'04':.004,'20':.016,'40':.04,'11':.1,'21':.25} if code=='0' else {'04':.001057,'20':.004227,'40':.01057,'11':.02642,'21':.066}).get(key)
                    if a is not None:add(m,i,'°C' if i['name']=='Temp' else ('L/min' if code=='0' else 'G/min'),.1 if i['name']=='Temp' else a,0,ev,16 if i['name']=='Temp' else 32,code=code)
            elif n.startswith('PFCA7') and i['name'] in ('Flow','Accumulated'):
                key=n[5:7];acc=i['name']=='Accumulated'
                a=(.1 if key=='10' else 1) if acc else {'10':.0025,'25':.00625,'50':.0125,'11':.025}[key]
                add(m,i,'L' if acc else 'L/min',a,0,evidence('OM_PFCA7',[55,56,58]),32 if acc else 16,32 if acc else 16,not acc)
            elif n.startswith('PFUW7') and i['name'] in ('Flow','Accumulated'):
                acc=i['name']=='Accumulated';a=1 if acc else {'60':.015,'11':.025,'21':.05}[n[5:7]]
                add(m,i,'L' if acc else 'L/min',a,0,evidence('OM_PFUW7',[84,85,87]),32 if acc else 16,32 if acc else 16,not acc)
            elif n.startswith('PSH-') and int(m['deviceId']) in (728,729) and i['name'] in ('Humidity value','Temperature value'):
                add(m,i,'%R.H.' if i['name']=='Humidity value' else '°C',.1,0,evidence('OM_PSH',[75,76,77]),32 if i['name']=='Humidity value' else 16)
    # The manuals explicitly direct peak/bottom ISDU values to the PD formula.
    # Bind each variable independently; never apply a PD bit offset to ISDU bytes.
    for m in models:
        base=m['name'].split('-')[0]
        if base not in ('ISE20B','ZSE20B','ZSE20BF','ISE20C','ISE20CH','ZSE20C','ZSE20CF') or m['name'].endswith('-T'):continue
        pd=next((r for r in rules.values() if r['definition_key']==m['sha256'] and r['item_id'].startswith('PD IN:') and r['unit_code']=='0'),None)
        if pd is None:continue
        for i in m['items']:
            if i.get('index') not in ('2002','2003') or i.get('accessRights')!='ro':continue
            dt=i['datatype']
            if dt['type']!='UIntegerT' or dt.get('bitLength')!='16' or len(dt['ranges'])!=1:continue
            refs=[x['attributes'] for x in m['presentation_references'] if x['attributes'].get('variableId')==i['id'] and x['attributes'].get('unitCode')=='1132']
            agreeing=[x for x in refs if math.isclose(float(x.get('gradient',1)),pd['scale'],rel_tol=1e-10) and math.isclose(float(x.get('offset',0)),pd['offset'],abs_tol=1e-9)]
            if not agreeing:continue
            rg=dt['ranges'][0]
            ev=evidence('OM_ZSE20B-L',[76,78,87]) if '20B' in base else evidence('OM_ZSE20C-L',[66,68,78])
            rules[m['sha256'],i['id']]={**pd,'item_id':i['id'],'source':'ACYCLIC','index':int(i['index']),'subindex':0,
                'bit_offset':None,'bit_length':16,'raw_min':int(rg['lowerValue']),'raw_max':int(rg['upperValue']),
                'special_values':[int(c['value']) for c in dt['choices']], 'evidence':ev,'iodd_presentation_evidence':agreeing}
    result=list(rules.values())
    (OUT/'engineering-rules.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'engineering-conflicts.json').write_text(json.dumps(conflicts,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Rules:',len(result),'Definitions:',len({r['definition_key'] for r in result}))
    print('Blocked coefficient comparisons:', len(conflicts))

if __name__=='__main__':main()

/* Live ISDU conditions gate reviewed scaling. Never infer a unit from the name. */
(function(g){
function create(){let cache=null;
 async function read({channel,port,model,layout}){
  const key=[channel,port,model.sha256,layout.id].join(':');
  if(cache?.key===key&&Date.now()-cache.timestamp<30000)return cache;
  const ids=new Set(layout.condition.map(c=>c.attributes?.variableId).filter(Boolean));
  const profile=IoddDiagnosticProfiles[model.sha256];for(const id of Object.keys(profile?.required_configuration||{}))ids.add(id);
  const rules=model.engineering_rules||[];const unit=model.items.find(i=>i.id==='V_Unit'&&i.source==='ACYCLIC');if(unit&&rules.length)ids.add(unit.id);
  const values={},errors=[];
  for(const id of ids){const item=model.items.find(i=>i.id===id&&i.source==='ACYCLIC'&&['ro','rw'].includes(i.accessRights));
   if(!item){errors.push(id+': 실제 조건 조회 정의 없음');continue;}
   try{const r=await fetch('/isdu',{method:'POST',headers:{'Content-Type':'application/json','X-Read-Token':g.readToken},body:JSON.stringify({channel,port,definition:model.sha256,item:id,subindex:0})}),d=await r.json();if(!r.ok)throw Error(d.error);if(d.channel!==channel||d.port!==port||d.definition!==model.sha256||d.item!==id||d.subindex!==0)throw Error('설정 응답 대상 불일치');
    const v=IoddPresentation.decode(item.datatype,d.bytes).value;if(typeof v!=='number'&&typeof v!=='boolean')throw Error('조건 자료형 해석 미지원');values[id]=v;
   }catch(e){errors.push(id+': '+e.message);}
  }
  if(!unit&&rules.length&&new Set(rules.map(r=>r.unit_code)).size===1)values.V_Unit=rules[0].unit_code;
  const conditionOK=layout.condition.every(c=>c.tag==='Condition'&&String(values[c.attributes?.variableId])===String(c.attributes?.value));
  cache={key,timestamp:Date.now(),values,conditionOK,errors};return cache;
 }
 return {read,invalidate(){cache=null;}};
}
g.IoddLiveUnits={create};
})(globalThis);

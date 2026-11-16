/* Definition-only composition; no transport or hardware defaults. */
(function(global){
'use strict';
const sections=[['measurement','측정값'],['state','상태·진단 비트'],['acyclic','비주기 조회'],['settings','설정 정의'],['output','출력·명령 정의'],['definition','복합·미해석 정의']];
function role(item){
 if(item.source==='PD OUT')return 'output';
 if(['structure','unresolved'].includes(item.widget))return 'definition';
 if(item.source==='ACYCLIC')return item.accessRights==='ro'?'acyclic':'settings';
 return item.widget==='number'?'measurement':'state';
}
function compose(model,layoutId){
 const layouts=model.layouts||[];
 const layout=layouts.find(l=>String(l.id)===String(layoutId));
 const groups=sections.map(([id,title])=>({id,title,bindings:[]}));
 let pending=0;
 model.items.forEach((item,index)=>{
  if(item.source!=='ACYCLIC'&&(!layout||String(item.layout)!==String(layout.id))){pending++;return;}
  const group=groups.find(g=>g.id===role(item));
  group.bindings.push({index,item_id:item.id,definition_key:model.sha256,
   view:item.widget==='number'?'numeric':{status:'state',enum:'state',text:'information',structure:'structure'}[item.widget]||'definition',
   source:item.source,index_address:item.index??null,subindex:item.subindex??null,
   layout:item.layout??null,write_enabled:false});
 });
 return {definition_key:model.sha256,layout:layout?.id??null,groups,pending,
  condition:layout?.condition||[],hardware_verified:false};
}
const api={compose,role,sections};if(typeof module!=='undefined')module.exports=api;else global.IoddDeviceDashboard=api;
})(globalThis);

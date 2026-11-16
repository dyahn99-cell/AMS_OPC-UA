/* Offline widget library. Mounts accept definition + sample, never a transport. */
(function(global){
'use strict';
const numericTypes=new Set(['IntegerT','UIntegerT','Float32T','Float64T']);
function views(item){
 if(item.widget==='number')return ['numeric','focus','gauge','trend','counter',...(item.source==='ACYCLIC'?['parameter-number']:[])];
 return {enum:['state','parameter-select'],status:['state'],text:['information'],structure:['structure'],unresolved:['definition']}[item.widget]||['definition'];
}
function interpret(item,value){
 if(value===null||value===undefined||value==='')return {quality:'unavailable',text:'미수신'};
 const dt=item.datatype||{},type=dt.type;
 if(type==='unresolved'||item.widget==='unresolved')return {quality:'unresolved',text:'정의 해석 필요'};
 if(type==='RecordT'||type==='ArrayT'||item.widget==='structure')return {quality:'unresolved',text:'복합 항목 · 하위 정의 확인'};
 if(type==='BooleanT'){
  const yes=value===true||value==='true'||value===1||value==='1',no=value===false||value==='false'||value===0||value==='0';
  if(!yes&&!no)return {quality:'invalid',text:'유효하지 않은 논리값'};
  const choice=(dt.choices||[]).find(c=>String(c.value)===(yes?'true':'false')||String(c.value)===(yes?'1':'0'));
  return {quality:'good',text:choice?.label||(yes?'ON':'OFF')};
 }
 if(numericTypes.has(type)){
  const n=Number(value);if(!Number.isFinite(n)||(['IntegerT','UIntegerT'].includes(type)&&!Number.isInteger(n)))return {quality:'invalid',text:'유효하지 않은 값'};
  if(['IntegerT','UIntegerT'].includes(type)&&!Number.isSafeInteger(n))return {quality:'unresolved',text:'정밀 정수 해석 필요'};
  const bits=Number(dt.bitLength);if(type==='UIntegerT'&&n<0)return {quality:'invalid',text:'부호 없는 값에 음수 입력'};
  if(Number.isInteger(bits)&&bits>0&&bits<=53&&['IntegerT','UIntegerT'].includes(type)){
   const lo=type==='IntegerT'?-(2**(bits-1)):0,hi=type==='IntegerT'?2**(bits-1)-1:2**bits-1;
   if(n<lo||n>hi)return {quality:'invalid',text:'자료형 범위 밖'};
  }
  const choice=(dt.choices||[]).find(c=>Number(c.value)===n);
  if(choice)return {quality:dt.ranges?.length?'special':'good',text:choice.label||('별도 코드 '+choice.value)};
  if(dt.ranges?.length&&!dt.ranges.some(r=>n>=Number(r.lowerValue)&&n<=Number(r.upperValue)))return {quality:'invalid',text:'정의 범위 밖'};
  if(item.widget==='enum')return {quality:'invalid',text:'정의되지 않은 코드'};
  return {quality:'good',text:n.toLocaleString('ko-KR',{maximumFractionDigits:8}),number:n};
 }
 if(type==='StringT'||type==='OctetStringT')return {quality:'good',text:String(value)};
 return {quality:'unresolved',text:'지원하지 않는 자료형'};
}
function sample(item){
 const dt=item.datatype||{};if(item.widget==='enum')return dt.choices?.[0]?.value??null;
 if(dt.type==='BooleanT')return false;
 if(item.widget==='text')return 'DEMO';
 if(item.widget==='structure'||item.widget==='unresolved')return null;
 const range=dt.ranges?.[0];if(range){const n=(Number(range.lowerValue)+Number(range.upperValue))/2;return Number.isFinite(n)?Math.trunc(n):null;}
 return 0;
}
function mount(container,binding){
 const live=binding.readOnly===true;
 const item=binding.item;let view=views(item).includes(binding.view)?binding.view:views(item)[0],history=[],current=binding.sample===undefined?sample(item):binding.sample;
 function node(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
 const card=node('article','iw-card'),head=node('div','iw-head'),title=node('h3','',item.name||item.id),badge=node('span','iw-badge',item.source);head.append(title,badge);card.append(head);
 card.append(node('small','',binding.model+' · '+(item.index?'Index '+item.index:'Layout '+(item.layout??'—'))));
 const switcher=node('select');switcher.setAttribute('aria-label','위젯 표시 형태');const labels={numeric:'수치',focus:'대표값 + 추이',gauge:'게이지',trend:'추이',counter:'누적값 표시',state:'상태',information:'정보',structure:'복합 항목',definition:'정의 확인','parameter-select':'선택 파라미터','parameter-number':'수치 파라미터'};
 for(const key of views(item)){const o=node('option','',labels[key]);o.value=key;switcher.append(o);}switcher.value=view;card.append(switcher);
 let engineeringConfirmed=false,currentEngineering=null,lastTimestamp=0,historyUnit='raw';
 const rule=binding.engineeringRule;
 if(rule&&global.IoddEngineering){const label=node('label'),check=node('input');check.type='checkbox';label.append(check,node('span','','수동 구성 확인: V_Unit='+rule.unit_code+' / '+rule.unit+' · 단위 변환 적용'));card.append(label);check.addEventListener('change',()=>{engineeringConfirmed=check.checked;paint();});}
 const value=node('div','iw-value');value.setAttribute('aria-live','polite');card.append(value);
 const visual=node('div','iw-visual'),status=node('p','iw-status');card.append(visual,status);
 const label=node('label','','모의 원시값'),control=node(item.widget==='enum'||item.widget==='status'?'select':'input');
 if(item.widget==='enum'||item.widget==='status'){
  const options=item.widget==='status'?['false','true'].map(v=>({value:v,label:interpret(item,v).text})):item.datatype.choices||[];
  for(const c of options){const o=node('option','',(c.label||'코드')+' ('+c.value+')');o.value=String(c.value);control.append(o);}
 }else control.type=item.widget==='number'?'number':'text';
 control.value=current===null?'':String(current);control.disabled=['structure','unresolved'].includes(item.widget);control.step='any';label.append(control);label.hidden=live;control.disabled=live||control.disabled;card.append(label);
 const buttons=node('div','iw-actions'),read=node('button','','모의 샘플 추가'),clear=node('button','','미수신 상태');buttons.append(read,clear);buttons.hidden=live;read.disabled=live;clear.disabled=live;card.append(buttons);
 if(item.source==='ACYCLIC'||item.source==='PD OUT'){const disabled=node('button','','실물 쓰기 미연결');disabled.disabled=true;buttons.append(disabled);}
 if(item.widget==='structure'){
  const details=node('details'),summary=node('summary','','하위 항목 정의');details.append(summary);
  for(const child of item.datatype.items||[]){const row=node('div','iw-record',child.name+' · '+child.datatype.type+' · subindex '+(child.subindex??'—'));details.append(row);}
  if(!item.datatype.items?.length)details.append(node('p','','배열/복합 타입은 원본 정의에서 확인'));card.append(details);
 }
 const details=node('details'),summary=node('summary','','IODD 연결 정의'),pre=node('pre');summary.textContent='IODD 연결 정의';pre.textContent=JSON.stringify({definition_key:binding.definition_key,engineering_rule:rule,...item},null,2);details.append(summary,pre);card.append(details);
 card.append(node('p','iw-note',(live?'수신 값 · 확인된 단위·배율만 적용 · 읽기 전용':rule?'모의 값 · 단위 변환은 수동 구성 확인 후 적용 · 실물 쓰기 없음':'모의 값 · 단위/배율 미적용 · 실물 쓰기 없음')+(item.condition?.length?' · 조건부 PD: 실제 조건 확인 필요':'')));
 function paint(){
  const result=interpret(item,current);value.textContent=result.text+(result.number!==undefined?' raw':'');value.dataset.quality=result.quality;
  const convertNumber=n=>currentEngineering?.quality==='good'?{quality:'good',value:Number((n*currentEngineering.scale+currentEngineering.offset).toPrecision(12)),unit:currentEngineering.unit}:engineeringConfirmed?global.IoddEngineering.convert(rule,n,{V_Unit:rule.unit_code}):{quality:'good',value:n,unit:'raw'};
  if(currentEngineering?.quality==='good'&&result.number!==undefined){value.textContent=currentEngineering.value.toLocaleString('ko-KR',{maximumFractionDigits:8})+' '+currentEngineering.unit;value.title='원시값 '+result.number.toLocaleString('ko-KR');}
  if(engineeringConfirmed&&result.number!==undefined){const converted=convertNumber(result.number);if(converted.quality==='good')value.textContent=converted.value+' '+converted.unit;else{value.textContent='변환 조건 확인 필요';value.dataset.quality='unresolved';}}
  status.textContent=result.quality==='good'?(live?'수신 값 · ':'모의 값 · ')+(item.accessRights||item.accessRightRestriction||'접근 권한 별도 확인'):result.text;visual.replaceChildren();
  if(view==='gauge'){
   const range=item.datatype.ranges?.[0];if(result.number===undefined||!range){visual.append(node('small','','숫자 범위가 확인돼야 게이지를 표시합니다.'));return;}
   const a=convertNumber(Number(range.lowerValue)),b=convertNumber(Number(range.upperValue)),v=convertNumber(result.number);
   if([a,b,v].some(x=>x.quality!=='good')){visual.append(node('small','','변환 범위 확인 필요'));return;}
   const lo=Math.min(a.value,b.value),hi=Math.max(a.value,b.value),p=node('progress');p.max=100;p.value=hi>lo?Math.max(0,Math.min(100,100*(v.value-lo)/(hi-lo))):0;p.setAttribute('aria-label',item.name+' '+v.unit+' 범위');visual.append(p,node('small','',lo+' — '+hi+' '+v.unit+' · 첫 정의 범위'));
  }
  if(view==='focus'){paintFocus(result,convertNumber);return;}
  if(view==='trend'){
   const nums=history.filter(h=>h.number!==undefined).map(h=>convertNumber(h.number)).filter(h=>h.quality==='good').map(h=>({number:h.value}));if(nums.length<2){visual.append(node('small','',live?'수신 2회부터 추이를 표시합니다': '모의 값을 바꾼 후 샘플을 추가하세요. 2개 이상에서 그래프를 표시합니다.'));return;}
   const unit=currentEngineering?.quality==='good'?currentEngineering.unit:engineeringConfirmed?rule.unit:'raw';
   const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 300 110');svg.setAttribute('role','img');svg.setAttribute('aria-label',(live?'실제 수신':'모의 샘플')+' 추이 '+unit);
   const min=Math.min(...nums.map(n=>n.number)),max=Math.max(...nums.map(n=>n.number)),span=max-min||1;
   const poly=document.createElementNS('http://www.w3.org/2000/svg','polyline');poly.setAttribute('points',nums.map((h,i)=>`${10+i*280/(nums.length-1)},${85-(h.number-min)/span*65}`).join(' '));poly.setAttribute('fill','none');poly.setAttribute('stroke','currentColor');poly.setAttribute('stroke-width','2');svg.append(poly);visual.append(svg,node('small','',`${live?'실제 수신':'모의 샘플'} ${nums.length}개 · ${min}–${max} ${unit} · 최근 수집 순서`));
  }
  if(view==='counter')visual.append(node('small','','장비 값 그대로 표시 · 의미상 누적 항목인지 별도 확인 · 자동 합산/초기화 없음'));
 }
 function paintFocus(result,convertNumber){
  const unit=currentEngineering?.quality==='good'?currentEngineering.unit:'raw';
  const header=node('div','focus-chart-heading');header.append(node('span','',live?'최근 수신 추이':'모의 샘플 추이'),node('small','',unit));visual.append(header);
  const valid=history.filter(h=>h.number!==undefined).map(h=>({...h,n:convertNumber(h.number).value}));
  if(valid.length<2){const empty=node('div','focus-chart-empty');empty.append(node('span','',result.number===undefined?'수신을 기다리고 있습니다':'추이를 수집하고 있습니다'),node('small','',live?'실제 값이 두 번 이상 수신되면 그래프가 표시됩니다.':'모의 샘플을 두 번 이상 추가하면 표시됩니다.'));visual.append(empty);return;}
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 640 190');svg.setAttribute('role','img');svg.setAttribute('aria-label',item.name+(live?' 실제 수신 추이 ':' 모의 샘플 추이 ')+unit);
  const lo=Math.min(...valid.map(h=>h.n)),hi=Math.max(...valid.map(h=>h.n)),pad=(hi-lo)*.14||Math.max(Math.abs(lo)*.02,1),bottom=lo-pad,top=hi+pad;
  const first=history[0].timestamp,last=history[history.length-1].timestamp,span=Math.max(1,last-first);
  const x=t=>52+(t-first)/span*574,y=n=>151-(n-bottom)/(top-bottom)*132;
  const make=(tag,attrs,text)=>{const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;svg.append(e);return e;};
  for(let i=0;i<3;i++){const n=bottom+(top-bottom)*i/2;make('line',{x1:52,x2:626,y1:y(n),y2:y(n),stroke:'currentColor',opacity:'.13'});make('text',{x:44,y:y(n)+3,'text-anchor':'end','font-size':9,fill:'currentColor',opacity:'.65'},n.toLocaleString('ko-KR',{maximumFractionDigits:2}));}
  // Invalid samples and pauses remain visible as gaps, not invented continuity.
  let segments=[],segment=[],previous=null;
  for(const h of history){if(h.number===undefined||previous&&h.timestamp-previous.timestamp>5000){if(segment.length)segments.push(segment);segment=[];}if(h.number!==undefined)segment.push({t:h.timestamp,n:convertNumber(h.number).value});previous=h;}if(segment.length)segments.push(segment);
  for(const seg of segments){make('polyline',{points:seg.map(h=>x(h.t)+','+y(h.n)).join(' '),fill:'none',stroke:'currentColor','stroke-width':2.5,'stroke-linejoin':'round'});if(seg.length===1)make('circle',{cx:x(seg[0].t),cy:y(seg[0].n),r:2.5,fill:'currentColor'});}
  make('text',{x:52,y:180,'font-size':10,fill:'currentColor',opacity:'.65'},new Date(first).toLocaleTimeString());make('text',{x:626,y:180,'text-anchor':'end','font-size':10,fill:'currentColor',opacity:'.65'},new Date(last).toLocaleTimeString());visual.append(svg);
  const stats=node('div','focus-statistics');for(const [label,n] of [['최소',lo],['최대',hi],['평균',valid.reduce((a,h)=>a+h.n,0)/valid.length]]){const e=node('span','',label+' ');e.append(node('strong','',n.toLocaleString('ko-KR',{maximumFractionDigits:2})));stats.append(e);}visual.append(stats);
 }
 function setSample(v,info={}){current=v;currentEngineering=info.engineering||null;const unit=currentEngineering?.quality==='good'?JSON.stringify([currentEngineering.unit,currentEngineering.scale,currentEngineering.offset]):'raw';if(v===null){history=[];lastTimestamp=0;}if(historyUnit!==unit){history=[];historyUnit=unit;}if(live&&Number.isFinite(info.timestamp)&&info.timestamp>lastTimestamp){history.push({...interpret(item,v),timestamp:info.timestamp});history=history.slice(-60);lastTimestamp=info.timestamp;}control.value=v===null?'':String(v);paint();}
 control.addEventListener('input',()=>{current=control.value;paint();binding.onSample?.(current);});control.addEventListener('change',()=>{current=control.value;paint();binding.onSample?.(current);});switcher.addEventListener('change',()=>{view=switcher.value;card.classList.toggle('iw-focus',view==='focus');paint();});
 read.addEventListener('click',()=>{binding.onSample?.(current);history.push({...interpret(item,current),timestamp:Date.now()});history=history.slice(-30);paint();});clear.addEventListener('click',()=>{setSample(null);binding.onSample?.(null);});
 card.classList.toggle('iw-focus',view==='focus');container.append(card);paint();return {setSample,setView(next){if(views(item).includes(next)){view=next;switcher.value=next;card.classList.toggle('iw-focus',next==='focus');paint();}},destroy(){card.remove();},element:card};
}
const api={interpret,mount,views,sample};if(typeof module!=='undefined')module.exports=api;else global.IoddWidgets=api;
})(globalThis);

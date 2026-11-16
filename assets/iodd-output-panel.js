/* One transport-independent output UI for EXW1 contacts and IODD PD OUT. */
(function(g){
'use strict';
function mount({context,before,onSnapshot,available=()=>true}){
 const $=id=>document.getElementById(id);let target=null,snapshot=null,busy=false,expires,job=null,watch,locked=null,selected=new Set();
 const workflow=document.createElement('div');workflow.className='output-workflow';workflow.setAttribute('aria-label','출력 조작 단계');
 for(const [n,label] of [[1,'출력 조회'],[2,'조작 허용'],[3,'접점 조작']]){const step=document.createElement('span');step.dataset.step=n;step.textContent=n+' · '+label;workflow.append(step);}$('output-target').after(workflow);
 const image=()=>snapshot?.[target?.kind==='iolink'?'bytes':'words'];
 async function request(path,q){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Read-Token':g.readToken},body:JSON.stringify(q)}),d=await r.json();if(!r.ok){const e=Error(d.error||'출력 요청 실패');e.status=r.status;throw e;}return d;}
 function lock(){if(locked)return;locked=[...document.querySelectorAll('main input,main select,main button')].map(el=>[el,el.disabled]);locked.forEach(([el])=>el.disabled=true);}
 function unlock(){locked?.forEach(([el,disabled])=>el.disabled=disabled);locked=null;}
 function contacts(){return !snapshot?[]:target.kind==='iolink'?snapshot.contacts:Array.from({length:snapshot.bits},(_,bit)=>({key:String(bit),bit,label:'OUT '+bit}));}
 function contactValue(c){if(target.kind!=='iolink')return !!(snapshot.words[c.bit>>4]&(1<<(c.bit%16)));const v=snapshot.fields.find(f=>f.item===c.item)?.value;return c.bit===null?!!v:!!(v&(1<<c.bit));}
 function command(c,value){if(target.kind!=='iolink')return {bit:c.bit,value};let v=snapshot.fields.find(f=>f.item===c.item).value;v=c.bit===null?value:value?v|(1<<c.bit):v&~(1<<c.bit);return {item:c.item,value:v};}
 function reset(){if(job)return;snapshot=null;clearTimeout(expires);$('output-arm').checked=false;$('output-status').textContent='미조회 · 출력 조회 후 조작하세요';$('output-contacts').replaceChildren();$('output-fields').replaceChildren();onSnapshot?.(null);}
 function configure(){if(job||busy)return;const next=context();if(JSON.stringify(next?.target)!==JSON.stringify(target)){reset();selected.clear();target=next?.target||null;}$('output-panel').hidden=!target;if(!target)return;$('output-target').textContent=next.label;paint();}
 function accept(d){
  if(d.channel!==target.channel||d.model!==target.model||d.outputOffset!==target.outputOffset||!Number.isFinite(d.timestamp))throw Error('출력 응답 대상 불일치');
  if(target.kind==='iolink'&&(d.port!==target.port||d.definition!==target.definition||d.layout!==target.layout||d.portOutputOffset!==target.portOutputOffset||d.portOutputBytes!==target.portOutputBytes||d.bytes?.length!==target.portOutputBytes))throw Error('포트 출력 응답 대상 불일치');
  if(target.kind!=='iolink'&&(!Array.isArray(d.words)||d.words.length!==nextSize()))throw Error('출력 길이 불일치');
  snapshot=d;onSnapshot?.(d);clearTimeout(expires);if(!job)expires=setTimeout(()=>{reset();$('output-status').textContent='30초 경과 · 다시 조회하세요';paint();},30000);
 }
 function nextSize(){return target?.model==='valve'?2:1;}
 function allowed(){return !busy&&!job&&snapshot&&$('output-arm').checked&&Date.now()-snapshot.timestamp<30000;}
 function paint(){
  const host=$('output-contacts');host.replaceChildren();$('output-fields').replaceChildren();
  for(const step of workflow.children)step.dataset.active=String(Number(step.dataset.step)===(snapshot?($('output-arm').checked?3:2):1));
  host.dataset.ready=String(!!snapshot);
  if(!snapshot){const empty=document.createElement('p');empty.className='output-awaiting';empty.textContent='출력을 조회하면 접점 상태와 ON/OFF 버튼이 표시됩니다.';host.append(empty);}

  for(const c of contacts()){
   const box=document.createElement('div');box.className='bit-explanation'+(contactValue(c)?' is-on':'');box.style.display='inline-block';
   const check=document.createElement('input');check.type='checkbox';check.checked=selected.has(c.key);check.disabled=busy||!!job;check.setAttribute('aria-label',c.label+' 테스트 선택');check.onchange=()=>{check.checked?selected.add(c.key):selected.delete(c.key);paint();};
   const label=document.createElement('strong');label.textContent=c.label+' · '+(contactValue(c)?'ON':'OFF');box.append(check,label);
   for(const [name,value] of [['ON',true],['OFF',false]]){const b=document.createElement('button');b.textContent=name;b.setAttribute('aria-label',c.label+' '+name);b.disabled=!allowed();b.onclick=()=>operate(command(c,value));box.append(b);}host.append(box);
  }
  if(target?.kind==='iolink')for(const f of snapshot?.fields||[]){
   const item=context()?.model.items.find(i=>i.id===f.item),row=document.createElement('p');
   row.textContent=item.name+' · '+(f.value===null?'해석 미지원':String(f.value))+' raw · ';
   if(f.writable&&item.datatype.type!=='BooleanT'){
    const dt=item.datatype,input=document.createElement(dt.choices?.length&&!dt.ranges?.length?'select':'input');
    if(input.tagName==='SELECT')for(const c of dt.choices)input.append(new Option(c.label+' (코드 '+c.value+')',c.value));else{input.type=dt.type==='OctetStringT'?'text':'number';input.step='1';}
    input.value=f.value;input.setAttribute('aria-label',item.name+' 새 출력값');input.disabled=!allowed();
    const b=document.createElement('button');b.textContent='적용';b.disabled=!allowed();b.onclick=()=>{if(dt.type==='OctetStringT'){const hex=input.value.replace(/\s/g,'');if(!/^[0-9A-Fa-f]+$/.test(hex)||hex.length!==Number(dt.fixedLength)*2){$('output-status').textContent=dt.fixedLength+'바이트 HEX를 입력하세요';return;}operate({item:item.id,value:input.value});return;}if(input.value.trim()===''||!Number.isSafeInteger(Number(input.value))){$('output-status').textContent='정수를 입력하세요';return;}const v=Number(input.value),check=IoddWidgets.interpret(item,v);if(!['good','special'].includes(check.quality)){$('output-status').textContent=check.text;return;}operate({item:item.id,value:v});};
    row.append(input,b,document.createTextNode(' · 허용: '+(dt.type==='OctetStringT'?dt.fixedLength+'바이트 HEX · 내부 비트 의미는 원본 매뉴얼 확인':dt.ranges?.length?dt.ranges.map(r=>r.lowerValue+'…'+r.upperValue).join(' / '):dt.choices?.length?'선택 코드':'자료형 '+dt.bitLength+'비트')));
   }else if(f.writable&&item.datatype.type==='BooleanT'&&!contacts().some(c=>c.item===item.id))for(const [name,v] of [['ON',true],['OFF',false]]){const b=document.createElement('button');b.textContent=name;b.disabled=!allowed();b.onclick=()=>operate({item:item.id,value:v});row.append(b);}
   $('output-fields').append(row);
  }
  $('output-read').disabled=busy||!!job;$('output-arm').disabled=busy||!!job;$('output-test-select').disabled=busy||!!job||!snapshot;
  $('output-test-start').disabled=!allowed()||selected.size<1||selected.size>32;$('output-test-stop').disabled=!job;
  $('output-test-interval').disabled=busy||!!job;
 }
 async function operate(change=null){
  if(busy||job||!target)return;if(!available()){$('output-status').textContent='진행 중인 읽기가 완료된 후 다시 조작하세요';return;}if(change&&!allowed()){reset();paint();return;}before();busy=true;lock();paint();
  $('output-status').textContent=change?'출력 전송 · 재조회 중…':'실제 출력 맵·값 조회 중…';
  try{const d=await request(change?'/output-write':'/output-read',{...target,...change,...(change?{expected:image()}:{})});accept(d);if(change&&!d.verified)throw Error('출력 메모리 재조회 불일치');$('output-status').textContent=(change?'출력 적용·재조회 일치':'실제 출력 맵·값 조회 완료')+' · '+new Date(d.timestamp).toLocaleTimeString();}
  catch(e){reset();$('output-status').textContent=e.message+' · 다시 조회하세요';}
  finally{busy=false;unlock();paint();}
 }
 async function start(){
  if(!allowed()||!selected.size)return;if(!available()){$('output-status').textContent='진행 중인 읽기가 완료된 후 테스트하세요';return;}const interval=Number($('output-test-interval').value);if(!Number.isInteger(interval)||interval<200||interval>5000){$('output-status').textContent='간격은 200–5,000ms 입니다';return;}
  before();busy=true;lock();clearTimeout(expires);paint();
  try{job=await request('/output-test-start',{target,contacts:[...selected],interval,expected:image()});sessionStorage.setItem('ams.output-test',job.id);busy=false;paint();pollJob();}
  catch(e){busy=false;unlock();$('output-status').textContent=e.message;paint();}
 }
 async function pollJob(){
  if(!job)return;try{
   job=await request('/output-test-status',{id:job.id});if(!target)target=job.target;$('output-panel').hidden=false;$('output-target').textContent='CH'+target.channel+(target.port?' · P'+target.port:'')+' · 출력 테스트';$('output-status').textContent=job.label+' · '+job.step+'/'+job.total+' · '+({'running':'순차 ON/OFF 중','stopping':'중지 · OFF 확인 중','completed':'완료','cancelled':'중지 완료','failed':'실패'}[job.state]||job.state)+(job.error?' · '+job.error:'')+(job.cleanup==='off_unconfirmed'?' · OFF 미확인 — 장비에서 확인 필요':job.cleanup==='off_verified'?' · OFF 재조회 일치':'');
   if(['running','stopping'].includes(job.state)){paint();watch=setTimeout(pollJob,500);return;}
   const d=job.snapshot;job=null;sessionStorage.removeItem('ams.output-test');unlock();if(d)accept(d);else{snapshot=null;$('output-arm').checked=false;}configure();paint();
  }catch(e){if(e.status===422){job=null;sessionStorage.removeItem('ams.output-test');snapshot=null;unlock();$('output-arm').checked=false;configure();paint();$('output-status').textContent='서버 테스트 상태 없음 · OFF 미확인 — 장비에서 확인하고 다시 조회하세요';return;}$('output-status').textContent='테스트 상태 조회 실패: '+e.message+' · 서버의 유한 테스트는 계속 종료를 시도합니다';watch=setTimeout(pollJob,1500);}
 }
 $('output-read').onclick=()=>operate();$('output-arm').onchange=paint;$('output-test-start').onclick=start;
 $('output-test-select').onclick=()=>{selected=new Set(contacts().slice(0,32).map(c=>c.key));paint();};
 $('output-test-stop').onclick=async()=>{if(!job)return;try{await request('/output-test-stop',{id:job.id});$('output-status').textContent='중지 요청 · 현재 접점 OFF 확인 중…';}catch(e){$('output-status').textContent=e.message;}};
 // A page reload must still expose the server-owned test's stop/status controls.
 const pending=sessionStorage.getItem('ams.output-test');if(pending){job={id:pending};lock();$('output-panel').hidden=false;pollJob();}
 return {configure,reset,active:()=>busy||!!job};
}
g.IoddOutputPanel={mount};
})(globalThis);

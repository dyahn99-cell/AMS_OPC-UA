/* ISDU payload boundary. No assumed EXW1-RL wire codes and no device writes. */
(function(g){
'use strict';
const statusNames=['정상','유지보수 필요','사양 범위 초과','기능 점검','고장'];
const qualifierNames=['측정 범위 내','측정 범위 밖 · 앞쪽','측정 범위 밖 · 케이블쪽','동작 범위 밖'];
const eventNames={6144:'커넥터 0–7 과전류',6145:'커넥터 8–15 과전류',6224:'입력 횟수 초과',6225:'오토 스위치 이상',20753:'제어/입력 전원 저하'};
function plan(review){
 return (review?.required_reads||[]).map(r=>({...r,length:r.index===37?15:1,kind:r.index===36?'device_status':r.index===229?'position_qualifier':'events'}));
}
function decode(spec,bytes){
 if(!Array.isArray(bytes)||bytes.length!==spec.length||!bytes.every(b=>Number.isInteger(b)&&b>=0&&b<=255))throw Error('invalid_payload');
 if(spec.kind==='device_status'){
  if(bytes[0]>4)throw Error('unknown_device_status');
  return {value:bytes[0],text:statusNames[bytes[0]],severity:bytes[0]===0?'normal':bytes[0]===4?'error':'warning'};
 }
 if(spec.kind==='position_qualifier'){
  if(bytes[0]>3)throw Error('unknown_position_qualifier');
  return {value:bytes[0],text:qualifierNames[bytes[0]],severity:bytes[0]===0?'normal':'warning'};
 }
 if(spec.kind!=='events')throw Error('unsupported_payload');
 const events=[];
 for(let i=0;i<bytes.length;i+=3){
  const qualifier=bytes[i],code=bytes[i+1]*256+bytes[i+2];
  if(qualifier===0&&code===0)continue;
  const mode=qualifier>>6,type=(qualifier>>4)&3,source=(qualifier>>3)&1,instance=qualifier&7;
  events.push({qualifier,code,mode,type,source,instance,text:(source===0&&instance===4?eventNames[code]:null)||'미등록 이벤트 0x'+code.toString(16).padStart(4,'0'),active:mode===3,severity:type===3?'error':type===2?'warning':type===1?'notice':'unknown'});
 }
 return {events,text:events.length?events.map(e=>e.text).join(' / '):'이벤트 없음'};
}
function identity(c){return ['master','revision','base','channel','port','definition'].map(k=>[k,c[k]]);}
async function read(context,review,reader,{now=Date.now,timeout=3000,maxAge=30000}={}){
 if(!context||review?.definition_key!==context.definition||typeof context.master!=='string'||!Number.isInteger(context.revision)||!Number.isInteger(context.port)||context.port<1||context.port>4||!Number.isInteger(context.channel)||context.channel<1||context.channel>127||context.revision<0||!context.master||typeof context.base!=='string'||!context.base)throw Error('invalid_context');
 if(!Number.isFinite(timeout)||timeout<=0||timeout>30000||!Number.isFinite(maxAge)||maxAge<0)throw Error('invalid_timing');
 const frozen=structuredClone(context),specs=plan(review),fields=[];
 if(!specs.length)throw Error('diagnostic_plan_unavailable');
 for(const spec of specs){
  const request={...frozen,index:spec.index,subindex:spec.subindex,operation:'read',requestId:globalThis.crypto.randomUUID()};
  let timer;
  try{
   if(typeof reader!=='function')throw Error('transport_unavailable');
   const response=await Promise.race([Promise.resolve().then(()=>reader(structuredClone(request))),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('timeout')),timeout);})]);
   if(JSON.stringify(identity(context))!==JSON.stringify(identity(frozen)))throw Error('configuration_changed');
   if(!response||identity(request).some(([k,v])=>response[k]!==v)||response.index!==spec.index||response.subindex!==spec.subindex||response.requestId!==request.requestId)throw Error('identity_mismatch');
   if(response.connected!==true||response.error)throw Error(response.error?'device_read_error':'disconnected');
   const time=now();
   if(!Number.isFinite(response.timestamp)||!Number.isFinite(time)||response.timestamp>time)throw Error('invalid_timestamp');
   if(time-response.timestamp>maxAge)throw Error('stale');
   fields.push({...spec,quality:'good',timestamp:response.timestamp,...decode(spec,response.bytes)});
  }catch(error){fields.push({...spec,quality:error.message,value:null,timestamp:null});}
  finally{clearTimeout(timer);}
 }
 if(JSON.stringify(identity(context))!==JSON.stringify(identity(frozen)))return {context:frozen,source:'ACYCLIC',fields:specs.map(s=>({...s,quality:'configuration_changed',value:null,timestamp:null}))};
 return {context:frozen,source:'ACYCLIC',fields};
}
function mount(host,review){
 const el=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
 const box=el('section',''),title=el('h3','제품 진단'),status=el('p',review?({pd_applied:'PD 진단 적용',acyclic_required:'비주기 응답 해석 구현 · 전송 미연결',evidence_conflict:'문서 불일치 · 측정값 보류',evidence_pending:'추가 근거 필요'}[review.status]||review.status)+' · '+review.reason:'진단 근거 없음');box.append(title,status);host.append(box);
 if(!review)return;
 const specs=plan(review);
 for(const spec of specs){
  const row=el('div',''),label=el('p',`비주기 ${spec.index}/${spec.subindex} · ${spec.length}바이트 · 수신값 없음`),input=el('input',''),button=el('button','모의 응답 해석'),result=el('pre','');
  input.placeholder='모의 HEX 입력';input.setAttribute('aria-label',`${spec.index}/${spec.subindex} 모의 응답`);
  button.onclick=()=>{try{const value=input.value.trim();if(!/^[0-9a-fA-F]{2}(?:\s+[0-9a-fA-F]{2})*$/.test(value))throw Error('HEX 바이트를 입력하세요');result.textContent='모의 데이터 · 실제 수신 아님\n'+JSON.stringify(decode(spec,value.split(/\s+/).map(v=>parseInt(v,16))),null,2);}catch(e){result.textContent=e.message;}};
  row.append(label,input,button,result);box.append(row);
 }
 if(specs.length)box.append(el('p','실제 비주기 전송 미연결 · PD 갱신과 별도 · 이 진단값으로 PD 측정값을 자동 정상 처리하지 않음'));
}
const api={plan,decode,read,mount};if(typeof module!=='undefined')module.exports=api;else g.IoddAcyclicDiagnostics=api;
})(globalThis);

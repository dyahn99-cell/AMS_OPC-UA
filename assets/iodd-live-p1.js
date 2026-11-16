(async()=>{
const $=id=>document.getElementById(id);let models=[],widgets=[],generation=0,timer,busy=false,pollTimer=null,polling=false,inspectorCache=null;
function report(phase,extra={}){window.dispatchEvent(new CustomEvent('iodd-live-state',{detail:{phase,channel:Number($('channel').value),port:Number($('port').value),...extra}}));}
try{const r=await fetch('/connection');if(r.ok)window.connectionProfile=await r.json();}catch(e){}
window.connectionProfile ||= {host:'192.168.0.10',port:502,unit:1,timeout:4,refreshMs:1000};
window.connectionKey=window.connectionProfile.host+(window.connectionProfile.port===502&&window.connectionProfile.unit===1?'':'.p'+window.connectionProfile.port+'.u'+window.connectionProfile.unit);
window.dispatchEvent(new CustomEvent('iodd-connection-loaded',{detail:window.connectionProfile}));
function stopPolling(){polling=false;clearTimeout(pollTimer);$('stop').disabled=true;}
function scheduleRead(){if(polling)pollTimer=setTimeout(()=>$('read').onclick(),window.connectionProfile.refreshMs);}
$('stop').onclick=()=>{stopPolling();$('status').textContent+=' · 자동 갱신 중지';report('paused');};
window.addEventListener('ex600-config-changed',()=>{stopPolling();clear();});
const topologyKey='ams.live.'+window.connectionKey+'.remote-map.v1';
let topology={diagnostic:10,rows:Array.from({length:15},(_,i)=>({model:i===0?'rla':'',input:i===0?64:0,output:i===0?64:0}))},mapError='';
try{const saved=JSON.parse(localStorage.getItem(topologyKey)||'null');if(saved){if(saved.rows?.length!==15)throw Error('채널 구성 오류');RemoteMap.calculate(saved);topology=saved;}}catch(e){mapError='저장된 구성 오류: 실제 등록 구성을 다시 확인하세요';}
function remote(){return RemoteMap.calculate(topology)[activeChannel-1];}
function syncMap(){
 try{const rows=RemoteMap.calculate(topology);mapError='';for(const r of rows){const tr=$('remote-row-'+r.channel);if(tr){tr.querySelector('.input-start').textContent=r.registered&&r.input?r.inputStart:'—';tr.querySelector('.output-start').textContent=r.registered&&r.output?r.outputStart:'—';}}
 const r=rows[activeChannel-1];$('channel-offset').value=r.registered?r.inputStart:'';if(r.registered){$('total-in').value=r.input;$('total-out').value=r.output;}$('total-in').readOnly=$('total-out').readOnly=true;
 $('remote-map-status').textContent='등록 '+rows.filter(r=>r.registered).length+'개 · 할당 바이트 기준 자동 계산';
 }catch(e){mapError=e.message;$('remote-map-status').textContent=mapError;$('read').disabled=true;}
}
function mountMap(){
 $('base-diagnostic').value=topology.diagnostic;
 topology.rows.forEach((r,i)=>{const tr=document.createElement('tr');tr.id='remote-row-'+(i+1);tr.innerHTML='<td>CH'+(i+1)+'</td><td><select aria-label="CH'+(i+1)+' 리모트"></select></td><td><input class="size-in" type="number" step="2" aria-label="입력 할당"></td><td><input class="size-out" type="number" step="2" aria-label="출력 할당"></td><td class="input-start"></td><td class="output-start"></td>';
 const sel=tr.querySelector('select'),a=tr.querySelector('.size-in'),b=tr.querySelector('.size-out');sel.append(new Option('미등록',''));for(const [key,p] of Object.entries(RemoteMap.profiles))sel.append(new Option(p.name,key));sel.value=r.model;
 const thumb=document.createElement('button'),image=document.createElement('img');thumb.type='button';thumb.className='channel-product-thumb';thumb.append(image);sel.before(thumb);thumb.onclick=()=>{$('channel').value=String(i+1);$('channel').onchange();window.dispatchEvent(new CustomEvent('iodd-channel-selected'));$('remote-visual').scrollIntoView({behavior:'smooth',block:'center'});};
 const sizes=()=>{const asset=ProductVisuals.remote(r);thumb.hidden=!asset;if(asset){image.src='/assets/product-models/'+asset.poster;image.alt=asset.part;thumb.setAttribute('aria-label','CH'+(i+1)+' '+asset.part+' 보기');}else image.removeAttribute('src');const p=RemoteMap.profiles[r.model];a.value=r.input;b.value=r.output;a.disabled=b.disabled=!p?.max;a.min=b.min=p?.min||2;a.max=b.max=p?.max||130;};sizes();
 const update=()=>{stopPolling();clear();syncMap();if(!mapError){try{localStorage.setItem(topologyKey,JSON.stringify(topology));}catch(e){}render();}};
 sel.onchange=()=>{r.model=sel.value;const p=RemoteMap.profiles[r.model];r.input=p?.input||0;r.output=p?.output||0;sizes();update();};a.onchange=b.onchange=()=>{r.input=Number(a.value);r.output=Number(b.value);update();};$('remote-rows').append(tr);});
 $('base-diagnostic').onchange=()=>{stopPolling();clear();topology.diagnostic=Number($('base-diagnostic').value);syncMap();if(!mapError){try{localStorage.setItem(topologyKey,JSON.stringify(topology));}catch(e){}render();}};syncMap();
}
function remoteView(){
 syncMap();let r;try{r=remote();}catch(e){r={registered:false};}const io=r.registered&&r.profile.kind==='iolink';mountOutput(r);report('context',{remote:r,model:selected(),assignments:Object.entries({1:{},2:{},3:{},4:{},...portSettings,[activePort]:{...portSettings[activePort],definition:$('model').value}}).map(([port,c])=>({port:Number(port),definition:c.definition,name:models.find(m=>m.sha256===c.definition)?.name||'',model:models.find(m=>m.sha256===c.definition),layout:port===activePort?$('layout').value:c.layout,swap:port===activePort?$('swap').value:c.swap,enabled:c.monitorEnabled!==false,input:Number($('in-'+port)?.value||0),output:Number($('out-'+port)?.value||0)}))});
 RemoteVisual.mount({remote:r,product:selected(),port:Number($('port').value),enabled:portSettings[activePort]?.monitorEnabled!==false,onSelect:n=>{$('port').value=String(n);$('port').onchange();window.dispatchEvent(new CustomEvent('iodd-port-selected'));},onEnable:enabled=>{stopPolling();portSettings[activePort]={...portSettings[activePort],monitorEnabled:enabled};savePort();render();}});
 for(const id of ['port','search','model','cards','diagnostic-details','open-settings','settings','pinned-panel','product-definition'])$(id).hidden=!io;
 $('test-mode').parentElement.hidden=!io;$('byte-map').parentElement.hidden=!io;$('remote-panel').hidden=io;
 if(io){for(const option of $('port').options)option.disabled=r.model.startsWith('rlb')&&Number(option.value)>2;return true;}
 $('remote-title').textContent=r.registered?r.profile.name:'미등록 채널';renderRemoteInputs(r);
 $('remote-note').textContent=!r.registered?'위 구성표에서 실제 등록된 리모트를 선택하세요.':r.profile.kind==='output'?'출력 '+(r.output*8)+'점 · 아래 수동 출력 패널에서 조회하고 ON/OFF할 수 있습니다.':r.profile.kind==='modular'?'EX600-W 전체 할당은 구성표에서, AMB 위치와 센서 환산은 아래 모듈 설정에서 지정하세요.':r.profile.kind==='analog'?'4채널 바이트 원시값 표시 · 단위·스케일 해석은 전용 맵 확인 후 연결합니다.':'입력 원시 데이터 확인 · 장비의 바이트 순서 설정과 대조하세요.';
 $('read').disabled=busy||!!mapError||!r.registered||!r.input;return false;
}
function renderRemoteInputs(r,bytes=null,quality='unknown'){
 const host=$('remote-values'),kind=r?.profile?.kind;
 if(!r?.registered||!['digital','analog'].includes(kind)){host.replaceChildren();host.dataset.frameKey='';return;}
 const key=r.channel+':'+r.model;
 if(host.dataset.frameKey!==key){
  host.replaceChildren();host.dataset.frameKey=key;host.dataset.kind=kind;
  if(kind==='digital')for(let b=0;b<Math.ceil((r.profile.bits||16)/8);b++){
   const group=document.createElement('section');group.className='remote-byte-group';
   const heading=document.createElement('h3');heading.textContent='BYTE '+b+' · IN '+b*8+'–'+Math.min(b*8+7,(r.profile.bits||16)-1);group.append(heading);
   const grid=document.createElement('div');grid.className='remote-contact-grid';group.append(grid);
   for(let bit=b*8;bit<Math.min(b*8+8,r.profile.bits||16);bit++){
    const el=document.createElement('div');el.dataset.inputBit=bit;el.className='bit-explanation remote-contact';
    const name=document.createElement('strong');name.textContent='IN '+bit;
    const value=document.createElement('span');value.className='remote-contact-value';
    const address=document.createElement('small');address.textContent='B'+b+' · bit '+bit%8;el.append(name,value,address);grid.append(el);
   }host.append(group);
  }
  else for(let n=0;n<4;n++){
   const el=document.createElement('section');el.className='remote-analog-card';el.dataset.inputAnalog=n;
   const name=document.createElement('h3');name.textContent='CH'+(n+1);
   const value=document.createElement('strong');value.className='remote-analog-value';
   const address=document.createElement('small');address.textContent='B'+n*2+'–B'+(n*2+1)+' · 2바이트';
   const note=document.createElement('p');note.textContent='전압·전류 변환 맵 확인 전 · 원시값';el.append(name,value,address,note);host.append(el);
  }
  if(kind==='digital'&&r.input>2){const note=document.createElement('p');note.className='input-extra';host.append(note);}
 }
 host.dataset.quality=quality;
 if(kind==='digital')for(const el of host.querySelectorAll('[data-input-bit]')){
  const bit=Number(el.dataset.inputBit),on=bytes?!!(bytes[bit>>3]&(1<<(bit%8))):null;
  el.classList.toggle('is-on',on===true);el.dataset.state=on===null?'unknown':on?'on':'off';
  const label=on===null?'—':on?'ON':'OFF';const value=el.querySelector('.remote-contact-value');if(value.textContent!==label)value.textContent=label;
  el.setAttribute('aria-label','IN '+bit+' · '+(on===null?'미수신':label));
 }
 else for(const el of host.querySelectorAll('[data-input-analog]')){
  const n=Number(el.dataset.inputAnalog),text=bytes?'HEX '+bytes.slice(n*2,n*2+2).map(b=>b.toString(16).padStart(2,'0').toUpperCase()).join(' '):'—';
  const value=el.querySelector('.remote-analog-value');if(value.textContent!==text)value.textContent=text;
 }
 const extra=host.querySelector('.input-extra');if(extra)extra.textContent=bytes?'추가 알림 원시 바이트: '+bytes.slice(2).map(b=>b.toString(16).padStart(2,'0').toUpperCase()).join(' '):'추가 알림 영역 · 조회 후 표시';
}
async function readRemote(){
 if(busy)return;let r;try{if(mapError)throw Error(mapError);r=remote();}catch(e){$('status').textContent=e.message;return;}if(!r.registered||!r.input)return;
 const gen=generation;busy=true;polling=true;$('stop').disabled=false;$('read').disabled=true;clearTimeout(pollTimer);
 try{const res=await fetch('/read',{method:'POST',headers:{'Content-Type':'application/json','X-Read-Token':window.readToken},body:JSON.stringify({channel:r.channel,inputOffset:r.inputStart,inputBytes:r.input})}),data=await res.json();if(gen!==generation)return;if(!res.ok)throw Error(data.error);if(data.channel!==r.channel||data.inputOffset!==r.inputStart||!Array.isArray(data.bytes)||data.bytes.length!==r.input||data.bytes.some(b=>!Number.isInteger(b)||b<0||b>255)||!Number.isFinite(data.timestamp))throw Error('응답 대상/데이터 형식 오류');
 RemoteVisual.input(data);report('sample',{timestamp:data.timestamp,kind:r.profile.kind,inputOffset:data.inputOffset,bytes:data.bytes});const host=$('remote-values'),bytes=data.bytes;
 const fresh=Date.now()-data.timestamp<30000;renderRemoteInputs(r,fresh?bytes:null,fresh?'received':'stale');if(!fresh)report('stale');if(!['digital','analog'].includes(r.profile.kind))host.textContent=fresh?'HEX '+bytes.map(b=>b.toString(16).padStart(2,'0').toUpperCase()).join(' '):'데이터 만료';
 $('raw').textContent=JSON.stringify(data,null,2);$('status').textContent='CH'+r.channel+' · '+r.input+'바이트 수신 · '+new Date(data.timestamp).toLocaleTimeString();clearTimeout(timer);timer=setTimeout(()=>{renderRemoteInputs(r,null,'stale');if(!['digital','analog'].includes(r.profile.kind))host.textContent='수신 후 30초 경과 · 데이터 만료';report('stale');},30000);
 }catch(e){if(gen===generation){RemoteVisual.clear();renderRemoteInputs(r,null,'error');if(!['digital','analog'].includes(r.profile.kind))$('remote-values').textContent='미수신';RemoteVisual.clear();$('status').textContent='읽기 실패: '+e.message;report('error',{message:e.message});}}finally{busy=false;if(gen===generation)$('read').disabled=false;else render();scheduleRead();}
}
const liveUnits=IoddLiveUnits.create();
const outputModels=new Set(['rdy','rdyg','rdm','rdmg','rdmgn','valve']);
function outputContext(){
 if(mapError)return null;
 const r=remote();if(!r.registered)return null;
 if(outputModels.has(r.model))return {target:{channel:r.channel,model:r.model,outputOffset:r.outputStart},bytes:r.output,label:'CH'+r.channel+' · '+r.profile.name+' · 출력 시작 '+r.outputStart+'B'};
 if(r.profile.kind!=='iolink')return null;
 const m=selected(),layout=m?.layouts.find(l=>String(l.id)===$('layout').value);if(!layout?.directions.some(d=>d.source==='PD OUT'))return null;
 try{const a=allocation(),port=Number($('port').value),slot=a.ports[port-1];return {model:m,target:{kind:'iolink',channel:r.channel,model:r.model,port,definition:m.sha256,layout:layout.id,swap:$('swap').value,totalOutput:a.output,outputOffset:r.outputStart,portOutputOffset:slot.outputStart,portOutputBytes:slot.output},label:'CH'+r.channel+' · P'+port+' · '+m.name+' · PD OUT'};}catch(e){return null;}
}
const outputPanel=IoddOutputPanel.mount({context:outputContext,before:stopPolling,available:()=>!busy&&!pinsBusy,onSnapshot:d=>{if(d)report('output',{timestamp:d.timestamp,kind:'output',snapshot:d});if(d&&!d.bytes)RemoteVisual.output(d);else RemoteVisual.clearOutput();}});
function resetOutput(){outputPanel.reset();}
function mountOutput(){outputPanel.configure();}
const initialParams=new URLSearchParams(location.hash.slice(1));
let activeChannel=Number(initialParams.get('channel')||1);if(!Number.isInteger(activeChannel)||activeChannel<1||activeChannel>15)activeChannel=1;
for(let ch=1;ch<=15;ch++)$('channel').append(new Option('CH'+ch,ch));$('channel').value=String(activeChannel);
const channelKey=kind=>'ams.live.'+window.connectionKey+'.ch'+activeChannel+'.'+kind+'.v1';
let allocationKey=channelKey('allocation');
for(let p=1;p<=4;p++){$('allocation-ports').insertAdjacentHTML('beforeend',`<div>P${p} <label>입력 바이트 <input id="in-${p}" type="number" min="0" max="32" value="${p<=2?16:0}"></label><label>출력 바이트 <input id="out-${p}" type="number" min="0" max="32" value="${p<=2?16:0}"></label></div>`);}
const allocationIds=['channel-offset','total-in','total-out',...Array.from({length:4},(_,i)=>['in-'+(i+1),'out-'+(i+1)]).flat()];
try{const saved=JSON.parse(localStorage.getItem(allocationKey)||'{}');for(const id of allocationIds)if(Number.isInteger(saved[id]))$(id).value=saved[id];}catch(e){}
function allocation(){
 if(mapError)throw Error(mapError);const selectedRemote=remote();if(!selectedRemote.registered||selectedRemote.profile.kind!=='iolink')throw Error('IO-Link 리모트를 선택하세요');
 const inputOffset=$('channel-offset').value===''?NaN:Number($('channel-offset').value);if(!Number.isInteger(inputOffset)||inputOffset<0)throw Error('선택한 채널의 입력 시작 위치를 확인해서 입력하세요');
 const total=selectedRemote.input,output=selectedRemote.output;let inputStart=2,outputStart=2;const ports=[];const limit=selectedRemote.model.endsWith('1')?14:32;
 for(let p=1;p<=4;p++){const input=Number($('in-'+p).value),out=Number($('out-'+p).value);if(!Number.isInteger(input)||input<0||input>limit||!Number.isInteger(out)||out<0||out>limit)throw Error('포트 크기는 0–32 정수입니다');if(selectedRemote.model.startsWith('rlb')&&p>2&&(input||out))throw Error('Class B는 P1/P2만 사용합니다');ports.push({input,output:out,start:inputStart,outputStart});inputStart+=input;outputStart+=out;}
 if(!Number.isInteger(total)||total<2||total>130||!Number.isInteger(output)||output<2||output>130)throw Error('전체 크기는 2–130 정수입니다');
 if(inputStart>total||outputStart>output)throw Error('상태 2바이트 + 포트 할당 합계가 전체 크기를 초과합니다 (입력 '+inputStart+' / 출력 '+outputStart+')');
 if(inputOffset+total>1440)throw Error('입력 위치와 크기가 1440바이트를 초과합니다');return {total,output,ports,inputOffset};
}
function showAllocation(){try{const a=allocation();$('allocation-map').textContent=a.ports.map((p,i)=>'P'+(i+1)+' 입력 위치 '+(a.inputOffset+p.start)+' / 채널 내 출력 위치 '+p.outputStart+' (바이트)').join(' · ');}catch(e){$('allocation-map').textContent=e.message;}}
showAllocation();
for(const id of allocationIds)$(id).oninput=()=>{stopPolling();clear();showAllocation();try{allocation();localStorage.setItem(allocationKey,JSON.stringify(Object.fromEntries(allocationIds.map(id=>[id,Number($(id).value)]))));}catch(e){$('status').textContent=e.message;}};
let pinnedController=null,pinsBusy=false,pinsRefreshPending=false,pinsLastRead=0;
let isduSnapshot=null;
function choiceLabel(c){const labels={'L_min':'L/min (리터/분)','G_min':'gal/min (갤런/분)','HYS':'히스테리시스','Hysteresis':'히스테리시스','Window comparator':'윈도 비교','OFF':'꺼짐','ON':'켜짐'};return labels[c.label]||c.label||('코드 '+c.value);}
function resetSetting(){isduSnapshot=null;$('isdu-apply').disabled=true;$('isdu-edit').value='';const {dt,access}=setting(),choices=dt?.choices||[],enumerated=choices.length>0&&!dt?.ranges?.length;
 $('isdu-choice').replaceChildren(new Option('설정 선택',''));for(const c of choices)$('isdu-choice').append(new Option(choiceLabel(c)+' (코드 '+c.value+')',String(c.value)));
 $('isdu-choice').hidden=!enumerated;$('isdu-edit').hidden=enumerated;
 $('isdu-help').textContent=access==='ro'?'읽기 전용 설정':enumerated?'이름으로 선택하세요. 장비에는 해당 코드가 전송됩니다.':dt?.ranges?.length?'허용 범위: '+dt.ranges.map(r=>Number(r.lowerValue).toLocaleString()+' ~ '+Number(r.upperValue).toLocaleString()).join(' / ')+' · 원시 정수 기준':'현재 편집은 정수 설정을 지원합니다.';
}

function setting(){const m=selected(),parts=$('isdu-item').value.split('|'),parent=m?.items.find(i=>i.id===parts[0]),subindex=Number(parts[1]||0),child=subindex?parent?.datatype.items.find(i=>Number(i.subindex)===subindex):null;return {model:m,item:parent,subindex,dt:child?.datatype||parent?.datatype,name:child?parent.name+' / '+child.name:parent?.name,access:child?.accessRightRestriction||parent?.accessRights};}
function clear(){report('idle');try{renderRemoteInputs(remote());}catch(e){$('remote-values').replaceChildren();}liveUnits.invalidate();pinnedController?.destroy();pinnedController=null;RemoteVisual.clear();resetOutput();resetSetting();inspectorCache=null;generation++;clearTimeout(timer);widgets.forEach(w=>{w.lastField=null;w.widget.setSample(null);w.preview.textContent='';w.widget.element.classList.remove('bit-on');w.onBadge.hidden=true;});$('raw').textContent='';$('byte-map').replaceChildren();$('bit-detail').textContent='수신 후 바이트를 선택하세요';$('status').textContent='연결 대기 · ‘연결 · 자동 갱신’을 누르세요';}
function inspectBytes(packet,start,m,layoutId,swap,size){
 const layout=m.layouts.find(l=>l.id===layoutId),direction=layout.directions.find(d=>d.source==='PD IN');
 const length=Math.ceil(Number(direction?.bitLength||0)/8),slot=IoddPdDecoder.normalize(packet.bytes.slice(start,start+size),swap);
 const items=m.items.filter(i=>i.source==='PD IN'&&i.layout===layoutId);
 const cacheKey=[m.sha256,layoutId,start,swap,size].join(':');
 if(inspectorCache?.key===cacheKey){
  const cache=inspectorCache,changed=cache.slot[cache.selected]!==slot[cache.selected];
  slot.forEach((value,i)=>{if(cache.slot[i]!==value)cache.buttons[i].textContent='B'+i+' · '+value.toString(16).padStart(2,'0').toUpperCase();cache.slot[i]=value;});
  if(changed)cache.buttons[cache.selected]?.click();return;
 }

 const host=$('byte-map');host.replaceChildren();
 const ranges=new Map();
 for(const item of items){const offset=Number(item.bitOffset),bits=item.datatype.type==='BooleanT'?1:Number(item.datatype.bitLength);if(!Number.isInteger(offset)||!Number.isInteger(bits)||bits<1)continue;
  const first=length-Math.ceil((offset+bits)/8),last=length-1-Math.floor(offset/8);if(first<0||last>=length)continue;
  const key=first+':'+last;if(!ranges.has(key))ranges.set(key,{first,last,names:[]});ranges.get(key).names.push(item.name);
 }
 const groups=[];for(let i=0;i<size;i++){
  const matches=[...ranges.values()].filter(r=>i>=r.first&&i<=r.last),key=i>=length?'padding':matches.map(r=>r.first+':'+r.last).join('|')||'reserved';
  let group=groups[groups.length-1];if(!group||group.key!==key){group={key,first:i,last:i,names:[...new Set(matches.flatMap(r=>r.names))]};groups.push(group);}else group.last=i;
 }
 const containers=new Map();const colors=['#006bb6','#7759c4','#c58a28','#408bb0'];
 for(const [n,group] of groups.entries()){
  const box=document.createElement('section'),title=document.createElement('div');box.style.cssText='display:inline-block;vertical-align:top;margin:8px;padding:12px;border:1px solid '+colors[n%colors.length]+';border-radius:10px';
  const names=group.names.map(name=>({Accumulated:'누적량',Flow:'순간 유량'}[name]||name));
  title.textContent=(group.key==='padding'?'여유 영역':group.key==='reserved'?'미정의 영역':names.length>2?'상태·진단':names.join(' / '))+' · B'+group.first+(group.last!==group.first?'–B'+group.last:'');title.title=names.join(' / ');box.append(title);host.append(box);
  for(let i=group.first;i<=group.last;i++)containers.set(i,box);
 }
 const buttons=[];
 for(let index=0;index<size;index++){
  const button=document.createElement('button');button.textContent='B'+index+' · '+slot[index].toString(16).padStart(2,'0').toUpperCase();
  if(index>=length){button.disabled=true;button.title='포트 여유 영역 · IODD 해석 제외';button.style.opacity='.35';}
  button.onclick=()=>{
   if(inspectorCache)inspectorCache.selected=index;
   const base=(length-1-index)*8,detail=$('bit-detail');detail.replaceChildren();const heading=document.createElement('p');heading.textContent='Byte '+index+' · '+slot[index].toString(2).padStart(8,'0')+' · 실제 PD '+length+'바이트 기준';detail.append(heading);let hidden=0;
   for(let bit=7;bit>=0;bit--){const globalBit=base+bit,item=items.find(i=>{const offset=Number(i.bitOffset),bits=i.datatype.type==='BooleanT'?1:Number(i.datatype.bitLength);return globalBit>=offset&&globalBit<offset+bits;});if(!item){hidden++;continue;}
    const on=!!(slot[index]&(1<<bit)),row=document.createElement('div');row.className='bit-explanation'+(on?' is-on':'');row.textContent='bit '+bit+' · g'+globalBit+' · '+(on?'● ON':'○ OFF')+' · '+item.name+(item.datatype.type==='BooleanT'?'':' · 값 비트');detail.append(row);
   }
   if(hidden){const note=document.createElement('p');note.textContent='IODD 미정의 비트 '+hidden+'개 해석 제외';detail.append(note);}
  };containers.get(index).append(button);buttons.push(button);
 }
 inspectorCache={key:cacheKey,slot,buttons,selected:Math.max(0,length-2)};
 if(length)buttons[inspectorCache.selected].click();
}
function selected(){return models.find(m=>m.sha256===$('model').value);}
function render(){stopPolling();clear();$('cards').replaceChildren();$('state-cards').replaceChildren();widgets=[];if(!remoteView())return;const m=selected(),layout=m?.layouts.find(l=>String(l.id)===$('layout').value);$('read').disabled=busy||!layout||portSettings[activePort]?.monitorEnabled===false;$('condition').textContent=layout?'선택 레이아웃 조건: '+JSON.stringify(layout.condition)+' · 실제 제품 설정과 일치해야 합니다.':'';showProduct();if(!layout)return;
let focusKey='';const preferenceKey='ams.focus.'+activeChannel+'.'+activePort+'.'+m.sha256;try{focusKey=localStorage.getItem(preferenceKey)||'';}catch(e){}
const plan=IoddPresentation.plan(m,layout.id,focusKey),items=plan.fields.filter(x=>x.item.source==='PD IN'),measurements=plan.measurements,primary=plan.primary;
const signalHost=role=>{const id=role==='diagnostic'?'signal-diagnostics':'signal-states';let grid=$(id);if(!grid){const section=document.createElement('section'),heading=document.createElement('h3');heading.textContent=role==='diagnostic'?'제품 진단':'동작·출력 상태';grid=document.createElement('div');grid.id=id;grid.className='signal-grid';section.append(heading,grid);$('state-cards').append(section);}return grid;};
$('diagnostic-details').hidden=!plan.states.length&&!plan.diagnostics.length;
for(const {item,binding} of items){if(!item)continue;const widget=IoddWidgets.mount(binding.role==='measurement'?$('cards'):signalHost(binding.role),{readOnly:true,model:m.name,definition_key:m.sha256,item:{...item,name:binding?.label||item.name},view:item===primary?.item?'focus':binding?.default_view||IoddWidgets.views(item)[0],sample:null});widget.element.dataset.signalKind=binding.signal_kind||'neutral';widget.element.dataset.itemId=item.id;widget.element.dataset.role=binding?.role||(item.widget==='number'?'measurement':'state');if(item===primary?.item)widget.element.classList.add('primary-measurement');if(measurements.some(x=>x.item===item)){const focus=document.createElement('button');focus.type='button';focus.className='focus-select';focus.textContent=item===primary?.item?'대표 지표':'대표로 보기';focus.setAttribute('aria-pressed',String(item===primary?.item));focus.onclick=()=>{try{localStorage.setItem(preferenceKey,item.id);}catch(e){}for(const w of widgets){if(w.widget.element.parentElement!==$('cards'))continue;const yes=w.item.id===item.id;w.widget.element.classList.toggle('primary-measurement',yes);w.widget.setView(yes?'focus':'numeric');const b=w.widget.element.querySelector('.focus-select');if(b){b.textContent=yes?'대표 지표':'대표로 보기';b.setAttribute('aria-pressed',String(yes));}}};widget.element.prepend(focus);}const preview=document.createElement('p');preview.className='sample-preview';widget.element.append(preview);const onBadge=document.createElement('strong');onBadge.className='bit-on-badge';onBadge.textContent='● ON';onBadge.hidden=true;widget.element.prepend(onBadge);widgets.push({widget,item,preview,onBadge});}}
function showProduct(){
 const m=selected(),p=IoddPresentation.profile(m);$('product-outputs').replaceChildren();
 $('product-summary').textContent=p?[m.name,p.version.version,p.version.releaseDate,'Device ID '+m.deviceId,...p.categories,'측정'+' '+p.capabilities.measurements,'상태 '+p.capabilities.states,'진단 '+p.capabilities.diagnostics,'출력 '+p.capabilities.pd_outputs].join(' · '):'제품 선택 후 표시 항목을 구성합니다.';
 for(const b of p?.pd.filter(b=>b.source==='PD OUT'&&String(b.layout)===$('layout').value)||[]){const item=m.items.find(i=>i.id===b.item),row=document.createElement('p');row.textContent=b.label+' · Layout '+b.layout+' · bit '+item.bitOffset+' · '+item.datatype.type; $('product-outputs').append(row);}
 mountPinned();mountOutput();
}
function mountPinned(){
 pinnedController?.destroy();pinnedController=null;pinsLastRead=0;const m=selected();$('pinned-cards').replaceChildren();$('read-pins').disabled=!m||pinsBusy;
 if(!m){$('pins-status').textContent='제품을 선택하세요';return;}
 pinnedController=IoddPresentation.mountSettings($('pinned-cards'),{channel:activeChannel,port:Number(activePort),model:m,onEdit:key=>openSettings(key),onSample:d=>window.dispatchEvent(new CustomEvent('iodd-setting-sample',{detail:{...d,channel:activeChannel,port:Number(activePort),definition:m.sha256}})),read:async q=>{const r=await fetch('/isdu',{method:'POST',headers:{'Content-Type':'application/json','X-Read-Token':window.readToken},body:JSON.stringify(q)});const d=await r.json();if(!r.ok)throw Error(d.error||'읽기 실패');return d;}});
 $('read-pins').disabled=pinsBusy||!pinnedController.count;$('pins-status').textContent=pinnedController.count?pinnedController.count+'개 선택 · 미수신 · 연결 시 30초 간격으로 조회':'PD만 표시 중 · 필요한 설정값을 선택해 추가하세요';
}
async function refreshPins(){
 if(pinsBusy||!pinnedController?.count)return;
 pinsBusy=true;$('read-pins').disabled=true;const controller=pinnedController,gen=generation;pinsLastRead=Date.now();
 try{const r=await controller.read();if(gen===generation&&r)$('pins-status').textContent=r.ok+'/'+r.total+'개 조회 완료 · '+new Date().toLocaleTimeString()+' · 설정은 30초 간격';}
 finally{pinsBusy=false;if(pinsRefreshPending){pinsRefreshPending=false;mountPinned();}$('read-pins').disabled=!pinnedController?.count;}
}
$('read-pins').onclick=()=>{if(!busy)return refreshPins();};
function syncPins(){if(!selected())return;if(pinsBusy){pinsRefreshPending=true;return;}mountPinned();}
window.addEventListener('storage',e=>{if(selected()&&e.key===IoddPresentation.storageKey({channel:activeChannel,port:Number(activePort),model:selected()}))syncPins();});
window.addEventListener('iodd-pins-changed',e=>{if(selected()&&e.detail.key===IoddPresentation.storageKey({channel:activeChannel,port:Number(activePort),model:selected()}))syncPins();});
window.addEventListener('focus',()=>{if(pinnedController&&selected()&&JSON.stringify(pinnedController.keys)!==JSON.stringify(IoddPresentation.pins({channel:activeChannel,port:Number(activePort),model:selected()})))syncPins();});
function choose(){clear();$('isdu-value').textContent='미수신 · 조회만 가능';$('isdu-item').replaceChildren();for(const i of selected()?.items.filter(i=>i.source==='ACYCLIC'&&['ro','rw'].includes(i.accessRights))||[]){ $('isdu-item').append(new Option(i.name+' · '+i.index,i.id));if(i.datatype.type==='RecordT'&&i.datatype.subindexAccessSupported!=='false')for(const child of i.datatype.items)$('isdu-item').append(new Option(i.name+' / '+child.name,i.id+'|'+child.subindex)); }$('diag').checked=false;$('diag-option').hidden=!Object.keys(IoddDiagnosticProfiles[selected()?.sha256]?.required_configuration||{}).length;$('layout').replaceChildren();const empty=new Option('PD 레이아웃 선택','');$('layout').append(empty);for(const l of selected()?.layouts||[])$('layout').append(new Option('Layout '+l.id+' '+JSON.stringify(l.condition),String(l.id)));if(selected()?.layouts.length===1)$('layout').value=String(selected().layouts[0].id);render();if(selected()&&$('layout').value===''){$('settings').open=true;$('status').textContent='이 제품은 상세 설정에서 측정 형식을 선택해주세요';}}
let settingsKey=channelKey('port-settings');
let activePort=$('port').value,portSettings={};
try{const saved=JSON.parse(localStorage.getItem(settingsKey)||'{}');if(saved&&typeof saved==='object'&&!Array.isArray(saved))portSettings=saved;}catch(e){}
function savePort(){
 portSettings[activePort]={monitorEnabled:portSettings[activePort]?.monitorEnabled!==false,definition:$('model').value,layout:$('layout').value,swap:$('swap').value,diag:$('diag').checked,test:$('test-mode').checked};
 try{localStorage.setItem(settingsKey,JSON.stringify(portSettings));}catch(e){}
}
function modelOptions(query='',keep=''){
 $('model').replaceChildren(new Option('제품·IODD 버전 선택',''));
 for(const m of models.filter(m=>m.sha256===keep||m.name.toLowerCase().includes(query.toLowerCase())))$('model').append(new Option(m.name+(models.filter(x=>x.name===m.name).length>1?' · '+m.document.version+' / '+m.document.releaseDate+' / ID '+m.deviceId:''),m.sha256));
 $('model').value=keep;
}
function restorePort(){
 const saved=portSettings[activePort]||{};$('search').value='';modelOptions('',saved.definition||'');choose();
 if(selected()?.layouts.some(l=>String(l.id)===saved.layout))$('layout').value=saved.layout;
 $('swap').value=['direct','swap16','swap32','swapAll'].includes(saved.swap)?saved.swap:'direct';
 $('diag').checked=saved.diag===true;$('test-mode').checked=saved.test!==false;render();
}
function search(){modelOptions($('search').value,$('model').value);}
function loadChannelAllocation(){
 let saved={};try{saved=JSON.parse(localStorage.getItem(allocationKey)||'{}');}catch(e){}
 for(const id of allocationIds){const fallback=id==='channel-offset'?(activeChannel===1?10:''):id.startsWith('total-')?64:Number(id.slice(-1))<=2?16:0;$(id).value=Number.isInteger(saved?.[id])?saved[id]:fallback;}
 $('connection-label').textContent='CH'+activeChannel+' · '+window.connectionProfile.host;syncMap();showAllocation();
}
loadChannelAllocation();
$('channel').onchange=()=>{stopPolling();savePort();activeChannel=Number($('channel').value);allocationKey=channelKey('allocation');settingsKey=channelKey('port-settings');portSettings={};try{const saved=JSON.parse(localStorage.getItem(settingsKey)||'{}');if(saved&&typeof saved==='object'&&!Array.isArray(saved))portSettings=saved;}catch(e){}loadChannelAllocation();restorePort();history.replaceState(null,'','#'+new URLSearchParams({channel:activeChannel,port:activePort}));};
if(['1','2','3','4'].includes(initialParams.get('port'))){activePort=initialParams.get('port');$('port').value=activePort;}
$('port').onchange=()=>{savePort();activePort=$('port').value;restorePort();};
$('model').onchange=()=>{choose();savePort();};$('search').oninput=search;
for(const id of ['layout','swap','diag','test-mode'])$(id).onchange=()=>{render();savePort();};
$('read').onclick=async()=>{if(busy)return;if(pinsBusy){scheduleRead();return;}if(mapError){$('status').textContent=mapError;return;}if(remote().profile?.kind!=='iolink')return readRemote();if(portSettings[activePort]?.monitorEnabled===false){stopPolling();return;}clearTimeout(pollTimer);const gen=generation,m=selected(),selectedPort=Number($('port').value);if(!m)return;let a;try{a=allocation();}catch(e){stopPolling();$('status').textContent=e.message;return;}if(remote().model.startsWith('rlb')&&selectedPort>2){$('status').textContent='Class B는 P1/P2를 선택하세요';stopPolling();return;}const slot=a.ports[selectedPort-1];const c=IoddMasterConfig.create();c.input=2+slot.input;c.output=2+slot.output;Object.assign(c.ports[0],{enabled:true,mode:'manual',input:slot.input,output:slot.output,definition:m.sha256,layout:Number($('layout').value),swap:$('swap').value});const validation=IoddMasterConfig.validate(c,models);if(validation.errors.length){$('status').textContent=validation.errors.join(' / ');return;}polling=true;$('stop').disabled=false;const options={diagnosticPreview:$('test-mode').checked,diagnostics:$('diag').checked?{1:{V_diAG:1}}:{}};busy=true;$('read').disabled=true;if(!inspectorCache)$('status').textContent='실제 입력 읽는 중…';try{const units=await liveUnits.read({channel:activeChannel,port:selectedPort,model:m,layout:m.layouts.find(l=>l.id===c.ports[0].layout)});if(gen!==generation)return;options.units={1:units.values};options.conditionOK=units.conditionOK;options.diagnostics={1:{...options.diagnostics[1],...units.values}};$('condition').textContent=(units.conditionOK?'레이아웃 조건 확인':'레이아웃 조건 미확인')+' · 단위 설정 '+(units.values.V_Unit??'미확인')+(units.errors.length?' · '+units.errors.join(' / '):' · ISDU 조회');const r=await fetch('/read',{method:'POST',headers:{'Content-Type':'application/json','X-Read-Token':window.readToken},body:JSON.stringify({inputBytes:a.total,inputOffset:a.inputOffset,channel:activeChannel})}),packet=await r.json();if(gen!==generation)return;if(!r.ok)throw Error(packet.error||'읽기 실패');RemoteVisual.input(packet);// Project the selected 16-byte slot into the single-port decoder plan.
const start=slot.start,shift=2*(selectedPort-1);
if(![1,2,3,4].includes(selectedPort)||!Array.isArray(packet.bytes)||packet.bytes.length!==a.total)throw Error('포트 입력 길이 오류');
const projected={...packet,bytes:[(packet.bytes[0]>>shift)&3,(packet.bytes[1]>>shift)&3,...packet.bytes.slice(start,start+slot.input)]};
inspectBytes(packet,start,m,c.ports[0].layout,c.ports[0].swap,slot.input);const result=IoddPdDecoder.decode(c,models,projected,options),port={...result.ports[0],port:selectedPort};$('raw').textContent=JSON.stringify({timestamp:packet.timestamp,bytes:packet.bytes,selectedPort,inputOffsetInChannel:start,port},null,2);for(const w of widgets){const f=port.fields.find(f=>f.item_id===w.item.id);const signature=JSON.stringify(f);if(w.lastField===signature&&w.item.widget!=='number')continue;w.lastField=signature;const isOn=w.item.datatype.type==='BooleanT'&&(f?.quality==='good'?f.value===true:f?.preview?.value===true);w.widget.element.classList.toggle('bit-on',isOn);w.widget.element.dataset.signalEvidence=f?.quality==='good'?'received':f?.preview?'preview':'unavailable';w.onBadge.textContent=f?.quality==='good'?'● ON':'시험 ON';w.onBadge.hidden=!isOn;w.widget.setSample(f?.quality==='good'?f.value:null,{engineering:f?.engineering,timestamp:packet.timestamp});w.preview.textContent=f?.preview&&f.quality!=='good'?'시험 수신값: '+(typeof f.preview.value==='boolean'?(f.preview.value?'ON':'OFF'):String(f.preview.value))+(f.preview.interpretation!=='good'?' · '+(f.preview.label||f.preview.interpretation):''):'';}const blocked=port.fields.filter(f=>f.quality!=='good');const summaries=a.ports.map((allocated,i)=>{
 const n=i+1,saved=n===selectedPort?{definition:m.sha256,layout:c.ports[0].layout,swap:c.ports[0].swap}:portSettings[String(n)]||{},product=models.find(x=>x.sha256===saved.definition);
 const connected=!!(packet.bytes[0]&(1<<(2*i+1))),valid=!!(packet.bytes[1]&(1<<(2*i))),event=!!(packet.bytes[1]&(1<<(2*i+1)));
 if(!product||!product.layouts.some(l=>String(l.id)===String(saved.layout)))return {port:n,definition:saved.definition,connected,valid,event,fields:[]};
 if(n===selectedPort)return {...port,connected,valid,event};
 const cfg=IoddMasterConfig.create();cfg.input=2+allocated.input;cfg.output=2+allocated.output;Object.assign(cfg.ports[0],{enabled:saved.monitorEnabled!==false,mode:'manual',input:allocated.input,output:allocated.output,definition:product.sha256,layout:Number(saved.layout),swap:saved.swap||'direct'});
 const projectedPort={...packet,bytes:[(packet.bytes[0]>>(2*i))&3,(packet.bytes[1]>>(2*i))&3,...packet.bytes.slice(allocated.start,allocated.start+allocated.input)]};
 const decoded=IoddPdDecoder.decode(cfg,models,projectedPort,{conditionOK:false});return {...decoded.ports[0],port:n,definition:product.sha256,connected,valid,event};
});report('sample',{timestamp:packet.timestamp,kind:'iolink',blocked:blocked.length,portQuality:port.quality,ports:summaries});$('status').textContent='실제 '+a.total+'바이트 수신 · '+new Date(packet.timestamp).toLocaleTimeString()+(polling?' · '+(window.connectionProfile.refreshMs/1000)+'초 자동 갱신 · P':' · 자동 갱신 중지 · P')+selectedPort+' '+port.quality+(blocked.length?' · 값 보류: '+[...new Set(blocked.map(f=>f.quality))].join(', '):' · 원시값 표시');if(pinnedController?.count&&Date.now()-pinsLastRead>=30000)await refreshPins();if(gen!==generation)return;clearTimeout(timer);timer=setTimeout(()=>{widgets.forEach(w=>{w.lastField=null;w.widget.setSample(null);w.preview.textContent='';w.widget.element.classList.remove('bit-on');w.onBadge.hidden=true;});$('status').textContent='수신 후 30초 경과 · 다시 읽어주세요';report('stale');},Math.max(0,30000-(Date.now()-packet.timestamp)));}catch(e){if(gen===generation){widgets.forEach(w=>{w.lastField=null;w.widget.setSample(null);w.preview.textContent='';w.widget.element.classList.remove('bit-on');w.onBadge.hidden=true;});RemoteVisual.clear();$('status').textContent='읽기 실패: '+e.message;report('error',{message:e.message});}}finally{busy=false;if(gen===generation)$('read').disabled=!selected()||$('layout').value===''||portSettings[activePort]?.monitorEnabled===false;else render();scheduleRead();}};
$('isdu-item').onchange=()=>{resetSetting();$('isdu-value').textContent='미수신';};
$('isdu-read').onclick=async()=>{
 const {model,item,subindex,dt,name,access}=setting();if(!item)return;const settingKey=$('isdu-item').value;resetSetting();
 const gen=generation,port=Number($('port').value);$('isdu-read').disabled=true;$('isdu-value').textContent='설정값 읽는 중…';
 try{const response=await fetch('/isdu',{method:'POST',headers:{'Content-Type':'application/json','X-Read-Token':window.readToken},body:JSON.stringify({channel:activeChannel,port,definition:model.sha256,item:item.id,subindex})}),data=await response.json();
 if(gen!==generation||$('isdu-item').value!==settingKey)return;if(!response.ok)throw Error(data.error);
 if(data.port!==port||data.definition!==model.sha256||data.item!==item.id)throw Error('응답 대상 불일치');
 const bytes=data.bytes;let shown='HEX '+bytes.map(b=>b.toString(16).padStart(2,'0')).join(' ');
 if(['IntegerT','UIntegerT'].includes(dt.type)&&bytes.length===Math.ceil(Number(dt.bitLength)/8)&&Number(dt.bitLength)<=32){let n=bytes.reduce((a,b)=>a*256+b,0);if(dt.type==='IntegerT'&&n>=2**(Number(dt.bitLength)-1))n-=2**Number(dt.bitLength);const choice=dt.choices.find(c=>Number(c.value)===n);shown=choice?choiceLabel(choice)+' (코드 '+n+')':n.toLocaleString();$('isdu-edit').value=String(n);$('isdu-choice').value=String(n);}
 else if(dt.type==='Float32T'&&bytes.length===4)shown=String(new DataView(Uint8Array.from(bytes).buffer).getFloat32(0,false));
 else if(dt.type==='StringT')shown=new TextDecoder().decode(Uint8Array.from(bytes)).replace(/\0+$/,'');
 isduSnapshot={channel:activeChannel,port,definition:model.sha256,item:item.id,subindex,expected:bytes,settingKey};$('isdu-apply').disabled=access!=='rw'||!['IntegerT','UIntegerT'].includes(dt.type)||![8,16,32].includes(Number(dt.bitLength));
 $('isdu-value').textContent=name+': '+shown+' · P'+port+' · '+new Date(data.timestamp).toLocaleTimeString();
 }catch(e){if(gen===generation)$('isdu-value').textContent='조회 실패: '+e.message;}finally{$('isdu-read').disabled=false;}
};
$('isdu-apply').onclick=async()=>{
 const input=$('isdu-choice').hidden?$('isdu-edit'):$('isdu-choice');if(!isduSnapshot||input.value.trim()==='')return;
 const value=Number(input.value);if(!Number.isSafeInteger(value)){$('isdu-value').textContent='정수를 입력하세요';return;}
 const request={...isduSnapshot,value},gen=generation;stopPolling();$('isdu-apply').disabled=true;$('isdu-read').disabled=true;isduSnapshot=null;
 $('isdu-value').textContent='P'+request.port+' 설정 적용 후 다시 확인 중…';
 try{const r=await fetch('/isdu-write',{method:'POST',headers:{'Content-Type':'application/json','X-Read-Token':window.readToken},body:JSON.stringify(request)}),data=await r.json();if(gen!==generation||$('isdu-item').value!==request.settingKey)return;if(!r.ok)throw Error(data.error);$('isdu-value').textContent=data.verified?'P'+request.port+' 설정 적용·재조회 일치: '+(setting().dt.choices.find(c=>Number(c.value)===value)?choiceLabel(setting().dt.choices.find(c=>Number(c.value)===value)):value.toLocaleString()):'적용 후 값 불일치 · 다시 조회하세요';}
 catch(e){if(gen===generation)$('isdu-value').textContent='적용 확인 실패: '+e.message+' · 자동 재전송하지 않습니다. 다시 조회하세요.';}
 finally{$('isdu-read').disabled=false;}
};
function openSettings(item=''){const m=selected();if(!m){$('status').textContent='제품을 먼저 선택하세요';return;}stopPolling();window.open('/settings#'+new URLSearchParams({channel:activeChannel,port:$('port').value,definition:m.sha256,...(item?{item}:{})}),'_blank','noopener');}
$('open-settings').onclick=$('choose-pins').onclick=()=>openSettings();
window.addEventListener('storage',e=>{if(e.key==='ams.settings.changed'){liveUnits.invalidate();stopPolling();syncPins();widgets.forEach(w=>{w.lastField=null;w.widget.setSample(null);w.widget.element.classList.remove('bit-on');w.onBadge.hidden=true;w.preview.textContent='';});$('status').textContent='제품 설정 변경됨 · 다시 연결하여 단위·조건을 조회하세요';}});
window.addEventListener('pagehide',stopPolling);
ProductVisuals.mountBase();
mountMap();
try{const [r,,er]=await Promise.all([fetch('/catalog'),IoddPresentation.load(),fetch('/engineering')]);if(!r.ok||!er.ok)throw Error('제품 목록·배율 로드 실패');models=(await r.json()).models;const rules=await er.json();for(const m of models)m.engineering_rules=rules.filter(x=>x.definition_key===m.sha256);const initial=new URLSearchParams(location.hash.slice(1)).get('definition');if(!portSettings[activePort]&&initial&&models.some(m=>m.sha256===initial))portSettings[activePort]={definition:initial};restorePort();savePort();}catch(e){$('status').textContent=e.message;}
})();

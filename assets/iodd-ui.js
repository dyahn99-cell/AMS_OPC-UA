/* Page navigation consumes display metadata. It never reads or writes device memory. */
(()=>{
 const $=id=>document.getElementById(id),views=['overview','remote','monitor','output','engineering'];
 const initial=new URLSearchParams(location.hash.slice(1));
 let active=initial.has('definition')?'monitor':initial.has('channel')?'remote':'overview';
 let contextData=null,lastSample=null,phase='idle',visualKey='',scheduled=false;
 const portSamples=new Map(),settingSamples=new Map();
 const contextControls=document.querySelector('.context-controls'),contextHost=document.querySelector('.device-context');
 const observations=new Map(),tabs=Array.from(document.querySelectorAll('[data-workspace]'));
 const channelSummary=node('section','remote-channel-summary');channelSummary.id='ui-remote-summary';channelSummary.setAttribute('aria-label','선택 리모트 할당 및 수신 정보');contextHost.after(channelSummary);
 for(const [key,label] of [['allocation','입출력 할당'],['address','시작 위치'],['capacity','채널 구성'],['activity','현재 상태']]){const card=node('div','remote-summary-item');card.append(node('span','',label),node('strong','', '—'));card.dataset.summary=key;channelSummary.append(card);}
 function remoteSummary(){
  const r=contextData?.remote,p=remote(),io=p?.kind==='iolink';channelSummary.hidden=io||!r?.registered||!['monitor','output'].includes(active);if(channelSummary.hidden)return;
  const fresh=lastSample?.channel===current()&&Date.now()-lastSample.timestamp<30000&&phase!=='error'&&phase!=='stale';
  const set=(key,text)=>{const e=channelSummary.querySelector('[data-summary="'+key+'"] strong');if(e.textContent!==text)e.textContent=text;};
  set('allocation','IN '+r.input+' B / OUT '+r.output+' B');
  set('address','IN '+(r.input?r.inputStart+' B':'—')+' / OUT '+(r.output?r.outputStart+' B':'—'));
  set('capacity',p.kind==='modular'?'EX600-AMB · AI 2 / AO 2':p.kind==='analog'?'아날로그 4채널':p.kind==='digital'?'입력 '+(p.bits||16)+'점'+(r.output?' · 출력 '+(p.bits||r.output*8)+'점':''):p.kind==='output'?'출력 '+r.output*8+'점':'원시 데이터');
  let state='조회 전 · 미확인';
  if(phase==='error')state='조회 실패';else if(phase==='stale'||lastSample&&!fresh)state='데이터 만료';else if(fresh){
   if(lastSample.phase==='output'){const d=lastSample.snapshot;let on=0;if(d?.words)for(let bit=0;bit<d.bits;bit++)if(d.words[bit>>4]&(1<<(bit%16)))on++;state='출력 ON '+on+' / '+(d?.bits||r.output*8)+'점';}
   else if(p.kind==='digital'){let on=0;for(let bit=0;bit<(p.bits||16);bit++)if(lastSample.bytes?.[bit>>3]&(1<<(bit%8)))on++;state='입력 ON '+on+' / '+(p.bits||16)+'점';}
   else state=p.kind==='modular'?'모듈 입력 수신됨':'4채널 수신됨';if(phase==='paused')state+=' · 갱신 중지';
  }
  set('activity',state);channelSummary.dataset.state=fresh?'received':phase==='error'?'error':'unknown';
 }

 let displayedView=null;
 const reducedMotion=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
 function revealView(name){
  if(displayedView===name)return;displayedView=name;const panel=$('ui-'+name+'-view');
  if(reducedMotion())return;panel.getAnimations().forEach(a=>a.cancel());
  panel.animate([{opacity:.35,transform:'translateY(8px)'},{opacity:1,transform:'translateY(0)'}],{duration:220,easing:'cubic-bezier(.2,.8,.2,1)'});
  requestAnimationFrame(()=>{if(displayedView!==name||reducedMotion())return;const cards=panel.querySelectorAll('.port-summary-card,.channel-overview-card,.decision-strip>div');
  Array.from(cards).slice(0,15).forEach((card,i)=>card.animate([{opacity:.45,transform:'translateY(5px)'},{opacity:1,transform:'translateY(0)'}],{duration:200,delay:Math.min(i*35,175),easing:'ease-out'}));});
 }
 function setMetric(element,text){
  if(element.textContent===text)return;element.textContent=text;
  if(text==='—'||reducedMotion())return;
  element.getAnimations().forEach(a=>a.cancel());element.animate([{color:'#006bb6',backgroundColor:'#e5f2ff'},{color:getComputedStyle(element).color,backgroundColor:'transparent'}],{duration:550,easing:'ease-out'});
 }
 const current=()=>Number($('channel').value),locked=()=>$('channel').disabled;
 const remote=()=>RemoteMap.profiles[$('remote-row-'+current())?.querySelector('select')?.value];
 function show(name){
  if(!views.includes(name))return;if(name==='overview'&&location.hash)history.replaceState(null,'',location.pathname);active=name;document.body.dataset.page=name;
  for(const view of views)$('ui-'+view+'-view').hidden=view!==name;
  for(const tab of tabs){if(tab.dataset.workspace===name)tab.setAttribute('aria-current','page');else tab.removeAttribute('aria-current');}
  document.querySelector('.device-context').hidden=name==='overview'||name==='remote';
  const controlsHost=name==='remote'?$('ui-channel-actions'):contextHost;if(contextControls.parentElement!==controlsHost)controlsHost.append(contextControls);
  $('device-picker').hidden=name!=='monitor'||remote()?.kind!=='iolink';
  document.querySelector('.workspace-tabs').hidden=name==='overview';
  $('ui-page-title').textContent=name==='overview'?'전체 시스템':name==='remote'?'포트 연결 현황':name==='engineering'?'연결 구성 · 점검':name==='output'?'출력 조작':'디바이스 모니터링';
  $('ui-overview').setAttribute('aria-current',name==='overview'?'page':'false');revealView(name);
  remoteSummary();
  if(name==='monitor'&&remote()?.kind==='iolink'&&$('model').options.length>1&&!$('model').value)$('device-picker').open=true;
 }
 function configure(){if(locked())return;show('engineering');$('channel-config').open=true;$('channel-config').scrollIntoView({behavior:'smooth',block:'start'});}
 function selectChannel(n){if(locked())return;$('channel').value=String(n);$('channel').onchange();const p=remote();show(p?.kind==='iolink'?'remote':p?.kind==='output'?'output':'monitor');refresh();if(!p)configure();}
 function selectPort(n){if(locked())return;$('port').value=String(n);$('port').dispatchEvent(new Event('change',{bubbles:true}));show('monitor');}
 function statusFor(n){const o=observations.get(n);return !o?'미조회 · 연결 미확인':o.failed?'최근 조회 실패':Date.now()-o.timestamp>30000?'최근 수신 만료':(o.blocked?'일부 값 해석 보류':'최근 조회')+' · '+new Date(o.timestamp).toLocaleTimeString()+' · '+o.label;}
 function updateOverview(){
  const cards=Array.from(document.querySelectorAll('.channel-overview-card'));let observed=0,attention=0;
  for(const card of cards){const n=Number(card.dataset.channel),o=observations.get(n);card.querySelector('.channel-observation').textContent=statusFor(n);const state=!o?'unknown':o.failed?'error':Date.now()-o.timestamp>30000?'stale':o.blocked?'partial':'received';card.dataset.observation=state;if(o)observed++;if(['error','stale'].includes(state))attention++;}
  $('ui-stat-registered').textContent=cards.length;$('ui-stat-observed').textContent=observed;$('ui-stat-attention').textContent=attention;
 }
 function context(){
  const channel=current(),p=remote(),io=p?.kind==='iolink',model=contextData?.model;
  document.body.dataset.deviceKind=p?.kind||'unknown';
  const onRemote=active==='remote';
  $('ui-context-path').textContent='EXW1  /  CH '+String(channel).padStart(2,'0')+(io&&!onRemote?'  /  P'+$('port').value:'');
  const selectedName=$('model').selectedOptions[0]?.textContent;
  $('ui-product-name').textContent=io&&!onRemote?(model?.name||selectedName||'제품 선택'):p?.name||'미등록 채널';
  $('ui-context-note').textContent=onRemote?'포트별 연결 제품 · 핵심 PD · 선택한 설정값':io?'현재 측정값 · 변화 추이 · 관련 설정':p?.kind==='output'?'출력 메모리 상태 · 접점 조작':p?.kind==='modular'?'EX600-W / EX600-AMB · 입력 CH0·CH1':p?.kind==='analog'?'아날로그 입력 4채널 · 단위·스케일 확인 전 원시값':'입력 접점 상태';
  if(io&&!onRemote&&$('model').value&&!$('layout').value)$('ui-context-note').textContent='측정 형식 선택 필요 · 구성·점검 → 상세 설정';
  const plan=io&&model?IoddPresentation.plan(model,$('layout').value):null;$('ui-measurement-title').textContent=io?(plan?.measurements.length?'측정 현황':'디바이스 상태'):p?.kind==='modular'?'모듈 입력 · 유량 모니터링':p?.kind==='analog'?'아날로그 입력':p?.kind==='digital'?'입력 접점 모니터링':'입력 현황';if(active==='monitor'&&plan&&!plan.measurements.length&&!plan.states.length&&!plan.diagnostics.length&&plan.outputs.length)active='output';
  $('ui-remote-heading').textContent='포트 연결 현황';
  $('ui-output-empty').hidden=!$('output-panel').hidden;
  $('ui-device-visual').hidden=!io;
  $('ui-device-location').textContent='CH'+channel+' / P'+$('port').value;
  $('ui-output-shortcut').hidden=$('output-panel').hidden;
  if(p?.kind==='output')$('remote-note').textContent='출력 메모리를 조회해 접점 ON/OFF를 확인하세요. 실제 밸브 위치 피드백은 별도입니다.';
  const key=channel+':'+$('port').value+':'+(model?.sha256||'');
  if(io&&key!==visualKey){visualKey=key;ProductVisuals.mount($('ui-device-stage'),ProductVisuals.product(model),{label:model?.name||'제품 미선택',note:'선택한 디바이스의 대표 외형'});}
  if(!io){visualKey='';ProductVisuals.clear($('ui-device-stage'));}
  document.querySelector('[data-workspace=remote]').hidden=!io;document.querySelector('[data-workspace=monitor]').hidden=p?.kind==='output'||!!(plan&&!plan.measurements.length&&!plan.states.length&&!plan.diagnostics.length&&plan.outputs.length);
  document.querySelector('[data-workspace=output]').hidden=$('output-panel').hidden;
  $('read').hidden=p?.kind==='output';$('stop').hidden=p?.kind==='output';
  renderPortCards(io);
  show(active);quality();
 }
 function node(tag,cls,text){const e=document.createElement(tag);e.className=cls;if(text!==undefined)e.textContent=text;return e;}
 function portKey(n,definition){return current()+':'+n+':'+definition;}
 function renderPortCards(io){
  const grid=$('ui-port-grid'),portNav=$('ui-channel-port-nav');grid.replaceChildren();portNav.replaceChildren();if(!io)return;
  const available=Array.from($('port').options).filter(o=>!o.disabled),assignments=contextData?.assignments||[],assigned=available.filter(o=>assignments.find(a=>a.port===Number(o.value))?.model).length;
  grid.dataset.assignedCount=assigned;
  $('ui-channel-badge').textContent='CH '+String(current()).padStart(2,'0');$('ui-channel-name').textContent=remote()?.name||'IO-Link 마스터';
  $('ui-channel-assigned').textContent='제품 지정 '+assigned+' / '+available.length;
  $('ui-channel-size').textContent='할당 IN '+($('total-in').value||'—')+' B · OUT '+($('total-out').value||'—')+' B';
  const asset=ProductVisuals.remote({model:$('remote-row-'+current())?.querySelector('select')?.value}),poster=$('ui-channel-poster');poster.hidden=!asset;if(asset){poster.src='/assets/product-models/'+asset.poster;poster.alt=asset.part+' 대표 외형';}else poster.removeAttribute('src');
  $('ui-channel-setup').disabled=locked();
  for(const option of $('port').options){if(option.disabled)continue;
   const n=Number(option.value),a=contextData?.assignments?.find(x=>x.port===n),model=a?.model;
   const portLink=node('button','channel-port-link');portLink.type='button';portLink.disabled=locked();portLink.dataset.port=n;portLink.setAttribute('aria-label','P'+n+' 포트 상세');portLink.setAttribute('aria-pressed',String(n===Number($('port').value)));portLink.append(node('strong','','P'+n),node('span','',a?.name||'제품 미지정'));portLink.onclick=()=>selectPort(n);portNav.append(portLink);
   const card=node('article','port-summary-card');card.dataset.port=n;card.dataset.assigned=String(!!model);card.dataset.definition=a?.definition||'';
   const open=node('button','port-device-card');open.type='button';open.disabled=locked();open.setAttribute('aria-label','P'+n+' 디바이스 보기');open.setAttribute('aria-pressed',String(n===Number($('port').value)));open.onclick=()=>selectPort(n);
   const head=node('div','port-card-top');head.append(node('span','port-index','P'+n),node('span','port-received','미조회'));open.append(head);
   const identity=node('div','port-card-identity'),asset=ProductVisuals.product(model);
   if(asset){const img=node('img','port-product-image');img.src='/assets/product-models/'+asset.poster;img.alt=model.name;identity.append(img);}else identity.append(node('span','port-product-placeholder',model?'IO':'＋'));
   const names=node('div','port-product-name');names.append(node('small','',model?'IO-LINK DEVICE':'제품 미지정'),node('strong','',a?.name||'연결 제품을 선택하세요'));identity.append(names);open.append(identity);
   const plan=model?IoddPresentation.plan(model,a.layout,localStorage.getItem('ams.focus.'+current()+'.'+n+'.'+model.sha256)||''):null;
   const fields=plan?(plan.primary?[plan.primary,...plan.secondary].slice(0,2):[...plan.states,...plan.diagnostics].slice(0,2)):[];
   const metrics=node('div','port-summary-metrics');
   for(const f of fields){const line=node('div','port-metric');line.dataset.item=f.item.id;line.append(node('span','',f.binding.label||f.item.name),node('strong','port-metric-value','—'),node('small','port-metric-note','미조회'));metrics.append(line);}
   if(!fields.length)metrics.append(node('p','port-empty-note',model?'상세 화면에서 PD 형식을 확인하세요.':'제품을 지정하면 PD 항목이 표시됩니다.'));open.append(metrics);
   const settings=node('div','port-summary-settings');settings.append(node('small','port-settings-heading','주요 설정값'));
   const keys=model?IoddPresentation.pins({channel:current(),port:n,model}):[];
   for(const key of keys.slice(0,2)){const resolved=IoddPresentation.resolve({model},key);if(!resolved)continue;const line=node('div','port-setting');line.dataset.setting=key;line.append(node('span','',resolved.binding.label),node('strong','','—'));settings.append(line);}
   if(!keys.length)settings.append(node('p','port-empty-note',model?'임계값·모드 등 필요한 설정값을 선택하세요.':'제품 지정 후 설정값을 선택할 수 있습니다.'));
   if(keys.length>2)settings.append(node('small','port-other-settings','추가 '+(keys.length-2)+'개 · 상세에서 보기'));open.append(settings);card.append(open);
   const foot=node('div','port-card-footer');foot.append(node('span','port-slot-size','할당 IN '+(a?.input??'—')+' B / OUT '+(a?.output??'—')+' B'));
   const detail=node('button','port-detail-link',model?'상세 보기 →':'제품 지정 →');detail.type='button';detail.disabled=locked();detail.onclick=()=>selectPort(n);foot.append(detail);
   const setup=node('button','port-setup-link','설정값 보기 · 수정');setup.type='button';setup.disabled=locked()||!model;setup.setAttribute('aria-label','P'+n+' 설정 열기');setup.onclick=()=>{selectPort(n);$('choose-pins').click();};foot.append(setup);card.append(foot);grid.append(card);
  }paintPortCards();
 }
 function paintPortCards(){
  let received=0,attention=0;
  for(const card of $('ui-port-grid').children){
   const n=Number(card.dataset.port),definition=card.dataset.definition,a=contextData?.assignments?.find(x=>x.port===n),sample=portSamples.get(portKey(n,definition)),fresh=sample&&Date.now()-sample.timestamp<30000&&!sample.failed;
   const label=card.querySelector('.port-received');const status=a?.enabled===false?'사용 안 함':!sample?'미조회':sample.failed?'조회 실패':!fresh?'수신 만료':!sample.connected?'통신 없음':sample.event?'장치 이벤트':!definition?'제품 지정 필요':!sample.valid?'PD 무효':'PD 수신';
   label.textContent=status;card.dataset.receive=a?.enabled===false||!sample?'unknown':!fresh||!sample.valid||sample.event?'attention':sample.connected?'received':'unknown';
   const portLink=$('ui-channel-port-nav').querySelector('[data-port="'+n+'"]');if(portLink)portLink.dataset.receive=card.dataset.assigned==='true'?card.dataset.receive:'unknown';
   if(card.dataset.assigned==='true'&&card.dataset.receive==='received')received++;if(card.dataset.assigned==='true'&&card.dataset.receive==='attention')attention++;
   for(const line of card.querySelectorAll('.port-metric')){const f=sample?.fields?.find(x=>x.item_id===line.dataset.item),eng=f?.engineering,good=fresh&&a?.enabled!==false&&f?.quality==='good';
    setMetric(line.querySelector('.port-metric-value'),!good?'—':eng?.quality==='good'?new Intl.NumberFormat('ko-KR',{maximumFractionDigits:4}).format(eng.value)+' '+eng.unit:typeof f.value==='number'?new Intl.NumberFormat('ko-KR',{maximumFractionDigits:4}).format(f.value):typeof f.value==='boolean'?(f.value?'ON':'OFF'):String(f.value??'—'));
    line.querySelector('.port-metric-note').textContent=!sample?'연결 후 표시됩니다':sample.failed?'조회 실패':!fresh?'마지막 수신 만료':a?.enabled===false?'조회 사용 안 함':!good?(f?.quality==='layout_condition_unconfirmed'?'단위·조건 조회 필요':'유효성 확인 필요'):eng?.quality==='good'?'측정값':'PD 원시값';
   }
   for(const line of card.querySelectorAll('.port-setting')){const d=settingSamples.get(portKey(n,definition)+':'+line.dataset.setting),freshSetting=d&&Date.now()-d.timestamp<60000;line.querySelector('strong').textContent=!freshSetting?'미조회':d.failed?'조회 실패':d.text;line.title=d?'최근 조회 '+new Date(d.timestamp).toLocaleTimeString()+(freshSetting?'':' · 만료'):'상세 화면에서 설정값을 조회하세요';}
  }
  const state=$('ui-channel-receiving');state.textContent=received?'최근 PD 수신 '+received+'개'+(attention?' · 확인 필요 '+attention+'개':''):attention?'수신 상태 확인 필요':'수신 미확인';state.dataset.state=attention?'attention':received?'received':'unknown';
 }
 function refresh(){
  const rows=Array.from(document.querySelectorAll('#remote-rows tr')),nav=$('ui-channels');let registered=0;
  nav.replaceChildren();$('ui-channel-grid').replaceChildren();
  for(const row of rows){
   const n=Number(row.id.replace('remote-row-','')),select=row.querySelector('select');if(!select.value&&n!==current())continue;if(select.value)registered++;
   const button=document.createElement('button');button.type='button';button.className='channel-nav';button.disabled=locked();button.setAttribute('aria-label','CH'+n+' 채널 선택');button.setAttribute('aria-current',String(n===current()&&active!=='overview'));
   const number=document.createElement('span');number.className='channel-number';number.textContent=String(n).padStart(2,'0');const label=document.createElement('span');label.textContent=select.value?select.selectedOptions[0].textContent.split(' · ')[0]:'미등록 채널';const small=document.createElement('small');small.textContent='CH'+n+' · '+(select.value?'등록됨':'구성 필요');label.append(small);button.append(number,label);button.onclick=()=>selectChannel(n);nav.append(button);row.classList.toggle('ui-current-row',n===current());
   if(!select.value)continue;
   const card=document.createElement('article');card.className='channel-overview-card';card.dataset.channel=n;const cardOpen=document.createElement('button');cardOpen.type='button';cardOpen.className='channel-open';cardOpen.disabled=locked();cardOpen.setAttribute('aria-label','CH'+n+' 리모트 보기');cardOpen.onclick=()=>selectChannel(n);
   const header=document.createElement('span');header.className='channel-card-index';header.textContent='CHANNEL '+String(n).padStart(2,'0');const name=document.createElement('strong');name.textContent=select.selectedOptions[0].textContent;const sizes=document.createElement('span');sizes.className='channel-card-map';sizes.textContent='입력 '+row.querySelector('.size-in').value+' B · 출력 '+row.querySelector('.size-out').value+' B';
   const source=row.querySelector('.channel-product-thumb img');if(source?.getAttribute('src')){const image=document.createElement('img');image.src=source.src;image.alt=source.alt;image.className='channel-card-image';cardOpen.append(image);}
   const stamp=document.createElement('small');stamp.className='channel-observation';cardOpen.append(header,name,sizes,stamp);card.append(cardOpen);$('ui-channel-grid').append(card);
  }
  $('ui-channel-count').textContent=registered+'개';$('ui-config').disabled=$('ui-overview').disabled=locked();context();updateOverview();
 }
 function quality(){
  remoteSummary();
  const startHint=$('ui-channel-start-hint'),noDefinition=!$('model').value||!$('layout').value;startHint.hidden=!noDefinition;startHint.textContent=Number($('ui-port-grid').dataset.assignedCount||0)===0?'아래 포트에서 제품을 지정하면 측정 연결을 시작할 수 있습니다.':'제품 바로가기를 선택한 뒤 측정 연결을 시작하세요.';
  const signals=Array.from(document.querySelectorAll('#state-cards .bit-on'));
  const alerts=signals.filter(e=>['alert','warning'].includes(e.dataset.signalKind)&&e.dataset.signalEvidence==='received');
  const previews=signals.filter(e=>e.dataset.signalEvidence==='preview');
  const notices=signals.filter(e=>e.dataset.signalKind==='notice'&&e.dataset.signalEvidence==='received');
  $('ui-state-count').textContent=alerts.length?'· 주의 신호 '+alerts.length+'개':previews.length?'· 시험 신호 '+previews.length+'개':signals.length?'· 활성 상태 '+signals.length+'개':'';
  const fresh=lastSample&&Date.now()-lastSample.timestamp<30000,stale=lastSample&&!fresh;
  $('ui-data-quality').textContent=phase==='error'?'읽기 실패':stale||phase==='stale'?'데이터 만료':phase==='paused'?'갱신 중지':phase==='idle'?'연결 대기':lastSample?.blocked?'일부 값 해석 보류':phase==='output'?'출력 조회됨':'수신됨';
  $('ui-data-quality').dataset.state=fresh&&!lastSample?.blocked&&phase!=='error'?'received':phase==='error'||stale?'attention':'unknown';
  $('ui-last-sample').textContent=lastSample?new Date(lastSample.timestamp).toLocaleTimeString():'—';
  $('ui-device-condition').textContent=!fresh||phase==='error'?'판단 대기':alerts.length?'오류·주의 신호 ON · '+alerts.length+'개':lastSample?.blocked?'유효성 확인 필요':notices.length?'시험·강제 출력 상태 ON':phase==='output'?'출력 메모리 · 동작 피드백 별도':remote()?.kind==='iolink'?'수신 상태 확인 · 정상 범위 미설정':remote()?.kind==='modular'?'원시 입력 수신 · 모듈 진단 미해석':'입력 접점 확인';
  $('ui-device-pq').textContent=!fresh?'미확인':lastSample?.portQuality?({'good':'유효한 PD',invalid:'PD 유효성 확인 필요'}[lastSample.portQuality]||'PD 상태 '+lastSample.portQuality):'미확인';
 }
 function schedule(){if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;refresh();});}
 tabs.forEach(tab=>tab.onclick=()=>{show(tab.dataset.workspace);context();});
 $('ui-channel-setup').onclick=()=>{if(locked())return;show('engineering');$('settings').open=true;$('allocation').scrollIntoView({behavior:reducedMotion()?'auto':'smooth',block:'start'});};
 $('ui-overview').onclick=()=>{show('overview');refresh();};$('ui-config').onclick=configure;$('ui-back-remote').onclick=()=>{show('remote');context();};
 document.addEventListener('change',e=>{if(e.target===$('channel')){const p=remote();show(p?.kind==='iolink'?'remote':p?.kind==='output'?'output':'monitor');}if(e.target===$('port'))show('monitor');schedule();});
 window.addEventListener('iodd-channel-selected',()=>{const p=remote();show(p?.kind==='iolink'?'remote':p?.kind==='output'?'output':'monitor');schedule();});
 window.addEventListener('iodd-port-selected',()=>{show('monitor');schedule();});
 window.addEventListener('iodd-live-state',e=>{const d=e.detail;if(d.phase==='context'){
 if(contextData?.channel===d.channel)for(const a of d.assignments||[]){const old=contextData.assignments?.find(x=>x.port===a.port),signature=x=>JSON.stringify([x?.definition,String(x?.layout??''),x?.swap||'direct',x?.enabled,x?.input,x?.output]);if(signature(a)!==signature(old)||contextData.remote?.inputStart!==d.remote?.inputStart||contextData.remote?.model!==d.remote?.model)for(const map of [portSamples,settingSamples])for(const key of map.keys())if(key.startsWith(d.channel+':'+a.port+':'))map.delete(key);}
 contextData=d;schedule();return;}phase=d.phase;if(d.phase==='idle')lastSample=null;if(d.phase==='sample'&&d.kind==='iolink')for(const p of d.ports||[])portSamples.set(d.channel+':'+p.port+':'+(p.definition||''),{...p,timestamp:d.timestamp});if(['sample','output'].includes(d.phase)){lastSample=d;observations.set(d.channel,{timestamp:d.timestamp,blocked:d.blocked,label:d.kind==='iolink'?'P'+d.port:d.phase==='output'?'출력':'입력'});}if(d.phase==='error'){lastSample=null;for(const [key,sample] of portSamples)if(key.startsWith(d.channel+':'))sample.failed=true;}if(d.phase==='error')observations.set(d.channel,{timestamp:Date.now(),failed:true,label:'조회 실패'});quality();updateOverview();paintPortCards();});
 new MutationObserver(schedule).observe($('remote-rows'),{childList:true});new MutationObserver(schedule).observe($('channel'),{attributes:true,attributeFilter:['disabled']});new MutationObserver(schedule).observe($('output-panel'),{attributes:true,attributeFilter:['hidden']});new MutationObserver(quality).observe($('state-cards'),{childList:true,subtree:true,attributes:true,attributeFilter:['class','data-signal-evidence']});
 window.addEventListener('iodd-setting-sample',e=>{const d=e.detail;settingSamples.set(d.channel+':'+d.port+':'+d.definition+':'+d.key,d);paintPortCards();});
 window.addEventListener('iodd-pins-changed',schedule);window.addEventListener('focus',schedule);window.addEventListener('storage',e=>{if(e.key==='ams.settings.changed'){portSamples.clear();settingSamples.clear();}if(e.key==='ams.settings.changed'||e.key?.startsWith('ams.display.'))schedule();});window.addEventListener('hashchange',schedule);setInterval(()=>{quality();updateOverview();paintPortCards();},1000);
 const shortcut=document.createElement('button');shortcut.type='button';shortcut.id='ui-output-shortcut';shortcut.textContent='출력 상태 조회·조작 →';shortcut.onclick=()=>{show('output');context();};$('remote-panel').append(shortcut);
 window.IoddWorkspace={selectChannel,selectPort,configure,overview:()=>{show('overview');refresh();}};
 show(active);refresh();
})();

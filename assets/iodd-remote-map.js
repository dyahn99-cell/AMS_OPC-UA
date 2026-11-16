/* Manual registration map. Sizes include allocated padding. */
(function(g){
const profiles={
 rdx:{name:'RDX · e-CON 입력16점',input:2,output:0,kind:'digital'},
 rdy:{name:'RDY · e-CON 출력16점',input:0,output:2,kind:'output'},
 rdm:{name:'RDM · e-CON 입출력8점',input:2,output:2,kind:'digital',bits:8},
 rdxg:{name:'RDX · 그로밋 입력16점',input:2,output:0,kind:'digital'},
 rdxgn:{name:'RDX · 그로밋 입력16점 + 알림',input:4,output:0,kind:'digital'},
 rdyg:{name:'RDY · 그로밋 출력16점',input:0,output:2,kind:'output'},
 rdmg:{name:'RDM · 그로밋 입출력8점',input:2,output:2,kind:'digital',bits:8},
 rdmgn:{name:'RDM · 그로밋 입출력8점 + 알림',input:4,output:2,kind:'digital',bits:8},
 valve:{name:'RDY · 밸브32점',input:0,output:4,kind:'output'},
 analog:{name:'RAXZA2C · 아날로그4점',input:8,output:0,kind:'analog'},
 rla:{name:'RLAPA8C · IO-Link A (V2)',input:64,output:64,kind:'iolink',max:130},
 rlb:{name:'RLBPA7C · IO-Link B (V2)',input:64,output:64,kind:'iolink',max:66},
 rla1:{name:'RLAPA8C · IO-Link A (V1)',input:16,output:16,kind:'iolink'},
 rlb1:{name:'RLBPA7C · IO-Link B (V1)',input:16,output:16,kind:'iolink'},
 ams:{name:'EXA1 · AMS',input:36,output:18,kind:'raw'},
 ex600w:{name:'EX600-W · 모듈형 (EX600-AMB)',input:4,output:4,kind:'modular',max:130,min:4}
};
function calculate(state){let input=state.diagnostic,output=0;if(![0,4,10,16,28,52].includes(input))throw Error('베이스 진단 크기 오류');return state.rows.map((r,i)=>{if(!r.model)return {channel:i+1,registered:false};const p=profiles[r.model];if(!p)throw Error('알 수 없는 리모트');for(const d of ['input','output'])if(!Number.isInteger(r[d])||(p.max?(r[d]<(p.min||2)||r[d]>p.max||r[d]%2):r[d]!==p[d]))throw Error('CH'+(i+1)+' 할당 크기 오류');const result={...r,...{channel:i+1,registered:true,profile:p,inputStart:input,outputStart:output}};input+=r.input;output+=r.output;if(input>1440||output>1440)throw Error('시스템 1440바이트 초과');return result;});}
const api={profiles,calculate};if(typeof module!=='undefined')module.exports=api;else g.RemoteMap=api;
})(globalThis);

/* EX600-W module view: consumes the existing channel reader; no device writes. */
(function(g){
function defaults(){return {unit:'',inputOffset:0,outputOffset:0,order:'le',signed:false,confirmed:false,sensor:0,scale:false,rawLow:'',rawHigh:'',voltLow:'',voltHigh:'',flowLow:'',flowHigh:''};}
function inputs(c){return c.inputs||[0,1].map(ch=>({...c,kind:'flow',measurementUnit:'L/min',scale:c.scale&&ch===c.sensor}));}
function validate(c,r){
 for(const [key,size] of [['inputOffset',r.input],['outputOffset',r.output]])if(!Number.isInteger(c[key])||c[key]<0||c[key]+4>size)throw Error('AMB의 4바이트 영역이 채널 할당을 벗어납니다.');
 if(!['le','be'].includes(c.order)||![0,1].includes(c.sensor))throw Error('채널 또는 바이트 순서를 확인하세요.');
 if(c.inputs){if(!Array.isArray(c.inputs)||c.inputs.length!==2)throw Error('입력 두 채널 설정이 필요합니다.');for(const input of c.inputs){if(!['flow','pressure'].includes(input.kind)||!(input.kind==='flow'?['L/min','m³/h']:['MPa','kPa','bar']).includes(input.measurementUnit))throw Error('측정 종류와 단위를 확인하세요.');validate({...c,...input,inputs:undefined,sensor:0},r);}}
 if(!c.inputs&&c.scale){for(const k of ['rawLow','rawHigh','voltLow','voltHigh','flowLow','flowHigh'])if(c[k]===''||!Number.isFinite(Number(c[k])))throw Error('환산 기준값을 모두 입력하세요.');
 if(Number(c.rawHigh)<=Number(c.rawLow)||Number(c.voltHigh)<=Number(c.voltLow)||Number(c.flowHigh)<=Number(c.flowLow))throw Error('환산 상한은 하한보다 커야 합니다.');
 if(!Number.isInteger(Number(c.rawLow))||!Number.isInteger(Number(c.rawHigh))||Number(c.rawLow)<(c.signed?-32768:0)||Number(c.rawHigh)>(c.signed?32767:65535))throw Error('원시값 기준은 선택한 16비트 형식의 범위에 있어야 합니다.');
 if(!c.confirmed)throw Error('모듈 위치와 데이터 형식을 먼저 확인하세요.');}
 return c;
}
function decode(bytes,c,r){validate(c,r);if(!c.confirmed)return [];
 if(!Array.isArray(bytes)||bytes.length!==r.input||bytes.some(b=>!Number.isInteger(b)||b<0||b>255))throw Error('입력 길이 또는 바이트 오류');
 return [0,1].map(ch=>{const x=inputs(c)[ch],at=c.inputOffset+ch*2,pair=bytes.slice(at,at+2);let raw=x.order==='le'?pair[0]+pair[1]*256:pair[0]*256+pair[1];if(x.signed&&raw>=32768)raw-=65536;
 const out={ch,raw,hex:pair.map(b=>b.toString(16).padStart(2,'0')).join(' ').toUpperCase(),voltage:null,flow:null,value:null,kind:x.kind,measurementUnit:x.measurementUnit,quality:'raw'};
 if(x.scale){const ratio=(raw-Number(x.rawLow))/(Number(x.rawHigh)-Number(x.rawLow));
 if(ratio<0||ratio>1)out.quality='out_of_range';else{out.voltage=Number(x.voltLow)+ratio*(Number(x.voltHigh)-Number(x.voltLow));out.value=Number(x.flowLow)+ratio*(Number(x.flowHigh)-Number(x.flowLow));if(x.kind==='flow'&&x.measurementUnit==='L/min')out.flow=out.value;out.quality='scaled';}}
 return out;});
}
const columns=['time_iso','host','wireless_channel','module','unit','sensor_channel','input_byte','status','raw','voltage_V','measurement_value','hex','byte_order','signed','raw_low','raw_high','volt_low','volt_high','measurement_low','measurement_high','measurement_kind','measurement_unit'];
function csv(rows){const cell=v=>'"'+(typeof v==='number'?String(v):String(v??'').replace(/^[=+@\-]/,"'$&")).replaceAll('"','""')+'"';return '\ufeff'+[columns,...rows].map(row=>row.map(cell).join(',')).join('\r\n')+'\r\n';}
const api={defaults,inputs,validate,decode,csv};if(typeof module!=='undefined')module.exports.Ex600=api;g.Ex600Module=api;
if(typeof document==='undefined')return;
let remote=null,config=defaults(),panel=null,recording=false,rows=[],history=[[],[]],stamp=0,expiry=null,contextKey='';
const $=id=>document.getElementById(id),key=()=> 'ams.live.'+window.connectionKey+'.ch'+remote.channel+'.ex600-amb.v1';
function node(tag,text){const e=document.createElement(tag);if(text)e.textContent=text;return e;}
function control(form,label,id,type,value){const wrap=node('label',label),input=node('input');input.id='ex600-'+id;input.type=type;input.value=value;if(type==='number')input.step='any';wrap.append(input);form.append(wrap);return input;}
function invalidate(text){clearTimeout(expiry);stamp=0;history=[[],[]];if(!panel)return;for(const e of panel.querySelectorAll('[data-ex600-value]'))e.textContent='—';$('ex600-state').textContent=text;draw();}
function draw(){if(!panel)return;for(let ch=0;ch<2;ch++)drawChannel(ch,history[ch]);}
function drawChannel(ch,history){const svg=$('ex600-trend-'+ch);svg.replaceChildren();const values=history.filter(x=>x!==null);if(values.length<2)return;const lo=Math.min(...values),span=Math.max(...values)-lo||1;let run=[];const flush=()=>{if(run.length>1){const line=document.createElementNS('http://www.w3.org/2000/svg','polyline');line.setAttribute('points',run.join(' '));line.setAttribute('fill','none');line.setAttribute('stroke','#4daeff');line.setAttribute('stroke-width','2');svg.append(line);}run=[];};history.forEach((v,i)=>{if(v===null){flush();return;}run.push((i*600/Math.max(1,history.length-1))+','+(100-(v-lo)*90/span));});flush();}
function recordStatus(){if(!panel)return;$('ex600-record').textContent=recording?'기록 중지':'CSV 기록 시작';$('ex600-record-note').textContent=(recording?'기록 중 · ':'기록 정지 · ')+rows.length+'행 / 최대 100,000행 · 다운로드 전까지 이 탭에 보관';$('ex600-download').disabled=!rows.length;$('ex600-reset').disabled=recording||!rows.length;}
function log(samples,status,time){if(!recording||!remote)return;const now=new Date(time||Date.now()).toISOString();for(const sample of samples.length?samples:[{ch:0},{ch:1}]){
 if(rows.length>=100000){recording=false;break;}
 const x=inputs(config)[sample.ch];rows.push([now,window.connectionProfile?.host||'',remote.channel,'EX600-AMB',config.unit,sample.ch,remote.inputStart+config.inputOffset+sample.ch*2,status||sample.quality,sample.raw??'',sample.voltage??'',sample.value??'',sample.hex||'',x.order,x.signed,...['rawLow','rawHigh','voltLow','voltHigh','flowLow','flowHigh'].map(k=>x[k]),x.kind,x.measurementUnit]);}recordStatus();}
function mount(r){
 const next=r?.profile?.kind==='modular'?JSON.stringify([window.connectionKey,r.channel,r.inputStart,r.outputStart,r.input,r.output]):'';
 if(next===contextKey&&panel)return;
 if(recording){log([],'context_changed');recording=false;}
 contextKey=next;clearTimeout(expiry);remote=r;history=[[],[]];stamp=0;
 if(panel)panel.remove();panel=null;if(!next)return;
 config=defaults();try{const stored=JSON.parse(localStorage.getItem(key())||'null');if(stored)config={...config,...stored};validate(config,r);}catch(e){config=defaults();}
 panel=node('section');panel.id='ex600-module';panel.className='ex600-module';$('remote-panel').append(panel);
 panel.append(node('h3','EX600-W → EX600-AMB → 아날로그 입력'));
 panel.append(node('p','AMB 입력 4B / 출력 4B · 모듈 위치는 채널 내부 상대 바이트입니다. 채널 전체 할당은 실제 Configurator와 맞추세요.'));
 const address=node('p');address.id='ex600-address';panel.append(address);
 const details=node('details'),summary=node('summary','모듈 위치 · 입력별 압력/유량 설정');details.append(summary);panel.append(details);details.open=!config.confirmed;
 const form=node('form');form.id='ex600-form';form.className='ex600-config';details.append(form);
 control(form,'Unit 번호 (Configurator)','unit','text',config.unit);
 for(const [id,label] of [['inputOffset','AMB 입력 상대 시작 B'],['outputOffset','AMB 출력 상대 시작 B']]){const e=control(form,label,id,'number',config[id]);e.min='0';e.step='1';e.required=true;}
 const confirmed=control(form,'입력 위치·CH0/CH1 각 2B 형식을 확인함','confirmed','checkbox','');confirmed.checked=config.confirmed;
 inputs(config).forEach((x,ch)=>{
 const group=node('fieldset');group.className='ex600-input-config';group.append(node('legend','입력 '+(ch+1)+' · CH'+ch));form.append(group);
 const choose=(id,label,options,value)=>{const wrap=node('label',label),sel=node('select');sel.id='ex600-'+ch+'-'+id;for(const [v,t] of options)sel.append(new Option(t,v));sel.value=value;wrap.append(sel);group.append(wrap);return sel;};
 const kind=choose('kind','측정 종류',[['flow','유량'],['pressure','압력']],x.kind);
 const unit=choose('measurementUnit','표시 단위',[],x.measurementUnit);
 const units=()=>{unit.replaceChildren();for(const v of kind.value==='flow'?['L/min','m³/h']:['MPa','kPa','bar'])unit.append(new Option(v,v));};units();unit.value=x.measurementUnit;kind.onchange=units;
 choose('order','2바이트 순서',[['le','하위 → 상위'],['be','상위 → 하위']],x.order);
 for(const [id,label] of [['signed','부호 있는 16비트'],['scale','확인한 범위로 환산 사용']]){const el=control(group,label,ch+'-'+id,'checkbox','');el.checked=x[id];}
 for(const [id,label] of [['rawLow','원시값 하한'],['rawHigh','원시값 상한'],['voltLow','대응 전압 하한 V'],['voltHigh','대응 전압 상한 V'],['flowLow','측정값 하한 (선택 단위)'],['flowHigh','측정값 상한 (선택 단위)']])control(group,label,ch+'-'+id,'number',x[id]);
 });
 form.append(node('p','환산 기준은 실제 AMB 입력 형식과 센서 출력 설정을 확인해 입력하세요. 12bit만으로 원시값 범위를 추정하지 않습니다. 설정은 대시보드에만 저장합니다. 출력 4B는 주소 계산에 반영하며 아날로그 출력 조작은 아직 지원하지 않습니다.'));
 const save=node('button','구성 저장');save.type='submit';form.append(save);const message=node('p');message.id='ex600-config-message';message.setAttribute('role','status');form.append(message);
 form.onsubmit=e=>{e.preventDefault();const draft={...config};for(const k of ['unit','inputOffset','outputOffset','confirmed']){const el=$('ex600-'+k);draft[k]=el.type==='checkbox'?el.checked:['inputOffset','outputOffset'].includes(k)?Number(el.value):el.value;}
 draft.inputs=inputs(config).map((x,ch)=>{const out={};for(const k of ['kind','measurementUnit','order','signed','scale','rawLow','rawHigh','voltLow','voltHigh','flowLow','flowHigh']){const el=$('ex600-'+ch+'-'+k);out[k]=el.type==='checkbox'?el.checked:el.value;}return out;});

 try{validate(draft,remote);localStorage.setItem(key(),JSON.stringify(draft));if(recording){log([],'configuration_changed');recording=false;}window.dispatchEvent(new Event('ex600-config-changed'));config=draft;for(let ch=0;ch<2;ch++){$('ex600-label-flow-'+ch).textContent=(inputs(config)[ch].kind==='pressure'?'압력 ':'유량 ')+inputs(config)[ch].measurementUnit;}invalidate('구성 변경 · 다시 연결하세요');message.textContent='이 채널의 모듈 구성을 저장했습니다.';updateAddress();recordStatus();}catch(err){message.textContent=err.message;}};
 const cards=node('div');cards.className='ex600-cards';for(let ch=0;ch<2;ch++){const card=node('section');card.className='remote-analog-card';card.append(node('h3','EX600-AMB · CH'+ch));for(const [name,label] of [['flow',(inputs(config)[ch].kind==='pressure'?'압력 ':'유량 ')+inputs(config)[ch].measurementUnit],['voltage','전압 V'],['raw','원시값']]){const caption=node('small',label);caption.id='ex600-label-'+name+'-'+ch;card.append(caption);const value=node('strong','—');value.id='ex600-'+name+'-'+ch;value.dataset.ex600Value='';card.append(value);}cards.append(card);}panel.append(cards);
 const state=node('p','조회 전 · 미확인');state.id='ex600-state';state.setAttribute('role','status');panel.append(state);
 for(let ch=0;ch<2;ch++){const label=node('p','입력 '+(ch+1)+' · CH'+ch+' 최근 60회 추이 (채널별 자동 축)');panel.append(label);const trend=document.createElementNS('http://www.w3.org/2000/svg','svg');trend.id='ex600-trend-'+ch;trend.style.cssText='width:100%;height:130px';trend.setAttribute('viewBox','0 0 600 110');trend.setAttribute('aria-label','CH'+ch+' 측정 추이');trend.setAttribute('role','img');panel.append(trend);}
 const record=node('button');record.id='ex600-record';record.type='button';record.onclick=()=>{if(!recording&&!config.confirmed){$('ex600-state').textContent='모듈 위치와 데이터 형식 확인 후 기록하세요.';return;}recording=!recording;recordStatus();};panel.append(record);
 const download=node('button','CSV 다운로드');download.id='ex600-download';download.type='button';download.onclick=()=>{const url=URL.createObjectURL(new Blob([csv(rows)],{type:'text/csv;charset=utf-8'})),a=node('a');a.href=url;a.download='EX600-AMB-'+new Date().toISOString().replaceAll(':','-')+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};panel.append(download);
 const reset=node('button','저장 목록 비우기');reset.id='ex600-reset';reset.type='button';reset.onclick=()=>{if(!recording&&confirm('CSV 기록 '+rows.length+'행을 비울까요?')){rows=[];recordStatus();}};panel.append(reset);
 const note=node('p');note.id='ex600-record-note';panel.append(note);updateAddress();recordStatus();
}
function updateAddress(){if(panel)$('ex600-address').textContent='전체 맵: 입력 B'+(remote.inputStart+config.inputOffset)+'–'+(remote.inputStart+config.inputOffset+3)+' / 출력 B'+(remote.outputStart+config.outputOffset)+'–'+(remote.outputStart+config.outputOffset+3)+(config.confirmed?' · 사용자 확인 맵':' · 위치 미확인');}
window.addEventListener('iodd-live-state',e=>{const d=e.detail;if(d.phase==='context'){mount(d.remote);return;}if(!panel||d.channel!==remote.channel)return;
 if(['idle','error','stale'].includes(d.phase)){log([],d.phase);invalidate(d.phase==='error'?'읽기 실패 · 결측':d.phase==='stale'?'데이터 만료':'미수신');if(d.phase==='idle')recording=false;recordStatus();return;}
 if(d.phase==='paused'){log([],'paused');recording=false;recordStatus();return;}
 if(d.phase!=='sample'||d.kind!=='modular')return;
 const age=Date.now()-d.timestamp;if(!Number.isFinite(age)||age< -1000||age>=30000){log([],'stale');invalidate('수신 시각 확인 필요');return;}
 try{const samples=decode(d.bytes,config,remote);if(!samples.length){invalidate('모듈 위치와 2바이트 데이터 형식을 먼저 확인하세요.');return;}
 if(stamp&&d.timestamp<=stamp)return;
 if(stamp&&d.timestamp-stamp>5000)history.forEach(h=>h.push(null));stamp=d.timestamp;
 for(const s of samples){$('ex600-raw-'+s.ch).textContent=s.raw+' · '+s.hex;$('ex600-voltage-'+s.ch).textContent=s.voltage===null?'—':s.voltage.toFixed(3);$('ex600-flow-'+s.ch).textContent=s.value===null?'—':s.value.toLocaleString('ko-KR',{maximumFractionDigits:3});}
 samples.forEach(s=>history[s.ch].push(s.value));history=history.map(h=>h.slice(-60));draw();log(samples,null,d.timestamp);
 $('ex600-state').textContent=new Date(d.timestamp).toLocaleTimeString()+' 수신 · '+(samples.some(s=>s.quality==='out_of_range')?'환산 범위 밖 · 해당 입력 보류':inputs(config).some(x=>x.scale)?'입력별 설정으로 압력/유량 환산':'원시값 표시 · 환산 미설정');
 clearTimeout(expiry);expiry=setTimeout(()=>{log([],'stale');invalidate('수신 후 30초 경과 · 데이터 만료');},30000-age);
 }catch(err){log([],'decode_error');invalidate(err.message);}
});
window.addEventListener('beforeunload',e=>{if(rows.length||recording){e.preventDefault();e.returnValue='';}});
})(globalThis);

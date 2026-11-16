(function(global){
'use strict';
function mount(host,models,onOpen){
 const api=global.IoddMasterConfig,key='ams.exw1.manual-plan.v1';let config=api.create();
 const el=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
 const status=el('p'),form=el('div'),ports=el('div'),report=el('pre'),actions=el('div'),json=el('textarea');
 form.className='toolbar';ports.style.cssText='display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px';json.rows=6;json.style.width='100%';json.setAttribute('aria-label','구성 JSON 가져오기 또는 내보내기');
 host.append(el('h2','마스터 → 포트 → 제품'),el('p','오프라인 구성 계획 · 실제 장비 설정과 별도 · 총 바이트는 페어링 값과 대조해야 합니다.'),form,ports,report,actions,status,json);
 function field(parent,title,obj,prop,options,type='text'){
  const label=el('label',title),input=el(options?'select':'input');
  if(options)for(const [value,name] of options){const o=el('option',name);o.value=value;input.append(o);}
  else input.type=type;
  input.value=obj[prop]??'';if(type==='checkbox')input.checked=obj[prop];
  input.onchange=()=>{obj[prop]=type==='checkbox'?input.checked:type==='number'?(input.value===''?null:Number(input.value)):input.value;status.textContent='변경됨 · 저장 전';draw();};label.append(input);parent.append(label);return input;
 }
 function button(parent,title,fn){const b=el('button',title);b.onclick=fn;parent.append(b);return b;}
 function draw(){
  form.replaceChildren();ports.replaceChildren();
  field(form,'베이스 ID',config,'base');field(form,'채널 1–15',config,'channel',null,'number');
  field(form,'마스터 모델',config,'model',Object.keys(api.types).map(x=>[x,x]));
  field(form,'무선 프로토콜',config,'protocol',[['2.0','V2.0'],['1.0','V1.0 · 16/16 bytes']]);
  field(form,'전체 입력 bytes',config,'input',null,'number');field(form,'전체 출력 bytes',config,'output',null,'number');
  field(form,'PORT1 → P1/P3 분기 배선 확인',config,'y1',null,'checkbox');field(form,'PORT2 → P2/P4 분기 배선 확인',config,'y2',null,'checkbox');
  for(const p of config.ports){
   const card=el('div');card.className='iw-card';card.append(el('h3','P'+p.id+' · PORT'+(p.id%2?1:2)+' / Pin '+(p.id<=2?4:2)));ports.append(card);
   field(card,'사용',p,'enabled',null,'checkbox');field(card,'별칭',p,'alias');
   field(card,'포트 모드',p,'mode',[['deactivated','미사용'],['manual','IO-Link Manual'],['autostart','IO-Link Autostart'],['di','DI_C/Q'],['do','DO_C/Q']]);
   field(card,'입력 할당 bytes',p,'input',null,'number');field(card,'출력 할당 bytes',p,'output',null,'number');
   field(card,'PD 바이트 순서',p,'swap',[['direct','Direct'],['swap16','Swap 16 bit'],['swap32','Swap 32 bit'],['swapAll','Swap All']]);
   const selector=field(card,'제품 · 정확한 IODD 정의',p,'definition',[['','제품 버전을 선택하세요'],...models.map(m=>[m.sha256,m.name+' · '+m.sha256.slice(0,8)])]);
   selector.onchange=()=>{p.definition=selector.value||null;p.layout=null;status.textContent='변경됨 · 저장 전';draw();};
   const model=models.find(m=>m.sha256===p.definition);
   const select=field(card,'PD 레이아웃 · 수동 선택',p,'layout',[['','레이아웃 선택'],...(model?.layouts||[]).map(l=>[String(l.id),'Layout '+l.id+' '+JSON.stringify(l.condition)])]);
   select.onchange=()=>{p.layout=select.value===''?null:Number(select.value);status.textContent='변경됨 · 저장 전';draw();};
   button(card,'선택 IODD 길이로 채우기',()=>{const layout=model?.layouts.find(l=>l.id===p.layout);if(!layout){status.textContent='제품과 레이아웃을 먼저 선택하세요';return;}for(const [source,dir] of [['PD IN','input'],['PD OUT','output']]){const d=layout.directions.find(d=>d.source===source);p[dir]=d?Math.ceil(Number(d.bitLength)/8):0;}status.textContent='IODD 길이 입력됨 · 실장비 값 미확인';draw();});
   const open=button(card,'이 포트 위젯 열기',()=>onOpen(p));open.disabled=!p.enabled||!['manual','autostart'].includes(p.mode)||!model||p.layout===null;
  }
  const result=api.validate(config,models);
  report.textContent=['로컬 구성 검증: '+(result.errors.length?'수정 필요':'통과 · 실물 미검증'),'고정 영역: 입력 0–1 / 출력 0–1 (각 2 bytes)',...result.map.map(r=>'P'+r.port+' 입력 '+(r.input_start===null?'—':r.input_start+'..'+(r.input_start+r.input_bytes-1))+' / 출력 '+(r.output_start===null?'—':r.output_start+'..'+(r.output_start+r.output_bytes-1))),'필요 입력/출력 '+result.input+'/'+result.output+' bytes',...result.errors.map(x=>'오류: '+x),...result.warnings.map(x=>'확인: '+x)].join('\n');
 }
 const run=fn=>()=>{try{fn();}catch(e){status.textContent='처리 실패: '+e.message;}};
 button(actions,'이 브라우저에 저장',run(()=>{localStorage.setItem(key,api.encode(config,models));status.textContent='로컬 저장 완료 · 장비에 적용되지 않음';}));
 button(actions,'저장 구성 불러오기',run(()=>{const text=localStorage.getItem(key);if(!text)throw Error('저장된 구성 없음');const loaded=api.decode(text,models);config=loaded;draw();status.textContent='저장 구성 복원 · 장비에서 읽은 값 아님';}));
 button(actions,'JSON 내보내기',run(()=>{json.value=api.encode(config,models);status.textContent='JSON 생성 완료 · 아래 내용을 파일로 보관할 수 있습니다';}));
 button(actions,'JSON 가져오기',run(()=>{const loaded=api.decode(json.value,models);config=loaded;draw();status.textContent='구성 가져옴 · 저장 전';}));
 try{const text=localStorage.getItem(key);if(text){config=api.decode(text,models);status.textContent='이 브라우저의 저장 구성 복원';}}catch(e){status.textContent='자동 복원 실패: '+e.message;}
 draw();return {getConfig:()=>JSON.parse(JSON.stringify(config)),loadConfig(value){config=api.decode(JSON.stringify(value),models);draw();status.textContent='선택한 마스터 구성 · 실제 장비 미연결';}};
}
global.IoddMasterEditor={mount};
})(globalThis);

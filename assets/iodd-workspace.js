(function(global){
'use strict';
function mount(host,editor,models,openPort,onLive){
 const e=(tag,text)=>{const n=document.createElement(tag);n.textContent=text||'';return n;};
 let snapshot={revision:0,masters:[]},selected=null,token=null,busy=false,loaded=false;
 const info=e('p','서버 구성 불러오는 중'),tree=e('div'),actions=e('div');host.append(e('h2','저장된 장비 트리'),actions,info,tree);
 const buttons=[];
 function button(label,fn){const b=e('button',label);b.onclick=async()=>{if(busy)return;busy=true;buttons.forEach(x=>x.disabled=true);try{await fn();}catch(err){info.textContent=err.message;}finally{busy=false;buttons.forEach(x=>x.disabled=false);}};actions.append(b);buttons.push(b);}
 async function request(method,payload,path='/api/device-workspace'){
  if(!token){const r=await fetch('/api/local-session',{headers:{'x-ams-bootstrap':'1'}});if(!r.ok)throw Error('로컬 세션 인증 실패');token=(await r.json()).token;}
  const r=await fetch(path,{method,headers:{'x-ams-local-token':token,'Content-Type':'application/json'},...(payload?{body:JSON.stringify(payload)}:{})});
  const data=await r.json();if(!r.ok)throw Error(data.error||'서버 요청 실패');return data;
 }
 function draw(){tree.replaceChildren();
  for(const base of [...new Set(snapshot.masters.map(m=>m.config.base))].sort()){
   const branch=e('section'),title=e('h3',base);branch.append(title);tree.append(branch);
   for(const master of snapshot.masters.filter(m=>m.config.base===base).sort((a,b)=>a.config.channel-b.config.channel)){
    const c=master.config,b=e('button','CH'+c.channel+' · '+c.model+(selected===master.id?' · 편집 중':''));
    b.onclick=()=>{if(busy)return;try{editor.loadConfig(c);selected=master.id;info.textContent='선택한 마스터를 편집 중 · 서버 저장 전';draw();}catch(err){info.textContent=err.message;}};branch.append(b);
    const list=e('ul');branch.append(list);for(const p of c.ports.filter(p=>p.enabled)){
     const item=e('li'),model=models.find(m=>m.sha256===p.definition),port=e('button','P'+p.id+' · '+(p.alias||model?.name||p.mode));
     port.disabled=!model||!['manual','autostart'].includes(p.mode);port.onclick=()=>{if(busy)return;try{editor.loadConfig(c);selected=master.id;openPort(p,master.id,c);draw();}catch(err){info.textContent=err.message;}};item.append(port);list.append(item);
    }
   }
  }
  if(!snapshot.masters.length)tree.append(e('p','저장된 마스터 없음 · 아래에서 구성 후 서버에 저장하세요.'));
 }
 async function load(){snapshot=await request('GET');loaded=true;selected=null;draw();info.textContent='서버 구성 '+snapshot.masters.length+'개 · 버전 '+snapshot.revision+' · 실물 미연결';}
 button('서버에서 다시 불러오기',load);
 button('새 마스터 구성',()=>{editor.loadConfig(global.IoddMasterConfig.create());selected=null;draw();info.textContent='새 마스터 편집 · 고유한 베이스/채널을 지정하세요';});
 button('편집 구성을 서버에 저장',async()=>{
  if(!loaded)throw Error('먼저 서버 구성을 불러오세요');
  const config=editor.getConfig();global.IoddMasterConfig.encode(config,models);
  const id=selected||crypto.randomUUID(),masters=snapshot.masters.filter(m=>m.id!==id).concat([{id,config}]);
  const saved=await request('PUT',{revision:snapshot.revision,masters});snapshot=saved;selected=id;draw();info.textContent='서버 저장 완료 · '+config.base+'/CH'+config.channel+' · 장비에는 적용하지 않음';
 });
 const diag=document.createElement('input');diag.type='checkbox';const dl=e('label','읽을 제품의 진단 V_diAG=1 확인 (미확인 시 해당 수치 보류)');dl.append(diag);host.append(dl);
 button('선택 마스터 입력 1회 읽기',async()=>{
  if(!loaded||!selected)throw Error('서버 트리에서 저장된 마스터를 선택하세요');
  const entry=snapshot.masters.find(m=>m.id===selected);
  if(JSON.stringify(editor.getConfig())!==JSON.stringify(entry.config))throw Error('편집 내용을 먼저 서버에 저장하세요');
  onLive?.(null);info.textContent='입력 읽는 중 · 출력 쓰기 없음';
  const data=await request('POST',{id:selected,revision:snapshot.revision},'/api/device-workspace/read');
  if(data.id!==selected||data.revision!==snapshot.revision)throw Error('구성이 달라져 응답을 폐기했습니다');
  const result=await global.IoddRegisterInput.read(data.config,models,data.mapping,async()=>data.response,{diagnostics:diag.checked?Object.fromEntries(data.config.ports.map(p=>[p.id,{V_diAG:1}])):{}});
  if(result.error)throw Error(result.error);
  onLive?.({...data,decoded:result.decoded});info.textContent='입력 1회 수신 · '+new Date(data.response.timestamp).toLocaleTimeString()+' · 자동 폴링 없음';
 });
 load().catch(err=>{info.textContent=err.message;});
}
// Runtime-independent mock cache: identity includes master, port, revision and layout.
class Samples{
 constructor(){this.values=new Map();}
 key(context,item){return JSON.stringify([context,item]);}
 set(context,item,value,time=Date.now()){this.values.set(this.key(context,item),{value,time});}
 get(context,item,now=Date.now()){const v=this.values.get(this.key(context,item));return !v?{value:null,quality:'unavailable'}:now-v.time>30000?{value:null,quality:'stale',time:v.time}:{...v,quality:'mock'};}
 disconnect(context){for(const key of this.values.keys())if(JSON.parse(key)[0]===context)this.values.delete(key);}
}
const api={mount,Samples};if(typeof module!=='undefined')module.exports=api;else global.IoddWorkspace=api;
})(globalThis);

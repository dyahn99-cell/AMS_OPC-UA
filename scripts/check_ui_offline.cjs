/* Explicit Node-only checks: no server, worker, browser or real fetch is started. */
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'dashboard.html'),'utf8');
const inline=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m=>m[1]).filter(s=>s.trim());
for(const source of inline)new vm.Script(source,{filename:'dashboard-inline.js'});
const js=inline.join('\n');
let syntaxCount=inline.length;
for(const name of fs.readdirSync(path.join(root,'assets')).filter(n=>n.endsWith('.js'))){
  new vm.Script(fs.readFileSync(path.join(root,'assets',name),'utf8'),{filename:name});syntaxCount++;
}
new vm.Script(fs.readFileSync(path.join(root,'worker.js'),'utf8'),{filename:'worker.js'});syntaxCount++;
let checks=0;
function between(start,end){
  const from=js.indexOf(start),to=js.indexOf(end,from+start.length);
  assert(from>=0&&to>from,`missing source boundary ${start}`);
  return js.slice(from,to);
}
class Element{
  constructor(tag){this.tagName=tag;this.children=[];this.className='';this.style={};this.listeners={};this.dataset={};this.hidden=false;this.disabled=false;this._text='';}
  append(...nodes){for(let node of nodes){if(typeof node==='string')node={_text:node,textContent:node};node.parentElement=this;this.children.push(node);}}
  replaceChildren(...nodes){this.children=[];this._text='';this.append(...nodes);}
  set textContent(value){this.children=[];this._text=String(value);}
  get textContent(){return this._text+this.children.map(n=>n.textContent||'').join('');}
  set innerHTML(value){assert(value.includes('No schedules registered'),'test prohibits HTML interpolation');this._text=value;}
  addEventListener(event,fn){this.listeners[event]=fn;}
  querySelector(selector){return descendants(this).find(n=>n.className?.split(' ').includes(selector.slice(1)))||null;}
  before(node){const parent=this.parentElement;node.parentElement=parent;parent.children.splice(parent.children.indexOf(this),0,node);}
}
function descendants(node){return [node,...(node.children||[]).flatMap(descendants)];}
const nodes=Object.fromEntries(['sch_list','sch_count','hero_sch_count','scb_list','scb_count','scb_count_total'].map(id=>[id,new Element('div')]));
const clicked=[];
const ctx=vm.createContext({document:{getElementById:id=>nodes[id]||null,createElement:tag=>new Element(tag),createTextNode:text=>({textContent:String(text)})},
  scheduleState:s=>s.status==='RUNNING'?'running':'waiting',setText2:(id,text)=>{if(nodes[id])nodes[id].textContent=text;},
  nextRunLabel:s=>s.start_time,toggleSchedule:id=>clicked.push(['toggle',id]),stopSchedule:id=>clicked.push(['stop',id]),editSchedule:id=>clicked.push(['edit',id]),deleteSchedule:id=>clicked.push(['delete',id])});
vm.runInContext(between('function renderSchedules(', 'async function execSchedule('),ctx);
vm.runInContext(between('function renderScheduleBeta(', '// ==== DEVICE PORT 4'),ctx);
const attack='<img src=x onerror="throw 1"><svg onload="throw 2">';
ctx.rows=[{id:'safe-id_1',name:attack,remote_id:attack,start_time:attack,end_time:'23:59',repeat:'daily',days:[attack],mode:attack,active:true},
  {id:"x');throw 3;//",name:'invalid id',remote_id:'AMS01',start_time:'10:00',end_time:'11:00',status:'RUNNING',active:true}];
vm.runInContext('renderSchedules(rows)',ctx);
for(const key of ['sch_list','scb_list']){
  const all=descendants(nodes[key]);
  assert(all.some(n=>n.textContent===attack));
  assert(!all.some(n=>['img','svg','script'].includes(n.tagName)));
  const buttons=all.filter(n=>n.tagName==='button');
  assert.equal(buttons.filter(n=>n.disabled).length,3);
  assert(buttons.filter(n=>!n.disabled).every(n=>typeof n.listeners.click==='function'));
  buttons.find(n=>!n.disabled).listeners.click();checks++;
}
assert.deepEqual(clicked,[['toggle','safe-id_1'],['toggle','safe-id_1']]);checks++;
const canvas=new Element('canvas'),parent=new Element('div');parent.append(canvas);nodes.offlineChart=canvas;
vm.runInContext(between('function chartAvailable(', 'const ch='),ctx);
assert.equal(vm.runInContext('mkChart("offlineChart","#007aff")',ctx),null);
assert(canvas.hidden);assert(parent.textContent.includes('Chart unavailable'));checks++;
const authSource=fs.readFileSync(path.join(root,'assets/local-access.js'),'utf8');
function checkMeasurements(){
  const ids=['lv_pressure','lv_temp','lv_flow','lv_acc','hero_pressure','hero_flow','hero_temp','cv_p','cv_f','cv_t','panel_pressure','panel_flow','panel_temp','panel_acc','bru_kpi_flow','bru_kpi_acc','bru_kpi_temp','hist_total_flow','hero_hist_total','en_acc_l','en_acc_m3','en_kwh','en_cost','en_co2','hero_energy_flow','hero_energy_kwh','hero_energy_co2','energy_data_status','last_update'];
  const els=Object.fromEntries(ids.map(id=>[id,new Element('div')]));
  const history=[];
  const scope=vm.createContext({document:{getElementById:id=>els[id]||null,createElement:tag=>new Element(tag)},remoteFlowHistory:{},selectedRemoteId:'AMS02',getSelectedRemoteData:()=>scope.row,
    pushHist:(...values)=>history.push(values),updCharts:()=>{},updateLiveVisuals:()=>{},applyModeUI:()=>{},setBadge:()=>{},updateIoLinkUI:()=>{},updateDevicePanel:()=>{},renderConsoleView:()=>{},boolFromOpcValue:()=>false,
    standbyUiPendingUntil:Infinity,forcedStandbyUiPendingUntil:Infinity,airUiPendingUntil:Infinity});
  vm.runInContext(between('function measurementNumber(','function fmtGrouped('),scope);
  vm.runInContext(between('function rememberRemoteFlow(','function remotePatchMatches('),scope);
  vm.runInContext(between('function renderSelectedRemoteLive(','async function loadMultiMonitor('),scope);
  for(const input of [null,undefined,'','  ',false,{},NaN,Infinity]){
    scope.input=input; assert.equal(vm.runInContext('measurementNumber(input)',scope),null);checks++;
  }
  for(const input of [0,'0']){scope.input=input;assert.equal(vm.runInContext('measurementNumber(input)',scope),0);checks++;}
  for(const extra of [{online:false},{device_connected:false},{stale:true},{opcua_stale:true},{field_quality:{pressure_mpa:'stale'}},{field_quality:{pressure_mpa:'partial'}},{field_quality:{pressure_mpa:'unavailable'}}]){
    scope.row={online:true,pressure_mpa:5,...extra};assert.equal(vm.runInContext('measurementValue(row,"pressure_mpa")',scope),null);checks++;
  }
  scope.row={online:true,pressure_mpa:0,temperature_c:null,instant_flow_l_min:0,accumulated_flow_l:0,energy:{kwh:0,cost_krw:0,co2_kg:0}};
  vm.runInContext('renderSelectedRemoteLive()',scope);
  assert.equal(els.lv_pressure.textContent,'0.000');assert.equal(els.lv_temp.textContent,'-');assert.equal(els.en_kwh.textContent,'0.0000');assert.equal(history.at(-1)[3],null);checks++;
  scope.row={online:true,pressure_mpa:8,instant_flow_l_min:9,stale:true};
  vm.runInContext('renderSelectedRemoteLive()',scope);
  assert.equal(els.lv_pressure.textContent,'-');assert.equal(history.at(-1)[1],null);assert.equal(history.at(-1)[2],null);checks++;
  scope.row={online:false,pressure_mpa:8};
  assert.equal(vm.runInContext('renderSelectedRemoteLive()',scope),true);assert(ids.slice(0,20).every(id=>els[id].textContent==='-'));checks++;
  scope.row=null;assert.equal(vm.runInContext('renderSelectedRemoteLive()',scope),true);checks++;
  scope.row={online:true,accumulated_flow_l:1000,energy:{error:attack,kwh:500}};
  vm.runInContext('renderLiveEnergy(row)',scope);
  assert.equal(els.en_kwh.textContent,'-');assert.equal(els.energy_data_status.textContent,'Energy unavailable: '+attack);assert.equal(els.energy_data_status.children.length,0);checks++;
  scope.row={online:true,accumulated_flow_l:1000,dashboard_total_flow_l:null,energy:{kwh:1}};
  vm.runInContext('renderLiveEnergy(row)',scope);assert.equal(els.en_acc_l.textContent,'-');assert.equal(els.en_kwh.textContent,'-');checks++;
  vm.runInContext('rememberRemoteFlow("x",0);rememberRemoteFlow("x",null);rememberRemoteFlow("x",2)',scope);
  assert.deepEqual(Array.from(scope.remoteFlowHistory.x),[0,null,2]);
  assert.equal((vm.runInContext('renderSparkline("x")',scope).match(/<polyline/g)||[]).length,2);
  assert.match(vm.runInContext('renderSparkline("empty")',scope),/Unavailable/);checks++;
  // Chart data mappings must preserve null gaps in both history presentations.
  assert(js.includes('histData.map(r=>measurementNumber(r[histMode]))'));
  assert(js.includes('histbData.map(r=>measurementNumber(r.avg))'));checks++;
}
checkMeasurements();
async function checkAuth(){
  const calls=[];let apiStatus=200;
  const window={};
  // Keep all HTTP as fake callbacks. No Node fetch implementation is exposed.
  window.fetch=async(input,options)=>{
    const request=input instanceof Request?input:new Request(input,options);calls.push(request);
    return new Response(JSON.stringify(new URL(request.url).pathname==='/api/local-session'?{ok:true,token:'fake-token'}:{}),{status:new URL(request.url).pathname==='/api/local-session'?200:apiStatus,headers:{'Content-Type':'application/json'}});
  };
  const auth=vm.createContext({window,location:{protocol:'http:',origin:'http://127.0.0.1:8000',href:'http://127.0.0.1:8000/dashboard'},Request,Response,Headers,URL});
  vm.runInContext(authSource,auth);
  await Promise.all([window.amsFetch('http://127.0.0.1:8000/api/status'),window.amsFetch('http://127.0.0.1:8000/api/schedules')]);
  assert.equal(calls.filter(r=>r.url.endsWith('/api/local-session')).length,1);
  assert.equal(calls[0].headers.get('x-ams-bootstrap'),'1');
  assert(calls.slice(1).every(r=>r.headers.get('x-ams-local-token')==='fake-token'&&r.redirect==='error'));
  assert(calls.every(r=>!r.url.includes('fake-token')));checks++;
  const originalCount=calls.length;
  await assert.rejects(window.amsFetch('https://evil.invalid/api/status'),/same origin/);
  assert.equal(calls.length,originalCount);checks++;
  apiStatus=403;
  const response=await window.amsFetch('http://127.0.0.1:8000/api/control/air-supply',{method:'POST',body:'{}'});
  assert.equal(response.status,403);
  assert.equal(calls.length,originalCount+1,'no automatic request replay');checks++;
  await window.amsLocalToken();assert.equal(calls.length,originalCount+2,'next request refreshes invalid token');checks++;
}
async function checkRecovery(){
  const ids=['hub_registry_recovery','hub_registry_errors','hub_registry_raw','hub_registry_save','hub_registry_status','connModal','hub_ams_host','hub_ams_password','hub_ams_channel','hub_opcua_endpoint','conn_status'];
  const elements=Object.fromEntries(ids.map(id=>[id,{value:'',textContent:'',hidden:false,disabled:false,classList:{add(){}}}]));
  const calls=[];
  const recovery=vm.createContext({document:{getElementById:id=>elements[id]},API:'http://127.0.0.1:8000',toast:()=>{},renderHubDeviceProfiles:()=>{},renderHubTopology:()=>{}});
  vm.runInContext(between('let hubDeviceProfiles=[]','function renderHubTopology('),recovery);
  recovery.hub={raw_device_profiles:{BROKEN:{endpoint:attack}},recovery:{quarantined_profiles:[{device_id:'BROKEN',error:attack}]}};
  vm.runInContext('hubRegistryLoaded=true;renderHubRegistryRecovery(hub)',recovery);
  assert.equal(elements.hub_registry_errors.textContent,'BROKEN: '+attack);
  assert.equal(JSON.parse(elements.hub_registry_raw.value).BROKEN.endpoint,attack);
  assert.equal(elements.hub_registry_save.disabled,true);checks++;
  // Loading one failed connection section must not discard the usable registry.
  recovery.amsFetch=async url=>{calls.push(url);return url.endsWith('/devices')?{ok:true,json:async()=>({devices:[],raw_device_profiles:{},recovery:{recovery_only:true}})}:{ok:false,status:503};};
  vm.runInContext(between('async function openConnModal(','function closeConnModal('),recovery);
  await vm.runInContext('openConnModal()',recovery);
  assert.equal(calls.length,3);
  assert.equal(elements.hub_registry_save.disabled,false);
  assert.match(elements.hub_registry_status.textContent,/RECOVERY ONLY/);
  assert.match(elements.conn_status.textContent,/HTTP 503/);checks++;
}
async function checkPinIntent(){
  const calls=[];
  const scope=vm.createContext({p4DoWritePending:false,p4PdoutWriteBlockedReason:'',p4DoValue:0x35,
    p4DoUiOverride:null,p4DoUiPendingUntil:0,selectedRemoteId:'AMS01',deviceRequestContext:()=>({id:'AMS01'}),staleDeviceWrite:()=>false,
    port4DoPinMask:pin=>pin===2?128:pin===4?64:0,toast:()=>{},setTimeout:()=>{},loadMultiMonitor:()=>{},
    updatePort4StandardIo:(_data,_di,value)=>{scope.p4DoValue=value;},
    hubCommand:async(id,command,payload)=>{calls.push({id,command,payload:JSON.parse(JSON.stringify(payload))});return {ok:true,value:0xF5};}});
  vm.runInContext(between('async function setPort4DoPin(', 'async function clearPort4Do('),scope);
  await vm.runInContext('setPort4DoPin(2)',scope);
  assert.deepEqual(calls[0],{id:'AMS01',command:'port4_do',payload:{pin:2,enabled:true}});checks++;
  await vm.runInContext('setPort4DoPin(4)',scope);
  assert.deepEqual(calls[1].payload,{pin:4,enabled:false});checks++;
  assert(calls.every(call=>!('value' in call.payload)));checks++;
}
async function checkSelectionOwnership(){
  const elements=new Map();const calls=[],toasts=[];
  const element=id=>{if(!elements.has(id))elements.set(id,{textContent:'old',value:'',classList:{}});return elements.get(id)};
  const scope=vm.createContext({API:'',AbortController,Event,setTimeout:fn=>fn(),window:{dispatchEvent(){}},
    document:{getElementById:element,querySelectorAll:()=>[]},selectedRemoteId:'A',viewScope:'device',deviceConnected:true,
    modeUiPendingUntil:0,standbyUiPendingUntil:0,forcedStandbyUiPendingUntil:0,airUiPendingUntil:0,airUiOverride:null,p4DoUiOverride:null,p4DoUiPendingUntil:0,
    updatePF3AIsolationUI(){},toast:(...args)=>toasts.push(args),formatApiError:r=>r.error||'unverified',
    latestRemotePayload:{remotes:[{id:'A',online:true},{id:'B',online:true},{id:'OFF',online:false}]},
    amsFetch:(url,options)=>new Promise(resolve=>calls.push({url,options,resolve})),
    isDemoLiveSource:()=>false,isModbusSource:()=>false,activeSettingsRemote:()=>scope.selectedRemoteId});
  vm.runInContext(between('let deviceSelectionGeneration=','// After a settings write'),scope);
  vm.runInContext(between('async function refreshSettingsWithRetry(','// ?'),scope);
  vm.runInContext(between('async function apiPost(','// ?'),scope);
  const response=data=>({ok:true,json:async()=>data});
  const a=vm.runInContext('updateSettings()',scope);
  vm.runInContext('invalidateDeviceSelection();selectedRemoteId="B"',scope);
  assert.equal(element('cfg_itv_op').textContent,'—');assert(calls[0].options.signal.aborted);checks++;
  const b=vm.runInContext('updateSettings()',scope);
  calls[1].resolve(response({ok:true,operation_kpa:200,standby_kpa:100}));await b;
  calls[0].resolve(response({ok:true,operation_kpa:900,standby_kpa:800}));await a;
  assert.equal(element('cfg_itv_op').textContent,200);checks++;
  const old=vm.runInContext('deviceRequestContext()',scope);
  vm.runInContext('invalidateDeviceSelection();selectedRemoteId="A"',scope);scope.old=old;
  const before=calls.length;await vm.runInContext('refreshSettingsWithRetry([],old)',scope);assert.equal(calls.length,before);checks++;
  vm.runInContext(between('async function applyITV(','async function applyPF3A('),scope);
  element('itv_op').value='450';scope.deviceConnected=true;
  const write=vm.runInContext('applyITV()',scope);const pending=calls.at(-1);
  assert(pending.url.includes('/A/settings'));assert.equal(pending.options.method,'PUT');
  vm.runInContext('invalidateDeviceSelection();selectedRemoteId="B"',scope);
  pending.resolve(response({ok:true}));await write;
  assert.equal(calls.length,before+1);assert.equal(element('cfg_itv_op').textContent,'—');checks++;
  for(const value of [{ok:true,partial:true},{ok:true,results:{A:{ok:true},B:{ok:false}}},{ok:true,outcome:'accepted'},{ok:true,recovery_required:true},{ok:true,verified:false},{}]){
    scope.value=value;assert.equal(vm.runInContext('isApiOk(value)',scope),false);checks++;
  }
  const count=calls.length;const offline=await vm.runInContext('hubCommand("OFF","mode",{mode:1})',scope);
  assert.equal(offline.ok,false);assert.equal(calls.length,count);checks++;
  assert(!between('function selectRemote(','initTheme()').includes('!current.online'));checks++;
}
Promise.all([checkAuth(),checkRecovery(),checkPinIntent(),checkSelectionOwnership()]).then(()=>console.log(JSON.stringify({node:process.version,syntax_files:syntaxCount,checks_passed:checks,transport:'fake callbacks only',not_run:['full browser bootstrap/layout','worker behavior','device communication']}))).catch(error=>{console.error(error);process.exitCode=1;});

/* Device workspace beta. Full navigation on device changes isolates pending requests. */
(()=>{
  const enabled=localStorage.getItem('ams_device_navigation')!=='classic';
  const toggle=document.createElement('button');toggle.className='hdr-btn';toggle.textContent=enabled?'장비 탐색 β → 기존':'기존 → 장비 탐색 β';
  toggle.onclick=()=>{if(!confirm('화면을 다시 엽니다. 미적용 입력은 유지되지 않습니다. 전환할까요?'))return;localStorage.setItem('ams_device_navigation',enabled?'classic':'device');location.reload();};
  document.querySelector('header .ws-status').append(toggle);
  if(!enabled)return;
  document.body.classList.add('device-workspace');
  const style=document.createElement('style');style.textContent=`
    body.device-workspace .main,body.device-workspace>.tabs{margin-left:208px}
    #deviceRail{position:fixed;top:var(--device-rail-top,200px);bottom:0;left:0;width:208px;padding:18px 12px;overflow:auto;background:var(--panel,#fff);border-right:1px solid var(--border,#bbb);z-index:8}
    body.dark-mode #deviceRail{background:#111b2b}body.brutal-mode #deviceRail{background:#f2eee3;color:#111;border-right:2px solid #111}
    #deviceRail button{display:block;width:100%;margin:6px 0;padding:12px;text-align:left;border:1px solid transparent;background:transparent;color:inherit;cursor:pointer;font:inherit}
    #deviceRail button.selected{border-color:currentColor;background:var(--accent,#ffd238);color:#111;font-weight:800}
    body.brutal-mode #deviceRail button{color:var(--ink);border-radius:0}
    body.brutal-mode #deviceRail button.selected{background:var(--ink);color:var(--hazard);border-color:var(--ink)}
    body.brutal-mode #deviceRail small,body.brutal-mode #workspaceContext{color:var(--ink)}
    #deviceRail button:disabled{opacity:.45;cursor:default}#deviceRail small{display:block;margin:14px 8px;font-size:11px}
    #workspaceContext{padding:14px 0;font-weight:700;letter-spacing:.4px}
    body.device-workspace #bruDeviceTabs,body.device-workspace #liveDeviceTabs,body.device-workspace #hist_remote,body.device-workspace #histbDeviceTabs{display:none!important}
    @media(max-width:800px){body.device-workspace .main,body.device-workspace>.tabs{margin-left:0}#deviceRail{position:relative;top:auto;bottom:auto;width:100%;display:flex;overflow:auto;gap:5px;padding:8px;flex-shrink:0}#deviceRail button{min-width:120px;width:auto}#deviceRail small{display:none}}
  `;document.head.append(style);
  const rail=document.createElement('aside');rail.id='deviceRail';rail.setAttribute('aria-label','장비 선택');
  const connectionBar=document.querySelector('.connection-bar');
  connectionBar.after(rail);
  // Header wraps at narrow widths and connection status can add another line.
  // Anchor the rail below their actual bounds instead of a fixed header estimate.
  function positionRail(){
    document.body.style.setProperty('--device-rail-top',`${Math.ceil(connectionBar.getBoundingClientRect().bottom)}px`);
  }
  const railLayoutObserver=new ResizeObserver(positionRail);
  railLayoutObserver.observe(document.querySelector('header'));
  railLayoutObserver.observe(connectionBar);
  window.addEventListener('resize',positionRail);
  positionRail();
  const context=document.createElement('div');context.id='workspaceContext';document.querySelector('main').prepend(context);
  let target=localStorage.getItem('ams_workspace_target')||(viewScope==='overview'?'COMBINED':selectedRemoteId);
  const originalShow=showTab;
  const originalSchedules=renderSchedules;
  const isAll=()=>target==='COMBINED';
  function go(id){
    if(id===target)return;
    if(!confirm('장비를 전환합니다. 미적용 입력은 초기화됩니다. 계속할까요?'))return;
    // Show the accepted selection immediately; full navigation still isolates reads.
    rail.querySelectorAll('button[data-device-id]').forEach(b=>b.classList.toggle('selected',b.dataset.deviceId===id));
    context.textContent=id==='COMBINED'?'전체 현황':deviceDisplayLabel(id)+' · Loading selected device…';
    if(id!=='COMBINED')renderDeviceSelection(id);
    localStorage.setItem('ams_workspace_target',id);
    const current=localStorage.getItem('ams_workspace_tab')||'multi';
    if(id!=='COMBINED'&&current==='multi')localStorage.setItem('ams_workspace_tab','live');
    if(id==='COMBINED'&&['live','port4'].includes(current))localStorage.setItem('ams_workspace_tab','multi');
    localStorage.setItem('ams_selected_remote',id);
    localStorage.setItem('ams_view_scope',id==='COMBINED'?'overview':'device');
    location.reload();
  }
  selectRemote=go;
  renderSchedules=function(list){return originalSchedules(isAll()?list:list.filter(s=>(s.remote_id||'AMS00')===target||s.remote_id==='COMBINED'));};
  function scopeHistory(){
    const id=isAll()?'ALL':target;
    histRemoteId=id;histbRemoteId=id;
    const select=document.getElementById('hist_remote');if(select)select.value=id;
    updateHistFieldAvailability();updateHistFieldAvailabilityBeta();
  }
  showTab=function(name,element,updateScope=true){
    if(name==='multi'&&!isAll()){go('COMBINED');return;}
    if(isAll()&&['live','port4'].includes(name))name='multi';
    viewScope=isAll()?'overview':'device';
    localStorage.setItem('ams_workspace_tab',name);
    scopeHistory();
    return originalShow(name,getTabEl(name),false);
  };
  let signature='';
  function refresh(){
    const rows=latestRemotePayload?.remotes||[];
    const selected=rows.find(r=>(r.id||r.device_id||r.remote_id)===target);
    scopeHistory();
    context.textContent=isAll()?'전체 현황 · 전체 스케줄 / 합산 이력':deviceDisplayLabel(target)+' · '+String(selected?.transport||'연결 대기').toUpperCase()+' · '+(selected?.online?'연결됨':'오프라인 · 기존 제어 잠금 적용');
    document.querySelectorAll('.tabs .tab').forEach(t=>{t.style.display=(isAll()?['multi','schedule','history']:['live','port4','schedule','history']).includes(t.dataset.page)?'':'none';});
    const key=JSON.stringify(rows.map(r=>[r.id||r.device_id||r.remote_id,r.name,r.profile?.name,r.profile?.channel,r.profile?.metadata?.gateway_id,r.online,r.placeholder,r.wireless_connected,r.health?.stale,r.stale,r.gateway_diagnostics?.error]));if(key===signature)return;signature=key;rail.replaceChildren();
    const label=document.createElement('small');label.textContent='WORKSPACE · DEVICE';rail.append(label);
    function button(id,text,disabled=false){const b=document.createElement('button');b.dataset.deviceId=id;b.textContent=text;b.classList.toggle('selected',id===target);b.disabled=disabled;b.onclick=()=>go(id);rail.append(b);}
    button('COMBINED','전체 현황');
    for(const r of rows){const id=r.id||r.device_id||r.remote_id;if(!id||id==='COMBINED'||r.placeholder||!remoteConnectionPresent(r))continue;const io=(r.device_kind||r.profile?.metadata?.device_kind)==='remote_io';button(id,'● '+deviceDisplayLabel(id,rows)+(io?' · IO / 전체에서 확인':''),io);}
    const note=document.createElement('small');note.textContent='연결된 장비만 표시합니다. 연결 설정은 주소 / 설정에서, IO는 전체 현황에서 확인하세요.';rail.append(note);
  }
  viewScope=isAll()?'overview':'device';if(!isAll())selectedRemoteId=target;
  showTab(localStorage.getItem('ams_workspace_tab')||(isAll()?'multi':'live'));
  refresh();renderSchedules(scheduleCache||[]);setInterval(refresh,1000);
})();

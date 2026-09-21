/* Connection diagnostics: rendering and explicit, read-only AI assistance. */
(()=>{
  const el=id=>document.getElementById(id);
  let busy=false;
  const labels={DISABLED:'사용 안 함',LIVE:'데이터 수신 정상',STALE:'데이터 오래됨 · 연결 설정 확인 필요',ERROR:'연결/읽기 실패 · 아래 설정 확인',WAITING_DATA:'통신 연결됨 · 첫 데이터 대기',CONNECTING:'연결 대기 · 수신 기록 없음'};
  async function request(path,options={}){
    const ctx=deviceRequestContext();
    const read=options.method!=='POST'?beginDeviceRead('diagnostics'+path,ctx):null;
    const controller=read?.controller||new AbortController();
    const timer=setTimeout(()=>controller.abort(),options.method==='POST'?55000:8000);
    try{
      const r=await amsFetch(API+'/api/diagnostics'+path,{...options,signal:controller.signal,cache:'no-store'});
      if(!(r.headers.get('content-type')||'').includes('application/json'))throw new Error('진단 API를 사용할 수 없습니다. 서버 업데이트/재시작을 확인하세요.');
      const data=await r.json();
      if(!deviceContextCurrent(ctx) || (read && !deviceReadCurrent('diagnostics'+path,read))) {const e=new Error('Previous selection response ignored');e.name='StaleSelection';throw e;}
      if(!r.ok)throw new Error(data.detail||'진단 요청 실패');
      return data;
    }catch(e){if(!deviceContextCurrent(ctx)){const stale=new Error('Previous selection response ignored');stale.name='StaleSelection';throw stale;}if(e.name==='AbortError')throw new Error('응답 시간이 초과되었습니다. 실행창과 네트워크 상태를 확인하세요.');throw e;}
    finally{clearTimeout(timer);}
  }
  async function refresh(){
    if(busy)return;
    busy=true;el('diagRefresh').disabled=true;
    try{
      const d=await request('');const host=el('diagStatus');host.replaceChildren();
      const title=document.createElement('p');title.textContent='서버 정상 · 실행 '+d.server.uptime_seconds+'초 · 확인 '+new Date().toLocaleTimeString();host.append(title);
      if(!d.devices.length){const empty=document.createElement('p');empty.textContent='등록된 장비가 없습니다. 아래에서 통신 방식과 주소를 등록하세요.';host.append(empty);}
      for(const r of d.devices){const line=document.createElement('p');line.textContent=r.device_id+' · '+r.transport.toUpperCase()+' · '+(labels[r.state]||r.state)+' | 마지막 수신: '+(r.last_success_at||'없음')+' | 연속 실패: '+r.failures+(r.error?' | '+r.error:'');host.append(line);}
      for(const r of d.devices){const line=document.createElement('p');line.textContent=r.device_id+' · '+(r.settings_access||'설정 경로 정보 없음');host.append(line);}
      el('diagAiSetup').textContent=d.gemini_configured?'Gemini 키 설정됨 · '+d.model:'API 키 미설정 · 아래에서 Gemini API 키를 등록하세요.';
    }catch(e){if(e.name==='StaleSelection')return;el('diagStatus').textContent='서버 진단에 접속하지 못했습니다. '+e.message;}
    finally{busy=false;el('diagRefresh').disabled=false;}
  }
  el('diagRefresh').addEventListener('click',refresh);
  el('diagSaveKey').addEventListener('click',async()=>{
    const input=el('diagApiKey'),button=el('diagSaveKey'),status=el('diagKeyStatus');
    if(!input.value.trim()){status.textContent='API 키를 입력해 주세요.';return;}
    button.disabled=true;status.textContent='등록 중…';
    try{
      await request('/api-key',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:input.value.trim()})});
      input.value='';status.textContent='키 등록 완료 · 서버 실행 중 사용 가능 (Google 유효성 검사는 문의 시 수행)';await refresh();
    }catch(e){status.textContent=e.name==='StaleSelection'?'등록 상태를 새로고침해 확인해 주세요.':e.message;}
    finally{input.value='';button.disabled=false;}
  });
  el('diagLogs').addEventListener('click',async()=>{
    el('diagOutput').textContent='최근 로그를 불러오는 중…';
    try{el('diagOutput').textContent=(await request('/logs')).text;}catch(e){if(e.name==='StaleSelection')return;el('diagOutput').textContent=e.message;}
  });
  el('diagAsk').addEventListener('click',async()=>{
    if(!el('diagConsent').checked){el('diagOutput').textContent='Google 전송 안내를 확인하고 동의해 주세요.';return;}
    el('diagAsk').disabled=true;el('diagOutput').textContent='진단 정보 수집 → Google 분석 요청 중… 최대 약 50초 소요됩니다.';
    try{const d=await request('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:el('diagQuestion').value||'연결 문제와 확인 순서를 설명해 주세요.',consent:true})});el('diagOutput').textContent=d.answer;}
    catch(e){if(e.name==='StaleSelection')return;el('diagOutput').textContent=e.message;}finally{el('diagAsk').disabled=false;}
  });
  const modal=el('connModal');
  new MutationObserver(()=>{if(modal.classList.contains('open'))refresh();}).observe(modal,{attributes:true,attributeFilter:['class']});
  setInterval(()=>{if(modal.classList.contains('open')&&!document.hidden)refresh();},5000);
})();

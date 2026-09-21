(()=>{
  const old=document.getElementById('lv_port3_card');if(!old)return;
  const style=document.createElement('style');style.textContent='.saving-card{padding:18px;border:1px solid var(--border,#aaa);border-top:3px solid var(--green,#197e4b);background:var(--panel,transparent)}.saving-title{font-size:11px;font-weight:800}.saving-number{font-size:30px;font-weight:900;margin:10px 0}.saving-note{font-size:11px;line-height:1.6;white-space:pre-line}.saving-card button{margin-top:10px;padding:7px;font:inherit;font-size:11px;cursor:pointer}.saving-aux{display:flex;gap:14px;font-size:12px}.saving-details{margin:16px 0}body.brutal-mode .saving-card{background:var(--paper,#f2eee3);color:var(--ink,#111);border:2px solid #111;border-top:4px solid #197e4b;margin-bottom:16px}.saving-detail-output{white-space:pre-wrap;font:inherit;font-size:12px}';document.head.append(style);
  const cards=[];
  function card(){const c=document.createElement('section');c.className='saving-card';c.innerHTML='<div class="saving-title">오늘의 추정 절감</div><div class="saving-number">—</div><div class="saving-aux"></div><div class="saving-note">계산 데이터 확인 중</div><button type="button">압력 기준 새로 읽기</button>';c.querySelector('button').onclick=async()=>{c.querySelector('button').disabled=true;try{const ctx=deviceRequestContext();await updateSettings(ctx);if(deviceContextCurrent(ctx))await refresh();}finally{c.querySelector('button').disabled=false;}};cards.push(c);return c;}
  const c=card();old.before(c);
  const details=document.createElement('details');details.className='saving-details';const summary=document.createElement('summary');summary.textContent='포트 3 외부 입력 상태';details.append(summary);document.getElementById('page-live').append(details);details.append(old);
  const event=document.getElementById('bru_ev_list')?.closest('.bru-block');if(event)event.before(card());
  let busy=false,lastId='',activeRequest=null;
  window.addEventListener('ams-device-selection',()=>{activeRequest?.controller.abort();activeRequest=null;busy=false;lastId='';message('장비별 계산 기록 확인 중');});
  function message(text){for(const c of cards){c.querySelector('.saving-number').textContent='—';c.querySelector('.saving-aux').textContent='';c.querySelector('.saving-note').textContent=text;}}
  async function refresh(){
    const id=selectedRemoteId;
    if(id!==lastId){lastId=id;message('장비별 계산 기록 확인 중');}
    if(busy)return;
    if(!id||id==='COMBINED'){message('개별 AMS 장비를 선택하세요');return;}
    busy=true;const request=beginDeviceRead('savings');activeRequest=request;const controller=request.controller,timer=setTimeout(()=>controller.abort(),10000);
    const current=()=>activeRequest===request && deviceReadCurrent('savings',request) && deviceContextCurrent(request);
    try{
      const r=await amsFetch(API+'/api/hub/devices/'+encodeURIComponent(id)+'/savings',{cache:'no-store',signal:controller.signal});
      if(!r.ok)throw Error('절감 API 응답 오류 · 서버 재시작 확인');const d=await r.json();if(!current())return;
      if(!d.available){message(d.reason||'계산 데이터 부족');return;}
      const fmt=(v,n=1)=>Number(v).toLocaleString('ko-KR',{maximumFractionDigits:n});
      for(const c of cards){c.querySelector('.saving-number').textContent=fmt(d.saved_litres)+' L';c.querySelector('.saving-aux').textContent=fmt(d.saved_kwh,3)+' kWh · '+fmt(d.saved_won)+' 원';c.querySelector('.saving-note').textContent=id+' · '+d.operation_kpa+' → '+d.standby_kpa+' kPa (+100 기준)\n집계 스탠바이 '+fmt(d.standby_seconds/60)+'분 · 제외 구간 '+d.excluded_intervals+'개\n현재 압력으로 오늘 기록을 추정 · 과거 압력 변경 미반영';}
      for(const c of cards){let more=c.querySelector('details');if(!more){more=document.createElement('details');more.innerHTML='<summary>DATA 환산계수 · 계산 상세</summary><div class="saving-detail-output"></div>';c.append(more);}more.querySelector('div').textContent='스탠바이 사용량 '+fmt(d.standby_litres)+' L\n예상 Operation 사용량 = '+fmt(d.standby_litres)+' ÷ '+fmt(d.ratio,4)+'\n전력 원단위 '+d.kwh_per_m3+' kWh/m³ · 요금 '+d.price_per_kwh+' 원/kWh\n압력비에 소비량이 비례한다는 가정입니다. 누락·전환 구간은 제외합니다.';}
    }catch(e){if(current())message(e.name==='AbortError'?'절감 조회 시간 초과':e.message);}finally{clearTimeout(timer);if(activeRequest===request)busy=false;}
  }
  const initialMessage=message;message=function(text){initialMessage(text);for(const c of cards)c.querySelector('details')?.remove();};
  refresh();setInterval(refresh,15000);
})();

(function(g){
'use strict';
function mount(host,editor,models,showPort){
 const el=(tag,text)=>{const n=document.createElement(tag);n.textContent=text||'';return n;};
 const heading=el('h2','1단계 · 모의 PD 패킷 검증'),note=el('p','마스터 입력 이미지 전체를 HEX로 입력하세요. 고정 영역 2바이트를 포함합니다. 실제 장비 요청 없음.'),input=el('textarea');input.rows=3;input.style.width='100%';input.placeholder='예: 02 01 3E 80 (ISE70 MPa, 입력 4 bytes 구성일 때)';input.setAttribute('aria-label','모의 마스터 입력 HEX');
 const connected=el('input');connected.type='checkbox';connected.checked=true;const cl=el('label','모의 전송 연결됨');cl.append(connected);
 const old=el('input');old.type='checkbox';const ol=el('label','31초 전 패킷으로 검사');ol.append(old);
 const diagnostic=el('input');diagnostic.type='checkbox';diagnostic.dataset.diagnostic='true';const dl=el('label','모의 조건: 각 포트의 진단 설정 V_diAG=1 확인 (기본값으로 가정하지 않음)');dl.append(diagnostic);
 const run=el('button','모의 패킷 해석'),output=el('pre'),ports=el('div');host.append(heading,note,input,cl,ol,dl,run,ports,output);
 run.onclick=()=>{
  ports.replaceChildren();
  try{
   const tokens=input.value.trim()?input.value.trim().split(/\s+/):[];
   if(!tokens.every(t=>/^[0-9a-fA-F]{2}$/.test(t)))throw Error('각 바이트를 두 자리 HEX와 공백으로 입력하세요');
   const config=editor.getConfig(),now=Date.now(),packet={bytes:tokens.map(t=>parseInt(t,16)),connected:connected.checked,timestamp:now-(old.checked?31000:0)};
   const result=g.IoddPdDecoder.decode(config,models,packet,{now,diagnostics:diagnostic.checked?Object.fromEntries(config.ports.map(p=>[p.id,{V_diAG:1}])):{}});output.textContent=JSON.stringify(result,null,2);
   for(const port of result.ports.filter(p=>config.ports[p.port-1].enabled&&['manual','autostart'].includes(config.ports[p.port-1].mode))){
    const b=el('button','P'+port.port+' 결과를 위젯에 표시 · '+port.quality);b.onclick=()=>showPort(config.ports[port.port-1],config,port,packet.timestamp);ports.append(b);
   }
  }catch(err){output.textContent='해석 실패: '+err.message;}
 };
}
g.IoddPacketLab={mount};
})(globalThis);

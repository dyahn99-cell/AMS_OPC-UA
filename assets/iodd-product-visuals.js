/* Shared product assets. Product identity selects the model; instance state
 * belongs to channel/port and never lives in a shared GLB. */
(function(g){
'use strict';
const assets={
 base:{part:'EXW1-BMTAC',file:'EXW1-BMTAC.display.glb',poster:'EXW1-BMTAC.png'},
 rla:{part:'EXW1-RLAPA8C',file:'EXW1-RLAPA8C.display.glb',poster:'EXW1-RLAPA8C.png'},
 pf3a:{part:'PF3A701H-L30',file:'PF3A701H-L30.display.glb',poster:'PF3A701H-L30.png'},
 pfuw:{part:'PFUW760-L1',file:'PFUW760-L1.display.glb',poster:'PFUW760-L1.png'}
};
const mounted=new WeakMap();
function remote(r){return r?.model==='rla'||r?.model==='rla1'?assets.rla:null;}
function product(m){if(/^PF3A701H.*L3/.test(m?.name||''))return assets.pf3a;return m?.name?.startsWith('PFUW760-L1')?assets.pfuw:null;}
function clear(host){const old=mounted.get(host);if(old){old.viewer.removeAttribute('src');mounted.delete(host);}host.replaceChildren();}
function mount(host,asset,{label='',note=''}={}){
 if(!asset){clear(host);const p=document.createElement('p');p.className='rv-note';p.textContent=label+' · 해당 제품의 3D 파일은 아직 등록되지 않았습니다.';host.append(p);return null;}
 const old=mounted.get(host);
 if(old?.asset.file===asset.file&&old.viewer.parentElement?.parentElement===host){old.label.textContent=label||asset.part;old.note.textContent=note;return old.viewer;}
 clear(host);const shell=document.createElement('div');shell.className='pv-shell';
 const title=document.createElement('strong');title.className='pv-label';title.textContent=label||asset.part;
 const viewer=document.createElement('model-viewer');viewer.setAttribute('src','/assets/product-models/'+asset.part+'.outline.glb');viewer.alt=asset.part+' 3D 제품 모델';viewer.setAttribute('camera-controls','');viewer.setAttribute('touch-action','pan-y');viewer.setAttribute('environment-image','neutral');viewer.setAttribute('shadow-intensity','0');viewer.setAttribute('exposure','1');viewer.setAttribute('camera-orbit','35deg 65deg auto');viewer.setAttribute('interaction-prompt','none');viewer.setAttribute('loading','eager');viewer.className='pv-model';
 const status=document.createElement('p');status.className='pv-status';status.textContent='3D 로딩 중…';
 
 const progress=document.createElement('div');progress.slot='progress-bar';progress.hidden=true;viewer.append(progress);
 viewer.addEventListener('load',()=>{status.textContent=shell.dataset.view==='line'?'제품 윤곽선 · 드래그로 회전':'드래그로 회전 · 휠/핀치로 확대';viewer.dataset.ready='true';});
 viewer.addEventListener('error',()=>{status.textContent='3D 로딩 실패 · 데이터 조회와 조작은 계속 사용할 수 있습니다.';viewer.dataset.ready='error';});
 shell.dataset.view='line';
 const actions=document.createElement('div');actions.className='pv-actions';
 const switchView=document.createElement('button');switchView.type='button';switchView.textContent='3D 보기';switchView.onclick=()=>{const isLine=shell.dataset.view==='line';shell.dataset.view=isLine?'3d':'line';viewer.dataset.ready='loading';viewer.setAttribute('src','/assets/product-models/'+(isLine?asset.file:asset.part+'.outline.glb')); viewer.setAttribute('shadow-intensity',isLine?'0.6':'0');switchView.textContent=isLine?'선화 보기':'3D 보기';};
 const home=document.createElement('button');home.type='button';home.textContent='기본 시점';home.onclick=()=>{viewer.cameraOrbit='35deg 65deg auto';viewer.cameraTarget='auto auto auto';viewer.fieldOfView='auto';viewer.jumpCameraToGoal();};
 const rotate=document.createElement('button');rotate.type='button';rotate.textContent='자동 회전';rotate.setAttribute('aria-pressed','false');rotate.onclick=()=>{const on=!viewer.hasAttribute('auto-rotate');viewer.toggleAttribute('auto-rotate',on);rotate.setAttribute('aria-pressed',String(on));};
 const expand=document.createElement('button');expand.type='button';expand.textContent='크게 보기';expand.onclick=async()=>{try{if(document.fullscreenElement===shell)await document.exitFullscreen();else await shell.requestFullscreen();}catch(e){status.textContent='전체 화면을 열 수 없습니다. 회전·확대는 현재 화면에서 가능합니다.';}};
 actions.append(switchView,home,rotate);const tools=document.createElement('details');tools.className='pv-tools';const summary=document.createElement('summary');summary.textContent='회전·표현 옵션';tools.append(summary,actions);const footer=document.createElement('div');footer.className='pv-footer';footer.append(status,expand);const caption=document.createElement('p');caption.className='rv-note';caption.textContent=note;
 status.textContent='제품 윤곽선 · 드래그로 회전';shell.append(title,viewer,footer,tools,caption);host.append(shell);mounted.set(host,{asset,viewer,label:title,note:caption});return viewer;
}
function mountBase(){const panel=document.getElementById('base-visual-panel'),host=document.getElementById('base-visual');if(!panel||!host)return;panel.addEventListener('toggle',()=>{if(panel.open)mount(host,assets.base,{label:'EXW1-BMTAC · '+(g.connectionProfile?.host||'192.168.0.10'),note:'베이스 제품 외형 · 통신 상태와 수신값은 별도로 표시합니다.'});});}
g.ProductVisuals={assets,remote,product,mount,clear,mountBase};
})(globalThis);

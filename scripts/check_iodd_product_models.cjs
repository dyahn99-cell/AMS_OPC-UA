/* All GLBs and renderer are local. No hardware requests are allowed here. */
const assert=require('node:assert/strict');
const {chromium}=require('C:/Users/dyahn/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],external=[],posts=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{const request=route.request(),url=new URL(request.url());if(request.method()==='POST'){posts.push(url.pathname);return route.abort();}if(url.hostname!=='127.0.0.1'){external.push(request.url());return route.abort();}requests.push(url.pathname);return route.continue();});
 try{
  await page.goto('http://127.0.0.1:8011/#port=2&definition=b920ace7772c1d0982eaa99475e3d4df903b859a9b1ddc170640bbe24ecfe638');
  await page.waitForFunction(()=>document.querySelectorAll('#remote-visual model-viewer').length===1&&Array.from(document.querySelectorAll('#remote-visual model-viewer')).every(v=>v.dataset.ready==='true'));
  await page.locator('[data-workspace=remote]').click();assert.equal(await page.locator('#ui-master-details').evaluate(d=>d.open),false);await page.locator('#ui-master-details > summary').click();assert.equal(await page.locator('#remote-row-1 .channel-product-thumb img').getAttribute('alt'),'EXW1-RLAPA8C');
  await page.locator('#rv-drawing .pv-tools').evaluate(d=>d.open=true);await page.locator('#rv-drawing').getByRole('button',{name:'3D 보기',exact:true}).click();
  await page.locator('#rv-drawing model-viewer').evaluate(v=>{window.savedRemoteViewer=v;v.cameraOrbit='20deg 75deg auto';v.jumpCameraToGoal();});
  await page.getByRole('button',{name:'PORT1 논리 포트 선택',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'PORT1 P3 선택',exact:true}).isVisible(),true);
  await page.getByRole('button',{name:'PORT1 P1 선택',exact:true}).click();
  assert.equal(await page.locator('#port').inputValue(),'1');assert.equal(await page.locator('#rv-product-image').isVisible(),false);
  assert.equal(await page.locator('#rv-drawing model-viewer').evaluate(v=>v===window.savedRemoteViewer),true);
  await page.locator('[data-workspace=remote]').click();await page.getByRole('button',{name:'P2 상태 선택',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#ui-device-stage model-viewer')?.dataset.ready==='true');
  assert.match(await page.locator('#ui-device-location').innerText(),/CH1 \/ P2/);
  assert.match(await page.locator('#model').inputValue(),/^b920ace/);
  await page.locator('[data-workspace=remote]').click();await page.locator('#rv-drawing .pv-tools').evaluate(d=>d.open=true);await page.locator('#rv-drawing').getByRole('button',{name:'자동 회전',exact:true}).click();assert.equal(await page.locator('#rv-drawing model-viewer').evaluate(v=>v.hasAttribute('auto-rotate')),true);
  await page.locator('#rv-drawing').getByRole('button',{name:'기본 시점',exact:true}).click();
  await page.locator('[data-workspace=engineering]').click();await page.locator('#base-visual-panel summary').click();await page.waitForFunction(()=>document.querySelector('#base-visual model-viewer')?.dataset.ready==='true');
  assert.equal(await page.locator('model-viewer').count(),3);
  await page.evaluate(()=>RemoteVisual.input({connected:true,timestamp:Date.now(),bytes:[8,12]}));
  assert.equal(await page.locator('#rv-physical-2').getAttribute('data-state'),'error');
  await page.evaluate(()=>RemoteVisual.clear());assert.equal(await page.locator('#rv-physical-2').getAttribute('data-state'),'unknown');
  await page.locator('[data-workspace=engineering]').click();await page.locator('#channel-config').evaluate(d=>d.open=true);await page.locator('#remote-row-2 select').selectOption('rla');await page.locator('#remote-row-2 .channel-product-thumb').click();
  assert.equal(await page.locator('#channel').inputValue(),'2');assert.match(await page.locator('#rv-drawing .pv-label').innerText(),/^CH2/);assert.equal(await page.locator('#rv-product-image').isVisible(),false);
  await page.locator('[data-workspace=engineering]').click();await page.locator('#channel-config').evaluate(d=>d.open=true);await page.locator('#remote-row-2 select').selectOption('rlb');assert.equal(await page.locator('#rv-drawing model-viewer').count(),0);assert.match(await page.locator('#rv-drawing img').getAttribute('src'),/rlb\.png$/);
  await page.locator('#remote-row-1 .channel-product-thumb').click();
  await page.waitForFunction(()=>document.querySelector('#rv-drawing model-viewer')?.dataset.ready==='true');
  await page.locator('#rv-drawing model-viewer').evaluate(v=>v.removeAttribute('auto-rotate'));
  await page.locator('[data-workspace=remote]').click();await page.locator('#remote-visual').screenshot({path:'outputs/iodd/product-models-dashboard.png'});
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(posts,[]);
  assert(requests.some(p=>p.endsWith('EXW1-RLAPA8C.png')));assert(requests.some(p=>p.endsWith('PFUW760-L1.outline.glb')));
  console.log('PASS: 3 local GLBs, product posters, physical-to-logical port selection, preserved 3D camera, channel isolation, unknown-model fallback, status overlay, no external or hardware requests.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

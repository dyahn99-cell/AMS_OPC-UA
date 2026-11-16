/* Operational UI regression. Every device request is intercepted; no hardware writes. */
const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('C:/Users/dyahn/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const models=JSON.parse(fs.readFileSync('outputs/iodd/catalog.json','utf8')).models,flow=models.find(m=>m.sha256.startsWith('b920ace'));
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1536,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));let serial=0,fail=false,calls=0;
 await page.route('**/*',async route=>{const req=route.request();if(req.method()!=='POST')return route.continue();calls++;const q=req.postDataJSON(),path=new URL(req.url()).pathname;let d;
 if(path==='/isdu'){const item=flow.items.find(i=>i.id===q.item);const size=Math.ceil(Number(item?.datatype.bitLength||8)/8);d={...q,bytes:Array(size).fill(0),timestamp:Date.now()};}
 else if(path==='/read'){if(fail)return route.fulfill({status:502,contentType:'application/json',body:JSON.stringify({error:'UI test disconnect'})});const bytes=Array(q.inputBytes).fill(0),value=1000+[0,120,70,200,160,210][serial++%6];bytes[0]=8;bytes[1]=4;bytes.splice(18,8,0,0x12,0xd6,0x87,value>>8,value&255,0,0);d={...q,connected:true,bytes,timestamp:Date.now()};}
 else throw Error('Unexpected device operation '+path);
 await route.fulfill({contentType:'application/json',body:JSON.stringify(d)});
 });
 const url='http://127.0.0.1:8011/#channel=1&port=2&definition='+flow.sha256;
 await page.goto(url);await page.waitForFunction(()=>!document.getElementById('read').disabled);
 assert.equal(await page.locator('#device-picker').evaluate(d=>d.open),false);assert.equal(calls,0);
 assert.match(await page.locator('.primary-measurement h3').innerText(),/순간 유량/);assert.equal(await page.locator('.primary-measurement svg').count(),0);
 await page.locator('#read').click();await page.waitForFunction(()=>document.querySelector('.focus-statistics'));
 await page.waitForFunction(()=>document.querySelectorAll('.focus-statistics strong').length===3);
 assert.match(await page.locator('#ui-data-quality').innerText(),/수신됨|일부 값 해석 보류/);assert.match(await page.locator('.primary-measurement .iw-value').innerText(),/L\/min/);
 const first=await page.locator('.primary-measurement').evaluate(e=>e.dataset.itemId);
 await page.waitForTimeout(3200);await page.locator('#stop').click();assert.match(await page.locator('#ui-data-quality').innerText(),/갱신 중지/);
 await page.evaluate(()=>{const b=document.createElement('div');b.id='test-banner';b.textContent='모의 수신 · UI 검증 화면 (실제 장비 값 아님)';b.style.cssText='position:fixed;right:18px;bottom:12px;z-index:999;background:#fff3cb;color:#795314;border:1px solid #caa454;padding:10px 16px;border-radius:6px;font:12px sans-serif';document.body.append(b);});
 await page.screenshot({path:'outputs/iodd/operational-focus-mock.png'});
 await page.locator('#cards .focus-select[aria-pressed=false]').first().click();assert.notEqual(await page.locator('.primary-measurement').evaluate(e=>e.dataset.itemId),first);
 const chosen=await page.locator('.primary-measurement').evaluate(e=>e.dataset.itemId);await page.reload();await page.waitForFunction(()=>document.querySelector('.primary-measurement'));assert.equal(await page.locator('.primary-measurement').evaluate(e=>e.dataset.itemId),chosen);
 await page.locator('#read').click();await page.waitForFunction(()=>['수신됨','일부 값 해석 보류'].includes(document.getElementById('ui-data-quality').textContent));fail=true;await page.waitForFunction(()=>document.getElementById('ui-data-quality').textContent==='읽기 실패');assert.equal(await page.locator('#ui-device-condition').innerText(),'판단 대기');assert.equal(await page.locator('.primary-measurement svg').count(),0);await page.locator('#stop').click();
 await page.locator('#ui-overview').click();assert.equal(await page.locator('.channel-overview-card').count(),1);await page.getByRole('button',{name:'CH1 리모트 보기',exact:true}).click();assert.equal(await page.locator('#ui-remote-view').isVisible(),true);await page.getByRole('button',{name:'P2 디바이스 보기',exact:true}).click();assert.equal(await page.locator('#ui-monitor-view').isVisible(),true);
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.screenshot({path:'outputs/iodd/operational-focus-mobile.png',fullPage:true});assert.deepEqual(errors,[]);
 console.log('PASS: role-based hero, actual sample chart, engineering units, persisted primary selection, disconnect clears chart, truthful quality, overview navigation, mobile. All device requests mocked.');
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});

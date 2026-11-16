/* Browser integration test: every hardware endpoint is intercepted. */
const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('C:/Users/dyahn/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const models=JSON.parse(fs.readFileSync('outputs/iodd/catalog.json','utf8')).models;
const flow=models.find(m=>m.sha256.startsWith('b920ace'));
const output=models.find(m=>m.name==='EX260-MIL1'&&m.deviceId==='661');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage({viewport:{width:1400,height:1000}}),errors=[],calls=[];
 page.on('pageerror',e=>errors.push(e.message));
 let unit=0,ioBytes=Array(16).fill(0),digitalWords=[0x8000],test=null,serial=0;
 const snap=q=>{
  if(q.kind!=='iolink')return {...q,words:[...digitalWords],bits:16,timestamp:Date.now()};
  const fields=output.items.filter(i=>i.source==='PD OUT'&&i.layout===q.layout).map((i,n)=>({item:i.id,value:ioBytes[n],writable:true}));
  const contacts=fields.flatMap((f,n)=>Array.from({length:8},(_,bit)=>({key:f.item+':'+bit,item:f.item,bit,label:'OUT '+(n*8+bit)})));
  return {...q,bytes:[...ioBytes],fields,contacts,timestamp:Date.now()};
 };
 await page.route('**/*',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;
  if(!['/read','/isdu','/isdu-write','/output-read','/output-write','/output-test-start','/output-test-status','/output-test-stop'].includes(path))return route.continue();
  const q=req.postDataJSON();calls.push({path,q});let d;
  if(path==='/isdu'){
   const m=models.find(m=>m.sha256===q.definition),i=m.items.find(i=>i.id===q.item);assert(i);const bits=Number(i.datatype.bitLength)||8;
   let value=q.item==='V_Unit'?unit:q.item==='V_diAG'?1:0;
   d={...q,bytes:Array.from({length:bits/8},(_,n)=>(value >>> (8*(bits/8-n-1)))&255),timestamp:Date.now()};
  }else if(path==='/read'){
   const bytes=Array(q.inputBytes).fill(0);bytes[0]=8;bytes[1]=4;bytes.splice(18,8,0,0x12,0xd6,0x87,3,0xe8,0,0);
   d={channel:q.channel,inputOffset:q.inputOffset,connected:true,bytes,timestamp:Date.now()+(serial++/10)};
  }else if(path==='/output-read')d=snap(q);
  else if(path==='/output-write'){
   if(q.kind==='iolink'){assert.deepEqual(q.expected,ioBytes);const n=output.items.filter(i=>i.source==='PD OUT').findIndex(i=>i.id===q.item);assert(n>=0);ioBytes[n]=q.value;}
   else{assert.deepEqual(q.expected,digitalWords);const mask=1<<q.bit;digitalWords[0]=q.value?digitalWords[0]|mask:digitalWords[0]&~mask;}
   d={...snap(q),verified:true};
  }else if(path==='/output-test-start'){
   assert.deepEqual(q.expected,q.target.kind==='iolink'?ioBytes:digitalWords);test={id:'mock-job',target:q.target,state:'running',step:1,total:q.contacts.length,label:'OUT 0',cleanup:'not_needed'};d=test;
  }else if(path==='/output-test-stop'){test.state='cancelled';test.cleanup='off_verified';test.snapshot=snap(test.target);d=test;}
  else if(path==='/output-test-status')d=test;
  else throw Error('unexpected hardware request '+path);
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(d)});
 });
 try{
  await page.goto('http://127.0.0.1:8011/#port=2&definition='+flow.sha256);
  await page.waitForFunction(()=>!document.getElementById('read').disabled);
  await page.locator('#read').click();
  await page.waitForFunction(()=>document.querySelector('#cards .iw-value')?.textContent==='15 L/min');
  assert.match(await page.locator('#cards').innerText(),/1,234,567 L/);
  await page.locator('#cards .iw-card').first().locator('select').selectOption('trend');
  await page.waitForFunction(()=>!!document.querySelector('#cards svg'));
  await page.locator('#stop').click();
  assert(calls.some(c=>c.path==='/isdu'&&c.q.port===2&&c.q.item==='V_Unit'));
  await page.screenshot({path:'outputs/iodd/live-functional-flow.png',fullPage:true});
  unit=1;await page.locator('#port').selectOption('1');await page.locator('#port').selectOption('2');
  await page.locator('#read').click();await page.waitForFunction(()=>document.querySelector('#cards .iw-value')?.textContent==='1,000 raw');await page.locator('#stop').click();
  await page.locator('#port').selectOption('1');await page.locator('#device-picker').evaluate(d=>d.open=true);await page.locator('#model').selectOption(output.sha256);
  await page.locator('[data-workspace=output]').click();assert.equal(await page.locator('#output-panel').isVisible(),true);
  await page.locator('#output-read').click();await page.waitForFunction(()=>document.getElementById('output-status').textContent.includes('조회 완료'));
  await page.locator('#output-arm').check();await page.getByRole('button',{name:'OUT 0 ON',exact:true}).click();
  await page.waitForFunction(()=>document.getElementById('output-status').textContent.includes('적용·재조회 일치'));assert.equal(ioBytes[0],1);assert(ioBytes.slice(1).every(n=>n===0));
  await page.getByRole('button',{name:'OUT 0 OFF',exact:true}).click();await page.waitForFunction(()=>document.getElementById('output-status').textContent.includes('적용·재조회 일치'));assert.equal(ioBytes[0],0);
  await page.getByRole('checkbox',{name:'OUT 0 테스트 선택',exact:true}).check();await page.locator('#output-test-start').click();
  await page.waitForFunction(()=>!document.getElementById('output-test-stop').disabled);assert.equal(await page.locator('#channel').isDisabled(),true);
  await page.locator('#output-test-stop').click();await page.waitForFunction(()=>document.getElementById('output-status').textContent.includes('중지 완료'));
  assert.equal(await page.locator('#channel').isEnabled(),true);
  await page.screenshot({path:'outputs/iodd/live-functional-output.png',fullPage:true});
  await page.locator('[data-workspace=engineering]').click();await page.locator('#channel-config').evaluate(d=>d.open=true);await page.locator('#remote-row-2 select').selectOption('rdy');await page.locator('#channel').selectOption('2');await page.locator('[data-workspace=output]').click();
  await page.locator('#output-read').click();await page.waitForFunction(()=>document.getElementById('output-status').textContent.includes('조회 완료'));
  await page.locator('#output-arm').check();await page.getByRole('button',{name:'OUT 1 ON',exact:true}).click();await page.waitForFunction(()=>document.getElementById('output-status').textContent.includes('적용·재조회 일치'));
  assert.deepEqual(digitalWords,[0x8002]);assert(calls.some(c=>c.path==='/output-write'&&c.q.channel===2&&c.q.outputOffset===64));
  assert.deepEqual(errors,[]);
  console.log('PASS: live units, raw fallback, actual history, independent P1/P2 models, shared IO/digital output controls, contact stop, configuration lock, allocated CH2 offset. Hardware endpoints mocked: '+calls.length);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

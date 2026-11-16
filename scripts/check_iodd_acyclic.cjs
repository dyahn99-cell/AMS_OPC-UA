const assert=require('node:assert/strict'),fs=require('node:fs');
const api=require('../assets/iodd-acyclic-diagnostics.js');
const reviews=JSON.parse(fs.readFileSync('outputs/iodd/diagnostic-review.json','utf8')).definitions.filter(r=>r.required_reads);
async function main(){
 assert.equal(reviews.length,16);
 for(const review of reviews){
  const context={master:'a',revision:1,base:'base',channel:1,port:1,definition:review.definition_key};
  const reply=q=>({...q,connected:true,timestamp:100,bytes:Array(api.plan(review).find(s=>s.index===q.index).length).fill(0)});
  let result=await api.read(context,review,reply,{now:()=>100});
  assert(result.fields.every(f=>f.quality==='good'));assert.equal(result.source,'ACYCLIC');
  for(const key of ['master','revision','base','channel','port','definition','index','subindex','requestId']){
   result=await api.read(context,review,q=>({...reply(q),[key]:'wrong'}),{now:()=>100});
   assert(result.fields.every(f=>f.quality==='identity_mismatch'&&f.value===null),key);
  }
  for(const [patch,quality] of [[{timestamp:101},'invalid_timestamp'],[{timestamp:-30000},'stale'],[{connected:false},'disconnected'],[{error:'ISDU error'},'device_read_error'],[{bytes:[]},'invalid_payload']]){
   result=await api.read(context,review,q=>({...reply(q),...patch}),{now:()=>100});assert(result.fields.every(f=>f.quality===quality));
  }
  result=await api.read(context,review,null);assert(result.fields.every(f=>f.quality==='transport_unavailable'));
  result=await api.read(context,review,()=>new Promise(()=>{}),{timeout:1});assert(result.fields.every(f=>f.quality==='timeout'));
  result=await api.read(context,review,q=>{context.port=2;return reply(q);},{now:()=>100});assert(result.fields.every(f=>f.quality==='configuration_changed'));
 }
 const spec={kind:'events',length:15};
 const events=api.decode(spec,[0xf4,0x18,0,0xa4,0x18,0x50,0,0,0,0,0,0,0,0,0]).events;
 assert.equal(events[0].severity,'error');assert.equal(events[0].active,true);assert.equal(events[1].active,false);assert.equal(events[1].mode,2);
 assert.throws(()=>api.decode({kind:'device_status',length:1},[5]));
 assert.throws(()=>api.decode({kind:'position_qualifier',length:1},[4]));
 assert.equal(api.decode({kind:'device_status',length:1},[4]).severity,'error');
 // UI smoke check without starting a server or browser.
 global.document={createElement:tag=>({tag,children:[],textContent:'',append(...xs){this.children.push(...xs);},setAttribute(){}})};
 const host=document.createElement('div');api.mount(host,reviews.find(r=>r.model.startsWith('EX600')));
 const box=host.children[0],row=box.children[2];row.children[1].value='04';row.children[2].onclick();assert.match(row.children[3].textContent,/고장/);
 console.log('PASS: 16 exact ISDU plans, identity/revision isolation, timing, payload failures, event decoding and widget smoke test');
}
main().catch(e=>{console.error(e);process.exitCode=1;});

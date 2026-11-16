const assert=require('node:assert/strict'),fs=require('node:fs');
const profiles=require('../assets/iodd-diagnostic-profiles.js'),pd=require('../assets/iodd-pd-decoder.js'),master=require('../assets/iodd-master-config.js');
const models=JSON.parse(fs.readFileSync('outputs/iodd/catalog.json','utf8')).models;
let layouts=0;
for(const [sha,profile] of Object.entries(profiles)){
 assert(profile.evidence.sha256||(profile.evidence.source_kind==='official_pdf_web_extraction'&&profile.evidence.url.startsWith('https://www.smcworld.com/')));assert(profile.evidence.pdf_pages.length);
 const model=models.find(m=>m.sha256===sha);assert(model);
 for(const layout of model.layouts){
  const fields=model.items.filter(i=>i.source==='PD IN'&&i.layout===layout.id&&i.widget==='number'&&(!profile.field_checks||profile.field_checks[i.id]));
  let word=0n;for(const i of fields){const range=i.datatype.ranges[0]||{lowerValue:0,upperValue:0},bits=BigInt(i.datatype.bitLength),n=BigInt(Math.trunc((Number(range.lowerValue)+Number(range.upperValue))/2));word|=(n&((1n<<bits)-1n))<<BigInt(i.bitOffset);}
  for(const f of fields)for(const bit of profile.field_checks?.[f.id]?.one_bits||[])word|=1n<<BigInt(bit);
  const len=Math.ceil(Number(layout.directions.find(d=>d.source==='PD IN').bitLength)/8);
  const bytes=Array.from({length:len},(_,n)=>Number((word>>BigInt(8*(len-1-n)))&255n));
  const c=master.create();c.input=2+len;Object.assign(c.ports[0],{enabled:true,mode:'manual',input:len,definition:sha,layout:layout.id});
  const output=Math.ceil(Number(layout.directions.find(d=>d.source==='PD OUT')?.bitLength||0)/8);c.output=2+output;c.ports[0].output=output;
  const packet={connected:true,timestamp:1,bytes:[2,1,...bytes]},options={now:1,diagnostics:{1:{V_diAG:1}}};
  let result=pd.decode(c,models,packet,options);for(const f of fields)assert.equal(result.ports[0].fields.find(x=>x.item_id===f.id).quality,'good',model.name);
  if(Object.keys(profile.required_configuration).length){result=pd.decode(c,models,packet,{now:1});assert(result.ports[0].fields.filter(f=>fields.some(i=>i.id===f.item_id)).every(f=>f.quality==='diagnostic_configuration_required'));}
  const bits=[...new Set([...profile.bits,...fields.flatMap(f=>profile.field_checks?.[f.id]?.one_bits||[])])];
  for(const bit of bits){
   const bad=structuredClone(packet);bad.bytes[2+len-1-Math.floor(bit/8)]^=1<<(bit%8);
   result=pd.decode(c,models,bad,options);
   for(const f of fields){
    const gate=profile.field_checks?.[f.id];
    const affected=!gate||[...gate.zero_bits,...gate.one_bits].includes(bit);
    const decoded=result.ports[0].fields.find(x=>x.item_id===f.id);
    assert.equal(decoded.quality,affected?'device_diagnostic':'good',`${model.name} ${f.name} bit ${bit}`);
    if(affected)assert.equal(decoded.value,null);
   }
  }
  for(const bit of profile.bits){const item=model.items.find(i=>i.source==='PD IN'&&i.layout===layout.id&&i.bitOffset===String(bit)&&i.datatype.type==='BooleanT');if(!item)continue;const bad=structuredClone(packet);bad.bytes[2+len-1-Math.floor(bit/8)]|=1<<(bit%8);const value=pd.decode(c,models,bad,options).ports[0].fields.find(f=>f.item_id===item.id);assert.equal(value.value,true);}
  layouts++;
 }
}
assert.equal(Object.keys(profiles).length,172);
const audit=JSON.parse(fs.readFileSync('outputs/iodd/diagnostic-review.json','utf8'));
assert.equal(audit.definitions.length,239);assert.equal(new Set(audit.definitions.map(r=>r.definition_key)).size,239);
for(const r of audit.definitions){assert(r.reason);assert(r.pdf_pages.length);assert.equal(!!profiles[r.definition_key],r.status==='pd_applied');}
console.log(`PASS: 172 exact diagnostic profiles / ${layouts} layouts, every error bit and disabled/unconfirmed diagnostics`);

const assert=require('node:assert/strict'),fs=require('node:fs');
const api=require('../assets/iodd-register-input.js'),master=require('../assets/iodd-master-config.js');
const models=JSON.parse(fs.readFileSync('outputs/iodd/catalog.json','utf8')).models;
const m=models.find(m=>m.name==='ISE70'),c=master.create();c.input=4;Object.assign(c.ports[0],{enabled:true,mode:'manual',input:2,definition:m.sha256,layout:3});
const map={confirmed:true,base:c.base,channel:1,address:100,functionCode:4,byteOffset:0,wordByteOrder:'high-low'};
const options={now:1000,diagnostics:{1:{V_diAG:1}}};
(async()=>{
 let calls=0;
 const reader=async r=>{calls++;assert.equal(r.functionCode,4);assert.equal(r.count,2);return {...r,connected:true,timestamp:1000,words:[0x0201,0x3e80]};};
 let result=await api.read(c,models,map,reader,options);assert.equal(result.decoded.ports[0].fields[0].raw,2000);assert.equal(calls,1);
 await assert.rejects(api.read(c,models,{...map,confirmed:false},reader,options));assert.equal(calls,1);
 await assert.rejects(api.read(c,models,{...map,functionCode:16},reader,options));assert.equal(calls,1);
 result=await api.read(c,models,map,async r=>({...await reader(r),channel:2}),options);assert.equal(result.error,'response_identity_mismatch');assert(result.decoded.ports[0].fields.every(f=>f.value===null));
 result=await api.read(c,models,map,async()=>{throw Error('timeout');},options);assert.equal(result.decoded.quality,'disconnected');
 result=await api.read(c,models,{...map,wordByteOrder:'low-high'},async r=>({...r,connected:true,timestamp:1000,words:[0x0102,0x803e]}),options);assert.equal(result.decoded.ports[0].fields[0].raw,2000);
 result=await api.read(c,models,{...map,byteOffset:1},async r=>({...r,connected:true,timestamp:1000,words:[0xff02,0x013e,0x8000]}),options);assert.equal(result.decoded.ports[0].fields[0].raw,2000);
 result=await api.read(c,models,map,async r=>{c.ports[0].layout=0;return reader(r);},options);assert.equal(result.decoded.ports[0].layout,3);
 console.log('PASS: injected read, no write codes, explicit mapping, identity, timeout, word order, odd byte offset, concurrent edit snapshot');
})().catch(e=>{console.error(e);process.exitCode=1;});

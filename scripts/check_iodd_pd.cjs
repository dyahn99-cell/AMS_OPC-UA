const assert=require('node:assert/strict'),fs=require('node:fs');
const api=require('../assets/iodd-pd-decoder.js'),master=require('../assets/iodd-master-config.js');
const models=JSON.parse(fs.readFileSync('outputs/iodd/catalog.json','utf8')).models,rules=JSON.parse(fs.readFileSync('outputs/iodd/engineering-rules.json','utf8'));
const pressure=models.find(m=>m.name==='ISE70'),flow=models.find(m=>m.name==='PF3W704-LT-X445');
const c=master.create();c.input=10;c.output=2;
for(const [n,m,length] of [[0,pressure,2],[1,flow,6]])Object.assign(c.ports[n],{enabled:true,mode:'manual',definition:m.sha256,layout:m.layouts.find(l=>l.condition[0]?.attributes.value==='0').id,input:length});
const options={now:1000,rules,diagnostics:{1:{V_diAG:1},2:{V_diAG:1}},units:{1:{V_Unit:0},2:{V_Unit:0}}};
const packet={connected:true,timestamp:1000,bytes:[0x0a,0x05,0x3e,0x80,0x02,0xee,0xff,0xce,0,0]};
let result=api.decode(c,models,packet,options);
assert.equal(result.ports[0].fields[0].raw,2000);assert.equal(result.ports[0].fields[0].engineering.value,.25);
assert.equal(result.ports[1].fields[0].engineering.value,3);assert.equal(result.ports[1].fields[1].engineering.value,-5);
assert.equal(result.ports[1].fields[1].value,-50);
const bad=(change,expected,port=0)=>{const p=structuredClone(packet);change(p);const r=api.decode(c,models,p,options);assert.equal(r.ports[port].quality,expected);assert(r.ports[port].fields.every(f=>f.value===null));};
bad(p=>p.connected=false,'disconnected');bad(p=>p.timestamp=-30001,'stale');bad(p=>p.timestamp=1001,'invalid_timestamp');bad(p=>p.bytes.pop(),'invalid_frame');bad(p=>p.bytes.push(0),'invalid_frame');bad(p=>p.bytes[0]=256,'invalid_frame');bad(p=>p.bytes[1]=4,'pd_invalid');bad(p=>p.bytes[0]=8,'device_disconnected');bad(p=>p.bytes[1]=7,'device_event');
const invalid=structuredClone(packet);invalid.bytes[1]=4;result=api.decode(c,models,invalid,options);assert.equal(result.ports[1].quality,'good');
// SMC PDF 142: complete 8-byte permutations and 7-byte data padded to 8 bytes.
const original=[1,0x23,0x45,0x67,0x89,0xab,0xcd,0xef];
assert.deepEqual(api.normalize([0x23,1,0x67,0x45,0xab,0x89,0xef,0xcd],'swap16'),original);
assert.deepEqual(api.normalize([0x67,0x45,0x23,1,0xef,0xcd,0xab,0x89],'swap32'),original);
assert.deepEqual(api.normalize([...original].reverse(),'swapAll'),original);
assert.deepEqual(api.normalize([0x67,0x45,0x23,1,0,0xcd,0xab,0x89],'swap32'),[1,0x23,0x45,0x67,0x89,0xab,0xcd,0]);
assert.deepEqual(api.normalize([1,2],'swap32'),[1,2]);assert.throws(()=>api.normalize([1,2,3],'swap16'));
const swapped=structuredClone(c);swapped.ports[0].swap='swap16';const pp=structuredClone(packet);[pp.bytes[2],pp.bytes[3]]=[pp.bytes[3],pp.bytes[2]];assert.equal(api.decode(swapped,models,pp,options).ports[0].fields[0].raw,2000);
const special=structuredClone(packet);special.bytes[2]=special.bytes[3]=0;assert.equal(api.decode(c,models,special,options).ports[0].fields[0].quality,'special');
const deviceError=structuredClone(packet);deviceError.bytes[3]|=4;let flagged=api.decode(c,models,deviceError,options);assert.equal(flagged.ports[0].fields[0].quality,'device_diagnostic');assert.equal(flagged.ports[0].fields[0].value,null);assert.equal(flagged.ports[0].fields[1].value,true);
const unreviewed=structuredClone(pressure);unreviewed.sha256='unreviewed';const unknownConfig=structuredClone(c);unknownConfig.ports[0].definition='unreviewed';assert.equal(api.decode(unknownConfig,[unreviewed,flow],packet,options).ports[0].fields[0].quality,'diagnostics_unverified');
assert.equal(api.decode(c,models,packet,{now:1000,rules,diagnostics:{1:{V_diAG:1},2:{V_diAG:1}}}).ports[0].fields[0].engineering.quality,'configuration_required');
assert.equal(api.scalar([255,255,255,255,255,255,255,255],{datatype:{type:'UIntegerT',bitLength:64},bitOffset:0}).quality,'precision_required');
assert.equal(api.scalar([0],{datatype:{type:'RecordT'},bitOffset:0}).quality,'unsupported');
// Exercise packet-lab delivery without a browser or transport.
class E{constructor(t){this.tagName=t;this.children=[];this.style={};this.dataset={};this.value='';}append(...c){this.children.push(...c);}replaceChildren(...c){this.children=c;}setAttribute(k,v){this[k]=v;}}
global.document={createElement:t=>new E(t)};global.IoddPdDecoder=api;
require('../assets/iodd-packet-lab.js');const host=new E('main');let delivered=null;
global.IoddPacketLab.mount(host,{getConfig:()=>structuredClone(c)},models,(p,config,result)=>{delivered=result;});
const nodes=e=>[e,...e.children.flatMap(nodes)];const textarea=nodes(host).find(e=>e.tagName==='textarea');textarea.value=packet.bytes.map(b=>b.toString(16).padStart(2,'0')).join(' ');
nodes(host).find(e=>e.tagName==='input'&&e.dataset?.diagnostic).checked=true;nodes(host).find(e=>e.textContent==='모의 패킷 해석').onclick();nodes(host).find(e=>e.tagName==='button'&&e.textContent.startsWith('P1 결과')).onclick();assert.equal(delivered.fields[0].raw,2000);
textarea.value='GG';nodes(host).find(e=>e.textContent==='모의 패킷 해석').onclick();assert(nodes(host).find(e=>e.tagName==='pre').textContent.startsWith('해석 실패'));
console.log('PASS: ISE70/PF3W byte fixtures, signed values, unit conversion, PQ/event/disconnect/stale, exact frame length, swaps, special/unsupported values');

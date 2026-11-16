'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),api=require('../assets/iodd-master-config.js');
const fixture=(sha,input,output)=>({sha256:sha,layouts:[{id:0,directions:[{source:'PD IN',bitLength:String(input*8)},{source:'PD OUT',bitLength:String(output*8)}]}]});
const models=[fixture('a',10,0),fixture('b',12,4)];
// Official EXW1-RL manual PDF p162, V2 mixed IOL / DO / DI / IOL.
const c=api.create();c.input=24;c.output=6;c.y1=c.y2=true;
Object.assign(c.ports[0],{enabled:true,mode:'manual',input:10,definition:'a',layout:0});
Object.assign(c.ports[1],{enabled:true,mode:'do'});Object.assign(c.ports[2],{enabled:true,mode:'di'});
Object.assign(c.ports[3],{enabled:true,mode:'autostart',input:12,output:4,definition:'b',layout:0});
let r=api.validate(c,models);assert.deepEqual(r.errors,[]);assert.equal(r.input,24);assert.equal(r.output,6);
assert.deepEqual(r.map.map(p=>[p.input_start,p.output_start]),[[2,null],[null,null],[null,null],[12,2]]);
assert.deepEqual(api.decode(api.encode(c,models),models),c);
const bad=mutate=>{const d=structuredClone(c);mutate(d);assert(api.validate(d,models).errors.length);assert.throws(()=>api.encode(d,models));};
bad(d=>d.input=23);bad(d=>d.ports[0].input=9);bad(d=>d.y2=false);bad(d=>d.model='EXW1-RLBPA7C');bad(d=>d.protocol='1.0');bad(d=>d.ports[0].layout=7);bad(d=>d.ports[0].definition='unknown');bad(d=>d.ports[1].input=1);bad(d=>d.ports[0].input=.5);bad(d=>d.channel=0);bad(d=>d.ports[0].id=2);
const v1=api.create();v1.protocol='1.0';v1.input=v1.output=16;assert.equal(api.validate(v1,models).errors.length,0);
const all=JSON.parse(fs.readFileSync('outputs/iodd/catalog.json','utf8')).models;
for(const m of all)for(const l of m.layouts){const plan=api.create();Object.assign(plan.ports[0],{enabled:true,mode:'manual',definition:m.sha256,layout:l.id});for(const [s,d] of [['PD IN','input'],['PD OUT','output']]){plan.ports[0][d]=Math.ceil(Number(l.directions.find(x=>x.source===s)?.bitLength||0)/8);plan[d]=2+plan.ports[0][d];}assert.equal(api.validate(plan,all).errors.length,0,m.name);}
// Persistence UI: restore validated saved values; reject malformed import without replacing state.
class E{constructor(t){this.tagName=t;this.children=[];this.value='';this.style={};}append(...e){this.children.push(...e);}replaceChildren(...e){this.children=e;}setAttribute(k,v){this[k]=v;}}
global.document={createElement:t=>new E(t)};global.IoddMasterConfig=api;
const store=new Map();global.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
require('../assets/iodd-master-editor.js');let host=new E('main'),editor=global.IoddMasterEditor.mount(host,models,()=>{});
const nodes=e=>[e,...e.children.flatMap(nodes)],button=(h,s)=>nodes(h).find(e=>e.tagName==='button'&&e.textContent===s);
button(host,'이 브라우저에 저장').onclick();assert.equal(store.size,1);
host=new E('main');editor=global.IoddMasterEditor.mount(host,models,()=>{});assert.deepEqual(editor.getConfig(),api.create());
nodes(host).find(e=>e.tagName==='textarea').value=JSON.stringify(c);button(host,'JSON 가져오기').onclick();assert.deepEqual(editor.getConfig(),c);
nodes(host).find(e=>e.tagName==='textarea').value='{}';button(host,'JSON 가져오기').onclick();assert.deepEqual(editor.getConfig(),c);
console.log('PASS: official mixed-port map, all 432 IODD layouts, limits, invalid-save rejection, JSON and local persistence');

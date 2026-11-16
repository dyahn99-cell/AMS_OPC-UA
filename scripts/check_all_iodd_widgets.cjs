'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.listeners={};this.value='';}
 append(...c){this.children.push(...c);}setAttribute(k,v){this[k]=v;}replaceChildren(...c){this.children=c;}addEventListener(k,v){this.listeners[k]=v;}remove(){};
}
global.document={createElement:t=>new Element(t),createElementNS:(ns,t)=>new Element(t)};
const widgets=require('../assets/iodd-widgets.js');
global.IoddEngineering=require('../assets/iodd-engineering.js');
const rules=JSON.parse(fs.readFileSync('outputs/iodd/engineering-rules.json','utf8'));
const catalog=JSON.parse(fs.readFileSync('outputs/iodd/catalog.json','utf8'));
let count=0,viewCount=0;const types=new Set();
for(const m of catalog.models)for(const item of m.items){
 const views=widgets.views(item);assert(views.length);types.add(item.widget);
 for(const view of views){const host=new Element('main');const instance=widgets.mount(host,{model:m.name,definition_key:m.sha256,item,view,engineeringRule:rules.find(r=>r.definition_key===m.sha256&&r.item_id===item.id)});assert.equal(host.children.length,1);const check=instance.element.children.flatMap(x=>x.children||[]).find(x=>x.type==='checkbox');if(check){check.checked=true;check.listeners.change();}instance.setSample(null);instance.setSample(widgets.sample(item));instance.setSample('not a number');viewCount++;}
 count++;
}
assert.equal(count,11217);assert(types.has('structure'));assert(types.has('status'));assert(types.has('text'));
assert.equal(widgets.interpret({widget:'status',datatype:{type:'BooleanT'}},'garbage').quality,'invalid');
assert.equal(widgets.interpret({widget:'status',datatype:{type:'BooleanT',choices:[{value:'true',label:'Disable'},{value:'false',label:'Enable'}]}},true).text,'Disable');
assert.equal(widgets.interpret({widget:'number',datatype:{type:'UIntegerT',bitLength:'8'}},256).quality,'invalid');
assert.equal(widgets.interpret({widget:'number',datatype:{type:'UIntegerT',bitLength:'8'}},-1).quality,'invalid');
assert.equal(widgets.interpret({widget:'number',datatype:{type:'IntegerT',bitLength:'16'}},2**54).quality,'unresolved');
// A vacuum sensor's negative coefficient must invert the gauge, not its limits.
const rule=rules.find(r=>r.model==='ZSE20C-L'&&r.unit==='kPa');
const model=catalog.models.find(m=>m.sha256===rule.definition_key),item=model.items.find(i=>i.id===rule.item_id);
const host=new Element('main'),mounted=widgets.mount(host,{model:model.name,definition_key:model.sha256,item,view:'gauge',sample:3000,engineeringRule:rule});
const descendants=e=>[e,...e.children.flatMap(descendants)];
const find=p=>descendants(mounted.element).find(p);
const check=find(e=>e.type==='checkbox');check.checked=true;check.listeners.change();
assert.equal(find(e=>e.className==='iw-value').textContent,'-50 kPa');
const progress=find(e=>e.tagName==='progress');assert(progress.value>=0&&progress.value<=100);
assert(find(e=>typeof e.textContent==='string'&&e.textContent.endsWith('kPa · 첫 정의 범위')));
check.checked=false;check.listeners.change();assert.equal(find(e=>e.className==='iw-value').textContent,'3000 raw');
const selector=find(e=>e.tagName==='select');selector.value='trend';selector.listeners.change();
const add=find(e=>e.textContent==='모의 샘플 추가');add.listeners.click();mounted.setSample(2000);add.listeners.click();
check.checked=true;check.listeners.change();
assert(find(e=>e.tagName==='svg')['aria-label'].includes('kPa'));
assert(find(e=>e.textContent==='모의 샘플 2개 · -50–-25 kPa · 수집 순서'));
console.log(`PASS: ${count} items, ${viewCount} widget mounts, missing/invalid samples, all catalog data types`);

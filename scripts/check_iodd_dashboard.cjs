'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const {compose}=require('../assets/iodd-device-dashboard.js');
const {views}=require('../assets/iodd-widgets.js');
const models=JSON.parse(fs.readFileSync('outputs/iodd/catalog.json','utf8')).models;
let compositions=0;
for(const model of models){
 const waiting=compose(model,'');
 assert.equal(waiting.layout,null);
 assert(waiting.groups.flatMap(g=>g.bindings).every(b=>b.source==='ACYCLIC'));
 const covered=new Set(waiting.groups.flatMap(g=>g.bindings).map(b=>b.index));
 for(const layout of model.layouts){
  const result=compose(model,layout.id),bindings=result.groups.flatMap(g=>g.bindings);
  const expected=model.items.filter(i=>i.source==='ACYCLIC'||String(i.layout)===String(layout.id));
  assert.equal(bindings.length,expected.length);
  assert.equal(new Set(bindings.map(b=>b.index)).size,bindings.length);
  for(const b of bindings){
   covered.add(b.index);const item=model.items[b.index];
   assert.equal(b.definition_key,model.sha256);assert.equal(b.item_id,item.id);
   assert.equal(b.write_enabled,false);assert(views(item).includes(b.view));
   if(b.source!=='ACYCLIC')assert.equal(String(b.layout),String(layout.id));
  }
  compositions++;
 }
 assert.equal(covered.size,model.items.length,model.name+' missing fields');
}
console.log(`PASS: ${models.length} devices, ${compositions} layout compositions, no omitted fields or mixed PD layouts`);

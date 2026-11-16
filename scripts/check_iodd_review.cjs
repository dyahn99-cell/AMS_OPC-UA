'use strict';
// Independently check inventory coverage and evidence integrity, without device I/O.
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const base='outputs/iodd/',catalog=read(base+'catalog.json'),review=read(base+'full-product-review.json');
const rules=read(base+'engineering-rules.json'),conflicts=read(base+'engineering-conflicts.json');
const models=new Map(catalog.models.map(m=>[m.sha256,m]));
assert.equal(review.definitions.length,models.size);
assert.equal(new Set(review.definitions.map(r=>r.definition_key)).size,models.size);
assert.equal(new Set(review.definitions.flatMap(r=>r.packages)).size,41);
for(const row of review.definitions){
 const model=models.get(row.definition_key);assert(model);
 assert.equal(row.fields.length,model.items.length);
 assert(row.manual_reviews.length);
 for(const evidence of row.manual_reviews){
  assert(evidence.url?.startsWith('https://'));assert(evidence.pages.length);
 }
 assert.equal(row.hardware_verified,false);assert.equal(row.manual_review_complete,false);
}
const docs=new Map(read(base+'manuals/download-manifest.json').map(d=>[d.file,d]));
for(const doc of docs.values()){
 assert.equal(doc.sha256,crypto.createHash('sha256').update(fs.readFileSync(base+'manuals/'+doc.file)).digest('hex'));
}
for(const r of rules){
 const model=models.get(r.definition_key),item=model.items.find(i=>i.id===r.item_id);assert(item);
 assert.equal(item.source,r.index===undefined?'PD IN':'ACYCLIC');
 assert(r.iodd_presentation_evidence.length);
 assert(!conflicts.some(c=>c.definition_key===r.definition_key&&c.item_id===r.item_id));
 const doc=docs.get(r.evidence.document);
 if(doc){assert.equal(r.evidence.sha256,doc.sha256);for(const p of r.evidence.pdf_pages)assert(p>0&&p<=doc.pages);}
 else assert.equal(r.evidence.url,'https://www.smcworld.com/upfiles/_manual/e/PSxx-PSV0007.pdf');
}
console.log(`PASS: ${models.size} definitions / 41 packages, ${rules.length} exact-field rules, ${docs.size} PDF hashes, no conflict rules`);

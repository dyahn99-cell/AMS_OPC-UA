const assert=require('node:assert/strict'),fs=require('node:fs'),{convert}=require('../assets/iodd-engineering.js');const rules=JSON.parse(fs.readFileSync('outputs/iodd/engineering-rules.json','utf8'));
const p=rules.find(r=>r.model==='ISE70'&&r.unit==='MPa');assert.equal(convert(p,2000,{V_Unit:0}).value,.25);assert.equal(convert(p,4000,{V_Unit:0}).value,.75);assert.equal(convert(p,1000,{V_Unit:0}).value,0);assert.equal(convert(p,0,{V_Unit:0}).quality,'special');assert.equal(convert(p,5201,{V_Unit:0}).quality,'out_of_range');assert.equal(convert(p,2000,{}).quality,'configuration_required');assert.equal(convert(p,2000,{V_Unit:3}).quality,'configuration_required');assert.equal(convert(p,null,{V_Unit:0}).quality,'invalid');
const f=rules.find(r=>r.unit==='L/min');assert.equal(convert(f,750,{V_Unit:0}).value,3);const t=rules.find(r=>r.unit==='°C'&&r.unit_code==='0');assert.equal(convert(t,-50,{V_Unit:0}).value,-5);assert.equal(convert(t,450,{V_Unit:0}).value,45);
for(const r of rules){assert.equal(convert(r,r.raw_min,{V_Unit:r.unit_code}).quality,'good');assert.equal(convert(r,r.raw_max,{V_Unit:r.unit_code}).quality,'good');}
const fixtures=[
 ['ISE71','MPa',2000,.4],['ISE79S','MPa',2000,12.5],
 ['ZSE20C-L','kPa',3000,-50],['ZSE20CF-L','kPa',3000,0],
 ['PF2M725x-xx-Lx-xxx','L/min',3000,18.75],
 ['PF3A703H-xx-Lx-xxx','L/min',2800,2100],
 ['PF3A701H-xx-Lx-xxx','L/min',2800,700],
 ['PF3W720x-xx-LxT-xxx','L/min',500,8],
 ['PFUW760-L1x-xx','L/min',500,7.5],
 ['PFCA710-xx-1x-xxx','L/min',500,1.25],
 ['PFCA710-xx-1x-xxx','L',100,10],['PSH-LL','%R.H.',100,10]
];
for(const [model,unit,raw,expected] of fixtures){const r=rules.find(r=>r.model===model&&r.unit===unit);assert(r,model+' '+unit);assert.equal(convert(r,raw,{V_Unit:r.unit_code}).value,expected);}
const peak=rules.find(r=>r.model==='ISE20B-L'&&r.index===2002);assert(peak);assert.equal(peak.bit_offset,null);assert.equal(convert(peak,2000,{V_Unit:0}).value,.25);
const conflicts=JSON.parse(fs.readFileSync('outputs/iodd/engineering-conflicts.json','utf8'));
assert.equal(conflicts.length,4);
for(const c of conflicts)assert(!rules.some(r=>r.definition_key===c.definition_key&&r.item_id===c.item_id));
assert(!rules.some(r=>r.model==='PSH-L2'&&r.device_id==='650'));
assert(!rules.some(r=>r.model.includes('X731')));
assert(!rules.some(r=>r.model.startsWith('PF2MC')));
assert.equal(new Set(rules.map(r=>r.definition_key+'|'+r.item_id)).size,rules.length);
console.log('PASS: manual examples, unit mismatch, missing config, special code, signed temperature, all rule boundaries');

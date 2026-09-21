const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../dashboard.html'),'utf8');
function section(begin,end){const a=source.indexOf(begin),b=source.indexOf(end,a+begin.length);assert(a>=0&&b>a);return source.slice(a,b);}
const select={value:'AMS01',innerHTML:''};
const c={document:{getElementById:()=>select},viewScope:'overview',selectedRemoteId:'COMBINED',escapeHtml:String};
vm.createContext(c);
vm.runInContext(section('function syncScheduleTargets(', 'function syncHistDeviceSelect('),c);
c.syncScheduleTargets([]);assert.equal(select.value,'AMS01');assert.match(select.innerHTML,/Unavailable/);
c.syncScheduleTargets([{device_id:'AMS01',name:'one'}]);assert.equal(select.value,'AMS01');
vm.runInContext(section('function scheduleState(', 'function editSchedule('),c);
assert.equal(c.scheduleState({run:{state:'COMPLETED'}}),'done');
assert.equal(c.scheduleState({run:{state:'RESTORING'}}),'running');
vm.runInContext(section('function isApiOk(', '// ?'),c);
assert.equal(c.isApiOk({ok:true,run:{last_result:{ok:false}},result:{ok:true}}),true);
assert.equal(c.isApiOk({ok:true,result:{ok:false}}),false);
vm.runInContext(section('function energyInputNumber(', 'async function saveEnergy'),c);
select.value='0';assert.equal(c.energyInputNumber('x',170),0);
select.value='';assert.equal(c.energyInputNumber('x',170),170);
console.log('PASS: selected schedule target survives disconnect; schedule states; current versus historical results; zero settings');

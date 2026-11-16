/* Input: one master's ordered byte image, not Modbus registers. Pure/read-only. */
(function(g){
'use strict';
const master=typeof module!=='undefined'?require('./iodd-master-config.js'):g.IoddMasterConfig;
const widgets=typeof module!=='undefined'?require('./iodd-widgets.js'):g.IoddWidgets;
const engineering=typeof module!=='undefined'?require('./iodd-engineering.js'):g.IoddEngineering;
const diagnostics=typeof module!=='undefined'?require('./iodd-diagnostic-profiles.js'):g.IoddDiagnosticProfiles;
function normalize(bytes,mode){
 const a=Array.from(bytes);
 if(mode==='direct')return a;
 if(mode==='swapAll')return a.reverse();
 const size=mode==='swap16'?2:mode==='swap32'?4:0;
 if(mode==='swap32'&&a.length===2)return a; // EXW1-RL PDF p142 footnote.
 if(!size||a.length%size)throw Error('swap_mapping_alignment');
 return a.flatMap((_,i)=>i%size?[]:a.slice(i,i+size).reverse());
}
function scalar(bytes,item){
 const type=item.datatype.type,bits=type==='BooleanT'?1:Number(item.datatype.bitLength),offset=Number(item.bitOffset);
 if(!['BooleanT','IntegerT','UIntegerT'].includes(type))return {quality:'unsupported',value:null};
 if(item.bitOffset===undefined||!Number.isInteger(bits)||bits<1||!Number.isInteger(offset)||offset<0||offset+bits>bytes.length*8)return {quality:'invalid_definition',value:null};
 let word=0n;for(const b of bytes)word=(word<<8n)|BigInt(b);
 let raw=(word>>BigInt(offset))&((1n<<BigInt(bits))-1n);
 if(type==='IntegerT'&&(raw&(1n<<BigInt(bits-1))))raw-=1n<<BigInt(bits);
 if(type==='BooleanT')return {quality:'good',value:raw!==0n};
 if(raw>BigInt(Number.MAX_SAFE_INTEGER)||raw<BigInt(Number.MIN_SAFE_INTEGER))return {quality:'precision_required',value:null,raw_text:String(raw)};
 const value=Number(raw),check=widgets.interpret(item,value);
 return {quality:check.quality,value:check.quality==='good'?value:null,raw:value,label:check.text};
}
function decode(config,models,packet,options={}){
 const validation=master.validate(config,models);
 if(validation.errors.length)return {quality:'configuration_invalid',errors:validation.errors,ports:[]};
 const now=options.now??Date.now(),maxAge=options.maxAge??30000;
 let quality='good';
 if(!packet||packet.connected!==true)quality='disconnected';
 else if(!Number.isFinite(packet.timestamp)||!Number.isFinite(now)||!Number.isFinite(maxAge)||maxAge<0||packet.timestamp>now)quality='invalid_timestamp';
 else if(now-packet.timestamp>maxAge)quality='stale';
 else if(!Array.isArray(packet.bytes)||packet.bytes.length!==config.input||!packet.bytes.every(v=>Number.isInteger(v)&&v>=0&&v<=255))quality='invalid_frame';
 const result={quality,timestamp:packet?.timestamp??null,source:'byte_image',ports:[]};
 for(const p of config.ports){
  const row=validation.map.find(r=>r.port===p.id),model=models.find(m=>m.sha256===p.definition);
  const items=model?.items.filter(i=>i.source==='PD IN'&&i.layout===p.layout)||[];
  const out={port:p.id,definition:p.definition,layout:p.layout,quality,device_event:null,fields:[]};result.ports.push(out);
  if(!p.enabled)out.quality='disabled';
  else if(!['manual','autostart'].includes(p.mode))out.quality='digital_mode';
  else if(quality==='good'){
   const bit=2*(p.id-1),connected=!!(packet.bytes[0]&(1<<(bit+1))),valid=!!(packet.bytes[1]&(1<<bit));
   out.device_event=!!(packet.bytes[1]&(1<<(bit+1)));
   out.quality=!connected?'device_disconnected':!valid?'pd_invalid':out.device_event?'device_event':'good';
  }
  let data=null;
  if(out.quality==='good'||(options.diagnosticPreview===true&&out.quality==='device_event'))try{
   const layout=model.layouts.find(l=>l.id===p.layout),direction=layout.directions.find(d=>d.source==='PD IN');
   const length=direction?Math.ceil(Number(direction.bitLength)/8):0;
   data=normalize(row.input_bytes?packet.bytes.slice(row.input_start,row.input_start+row.input_bytes):[],p.swap);
   if(data.slice(length).some(b=>b!==0))throw Error('nonzero_padding');
   data=data.slice(0,length);
  }catch(e){out.quality='mapping_unconfirmed';out.reason=e.message;}
  const profile=diagnostics[p.definition],checks=profile?.bits;out.diagnostic_profile=checks?'reviewed':'unverified';
  const diagnosticConfig=!!profile&&Object.entries(profile.required_configuration).every(([key,value])=>String(options.diagnostics?.[p.id]?.[key])===value);
  let diagnosticActive=false,word=0n;
  if(data&&checks){for(const b of data)word=(word<<8n)|BigInt(b);diagnosticActive=checks.some(bit=>!!(word&(1n<<BigInt(bit))));}
  for(const item of items){
   const field={item_id:item.id,name:item.name,source:'PD IN',...(out.quality==='good'?scalar(data,item):{quality:out.quality,value:null})};
   if(options.diagnosticPreview===true&&data&&['good','device_event'].includes(out.quality)){
    const raw=scalar(data,item);
    if(typeof raw.raw==='number'||typeof raw.value==='boolean')field.preview={value:raw.raw??raw.value,quality:'test_raw',interpretation:raw.quality,label:raw.label??null};
   }
   const gate=profile?.field_checks?.[item.id];
   const verified=!!checks&&(!profile.field_checks||!!gate);
   const blocked=gate?(gate.zero_bits.some(bit=>!!(word&(1n<<BigInt(bit))))||gate.one_bits.some(bit=>!(word&(1n<<BigInt(bit))))):diagnosticActive;
   if(field.quality==='good'&&typeof field.value==='number'&&(!verified||!diagnosticConfig||blocked)){field.quality=!verified?'diagnostics_unverified':!diagnosticConfig?'diagnostic_configuration_required':'device_diagnostic';field.value=null;}
   if(field.quality==='good'&&typeof field.value==='number'&&options.conditionOK===false){field.quality='layout_condition_unconfirmed';field.value=null;}
   const candidates=(model.engineering_rules||options.rules||[]).filter(r=>r.definition_key===model.sha256&&r.item_id===item.id);
   const rule=candidates.find(r=>String(r.unit_code)===String(options.units?.[p.id]?.V_Unit))||candidates[0];
   if(rule&&field.quality==='good'&&typeof field.value==='number')field.engineering={...engineering.convert(rule,field.value,options.units?.[p.id]),scale:rule.scale,offset:rule.offset};
   out.fields.push(field);
  }
 }
 return result;
}
const api={decode,normalize,scalar};if(typeof module!=='undefined')module.exports=api;else g.IoddPdDecoder=api;
})(globalThis);

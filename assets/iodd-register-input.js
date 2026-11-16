/* Injected read-only reader. No discovery, sockets, timers or write operations. */
(function(g){
'use strict';
const configApi=typeof module!=='undefined'?require('./iodd-master-config.js'):g.IoddMasterConfig;
const decoder=typeof module!=='undefined'?require('./iodd-pd-decoder.js'):g.IoddPdDecoder;
function requestFor(config,models,mapping){
 const check=configApi.validate(config,models);if(check.errors.length)throw Error('invalid_configuration');
 if(!mapping||mapping.confirmed!==true||mapping.base!==config.base||mapping.channel!==config.channel)throw Error('mapping_confirmation_required');
 if(![3,4].includes(mapping.functionCode)||!['high-low','low-high'].includes(mapping.wordByteOrder)||![0,1].includes(mapping.byteOffset))throw Error('invalid_read_mapping');
 const count=Math.ceil((config.input+mapping.byteOffset)/2);
 if(!Number.isInteger(mapping.address)||mapping.address<0||mapping.address+count>65536||count>125)throw Error('invalid_register_range');
 return {base:config.base,channel:config.channel,functionCode:mapping.functionCode,address:mapping.address,count};
}
function packetFor(config,request,mapping,response){
 if(!response||!['base','channel','functionCode','address'].every(k=>response[k]===request[k]))throw Error('response_identity_mismatch');
 if(response.connected!==true)return {connected:false,timestamp:response.timestamp,bytes:[]};
 if(!Array.isArray(response.words)||response.words.length!==request.count||!response.words.every(w=>Number.isInteger(w)&&w>=0&&w<=65535))throw Error('invalid_register_response');
 const bytes=response.words.flatMap(w=>mapping.wordByteOrder==='high-low'?[w>>>8,w&255]:[w&255,w>>>8]);
 return {connected:true,timestamp:response.timestamp,bytes:bytes.slice(mapping.byteOffset,mapping.byteOffset+config.input)};
}
async function read(config,models,mapping,reader,options={}){
 // Snapshot before awaiting: edits during a read cannot redirect its response.
 const frozenConfig=JSON.parse(JSON.stringify(config)),frozenMapping={...mapping};
 const request=requestFor(frozenConfig,models,frozenMapping);
 try{
  const response=await reader(Object.freeze({...request}));
  const packet=packetFor(frozenConfig,request,frozenMapping,response);
  return {request,packet,decoded:decoder.decode(frozenConfig,models,packet,options)};
 }catch(error){return {request,error:String(error.message||error),packet:{connected:false,timestamp:null,bytes:[]},decoded:decoder.decode(frozenConfig,models,null,options)};}
}
const api={requestFor,packetFor,read};if(typeof module!=='undefined')module.exports=api;else g.IoddRegisterInput=api;
})(globalThis);

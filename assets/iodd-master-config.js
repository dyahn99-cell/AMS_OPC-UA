/* Offline EXW1-RL plan, never a live device configuration or register map. */
(function(global){
'use strict';
const types={'EXW1-RLAPA8C':{ports:4,max:130},'EXW1-RLBPA7C':{ports:2,max:66}};
function create(){return {schema:1,base:'EXW1-01',channel:1,model:'EXW1-RLAPA8C',protocol:'2.0',input:2,output:2,y1:false,y2:false,ports:Array.from({length:4},(_,i)=>({id:i+1,enabled:false,mode:'deactivated',input:0,output:0,swap:'direct',definition:null,layout:null,alias:''}))};}
const integer=(x,a,b)=>Number.isInteger(x)&&x>=a&&x<=b;
function validate(c,models){
 const errors=[],warnings=[],map=[];let input=2,output=2;
 if(!c||c.schema!==1||!Array.isArray(c.ports)){return {errors:['지원하지 않는 구성 형식'],warnings,map,input,output};}
 const type=types[c.model];
 if(!type)errors.push('마스터 모델을 선택하세요');
 if(typeof c.y1!=='boolean'||typeof c.y2!=='boolean')errors.push('분기 배선 확인 값 오류');
 if(!['1.0','2.0'].includes(c.protocol))errors.push('무선 프로토콜을 선택하세요');
 if(typeof c.base!=='string'||!c.base.trim()||c.base.length>100)errors.push('베이스 식별자가 필요합니다');
 if(!integer(c.channel,1,15))errors.push('채널은 1–15 정수입니다');
 const limit=c.protocol==='1.0'?14:32;
 for(const dir of ['input','output'])if(c.protocol==='1.0'?c[dir]!==16:!integer(c[dir],2,type?.max||130))errors.push(dir+' 전체 바이트 범위 오류');
 if(c.ports.length!==4)errors.push('P1–P4 정의가 필요합니다');
 c.ports.forEach((p,i)=>{
  if(!p||p.id!==i+1){errors.push('포트 식별자 오류');return;}
  const name='P'+p.id;
  if(typeof p.enabled!=='boolean'||typeof p.alias!=='string'||p.alias.length>100)errors.push(name+' 사용 여부/별칭 오류');
  if(!['deactivated','manual','autostart','di','do'].includes(p.mode))errors.push(name+' 모드 오류');
  if(!['direct','swap16','swap32','swapAll'].includes(p.swap))errors.push(name+' 바이트 순서 오류');
  if(!integer(p.input,0,limit)||!integer(p.output,0,limit))errors.push(name+' 포트 바이트는 0–'+limit+' 정수입니다');
  if(p.enabled&&p.id>(type?.ports||0))errors.push(name+'은 이 모델에서 지원하지 않습니다');
  if(p.enabled&&p.id>=3&&!(p.id===3?c.y1:c.y2))errors.push(name+' 사용 시 PORT'+(p.id===3?1:2)+' 분기 배선을 확인하세요');
  const io=p.enabled&&['manual','autostart'].includes(p.mode);
  if(p.enabled&&p.mode==='deactivated')errors.push(name+' 사용 포트의 모드를 선택하세요');
  if(!io&&(p.input!==0||p.output!==0))errors.push(name+' 비활성/DI/DO 포트의 할당 바이트는 0이어야 합니다');
  const row={port:p.id,input_start:io&&p.input?input:null,output_start:io&&p.output?output:null,input_bytes:io?p.input:0,output_bytes:io?p.output:0};
  if(io){
   const model=models.find(m=>m.sha256===p.definition),layout=model?.layouts.find(l=>l.id===p.layout);
   if(!model||!layout)errors.push(name+' 제품 버전과 PD 레이아웃을 선택하세요');
   if(layout)for(const [source,dir] of [['PD IN','input'],['PD OUT','output']]){
    const direction=layout.directions.find(d=>d.source===source),bits=direction?Number(direction.bitLength):0;
    if(!Number.isInteger(bits)||bits<0)errors.push(name+' '+source+' 길이 확인 필요');
    else{const required=Math.ceil(bits/8);if(p[dir]<required)errors.push(name+' '+source+' 최소 '+required+'바이트 필요');else if(p[dir]>required)warnings.push(name+' '+source+' 여유 '+(p[dir]-required)+'바이트: 실장비 할당 확인');}
   }
   if(p.swap!=='direct')warnings.push(name+' 바이트 교환은 저장만 합니다. 디코더 미연결');
   input+=Number.isInteger(p.input)?p.input:0;output+=Number.isInteger(p.output)?p.output:0;
  }
  map.push(row);
 });
 if(input>c.input)errors.push('입력 할당 합계 '+input+' > 전체 '+c.input);
 if(output>c.output)errors.push('출력 할당 합계 '+output+' > 전체 '+c.output);
 return {errors,warnings,map,input,output};
}
function encode(config,models){const result=validate(config,models);if(result.errors.length)throw Error(result.errors.join('\n'));return JSON.stringify(config);}
function decode(text,models){const c=JSON.parse(text);encode(c,models);return c;}
const api={create,validate,encode,decode,types};if(typeof module!=='undefined')module.exports=api;else global.IoddMasterConfig=api;
})(globalThis);

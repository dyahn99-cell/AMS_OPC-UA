/* Reviewed engineering conversion only. Callers supply explicit manual unit configuration. */
(function(g){
function convert(rule,raw,config){
 if(!rule||!config||String(config.V_Unit)!==String(rule.unit_code))return {quality:'configuration_required'};
 if(typeof raw!=='number'||!Number.isSafeInteger(raw))return {quality:'invalid'};
 if(rule.special_values.includes(raw))return {quality:'special',raw};
 if(raw<rule.raw_min||raw>rule.raw_max)return {quality:'out_of_range',raw};
 return {quality:'good',raw,value:Number((raw*rule.scale+rule.offset).toPrecision(12)),unit:rule.unit};
}
const api={convert};if(typeof module!=='undefined')module.exports=api;else g.IoddEngineering=api;
})(globalThis);

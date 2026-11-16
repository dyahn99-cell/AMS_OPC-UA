'use strict';
const fs=require('node:fs'),{compose}=require('../../assets/iodd-device-dashboard.js');
const models=JSON.parse(fs.readFileSync('outputs/iodd/catalog.json','utf8')).models;
const definitions=models.map(m=>({definition_key:m.sha256,model:m.name,
 selection:'explicit_revision_and_layout',initial_value:null,
 waiting:compose(m,''),layouts:m.layouts.map(l=>compose(m,l.id))}));
fs.writeFileSync('outputs/iodd/device-dashboards.json',JSON.stringify({schema_version:1,
 scope:'structural composition; parameter semantics and hardware validity require further review',definitions},null,2));
console.log('Built '+definitions.length+' device dashboard definitions');

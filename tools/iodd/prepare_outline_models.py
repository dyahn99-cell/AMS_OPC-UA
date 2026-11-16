"""Uniform geometric ink for supplied CAD; keep original assembly and surfaces."""
import hashlib,json,struct
from prepare_product_models import DIRECTORY,PARTS,read_glb,accessor_values
from outline_geometry import PAPER,INK,SILHOUETTE,SHELL_RATIO,EDGE_RATIO,silhouette,tubes

def prepare_outline(part):
 raw,doc,original=read_glb(DIRECTORY/(part+'.glb'));binary=bytearray(original)
 def access(values,typ,target):
  while len(binary)%4:binary.append(0)
  component=5126 if typ=='VEC3' else 5125;offset=len(binary);binary.extend(struct.pack('<'+('f' if component==5126 else 'I')*len(values),*values))
  view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(binary)-offset,'target':target})
  a={'bufferView':view,'componentType':component,'count':len(values)//(3 if typ=='VEC3' else 1),'type':typ}
  if typ=='VEC3':a['min']=[min(values[i::3]) for i in range(3)];a['max']=[max(values[i::3]) for i in range(3)]
  doc['accessors'].append(a);return len(doc['accessors'])-1
 white=len(doc['materials']);ink=white+1;shell=white+2
 doc.setdefault('extensionsUsed',[])
 if 'KHR_materials_unlit' not in doc['extensionsUsed']:doc['extensionsUsed'].append('KHR_materials_unlit')
 for name,color,double in [('paper-surface',PAPER,True),('cad-edge-ink',INK,True),('silhouette-ink',SILHOUETTE,False)]:doc['materials'].append({'name':name,'doubleSided':double,'extensions':{'KHR_materials_unlit':{}},'pbrMetallicRoughness':{'baseColorFactor':color,'metallicFactor':0,'roughnessFactor':1}})
 extent=max(max(max(v[j] for v in accessor_values(doc,original,p['attributes']['POSITION']))-min(v[j] for v in accessor_values(doc,original,p['attributes']['POSITION'])) for j in range(3)) for m in doc['meshes'] for p in m['primitives'] if p.get('mode',4)==4)
 edges=0
 for mesh in doc['meshes']:
  prims=[];segments=[]
  for p in mesh['primitives']:
   coords=accessor_values(doc,original,p['attributes']['POSITION']);indices=[v[0] for v in accessor_values(doc,original,p['indices'])] if 'indices' in p else list(range(len(coords)))
   if p.get('mode',4)==1:
    if p.get('extras',{}).get('drawType')=='silhuette':continue
    segments.extend((coords[indices[i]],coords[indices[i+1]]) for i in range(0,len(indices),2));continue
   if p.get('mode',4)!=4:continue
   expanded,reverse=silhouette([x for v in coords for x in v],indices,extent*SHELL_RATIO)
   prims.append({'attributes':{'POSITION':access(expanded,'VEC3',34962)},'indices':access(reverse,'SCALAR',34963),'material':shell})
   p['material']=white;p['attributes'].pop('COLOR_0',None);prims.append(p)
  positions,indices=tubes(segments,extent*EDGE_RATIO)
  if positions:prims.append({'attributes':{'POSITION':access(positions,'VEC3',34962)},'indices':access(indices,'SCALAR',34963),'material':ink});edges+=len(indices)//36
  mesh['primitives']=prims
 doc['buffers'][0]['byteLength']=len(binary)
 doc.setdefault('asset',{}).setdefault('extras',{})['outlinePreparation']='Shared relative line weights; original CAD surfaces, feature edge paths and assembly transforms; silhouette shell and antialiased geometric ink.'
 encoded=json.dumps(doc,separators=(',',':')).encode();encoded+=b' '*(-len(encoded)%4)
 result=struct.pack('<4sII',b'glTF',2,28+len(encoded)+len(binary))+struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary
 (DIRECTORY/(part+'.outline.glb')).write_bytes(result)
 return {'part':part,'original_sha256':hashlib.sha256(raw).hexdigest(),'outline_sha256':hashlib.sha256(result).hexdigest(),'geometric_edge_segments':edges,'shell_ratio':SHELL_RATIO,'edge_ratio':EDGE_RATIO}
if __name__=='__main__':
 entries=[prepare_outline(part) for part in PARTS];(DIRECTORY/'outline-manifest.json').write_text(json.dumps(entries,indent=2),encoding='utf8');print(json.dumps(entries,indent=2))

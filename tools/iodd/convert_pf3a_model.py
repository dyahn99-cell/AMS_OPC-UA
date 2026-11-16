"""Render real CAD tessellation with continuous silhouettes and fine feature edges."""
import json, struct, math, hashlib
from pathlib import Path
from outline_geometry import PAPER, INK, SILHOUETTE, SHELL_RATIO, EDGE_RATIO
root = Path(__file__).resolve().parents[2]
meshes = json.loads((root/'tmp/cad-converter/mesh.json').read_text())['meshes']
doc = {'asset': {'version': '2.0', 'generator': 'OCCT CAD; geometric ink edges and silhouette shell'}, 'scene': 0, 'scenes': [{'nodes': []}], 'nodes': [], 'meshes': [], 'materials': [], 'buffers': [{'byteLength': 0}], 'bufferViews': [], 'accessors': [], 'extensionsUsed': ['KHR_materials_unlit']}
extent = max(max(m['attributes']['position']['array'][j::3])-min(m['attributes']['position']['array'][j::3]) for m in meshes for j in range(3))
shell_width = extent*SHELL_RATIO
edge_width = extent*EDGE_RATIO
binary = bytearray()
def access(values, typ, component, target):
 while len(binary)%4: binary.append(0)
 offset = len(binary)
 binary.extend(struct.pack('<'+('f' if component==5126 else 'I')*len(values), *values))
 view = len(doc['bufferViews'])
 doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(binary)-offset,'target':target})
 a = {'bufferView':view,'componentType':component,'count':len(values)//(3 if typ=='VEC3' else 1),'type':typ}
 if typ=='VEC3':
  a['min']=[min(values[i::3]) for i in range(3)]; a['max']=[max(values[i::3]) for i in range(3)]
 doc['accessors'].append(a)
 return len(doc['accessors'])-1
for name,color,double in [('Paper surface',PAPER,True),('Fine ink',INK,True),('Silhouette ink',SILHOUETTE,False)]:
 doc['materials'].append({'name':name,'doubleSided':double,'extensions':{'KHR_materials_unlit':{}},'pbrMetallicRoughness':{'baseColorFactor':color,'metallicFactor':0,'roughnessFactor':1}})
def unit(v):
 n=math.sqrt(sum(x*x for x in v)); return [x/n for x in v] if n else [0,0,0]
def cross(a,b): return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def key(v): return tuple(round(x,7) for x in v)
edges_count=0
for m in meshes:
 positions=m['attributes']['position']['array']; indices=m['index']['array']; vertices=[positions[i:i+3] for i in range(0,len(positions),3)]
 edges={}; normals={}
 for i in range(0,len(indices),3):
  tri=indices[i:i+3]; a,b,c=[vertices[j] for j in tri]
  normal=unit(cross([b[j]-a[j] for j in range(3)],[c[j]-a[j] for j in range(3)]))
  for j in tri:
   normals.setdefault(key(vertices[j]),set()).add(tuple(round(n,5) for n in normal))
  for x,y in [(tri[0],tri[1]),(tri[1],tri[2]),(tri[2],tri[0])]:
   edges.setdefault(tuple(sorted((key(vertices[x]),key(vertices[y])))),[]).append(normal)
 # A reversed, expanded shell draws the visible silhouette, including curved faces.
 # It stays behind the original opaque surface, so hidden edges remain hidden.
 expanded=[]
 for v in vertices:
  ns=normals[key(v)]; n=unit([sum(x[j] for x in ns) for j in range(3)])
  expanded.extend(v[j]+n[j]*shell_width for j in range(3))
 reverse=[k for i in range(0,len(indices),3) for k in (indices[i],indices[i+2],indices[i+1])]
 primitives=[{'attributes':{'POSITION':access(expanded,'VEC3',5126,34962)},'indices':access(reverse,'SCALAR',5125,34963),'material':2}, {'attributes':{'POSITION':access(positions,'VEC3',5126,34962)},'indices':access(indices,'SCALAR',5125,34963),'material':0}]
 # Thin polygonal tubes eliminate coplanar GL_LINES depth flicker and support AA.
 ink=[]; ink_ix=[]
 for (a,b),ns in edges.items():
  if not (len(ns)==1 or any(sum(x*y for x,y in zip(ns[0],n))<.8 for n in ns[1:])): continue
  direction=unit([b[j]-a[j] for j in range(3)])
  if direction==[0,0,0]: continue
  u=unit(cross(direction,[0,0,1] if abs(direction[2])<.9 else [0,1,0])); v=cross(direction,u)
  start=len(ink)//3; sides=6
  for p in (a,b):
   for k in range(sides):
    t=2*math.pi*k/sides
    ink.extend(p[j]+edge_width*(math.cos(t)*u[j]+math.sin(t)*v[j]) for j in range(3))
  for k in range(sides):
   q=(k+1)%sides
   ink_ix.extend([start+k,start+q,start+sides+k,start+q,start+sides+q,start+sides+k])
  edges_count+=1
 if ink: primitives.append({'attributes':{'POSITION':access(ink,'VEC3',5126,34962)},'indices':access(ink_ix,'SCALAR',5125,34963),'material':1})
 doc['meshes'].append({'name':m.get('name','CAD'),'primitives':primitives})
 doc['scenes'][0]['nodes'].append(len(doc['nodes'])); doc['nodes'].append({'mesh':len(doc['meshes'])-1})
def save(name):
 doc['buffers'][0]['byteLength']=len(binary)
 data=json.dumps(doc,separators=(',',':')).encode(); data+=b' '*(-len(data)%4)
 raw=struct.pack('<4sII',b'glTF',2,28+len(data)+len(binary))+struct.pack('<II',len(data),0x4e4f534a)+data+struct.pack('<II',len(binary),0x004e4942)+binary
 (root/'assets/product-models'/name).write_bytes(raw)
save('PF3A701H-L30.outline.glb'); save('PF3A701H-L30.display.glb')
(root/'assets/product-models/PF3A701H-L30-manifest.json').write_text(json.dumps({'source':'SMC_JP_PF3A701HL30.zip / PF3A701H-L3(0).stp','source_sha256':hashlib.sha256((root/'tmp/cad-converter/PF3A701H-L30.stp').read_bytes()).hexdigest(),'unit':'meter','triangles':sum(len(m['index']['array'])//3 for m in meshes),'derived_feature_edges':edges_count,'representative_family':'PF3A701H-xx-L3x-xxx','line_rendering':{'silhouette_shell_m':shell_width,'feature_radius_m':edge_width,'hidden_edges':'opaque CAD surface occlusion'},'note':'CAD-derived shape, no invented physical colour or port coordinates'},indent=2),encoding='utf8')
print('GLB created',edges_count)



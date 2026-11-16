"""Shared CAD ink geometry. Ratios are relative to product extent, not CAD units."""
import math
PAPER=[.975,.98,.985,1]
INK=[.004,.01,.02,1]
SILHOUETTE=[.002,.006,.014,1]
SHELL_RATIO=.0040
EDGE_RATIO=.0024
def unit(v):
 n=math.sqrt(sum(x*x for x in v));return [x/n for x in v] if n else [0,0,0]
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def silhouette(positions,indices,width):
 vertices=[positions[i:i+3] for i in range(0,len(positions),3)];normals={}
 def key(v):return tuple(round(x/width,4) for x in v)
 for i in range(0,len(indices),3):
  tri=indices[i:i+3];a,b,c=[vertices[j] for j in tri];n=unit(cross([b[j]-a[j] for j in range(3)],[c[j]-a[j] for j in range(3)]))
  for j in tri:normals.setdefault(key(vertices[j]),set()).add(tuple(round(x,5) for x in n))
 expanded=[]
 for v in vertices:
  ns=normals.get(key(v),{(0,0,0)});n=unit([sum(x[j] for x in ns) for j in range(3)])
  expanded.extend(v[j]+n[j]*width for j in range(3))
 reverse=[k for i in range(0,len(indices),3) for k in (indices[i],indices[i+2],indices[i+1])]
 return expanded,reverse
def tubes(segments,radius):
 positions=[];indices=[];seen=set()
 for a,b in segments:
  key=tuple(sorted(tuple(round(x/radius,3) for x in p) for p in (a,b)))
  if key in seen:continue
  seen.add(key);direction=unit([b[j]-a[j] for j in range(3)])
  if direction==[0,0,0]:continue
  u=unit(cross(direction,[0,0,1] if abs(direction[2])<.9 else [0,1,0]));v=cross(direction,u);start=len(positions)//3;sides=6
  for p in (a,b):
   for k in range(sides):
    t=2*math.pi*k/sides;positions.extend(p[j]+radius*(math.cos(t)*u[j]+math.sin(t)*v[j]) for j in range(3))
  for k in range(sides):
   q=(k+1)%sides;indices.extend([start+k,start+q,start+sides+k,start+q,start+sides+q,start+sides+k])
 return positions,indices

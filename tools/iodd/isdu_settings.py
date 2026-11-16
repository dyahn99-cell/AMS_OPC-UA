"""Typed ISDU settings validation. Commands and whole-record writes excluded."""
def resolve(item,subindex=0):
 if type(subindex) is not int:raise ValueError('invalid subindex')
 dt=item['datatype'];access=item.get('accessRights')
 if subindex:
  if dt['type']!='RecordT' or dt.get('subindexAccessSupported')=='false':raise ValueError('subindex access unavailable')
  child=next((c for c in dt['items'] if int(c['subindex'])==subindex),None)
  if child is None:raise ValueError('unknown subindex')
  if child.get('accessRightRestriction') in ('ro','wo'):access=child['accessRightRestriction']
  dt=child['datatype']
 return dt,access

def encode(dt,value):
 if dt['type'] not in ('IntegerT','UIntegerT') or type(value) is not int:raise ValueError('integer setting required')
 bits=int(dt['bitLength'])
 if bits not in (8,16,32):raise ValueError('unsupported setting size')
 signed=dt['type']=='IntegerT';lo=-(2**(bits-1)) if signed else 0;hi=2**(bits-1)-1 if signed else 2**bits-1
 if not lo<=value<=hi:raise ValueError('outside datatype range')
 choices=[int(c['value']) for c in dt.get('choices',[])];ranges=dt.get('ranges',[])
 if (choices or ranges) and value not in choices and not any(int(r['lowerValue'])<=value<=int(r['upperValue']) for r in ranges):raise ValueError('outside IODD range')
 return value.to_bytes(bits//8,'big',signed=signed)

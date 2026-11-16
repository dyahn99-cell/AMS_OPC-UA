"""BMTAC DOC1145638 p77-78: DeviceRead only; no DeviceWrite API."""
import socket,struct,time
import connection_profile

def transfer_isdu(port,index,subindex=0,payload=None,channel=1):
 if payload is not None and (not isinstance(payload,bytes) or not 1<=len(payload)<=202):raise ValueError("invalid write payload")
 if type(channel) is not int or not 1<=channel<=15:raise ValueError('invalid channel')
 if port not in (1,2,3,4) or not 0<=index<=65535 or not 0<=subindex<=255:raise ValueError('invalid ISDU address')
 sock,connection=connection_profile.connect()
 with sock as s:
  tid=0
  def exact(n):
   b=b''
   while len(b)<n:
    chunk=s.recv(n-len(b))
    if not chunk:raise OSError('connection closed')
    b+=chunk
   return b
  def exchange(pdu):
   nonlocal tid
   tid+=1;s.sendall(struct.pack('>HHHB',tid,0,len(pdu)+1,connection['unit'])+pdu)
   t,proto,size,unit=struct.unpack('>HHHB',exact(7))
   if (t,proto,unit)!=(tid,0,connection['unit']) or not 2<=size<=254:raise OSError('invalid Modbus response')
   r=exact(size-1)
   if r[0]!=pdu[0]:raise OSError('Modbus error '+r.hex())
   return r
  def words(address,count):
   r=exchange(struct.pack('>BHH',3,address,count))
   if len(r)!=2+2*count or r[1]!=2*count:raise OSError('invalid read length')
   return list(struct.unpack('>'+str(count)+'H',r[2:]))
  previous=words(5120,3)
  if previous[2]&255 in (0x32,0x33):raise OSError('acyclic mailbox busy')
  seq=previous[0]%65535+1
  request=[seq,0x10,0x32 if payload is None else 0x33,0x90,channel,0,0x64+port,0x3000,index,subindex]
  if payload is not None:
   padded=payload+b'\0'*(len(payload)%2)
   request += [len(payload)]+[padded[i]+(padded[i+1]<<8) for i in range(0,len(padded),2)]
  request += [0]*(112-len(request))
  response=exchange(struct.pack('>BHHB',16,4864,112,224)+struct.pack('>112H',*request))
  if response!=struct.pack('>BHH',16,4864,112):raise OSError('invalid request acknowledgement')
  end=time.monotonic()+connection['timeout']
  while time.monotonic()<end:
   r=words(5120,112)
   if r[0]==seq and r[2]&255==(0xb2 if payload is None else 0xb3):
    if r[1]!=0x10 or r[3:10]!=request[3:10]:raise OSError('ISDU response identity mismatch')
    if r[2]>>8:raise OSError('ISDU status '+hex(r[2]>>8))
    if payload is not None:return {'acknowledged':True}
    size=r[10]
    if not 1<=size<=202:raise OSError('unsupported ISDU payload length')
    payload=bytes(v for w in r[11:] for v in (w&255,w>>8))[:size]
    return {'channel':channel,'port':port,'index':index,'subindex':subindex,'timestamp':int(time.time()*1000),'bytes':list(payload)}
   if r[0] not in (previous[0],seq):raise OSError('mailbox changed by another client')
   time.sleep(.1)
  raise TimeoutError('ISDU response timeout')
def read_isdu(port,index,subindex=0,channel=1):
 return transfer_isdu(port,index,subindex,channel=channel)

def write_isdu(port,index,subindex,payload,channel=1):
 return transfer_isdu(port,index,subindex,payload,channel=channel)

if __name__=='__main__':
 import json
 print(json.dumps(read_isdu(2,1000)))

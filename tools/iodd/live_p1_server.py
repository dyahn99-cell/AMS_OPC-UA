"""Local commissioning UI. Shared Modbus target, explicit read/manual output endpoints."""
import json, socket, struct, time, secrets, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import nullcontext
ROOT=Path(__file__).resolve().parents[2]
TOKEN=secrets.token_urlsafe(32)
LOCK=threading.Lock()
from manual_output import Conflict
import connection_profile
from output_test import OutputTests
def call_output(q,write=False):
 if q.get('kind')=='iolink':from pd_output import output_request
 else:from manual_output import output_request
 with LOCK:
  if q.get('_session',TOKEN)!=TOKEN:raise Conflict('통신 설정이 변경됐습니다. 화면을 새로고침하세요.')
  return output_request(q,write=write)
OUTPUT_TESTS=OutputTests(call_output)
def read_input(input_bytes=64,input_offset=10,channel=1):
 if type(channel) is not int or not 1<=channel<=15:raise ValueError("invalid channel")
 if type(input_offset) is not int or input_offset<0 or input_offset+input_bytes>1440:raise ValueError("invalid input offset")
 if type(input_bytes) is not int or not 2<=input_bytes<=130:raise ValueError("inputBytes must be 2..130")
 skip=input_offset%2
 count=(input_bytes+skip+1)//2
 def exact(s,n):
  b=b''
  while len(b)<n:
   chunk=s.recv(n-len(b))
   if not chunk:raise OSError('connection closed')
   b+=chunk
  return b
 with LOCK:
  sock,connection=connection_profile.connect()
  with sock as s:
   return read_frame(s,connection,channel,inputOffset=input_offset,inputBytes=input_bytes,skip=skip,count=count,exact=lambda n:exact(s,n))
def read_frame(s,connection,channel,inputOffset,inputBytes,skip,count,exact):
 s.sendall(struct.pack('>HHHBBHH',1,0,6,connection['unit'],3,2048+inputOffset//2,count))
 tid,protocol,length,unit=struct.unpack('>HHHB',exact(7))
 if (tid,protocol,unit)!=(1,0,connection['unit']) or not 2<=length<=254:raise OSError('invalid Modbus header')
 pdu=exact(length-1)
 if len(pdu)!=2+count*2 or pdu[:2]!=bytes([3,count*2]):raise OSError('Modbus exception or invalid response')
 return {'channel':channel,'inputOffset':inputOffset,'connected':True,'timestamp':int(time.time()*1000),'bytes':list(b''.join(pdu[i:i+2][::-1] for i in range(2,len(pdu),2)))[skip:skip+inputBytes]}
class Handler(BaseHTTPRequestHandler):
 def send(self,status,data,kind='application/json'):
  if isinstance(data,dict) and isinstance(data.get('target'),dict):data={**data,'target':{k:v for k,v in data['target'].items() if k!='_session'}}
  raw=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
  self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  if self.headers.get('Host')!='127.0.0.1:8011':return self.send(403,{'error':'host'})
  if self.path=='/':return self.send(200,(ROOT/'assets/iodd-live-p1.html').read_text(encoding='utf8').replace('__TOKEN__',TOKEN).encode(),'text/html')
  if self.path=='/settings':return self.send(200,(ROOT/'assets/iodd-settings.html').read_text(encoding='utf8').replace('__TOKEN__',TOKEN).encode(),'text/html')
  if self.path=='/concept':return self.send(200,(ROOT/'assets/ams-flow-concept.html').read_bytes(),'text/html')
  if self.path=='/connection':return self.send(200,connection_profile.get())
  if self.path=='/presentations':return self.send(200,(ROOT/'outputs/iodd/product-presentations.json').read_bytes())
  if self.path=='/engineering':return self.send(200,(ROOT/'outputs/iodd/engineering-rules.json').read_bytes())
  if self.path=='/catalog':return self.send(200,(ROOT/'outputs/iodd/catalog.json').read_bytes())
  if self.path=='/assets/vendor/model-viewer/model-viewer.min.js':return self.send(200,(ROOT/'assets/vendor/model-viewer/model-viewer.min.js').read_bytes(),'text/javascript')
  model_files={'PF3A701H-L30.outline.glb','PF3A701H-L30.display.glb','EXW1-BMTAC.outline.glb','EXW1-RLAPA8C.outline.glb','PFUW760-L1.outline.glb','EXW1-BMTAC.glb','EXW1-RLAPA8C.glb','PFUW760-L1.glb','EXW1-BMTAC.display.glb','EXW1-RLAPA8C.display.glb','PFUW760-L1.display.glb'}
  if self.path.startswith('/assets/product-models/') and self.path.removeprefix('/assets/product-models/') in model_files:
   return self.send(200,(ROOT/self.path.lstrip('/')).read_bytes(),'model/gltf-binary')
  if self.path in ('/assets/product-models/PF3A701H-L30.png','/assets/product-models/EXW1-BMTAC.png','/assets/product-models/EXW1-RLAPA8C.png','/assets/product-models/PFUW760-L1.png'):
   return self.send(200,(ROOT/self.path.lstrip('/')).read_bytes(),'image/png')
  if self.path in ('/assets/remote-images/rla.png','/assets/remote-images/rlb.png'):
   return self.send(200,(ROOT/self.path.lstrip('/')).read_bytes(),'image/png')
  if self.path=='/assets/brand/smc-logo-white.svg':return self.send(200,(ROOT/'assets/brand/smc-logo-white.svg').read_bytes(),'image/svg+xml')
  if self.path=='/assets/iodd-ui.css':return self.send(200,(ROOT/'assets/iodd-ui.css').read_bytes(),'text/css')
  if self.path=='/assets/iodd-remote-visual.css':return self.send(200,(ROOT/'assets/iodd-remote-visual.css').read_bytes(),'text/css')
  allowed={'iodd-system.js','iodd-ui.js','iodd-product-visuals.js','iodd-output-panel.js','iodd-live-units.js','iodd-presentation.js','iodd-remote-visual.js','iodd-remote-map.js','iodd-settings.js','iodd-widgets.js','iodd-master-config.js','iodd-engineering.js','iodd-diagnostic-profiles.js','iodd-pd-decoder.js','iodd-live-p1.js'}
  name=self.path.removeprefix('/assets/')
  if self.path.startswith('/assets/') and name in allowed:return self.send(200,(ROOT/'assets'/name).read_bytes(),'text/javascript')
  self.send(404,{'error':'not found'})
 def do_POST(self):
  global TOKEN
  if self.path not in ('/connection','/connection-test','/read','/isdu','/isdu-write','/output-read','/output-write','/output-test-start','/output-test-status','/output-test-stop') or self.headers.get('Host')!='127.0.0.1:8011' or self.headers.get('Origin')!='http://127.0.0.1:8011' or self.headers.get('X-Read-Token')!=TOKEN:return self.send(403,{'error':'request rejected'})
  if self.path in ('/connection','/connection-test'):
   try:
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=4096:raise ValueError('invalid request size')
    q=json.loads(self.rfile.read(size))
    with OUTPUT_TESTS.guard:
     if OUTPUT_TESTS.job and OUTPUT_TESTS.job['state'] in ('running','stopping'):raise Conflict('출력 테스트를 먼저 중지하세요')
     with LOCK:
      result=connection_profile.save(q) if self.path=='/connection' else None
      if self.path=='/connection':TOKEN=secrets.token_urlsafe(32)
    if self.path=='/connection-test':
     if q!={}:raise ValueError('저장된 통신 설정으로 테스트합니다')
     data=read_input(input_bytes=2,input_offset=0,channel=1);result={'connected':True,'timestamp':data['timestamp'],'connection':connection_profile.get()}
    return self.send(200,result)
   except Conflict as e:return self.send(409,{'error':str(e)})
   except (ValueError,TypeError,KeyError) as e:return self.send(422,{'error':str(e)})
   except OSError as e:return self.send(503,{'error':str(e)})
  if self.path.startswith('/output-'):
   try:
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=4096:raise ValueError('invalid request size')
    q=json.loads(self.rfile.read(size))
    if not isinstance(q,dict):raise ValueError('invalid request')
    if self.path=='/output-test-start':
     if not isinstance(q.get('target'),dict):raise ValueError('invalid target')
     q['target']['_session']=self.headers.get('X-Read-Token');result=OUTPUT_TESTS.start(q)
    elif self.path=='/output-test-status':result=OUTPUT_TESTS.status(q.get('id'))
    elif self.path=='/output-test-stop':result=OUTPUT_TESTS.stop(q.get('id'))
    else:
     if self.path=='/output-write':
      with OUTPUT_TESTS.guard:
       if OUTPUT_TESTS.job and OUTPUT_TESTS.job['state'] in ('running','stopping'):raise Conflict('출력 테스트를 먼저 중지하세요.')
       q['_session']=self.headers.get('X-Read-Token');result=call_output(q,write=True)
     else:
      q['_session']=self.headers.get('X-Read-Token');result=call_output(q)
    return self.send(200,result)
   except Conflict as e:return self.send(409,{'error':str(e)})
   except (ValueError,TypeError,KeyError) as e:return self.send(422,{'error':str(e)})
   except OSError as e:return self.send(503,{'error':str(e)+' · 자동 재전송하지 않습니다. 다시 조회하세요.'})
  if self.path in ('/isdu','/isdu-write'):
   try:
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=4096:raise ValueError('invalid request size')
    q=json.loads(self.rfile.read(size))
    model=next(m for m in json.loads((ROOT/'outputs/iodd/catalog.json').read_text(encoding='utf8'))['models'] if m['sha256']==q['definition'])
    item=next(i for i in model['items'] if i['id']==q['item'] and i['source']=='ACYCLIC' and i.get('accessRights') in ('ro','rw'))
    from isdu_reader import read_isdu,write_isdu
    from isdu_settings import resolve,encode
    channel=q.get('channel',1)
    if type(channel) is not int or not 1<=channel<=15:raise ValueError('invalid channel')
    sub=q.get('subindex',0);dt,access=resolve(item,sub)
    if access not in ('ro','rw'):raise ValueError('setting is not readable')
    with (OUTPUT_TESTS.guard if self.path=='/isdu-write' else nullcontext()):
     if self.path=='/isdu-write' and OUTPUT_TESTS.job and OUTPUT_TESTS.job['state'] in ('running','stopping'):raise Conflict('출력 테스트를 먼저 중지하세요.')
     with LOCK:
      if self.headers.get('X-Read-Token')!=TOKEN:raise Conflict('통신 설정이 변경됐습니다. 화면을 새로고침하세요.')
      if self.path=='/isdu-write':
       if access!='rw':raise ValueError('read-only setting')
       encoded=encode(dt,q['value'])
       current=read_isdu(q['port'],int(item['index']),sub,channel=channel)
       if current['bytes']!=q.get('expected'):return self.send(409,{'error':'설정값이 변경됐습니다. 다시 조회하세요.'})
       write_isdu(q['port'],int(item['index']),sub,encoded,channel=channel)
       result=read_isdu(q['port'],int(item['index']),sub,channel=channel)
       result['verified']=result['bytes']==list(encoded)
      else:result=read_isdu(q['port'],int(item['index']),sub,channel=channel)
    return self.send(200,{**result,'definition':q['definition'],'item':item['id']})
   except Conflict as e:return self.send(409,{'error':str(e)})
   except (ValueError,KeyError,StopIteration,TypeError):return self.send(422,{'error':'invalid readable IODD item'})
   except OSError as e:return self.send(503,{'error':str(e)})
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<=size<=4096:raise ValueError('invalid request size')
   q=json.loads(self.rfile.read(size)) if size else {}
   self.send(200,read_input(q.get('inputBytes',64),q.get('inputOffset',10),q.get('channel',1)))
  except (ValueError,TypeError,AttributeError):self.send(422,{'error':'invalid inputBytes'})
  except OSError as e:self.send(503,{'error':str(e)})
if __name__=='__main__':
 print('P1 dashboard: http://127.0.0.1:8011',flush=True)
 ThreadingHTTPServer(('127.0.0.1',8011),Handler).serve_forever()

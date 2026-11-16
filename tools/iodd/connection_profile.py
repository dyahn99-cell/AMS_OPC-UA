"""Shared dashboard connection profile; does not change device Ethernet settings."""
import ipaddress,json,socket
from pathlib import Path
FILE=Path(__file__).resolve().parents[2]/'outputs/iodd/connection-profile.json'
DEFAULT={'host':'192.168.0.10','port':502,'unit':1,'timeout':4,'refreshMs':1000}
current=dict(DEFAULT)
def validate(q):
 if not isinstance(q,dict) or set(q)!=set(DEFAULT):raise ValueError('통신 설정 항목을 확인하세요')
 if not isinstance(q['host'],str):raise ValueError('IP 주소를 문자열로 입력하세요')
 ip=ipaddress.ip_address(q['host'])
 if ip.version!=4 or not ip.is_private or ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_link_local:raise ValueError('장비의 사설 IPv4 주소를 입력하세요')
 for key,lo,hi in [('port',1,65535),('unit',1,247),('refreshMs',500,10000)]:
  if type(q[key]) is not int or not lo<=q[key]<=hi:raise ValueError(key+' 범위 '+str(lo)+'–'+str(hi))
 if type(q['timeout']) not in (int,float) or not .5<=q['timeout']<=10:raise ValueError('응답 제한시간 범위 0.5–10초')
 return {**q,'host':str(ip)}
try:
 if FILE.exists():current=validate(json.loads(FILE.read_text(encoding='utf8')))
except (ValueError,OSError,TypeError):pass
def get():return dict(current)
def save(q):
 global current
 q=validate(q);FILE.parent.mkdir(parents=True,exist_ok=True);temp=FILE.with_suffix('.tmp');temp.write_text(json.dumps(q,indent=2),encoding='utf8');temp.replace(FILE);current=q;return get()
def connect():
 q=get();s=socket.create_connection((q['host'],q['port']),timeout=q['timeout']);s.settimeout(q['timeout']);return s,q

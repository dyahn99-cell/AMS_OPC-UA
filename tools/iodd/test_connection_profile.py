import unittest,tempfile,json,struct
from pathlib import Path
from unittest.mock import patch
import connection_profile as c
import live_p1_server as server
class ProfileTests(unittest.TestCase):
 def test_ranges_and_private_target(self):
  for update in [{'host':'8.8.8.8'},{'unit':0},{'timeout':float('nan')},{'refreshMs':0},{'port':70000}]:
   with self.assertRaises(ValueError):c.validate({**c.DEFAULT,**update})
 def test_atomic_save(self):
  old=c.get()
  with tempfile.TemporaryDirectory() as folder,patch.object(c,'FILE',Path(folder)/'profile.json'):
   try:self.assertEqual(c.save({**c.DEFAULT,'unit':2})['unit'],2);self.assertEqual(json.loads(c.FILE.read_text())['unit'],2)
   finally:c.current=old
 def test_frame_uses_unit_and_validates_echo(self):
  class Sock:
   def __init__(self,unit):self.raw=struct.pack('>HHHB',1,0,5,unit)+bytes([3,2,0x12,0x34]);self.sent=None
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def recv(self,n):r=self.raw[:n];self.raw=self.raw[n:];return r
   def sendall(self,r):self.sent=r
  s=Sock(2)
  with patch.object(c,'connect',return_value=(s,{**c.DEFAULT,'unit':2})):self.assertEqual(server.read_input(2,0)['bytes'],[0x34,0x12])
  self.assertEqual(s.sent[6],2)
  with patch.object(c,'connect',return_value=(Sock(1),{**c.DEFAULT,'unit':2})),self.assertRaises(OSError):server.read_input(2,0)
if __name__=='__main__':unittest.main()

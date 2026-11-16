"""Exercise the live HTTP handler without opening a socket or using hardware."""
import io
import json
import unittest
from unittest.mock import Mock, patch
import live_p1_server as server
from output_test import OutputTests

class RouteTests(unittest.TestCase):
    def post(self,path,body,origin='http://127.0.0.1:8011'):
        raw=json.dumps(body).encode();handler=object.__new__(server.Handler)
        handler.path=path;handler.rfile=io.BytesIO(raw)
        handler.headers={'Host':'127.0.0.1:8011','Origin':origin,'X-Read-Token':server.TOKEN,'Content-Length':str(len(raw))}
        result=[];handler.send=lambda status,data,*args:result.append((status,data))
        handler.do_POST();return result[0]
    def test_origin_required_before_driver(self):
        with patch.object(server,'call_output') as call:
            self.assertEqual(self.post('/output-write',{},origin='http://other-site')[0],403)
            call.assert_not_called()
    def test_output_read_uses_guarded_dispatch(self):
        with patch.object(server,'call_output',return_value={'words':[0]}) as call:
            self.assertEqual(self.post('/output-read',{'channel':2})[0],200)
            call.assert_called_once_with({'channel':2,'_session':server.TOKEN})
    def test_manual_and_isdu_writes_blocked_during_sweep(self):
        runner=OutputTests(Mock());runner.job={'state':'running'}
        with patch.object(server,'OUTPUT_TESTS',runner),patch.object(server,'call_output') as call,patch('isdu_reader.read_isdu') as read,patch('isdu_reader.write_isdu') as write:
            self.assertEqual(self.post('/output-write',{'channel':2})[0],409)
            q={'channel':1,'port':2,'definition':'b920ace7772c1d0982eaa99475e3d4df903b859a9b1ddc170640bbe24ecfe638','item':'V_Unit','subindex':0,'value':1,'expected':[0]}
            self.assertEqual(self.post('/isdu-write',q)[0],409)
            call.assert_not_called();read.assert_not_called();write.assert_not_called()
    def test_connection_change_rotates_session_without_device_call(self):
        old=server.TOKEN
        try:
            with patch('connection_profile.save',return_value=server.connection_profile.DEFAULT) as save:
                self.assertEqual(self.post('/connection',server.connection_profile.DEFAULT)[0],200)
                self.assertNotEqual(server.TOKEN,old)
                save.assert_called_once()
            with self.assertRaises(server.Conflict):server.call_output({'kind':'iolink','_session':old})
        finally:server.TOKEN=old
    def test_connection_change_rejected_during_output_sweep(self):
        runner=OutputTests(Mock());runner.job={'state':'running'}
        with patch.object(server,'OUTPUT_TESTS',runner),patch('connection_profile.save') as save:
            self.assertEqual(self.post('/connection',server.connection_profile.DEFAULT)[0],409)
            save.assert_not_called()
    def test_unknown_job_rejected(self):
        with patch.object(server,'OUTPUT_TESTS',OutputTests(Mock())):
            self.assertEqual(self.post('/output-test-status',{'id':'unknown'})[0],422)
            self.assertEqual(self.post('/output-test-stop',{'id':'unknown'})[0],422)
if __name__=='__main__':unittest.main()

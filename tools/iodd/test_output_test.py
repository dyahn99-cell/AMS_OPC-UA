import threading
import time
import unittest
from output_test import OutputTests
from manual_output import Conflict

class Device:
    def __init__(self):self.words=[0x8000];self.writes=[];self.lose_ack=False;self.external=False
    def call(self,q,write=False):
        if write:
            if self.words!=q['expected']:raise Conflict('changed')
            mask=1<<q['bit'];self.words[0]=self.words[0]|mask if q['value'] else self.words[0]&~mask
            self.writes.append((q['bit'],q['value']))
            if q['value'] and self.external:self.words[0]|=0x4000
            if q['value'] and self.lose_ack:raise OSError('lost ON acknowledgement')
        return {'words':list(self.words),'bits':16,'verified':not self.external}

class SweepTests(unittest.TestCase):
    def setup_job(self,d):
        runner=OutputTests(d.call)
        job={'id':'test','state':'running','cancel':threading.Event()};runner.job=job
        return runner,job
    def test_order_and_other_contacts_preserved(self):
        d=Device();r,j=self.setup_job(d);r.run(j,{},[{'bit':0,'label':'OUT0'},{'bit':1,'label':'OUT1'}],0,d.call({}),False)
        self.assertEqual(d.writes,[(0,True),(0,False),(1,True),(1,False)])
        self.assertEqual(d.words,[0x8000]);self.assertEqual(j['state'],'completed')
    def test_stop_during_on_still_turns_contact_off(self):
        d=Device();r,j=self.setup_job(d)
        original=d.call
        def call(q,write=False):
            result=original(q,write)
            if write and q['value']:j['cancel'].set()
            return result
        r.call=call;r.run(j,{},[{'bit':0,'label':'OUT0'},{'bit':1,'label':'OUT1'}],0,d.call({}),False)
        self.assertEqual(d.writes,[(0,True),(0,False)]);self.assertEqual(j['state'],'cancelled')
    def test_lost_on_ack_cleanup_no_repeat_on(self):
        d=Device();d.lose_ack=True;r,j=self.setup_job(d)
        r.run(j,{},[{'bit':0,'label':'OUT0'}],0,d.call({}),False)
        self.assertEqual(d.writes,[(0,True),(0,False)]);self.assertEqual(j['cleanup'],'off_verified')
    def test_external_change_is_not_overwritten_by_cleanup(self):
        d=Device();d.external=True;r,j=self.setup_job(d)
        r.run(j,{},[{'bit':0,'label':'OUT0'}],0,d.call({}),False)
        self.assertEqual(d.writes,[(0,True)]);self.assertEqual(j['cleanup'],'off_unconfirmed')
    def test_initial_on_and_stale_image_rejected(self):
        d=Device();r=OutputTests(d.call)
        for q in ({'contacts':['15'],'expected':[0x8000]},{'contacts':['0'],'expected':[0]}):
            with self.assertRaises(Conflict):r.start(dict(q,target={},interval=200))
        self.assertFalse(d.writes)
    def test_io_group_contact_cleanup_preserves_other_bits_and_padding(self):
        from unittest.mock import patch
        import pd_output
        state={'bytes':[0x80,0xaa]};writes=[]
        def call(q,write=False):
            if write:
                self.assertEqual(q['expected'],state['bytes']);state['bytes'][0]=q['value'];writes.append(q['value'])
                if q['value']==0x81:raise OSError('lost ON acknowledgement')
            return {'bytes':list(state['bytes']),'fields':[{'item':'out','value':state['bytes'][0]}],'verified':True}
        r=OutputTests(call);j={'id':'test','state':'running','cancel':threading.Event()};r.job=j
        item={'id':'out','bitOffset':'0','datatype':{'type':'UIntegerT','bitLength':'8'}}
        definition=({}, {}, {'bitLength':'8','datatype':{'type':'RecordT'}}, [item])
        with patch.object(pd_output,'definition',return_value=definition):
            r.run(j,{'kind':'iolink','swap':'direct'},[{'item':'out','bit':0,'label':'OUT0'}],0,call({}),True)
        self.assertEqual(writes,[0x81,0x80]);self.assertEqual(state['bytes'],[0x80,0xaa]);self.assertEqual(j['cleanup'],'off_verified')
if __name__=='__main__':unittest.main()

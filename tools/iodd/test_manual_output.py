import struct
import unittest
from unittest.mock import patch
import manual_output as mod

class FakeSocket:
    def __init__(self, unit=0x102a, offset=4, size=4):
        self.config=[2,unit,2048,offset//2,0,size]
        self.outputs={2:0x8001,3:0x55aa}
        self.output_writes=[]
        self.buffer=b''
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def settimeout(self,*args):pass
    def sendall(self,raw):
        tid,proto,size,unit=struct.unpack('>HHHB',raw[:7]);pdu=raw[7:]
        fc,addr,count=struct.unpack('>BHH',pdu[:5])
        if fc==3:
            words=self.config if addr==0x1700 else [self.outputs.get(addr+i,0) for i in range(count)]
            reply=bytes([3,count*2])+struct.pack('>'+str(count)+'H',*words)
        else:
            assert fc==16
            values=list(struct.unpack('>'+str(count)+'H',pdu[6:]))
            if addr!=0x1700:
                self.output_writes.append((addr,values))
                for i,w in enumerate(values):self.outputs[addr+i]=w
            reply=struct.pack('>BHH',16,addr,count)
        self.buffer=struct.pack('>HHHB',tid,0,len(reply)+1,1)+reply
    def recv(self,n):
        data=self.buffer[:n];self.buffer=self.buffer[n:];return data

class OutputTests(unittest.TestCase):
    def request(self,sock,**kw):
        q={'channel':2,'model':'valve','outputOffset':4,'bit':17,'value':True,'expected':[0x8001,0x55aa]};q.update(kw)
        with patch.object(mod.socket,'create_connection',return_value=sock):return mod.output_request(q,write=True)
    def test_selected_register_and_other_bits_preserved(self):
        sock=FakeSocket();r=self.request(sock,bit=16)
        self.assertEqual(sock.output_writes,[(3,[0x55ab])]);self.assertEqual(r['words'],[0x8001,0x55ab]);self.assertTrue(r['verified'])
    def test_off_preserves_other_contacts(self):
        sock=FakeSocket();self.request(sock,bit=0,value=False)
        self.assertEqual(sock.output_writes,[(2,[0x8000])])
    def test_wrong_hardware_blocked(self):
        sock=FakeSocket(unit=0x1017)
        with self.assertRaises(mod.Conflict):self.request(sock)
        self.assertFalse(sock.output_writes)
    def test_changed_snapshot_blocked(self):
        sock=FakeSocket()
        with self.assertRaises(mod.Conflict):self.request(sock,expected=[0,0])
        self.assertFalse(sock.output_writes)
    def test_reserved_rdm_bit_blocked(self):
        sock=FakeSocket()
        with self.assertRaises(ValueError):self.request(sock,model='rdm',bit=8,expected=[0])
        self.assertFalse(sock.output_writes)
    def test_read_never_writes_output(self):
        sock=FakeSocket()
        with patch.object(mod.socket,'create_connection',return_value=sock):
            r=mod.output_request({'channel':2,'model':'valve','outputOffset':4})
        self.assertEqual(r['words'],[0x8001,0x55aa]);self.assertFalse(sock.output_writes)
if __name__=='__main__':unittest.main()

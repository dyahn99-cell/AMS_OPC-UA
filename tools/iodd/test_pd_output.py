import unittest
from unittest.mock import patch
from test_manual_output import FakeSocket
import pd_output as mod

DIRECTION={'bitLength':'32','datatype':{'type':'RecordT'}}
ITEM={'id':'out','name':'OUT0_7','bitOffset':'24','datatype':{'type':'UIntegerT','bitLength':'8','ranges':[],'choices':[]}}
MODEL={'sha256':'exact-definition','items':[]}

class Socket(FakeSocket):
    def __init__(self, position=3, port=1, size=16):
        super().__init__();self.config=[0]*96
        self.config[:6]=[1,0x1017,2053,0,64,64]
        self.config[position*8:position*8+8]=[0,0x53+port,2054,1,16,size,0,0]
        self.outputs={0:0xaaff,1:0x0080,2:0x1234,3:0xeeee,8:0xcccc,2053:0x0102}

class PDOutputTests(unittest.TestCase):
    def request(self,sock,write=False,**args):
        q={'kind':'iolink','channel':1,'port':1,'model':'rla','definition':'exact-definition','layout':0,'swap':'direct','totalOutput':64,'outputOffset':0,'portOutputOffset':2,'portOutputBytes':16}
        q.update(args)
        with patch.object(mod.socket,'create_connection',return_value=sock),patch.object(mod,'definition',return_value=(MODEL,{'id':0,'condition':[]},DIRECTION,[ITEM])):
            return mod.output_request(q,write)
    def test_unit_id_search_not_firmware_position(self):
        for position in (3,4,7):
            r=self.request(Socket(position));self.assertEqual(r['fields'][0]['value'],128)
    def test_mask_preserves_other_bits_padding_header_and_port(self):
        sock=Socket();before=dict(sock.outputs);r=self.request(sock)
        after=self.request(sock,True,item='out',value=129,expected=r['bytes'])
        self.assertTrue(after['verified']);self.assertEqual(sock.outputs[1],0x0081)
        self.assertEqual({k:v for k,v in sock.outputs.items() if k!=1},{k:v for k,v in before.items() if k!=1})
        self.assertEqual(sock.output_writes,[(1,[0x0081])])
    def test_wrong_config_stale_snapshot_and_pq_reject_write(self):
        for field,value in [('portOutputOffset',4),('totalOutput',66),('portOutputBytes',14)]:
            sock=Socket();r=self.request(sock)
            expected=r['bytes'][:value] if field=='portOutputBytes' else r['bytes']
            with self.assertRaises(mod.Conflict):self.request(sock,True,item='out',value=1,expected=expected,**{field:value})
            self.assertFalse(sock.output_writes)
        sock=Socket();r=self.request(sock);sock.outputs[1]=1
        with self.assertRaises(mod.Conflict):self.request(sock,True,item='out',value=1,expected=r['bytes'])
        self.assertFalse(sock.output_writes)
        sock=Socket();r=self.request(sock);sock.outputs[2053]=2
        with self.assertRaises(mod.Conflict):self.request(sock,True,item='out',value=1,expected=r['bytes'])
        self.assertFalse(sock.output_writes)
    def test_value_validation_before_connection(self):
        with patch.object(mod.socket,'create_connection',side_effect=AssertionError('must not connect')):
            with self.assertRaises(ValueError):mod.encode([0]*4,ITEM,DIRECTION,256)
    def test_all_swap_modes_roundtrip_and_signed_cross_word(self):
        item={'datatype':{'type':'IntegerT','bitLength':'16','ranges':[{'lowerValue':'-100','upperValue':'100'}]},'bitOffset':'8'}
        source=[0xab,0,0,0xcd]
        for mode in ('direct','swap16','swap32','swapAll'):
            transport=mod.normalize(source+[0]*12,mode)
            ordered=mod.normalize(transport,mode)
            changed=mod.encode(ordered[:4],item,DIRECTION,-12)+ordered[4:]
            self.assertEqual(mod.decode(mod.normalize(mod.normalize(changed,mode),mode)[:4],item,DIRECTION),-12)
            self.assertEqual(changed[0],0xab);self.assertEqual(changed[3],0xcd)
    def test_non_contact_commands_excluded_from_sweep(self):
        dangerous={'id':'cmd','name':'Safety speed','bitOffset':'0','datatype':{'type':'BooleanT'}}
        self.assertEqual(len(mod.test_contacts([ITEM,dangerous],DIRECTION)),8)
    def test_octet_field_exact_length_and_other_field_preserved(self):
        item={'datatype':{'type':'OctetStringT','fixedLength':'3'},'bitOffset':'0'}
        result=mod.encode([0xaa,0,0,0],item,DIRECTION,'12 34 56')
        self.assertEqual(result,[0xaa,0x12,0x34,0x56]);self.assertEqual(mod.decode(result,item,DIRECTION),'12 34 56')
        for value in ('12 34','XX 34 56',12):
            with self.assertRaises(ValueError):mod.encode([0]*4,item,DIRECTION,value)
    def test_odd_allocation_neighbor_byte_preserved(self):
        sock=Socket(size=1)
        dt={'bitLength':'8','datatype':{'type':'UIntegerT'}}
        item={'id':'whole','name':'OutputByte','datatype':{'type':'UIntegerT','bitLength':'8'}}
        with patch.object(mod,'definition',return_value=(MODEL,{'id':0,'condition':[]},dt,[item])),patch.object(mod.socket,'create_connection',return_value=sock):
            q={'channel':1,'port':1,'model':'rla','totalOutput':64,'outputOffset':0,'portOutputOffset':2,'portOutputBytes':1}
            sock.outputs[1]=0xee80;r=mod.output_request(q)
            result=mod.output_request(dict(q,item='whole',value=1,expected=r['bytes']),True)
            self.assertTrue(result['verified']);self.assertEqual(sock.outputs[1],0xee01)
if __name__=='__main__':unittest.main()

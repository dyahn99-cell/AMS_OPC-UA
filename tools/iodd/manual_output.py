"""BMTAC DOC1145638 p37,56-58: manual PD output, not Force ON mode.
No retries, no background writes. Caller serializes with other device requests.
"""
import connection_profile
import socket
import struct
import time

# key: hardware remote ID, allocated output bytes, valid contact bits
PROFILES = {'rdy': (0x100e, 2, 16), 'rdm': (0x100d, 2, 8),
            'rdyg': (0x1029, 2, 16), 'rdmg': (0x1027, 2, 8),
            'rdmgn': (0x1027, 2, 8), 'valve': (0x102a, 4, 32)}

class Conflict(ValueError):
    pass

class Modbus:
    def __init__(self, sock, unit=1):
        self.sock, self.tid, self.unit = sock, 0, unit
    def exact(self, size):
        result = b''
        while len(result) < size:
            chunk = self.sock.recv(size-len(result))
            if not chunk: raise OSError('connection closed')
            result += chunk
        return result
    def exchange(self, pdu):
        self.tid += 1
        self.sock.sendall(struct.pack('>HHHB', self.tid, 0, len(pdu)+1, self.unit)+pdu)
        tid, proto, size, unit = struct.unpack('>HHHB', self.exact(7))
        if (tid, proto, unit) != (self.tid, 0, self.unit) or not 2 <= size <= 254:
            raise OSError('invalid Modbus response')
        response = self.exact(size-1)
        if response[0] != pdu[0]: raise OSError('Modbus exception '+response.hex())
        return response
    def read(self, address, count):
        response = self.exchange(struct.pack('>BHH', 3, address, count))
        if len(response) != count*2+2 or response[1] != count*2:
            raise OSError('invalid response length')
        return list(struct.unpack('>'+str(count)+'H', response[2:]))
    def write(self, address, words):
        count = len(words)
        response = self.exchange(struct.pack('>BHHB', 16, address, count, count*2)+struct.pack('>'+str(count)+'H', *words))
        if response != struct.pack('>BHH', 16, address, count):
            raise OSError('write acknowledgement mismatch; read again')

def output_request(q, write=False):
    channel, model, offset = q.get('channel'), q.get('model'), q.get('outputOffset')
    if type(channel) is not int or not 1 <= channel <= 15 or model not in PROFILES:
        raise ValueError('unsupported output remote')
    unit_id, size, bits = PROFILES[model]
    if type(offset) is not int or offset < 0 or offset % 2 or offset+size > 1440:
        raise ValueError('invalid output offset')
    if write:
        bit, value, expected = q.get('bit'), q.get('value'), q.get('expected')
        if type(bit) is not int or not 0 <= bit < bits or type(value) is not bool:
            raise ValueError('invalid output contact')
        if not isinstance(expected, list) or len(expected) != size//2 or any(type(w) is not int or not 0 <= w <= 65535 for w in expected):
            raise ValueError('read output before writing')
    sock,connection=connection_profile.connect()
    with sock:
        mb = Modbus(sock,connection['unit'])
        # Configuration mailbox: select channel, read its actual allocation.
        mb.write(0x1700, [channel]+[0]*15)
        config = mb.read(0x1700, 6)
        if config[0] != channel or config[1] != unit_id or config[3] != offset//2 or config[5] != size:
            raise Conflict('장비의 채널·모델·출력 할당과 구성표가 다릅니다. 출력을 전송하지 않았습니다.')
        address = offset//2
        words = mb.read(address, size//2)
        result = {'channel': channel, 'model': model, 'outputOffset': offset, 'bits': bits}
        if write:
            if words != expected:
                raise Conflict('조회 후 출력값이 변경됐습니다. 다시 조회하세요.')
            index, mask = bit//16, 1 << (bit%16)
            target = words[index] | mask if value else words[index] & ~mask
            # One register only; all other contact bits retain their latest read value.
            mb.write(address+index, [target])
            after = mb.read(address, size//2)
            wanted = list(words); wanted[index] = target
            result.update(verified=after == wanted, bit=bit, requested=value)
            words = after
        return dict(result, words=words, timestamp=int(time.time()*1000))

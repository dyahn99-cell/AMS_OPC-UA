"""One finite, server-owned contact sweep. Cancel finishes the current OFF.

No automatic retry of ON writes. Cleanup is a distinct OFF request, preserving
the current image only when it matches this job's last accepted/attempted image.
"""
import secrets
import threading
from manual_output import Conflict

class OutputTests:
    def __init__(self, call):
        self.call = call
        self.guard = threading.Lock()
        self.job = None

    def active(self):
        with self.guard: return self.job is not None and self.job['state'] in ('running', 'stopping')

    def status(self, key):
        with self.guard:
            if not self.job or self.job['id'] != key: raise ValueError('unknown output test')
            return {k: v for k, v in self.job.items() if k not in ('cancel',)}

    def stop(self, key):
        with self.guard:
            if not self.job or self.job['id'] != key: raise ValueError('unknown output test')
            if self.job['state'] == 'running':
                self.job['state'] = 'stopping'; self.job['cancel'].set()
        return self.status(key)

    @staticmethod
    def image(snapshot, io): return snapshot['bytes' if io else 'words']

    @staticmethod
    def value(snapshot, contact, io):
        if not io: return bool(snapshot['words'][contact['bit']//16] & (1 << (contact['bit']%16)))
        value = next(f['value'] for f in snapshot['fields'] if f['item'] == contact['item'])
        return bool(value) if contact['bit'] is None else bool(value & (1 << contact['bit']))

    @staticmethod
    def command(snapshot, contact, io, on):
        if not io: return {'bit': contact['bit'], 'value': on, 'expected': snapshot['words']}
        value = next(f['value'] for f in snapshot['fields'] if f['item'] == contact['item'])
        if contact['bit'] is None: value = on
        elif on: value |= 1 << contact['bit']
        else: value &= ~(1 << contact['bit'])
        return {'item': contact['item'], 'value': value, 'expected': snapshot['bytes']}

    def start(self, q):
        target, keys, interval = q.get('target'), q.get('contacts'), q.get('interval')
        if not isinstance(target, dict) or not isinstance(keys, list) or not 1 <= len(keys) <= 32 or len(set(keys)) != len(keys) or any(not isinstance(k, str) for k in keys):
            raise ValueError('select 1..32 distinct contacts')
        if type(interval) is not int or not 200 <= interval <= 5000: raise ValueError('interval must be 200..5000ms')
        # Reserve before communication so two concurrent starts cannot overlap.
        with self.guard:
            if self.job and self.job['state'] in ('running', 'stopping'): raise Conflict('출력 테스트가 이미 실행 중입니다.')
            self.job = {'id': secrets.token_urlsafe(18), 'target':target, 'state': 'running', 'step': 0, 'total': len(keys), 'label': '', 'error': '', 'cleanup': 'not_needed', 'cancel': threading.Event()}
            job = self.job
        try:
            io = target.get('kind') == 'iolink'
            snapshot = self.call(target, False)
            if self.image(snapshot, io) != q.get('expected'): raise Conflict('조회 후 출력값이 변경됐습니다. 다시 조회하세요.')
            contacts = snapshot['contacts'] if io else [{'key': str(bit), 'bit': bit, 'label': 'OUT '+str(bit)} for bit in range(snapshot['bits'])]
            selected = [next((c for c in contacts if c['key'] == key), None) for key in keys]
            if any(c is None for c in selected): raise ValueError('unsupported test contact')
            if any(self.value(snapshot, c, io) for c in selected): raise Conflict('선택한 접점은 모두 OFF로 조회된 상태에서 테스트하세요.')
            threading.Thread(target=self.run, args=(job, target, selected, interval/1000, snapshot, io), daemon=True).start()
            return self.status(job['id'])
        except Exception as e:
            with self.guard: job.update(state='failed', error=str(e))
            raise

    def run(self, job, target, contacts, interval, snapshot, io):
        current_contact = None
        try:
            for number, contact in enumerate(contacts, 1):
                if job['cancel'].is_set(): break
                with self.guard: job.update(step=number, label=contact['label'])
                current_contact = contact
                command = self.command(snapshot, contact, io, True)
                # Track a possibly-applied ON even when its acknowledgment is lost.
                before = snapshot
                snapshot = self.call(dict(target, **command), True)
                if not snapshot.get('verified'): raise Conflict('ON 재조회 불일치')
                job['cancel'].wait(interval)
                snapshot = self.call(dict(target, **self.command(snapshot, contact, io, False)), True)
                if not snapshot.get('verified'): raise Conflict('OFF 재조회 불일치')
                current_contact = None
                with self.guard: job['cleanup'] = 'off_verified'
                if job['cancel'].wait(interval): break
            with self.guard: job.update(state='cancelled' if job['cancel'].is_set() else 'completed', snapshot=snapshot)
        except Exception as e:
            cleanup = 'not_needed'
            if current_contact:
                cleanup = 'off_unconfirmed'
                try:
                    fresh = self.call(target, False)
                    # A failed ON acknowledgement may have applied. Accept only
                    # the same image except for the one selected contact.
                    off_command = self.command(fresh, current_contact, io, False)
                    expected_off = self.command(before, current_contact, io, False)
                    if io:
                        # All unrelated decoded fields AND padding must match.
                        from pd_output import definition, normalize, encode
                        _, _, direction, items = definition(target)
                        item = next(i for i in items if i['id'] == current_contact['item'])
                        size = (int(direction['bitLength'])+7)//8
                        ordered = normalize(fresh['bytes'], target.get('swap', 'direct'))
                        cleared = encode(ordered[:size], item, direction, off_command['value'])+ordered[size:]
                        if normalize(cleared, target.get('swap', 'direct')) != before['bytes']: raise Conflict('다른 출력 변경 감지')
                    else:
                        cleared = list(fresh['words']); bit = current_contact['bit']; cleared[bit//16] &= ~(1 << (bit%16))
                        if cleared != before['words']: raise Conflict('다른 출력 변경 감지')
                    result = self.call(dict(target, **off_command), True)
                    if result.get('verified'): cleanup = 'off_verified'
                except Exception: pass
            with self.guard: job.update(state='failed', error=str(e), cleanup=cleanup)

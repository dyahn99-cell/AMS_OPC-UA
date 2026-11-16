"""Offline configuration plans only. No runtime, transport or equipment imports."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path


class Conflict(ValueError):
    pass


def validate(masters, catalog):
    if not isinstance(masters, list) or len(masters) > 120:
        raise ValueError('마스터 목록은 최대 120개입니다')
    identities, locations = set(), set()
    def integer(value, low, high):
        return type(value) is int and low <= value <= high
    for entry in masters:
        if not isinstance(entry, dict):
            raise ValueError('마스터 형식 오류')
        identity, c = entry.get('id'), entry.get('config')
        if not isinstance(identity, str) or not 1 <= len(identity) <= 80 or identity in identities:
            raise ValueError('고유한 마스터 ID가 필요합니다')
        identities.add(identity)
        if not isinstance(c, dict) or c.get('schema') != 1:
            raise ValueError('지원하지 않는 구성 형식')
        base, ch = c.get('base'), c.get('channel')
        if not isinstance(base, str) or not base.strip() or base != base.strip() or len(base) > 100 or not integer(ch, 1, 15):
            raise ValueError('베이스/채널 오류')
        if (base, ch) in locations:
            raise ValueError('같은 베이스/채널에 마스터가 중복됩니다')
        locations.add((base, ch))
        kind, protocol = c.get('model'), c.get('protocol')
        if kind not in ('EXW1-RLAPA8C', 'EXW1-RLBPA7C') or protocol not in ('1.0', '2.0'):
            raise ValueError('모델/프로토콜 오류')
        count, maximum = (4, 130) if kind == 'EXW1-RLAPA8C' else (2, 66)
        limit = 14 if protocol == '1.0' else 32
        for direction in ('input', 'output'):
            if not integer(c.get(direction), 16 if protocol == '1.0' else 2, 16 if protocol == '1.0' else maximum):
                raise ValueError('전체 바이트 범위 오류')
        if any(type(c.get(y)) is not bool for y in ('y1', 'y2')):
            raise ValueError('분기 배선 확인 오류')
        ports = c.get('ports')
        if not isinstance(ports, list) or len(ports) != 4:
            raise ValueError('P1–P4 정의 필요')
        totals = {'input': 2, 'output': 2}
        for n, p in enumerate(ports, 1):
            if not isinstance(p, dict) or type(p.get('id')) is not int or p['id'] != n or type(p.get('enabled')) is not bool:
                raise ValueError('포트 형식 오류')
            if not isinstance(p.get('alias'), str) or len(p['alias']) > 100:
                raise ValueError('포트 별칭 오류')
            if p.get('mode') not in ('deactivated', 'manual', 'autostart', 'di', 'do') or p.get('swap') not in ('direct', 'swap16', 'swap32', 'swapAll'):
                raise ValueError('포트 모드/바이트 순서 오류')
            if p['enabled'] and (n > count or p['mode'] == 'deactivated' or (n > 2 and not c['y1' if n == 3 else 'y2'])):
                raise ValueError('사용 포트/분기 배선 불일치')
            io = p['enabled'] and p['mode'] in ('manual', 'autostart')
            layout = None
            if io:
                model = catalog.get(p.get('definition'))
                if model and type(p.get('layout')) is int:
                    layout = next((l for l in model['layouts'] if l['id'] == p['layout']), None)
                if layout is None:
                    raise ValueError('제품 버전/레이아웃 오류')
            for direction, source in (('input', 'PD IN'), ('output', 'PD OUT')):
                size = p.get(direction)
                if not integer(size, 0, limit) or (not io and size != 0):
                    raise ValueError('포트 바이트 범위 오류')
                if io:
                    d = next((d for d in layout['directions'] if d['source'] == source), None)
                    bits = int(d['bitLength']) if d else 0
                    if bits < 0 or size < (bits + 7) // 8:
                        raise ValueError('IODD 요구 길이보다 작은 할당')
                    totals[direction] += size
        if any(totals[d] > c[d] for d in totals):
            raise ValueError('포트 합계가 전체 할당보다 큽니다')


class WorkspaceStore:
    def __init__(self, path, catalog):
        self.path, self.catalog = Path(path), catalog

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS workspace (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, payload TEXT NOT NULL)')
        db.commit()
        return db

    def load(self):
        with closing(self._connect()) as db, db:
            row = db.execute('SELECT revision,payload FROM workspace WHERE id=1').fetchone()
        return {'revision': row[0], 'masters': json.loads(row[1])} if row else {'revision': 0, 'masters': []}

    def save(self, revision, masters):
        if type(revision) is not int or revision < 0:
            raise ValueError('저장 버전 오류')
        validate(masters, self.catalog)
        payload = json.dumps(masters, ensure_ascii=False)
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM workspace WHERE id=1').fetchone()
            current = row[0] if row else 0
            if revision != current:
                raise Conflict('다른 화면에서 변경했습니다. 다시 불러온 후 저장하세요')
            db.execute('INSERT OR REPLACE INTO workspace VALUES(1,?,?)', (current + 1, payload))
        return {'revision': current + 1, 'masters': json.loads(payload)}


def install_routes(app, base_dir, bundle_dir, read_master=None):
    from fastapi import Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from starlette.concurrency import run_in_threadpool

    def asset(name):
        path = Path(base_dir()) / 'assets' / name
        return path if path.exists() else Path(bundle_dir()) / 'assets' / name

    def store():
        definitions = json.loads(asset('iodd-layouts.json').read_text(encoding='utf-8'))
        return WorkspaceStore(Path(base_dir()) / 'device_workspace.sqlite3', {m['sha256']: m for m in definitions})

    @app.get('/device-workspace', response_class=HTMLResponse)
    def page():
        path = asset('iodd-workspace.html')
        if not path.exists():
            return HTMLResponse('장비 구성 화면 빌드가 필요합니다.', status_code=503)
        return HTMLResponse(path.read_text(encoding='utf-8'), headers={'Cache-Control': 'no-store'})

    @app.get('/api/device-workspace')
    def read():
        try:
            return store().load()
        except (OSError, sqlite3.Error, ValueError):
            return JSONResponse({'error': '구성 저장소를 읽을 수 없습니다. 기존 파일을 보존했습니다.'}, status_code=503)

    @app.put('/api/device-workspace')
    async def write(request: Request):
        # Bound streamed bodies as well as requests with Content-Length.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1_000_000:
                return JSONResponse({'error': '구성 크기 초과'}, status_code=413)
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError('구성 형식 오류')
            return store().save(payload.get('revision'), payload.get('masters'))
        except Conflict as exc:
            return JSONResponse({'error': str(exc)}, status_code=409)
        except (ValueError, TypeError, KeyError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=422)
        except (OSError, sqlite3.Error):
            return JSONResponse({'error': '구성 저장 실패'}, status_code=503)

    @app.post('/api/device-workspace/read')
    async def read_once(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4096:
                return JSONResponse({'error': '읽기 요청 크기 초과'}, status_code=413)
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or type(payload.get('revision')) is not int:
                raise ValueError('저장 구성 버전이 필요합니다')
            saved = store().load()
            if payload['revision'] != saved['revision']:
                raise Conflict('저장 구성이 바뀌었습니다. 다시 불러오세요')
            entry = next((m for m in saved['masters'] if m['id'] == payload.get('id')), None)
            if entry is None or read_master is None:
                raise ValueError('저장된 마스터와 읽기 연결이 필요합니다')
            validate([entry], store().catalog)
            result = await run_in_threadpool(read_master, entry['config'])
            if store().load()['revision'] != saved['revision']:
                raise Conflict('읽는 동안 구성이 변경되어 결과를 폐기했습니다')
            return {'id': entry['id'], 'revision': saved['revision'], 'config': entry['config'], **result}
        except Conflict as exc:
            return JSONResponse({'error': str(exc)}, status_code=409)
        except (ValueError, TypeError, KeyError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=422)
        except (OSError, sqlite3.Error):
            return JSONResponse({'error': '입력 읽기 실패 · 수신값 없음'}, status_code=503)

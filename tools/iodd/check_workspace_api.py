"""In-process ASGI requests; no runtime import, lifespan, server or socket."""
import asyncio
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from fastapi import FastAPI
import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from test_workspace import module, plan

spec = importlib.util.spec_from_file_location('workspace_access_test', ROOT / 'app/local_access.py')
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'assets').mkdir()
        (root / 'assets/iodd-layouts.json').write_text('[]')
        (root / 'assets/iodd-workspace.html').write_text('<h1>workspace</h1>')
        app = FastAPI()
        reads=[]
        def read_master(config):
            reads.append(config)
            return {'mapping': {'functionCode':3}, 'response': {'words':[0], 'connected':True}}
        module.install_routes(app, lambda: root, lambda: root, read_master)
        access.install_local_access(app)
        transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 12345))
        async with httpx.AsyncClient(transport=transport, base_url='http://localhost:8000') as client:
            assert (await client.get('/device-workspace')).status_code == 200
            assert (await client.get('/api/device-workspace')).status_code == 403
            token = (await client.get('/api/local-session', headers={'x-ams-bootstrap': '1'})).json()['token']
            headers = {'x-ams-local-token': token}
            assert (await client.get('/api/device-workspace', headers=headers)).json() == {'revision': 0, 'masters': []}
            payload = {'revision': 0, 'masters': [{'id': 'one', 'config': plan()}]}
            assert (await client.put('/api/device-workspace', headers=headers, json=payload)).status_code == 200
            assert (await client.put('/api/device-workspace', headers=headers, json=payload)).status_code == 409
            payload['revision'] = 1
            payload['masters'].append({'id': 'two', 'config': plan()})
            assert (await client.put('/api/device-workspace', headers=headers, json=payload)).status_code == 422
            assert (await client.put('/api/device-workspace', headers={**headers, 'origin': 'http://evil.invalid'}, json=payload)).status_code == 403
            assert (await client.put('/api/device-workspace', headers=headers, content=b' ' * 1_000_001)).status_code == 413
            assert (await client.put('/api/device-workspace', headers=headers, content='broken')).status_code == 422
            saved = (await client.get('/api/device-workspace', headers=headers)).json()
            assert saved['revision'] == 1 and len(saved['masters']) == 1
            response=await client.post('/api/device-workspace/read',headers=headers,json={'id':'one','revision':1})
            assert response.status_code==200 and len(reads)==1
            assert (await client.post('/api/device-workspace/read',headers=headers,json={'id':'one','revision':0})).status_code==409
            assert (await client.post('/api/device-workspace/read',headers=headers,json={'id':'missing','revision':1})).status_code==422
            assert (await client.post('/api/device-workspace/read',json={'id':'one','revision':1})).status_code==403
            assert len(reads)==1
    print('PASS: page, authenticated API, persistence, conflict, duplicate channel, invalid body, body limit, cross-origin rejection')


asyncio.run(main())

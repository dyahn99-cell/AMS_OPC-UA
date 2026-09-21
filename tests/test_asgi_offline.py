"""Real ASGI routing with immediate fake thread dispatch; no server or event loop sockets."""
import copy
import json
from unittest.mock import Mock
from starlette.websockets import WebSocketDisconnect
from app.control_coordinator import ControlCoordinator
import unittest
from unittest.mock import patch

from offline_fixtures import guarded_runtime, isolated_runtime
from test_local_access import finish_immediate, scope

runtime = guarded_runtime()


class AsgiOfflineTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))

    def request(self, payload, *, token=True, origin="http://127.0.0.1:8000"):
        request = scope("/api/control/standby-signal", token=runtime.app.state.local_request_token if token else None, origin=origin)
        request.update(http_version="1.1", root_path="", asgi={"version": "3.0"})
        request["headers"].append((b"content-type", b"application/json"))
        sent = []

        async def receive():
            return {"type": "http.request", "body": json.dumps(payload).encode(), "more_body": False}

        async def send(message):
            sent.append(message)

        async def dispatch(function, *args, **kwargs):
            return function(*args, **kwargs)

        with patch("fastapi.routing.run_in_threadpool", dispatch), patch("starlette.routing.run_in_threadpool", dispatch):
            finish_immediate(runtime.app(request, receive, send))
        return sent[0]["status"]

    def test_actual_routes_block_invalid_types_origin_and_missing_token(self):
        with patch.object(runtime, "_legacy_hub_command") as command:
            self.assertEqual(self.request({"remote_id": "AMS01", "enabled": "false"}), 422)
            self.assertEqual(self.request({"remote_id": "AMS01", "enabled": True}, token=False), 403)
            self.assertEqual(self.request({"remote_id": "AMS01", "enabled": True}, origin="https://evil.invalid"), 403)
            command.assert_not_called()

    def test_websocket_route_rejects_token_before_collecting(self):
        request = scope("/ws/hub", kind="websocket")
        request.update(http_version="1.1", root_path="", asgi={"version": "3.0"}, subprotocols=[])
        messages = iter([
            {"type": "websocket.connect"},
            {"type": "websocket.receive", "text": json.dumps({"type": "local-auth", "token": "wrong"})},
        ])
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        async def immediate(awaitable, *, timeout):
            return await awaitable

        with patch("app.local_access.asyncio.wait_for", immediate), patch.object(runtime, "_hub_live_payload") as collect:
            finish_immediate(runtime.app(request, receive, send))
        collect.assert_not_called()
        self.assertEqual([message["type"] for message in sent], ["websocket.accept", "websocket.close"])
        self.assertEqual(sent[-1]["code"], 1008)

    def observe(self, path, *, refresh=False):
        websocket = path.startswith('/ws/')
        request = scope(path, method='GET', kind='websocket' if websocket else 'http',
                        token=runtime.app.state.local_request_token)
        request.update(http_version='1.1', root_path='', asgi={'version': '3.0'}, subprotocols=[],
                       query_string=b'refresh=true' if refresh else b'')
        messages = iter([{'type': 'websocket.connect'}, {'type': 'websocket.receive',
            'text': json.dumps({'type': 'local-auth', 'token': runtime.app.state.local_request_token})}])
        sent = []

        async def receive():
            return next(messages) if websocket else {'type': 'http.request', 'body': b''}

        async def send(message):
            sent.append(message)
            if message['type'] == 'websocket.send':
                raise WebSocketDisconnect()

        async def dispatch(function, *args, **kwargs):
            return function(*args, **kwargs)

        async def immediate(awaitable, *, timeout):
            return await awaitable

        with patch('fastapi.routing.run_in_threadpool', dispatch), \
             patch('starlette.routing.run_in_threadpool', dispatch), \
             patch('app.local_access.asyncio.wait_for', immediate), \
             patch.object(runtime.asyncio, 'to_thread', dispatch):
            finish_immediate(runtime.app(request, receive, send))
        if websocket:
            self.assertEqual([m['type'] for m in sent], ['websocket.accept', 'websocket.send'])
            return json.loads(sent[-1]['text'])
        self.assertEqual(sent[0]['status'], 200)
        return json.loads(b''.join(m.get('body', b'') for m in sent))

    def test_actual_http_ws_observers_refresh_and_coordinator_output_boundary(self):
        runtime.config_store.update(data_source='modbus', modbus_process_byte_swap=True)
        payload = {'devices': [
            {'device_id': 'IO13', 'online': True, 'timestamp': '2026-09-01T00:00:00+00:00', 'dio_code': 1},
            {'device_id': 'AMS01', 'online': True, 'timestamp': '2026-09-01T00:00:00+00:00', 'ams_code': 3}]}
        hub = Mock()
        hub.cached.side_effect = lambda: copy.deepcopy(payload)
        hub.read_all.side_effect = lambda: copy.deepcopy(payload)
        register = [0xFDAB]

        def write(address, values, **kwargs):
            register[0] = values[0]

        with patch.object(runtime, 'get_device_hub', return_value=hub), \
             patch.object(runtime.time, 'time', return_value=1788220801), \
             patch.object(runtime, '_modbus_read_registers', side_effect=lambda *a, **k: [register[0]]), \
             patch.object(runtime, '_modbus_write_registers', side_effect=write) as writes, \
             patch.object(runtime, '_apply_dio_links', wraps=runtime._apply_dio_links) as dio, \
             patch.object(runtime, '_apply_ch1_status_lamp', wraps=runtime._apply_ch1_status_lamp) as lamp:
            for observers in (0, 1, 3):
                with self.subTest(observers=observers):
                    for _ in range(observers):
                        self.observe('/api/hub/snapshot')
                        self.observe('/api/remotes/status')
                        self.observe('/api/dio-links')
                        self.observe('/ws/hub')
                        self.observe('/ws/live')
                    hub.read_all.assert_not_called()
                    dio.assert_not_called()
                    lamp.assert_not_called()
                    writes.assert_not_called()
            self.observe('/api/hub/snapshot', refresh=True)
            hub.read_all.assert_called_once_with()
            dio.assert_not_called()
            lamp.assert_not_called()
            writes.assert_not_called()
            coordinator = ControlCoordinator(runtime._collect_control_cycle, Mock(), lambda: 10)
            coordinator._stop = Mock()
            coordinator._stop.is_set.side_effect = [False, True, True]
            with patch('app.control_coordinator.time.monotonic', return_value=0):
                coordinator._run()
            self.assertEqual(hub.read_all.call_count, 2)
            dio.assert_called_once()
            lamp.assert_called_once()
            writes.assert_called_once()
            self.assertEqual(register[0], 0xFEAB)
            self.observe('/api/hub/snapshot')
            self.observe('/ws/hub')
            self.assertEqual(hub.read_all.call_count, 2)
            self.assertEqual(writes.call_count, 1)

    def test_actual_route_dispatches_valid_request_once(self):
        with patch.object(runtime, "_legacy_hub_command", return_value={"ok": True}) as command:
            self.assertEqual(self.request({"remote_id": "AMS01", "enabled": False}), 200)
            command.assert_called_once_with("AMS01", "standby", {"enabled": False})

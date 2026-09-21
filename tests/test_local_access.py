import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.local_access import LocalAccessMiddleware, authenticate_websocket, local_request_error


def scope(path="/api/control/standby-signal", *, method="POST", host="127.0.0.1:8000", origin="http://127.0.0.1:8000", token=None, client="127.0.0.1", kind="http"):
    headers = [(b"host", host.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if token is not None:
        headers.append((b"x-ams-local-token", token.encode()))
    return {"type": kind, "method": method, "path": path, "scheme": "ws" if kind == "websocket" else "http",
            "headers": headers, "server": ("127.0.0.1", 8000), "client": (client, 53000), "query_string": b""}


def finish_immediate(coroutine):
    # ASGI middleware awaits only immediate fake callables; no event-loop sockets.
    try:
        coroutine.send(None)
    except StopIteration as finished:
        return finished.value
    finally:
        coroutine.close()
    raise AssertionError("unexpected asynchronous I/O in local access test")


class LocalAccessTests(unittest.TestCase):
    def request(self, request_scope):
        called, sent = [], []

        async def app(scope, receive, send):
            called.append(scope["path"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            sent.append(message)

        finish_immediate(LocalAccessMiddleware(app, token="synthetic-token")(request_scope, receive, send))
        return called, sent

    def test_no_token_blocks_commands_and_side_effecting_gets(self):
        for path, method in [("/api/control/standby-signal", "POST"), ("/api/hub/devices/AMS01/settings", "GET"), ("/api/hub/snapshot", "GET")]:
            with self.subTest(path=path):
                called, sent = self.request(scope(path, method=method))
                self.assertEqual(called, [])
                self.assertEqual(sent[0]["status"], 403)

    def test_same_origin_token_allows_route_once(self):
        called, sent = self.request(scope(token="synthetic-token"))
        self.assertEqual(called, ["/api/control/standby-signal"])
        self.assertEqual(sent[0]["status"], 200)
        headers = dict(sent[0]["headers"])
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertNotIn(b"access-control-allow-origin", headers)

    def test_host_origin_peer_are_checked_even_with_valid_token(self):
        cases = [
            {"host": "evil.invalid:8000"}, {"host": "127.0.0.1:9000"},
            {"host": "localhost.evil.invalid:8000"}, {"host": "user@127.0.0.1:8000"},
            {"origin": "null"}, {"origin": "http://evil.invalid"},
            {"origin": "http://127.0.0.1:9000"}, {"origin": "http://localhost:8000"},
            {"origin": "http://127.0.0.1:8000/"}, {"client": "192.0.2.1"},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                called, sent = self.request(scope(token="synthetic-token", **changes))
                self.assertEqual(called, [])
                self.assertEqual(sent[0]["status"], 403)

    def test_bootstrap_requires_non_simple_header_and_never_calls_route(self):
        request = scope("/api/local-session", method="GET", origin=None)
        called, sent = self.request(request)
        self.assertEqual(sent[0]["status"], 403)
        request["headers"].append((b"x-ams-bootstrap", b"1"))
        called, sent = self.request(request)
        self.assertEqual(called, [])
        self.assertEqual(sent[0]["status"], 200)
        self.assertEqual(json.loads(sent[1]["body"])["token"], "synthetic-token")

    def test_cross_site_navigation_and_preflight_cannot_get_token(self):
        request = scope("/api/local-session", method="GET", origin=None)
        request["headers"] += [(b"x-ams-bootstrap", b"1"), (b"sec-fetch-site", b"same-site")]
        self.assertEqual(self.request(request)[1][0]["status"], 403)
        request = scope("/api/local-session", method="OPTIONS", origin="https://evil.invalid")
        self.assertEqual(self.request(request)[1][0]["status"], 403)

    def test_websocket_origin_is_required_before_accept(self):
        for origin in (None, "null", "http://127.0.0.1:9000"):
            with self.subTest(origin=origin):
                called, sent = self.request(scope("/ws/hub", kind="websocket", origin=origin))
                self.assertEqual(called, [])
                self.assertEqual(sent, [{"type": "websocket.close", "code": 1008}])

    def test_duplicate_headers_and_non_ascii_token_reject_without_crash(self):
        request = scope(token="synthetic-token")
        request["headers"].append((b"host", b"localhost:8000"))
        self.assertEqual(self.request(request)[1][0]["status"], 403)
        self.assertEqual(self.request(scope(token="wrong-한글"))[1][0]["status"], 403)

    def test_localhost_ipv6_and_originless_script_requests(self):
        for host, origin in [("localhost:8000", "http://localhost:8000"), ("[::1]:8000", "http://[::1]:8000"), ("127.0.0.1:8000", None)]:
            with self.subTest(host=host, origin=origin):
                self.assertIsNone(local_request_error(scope(host=host, origin=origin, token="synthetic-token")))


class WebSocketAuthTests(unittest.TestCase):
    def authenticate(self, message, *, origin="http://127.0.0.1:8000", timeout=False):
        events = []

        async def accept():
            events.append("accept")

        async def close(*, code):
            events.append(("close", code))

        async def receive_json():
            events.append("receive")
            return message

        async def wait_for(awaitable, *, timeout):
            return await awaitable

        async def expire(awaitable, *, timeout):
            awaitable.close()
            raise asyncio.TimeoutError

        websocket = SimpleNamespace(
            scope=scope("/ws/hub", kind="websocket", origin=origin),
            app=SimpleNamespace(state=SimpleNamespace(local_request_token="synthetic-token")),
            accept=accept, close=close, receive_json=receive_json,
        )
        # A fake timeout driver, not an event loop or socket pair.
        with patch("app.local_access.asyncio.wait_for", expire if timeout else wait_for):
            result = finish_immediate(authenticate_websocket(websocket))
        return result, events

    def test_valid_first_frame_authenticates(self):
        result, events = self.authenticate({"type": "local-auth", "token": "synthetic-token"})
        self.assertTrue(result)
        self.assertEqual(events, ["accept", "receive"])

    def test_invalid_frames_close_before_data_is_served(self):
        for message in (None, [], {}, {"type": "command", "token": "synthetic-token"},
                        {"type": "local-auth", "token": "wrong"}):
            with self.subTest(message=message):
                result, events = self.authenticate(message)
                self.assertFalse(result)
                self.assertEqual(events, ["accept", "receive", ("close", 1008)])

    def test_invalid_origin_is_rejected_before_accept(self):
        result, events = self.authenticate({}, origin="https://evil.invalid")
        self.assertFalse(result)
        self.assertEqual(events, [("close", 1008)])

    def test_timeout_closes_without_telemetry(self):
        result, events = self.authenticate({}, timeout=True)
        self.assertFalse(result)
        self.assertEqual(events, ["accept", ("close", 1008)])


if __name__ == "__main__":
    unittest.main()

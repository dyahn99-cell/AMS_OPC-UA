"""Same-PC browser request protection, not authentication against local OS users."""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import secrets
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse


TOKEN_HEADER = "x-ams-local-token"
BOOTSTRAP_HEADER = "x-ams-bootstrap"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "frame-ancestors 'none'; object-src 'none'; base-uri 'self'",
}


def _authority(value: str, scheme: str):
    if not value or any(character.isspace() or ord(character) < 32 for character in value):
        return None
    try:
        parsed = urlsplit(f"{scheme}://{value}")
        if (parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment
                or parsed.hostname not in LOCAL_HOSTS):
            return None
        port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
        return parsed.hostname, port
    except ValueError:
        return None


def local_request_error(scope) -> str | None:
    headers = Headers(scope=scope)
    if len(headers.getlist("host")) != 1 or len(headers.getlist("origin")) > 1:
        return "invalid_local_host"
    scheme = "https" if scope.get("scheme") in {"https", "wss"} else "http"
    authority = _authority(headers.get("host", ""), scheme)
    server = scope.get("server")
    if authority is None or not server or authority[1] != server[1]:
        return "invalid_local_host"
    client = scope.get("client")
    try:
        if not client or not ipaddress.ip_address(client[0]).is_loopback:
            return "local_clients_only"
    except ValueError:
        return "local_clients_only"
    origin = headers.get("origin")
    if origin is not None:
        try:
            parsed = urlsplit(origin)
            if (parsed.scheme != scheme or parsed.path or parsed.query or parsed.fragment
                    or _authority(parsed.netloc, scheme) != authority):
                return "invalid_local_origin"
        except ValueError:
            return "invalid_local_origin"
    elif scope["type"] == "websocket":
        return "local_origin_required"
    # A same-site but different port is still a different web application.
    if headers.get("sec-fetch-site") not in (None, "none", "same-origin"):
        return "cross_origin_request_denied"
    return None


def _valid_token(value, expected) -> bool:
    return isinstance(value, str) and bool(value) and hmac.compare_digest(value.encode("utf-8"), expected.encode("utf-8"))


class LocalAccessMiddleware:
    def __init__(self, app, *, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        error = local_request_error(scope)
        if scope["type"] == "websocket":
            if error:
                await send({"type": "websocket.close", "code": 1008})
                return
            return await self.app(scope, receive, send)

        headers = Headers(scope=scope)
        path = scope.get("path", "")
        if not error and path == "/api/local-session":
            if scope["method"] != "GET" or headers.get(BOOTSTRAP_HEADER) != "1":
                error = "local_bootstrap_required"
            else:
                response = JSONResponse({"ok": True, "token": self.token}, headers=RESPONSE_HEADERS)
                return await response(scope, receive, send)
        # Some existing GET routes perform protocol request writes or automatic
        # control evaluation. Protect ALL API reads until those are separated.
        if not error and (path == "/api" or path.startswith("/api/")):
            if (len(headers.getlist(TOKEN_HEADER)) != 1
                    or not _valid_token(headers.get(TOKEN_HEADER), self.token)):
                error = "local_token_required"
        if error:
            response = JSONResponse({"ok": False, "error": error}, status_code=403, headers=RESPONSE_HEADERS)
            return await response(scope, receive, send)

        async def protected_send(message):
            if message["type"] == "http.response.start":
                replaced = {key.lower().encode("ascii") for key in RESPONSE_HEADERS}
                outgoing = [(key, value) for key, value in message.get("headers", []) if key.lower() not in replaced]
                outgoing.extend((key.lower().encode("ascii"), value.encode("ascii")) for key, value in RESPONSE_HEADERS.items())
                message = {**message, "headers": outgoing}
            await send(message)

        await self.app(scope, receive, protected_send)


def install_local_access(app):
    token = secrets.token_urlsafe(32)
    app.state.local_request_token = token
    app.add_middleware(LocalAccessMiddleware, token=token)


async def authenticate_websocket(websocket, *, timeout_s: float = 5.0) -> bool:
    """Authenticate in the first frame; never put tokens in URLs or access logs."""
    if local_request_error(websocket.scope):
        await websocket.close(code=1008)
        return False
    await websocket.accept()
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=timeout_s)
        if (not isinstance(message, dict) or message.get("type") != "local-auth"
                or not _valid_token(message.get("token"), websocket.app.state.local_request_token)):
            await websocket.close(code=1008)
            return False
        return True
    except (ValueError, RuntimeError, asyncio.TimeoutError):
        await websocket.close(code=1008)
        return False
    except Exception:
        # A client may disconnect before it sends its authentication frame.
        return False

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from starlette.requests import Request
from app.diagnostics import install, ApiKeyRegistration

class DiagnosticsKeyTests(unittest.TestCase):
    def test_private_session_key_and_origin(self):
        key = "synthetic-key-for-offline-tests-12345"
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            app = FastAPI()
            install(app, lambda: None, lambda: {"devices": []}, Path(directory))
            routes = {r.path: r.endpoint for r in app.routes}
            register = routes["/api/diagnostics/api-key"]
            request = Request({"type":"http", "headers": [(b"host",b"localhost"),(b"origin",b"http://localhost")]})
            bad = Request({"type":"http", "headers": [(b"host",b"localhost")]})
            with patch("app.diagnostics.requests.post") as outbound:
                with self.assertRaises(HTTPException):
                    register(ApiKeyRegistration(api_key=key), bad)
                result = register(ApiKeyRegistration(api_key=key), request)
                self.assertTrue(result["ok"])
                self.assertNotIn(key, str(result))
                self.assertTrue(routes["/api/diagnostics"]()["gemini_configured"])
                with self.assertRaises(HTTPException):
                    register(ApiKeyRegistration(api_key="bad"), request)
                outbound.assert_not_called()
            logs = Path(directory) / "logs"
            logs.mkdir()
            (logs / "server.log").write_text(key, encoding="utf-8")
            self.assertNotIn(key, str(routes["/api/diagnostics/logs"]()))
            second = FastAPI()
            install(second, lambda: None, lambda: {"devices": []}, Path(directory))
            status = next(r.endpoint for r in second.routes if r.path == "/api/diagnostics")
            self.assertFalse(status()["gemini_configured"])

"""Actual runtime worker ownership tests; all HTTP/process operations are pure fakes."""
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from offline_fixtures import guarded_runtime, isolated_runtime
from app.worker_owner import WorkerOwner, WORKER_PROTOCOL

runtime = guarded_runtime()


class FakeProcess:
    pid = 12345

    def __init__(self, dead=False):
        self.dead = dead
        self.actions = []

    def poll(self):
        return 0 if self.dead else None

    def wait(self, timeout):
        self.actions.append("wait")
        if not self.dead:
            raise runtime.subprocess.TimeoutExpired("fake-worker", timeout)
        return 0

    def terminate(self):
        self.actions.append("terminate")
        self.dead = True

    def kill(self):
        self.actions.append("kill")
        self.dead = True


class FakeResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status

    def json(self):
        return self.data


class FakeTransport:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self.sessions = []

    def session(self):
        transport = self

        class Session:
            trust_env = True
            closed = False

            def __enter__(self):
                transport.sessions.append(self)
                return self

            def __exit__(self, *args):
                self.closed = True

            def request(self, method, url, **kwargs):
                if self.trust_env:
                    raise AssertionError("ambient proxy/environment credentials enabled")
                if kwargs.get("allow_redirects") is not False:
                    raise AssertionError("redirects enabled")
                transport.calls.append((method, url, kwargs))
                return transport.handler(method, url, kwargs)

        return Session()


class WorkerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))
        self.enterContext(patch.object(runtime, "node_worker_stdout", None))
        self.enterContext(patch.object(runtime, "node_worker_stderr", None))
        self.owner = WorkerOwner(
            nodes_path=Path(runtime.NODES_FILE).resolve(),
            endpoint=runtime.config_store["opcua_endpoint"], password="synthetic",
            port=39999, token="a" * 64, instance_id="b" * 32, fingerprint="c" * 64,
        )
        self.proc = FakeProcess()
        runtime.node_worker_owner = self.owner
        runtime.node_worker_proc = self.proc
        self.transport = FakeTransport(self.respond)
        self.enterContext(patch.object(runtime.requests, "Session", self.transport.session))
        self.enterContext(patch.object(runtime.requests, "request", side_effect=AssertionError("global HTTP forbidden")))
        self.enterContext(patch.object(runtime.requests, "post", side_effect=AssertionError("global POST forbidden")))
        self.enterContext(patch.object(runtime.subprocess, "Popen", side_effect=AssertionError("spawn forbidden")))

    def identity(self):
        return {"worker_protocol": WORKER_PROTOCOL, "worker_instance_id": self.owner.instance_id,
                "worker_fingerprint": self.owner.fingerprint, "endpoint": self.owner.endpoint,
                "pid": self.proc.pid, "connected": True}

    def respond(self, method, url, kwargs):
        return FakeResponse(self.identity() if url.endswith("/status") else {"ok": True})

    def writes(self):
        return [entry for entry in self.transport.calls if entry[0] != "GET"]

    def test_no_owner_or_dead_child_performs_zero_http(self):
        for owner, proc in ((None, None), (self.owner, None), (None, self.proc), (self.owner, FakeProcess(True))):
            with self.subTest(owner=owner, proc=proc):
                runtime.node_worker_owner, runtime.node_worker_proc = owner, proc
                with self.assertRaises(RuntimeError):
                    runtime._owned_worker_request("POST", "/write", json_body={})
        self.assertEqual(self.transport.calls, [])

    def test_identity_mismatch_performs_zero_writes(self):
        for field, value in (("pid", 999), ("endpoint", "opc.tcp://foreign.invalid:4840"),
                             ("worker_instance_id", "d" * 32), ("worker_fingerprint", "d" * 64)):
            with self.subTest(field=field):
                self.transport.handler = lambda *args, field=field, value=value: FakeResponse({**self.identity(), field: value})
                with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                    runtime._owned_worker_request("POST", "/write", json_body={})
        self.assertEqual(self.writes(), [])

    def test_child_dies_during_status_performs_zero_writes(self):
        def dies(*args):
            self.proc.dead = True
            return FakeResponse(self.identity())
        self.transport.handler = dies
        with self.assertRaises(RuntimeError):
            runtime._owned_worker_request("POST", "/write", json_body={})
        self.assertEqual(self.writes(), [])
        self.assertEqual(len(self.transport.calls), 1)

    def test_owner_or_process_changes_during_status_rejects(self):
        for attribute, replacement in (("node_worker_owner", replace(self.owner)),
                                       ("node_worker_proc", FakeProcess())):
            with self.subTest(attribute=attribute):
                runtime.node_worker_owner, runtime.node_worker_proc = self.owner, self.proc
                def change(*args):
                    setattr(runtime, attribute, replacement)
                    return FakeResponse(self.identity())
                self.transport.handler = change
                with self.assertRaises(RuntimeError):
                    runtime._owned_worker_request("POST", "/write", json_body={})
        self.assertEqual(self.writes(), [])

    def test_owner_changes_during_operation_rejects_result(self):
        def change(method, url, kwargs):
            if not url.endswith("/status"):
                runtime.node_worker_owner = replace(self.owner)
            return self.respond(method, url, kwargs)
        self.transport.handler = change
        with self.assertRaises(RuntimeError):
            runtime._owned_worker_request("POST", "/write", json_body={})
        self.assertEqual(len(self.writes()), 1)

    def test_changed_status_identity_not_published_as_connected_cache(self):
        runtime.config_store["data_source"] = "opcua"
        def change(*args):
            runtime.node_worker_owner = replace(self.owner)
            return FakeResponse(self.identity())
        self.transport.handler = change
        status = runtime._get_worker_status()
        self.assertFalse(status["connected"])
        self.assertNotIn("worker_instance_id", runtime._worker_status_cache)

    def test_changed_data_ownership_does_not_publish_remotes(self):
        def change(method, url, kwargs):
            if url.endswith("/data"):
                runtime.node_worker_owner = replace(self.owner)
                return FakeResponse({"connected": True, "remotes": {"FOREIGN": {"values": {"flow": 123}}}})
            return self.respond(method, url, kwargs)
        self.transport.handler = change
        with patch.object(runtime, "maybe_restart_node_worker", return_value=False):
            result = runtime._fetch_worker_data()
        self.assertIn("error", result)
        self.assertEqual(runtime._worker_remotes_cache, {})

    def test_valid_operation_once_ignores_all_proxy_and_disables_redirects(self):
        with patch.dict(runtime.os.environ, {"ALL_PROXY": "http://proxy.invalid:9", "HTTP_PROXY": "http://proxy.invalid:9", "NO_PROXY": ""}):
            result, _ = runtime._owned_worker_request("POST", "/write", json_body={"nodeId": "fixture", "value": True}, generation=runtime.config_generation_snapshot())
        self.assertTrue(result["ok"])
        self.assertEqual([entry[0] for entry in self.transport.calls], ["GET", "POST"])
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(len(self.transport.sessions), 2)
        self.assertTrue(all(session.closed and not session.trust_env for session in self.transport.sessions))
        for _, url, kwargs in self.transport.calls:
            self.assertTrue(url.startswith(self.owner.base_url + "/"))
            self.assertEqual(kwargs["headers"], self.owner.headers())
            self.assertIs(kwargs["allow_redirects"], False)

    def test_redirect_status_performs_zero_writes(self):
        self.transport.handler = lambda *args: FakeResponse({}, 302)
        with self.assertRaisesRegex(RuntimeError, "HTTP 302"):
            runtime._owned_worker_request("POST", "/write", json_body={})
        self.assertEqual(self.writes(), [])

    def test_foreign_shutdown_without_owned_live_child_performs_zero_http(self):
        for owner, proc in ((None, None), (self.owner, None), (self.owner, FakeProcess(True)), (None, FakeProcess())):
            with self.subTest(owner=owner, proc=proc):
                runtime.node_worker_owner, runtime.node_worker_proc = owner, proc
                runtime.stop_node_worker(timeout_s=0.01)
        self.assertEqual(self.transport.calls, [])

    def test_foreign_status_blocks_shutdown_and_terminates_only_handle(self):
        self.transport.handler = lambda *args: FakeResponse({**self.identity(), "pid": 999})
        runtime.stop_node_worker(timeout_s=0.01)
        self.assertEqual(self.writes(), [])
        self.assertEqual(len(self.transport.calls), 1)
        self.assertIn("terminate", self.proc.actions)
        self.assertIsNone(runtime.node_worker_proc)
        self.assertIsNone(runtime.node_worker_owner)

    def test_replacement_between_fetch_failure_and_restart_is_untouched(self):
        actual_restart = runtime.maybe_restart_node_worker
        replacement_owner = replace(self.owner)
        replacement_proc = FakeProcess()

        def replace_before_restart(reason, *, expected_owner, expected_proc):
            self.assertIs(expected_owner, self.owner)
            self.assertIs(expected_proc, self.proc)
            runtime.node_worker_owner = replacement_owner
            runtime.node_worker_proc = replacement_proc
            return actual_restart(reason, expected_owner=expected_owner, expected_proc=expected_proc)

        with patch.object(runtime, "_worker_last_restart_attempt", 0.0), \
                patch.object(runtime, "_worker_last_fetch", 0.0), \
                patch.object(runtime, "_owned_worker_request", side_effect=RuntimeError("fake failure")), \
                patch.object(runtime, "maybe_restart_node_worker", side_effect=replace_before_restart) as restart, \
                patch.object(runtime, "_stop_node_worker_locked") as stop, \
                patch.object(runtime, "_start_node_worker_locked") as start:
            result = runtime._fetch_worker_data()
            self.assertIn("worker_unreachable", result["error"])
            restart.assert_called_once()
            stop.assert_not_called()
            start.assert_not_called()
            self.assertEqual(runtime._worker_last_restart_attempt, 0.0)
        self.assertIs(runtime.node_worker_owner, replacement_owner)
        self.assertIs(runtime.node_worker_proc, replacement_proc)
        self.assertEqual(replacement_proc.actions, [])
        self.assertEqual(self.transport.calls, [])

    def test_same_owner_restart_is_admitted_once_then_throttled(self):
        def assert_lifecycle_locks():
            self.assertTrue(runtime.worker_status_lock.locked())
            self.assertTrue(runtime.node_worker_lock._is_owned())

        with patch.object(runtime, "_worker_last_restart_attempt", 0.0), \
                patch.object(runtime.time, "time", return_value=1000.0), \
                patch.object(runtime, "_stop_node_worker_locked", side_effect=assert_lifecycle_locks) as stop, \
                patch.object(runtime, "_start_node_worker_locked", side_effect=assert_lifecycle_locks) as start:
            self.assertTrue(runtime.maybe_restart_node_worker(
                "fake failure", expected_owner=self.owner, expected_proc=self.proc))
            self.assertFalse(runtime.maybe_restart_node_worker(
                "same failure", expected_owner=self.owner, expected_proc=self.proc))
            stop.assert_called_once()
            start.assert_called_once()
            self.assertEqual(runtime._worker_last_restart_attempt, 1000.0)
        self.assertEqual(self.transport.calls, [])

    def test_owned_shutdown_validates_status_then_posts_once(self):
        def shutdown(method, url, kwargs):
            response = self.respond(method, url, kwargs)
            if url.endswith("/shutdown"):
                self.proc.dead = True
            return response
        self.transport.handler = shutdown
        runtime.stop_node_worker(timeout_s=0.01)
        self.assertEqual([(method, url.rsplit("/", 1)[-1]) for method, url, _ in self.transport.calls], [("GET", "status"), ("POST", "shutdown")])
        self.assertNotIn("terminate", self.proc.actions)
        self.assertIsNone(runtime.node_worker_owner)

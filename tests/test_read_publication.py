"""Read publication barriers, using the actual runtime and fake transports only."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import Mock, patch

from offline_fixtures import guarded_runtime, isolated_runtime
from app.device_hub import DeviceHub, DeviceHealth, DeviceSnapshot

runtime = guarded_runtime()


class ReadPublicationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))
        self.enterContext(patch.object(runtime, "_worker_cache_token", None))
        self.enterContext(patch.object(runtime, "_modbus_live_generation", None))

    def test_obsolete_hub_success_and_failure_never_publish(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                registry = runtime.get_device_hub().registry
                profile = registry.require("AMS01")
                adapter = Mock()
                entered, release = threading.Event(), threading.Event()

                def read(_profile):
                    entered.set()
                    if not release.wait(3):
                        raise AssertionError("read release timed out")
                    if fail:
                        raise RuntimeError("old transport failed")
                    return DeviceSnapshot(profile.device_id, profile.transport, True,
                                          {"flow": 123}, DeviceHealth(connected=True))

                adapter.read_telemetry.side_effect = read
                hub = DeviceHub(registry, {profile.transport: adapter},
                                publication_guard=runtime._hub_publication_guard(runtime.current_config_generation()))
                with patch.object(runtime, "save_config") as save, patch.object(runtime, "save_runtime_state") as state, ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(hub.read_device, "AMS01")
                    try:
                        self.assertTrue(entered.wait(2))
                        generation = runtime.current_config_generation()
                        # Each branch must really publish a different generation;
                        # reusing one endpoint made the failure branch a no-op.
                        replacement = f"replacement-{int(fail)}.invalid"
                        published = runtime.update_config_values(modbus_host=replacement)
                        self.assertEqual(published["modbus_host"], replacement)
                        self.assertEqual(runtime.current_config_generation(), generation + 1)
                        save.assert_called_once()
                        state.assert_not_called()
                    finally:
                        release.set()
                    result = pending.result(timeout=3)
                adapter.read_telemetry.assert_called_once_with(profile)
                self.assertFalse(result["device_connected"])
                self.assertIn("obsolete hub configuration generation", result["error"])
                self.assertEqual(hub._snapshots, {})
                self.assertEqual(hub.cached("AMS01"), {})
                before = adapter.read_telemetry.call_count
                self.assertFalse(hub.read_device("AMS01")["device_connected"])
                self.assertEqual(adapter.read_telemetry.call_count, before)

    def test_current_hub_publishes_and_cached_rejects_later_generation(self):
        registry = runtime.get_device_hub().registry
        profile = registry.require("AMS01")
        adapter = Mock()
        adapter.read_telemetry.return_value = DeviceSnapshot("AMS01", profile.transport, True,
                                                           {"flow": 12}, DeviceHealth(connected=True))
        hub = DeviceHub(registry, {profile.transport: adapter},
                        publication_guard=runtime._hub_publication_guard(runtime.current_config_generation()))
        self.assertEqual(hub.read_device("AMS01")["flow"], 12)
        self.assertEqual(hub.cached("AMS01")["flow"], 12)
        with patch.object(runtime, "save_config"), patch.object(runtime, "save_runtime_state"):
            runtime.update_config_values(modbus_host="replacement.invalid")
        self.assertEqual(hub.cached("AMS01"), {})
        self.assertEqual(hub.cached()["devices"], [])

    def test_worker_owner_rotation_after_transport_before_parse_publication(self):
        owner, replacement = object(), object()
        proc = Mock()
        proc.poll.return_value = None
        response = {"connected": True, "remotes": {"AMS01": {"values": {"flow": 1}}}}

        def parse(*args):
            with runtime.node_worker_lock:
                runtime.node_worker_owner = replacement
                with runtime.worker_cache_lock:
                    runtime._worker_remotes_cache = {"NEW": {"sentinel": True}}
            return {"flow": 123}

        with patch.object(runtime, "node_worker_owner", owner), patch.object(runtime, "node_worker_proc", proc), \
                patch.object(runtime, "_worker_last_fetch", 0), \
                patch.object(runtime, "_owned_worker_request", return_value=(response, None)), \
                patch.object(runtime, "parse_remote_opcua_values", side_effect=parse):
            result = runtime._fetch_worker_data_locked()
            self.assertIn("obsolete", result["error"])
            self.assertEqual(runtime._worker_remotes_cache, {"NEW": {"sentinel": True}})
            self.assertEqual(runtime._worker_last_fetch, 0)

    def test_worker_failed_old_request_cannot_invalidate_replacement_cache(self):
        owner, replacement = object(), object()
        proc = Mock()
        proc.poll.return_value = None

        def request(*args, **kwargs):
            with runtime.node_worker_lock:
                runtime.node_worker_owner = replacement
                with runtime.worker_cache_lock:
                    runtime._worker_remotes_cache = {"NEW": {"device_connected": True}}
            raise RuntimeError("old transport failed")

        with patch.object(runtime, "node_worker_owner", owner), patch.object(runtime, "node_worker_proc", proc), \
                patch.object(runtime, "_worker_last_fetch", 0), \
                patch.object(runtime, "_owned_worker_request", side_effect=request), \
                patch.object(runtime, "maybe_restart_node_worker") as restart:
            self.assertIn("obsolete", runtime._fetch_worker_data_locked()["error"])
            self.assertEqual(runtime._worker_remotes_cache, {"NEW": {"device_connected": True}})
            restart.assert_not_called()

    def test_worker_same_owner_publishes_and_owner_change_rejects_cache_hit(self):
        owner, replacement = object(), object()
        proc = Mock()
        proc.poll.return_value = None
        response = {"connected": False, "remotes": {"AMS01": {"last_error": "no_data"}}}
        with patch.object(runtime, "node_worker_owner", owner), patch.object(runtime, "node_worker_proc", proc), \
                patch.object(runtime, "_worker_last_fetch", 0), \
                patch.object(runtime, "_owned_worker_request", return_value=(response, None)):
            self.assertEqual(runtime._fetch_worker_data_locked(), response)
            self.assertEqual(runtime._get_cached_remote("AMS01")["error"], "no_data")
            with runtime.node_worker_lock:
                runtime.node_worker_owner = replacement
            self.assertEqual(runtime._get_cached_remotes_snapshot(), {})

    def test_modbus_cache_generation_mismatch_is_not_a_hit(self):
        with patch.object(runtime, "_modbus_live_cache", {"AMS01": {"sentinel": "old"}}), \
                patch.object(runtime, "_modbus_live_at", runtime.time.time()), \
                patch.object(runtime, "_modbus_live_generation", runtime.current_config_generation() - 1), \
                patch.object(runtime, "_enabled_modbus_profiles", return_value={}), \
                patch.object(runtime._modbus_client_pool, "get") as transport:
            self.assertEqual(runtime.fetch_modbus_remotes(), {})
            transport.assert_not_called()
            self.assertEqual(runtime._modbus_live_generation, runtime.current_config_generation())

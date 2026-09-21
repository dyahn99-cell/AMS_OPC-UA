"""Bootstrap and lifespan tests; run only via scripts/check_offline.py."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace
from app.control_coordinator import ControlCoordinator
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from offline_fixtures import guarded_runtime, isolated_runtime, synthetic_config, synthetic_nodes

runtime = guarded_runtime()


def complete_without_loop(awaitable):
    """These mocked coroutines must finish without creating an event loop/socket."""
    iterator = awaitable.__await__()
    try:
        next(iterator)
    except StopIteration as result:
        return result.value
    finally:
        iterator.close()
    raise AssertionError("unexpected asynchronous suspension")


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(isolated_runtime(runtime))
        for name in ("BASE_DIR", "BUNDLE_DIR", "ASSETS_DIR", "CONFIG_FILE", "RUNTIME_STATE_FILE",
                     "NODES_FILE", "DB_DIR", "LOG_DIR", "IODD_DIR", "IODD_INDEX_FILE", "SCHEDULE_FILE"):
            self.stack.enter_context(patch.object(runtime, name, getattr(runtime, name)))
        self.stack.enter_context(patch.object(runtime, "_assets_app", Mock()))

    def test_supplied_inputs_no_persistence_and_stable_config_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "not-created"
            config, nodes = synthetic_config(), synthetic_nodes()
            config["server_port"] = 8765
            reference = runtime.config_store
            adapter = object()
            with patch.object(runtime, "load_config", side_effect=AssertionError("disk config read")), \
                 patch.object(runtime, "load_node_config", side_effect=AssertionError("disk node read")), \
                 patch.object(runtime, "_atomic_write_json", side_effect=AssertionError("write")), \
                 patch.object(runtime, "start_node_worker", side_effect=AssertionError("worker start")):
                runtime.initialize_runtime(base_dir=base, config=config, node_config=nodes,
                                           adapters={"demo": adapter}, persist=False)
            self.assertIs(runtime.config_store, reference)
            self.assertEqual(reference["server_port"], 8765)
            self.assertFalse(base.exists())
            self.assertEqual(runtime.BUNDLE_DIR, base)
            self.assertEqual(runtime._assets_app.all_directories, [str(base / "assets")])
            self.assertEqual(runtime.REMOTE_NODE_MAPS, runtime._read_node_maps(nodes))
            self.assertIs(runtime._runtime_adapters_override["demo"], adapter)
            nodes["remotes"]["AMS00"]["read"]["flow"] = "changed"
            config["modbus_gateways"].clear()
            self.assertNotEqual(runtime.AMS00_NODES["flow"], "changed")
            self.assertTrue(reference["modbus_gateways"])
            runtime.initialize_runtime()
            with self.assertRaises(RuntimeError):
                runtime.initialize_runtime(config={})

    def test_persisted_measurement_identity_rotates_on_node_change_after_restart(self):
        import copy
        with tempfile.TemporaryDirectory() as directory:
            cfg = synthetic_config()
            cfg.update(data_source="opcua", device_profiles={"AMS00": {"transport": "opcua"}},
                       device_profiles_explicit=True)
            nodes = synthetic_nodes()
            runtime.initialize_runtime(base_dir=directory, config=cfg, node_config=nodes, persist=True)
            source = runtime.config_store["measurement_sources"]["AMS00"]
            epoch = (runtime.config_store.get("measurement_epochs") or {}).get("AMS00", "initial")
            runtime._runtime_initialized = False
            nodes["remotes"]["AMS00"]["read"]["flow"] = "ns=2;s=synthetic-replacement-flow"
            runtime.initialize_runtime(base_dir=directory, node_config=nodes, persist=True)
            self.assertNotEqual(runtime.config_store["measurement_sources"]["AMS00"], source)
            self.assertNotEqual(runtime.config_store["measurement_epochs"]["AMS00"], epoch)
            changed_epoch = runtime.config_store["measurement_epochs"]["AMS00"]
            runtime._runtime_initialized = False
            runtime.initialize_runtime(base_dir=directory, node_config=nodes, persist=True)
            self.assertEqual(runtime.config_store["measurement_epochs"]["AMS00"], changed_epoch)

    def test_bootstrap_rejects_active_command(self):
        with runtime._command_generation():
            with self.assertRaises((RuntimeError, ValueError)):
                runtime.initialize_runtime(config=synthetic_config(), node_config=synthetic_nodes(), persist=False)
        self.assertFalse(runtime._runtime_initialized)

    def exercise_real_lifespan_drain(self, *, startup_failure=False):
        events = []
        collecting, release_collect = threading.Event(), threading.Event()
        commanding, release_command = threading.Event(), threading.Event()
        closed, joining = threading.Event(), threading.Event()
        admission = runtime._configuration_admission
        original_close = admission.close
        coordinators = []

        def collect():
            collecting.set()
            if not release_collect.wait(4):
                raise AssertionError('collection never released')
            events.append('collection finished')
            return {'devices': []}

        def command():
            with runtime._command_generation():
                commanding.set()
                if not release_command.wait(4):
                    raise AssertionError('command never released')
                with runtime._command_generation():
                    events.append('command finished')

        def close():
            events.append('admission closed')
            original_close()
            closed.set()

        class Coordinator(ControlCoordinator):
            def __init__(self, *args):
                super().__init__(*args)
                coordinators.append(self)

            def request_stop(self):
                events.append('coordinator stopped')
                super().request_stop()

        scheduler = Mock()
        scheduler.pause.side_effect = lambda: events.append('scheduler paused')
        scheduler.shutdown.side_effect = lambda **kw: events.append('scheduler stopped')
        operations = []
        def scheduler_start():
            operations.append(pool.submit(command))
            if not commanding.wait(2) or not collecting.wait(2):
                raise AssertionError('runtime work did not start')
            if startup_failure:
                raise RuntimeError('synthetic partial startup')
        scheduler.start.side_effect = scheduler_start
        hub = Mock()
        hub.registry.all.return_value = [SimpleNamespace(transport='opcua')]

        def stop_worker():
            self.assertTrue(runtime._runtime_live)
            self.assertIn('collection finished', events)
            self.assertIn('command finished', events)
            events.append('worker released')

        with ThreadPoolExecutor(max_workers=3) as pool:
            class ExecutorThread:
                def __init__(self, *, target, **kwargs):
                    self.target = target

                def start(self):
                    self.future = pool.submit(self.target)

                def join(self):
                    joining.set()
                    self.future.result(timeout=3)

            with patch('app.control_coordinator.threading', SimpleNamespace(Thread=ExecutorThread, Event=threading.Event)), \
                 patch('app.control_coordinator.ControlCoordinator', Coordinator), \
                 patch.object(runtime, 'initialize_runtime'), \
                 patch.object(runtime, 'get_device_hub', return_value=hub), \
                 patch.object(runtime, '_collect_control_cycle', collect), \
                 patch.object(runtime, '_save_collected_snapshot') as save, \
                 patch.object(runtime, 'AsyncIOScheduler', return_value=scheduler), \
                 patch.object(runtime, 'start_node_worker', side_effect=lambda: events.append('worker started')), \
                 patch.object(runtime, 'stop_node_worker', side_effect=stop_worker) as stop, \
                 patch.object(admission, 'close', side_effect=close):
                context = runtime.lifespan(runtime.app)
                try:
                    if startup_failure:
                        ending = pool.submit(complete_without_loop, context.__aenter__())
                    else:
                        complete_without_loop(context.__aenter__())
                        self.assertTrue(collecting.wait(2))
                        overlapping = runtime.lifespan(runtime.app)
                        with self.assertRaisesRegex(RuntimeError, 'active lifespan'):
                            complete_without_loop(overlapping.__aenter__())
                        self.assertTrue(runtime._runtime_live)
                        self.assertEqual(len(coordinators), 1)
                        ending = pool.submit(complete_without_loop, context.__aexit__(None, None, None))
                    self.assertTrue(closed.wait(2))
                    self.assertTrue(joining.wait(2))
                    self.assertLess(events.index('coordinator stopped'), events.index('admission closed'))
                    if not startup_failure:
                        self.assertLess(events.index('scheduler stopped'), events.index('admission closed'))
                    with self.assertRaises(ValueError):
                        with runtime._command_generation():
                            self.fail('new command admitted')
                    with self.assertRaises(ValueError):
                        with admission.transition():
                            self.fail('new transition admitted')
                    self.assertFalse(ending.done())
                    stop.assert_not_called()
                    self.assertTrue(runtime._runtime_live)
                    release_collect.set()
                    coordinators[0]._thread.future.result(timeout=2)
                    self.assertFalse(ending.done(), 'active command must still drain')
                    stop.assert_not_called()
                    self.assertTrue(runtime._runtime_live)
                finally:
                    release_collect.set()
                    release_command.set()
                operations[0].result(timeout=2)
                if startup_failure:
                    with self.assertRaisesRegex(RuntimeError, 'synthetic partial startup'):
                        ending.result(timeout=2)
                else:
                    ending.result(timeout=2)
                stop.assert_called_once_with()
                save.assert_not_called()
                self.assertFalse(runtime._runtime_live)
                self.assertEqual(events[-1], 'worker released')

    def test_actual_lifespan_stops_submission_closes_admission_and_drains(self):
        self.exercise_real_lifespan_drain()

    def test_actual_partial_startup_drains_started_coordinator_and_command(self):
        self.exercise_real_lifespan_drain(startup_failure=True)

    def test_lifespan_partial_startup_cleans_task_and_worker(self):
        class Task:
            cancelled = False

            def cancel(self):
                self.cancelled = True

            def __await__(self):
                if False:
                    yield
                raise asyncio.CancelledError()

        task = Task()
        def create_task(coroutine):
            coroutine.close()
            return task

        scheduler = Mock()
        scheduler.start.side_effect = RuntimeError("synthetic startup failure")
        hub = Mock()
        hub.registry.all.return_value = []
        with patch.object(runtime, "initialize_runtime"), \
             patch.object(runtime, "get_device_hub", return_value=hub), \
             patch("app.control_coordinator.ControlCoordinator") as coordinator, \
             patch.object(runtime, "AsyncIOScheduler", return_value=scheduler), \
             patch.object(runtime, "stop_node_worker") as stop:
            context = runtime.lifespan(runtime.app)
            with self.assertRaisesRegex(RuntimeError, "synthetic startup failure"):
                complete_without_loop(context.__aenter__())
        coordinator.return_value.request_stop.assert_called_once_with()
        coordinator.return_value.join.assert_called_once_with()
        stop.assert_called_once_with()
        self.assertFalse(runtime._runtime_live)

    def test_lifespan_body_failure_cleans_scheduler(self):
        class Task:
            def cancel(self):
                pass

            def __await__(self):
                if False:
                    yield
                raise asyncio.CancelledError()

        def create_task(coroutine):
            coroutine.close()
            return Task()

        scheduler, hub = Mock(), Mock()
        hub.registry.all.return_value = []
        with patch.object(runtime, "initialize_runtime"), \
             patch.object(runtime, "get_device_hub", return_value=hub), \
             patch("app.control_coordinator.ControlCoordinator") as coordinator, \
             patch.object(runtime, "AsyncIOScheduler", return_value=scheduler), \
             patch.object(runtime, "stop_node_worker") as stop:
            context = runtime.lifespan(runtime.app)
            complete_without_loop(context.__aenter__())
            failure = RuntimeError("body failure")
            self.assertFalse(complete_without_loop(context.__aexit__(RuntimeError, failure, None)))
        stop.assert_called_once_with()
        scheduler.shutdown.assert_called_once_with(wait=False)
        self.assertFalse(runtime._runtime_live)

"""Offline lifecycle contracts; run with the protected runner."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import Mock, patch

from app.config_transaction import ConfigurationAdmission
from app.control_coordinator import ControlCoordinator


class CoordinatorTests(unittest.TestCase):
    def test_saving_consumes_collected_payload_on_separate_cadence(self):
        payload = {"devices": [{"sample_id": "synthetic"}]}
        collect = Mock(return_value=payload)
        save = Mock()
        coordinator = ControlCoordinator(collect, save, lambda: 2.0)
        stop = Mock()
        stop.is_set.side_effect = [False, False, False, False, True]
        coordinator._stop = stop
        with patch("app.control_coordinator.time.monotonic", side_effect=[0, 0, 1, 1, 2, 3, 3, 3]):
            coordinator._run()
        self.assertEqual(collect.call_count, 2)
        save.assert_called_once_with(payload)

    def test_stop_during_collection_prevents_new_save(self):
        save = Mock()
        coordinator = ControlCoordinator(None, save, lambda: 0)

        def collect():
            coordinator.request_stop()
            return {"devices": []}

        coordinator.collect = collect
        coordinator._run()
        save.assert_not_called()

    def test_join_waits_for_blocked_collection_after_stop(self):
        entered = threading.Event()
        release = threading.Event()
        join_entered = threading.Event()
        joined = threading.Event()
        save = Mock()

        def collect():
            entered.set()
            if not release.wait(3):
                raise AssertionError("collector not released")
            return {"devices": []}

        coordinator = ControlCoordinator(collect, save, lambda: 0)
        with ThreadPoolExecutor(max_workers=2) as executor:
            class ExecutorThread:
                def __init__(self, *, target, **kwargs):
                    self.target = target

                def start(self):
                    self.future = executor.submit(self.target)

                def join(self):
                    join_entered.set()
                    self.future.result(timeout=2)

            def stop_and_join():
                coordinator.request_stop()
                coordinator.join()
                joined.set()

            thread_api = Mock(Thread=ExecutorThread)
            with patch("app.control_coordinator.threading", thread_api):
                coordinator.start()
            try:
                self.assertTrue(entered.wait(2))
                stopping = executor.submit(stop_and_join)
                self.assertTrue(join_entered.wait(2))
                self.assertFalse(joined.wait(0.05))
            finally:
                release.set()
            stopping.result(timeout=2)
        self.assertTrue(joined.is_set())
        save.assert_not_called()

    def test_closed_admission_drains_actual_work_and_allows_nested_completion(self):
        admission = ConfigurationAdmission()
        started = threading.Event()
        release = threading.Event()
        drained = threading.Event()

        def operation():
            with admission.command(lambda: {"generation": 1}):
                started.set()
                if not release.wait(3):
                    raise AssertionError("operation not released")
                with admission.command(lambda: {"generation": 2}) as nested:
                    self.assertEqual(nested["generation"], 1)

        def drain():
            admission.drain()
            drained.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            running = executor.submit(operation)
            try:
                self.assertTrue(started.wait(2))
                admission.close()
                with self.assertRaises(ValueError):
                    with admission.command(lambda: {}):
                        pass
                with self.assertRaises(ValueError):
                    with admission.transition():
                        pass
                waiting = executor.submit(drain)
                self.assertFalse(drained.wait(0.05))
            finally:
                release.set()
            running.result(timeout=2)
            waiting.result(timeout=2)
        self.assertTrue(drained.is_set())
        admission.reopen()
        with admission.command(lambda: {"generation": 2}) as current:
            self.assertEqual(current["generation"], 2)

"""Actual runtime configuration admission regressions; all persistence is mocked."""
import copy
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch

from offline_fixtures import guarded_runtime, isolated_runtime
from app.config_transaction import ConfigurationAdmission

runtime = guarded_runtime()


class ConfigurationAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))
        self.enterContext(patch.object(runtime, "_configuration_admission", ConfigurationAdmission()))
        self.enterContext(patch.object(runtime, "_config_generation", 0))

    def test_save_failure_preserves_memory_and_generation(self):
        before = copy.deepcopy(runtime.config_store)
        with patch.object(runtime, "save_config", side_effect=OSError("disk full")), patch.object(runtime, "save_runtime_state"):
            with self.assertRaises(OSError):
                runtime.update_config_values(ams_host="https://replacement.invalid")
        self.assertEqual(runtime.config_store, before)
        self.assertEqual(runtime.current_config_generation(), 0)
        with runtime._command_generation():
            pass  # Failed publication reopens admission.

    def test_transition_rejects_new_admission_and_drains_before_publish(self):
        admitted = threading.Event()
        release = threading.Event()
        published = threading.Event()
        failures = []
        old = runtime.get_ams_host()

        def command():
            try:
                with runtime._command_generation():
                    admitted.set()
                    if not release.wait(3):
                        raise AssertionError("command release timed out")
                    self.assertEqual(runtime.get_ams_host(), old)
            except BaseException as exc:
                failures.append(exc)

        def update():
            try:
                runtime.update_config_values(ams_host="https://replacement.invalid")
                published.set()
            except BaseException as exc:
                failures.append(exc)

        admission = runtime._configuration_admission
        with patch.object(runtime, "save_config"), patch.object(runtime, "save_runtime_state"), ThreadPoolExecutor(max_workers=2) as pool:
            reader = pool.submit(command)
            writer = None
            try:
                self.assertTrue(admitted.wait(3))
                writer = pool.submit(update)
                # Verify that the drain releases the condition lock.
                with admission._condition:
                    # Writer may not yet have marked the transition. Release
                    # the condition briefly through timed waits until it has.
                    for _ in range(100):
                        if admission._transitioning:
                            break
                        admission._condition.wait(.01)
                    self.assertTrue(admission._transitioning)
                with self.assertRaises(ValueError):
                    with runtime._command_generation():
                        self.fail("admitted a new command during transition")
                self.assertFalse(published.is_set())
                self.assertEqual(runtime.config_store["ams_host"], old)
            finally:
                release.set()
                reader.result(timeout=3)
                if writer is not None:
                    writer.result(timeout=3)
            self.assertTrue(reader.done())
            self.assertTrue(writer.done())
            self.assertEqual(failures, [])
            self.assertTrue(published.is_set())
            self.assertEqual(runtime.current_config_generation(), 1)

    def test_nested_simulator_state_update_does_not_drain_own_lease(self):
        with patch.object(runtime, "save_config"), patch.object(runtime, "save_runtime_state"):
            with runtime._command_generation():
                first = runtime._configuration_admission.current()
                with runtime._command_generation():
                    self.assertIs(runtime._configuration_admission.current(), first)
                    runtime.update_config_values(force_mode="02")
                self.assertEqual(runtime.current_config_generation(), 0)
                with self.assertRaises(ValueError):
                    runtime.update_config_values(ams_host="https://replacement.invalid")
        self.assertEqual(runtime.config_store["force_mode"], "02")

    def test_bootstrap_rejects_live_lease_and_reopens_after_failure(self):
        admission = runtime._configuration_admission
        with runtime._command_generation():
            with self.assertRaises(ValueError):
                with admission.bootstrap():
                    self.fail("bootstrap entered during a command")
        with self.assertRaises(RuntimeError):
            with admission.bootstrap():
                with self.assertRaises(ValueError):
                    with runtime._command_generation():
                        self.fail("command admitted during bootstrap")
                raise RuntimeError("initialization failed")
        with runtime._command_generation():
            pass

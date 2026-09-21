"""Stage5 synthetic-clock tests of real schedule handlers (no server or device)."""
import copy
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from offline_fixtures import guarded_runtime, isolated_runtime
from app.schedule_execution import ScheduleExecution


class Clock(datetime):
    current = datetime(2026, 9, 7, 23, 30)

    @classmethod
    def now(cls, tz=None):
        return cls.current


class ScheduleHandlerTests(unittest.TestCase):
    def setUp(self):
        self.r = guarded_runtime()
        context = isolated_runtime(self.r)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        r = self.r
        self.definitions = [{"id": "s1", "name": "fixture", "remote_id": "AMS01", "mode": 2,
            "start_time": "23:00", "end_time": "01:00", "repeat": "daily", "days": ["MON"], "active": False}]
        for name, value in (("schedules_store", self.definitions), ("_schedule_execution", ScheduleExecution()),
                            ("datetime", Clock), ("save_schedules", lambda: None)):
            p = patch.object(r, name, value)
            p.start()
            self.addCleanup(p.stop)
        Clock.current = datetime(2026, 9, 7, 23, 30)
        self.targets = ["AMS01"]
        hub = SimpleNamespace(registry=SimpleNamespace(targets=lambda target: [SimpleNamespace(device_id=d) for d in self.targets]))
        for name, value in (("get_device_hub", lambda: hub), ("_schedule_target", lambda target: target)):
            p = patch.object(r, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.calls = []
        self.fail = set()
        def action(run, entry, persist=None, *, restoring=False):
            self.calls.append((entry["device_id"], restoring))
            if restoring:
                return {"ok": True}
            if entry["device_id"] in self.fail:
                entry["state"] = "FAILED"
                return {"ok": False, "error": "fake failure"}
            entry.update(state="APPLYING", return_mode=1)
            persist()
            entry.update(state="APPLIED", owned=True)
            return {"ok": True}
        self.real_action = r._schedule_device_action
        p = patch.object(r, "_schedule_device_action", action)
        p.start()
        self.addCleanup(p.stop)

    def test_inactive_manual_stops_across_midnight(self):
        self.assertTrue(self.r.execute_schedule("s1")["ok"])
        self.assertFalse(self.definitions[0]["active"])
        Clock.current = datetime(2026, 9, 8, 1, 0)
        self.r.check_schedules()
        self.assertEqual(self.calls, [("AMS01", False), ("AMS01", True)])

    def test_partial_preserves_successful_restore(self):
        self.targets[:] = ["AMS01", "AMS02"]
        self.fail.add("AMS02")
        result = self.r.execute_schedule("s1")
        self.assertTrue(result["partial"])
        self.assertEqual(result["run"]["state"], "PARTIAL")
        self.r.stop_schedule("s1")
        self.assertEqual(self.calls[-1], ("AMS01", True))
        self.assertNotIn(("AMS02", True), self.calls)

    def test_duplicates_and_running_mutations(self):
        self.definitions[0]["active"] = True
        self.r.check_schedules()
        self.r.check_schedules()
        self.r.execute_schedule("s1")
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.r.delete_schedule("s1")["ok"])
        self.assertFalse(self.r.toggle_schedule("s1")["ok"])

    def test_restart_never_replays(self):
        self.r.execute_schedule("s1")
        persisted = copy.deepcopy(self.definitions)
        self.r._schedule_execution.load(persisted)
        self.r._schedule_execution.publish(self.definitions)
        self.assertEqual(self.r.get_schedules()[0]["run"]["state"], "RECOVERY_REQUIRED")
        self.assertTrue(self.r.stop_schedule("s1")["recovery_required"])
        Clock.current = datetime(2026, 9, 8, 2, 0)
        self.r.check_schedules()
        self.assertEqual(len(self.calls), 1)

    def test_occurrence_weekday_is_start_day(self):
        self.definitions[0]["active"] = True
        Clock.current = datetime(2026, 9, 8, 0, 30)
        self.r.check_schedules()
        self.assertEqual(len(self.calls), 1)
        self.r.stop_schedule("s1")
        self.r.check_schedules()
        self.assertEqual(len(self.calls), 2)

    def real_action_context(self, mode=2):
        r = self.r
        profile = SimpleNamespace(device_id="AMS01", transport="modbus", endpoint="fixture.invalid")
        hub = SimpleNamespace(registry=SimpleNamespace(require=lambda target: profile),
                              cached=lambda target: {"source_key": "fixture-source"})
        target = SimpleNamespace(transport="modbus", endpoint="fixture.invalid", channel=1,
                                 unit_id=1, mapping={"control": 4}, encoding={})
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(r, "get_device_hub", return_value=hub))
        stack.enter_context(patch.object(r, "_resolve_command_target", return_value=target))
        stack.enter_context(patch.object(r, "_hub_current_mode", return_value=1))
        return stack, profile, {"mode": mode}, {"device_id": "AMS01"}

    def test_unknown_standby_output_zero_writes(self):
        stack, profile, run, entry = self.real_action_context(8)
        with stack, patch.object(self.r, "_run_schedule_hub_command") as command:
            result = self.real_action(run, entry, lambda: None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "schedule_restore_unavailable")
        command.assert_not_called()

    def test_failed_manual_attempt_invalidates_restore(self):
        r = self.r
        stack, profile, run, entry = self.real_action_context()
        def command(device, mode):
            r._automatic_command_gate(profile, "mode")
            return {"ok": True}
        with stack, patch.object(r, "_run_schedule_hub_command", side_effect=command) as write, patch.object(r, "_dio_link_configs", return_value={"AMS01": {"enabled": False}}):
            self.assertTrue(self.real_action(run, entry, lambda: None)["ok"])
            r._automatic_command_gate(profile, "mode")  # admitted failed/uncertain manual attempt
            result = self.real_action(run, entry, restoring=True)
            self.assertTrue(result["superseded"])
            self.assertEqual(write.call_count, 1)

    def test_intent_persistence_precedes_write(self):
        stack, profile, run, entry = self.real_action_context()
        with stack, patch.object(self.r, "_run_schedule_hub_command") as command:
            with self.assertRaises(OSError):
                self.real_action(run, entry, lambda: (_ for _ in ()).throw(OSError("full")))
            command.assert_not_called()

    def test_settings_written_but_readback_not_confirmed(self):
        r = self.r
        for readback in (None, 101, OSError("read failed"), 100):
            with self.subTest(readback=readback), patch.object(r, "_exa1_service", side_effect=[None, readback]):
                result = r.write_modbus_exa1_settings("AMS01", {"operation_kpa": 100})
                self.assertTrue(result["applied"])
                self.assertEqual(result["written"], ["operation_kpa"])
                self.assertEqual(result["verified"], readback == 100)
                self.assertEqual(result["ok"], readback == 100)
                if readback != 100:
                    self.assertIn(result["outcome"], ("unverified", "verification_failed"))

    def test_persist_failure_before_output(self):
        with patch.object(self.r, "save_schedules", side_effect=OSError("full")):
            result = self.r.execute_schedule("s1")
        self.assertFalse(result["ok"])
        self.assertEqual(self.calls, [])
        self.assertTrue(result["recovery_required"])

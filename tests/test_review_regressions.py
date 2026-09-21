import copy
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.output_sequence import execute_output_sequence
from app.schedule_execution import ScheduleExecution
from app.exw1_topology import load_exw1_topology
from app.device_hub import DeviceProfile, DeviceHub, DeviceRegistry
from app.hub_adapters import HubAdapterBase
from app.connection_context import ConnectionContextManager
from app.history_contract import source_key
from offline_fixtures import guarded_runtime, isolated_runtime


class ReviewPureTests(unittest.TestCase):
    def test_device_health_does_not_inherit_other_channels_failures(self):
        contexts = ConnectionContextManager()
        first = DeviceProfile("AMS01", "one", "remote", "modbus", endpoint="fixture.invalid:502")
        second = DeviceProfile("AMS02", "two", "remote", "modbus", endpoint="fixture.invalid:502")
        shared = contexts.context_for(first)
        shared.last_error = "other channel failure"
        shared.last_success_at = "2026-09-21T00:00:00Z"
        class Adapter(HubAdapterBase):
            def read_telemetry(self, profile):
                return self._snapshot(profile, {"online": profile.device_id == "AMS01",
                    "timestamp": "2026-09-21T00:00:01Z"})
        hub = DeviceHub(DeviceRegistry([first, second]), {"modbus": Adapter({}, contexts)})
        one, two = hub.read_device("AMS01"), hub.read_device("AMS02")
        self.assertIsNone(one["health"]["error"])
        self.assertIsNone(two["health"]["last_success_at"])
        self.assertEqual(one["health"]["consecutive_failures"], 0)
        self.assertEqual(two["health"]["consecutive_failures"], 1)

    def test_partial_output_stops_and_preserves_uncertainty(self):
        calls = []
        def step(ok):
            calls.append(ok)
            return {"ok": ok, "verified": ok}
        result = execute_output_sequence([lambda: step(True), lambda: step(False), lambda: step(True)])
        self.assertEqual(calls, [True, False])
        self.assertTrue(result["partial"])
        self.assertTrue(result["recovery_required"])

    def test_first_write_exception_is_not_reported_as_unapplied(self):
        def uncertain():
            raise OSError("reply lost after write")
        result = execute_output_sequence([uncertain])
        self.assertTrue(result["applied"])
        self.assertFalse(result["ok"])

    def test_unit_id_changes_measurement_identity(self):
        keys = []
        for unit in (1, 2):
            config = {"data_source": "modbus", "modbus_host": "fixture.invalid", "modbus_unit_id": unit}
            profile = DeviceProfile(**load_exw1_topology(config).device_profiles()["AMS01"])
            keys.append(source_key(profile, config))
        self.assertNotEqual(*keys)

    def test_overlapping_schedule_cannot_capture_another_runs_temporary_mode(self):
        engine = ScheduleExecution()
        definition = {"id": "a", "remote_id": "AMS01", "mode": 2, "start_time": "12:00", "end_time": "13:00"}
        calls = []
        def apply(run, entry, persist):
            calls.append(entry["device_id"])
            entry.update(owned=True, state="APPLIED")
            return {"ok": True}
        engine.start(definition, datetime(2026, 9, 21, 12), ["AMS01"], apply, lambda: None)
        result = engine.start({**definition, "id": "b"}, datetime(2026, 9, 21, 12), ["AMS01"], apply, lambda: None)
        self.assertEqual(result["error"], "schedule_target_already_owned")
        self.assertEqual(calls, ["AMS01"])


class ReviewRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.r = guarded_runtime()
        context = isolated_runtime(self.r)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.r._schedule_execution = ScheduleExecution()

    def test_failed_schedule_edits_roll_back(self):
        r = self.r
        original = [{"id": "x", "name": "old", "active": False}]
        for action in (lambda: r.toggle_schedule("x"), lambda: r.delete_schedule("x"),
                       lambda: r.update_schedule("x", SimpleNamespace(model_dump=lambda: {"name": "new"}))):
            r.schedules_store = copy.deepcopy(original)
            with patch.object(r, "save_schedules", side_effect=OSError("disk full")):
                self.assertFalse(action()["ok"])
            self.assertEqual(r.schedules_store, original)

    def test_save_failure_reaches_collector(self):
        row = {"source_key": "s", "sample_id": "i", "timestamp": "2026-09-21T00:00:00Z"}
        with patch.object(self.r, "save_to_db", return_value={"ok": False, "error": "disk full"}):
            with self.assertRaisesRegex(RuntimeError, "disk full"):
                self.r._save_collected_snapshot({"devices": [row]})

    def test_recovery_acknowledgement_does_not_write_outputs(self):
        r = self.r
        r.schedules_store = [{"id": "x", "active": True}]
        r._schedule_execution.runs["x"] = {"state": "RECOVERY_REQUIRED", "targets": [{"device_id": "AMS01", "owned": True}]}
        with patch.object(r, "save_schedules"), patch.object(r, "_run_schedule_hub_command") as command:
            result = r.acknowledge_schedule_recovery("x", r.ScheduleRecoveryConfirmation(confirmed=True))
        self.assertTrue(result["ok"])
        self.assertFalse(r.schedules_store[0]["active"])
        command.assert_not_called()

    def test_reconnect_restores_same_route_but_changed_route_requires_recovery(self):
        r = self.r
        from contextlib import ExitStack
        profile = SimpleNamespace(device_id="AMS01", transport="modbus", endpoint="fixture.invalid")
        target = SimpleNamespace(transport="modbus", endpoint="fixture.invalid", channel=1,
                                 unit_id=1, mapping={"control": 4}, encoding={})
        snapshot = {"source_key": "fixture", "standby_signal": False}
        hub = SimpleNamespace(registry=SimpleNamespace(require=lambda _: profile), cached=lambda _: snapshot)
        for mode in (2, 8):
            with self.subTest(mode=mode), ExitStack() as stack:
                stack.enter_context(patch.object(r, "get_device_hub", return_value=hub))
                stack.enter_context(patch.object(r, "_resolve_command_target", return_value=target))
                stack.enter_context(patch.object(r, "_hub_current_mode", return_value=1))
                command = stack.enter_context(patch.object(r, "_run_schedule_hub_command", return_value={"ok": True}))
                run, entry = {"mode": mode}, {"device_id": "AMS01"}
                self.assertTrue(r._schedule_device_action(run, entry, lambda: None)["ok"])
                r._config_generation += 1  # A reconnect alone must not discard restoration.
                self.assertTrue(r._schedule_device_action(run, entry, restoring=True)["ok"])
                if mode == 8:
                    command.assert_called_with("AMS01", 8, standby_enabled=False)
                target.unit_id = 2
                result = r._schedule_device_action(run, entry, restoring=True)
                self.assertTrue(result["recovery_required"])
                self.assertEqual(command.call_count, 2)
                target.unit_id = 1

    def test_partial_settings_write_reports_applied_names(self):
        r = self.r
        with patch.object(r, "_exa1_service", side_effect=[None, OSError("reply lost")]):
            result = r.write_modbus_exa1_settings("AMS01", {"operation_kpa": 400, "standby_kpa": 200})
        self.assertFalse(result["ok"])
        self.assertTrue(result["partial"])
        self.assertTrue(result["recovery_required"])
        self.assertEqual(result["written"], ["operation_kpa"])

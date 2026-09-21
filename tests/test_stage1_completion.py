"""Remaining stage-1 contracts, only through the protected offline runner."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from offline_fixtures import guarded_runtime, isolated_runtime, synthetic_nodes
from app.config_journal import ConfigJournal, RecoveryRequired
from app.command_target import current_target
from app.connection_context import ConnectionContextManager
from app.device_hub import DeviceProfile
from app.hub_adapters import WebHubAdapter, SimulatorHubAdapter, OpcuaHubAdapter

runtime = guarded_runtime()


class Stage1CompletionTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(runtime, "CONFIG_FILE", self.root / "config.json"))
        self.enterContext(patch.object(runtime, "RUNTIME_STATE_FILE", self.root / "runtime_state.json"))

    def test_non_none_baseline_and_endpoint_publish_together(self):
        runtime.config_store["dashboard_last_raw_accumulated_l"] = 123.5
        before = runtime.current_config_generation()
        gateways = copy.deepcopy(runtime.config_store["modbus_gateways"])
        gateways["FIXTURE-EXW1"]["host"] = "replacement.invalid"
        runtime.update_config_values(modbus_gateways=gateways, dashboard_last_raw_accumulated_l=None)
        disk = runtime.load_config()
        self.assertEqual(disk["modbus_gateways"], gateways)
        self.assertIsNone(disk["dashboard_last_raw_accumulated_l"])
        self.assertEqual(runtime.current_config_generation(), before + 1)

    def test_committed_failure_blocks_new_commands_and_all_saves(self):
        previous = copy.deepcopy(runtime.config_store)
        original = ConfigJournal._replace
        def fail_target(path, value):
            if path == runtime.CONFIG_FILE:
                raise OSError("injected target failure")
            original(path, value)
        with patch.object(ConfigJournal, "_replace", side_effect=fail_target):
            with self.assertRaises(RecoveryRequired):
                runtime.update_config_values(data_source="opcua", dashboard_last_raw_accumulated_l=7)
        self.assertEqual(runtime.config_store, previous)
        for action in (lambda: runtime.update_config_values(force_mode="01"),
                       lambda: runtime.save_config(previous),
                       lambda: runtime.save_runtime_state(previous),
                       lambda: runtime.get_device_hub()):
            with self.assertRaises(RecoveryRequired):
                action()
        runtime._config_journal().recover()
        self.assertEqual(runtime.load_config()["dashboard_last_raw_accumulated_l"], 7)

    def test_malformed_bootstrap_exposes_read_only_recovery_without_defaults(self):
        journal = runtime._config_journal()
        journal.path.parent.mkdir()
        journal.path.write_text("{broken", encoding="utf-8")
        runtime.CONFIG_FILE.write_text('{"ams_password":"synthetic-private"}', encoding="utf-8")
        original = runtime.CONFIG_FILE.read_bytes()
        runtime.initialize_runtime(base_dir=self.root)
        self.assertTrue(runtime.configuration_recovery_status()["recovery_required"])
        self.assertEqual(runtime.config_store["device_profiles"], {})
        self.assertNotIn("ams_password", runtime.config_store)
        self.assertEqual(runtime.CONFIG_FILE.read_bytes(), original)
        self.assertIn(b"read-only", runtime.serve_dashboard().body)
        with self.assertRaises(RecoveryRequired):
            runtime.get_device_hub()

    def test_recovery_asgi_guard_preserves_outer_auth_and_blocks_writes(self):
        from test_local_access import scope, finish_immediate
        token = runtime.app.state.local_request_token
        self.enterContext(patch.object(runtime, "_runtime_recovery_error", "configuration_recovery_required"))

        def request(path, supplied_token=None, bootstrap=False):
            sent = []
            request_scope = scope(path, method="GET" if bootstrap else "POST", token=supplied_token)
            if bootstrap:
                request_scope["headers"].append((b"x-ams-bootstrap", b"1"))
            async def receive():
                return {"type": "http.request", "body": b""}
            async def send(message):
                sent.append(message)
            finish_immediate(runtime.app(request_scope, receive, send))
            return sent

        self.assertEqual(request("/api/control/standby-signal")[0]["status"], 403)
        for path in ("/api/control/standby-signal", "/api/hub/devices/AMS01/settings",
                     "/api/diagnostics/write-test", "/api/config"):
            sent = request(path, token)
            self.assertEqual(sent[0]["status"], 503)
            body = json.loads(sent[1]["body"])
            self.assertTrue(body["recovery_required"])
            self.assertNotIn("config", body)
        self.assertEqual(request("/api/local-session", bootstrap=True)[0]["status"], 200)
        self.assertEqual(request("/api/recovery/configuration")[0]["status"], 403)
        # POST reaches FastAPI routing (GET-only status endpoint), not the gate.
        self.assertEqual(request("/api/recovery/configuration", token)[0]["status"], 405)

    def test_persist_false_rejects_pending_replay_without_touching_files(self):
        journal = runtime._config_journal()
        journal.path.parent.mkdir()
        intent = {"version": 1, "values": {"config": {}, "runtime":
                  {key: None for key in runtime.RUNTIME_STATE_KEYS}}}
        journal.path.write_text(json.dumps(intent), encoding="utf-8")
        original = journal.path.read_bytes()
        with self.assertRaises(RecoveryRequired):
            runtime.initialize_runtime(base_dir=self.root, persist=False)
        self.assertEqual(journal.path.read_bytes(), original)
        self.assertFalse(runtime.CONFIG_FILE.exists())

    def test_invalid_candidate_never_creates_intent(self):
        with self.assertRaises(ValueError):
            runtime.update_config_values(device_profiles={"BAD": {"transport": "wrong"}},
                                         dashboard_last_raw_accumulated_l=99)
        self.assertFalse(runtime._config_journal().path.exists())
        self.assertFalse(runtime.CONFIG_FILE.exists())

    def test_direct_web_invalid_mode_has_no_warmup(self):
        warmup = Mock()
        adapter = WebHubAdapter({"warmup_web": warmup}, ConnectionContextManager())
        profile = DeviceProfile("AMS00", "base", "base", "web")
        with self.assertRaises(ValueError):
            adapter.execute_command(profile, "mode", {"mode": True})
        warmup.assert_not_called()

    def test_direct_simulator_disabled_and_invalid_no_mutation(self):
        update = Mock()
        adapter = SimulatorHubAdapter({"update_config": update}, ConnectionContextManager())
        profile = DeviceProfile("AMS00", "base", "base", "simulator", enabled=False)
        self.assertFalse(adapter.execute_command(profile, "mode", {"mode": 1})["ok"])
        self.assertFalse(adapter.write_settings(profile, {"operation_kpa": 1})["ok"])
        with self.assertRaises(ValueError):
            adapter.execute_command(profile, "standby", {"enabled": 1})
        update.assert_not_called()

    def test_port4_complete_image_only_before_service_io(self):
        write = Mock(return_value={"ok": True})
        config = {"opcua_endpoint": "opc.tcp://fixture.invalid:4840"}
        adapter = OpcuaHubAdapter({"get_config": lambda k, d: config.get(k, d),
            "signal_node": Mock(return_value="node"), "write_bytes_node": write}, ConnectionContextManager())
        profile = DeviceProfile("AMS01", "remote", "remote", "opcua", endpoint=config["opcua_endpoint"])
        for size in (0, 1, 15, 17):
            with self.assertRaises(ValueError):
                adapter.execute_command(profile, "port4_pdout", {"bytes": [0] * size})
        write.assert_not_called()
        values = list(range(16))
        self.assertTrue(adapter.execute_command(profile, "port4_pdout", {"bytes": values})["ok"])
        write.assert_called_once_with("node", values)

    def test_resolved_target_drives_mapping_even_if_mutable_global_changes(self):
        original_address = runtime.MODBUS_AMS_CHANNEL_MAP["AMS01"]["output_start"]
        client = Mock()
        observed = []
        def read(address, count):
            target = current_target("AMS01")
            self.assertIsNotNone(target)
            observed.append((address, target.endpoint, target.unit_id, target.generation))
            runtime.MODBUS_AMS_CHANNEL_MAP["AMS01"]["output_start"] = 9999
            return [0] if len(observed) == 1 else [runtime._modbus_wire_word(0x0100)]
        client.read_holding_registers.side_effect = read
        with patch.object(runtime._modbus_client_pool, "get", return_value=client):
            result = runtime._legacy_hub_command("AMS01", "standby", {"enabled": True})
        self.assertTrue(result["ok"], result)
        self.assertEqual([row[0] for row in observed], [original_address] * 2)
        self.assertEqual(client.write_registers.call_args.args[0], original_address)
        self.assertIsNone(current_target())

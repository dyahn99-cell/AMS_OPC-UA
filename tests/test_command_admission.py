"""Actual legacy route validation with synthetic runtime and no transport."""
import unittest
from unittest.mock import Mock, patch

from offline_fixtures import guarded_runtime, isolated_runtime


class CommandAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.runtime = guarded_runtime()
        self.context = isolated_runtime(self.runtime)
        self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)

    def test_explicit_invalid_contact_never_executes(self):
        runtime = self.runtime
        hub = Mock()
        with patch.object(runtime, "get_device_hub", return_value=hub):
            for contact in ("", None, "invalid"):
                with self.subTest(contact=contact):
                    result = runtime.ctrl_air_supply(runtime.AirSupplyRequest(
                        remote_id="AMS01", enabled=True, contact_mode=contact))
                    self.assertFalse(result["ok"])
            hub.execute.assert_not_called()

    def test_omitted_contact_preserves_default_contract(self):
        runtime = self.runtime
        with patch.object(runtime, "_legacy_hub_command", return_value={"ok": True}) as command:
            runtime.ctrl_air_supply(runtime.AirSupplyRequest(remote_id="AMS01", enabled=True))
        command.assert_called_once_with("AMS01", "air_supply", {"enabled": True})

    def test_ambiguous_pin_payload_never_reads_or_writes(self):
        runtime = self.runtime
        with patch.object(runtime, "get_device_hub") as hub:
            for values in ({"value": 0, "pin": 2, "enabled": True},
                           {"value": 0, "enabled": False},
                           {"enabled": True},
                           {"value": 0, "pin": None}):
                with self.subTest(values=values):
                    result = runtime.ctrl_port4_do(runtime.Port4DoRequest(remote_id="AMS01", **values))
                    self.assertFalse(result["ok"])
            hub.assert_not_called()

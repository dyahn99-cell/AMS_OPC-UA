import unittest
from unittest.mock import Mock, patch
from pydantic import ValidationError
from offline_fixtures import guarded_runtime, isolated_runtime

runtime = guarded_runtime()


class SampleQualityTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_runtime(runtime))

    def test_missing_counter_is_not_zero_and_real_zero_is_valid(self):
        for invalid in (None, "--", float("nan"), float("inf")):
            with self.subTest(value=invalid):
                row = runtime.parse_remote_opcua_values("AMS01", {"accumulated": invalid, "flow": 0})
                self.assertIsNone(row["accumulated_flow_l"])
                self.assertEqual(row["instant_flow_l_min"], 0)
                self.assertEqual(row["field_quality"]["accumulated_flow_l"], "unavailable")

    def test_missing_pdin_byte_only_invalidates_overlapping_field(self):
        with self.assertRaises(ValueError):
            runtime._extract_pd_bits(["--", "A0"], 8, 8)
        self.assertEqual(runtime._extract_pd_bits(["--", "A0"], 0, 8), 160)
        self.assertEqual(runtime._extract_pd_bits(["00", "00", "00", "00", "0F", "A0", "30", "00"], 16, 16), 4000)

    def test_invalid_energy_is_rejected_and_existing_bad_config_does_not_throw(self):
        for values in ({"tree_per_co2": 0}, {"price_per_kwh": -1}, {"kwh_per_m3": float("nan")}):
            with self.assertRaises(ValidationError):
                runtime.EnergyConfig(**values)
        with patch.dict(runtime.config_store, {"energy_tree_per_co2": 0}):
            self.assertIsNone(runtime.calculate_energy(100)["kwh"])

    def test_invalid_byte_entries_stay_unavailable_without_masking(self):
        invalid = [None, "--", True, -1, 256, 1.5, float("nan"), float("inf")]
        self.assertEqual(runtime._opcua_bytes_to_hex(invalid, len(invalid)), ["--"] * len(invalid))
        self.assertEqual(runtime._opcua_bytes_to_hex({"0": 0, "1": 160}, 3), ["00", "A0", "--"])
        wire = [0, 0, 0, 0, 15, 160, 48, 0]
        self.assertEqual(runtime._extract_pd_bits(runtime._opcua_bytes_to_hex(wire, 8), 16, 16), 4000)

    def test_missing_pqi_is_not_a_valid_zero_status(self):
        row = runtime.parse_remote_opcua_values("AMS01", {"flow": 0, "ex_p4_pqi": None})
        self.assertIsNone(row["port4_pqi"])
        self.assertEqual(row["field_quality"]["port4_pqi"], "unavailable")
        self.assertEqual(row["port4_status"], "Unavailable")
        self.assertEqual(row["instant_flow_l_min"], 0)

    def test_existing_energy_values_normalize_and_overflow_is_unavailable(self):
        with patch.dict(runtime.config_store, {"energy_kwh_per_m3": "0.11", "energy_tree_per_co2": "6"}):
            self.assertEqual(runtime.calculate_energy(1000)["kwh"], 0.11)
        for value in ("invalid", None, True, float("inf"), -1):
            with self.subTest(value=value), patch.dict(runtime.config_store, {"energy_kwh_per_m3": value}):
                self.assertIsNone(runtime.calculate_energy(1000)["kwh"])
        with patch.dict(runtime.config_store, {"energy_kwh_per_m3": 1e308}):
            self.assertIsNone(runtime.calculate_energy(1e308)["kwh"])

    def test_web_truncation_preserves_only_complete_fields(self):
        row = runtime.parse_process_hex("0000000000000FA0FF9C")
        self.assertEqual(row["accumulated_flow_l"], 0)
        self.assertEqual(row["instant_flow_l_min"], 4000)
        self.assertEqual(row["temperature_c"], -10)
        for field in ("pressure_mpa", "itv_pressure_mpa", "ams_code"):
            self.assertIsNone(row[field])
            self.assertEqual(row["field_quality"][field], "unavailable")
        self.assertEqual(row["diagnostic"], "Unavailable")
        self.assertEqual(row["port_status"], "Unavailable")
        self.assertIsNone(runtime.parse_process_hex("0000000000000FA")["instant_flow_l_min"])
        self.assertIsNone(runtime.parse_process_hex("000000000000GGGG")["instant_flow_l_min"])

    def test_scalar_wire_ranges_reject_fractional_and_out_of_range(self):
        for key, field, low, high in (
            ("flow", "instant_flow_l_min", 0, 65535),
            ("accumulated", "accumulated_flow_l", 0, 4294967295),
            ("temperature", "temperature_c", -32768, 32767),
            ("ex_p4_pqi", "port4_pqi", 0, 255),
        ):
            for value in (low - 1, high + 1, 1.5, True, float("inf")):
                with self.subTest(key=key, value=value):
                    row = runtime.parse_ams00_opcua_values({key: value})
                    self.assertIsNone(row[field])
                    self.assertEqual(row["field_quality"][field], "unavailable")
            for value in (low, high):
                self.assertEqual(runtime.parse_ams00_opcua_values({key: value})["field_quality"][field], "good")

    def test_cached_rows_recheck_measurement_and_field_age_without_mutating_cache(self):
        stamp = "2026-09-01T00:00:00+00:00"
        cached = {"AMS01": {"timestamp": stamp, "online": True, "device_connected": True,
                  "instant_flow_l_min": 0, "field_quality": {"instant_flow_l_min": "good"},
                  "field_source_timestamps": {"instant_flow_l_min": stamp}}}
        with patch.object(runtime, "_worker_remotes_cache", cached), \
                patch.object(runtime, "_worker_token_current", return_value=True), \
                patch.object(runtime.time, "time", return_value=1788220815):
            self.assertTrue(runtime._get_cached_remote("AMS01")["online"])
        with patch.object(runtime, "_worker_remotes_cache", cached), \
                patch.object(runtime, "_worker_token_current", return_value=True), \
                patch.object(runtime.time, "time", return_value=1788220816):
            row = runtime._get_cached_remote("AMS01")
        self.assertFalse(row["online"])
        self.assertTrue(row["stale"])
        self.assertEqual(row["field_quality"]["instant_flow_l_min"], "stale")
        self.assertTrue(cached["AMS01"]["online"])
        self.assertEqual(cached["AMS01"]["field_quality"]["instant_flow_l_min"], "good")
        cached["AMS01"]["timestamp"] = "2026-09-01T00:00:16+00:00"
        with patch.object(runtime, "_worker_remotes_cache", cached), \
                patch.object(runtime, "_worker_token_current", return_value=True), \
                patch.object(runtime.time, "time", return_value=1788220816):
            row = runtime._get_cached_remote("AMS01")
        self.assertTrue(row["online"])
        self.assertEqual(row["field_quality"]["instant_flow_l_min"], "stale")

    def test_stale_adapter_snapshot_cannot_be_online(self):
        from app.hub_adapters import HubAdapterBase
        profile = Mock(device_id="AMS01", transport="opcua")
        contexts = Mock()
        contexts.snapshot.return_value = {}
        adapter = HubAdapterBase({}, contexts)
        for flags in ({"stale": True}, {"opcua_stale": True}, {"health": {"stale": True}}):
            with self.subTest(flags=flags):
                snapshot = adapter._snapshot(profile, {"online": True, "instant_flow_l_min": 4000, **flags})
                self.assertFalse(snapshot.online)
                self.assertTrue(snapshot.health.stale)

    def test_aggregate_partial_and_unavailable_are_not_complete_zero(self):
        from app.device_hub import aggregate_snapshots
        rows = [{"device_id": "AMS01", "online": True, "instant_flow_l_min": 0},
                {"device_id": "AMS02", "online": True, "stale": True, "instant_flow_l_min": 4000}]
        combined = aggregate_snapshots(rows)
        self.assertEqual(combined["instant_flow_l_min"], 0)
        self.assertEqual(combined["field_quality"]["instant_flow_l_min"], "partial")
        self.assertIsNone(combined["accumulated_flow_l"])
        self.assertEqual(combined["field_quality"]["accumulated_flow_l"], "unavailable")
        rows[0]["online"] = False
        combined = aggregate_snapshots(rows)
        self.assertIsNone(combined["instant_flow_l_min"])
        self.assertEqual(combined["field_quality"]["instant_flow_l_min"], "unavailable")

    def test_invalid_or_stale_control_inputs_never_write_even_when_forced(self):
        fresh = {"online": True, "timestamp": "2026-09-01T00:00:00+00:00"}
        invalid = [{"dio_code": value} for value in (None, True, -1, 4, 1.5, float("nan"))]
        invalid += [{"error": "read_failed"}, {"stale": True}, {"timestamp": "2026-08-31T23:59:44+00:00"},
                    {"timestamp": None}, {"field_quality": {"dio_code": "unavailable"}}]
        hub = Mock()
        with patch.object(runtime, "get_device_hub", return_value=hub), \
                patch.object(runtime.time, "time", return_value=1788220801), \
                patch.dict(runtime.config_store, {"dio_links": {"AMS01": {"enabled": True}}}):
            for overrides in invalid:
                with self.subTest(overrides=overrides):
                    payload = {"devices": [{**fresh, "device_id": "IO13", "dio_code": 1, **overrides},
                                           {**fresh, "device_id": "AMS01"}]}
                    runtime._apply_dio_links(payload, force_target="AMS01")
                    self.assertEqual(runtime._dio_link_runtime["AMS01"]["error"], "dio_source_unavailable")
            payload = {"devices": [{**fresh, "device_id": "IO13", "dio_code": 1},
                                   {**fresh, "device_id": "AMS01", "stale": True}]}
            runtime._apply_dio_links(payload, force_target="AMS01")
            self.assertEqual(runtime._dio_link_runtime["AMS01"]["error"], "dio_target_unavailable")
        hub.execute.assert_not_called()

    def test_invalid_lamp_and_schedule_restore_suppress_io(self):
        fresh = {"online": True, "timestamp": "2026-09-01T00:00:00+00:00", "ams_code": 1}
        hub = Mock()
        with patch.object(runtime, "get_device_hub", return_value=hub), \
                patch.object(runtime.time, "time", return_value=1788220801), \
                patch.object(runtime, "_modbus_read_registers") as read, \
                patch.object(runtime, "_modbus_write_registers") as write, \
                patch.object(runtime, "MODBUS_AMS_CHANNEL_MAP", {"IO13": {"device_kind": "remote_io", "output_start": 0}}):
            for overrides in ({"ams_code": None}, {"ams_code": True}, {"ams_code": 255},
                              {"ams_code": 1.5}, {"ams_code": 2}, {"stale": True}, {"error": "read_failed"},
                              {"timestamp": None}, {"timestamp": "2026-08-31T23:59:44+00:00"},
                              {"field_quality": {"ams_code": "stale"}}):
                with self.subTest(overrides=overrides):
                    row = {**fresh, **overrides}
                    hub.cached.return_value = row
                    self.assertIsNone(runtime._hub_current_mode("AMS01"))
                    self.assertFalse(runtime._restore_schedule_mode("AMS01", 2, 1)["ok"])
                    # Waiting is known for lamp mapping but not a restorable mode.
                    if overrides != {"ams_code": 2}:
                        self.assertIsNone(runtime._ch1_lamp_bits(row))
                        runtime._apply_ch1_status_lamp({"devices": [
                            {**fresh, "device_id": "IO13"}, {**row, "device_id": "AMS01"}]})
            hub.cached.return_value = fresh
            for mode in (None, True, 0, 4, "1"):
                self.assertEqual(runtime._restore_schedule_mode("AMS01", 2, mode)["error"], "schedule_restore_unavailable")
            read.assert_not_called()
            write.assert_not_called()
        hub.execute.assert_not_called()
        hub.read_device.assert_not_called()

    def test_worker_failure_invalidates_previous_cache_even_inside_ttl(self):
        runtime._worker_remotes_cache = {"AMS01": {"accumulated_flow_l": 100, "device_connected": True}}
        owner, proc = object(), Mock()
        proc.poll.return_value = None
        token = (runtime.current_config_generation(), owner, proc)
        with patch.object(runtime, "node_worker_owner", owner), patch.object(runtime, "node_worker_proc", proc), \
                patch.object(runtime, "_worker_cache_token", token), patch.object(runtime, "_worker_last_fetch", 0), \
                patch.object(runtime, "_owned_worker_request", side_effect=RuntimeError("offline")) as request, \
                patch.object(runtime, "maybe_restart_node_worker"):
            runtime._fetch_worker_data()
            self.assertFalse(runtime._fetch_worker_data()["connected"])
            self.assertTrue(runtime._get_cached_remote("AMS01")["stale"])
            self.assertEqual(request.call_count, 1)

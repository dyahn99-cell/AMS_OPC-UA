"""Synthetic inputs only; this module never imports application code at module scope."""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sys
from unittest.mock import patch


class FrozenDatetime(datetime):
    """Pin history partition tests to the sample month, not the machine's date."""

    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 9, 12, 10, 0, 0)
        return value if tz is None else value.replace(tzinfo=tz)


def synthetic_config():
    # Explicit fixture for CH1/2 EXA1, CH3..12 reserved, CH13 remote I/O.
    # No site config, endpoint, password, or stored measurement is copied.
    slots = [
        {"channel": n, "kind": "exa1", "device_id": f"AMS{n:02d}",
         "model": 40, "input_bytes": 36, "output_bytes": 18}
        for n in (1, 2)
    ]
    slots += [{"channel": n, "kind": "dummy", "input_bytes": 36, "output_bytes": 18}
              for n in range(3, 13)]
    slots += [{"channel": 13, "kind": "remote_io", "device_id": "IO13",
               "input_bytes": 8, "output_bytes": 8}]
    return {
        "ams_host": "https://ams-base.invalid", "ams_password": "synthetic-not-a-secret",
        "opcua_endpoint": "opc.tcp://ams-base.invalid:4840", "data_source": "demo",
        "modbus_host": "exw1-fixture.invalid", "modbus_port": 502,
        "modbus_unit_id": 1, "modbus_timeout_s": 0.01,
        "modbus_exa1_ch1_model": 40, "modbus_exa1_ch2_model": 40,
        "modbus_process_byte_swap": False, "modbus_accumulator_word_swap": True,
        "modbus_gateways": {"FIXTURE-EXW1": {
            "name": "Synthetic EXW1", "host": "exw1-fixture.invalid", "port": 502,
            "unit_id": 1, "timeout_s": 0.01, "diagnostics": "advanced",
            "max_slots": 15, "slots": slots,
        }},
        "device_profiles": {}, "dio_links": {}, "iodd_assignments": {},
        "energy_kwh_per_m3": 0.11, "energy_price_per_kwh": 170.0,
        "energy_co2_per_kwh": 0.454, "energy_tree_per_co2": 6.0,
    }


def synthetic_nodes():
    return {"version": 1, "remotes": {
        device: {
            "read": {name: f"ns=2;s=offline.{device}.{name}"
                     for name in ("pressure", "temperature", "flow", "accumulated")},
            "write": {name: f"ns=2;s=offline.{device}.{name}"
                      for name in ("standby", "forced_standby", "air_nc", "air_no", "p4_do", "p4_pdout")},
        } for device in ("AMS00", "AMS01", "AMS02")
    }}


def write_synthetic_inputs(work):
    work = Path(work)
    for folder in ("assets", "db", "logs", "iodd_library"):
        (work / folder).mkdir(parents=True, exist_ok=True)
    for name, data in {
        "config.json": synthetic_config(), "nodes.json": synthetic_nodes(),
        "runtime_state.json": {}, "schedules.json": [], "iodd_library/index.json": [],
    }.items():
        (work / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def guarded_runtime():
    """Fail before importing runtime when someone runs unittest in the live checkout."""
    marker = getattr(sys, "_ams_offline_checkout", None)
    checkout = Path(__file__).resolve().parents[1]
    if marker is None or Path(marker).resolve() != checkout:
        raise RuntimeError("Run python scripts/check_offline.py; direct runtime test imports are unsafe")
    from app import runtime
    if not Path(runtime.__file__).resolve().is_relative_to(checkout):
        raise RuntimeError("runtime was imported from outside the guarded temporary checkout")
    return runtime


@contextmanager
def isolated_runtime(runtime):
    """Each test gets fresh config, caches, schedules, and a deterministic date.

    Keep real implementation functions intact; tests patch only their transports.
    Explicit defaults replace the old dependence on the user's Modbus site setup.
    """
    from contextlib import ExitStack
    import copy

    values = {
        "config_store": {**copy.deepcopy(runtime.DEFAULT_CONFIG), **synthetic_config()},
        "datetime": FrozenDatetime, "MODBUS_AMS_CHANNEL_MAP": {},
        "_exw1_topology_cache": None, "_exw1_topology_signature": None,
        "_hub_instance": None, "_hub_signature": None,
        "_acquisition_enabled": True,
        "_configuration_admission": runtime.ConfigurationAdmission(),
        "_CH1_LAMP_STATE": {},
        "_history_last_raw_by_device": {}, "_migrated_dbs": set(),
        "_modbus_live_cache": {}, "_modbus_live_at": 0.0, "_modbus_live_error": None,
        "_dio_link_runtime": {}, "schedules_store": [], "device_connected": False,
        "node_worker_owner": None, "node_worker_proc": None,
        "_config_generation": 0, "_runtime_initialized": False, "_runtime_live": False,
        "_runtime_adapters_override": None, "_runtime_recovery_error": None,
        "OPCUA_NODE_CONFIG": synthetic_nodes(),
        "REMOTE_NODE_MAPS": runtime._read_node_maps(synthetic_nodes()),
        "REMOTE_SIGNAL_NODES": runtime._write_node_maps(synthetic_nodes()),
        "AMS00_NODES": runtime._read_node_maps(synthetic_nodes())["AMS00"],
        "AMS01_NODES": runtime._read_node_maps(synthetic_nodes())["AMS01"],
        "_worker_remotes_cache": {}, "_worker_last_fetch": 0.0,
        "_worker_status_cache": {}, "_worker_status_at": 0.0,
    }
    with ExitStack() as stack:
        for name, value in values.items():
            stack.enter_context(patch.object(runtime, name, value))
        runtime.get_exw1_topology()
        yield runtime

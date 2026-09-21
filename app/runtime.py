from app.output_sequence import execute_output_sequence
import logging
from app import savings
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictBool, StrictInt, Field
from app.sample_quality import number as finite_number, sample_time, usable as sample_usable
from app import history_contract
from app.config_journal import ConfigJournal, RecoveryRequired
from app.command_target import ResolvedCommandTarget, current_target, target_scope
from functools import wraps
import requests
import urllib3
import asyncio
import time
import sqlite3
import socket
import struct
import csv
import io
import uuid
import threading
import traceback
import subprocess
import sys
import shutil
import os
import copy
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional
import json
import math
from pathlib import Path
from urllib.parse import urlparse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

try:
    from .command_payload import validate_command_payload
    from .config_transaction import ConfigurationAdmission, reject_new_quarantine
    from .connection_context import ConnectionContextManager
    from .device_hub import DeviceHealth, DeviceHub, DeviceProfile, DeviceRegistry, DeviceSnapshot
    from .exw1_topology import default_topology_config, load_exw1_topology
    from .hub_adapters import build_runtime_adapters
    from .local_access import authenticate_websocket, install_local_access
    from .modbus_client import ModbusClientPool, ModbusEndpoint
    from .worker_owner import WorkerOwner
except ImportError:
    from app.command_payload import validate_command_payload
    from app.config_transaction import ConfigurationAdmission, reject_new_quarantine
    from app.connection_context import ConnectionContextManager
    from app.device_hub import DeviceHealth, DeviceHub, DeviceProfile, DeviceRegistry, DeviceSnapshot
    from app.exw1_topology import default_topology_config, load_exw1_topology
    from app.hub_adapters import build_runtime_adapters
    from app.local_access import authenticate_websocket, install_local_access
    from app.modbus_client import ModbusClientPool, ModbusEndpoint
    from app.worker_owner import WorkerOwner

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def _save_collected_snapshot(payload):
    for device in payload.get("devices", []):
        if (device.get("source_key") and device.get("sample_id")
                and sample_time(device.get("timestamp")) is not None):
            # Invalid observations preserve gaps; COMBINED is not a counter source.
            result = save_to_db(device)
            if result and result.get("ok") is False:
                raise RuntimeError(result.get("error", "history_save_failed"))


_acquisition_enabled = False


def _collect_control_cycle():
    if not _acquisition_enabled or _runtime_recovery_error or _config_journal().path.exists():
        return {"devices": []}
    start_node_worker()
    generation = current_config_generation()
    payload = get_device_hub().read_all()
    with _command_generation():
        if generation != current_config_generation():
            return {"devices": []}
        payload["config_generation"] = generation
        payload["data_source"] = str(config_store.get("data_source") or "opcua").lower()
        return _with_committed_usage(_apply_ch1_status_lamp(_apply_dio_links(payload)))

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _runtime_live, _acquisition_enabled
    with _runtime_init_lock:
        if _runtime_live:
            raise RuntimeError("the runtime singleton already has an active lifespan")
        initialize_runtime()
        _runtime_live = True
    from .control_coordinator import ControlCoordinator
    coordinator = None
    scheduler = None
    _configuration_admission.reopen()
    scheduler_started = False
    try:
        if _runtime_recovery_error:
            yield
            return
        if config_store.get("connect_automatically") is True:
            # The coordinator starts acquisition off the page-serving event loop.
            _acquisition_enabled = True
        coordinator = ControlCoordinator(_collect_control_cycle, _save_collected_snapshot, get_save_interval)
        coordinator.start()
        scheduler = AsyncIOScheduler()
        scheduler.add_job(check_schedules, "interval", seconds=30, id="check_schedules")
        scheduler.start()
        scheduler_started = True
        yield
    finally:
        try:
            if coordinator is not None:
                coordinator.request_stop()
            if scheduler_started:
                scheduler.pause()
                scheduler.shutdown(wait=False)
        finally:
            # No await/cancellation boundary until real device threads have finished.
            # No configuration or endpoint lock is held while joining/draining.
            _configuration_admission.close()
            try:
                if coordinator is not None:
                    coordinator.join()
                _configuration_admission.drain()
                if not _runtime_recovery_error:
                    stop_node_worker()
            finally:
                with _runtime_init_lock:
                    _acquisition_enabled = False
                    _runtime_live = False

app = FastAPI(lifespan=lifespan)

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
BASE_DIR = APP_DIR
ASSETS_DIR = APP_DIR / "assets"
# Filesystem discovery is deferred to the explicit bootstrap boundary.
_assets_app = StaticFiles(directory=ASSETS_DIR, check_dir=False)
app.mount("/assets", _assets_app, name="assets")

@app.get("/", response_class=HTMLResponse)
def serve_root():
    return serve_dashboard()

@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    if _runtime_recovery_error:
        return HTMLResponse("<h1>Configuration recovery required</h1>"
            "<p>No devices, worker, collection or schedules were started. "
            "Stored configuration was not replaced with defaults.</p>"
            "<p>Stop the application and have an administrator repair or restore "
            "the private configuration transaction and both stores together, "
            "then restart. This recovery view is read-only.</p>",
            headers={"Cache-Control": "no-store"})
    p = BASE_DIR / "dashboard.html"
    if not p.exists():
        p = BUNDLE_DIR / "dashboard.html"
    html = p.read_text(encoding="utf-8") if p.exists() else "<h1>dashboard.html not found</h1>"
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

@app.get("/api/recovery/configuration")
def configuration_recovery_status():
    required = bool(_runtime_recovery_error) or _config_journal().path.exists()
    return {"ok": not required, "recovery_required": required,
            "error": "configuration_recovery_required" if required else None,
            "completion": "unknown" if required else "complete",
            "manual_repair_required": bool(_runtime_recovery_error)}


class ConfigurationRecoveryMiddleware:
    """Pure ASGI gate; does not introduce a task group or response stream."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and (_runtime_recovery_error or _config_journal().path.exists()):
            path = scope.get("path", "")
            allowed = {"/", "/dashboard", "/api/recovery/configuration", "/api/local-session"}
            if path not in allowed and not path.startswith("/assets/"):
                response = JSONResponse(configuration_recovery_status(), status_code=503)
                return await response(scope, receive, send)
        return await self.app(scope, receive, send)


app.add_middleware(ConfigurationRecoveryMiddleware)
# Install after the recovery middleware so Host/Origin/token checks remain outermost.
install_local_access(app)

# Configuration stores
CONFIG_FILE = BASE_DIR / "config.json"
RUNTIME_STATE_FILE = BASE_DIR / "runtime_state.json"
NODES_FILE = BASE_DIR / "nodes.json"
DB_DIR      = BASE_DIR / "db"
LOG_DIR = BASE_DIR / "logs"
IODD_DIR = BASE_DIR / "iodd_library"
IODD_INDEX_FILE = IODD_DIR / "index.json"
_runtime_initialized = False
_runtime_recovery_error = None
_runtime_live = False
_runtime_init_lock = threading.RLock()

DEFAULT_CONFIG = {
    "ams_host":                    "https://192.168.0.1",
    "ams_password":                "admin",
    "ams_channel":                 0,
    "server_port":                 8000,
    "data_save_interval_s":        5,
    "itv_operation_pressure_kpa":  500,
    "itv_standby_pressure_kpa":    300,
    "standby_flow_threshold_lmin": 50,
    "standby_hysteresis_lmin":     10,
    "standby_on_delay_s":          30,
    "standby_off_delay_s":         60,
    "pf3a_isolation_enabled":      False,
    "pf3a_isolation_delay_s":      0,
    "standby_signal_enabled":      False,
    "standby_signal_forced":       False,
    "opcua_endpoint":              "opc.tcp://192.168.0.1:4840",
    "forced_standby_enabled":      False,
    "opcua_air_contact_mode":      "NC",
    "air_supply_signal_on":        True,
    "air_supply_enabled":          True,
    # ?먮꼫吏 湲곗?媛?
    "energy_kwh_per_m3":           0.11,
    "energy_price_per_kwh":        170.0,
    "energy_co2_per_kwh":          0.454,
    "energy_tree_per_co2":         6.0,
    "dashboard_total_flow_l":       0.0,
    "dashboard_last_raw_accumulated_l": None,
    "dashboard_total_reset_at":     None,
    "data_source":                   "opcua",
    "modbus_host":                   "192.168.0.1",
    "modbus_port":                   502,
    "modbus_unit_id":                1,
    "modbus_timeout_s":              1.5,
    "modbus_exa1_model":             40,
    "modbus_exa1_ch1_model":         40,
    "modbus_exa1_ch2_model":         40,
    "modbus_process_byte_swap":      True,
    "modbus_accumulator_word_swap":  True,
    "dio_links":                    {},
    "iodd_assignments":              {},
    "device_profiles":              {},
    "modbus_gateways":              {},
}

RUNTIME_STATE_KEYS = {
    "dashboard_total_flow_l",
    "dashboard_last_raw_accumulated_l",
    "dashboard_total_reset_at",
    "measurement_epochs",
    "measurement_sources",
    "measurement_display_offsets",
}
# Calculated from the validated EXW1 gateway/slot topology after config load.
MODBUS_AMS_CHANNEL_MAP = {}


def _atomic_write_json(path: Path, data, *, backup: bool = False):
    """Durably replace a JSON file without exposing a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        if backup and path.exists():
            try:
                shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
            except Exception as e:
                print(f"[JSON] backup failed for {path.name}: {type(e).__name__}: {e}")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def _load_json_with_backup(path: Path, default):
    for candidate in (path, path.with_suffix(path.suffix + ".bak")):
        if not candidate.exists():
            continue
        try:
            with open(candidate, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception as e:
            print(f"[JSON] load failed {candidate.name}: {type(e).__name__}: {e}")
    return copy.deepcopy(default)

def _config_journal():
    return ConfigJournal(CONFIG_FILE, RUNTIME_STATE_FILE, RUNTIME_STATE_KEYS)


def load_config() -> dict:
    _config_journal().require_clear()
    saved = _load_json_with_backup(CONFIG_FILE, DEFAULT_CONFIG)
    if not isinstance(saved, dict):
        saved = DEFAULT_CONFIG.copy()
    for k, v in DEFAULT_CONFIG.items():
        saved.setdefault(k, v)
    runtime_state = _load_json_with_backup(RUNTIME_STATE_FILE, {})
    if isinstance(runtime_state, dict):
        for key in RUNTIME_STATE_KEYS:
            if key in runtime_state:
                saved[key] = runtime_state[key]
    return saved

def save_config(cfg: dict):
    with config_lock:
        _config_journal().require_clear()
        persisted = {k: v for k, v in cfg.items() if k not in RUNTIME_STATE_KEYS}
        _atomic_write_json(CONFIG_FILE, persisted, backup=True)

def save_runtime_state(cfg: dict):
    with config_lock:
        _config_journal().require_clear()
        state = {k: cfg.get(k) for k in RUNTIME_STATE_KEYS}
        _atomic_write_json(RUNTIME_STATE_FILE, state)

_config_generation = 0
_config_generation_lock = threading.RLock()


_configuration_admission = ConfigurationAdmission()
_ROUTE_CONFIG_KEYS = frozenset({
    "ams_host", "ams_password", "ams_channel", "opcua_endpoint", "data_source",
    "device_profiles", "device_profiles_explicit", "modbus_gateways",
    "modbus_gateways_explicit", "modbus_host", "modbus_port", "modbus_unit_id",
    "modbus_timeout_s", "modbus_exa1_model", "modbus_exa1_ch1_model",
    "modbus_exa1_ch2_model", "modbus_process_byte_swap", "modbus_accumulator_word_swap",
})


def _validate_config_candidate(previous, candidate):
    """Validate raw entries and effective routes, preserving unchanged quarantine."""
    old_topology = load_exw1_topology(previous, strict=False)
    topology = load_exw1_topology(candidate, strict=False)
    reject_new_quarantine(old_topology.quarantined, topology.quarantined,
                          identity="gateway_id", label="gateway")
    for effective in (False, True):
        old = (_effective_device_registry_config(previous, topology=old_topology)
               if effective else previous)
        new = (_effective_device_registry_config(candidate, topology=topology)
               if effective else candidate)
        old_registry = DeviceRegistry.from_config(old, strict=False)
        registry = DeviceRegistry.from_config(new, strict=False)
        reject_new_quarantine(old_registry.quarantined, registry.quarantined,
                              identity="device_id", label="profile")


def _publish_config_changes(changes):
    if _runtime_recovery_error:
        raise RecoveryRequired("configuration recovery required; restart after repair")
    with config_lock:
        _config_journal().require_clear()
        candidate = copy.deepcopy(config_store)
        if callable(changes):
            changes = changes(copy.deepcopy(candidate))
        candidate.update(copy.deepcopy(changes))
        changed = {key for key in changes if key not in config_store or candidate[key] != config_store[key]}
        if not changed:
            return copy.deepcopy(candidate)
        config_changed = bool(changed - RUNTIME_STATE_KEYS)
        state_changed = bool(changed & RUNTIME_STATE_KEYS)
        if config_changed:
            _validate_config_candidate(config_store, candidate)
            old_sources = _measurement_sources(config_store)
            new_sources = _measurement_sources(candidate)
            epochs = dict(candidate.get("measurement_epochs") or {})
            persisted_sources = dict(candidate.get("measurement_sources") or {})
            for device in old_sources.keys() - new_sources.keys():
                # Removal/disable ends continuity even when the same address returns later.
                epochs[device] = uuid.uuid4().hex
                persisted_sources[device] = old_sources[device]
            for device, source in new_sources.items():
                previous_source = persisted_sources.get(device, old_sources.get(device))
                if previous_source is not None and previous_source != source:
                    epochs[device] = uuid.uuid4().hex
                    persisted_sources[device] = source
            if (epochs != (candidate.get("measurement_epochs") or {}) or
                    persisted_sources != (candidate.get("measurement_sources") or {})):
                candidate.update(measurement_epochs=epochs, measurement_sources=persisted_sources)
                state_changed = True
        if config_changed and state_changed:
            _config_journal().commit(
                {k: v for k, v in candidate.items() if k not in RUNTIME_STATE_KEYS},
                {k: candidate.get(k) for k in RUNTIME_STATE_KEYS})
        elif config_changed:
            save_config(candidate)
        elif state_changed:
            save_runtime_state(candidate)
        config_store.clear()
        config_store.update(candidate)
        if changed & _ROUTE_CONFIG_KEYS:
            _bump_config_generation()
        return copy.deepcopy(candidate)


def update_config_values(*, _build_changes=None, **changes):
    global _acquisition_enabled, device_connected
    if _build_changes is not None and changes:
        raise ValueError("supply either a candidate builder or changes")
    if _build_changes is not None or any(key in _ROUTE_CONFIG_KEYS for key in changes):
        with _configuration_admission.transition():
            previous_source = str(config_store.get("data_source") or "opcua").lower()
            published = _publish_config_changes(_build_changes if _build_changes is not None else changes)
            selected_source = str(published.get("data_source") or "opcua").lower()
            if selected_source != previous_source:
                _acquisition_enabled = False
                device_connected = False
                # Retire only our owned child before admitting the new source.
                # Persisted profiles/topology remain intact for switching back.
                stop_node_worker()
                with _modbus_live_lock:
                    _modbus_live_cache.clear()
            return published
    else:
        # State-only writes inside commands must not wait for their own lease.
        return _publish_config_changes(changes)


def _bump_config_generation():
    global _config_generation
    with _config_generation_lock:
        _config_generation += 1


def current_config_generation() -> int:
    with _config_generation_lock:
        return _config_generation


def config_generation_snapshot() -> dict:
    """Pin the generation this command/read started with so a concurrent save cannot retarget it."""
    with config_lock:
        return {
            "generation": current_config_generation(),
            "config": copy.deepcopy(config_store),
            "opcua_endpoint": str(config_store.get("opcua_endpoint") or ""),
            "ams_password": str(config_store.get("ams_password") or ""),
            "data_source": str(config_store.get("data_source") or ""),
            "modbus_gateways": copy.deepcopy(config_store.get("modbus_gateways")),
            "device_profiles": copy.deepcopy(config_store.get("device_profiles")),
        }


def _require_same_generation(started: dict):
    current = current_config_generation()
    if started.get("generation") != current:
        raise ValueError("configuration changed while this command was in flight")


_active_command_generation = ContextVar("ams_command_generation", default=None)


@contextmanager
def _command_generation():
    """Nested protocol operations retain the generation admitted by their caller."""
    if _runtime_recovery_error:
        raise RecoveryRequired("configuration recovery required; restart after repair")
    _config_journal().require_clear()
    with _configuration_admission.command(config_generation_snapshot) as started:
        if not _acquisition_enabled:
            raise ValueError("Disconnected: click Connect before device access")
        _config_journal().require_clear()
        token = _active_command_generation.set(started)
        try:
            _require_same_generation(started)
            yield
            _require_same_generation(started)
        finally:
            _active_command_generation.reset(token)


def _check_command_generation():
    started = _active_command_generation.get()
    if started is not None:
        _require_same_generation(started)

def config_snapshot(exclude: tuple = ()) -> dict:
    with config_lock:
        return {k: v for k, v in config_store.items() if k not in exclude}

config_lock       = threading.RLock()
schedule_lock     = threading.RLock()
worker_cache_lock = threading.RLock()  # node worker cache ?쎄린/?곌린 蹂댄샇
demo_live_lock    = threading.RLock()
# Import exposes inert defaults only; disk input belongs to initialize_runtime().
config_store     = copy.deepcopy(DEFAULT_CONFIG)

_exw1_topology_lock = threading.RLock()
_exw1_topology_cache = None
_exw1_topology_signature = None
_modbus_client_pool = ModbusClientPool()


def get_exw1_topology():
    global _exw1_topology_cache, _exw1_topology_signature
    signature = json.dumps({
        "gateways": config_store.get("modbus_gateways"),
        "explicit": config_store.get("modbus_gateways_explicit"),
        "host": config_store.get("modbus_host"),
        "port": config_store.get("modbus_port"),
        "unit": config_store.get("modbus_unit_id"),
        "timeout": config_store.get("modbus_timeout_s"),
        "models": [config_store.get("modbus_exa1_ch1_model"), config_store.get("modbus_exa1_ch2_model")],
    }, sort_keys=True, default=str)
    with _exw1_topology_lock:
        if _exw1_topology_cache is None or signature != _exw1_topology_signature:
            topology = load_exw1_topology(config_store, strict=False)
            MODBUS_AMS_CHANNEL_MAP.clear()
            MODBUS_AMS_CHANNEL_MAP.update(topology.channel_map())
            _exw1_topology_cache = topology
            _exw1_topology_signature = signature
        return _exw1_topology_cache


def _modbus_client_for(*, remote_id: str | None = None, gateway_id: str | None = None):
    target = current_target(remote_id)
    if target is not None:
        if target.transport != "modbus" or gateway_id is not None:
            raise ValueError("invalid resolved Modbus operation")
        return _modbus_client_pool.get(ModbusEndpoint(**target.connection))
    topology = get_exw1_topology()
    if remote_id:
        _require_modbus_target(remote_id)
        slot = topology.slot_for_device(remote_id)
        gateway = topology.gateway(slot.gateway_id)
    elif gateway_id:
        gateway = topology.gateway(gateway_id)
    else:
        raise ValueError("an explicit Modbus device or gateway target is required")
    endpoint = ModbusEndpoint(gateway.host, gateway.port, gateway.unit_id, gateway.timeout_s)
    return _modbus_client_pool.get(endpoint)


def _effective_device_registry_config(candidate: dict | None = None, *, topology=None) -> dict:
    source = config_store if candidate is None else candidate
    effective = copy.deepcopy(source)
    profiles = copy.deepcopy(source.get("device_profiles", {}))
    if not isinstance(profiles, dict):
        return effective  # The registry reports the original corrupt container.
    admitted = DeviceRegistry.from_config(source, strict=False, allow_legacy=False)
    invalid_ids = {str(item.get("device_id")).upper() for item in admitted.quarantined}
    topology_mode = (str(source.get("data_source") or "").lower() == "modbus"
                     or bool(source.get("modbus_gateways")) or source.get("modbus_gateways_explicit"))
    has_modbus = any(profile.transport == "modbus" for profile in admitted.all(enabled_only=False))
    if not topology_mode and not has_modbus:
        return effective
    if topology is None:
        topology = get_exw1_topology() if candidate is None else load_exw1_topology(source, strict=False)
    generated_profiles = topology.device_profiles()
    effective["_profiles_authoritative"] = True
    # Keep raw invalid profiles, and never make them valid by overwriting fields
    # with generated addresses. The persisted file is never changed on load.
    for device_id, generated in generated_profiles.items():
        matching = [key for key in profiles if str(key).upper() == device_id]
        reserved_ams = generated.get("metadata", {}).get("reserved_ams_allocation") is True
        if not matching and (not topology_mode or source.get("device_profiles") or source.get("device_profiles_explicit")) and not (topology_mode and reserved_ams):
            continue  # Existing AMS allocations remain discoverable; explicit disabled profiles still win.
        if device_id in invalid_ids:
            continue
        key = matching[0] if matching else device_id
        existing = profiles.get(key, {})
        if matching and str(existing.get("transport") or "opcua").lower() != "modbus":
            continue
        merged = {**existing, **generated}
        merged["enabled"] = generated["enabled"] and existing.get("enabled", True)
        merged["name"] = existing.get("name") or generated["name"]
        merged["metadata"] = {**(existing.get("metadata") or {}), **generated["metadata"]}
        profiles[key] = merged
    errors = []
    for device_id, raw in list(profiles.items()):
        if not isinstance(raw, dict) or str(raw.get("transport") or "opcua").lower() != "modbus":
            continue
        canonical = str(device_id).upper()
        if canonical in invalid_ids:
            continue
        if canonical not in generated_profiles:
            errors.append({"device_id": device_id, "raw": copy.deepcopy(raw),
                           "error": "Modbus device has no valid topology slot; its gateway may be quarantined"})
            profiles.pop(device_id)
    effective["_profile_quarantine"] = errors
    effective["device_profiles"] = profiles
    return effective


def _enabled_modbus_profiles() -> dict:
    if str(config_store.get("data_source") or "opcua").lower() != "modbus":
        return {}
    registry = DeviceRegistry.from_config(_effective_device_registry_config(), strict=False)
    return {profile.device_id: profile for profile in registry.all() if profile.transport == "modbus"}


def _require_modbus_target(remote_id: str):
    requested = str(remote_id or "").upper()
    profile = _enabled_modbus_profiles().get(requested)
    if profile is None:
        raise ValueError(f"Modbus device is absent, disabled or quarantined: {requested}")
    return profile


device_connected = False
_demo_live_state = {
    "started_at": None,
    "raw_accumulated_l": 0.0,
    "last_tick": None,
    "mode": None,
    "flow": None,
    "pressure": None,
    "temperature": None,
}
_migrated_dbs: set = set()             # DB 留덉씠洹몃젅?댁뀡 1???ㅽ뻾 異붿쟻
db_migration_lock = threading.RLock()

def _admitted_config_value(key, default=None):
    target = current_target()
    if target is not None:
        return target.config.get(key, default)
    lease = _configuration_admission.current()
    source = lease["config"] if lease is not None else config_store
    return source.get(key, default)


def get_ams_host()       -> str:   return _admitted_config_value("ams_host")
def get_ams_pass()       -> str:   return _admitted_config_value("ams_password")
def get_ams_channel()    -> int:   return _admitted_config_value("ams_channel", 0)
def get_save_interval()  -> int:   return config_store.get("data_save_interval_s", 5)
def get_kwh_per_m3()     -> float: return config_store.get("energy_kwh_per_m3", 0.11)
def get_price_per_kwh()  -> float: return config_store.get("energy_price_per_kwh", 170.0)
def get_co2_per_kwh()    -> float: return config_store.get("energy_co2_per_kwh", 0.454)
def get_tree_per_co2()   -> float: return config_store.get("energy_tree_per_co2", 6.0)
def is_demo_data_source() -> bool:
    return str(config_store.get("data_source", "opcua") or "opcua").lower() == "demo"

# ?? IODD library ?????????????????????????????????????????
_iodd_index_lock = threading.RLock()
_iodd_index_cache = None
_iodd_index_mtime_ns = None


def _load_iodd_index() -> list:
    global _iodd_index_cache, _iodd_index_mtime_ns
    with _iodd_index_lock:
        source = IODD_INDEX_FILE if IODD_INDEX_FILE.exists() else IODD_INDEX_FILE.with_suffix(IODD_INDEX_FILE.suffix + ".bak")
        try:
            mtime_ns = source.stat().st_mtime_ns
        except OSError:
            return []
        if _iodd_index_cache is not None and _iodd_index_mtime_ns == mtime_ns:
            return copy.deepcopy(_iodd_index_cache)
        data = _load_json_with_backup(IODD_INDEX_FILE, [])
        if not isinstance(data, list):
            data = []
        _iodd_index_cache = data
        _iodd_index_mtime_ns = mtime_ns
        return copy.deepcopy(data)

def _save_iodd_index(items: list):
    global _iodd_index_cache, _iodd_index_mtime_ns
    with _iodd_index_lock:
        _atomic_write_json(IODD_INDEX_FILE, items, backup=True)
        _iodd_index_cache = copy.deepcopy(items)
        _iodd_index_mtime_ns = IODD_INDEX_FILE.stat().st_mtime_ns

def _safe_iodd_filename(name: str) -> str:
    stem = Path(name or "iodd.xml").name
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._")
    if not stem.lower().endswith(".xml"):
        stem += ".xml"
    return stem or "iodd.xml"

def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag

def _extract_iodd_text(root, *names: str) -> Optional[str]:
    targets = {n.lower() for n in names}
    for el in root.iter():
        local = _xml_local_name(str(el.tag)).lower()
        if local in targets:
            for key in ("Text", "Value", "Name", "Id"):
                val = el.attrib.get(key)
                if val:
                    return str(val).strip()
            if el.text and el.text.strip():
                return el.text.strip()
    return None

def _attr_ci(el, *names: str):
    wanted = {n.lower() for n in names}
    for key, value in el.attrib.items():
        if key.lower() in wanted:
            return value
    return None

def _to_int_or_none(value):
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(text, 0)
    except Exception:
        return None

def _to_float_or_none(value):
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except Exception:
        return None

# IO-Link unitCode -> display symbol.
# Standard codes come from the OPC Foundation IO-Link "EngineeringUnits" table.
# 1352/1357 are SMC vendor extensions (absent from the standard table) resolved
# from the device IODD gradients (4200*0.25=1050 l/min; 4200*0.0088275=37.1 cfm).
# Unknown codes fall back to "u#<code>" so a wrong symbol is never shown.
IOLINK_UNIT_CODES = {
    1000: "K", 1001: "°C",
    1038: "l", 1043: "ft³", 1048: "Gal",
    1054: "s", 1059: "h",
    1132: "MPa", 1133: "kPa", 1137: "bar", 1141: "psi",
    1240: "V", 1342: "%", 1348: "m³/min", 1363: "gal/min",
    1352: "l/min", 1357: "cfm",
}

def _unit_symbol(unit_code) -> str:
    code = _to_int_or_none(unit_code)
    if code is None:
        return ""
    return IOLINK_UNIT_CODES.get(code, f"u#{code}")

def _guess_field_name(el, fallback: str) -> str:
    for key in ("Name", "Text", "Id", "ID", "TextId", "NameTextId"):
        value = el.attrib.get(key)
        if value:
            return str(value).strip()
    for child in el:
        local = _xml_local_name(str(child.tag)).lower()
        if local in ("name", "text", "label") and child.text and child.text.strip():
            return child.text.strip()
    return fallback

def _iodd_text_map(root) -> dict:
    texts = {}
    for el in root.iter():
        if _xml_local_name(str(el.tag)).lower() != "text":
            continue
        text_id = el.attrib.get("id")
        value = el.attrib.get("value")
        if text_id and value:
            texts[text_id] = value
    return texts

def _name_from_text_ref(el, texts: dict, fallback: str) -> str:
    for child in el:
        if _xml_local_name(str(child.tag)).lower() != "name":
            continue
        text_id = child.attrib.get("textId")
        if text_id and texts.get(text_id):
            return str(texts[text_id]).strip()
        if child.text and child.text.strip():
            return child.text.strip()
    return _guess_field_name(el, fallback)

def _xsi_type(el) -> str:
    for key, value in el.attrib.items():
        kl = key.lower()
        if kl == "type" or kl == "xsi:type" or kl.endswith("}type"):
            return str(value)
    return ""

def _field_datatype_el(record_item):
    """Return the SimpleDatatype/Datatype element that describes a process RecordItem."""
    for child in record_item.iter():
        if _xml_local_name(str(child.tag)).lower() in ("simpledatatype", "datatype"):
            return child
    return None

def _parse_single_values(datatype_el, texts: dict) -> list:
    """Named enumeration entries (SingleValue) for one process field, e.g. true->"Error"."""
    if datatype_el is None:
        return []
    out = []
    for sv in datatype_el.iter():
        if _xml_local_name(str(sv.tag)).lower() != "singlevalue":
            continue
        raw = sv.attrib.get("value")
        if raw is None:
            continue
        out.append({"value": raw, "name": _name_from_text_ref(sv, texts, "")})
    return out

def _parse_value_range(datatype_el) -> Optional[dict]:
    if datatype_el is None:
        return None
    for vr in datatype_el.iter():
        if _xml_local_name(str(vr.tag)).lower() != "valuerange":
            continue
        lo = _to_int_or_none(vr.attrib.get("lowerValue"))
        hi = _to_int_or_none(vr.attrib.get("upperValue"))
        if lo is not None or hi is not None:
            return {"lower": lo, "upper": hi}
    return None

def _parse_iodd_pd_formatting(root) -> dict:
    """Map ProcessDataIn subindex -> display formatting (gradient/offset/unit/displayFormat).

    Process-data display formatting lives either on <ProcessDataRecordItemInfo> (the IODD
    spec location, preferred) or on <RecordItemRef> elements that reference the standard
    process-data input variable (V_ProcessDataInput) inside the menu collection. The first
    occurrence per subindex wins, so the device's default unit variant is used.
    """
    fmt = {}
    pd_var_ids = {"v_processdatainput"}

    def store(subindex, gradient, offset, unit_code, display_format):
        si = _to_int_or_none(subindex)
        if si is None or si in fmt:
            return
        if gradient is None and unit_code is None and offset is None and not display_format:
            return
        fmt[si] = {
            "gradient": gradient,
            "offset": offset,
            "unit_code": _to_int_or_none(unit_code),
            "unit": _unit_symbol(unit_code),
            "display_format": display_format or "",
        }

    for el in root.iter():
        if _xml_local_name(str(el.tag)).lower() != "processdatarecorditeminfo":
            continue
        store(_attr_ci(el, "subindex"),
              _to_float_or_none(_attr_ci(el, "gradient")),
              _to_float_or_none(_attr_ci(el, "offset")),
              _attr_ci(el, "unitCode"),
              _attr_ci(el, "displayFormat"))
    for el in root.iter():
        if _xml_local_name(str(el.tag)).lower() != "recorditemref":
            continue
        if (_attr_ci(el, "variableId") or "").lower() not in pd_var_ids:
            continue
        store(_attr_ci(el, "subindex"),
              _to_float_or_none(_attr_ci(el, "gradient")),
              _to_float_or_none(_attr_ci(el, "offset")),
              _attr_ci(el, "unitCode"),
              _attr_ci(el, "displayFormat"))
    return fmt

def _parse_iodd_process_fields(root) -> list:
    fields = []
    seen = set()
    texts = _iodd_text_map(root)
    process_data_in = None
    for candidate in root.iter():
        if _xml_local_name(str(candidate.tag)).lower() == "processdatain":
            process_data_in = candidate
            break
    if process_data_in is None:
        return fields

    for el in process_data_in.iter():
        if _xml_local_name(str(el.tag)).lower() != "recorditem":
            continue

        bit_offset = _to_int_or_none(_attr_ci(el, "bitOffset", "BitOffset", "bitPosition"))
        byte_offset = _to_int_or_none(_attr_ci(el, "byteOffset", "ByteOffset", "offset"))
        if bit_offset is None and byte_offset is not None:
            bit_offset = byte_offset * 8
        bit_length = _to_int_or_none(_attr_ci(el, "bitLength", "BitLength", "length", "Length"))
        datatype_el = _field_datatype_el(el)
        data_type = ""
        if datatype_el is not None:
            data_type = _xsi_type(datatype_el)
            if bit_length is None:
                bit_length = _to_int_or_none(_attr_ci(datatype_el, "bitLength", "BitLength", "length", "Length"))
        if bit_length is None:
            bit_length = 1
        if bit_offset is None or bit_length <= 0 or bit_length > 64:
            continue

        subindex = _to_int_or_none(_attr_ci(el, "subindex", "Subindex"))
        name = _name_from_text_ref(el, texts, f"PDin[{subindex if subindex is not None else len(fields)}]")
        data_type = data_type or (
            _attr_ci(el, "dataType", "Datatype", "datatype", "type", "Type")
            or _attr_ci(el, "dataTypeRef", "DatatypeRef", "typeRef")
            or ""
        )
        key = (bit_offset, bit_length, name)
        if key in seen:
            continue
        seen.add(key)
        field = {
            "name": name,
            "subindex": subindex,
            "bit_offset": bit_offset,
            "bit_length": bit_length,
            "data_type": str(data_type),
        }
        single_values = _parse_single_values(datatype_el, texts)
        if single_values:
            field["single_values"] = single_values
        value_range = _parse_value_range(datatype_el)
        if value_range:
            field["value_range"] = value_range
        fields.append(field)
        if len(fields) >= 32:
            break

    formatting = _parse_iodd_pd_formatting(root)
    for field in fields:
        fmt = formatting.get(field.get("subindex"))
        if not fmt:
            continue
        for k, v in fmt.items():
            if v not in (None, ""):
                field[k] = v

    fields.sort(key=lambda x: (x["bit_offset"], x["bit_length"], x["name"]))
    return fields

def _parse_iodd_process_lengths(root) -> dict:
    lengths = {
        "process_data_in_bit_length": None,
        "process_data_in_byte_length": None,
        "process_data_out_bit_length": None,
        "process_data_out_byte_length": None,
    }
    for el in root.iter():
        local = _xml_local_name(str(el.tag)).lower()
        if local not in ("processdatain", "processdataout"):
            continue
        bit_length = _to_int_or_none(_attr_ci(el, "bitLength", "BitLength"))
        if bit_length is None:
            for child in el.iter():
                child_local = _xml_local_name(str(child.tag)).lower()
                if child_local == "datatype":
                    bit_length = _to_int_or_none(_attr_ci(child, "bitLength", "BitLength"))
                    if bit_length is not None:
                        break
        if bit_length is None or bit_length <= 0:
            continue
        prefix = "process_data_in" if local == "processdatain" else "process_data_out"
        lengths[f"{prefix}_bit_length"] = bit_length
        lengths[f"{prefix}_byte_length"] = (bit_length + 7) // 8
    return lengths

# Bump when the parsed process-field schema changes so cached IODD index entries
# are re-parsed (older caches lack SingleValue names / scaling / unit metadata).
IODD_FIELD_SCHEMA = 2

def _parse_iodd_metadata(xml_text: str, filename: str) -> dict:
    meta = {
        "filename": filename,
        "vendor": "",
        "device": Path(filename).stem,
        "vendor_id": "",
        "device_id": "",
        "revision": "",
        "parse_status": "filename_only",
    }
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
        meta.update({
            "vendor": _extract_iodd_text(root, "VendorName", "VendorText", "Vendor") or "",
            "device": _extract_iodd_text(root, "DeviceName", "ProductName", "ProductText") or meta["device"],
            "vendor_id": _extract_iodd_text(root, "VendorId", "VendorID") or "",
            "device_id": _extract_iodd_text(root, "DeviceId", "DeviceID") or "",
            "revision": _extract_iodd_text(root, "Revision", "IoddVersion", "IODDVersion") or "",
            "process_data_in_fields": _parse_iodd_process_fields(root),
            "parse_status": "metadata",
            "pd_schema": IODD_FIELD_SCHEMA,
        })
        meta.update(_parse_iodd_process_lengths(root))
    except Exception as e:
        meta["parse_status"] = f"xml_parse_failed: {type(e).__name__}"
    return meta

def _enrich_iodd_item(item: dict) -> tuple[dict, bool]:
    if (item.get("pd_schema") == IODD_FIELD_SCHEMA
            and item.get("process_data_in_byte_length") is not None
            and item.get("process_data_in_fields")):
        field_names = {str(x.get("name", "")) for x in item.get("process_data_in_fields") or []}
        if not all(name.startswith("PDin[") for name in field_names if name):
            return item, False
    if not item.get("stored_filename"):
        return item, False
    path = IODD_DIR / str(item.get("stored_filename"))
    if not path.exists():
        return item, False
    try:
        xml_text = path.read_text(encoding="utf-8-sig")
        meta = _parse_iodd_metadata(xml_text, item.get("filename") or path.name)
        enriched = dict(item)
        for key in (
            "process_data_in_bit_length",
            "process_data_in_byte_length",
            "process_data_out_bit_length",
            "process_data_out_byte_length",
        ):
            if meta.get(key) is not None:
                enriched[key] = meta.get(key)
        if meta.get("process_data_in_fields"):
            enriched["process_data_in_fields"] = meta.get("process_data_in_fields")
        enriched["pd_schema"] = IODD_FIELD_SCHEMA
        return enriched, enriched != item
    except Exception as e:
        print(f"[IODD] enrich failed: {type(e).__name__}: {e}")
        return item, False

def _get_iodd_by_id(iodd_id: Optional[str]) -> Optional[dict]:
    if not iodd_id:
        return None
    items = _load_iodd_index()
    changed = False
    for idx, item in enumerate(items):
        item, item_changed = _enrich_iodd_item(item)
        if item_changed:
            items[idx] = item
            changed = True
        if item.get("id") == iodd_id:
            if changed:
                _save_iodd_index(items)
            return item
    if changed:
        _save_iodd_index(items)
    return None

def _assignment_key(remote_id: str, port: str) -> str:
    return f"{remote_id or 'AMS00'}:{port or 'port4'}"

def get_iodd_assignment(remote_id: str = "AMS00", port: str = "port4") -> Optional[dict]:
    assignments = config_store.get("iodd_assignments", {}) or {}
    iodd_id = assignments.get(_assignment_key(remote_id, port))
    item = _get_iodd_by_id(iodd_id)
    if not item:
        return None
    return {
        "id": item.get("id"),
        "name": item.get("device") or item.get("filename"),
        "vendor": item.get("vendor") or "",
        "filename": item.get("filename") or "",
        "parse_status": item.get("parse_status") or "",
        "field_count": len(item.get("process_data_in_fields") or []),
        "pdin_bit_length": item.get("process_data_in_bit_length"),
        "pdin_byte_length": item.get("process_data_in_byte_length"),
        "pdout_bit_length": item.get("process_data_out_bit_length"),
        "pdout_byte_length": item.get("process_data_out_byte_length"),
    }

def _hex_bytes_to_int(hex_bytes: list) -> int:
    value = 0
    for byte in hex_bytes:
        if byte == "--":
            byte = "00"
        value = (value << 8) | (int(str(byte), 16) & 0xFF)
    return value

def _extract_pd_bits(hex_bytes: list, bit_offset: int, bit_length: int) -> int:
    # IO-Link process data is big-endian: array byte 0 is the most-significant byte
    # (verified against the master: flow 4000=0x0FA0 sits in the high bytes, MSB-left).
    # IODD bitOffset is counted from the LSB of the whole process data.
    total_bits = len(hex_bytes) * 8
    if bit_offset < 0 or bit_length <= 0 or bit_offset + bit_length > total_bits:
        raise ValueError("bit range outside PDin")
    first = (total_bits - bit_offset - bit_length) // 8
    last = (total_bits - bit_offset - 1) // 8
    selected = hex_bytes[first:last + 1]
    if any(not isinstance(value, str) or len(value) != 2 or any(c not in "0123456789abcdefABCDEF" for c in value) for value in selected):
        raise ValueError("unavailable or invalid PDin byte")
    raw = _hex_bytes_to_int(selected)
    bit_offset -= (len(hex_bytes) - last - 1) * 8
    return (raw >> bit_offset) & ((1 << bit_length) - 1)

def _resolve_state_name(single_values, raw, bit_length) -> Optional[str]:
    """Map a decoded raw value to its IODD SingleValue name (e.g. true -> "Error active")."""
    if not single_values:
        return None
    for sv in single_values:
        v = sv.get("value")
        if v is None:
            continue
        s = str(v).strip().lower()
        if s in ("true", "false"):
            sv_int = 1 if s == "true" else 0
        else:
            sv_int = _to_int_or_none(v)
        if sv_int is not None and sv_int == raw:
            return sv.get("name") or None
    return None

def _format_display_value(scaled: float, display_format) -> str:
    """Format a scaled value honoring an IODD displayFormat like "Dec.0"/"Dec.1"."""
    decimals = None
    if display_format and "." in str(display_format):
        decimals = _to_int_or_none(str(display_format).rsplit(".", 1)[-1])
    if decimals is not None and decimals >= 0:
        return f"{scaled:.{decimals}f}"
    if float(scaled).is_integer():
        return str(int(scaled))
    return f"{scaled:.3f}".rstrip("0").rstrip(".")

def _is_error_name(name) -> bool:
    n = str(name or "").lower()
    return any(tok in n for tok in ("error", "alarm", "fault"))

def decode_iodd_pdin(hex_bytes: list, iodd_id: Optional[str]) -> tuple[list, str]:
    item = _get_iodd_by_id(iodd_id)
    if not item:
        return [], "raw_hex_only"
    fields = item.get("process_data_in_fields") or []
    if not fields:
        return [], "iodd_assigned_no_process_fields"
    active_len = _to_int_or_none(item.get("process_data_in_byte_length"))
    active_hex = list(hex_bytes or [])
    if active_len and active_len > 0:
        active_hex = active_hex[:min(16, active_len)]
        active_hex += ["--"] * max(0, min(16, active_len) - len(active_hex))
    decoded = []
    for field in fields[:32]:
        bit_length = field.get("bit_length")
        entry = {
            "name": field.get("name") or f"Bit {field.get('bit_offset')}",
            "bit_offset": field.get("bit_offset"),
            "bit_length": bit_length,
            "data_type": field.get("data_type") or "",
            "subindex": field.get("subindex"),
        }
        if field.get("value_range"):
            entry["value_range"] = field.get("value_range")
        if field.get("single_values"):
            entry["is_enum"] = True
        try:
            raw = _extract_pd_bits(active_hex, int(field["bit_offset"]), int(field["bit_length"]))
        except Exception as e:
            entry["value"] = None
            entry["error"] = str(e)
            decoded.append(entry)
            continue
        entry["hex"] = f"0x{raw:X}"
        width = int(field["bit_length"])
        if str(field.get("data_type") or "").split(":")[-1] == "IntegerT" and width > 0 and raw & (1 << (width - 1)):
            raw -= 1 << width
        entry["value"] = raw
        state_name = _resolve_state_name(field.get("single_values"), raw, bit_length)
        if state_name:
            entry["state_name"] = state_name
        gradient = field.get("gradient")
        if gradient is not None:
            try:
                scaled = raw * float(gradient) + float(field.get("offset") or 0)
                entry["scaled"] = scaled
                entry["display_value"] = _format_display_value(scaled, field.get("display_format"))
            except Exception:
                pass
        if field.get("unit"):
            entry["unit"] = field.get("unit")
        decoded.append(entry)
    return decoded, "iodd_decoded_generic"

def _build_pd_analysis(decoded: list, item: Optional[dict]) -> Optional[dict]:
    """Generic top-level summary derived purely from decoded IODD fields (no device hardcoding).

    Splits fields into boolean signals and analog/enum values, and picks a primary
    measurement (a scaled value with a unit that is not an enum) for the headline.
    """
    if not decoded:
        return None
    signals, values = [], []
    for d in decoded:
        if d.get("error"):
            continue
        if (d.get("bit_length") or 0) == 1:
            on = bool(d.get("value"))
            signals.append({
                "label": d.get("name"),
                "state": "on" if on else "off",
                "value": d.get("state_name") or ("ON" if on else "OFF"),
                "raw": d.get("value"),
                "is_error": _is_error_name(d.get("name")),
            })
        else:
            disp = d.get("display_value")
            values.append({
                "label": d.get("name"),
                "value": disp if disp is not None else d.get("value"),
                "unit": d.get("unit") or "",
                "raw": d.get("value"),
                "state_name": d.get("state_name") or "",
                "is_measurement": bool((d.get("unit") or d.get("scaled") is not None) and not d.get("is_enum")),
            })
    # Surface real measurements (unit/scaled) ahead of internal counters so the
    # summary tiles headline meaningful values (e.g. Flow, Accumulated) before
    # raw enum/level fields. Stable sort keeps IODD field order within each group.
    values.sort(key=lambda v: 0 if v.get("is_measurement") else 1)
    primary = next((v for v in values if v.get("is_measurement")), values[0] if values else None)
    device = (item or {}).get("device") or (item or {}).get("name") or (item or {}).get("filename") or "IODD"
    return {
        "profile": device,
        "primary": primary,
        "signals": signals,
        "values": values,
    }

def attach_iodd_context(data: dict, remote_id: str = "AMS00") -> dict:
    assignment = get_iodd_assignment(remote_id, "port4")
    data["port4_iodd"] = assignment
    if assignment:
        decoded, status = decode_iodd_pdin(data.get("port4_pdin_hex") or [], assignment.get("id"))
        data["port4_decoded"] = decoded
        data["port4_decode_status"] = status
        data["port4_analysis"] = _build_pd_analysis(decoded, _get_iodd_by_id(assignment.get("id")))
    else:
        data["port4_decoded"] = []
        data["port4_decode_status"] = "raw_hex_only"
        data["port4_analysis"] = None
    return data

def opcua_endpoint_from_ams_host(ams_host: str) -> str:
    parsed = urlparse(ams_host if "://" in ams_host else f"https://{ams_host}")
    host = parsed.hostname or ams_host.replace("https://", "").replace("http://", "").split(":")[0].strip("/")
    return f"opc.tcp://{host}:4840"

def load_node_config() -> dict:
    path = NODES_FILE if NODES_FILE.exists() else BUNDLE_DIR / "nodes.json"
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        remotes = data.get("remotes")
        if not isinstance(remotes, dict):
            raise ValueError("nodes.json must contain a remotes object")
        return data
    except Exception as e:
        print(f"[NODES] load failed: {type(e).__name__}: {e}")
        return {"version": 1, "remotes": {}}

def _read_node_maps(node_config: dict) -> dict[str, dict[str, str]]:
    remotes = node_config.get("remotes", {}) or {}
    return {
        remote_id: dict(remote_cfg.get("read") or {})
        for remote_id, remote_cfg in remotes.items()
        if isinstance(remote_cfg, dict)
    }

def _write_node_maps(node_config: dict) -> dict[str, dict[str, str]]:
    remotes = node_config.get("remotes", {}) or {}
    return {
        remote_id: dict(remote_cfg.get("write") or {})
        for remote_id, remote_cfg in remotes.items()
        if isinstance(remote_cfg, dict)
    }

OPCUA_NODE_CONFIG = {"version": 1, "remotes": {}}
REMOTE_NODE_MAPS = _read_node_maps(OPCUA_NODE_CONFIG)
REMOTE_SIGNAL_NODES = _write_node_maps(OPCUA_NODE_CONFIG)
AMS00_NODES = REMOTE_NODE_MAPS.get("AMS00", {})
AMS01_NODES = REMOTE_NODE_MAPS.get("AMS01", {})

main_loop        = None   # asyncio event loop, set in startup()
node_worker_proc = None   # persistent node-opcua worker subprocess
node_worker_stdout = None
node_worker_stderr = None
node_worker_owner = None
node_worker_lock = threading.RLock()
_worker_last_restart_attempt = 0.0
_WORKER_RESTART_MIN_INTERVAL_S = 5.0

WORKER_PORT     = int(os.environ.get("WORKER_PORT", "7100"))

_worker_remotes_cache: dict = {}   # remoteId ??parsed data dict
_worker_last_fetch: float   = 0.0  # epoch seconds of last /data call
worker_fetch_lock = threading.Lock()
worker_status_lock = threading.Lock()
_worker_status_cache: dict = {}
_worker_status_at = 0.0

# ?? ?먮꼫吏 怨꾩궛 ???????????????????????????????????????????
def calculate_energy(accumulated_flow_l: float) -> dict:
    invalid = {"rube": None, "kwh": None, "cost_krw": None, "co2_kg": None, "tree": None,
               "error": "invalid_energy_configuration_or_measurement"}
    coefficients = [finite_number(value) for value in
                    (get_kwh_per_m3(), get_price_per_kwh(), get_co2_per_kwh(), get_tree_per_co2())]
    raw = finite_number(accumulated_flow_l)
    if (raw is None or raw < 0 or any(value is None or value < 0 for value in coefficients)
            or coefficients[-1] <= 0):
        return invalid
    rube = raw / 1000.0
    kwh = rube * coefficients[0]
    cost = kwh * coefficients[1]
    co2 = kwh * coefficients[2]
    tree = co2 / coefficients[3]
    if any(finite_number(value) is None for value in (rube, kwh, cost, co2, tree)):
        return invalid
    return {
        "rube":     round(rube, 4),
        "kwh":      round(kwh,  4),
        "cost_krw": round(cost, 0),
        "co2_kg":   round(co2,  4),
        "tree":     round(tree, 4),
    }

def _derive_energy_for_storage(raw):
    """A failed derived metric must never prevent persistence of raw telemetry."""
    try:
        return calculate_energy(raw)
    except Exception:
        return {"rube": None, "kwh": None, "cost_krw": None, "co2_kg": None, "tree": None,
                "error": "energy_derivation_failed"}


def apply_usage_tracking(data: dict, persist: bool = False) -> dict:
    with config_lock:
        raw = float(data.get("accumulated_flow_l") or 0)
        last = config_store.get("dashboard_last_raw_accumulated_l")
        total = float(config_store.get("dashboard_total_flow_l") or 0)
        reset_detected = False
        if last is None:
            delta = 0.0
        elif raw >= float(last):
            delta = raw - float(last)
        else:
            reset_detected = True
            delta = 0.0
        dashboard_total = total + delta
        data["raw_accumulated_flow_l"] = raw
        data["delta_flow_l"] = round(delta, 3)
        data["dashboard_total_flow_l"] = round(dashboard_total, 3)
        data["reset_detected"] = reset_detected
        data["energy"] = _derive_energy_for_storage(dashboard_total)
        if persist:
            update_config_values(
                dashboard_last_raw_accumulated_l=raw,
                dashboard_total_flow_l=dashboard_total,
            )
    return data

# ?? SQLite ?붾퀎 DB ?????????????????????????????????????????
def get_db_path(dt: datetime = None) -> Path:
    if dt is None: dt = datetime.now()
    return DB_DIR / f"ams_data_{dt.strftime('%Y_%m')}.db"

def get_db_conn(dt: datetime = None) -> sqlite3.Connection:
    path = get_db_path(dt)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    path_key = str(path)
    try:
        with db_migration_lock:
            if path_key not in _migrated_dbs:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ams_log (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp   TEXT    NOT NULL,
                        remote_id   TEXT    DEFAULT 'AMS00',
                        pressure    REAL,
                        temperature REAL,
                        flow        REAL,
                        accumulated INTEGER,
                        raw_accumulated REAL,
                        delta_flow  REAL,
                        reset_detected INTEGER,
                        ams_status  TEXT,
                        ams_code    INTEGER,
                        diagnostic  TEXT,
                        energy_kwh  REAL,
                        energy_cost REAL,
                        energy_co2  REAL
                    )
                """)
                cols = [r[1] for r in conn.execute("PRAGMA table_info(ams_log)").fetchall()]
                for col, typ in [
                    ("energy_kwh","REAL"),("energy_cost","REAL"),("energy_co2","REAL"),
                    ("raw_accumulated","REAL"),("delta_flow","REAL"),("reset_detected","INTEGER"),
                    ("remote_id","TEXT"),
                ]:
                    if col not in cols:
                        conn.execute(f"ALTER TABLE ams_log ADD COLUMN {col} {typ}")
                conn.execute("UPDATE ams_log SET remote_id='AMS00' WHERE remote_id IS NULL OR remote_id='' ")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON ams_log(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_remote ON ams_log(remote_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_remote_ts ON ams_log(remote_id,timestamp)")
                conn.commit()
                _migrated_dbs.add(path_key)
    except Exception:
        conn.close()
        raise
    return conn

_history_counter_lock = threading.RLock()
_history_last_raw_by_device = {}

def _restore_history_raw(conn, remote_id: str, current_path: Path):
    """Read committed raw litres only; accumulated may be an adjusted lifetime total."""
    def latest(db):
        columns = {row[1] for row in db.execute("PRAGMA table_info(ams_log)")}
        if not {"remote_id", "raw_accumulated", "id"}.issubset(columns):
            return None
        row = db.execute(
            "SELECT raw_accumulated FROM ams_log WHERE remote_id=? ORDER BY id DESC LIMIT 1",
            (remote_id,),
        ).fetchone()
        # A latest row with unknown raw is a discontinuity, not permission to use
        # an older lifetime counter or bridge an unobserved reset.
        return (None if row[0] is None else float(row[0]),) if row else None

    found = latest(conn)
    if found is not None:
        return found[0]
    for path in sorted(DB_DIR.glob("ams_data_????_??.db"), reverse=True):
        if path.name >= current_path.name:
            continue
        previous = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0)
        try:
            found = latest(previous)
            if found is not None:
                return found[0]
        finally:
            previous.close()
    return None


def _stamp_measurement(profile, row):
    # A receipt timestamp is not evidence of a measurement. Keep such rows invalid.
    row = dict(row)
    if not row.get("timestamp"):
        row.update(device_connected=False, online=False, quality="unavailable")
        row["error"] = "measurement_timestamp_missing"
    return history_contract.stamp(profile, row, config_snapshot(), REMOTE_NODE_MAPS.get(profile.device_id))


def _measurement_sources(cfg):
    registry = DeviceRegistry.from_config(_effective_device_registry_config(cfg),
        opcua_device_ids=set(REMOTE_NODE_MAPS) | set(REMOTE_SIGNAL_NODES), strict=False)
    return {p.device_id: history_contract.source_key(p, cfg, REMOTE_NODE_MAPS.get(p.device_id))
            for p in registry.all()}


def save_to_db(data: dict):
    if data.get("source_key"):
        with config_lock, _history_counter_lock:
            try:
                device = str(data.get("device_id") or data.get("remote_id") or "").upper()
                cfg = config_snapshot()
                if (_measurement_sources(cfg).get(device) != data["source_key"] or
                        str((cfg.get("measurement_epochs") or {}).get(device, "initial")) !=
                        str(data.get("measurement_generation", "initial"))):
                    return {"ok": False, "error": "inactive_measurement_identity"}
                result = history_contract.save(DB_DIR, get_db_conn, data, calculate_energy)
                if result.get("committed") and result.get("raw_accumulated_flow_l") is not None:
                    _prepare_committed_usage_cache()
                    identity = (device, data["source_key"],
                                str(data.get("measurement_generation", "initial")),
                                history_contract._simulated(data))
                    _committed_usage_cache[identity] = result["committed_total_flow_l"]
                return result
            except Exception as exc:
                return {"ok": False, "error": f"history_write_failed: {type(exc).__name__}"}
    return {"ok": False, "error": "measurement_identity_required"}


def _legacy_save_to_db_for_tests(data: dict):
    """Retired pre-Stage3 algorithm retained solely for historical regression fixtures."""
    if not sample_usable(data, "accumulated_flow_l"):
        return {"ok": False, "error": "invalid_counter_sample"}
    conn = None
    # Keep baseline selection, persistence and publication in one ordered transaction.
    _history_counter_lock.acquire()
    try:
        remote_id = str(data.get("device_id") or data.get("remote_id") or "AMS00").upper()
        is_hub_sample = bool(data.get("transport")) or remote_id == "COMBINED" or (
            str(data.get("data_source") or "").lower() == "modbus" and remote_id in MODBUS_AMS_CHANNEL_MAP
        )
        save_time = datetime.now()
        conn = get_db_conn(save_time)
        if is_hub_sample:
            data = copy.deepcopy(data)
            raw = float(data.get("accumulated_flow_l") or 0)
            last = _history_last_raw_by_device.get(remote_id)
            if remote_id not in _history_last_raw_by_device:
                last = _restore_history_raw(conn, remote_id, get_db_path(save_time))
            reset_detected = last is not None and raw < last
            delta = 0.0 if last is None or reset_detected else raw - last
            data.update({
                "timestamp": data.get("timestamp") or data.get("captured_at") or datetime.now().isoformat(timespec="seconds"),
                "remote_id": remote_id,
                "raw_accumulated_flow_l": raw,
                "delta_flow_l": round(delta, 3),
                "dashboard_total_flow_l": raw,
                "reset_detected": reset_detected,
                "energy": _derive_energy_for_storage(raw),
            })
        else:
            data = apply_usage_tracking(data, persist=False)
        energy = data.get("energy", {})
        conn.execute("""
            INSERT INTO ams_log
              (timestamp,remote_id,pressure,temperature,flow,accumulated,
               raw_accumulated,delta_flow,reset_detected,
               ams_status,ams_code,diagnostic,energy_kwh,energy_cost,energy_co2)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data.get("timestamp"),
            data.get("remote_id", "AMS00"),
            data.get("pressure_mpa"),
            data.get("temperature_c"),
            data.get("instant_flow_l_min"),
            data.get("dashboard_total_flow_l"),
            data.get("raw_accumulated_flow_l"),
            data.get("delta_flow_l"),
            1 if data.get("reset_detected") else 0,
            data.get("ams_status"),
            data.get("ams_code"),
            data.get("diagnostic"),
            energy.get("kwh"),
            energy.get("cost_krw"),
            energy.get("co2_kg"),
        ))
        conn.commit()
        if is_hub_sample:
            _history_last_raw_by_device[remote_id] = raw
        else:
            update_config_values(
                dashboard_last_raw_accumulated_l=data.get("raw_accumulated_flow_l"),
                dashboard_total_flow_l=data.get("dashboard_total_flow_l"),
            )
    except Exception as e:
        print(f"[DB] ????ㅻ쪟: {e}")
    finally:
        try:
            if conn is not None:
                conn.close()
        finally:
            _history_counter_lock.release()

def _history_periods(start_dt: datetime, end_dt: datetime, unit: str):
    if unit == "second":
        return None
    if unit == "minute":
        cur = start_dt.replace(second=0, microsecond=0)
        end_cur = end_dt.replace(second=0, microsecond=0)
        step = lambda d: d + timedelta(minutes=1)
        fmt = "%Y-%m-%d %H:%M"
    elif unit == "hour":
        cur = start_dt.replace(minute=0, second=0, microsecond=0)
        end_cur = end_dt.replace(minute=0, second=0, microsecond=0)
        step = lambda d: d + timedelta(hours=1)
        fmt = "%Y-%m-%d %H"
    elif unit == "day":
        cur = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_cur = end_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        step = lambda d: d + timedelta(days=1)
        fmt = "%Y-%m-%d"
    elif unit == "month":
        cur = start_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_cur = end_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        step = lambda d: d.replace(month=d.month+1) if d.month < 12 else d.replace(year=d.year+1, month=1)
        fmt = "%Y-%m"
    else:
        return None
    periods = []
    while cur <= end_cur:
        periods.append(cur.strftime(fmt))
        cur = step(cur)
    return periods


HISTORY_MAX_PERIODS = 20_000
RAW_EXPORT_MAX_DAYS = 366


def _validated_history_range(start: str, end: str, unit: Optional[str] = None,
                             *, raw_export: bool = False) -> tuple[datetime, datetime]:
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    if end_dt < start_dt:
        raise ValueError("end date must be on or after start date")
    days = (end_dt.date() - start_dt.date()).days + 1
    if raw_export and days > RAW_EXPORT_MAX_DAYS:
        raise ValueError(f"raw CSV range must be <= {RAW_EXPORT_MAX_DAYS} days")
    seconds_per_period = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
        "month": 2_678_400,
    }
    if unit not in seconds_per_period:
        raise ValueError("unit must be second, minute, hour, day, or month")
    estimated = max(1, int((end_dt - start_dt).total_seconds() / seconds_per_period[unit]) + 1)
    if estimated > HISTORY_MAX_PERIODS:
        raise ValueError(
            f"query would create about {estimated:,} periods; maximum is {HISTORY_MAX_PERIODS:,}"
        )
    return start_dt, end_dt

_HISTORY_ALL_TOKENS = {"", "ALL", "ALL DEVICES"}
_HISTORY_ALL_EXCLUDE = ("COMBINED", "IO13")

def _history_remote_filter(remote_id: str | None):
    """SQL fragment + trailing bound params for a history remote_id selector.

    A specific device id filters to exactly that device. Empty / "ALL" / "ALL DEVICES"
    means the plant-wide combined view: real device rows only, excluding the stored
    COMBINED aggregate rows (summing those in would double-count) and non-process
    devices like IO13.
    """
    normalized = (remote_id or "").strip().upper()
    if normalized in _HISTORY_ALL_TOKENS:
        placeholders = ",".join("?" for _ in _HISTORY_ALL_EXCLUDE)
        return f"AND remote_id NOT IN ({placeholders})", tuple(_HISTORY_ALL_EXCLUDE)
    return "AND remote_id=?", (remote_id,)

def query_history(start: str, end: str, unit: str, field: str, remote_id: str = "ALL",
                  *, source=None, generation=None, include_simulated=None):
    start_dt, last_dt = _validated_history_range(start, end, unit)
    end_dt = last_dt.replace(hour=0, minute=0, second=0) + timedelta(days=1)
    return history_contract.query(
        DB_DIR, start_dt, end_dt, unit, field, remote_id,
        _history_periods(start_dt, last_dt, unit), calculate_energy,
        site_timezone=config_snapshot().get("site_timezone", "Asia/Seoul"),
        source=source, generation=generation, include_simulated=include_simulated)


def _legacy_query_history(start: str, end: str, unit: str, field: str, remote_id: str = "ALL"):
    fmt_map  = {"second":"%Y-%m-%d %H:%M:%S","minute":"%Y-%m-%d %H:%M","hour":"%Y-%m-%d %H","day":"%Y-%m-%d","month":"%Y-%m"}
    ts_fmt   = fmt_map.get(unit, "%Y-%m-%d")
    field_map = {
        "flow": "flow",
        "pressure": "pressure",
        "temperature": "temperature",
        "accumulated": "accumulated",
        "energy_kwh": "energy_kwh",
        "energy_cost": "energy_cost",
        "energy_co2": "energy_co2",
    }
    if field not in field_map:
        raise ValueError("unsupported history field")
    all_devices = (remote_id or "").strip().upper() in _HISTORY_ALL_TOKENS
    if all_devices and field in {"pressure", "temperature"}:
        raise ValueError("Select one device for pressure or temperature")
    if all_devices and field.startswith("energy_"):
        factor = get_kwh_per_m3() / 1000.0
        if field == "energy_cost":
            factor *= get_price_per_kwh()
        elif field == "energy_co2":
            factor *= get_co2_per_kwh()
        result = query_history(start, end, unit, "accumulated", remote_id)
        for row in result:
            value = round(row["usage"] * factor, 4)
            row.update(avg=value, max=value, min=value, aggregation="period_total_from_usage", coefficient_basis="current_configuration")
        return result
    start_dt, end_dt = _validated_history_range(start, end, unit)
    start_bound = start_dt.isoformat(timespec="seconds")
    end_bound = end_dt.isoformat(timespec="seconds")
    months   = []
    cur = start_dt.replace(day=1)
    while cur <= end_dt:
        months.append(cur)
        cur = cur.replace(month=cur.month+1) if cur.month < 12 else cur.replace(year=cur.year+1, month=1)
    rows = []
    for m in months:
        db_path = get_db_path(m)
        if not db_path.exists(): continue
        try:
            conn = get_db_conn(m)
            remote_filter, remote_params = _history_remote_filter(remote_id)
            params_base   = (start_bound, end_bound) + remote_params
            demo_expr = (
                "SUM(CASE WHEN UPPER(COALESCE(ams_status,''))='DEMO' "
                "OR COALESCE(diagnostic,'') LIKE 'DEMO SEED%' THEN 1 ELSE 0 END)"
            )
            if field == "accumulated":
                res = conn.execute(f"""
                    SELECT strftime('{ts_fmt}',replace(timestamp,'T',' ')) AS period,
                           SUM(COALESCE(delta_flow,0)) AS usage_l,
                           MAX(accumulated) AS dashboard_total_l,
                           COUNT(*),
                           {demo_expr} AS demo_count
                    FROM ams_log
                    WHERE timestamp>=? AND timestamp<=? {remote_filter}
                    GROUP BY period ORDER BY period
                """, params_base)
            elif all_devices and field == "flow":
                # Aggregate devices at the recorded second before temporal stats.
                # Missing device samples are not interpolated or forward-filled.
                res = conn.execute(f"""
                    WITH samples AS (
                        SELECT strftime('%Y-%m-%d %H:%M:%S',replace(timestamp,'T',' ')) AS sample_time,
                               SUM(flow) AS total_flow, COUNT(*) AS sample_count,
                               {demo_expr} AS demo_count
                        FROM ams_log
                        WHERE timestamp>=? AND timestamp<=? {remote_filter}
                        GROUP BY sample_time
                    )
                    SELECT strftime('{ts_fmt}',sample_time) AS period,
                           AVG(total_flow),MAX(total_flow),MIN(total_flow),
                           SUM(sample_count),SUM(demo_count)
                    FROM samples GROUP BY period ORDER BY period
                """, params_base)
            else:
                db_field = field_map[field]
                res = conn.execute(f"""
                    SELECT strftime('{ts_fmt}',replace(timestamp,'T',' ')) AS period,
                           AVG({db_field}), MAX({db_field}), MIN({db_field}), COUNT(*),
                           {demo_expr} AS demo_count
                    FROM ams_log
                    WHERE timestamp>=? AND timestamp<=? {remote_filter}
                    GROUP BY period ORDER BY period
                """, params_base)
            rows.extend(res.fetchall())
        except Exception as e:
            print(f"[DB] 議고쉶 ?ㅻ쪟: {e}")
        finally:
            if 'conn' in locals() and conn is not None:
                conn.close()
                conn = None
    if field == "accumulated":
        cumulative = 0.0
        data = []
        row_map = {r[0]: r for r in rows}
        period_keys = _history_periods(start_dt, end_dt, unit) or [r[0] for r in rows]
        for period in period_keys:
            r = row_map.get(period)
            if not r:
                usage = 0.0
                data.append({
                    "period": period,
                    "usage": 0.0,
                    "cumulative": round(cumulative, 4),
                    "dashboard_total": None,
                    "avg": 0.0,
                    "max": 0.0,
                    "min": 0.0,
                    "count": 0,
                    "demo_count": 0,
                    "is_demo": False,
                })
                continue
            usage = float(r[1] or 0)
            cumulative += usage
            demo_count = int(r[4] or 0)
            count = int(r[3] or 0)
            data.append({
                "period": period,
                "usage": round(usage, 4),
                "cumulative": round(cumulative, 4),
                "dashboard_total": round(r[2], 4) if r[2] is not None else None,
                "avg": round(usage, 4),
                "max": round(usage, 4),
                "min": round(usage, 4),
                "count": count,
                "demo_count": demo_count,
                "is_demo": bool(count and demo_count >= count),
            })
        return data
    row_map = {r[0]: r for r in rows}
    period_keys = _history_periods(start_dt, end_dt, unit) or [r[0] for r in rows]
    data = []
    for period in period_keys:
        r = row_map.get(period)
        if not r:
            data.append({"period":period,"avg":None,"max":None,"min":None,"count":0,"demo_count":0,"is_demo":False})
            continue
        count = int(r[4] or 0)
        demo_count = int(r[5] or 0)
        data.append({"period":period,
                     "avg":round(r[1],4) if r[1] is not None else None,
                     "max":round(r[2],4) if r[2] is not None else None,
                     "min":round(r[3],4) if r[3] is not None else None,
                     "count":count,
                     "demo_count":demo_count,
                     "is_demo": bool(count and demo_count >= count)})
    return data

def export_csv(start: str, end: str, remote_id: str = "ALL"):
    return io.StringIO("".join(iter_export_csv(start, end, remote_id)))


def _legacy_export_csv(start: str, end: str, remote_id: str = "ALL"):
    start_dt, end_dt = _validated_history_range(start, end, "day", raw_export=True)
    start_bound = start_dt.isoformat(timespec="seconds")
    end_bound = end_dt.isoformat(timespec="seconds")
    months   = []
    cur = start_dt.replace(day=1)
    while cur <= end_dt:
        months.append(cur)
        cur = cur.replace(month=cur.month+1) if cur.month < 12 else cur.replace(year=cur.year+1, month=1)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp","remote_id","pressure_mpa","temperature_c","flow_l_min",
                     "dashboard_accumulated_l","raw_accumulated_l","delta_flow_l","reset_detected",
                     "ams_status","diagnostic",
                     "energy_kwh","energy_cost_krw","energy_co2_kg"])
    for m in months:
        db_path = get_db_path(m)
        if not db_path.exists(): continue
        conn = get_db_conn(m)
        try:
            remote_filter, remote_params = _history_remote_filter(remote_id)
            params = (start_bound, end_bound) + remote_params
            rows = conn.execute(f"""
                SELECT timestamp,COALESCE(remote_id,'AMS00'),pressure,temperature,flow,accumulated,
                       raw_accumulated,delta_flow,reset_detected,
                       ams_status,diagnostic,energy_kwh,energy_cost,energy_co2
                FROM ams_log WHERE timestamp>=? AND timestamp<=? {remote_filter} ORDER BY timestamp
            """, params).fetchall()
        finally:
            conn.close()
        for r in rows:
            row = list(r)
            if row and isinstance(row[0], str):
                row[0] = row[0].replace("T", " ")
            writer.writerow(row)
    output.seek(0)
    return output


def iter_export_csv(start: str, end: str, remote_id: str = "ALL", *, source=None,
                    generation=None, include_simulated=None):
    start_dt, last_dt = _validated_history_range(start, end, "day", raw_export=True)
    end_dt = last_dt.replace(hour=0, minute=0, second=0) + timedelta(days=1)
    columns = ["timestamp", "remote_id", "pressure", "temperature", "flow", "accumulated",
               "raw_accumulated", "delta_flow", "reset_detected", "ams_status", "diagnostic",
               "energy_kwh", "energy_cost", "energy_co2", "source_key", "measurement_generation",
               "quality", "gap", "interval_start", "timestamp_basis", "legacy"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    yield buf.getvalue()
    for row in history_contract.rows(DB_DIR, start_dt, end_dt, remote_id,
            site_timezone=config_snapshot().get("site_timezone", "Asia/Seoul"), source=source,
            generation=generation, include_simulated=include_simulated):
        buf.seek(0)
        buf.truncate(0)
        writer.writerow([row.get(key) for key in columns])
        yield buf.getvalue()


def _legacy_iter_export_csv(start: str, end: str, remote_id: str = "ALL"):
    """Stream raw CSV rows without holding the full result or file in memory."""
    start_dt, end_dt = _validated_history_range(start, end, "day", raw_export=True)
    start_bound = start_dt.isoformat(timespec="seconds")
    end_bound = end_dt.isoformat(timespec="seconds")
    months = []
    cur = start_dt.replace(day=1)
    while cur <= end_dt:
        months.append(cur)
        cur = cur.replace(month=cur.month + 1) if cur.month < 12 else cur.replace(year=cur.year + 1, month=1)

    header = [
        "timestamp", "remote_id", "pressure_mpa", "temperature_c", "flow_l_min",
        "dashboard_accumulated_l", "raw_accumulated_l", "delta_flow_l", "reset_detected",
        "ams_status", "diagnostic", "energy_kwh", "energy_cost_krw", "energy_co2_kg",
    ]

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)

        def emit(row):
            writer.writerow(row)
            value = buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            return value

        yield emit(header)
        for month in months:
            if not get_db_path(month).exists():
                continue
            conn = get_db_conn(month)
            try:
                remote_filter, remote_params = _history_remote_filter(remote_id)
                params = (start_bound, end_bound) + remote_params
                cursor = conn.execute(f"""
                    SELECT timestamp,remote_id,pressure,temperature,flow,accumulated,
                           raw_accumulated,delta_flow,reset_detected,
                           ams_status,diagnostic,energy_kwh,energy_cost,energy_co2
                    FROM ams_log WHERE timestamp>=? AND timestamp<=? {remote_filter} ORDER BY timestamp
                """, params)
                for record in cursor:
                    row = list(record)
                    if row and isinstance(row[0], str):
                        row[0] = row[0].replace("T", " ")
                    yield emit(row)
            finally:
                conn.close()

    return generate()

def export_history_query_csv(start: str, end: str, unit: str, field: str, mode: str = "avg",
                             remote_id: str = "ALL", **filters):
    rows = query_history(start, end, unit, field, remote_id, **filters)
    output = io.StringIO()
    writer = csv.writer(output)
    if field == "accumulated":
        total_usage_l = float(rows[-1].get("cumulative") or 0) if rows else 0.0
        total_usage_m3 = total_usage_l / 1000.0
        total_energy_kwh = total_usage_m3 * get_kwh_per_m3()
        total_cost = total_energy_kwh * get_price_per_kwh()
        total_co2 = total_energy_kwh * get_co2_per_kwh()

        writer.writerow([f"{unit.title()} Usage Report"])
        writer.writerow(["Time Period","Usage (L)","Cumulative Usage (L)"])
        for r in rows:
            writer.writerow([
                r.get("period"),
                r.get("usage"),
                r.get("cumulative"),
            ])
        writer.writerow([])
        writer.writerow(["Energy Summary"])
        writer.writerow(["Total Usage (L)", round(total_usage_l, 4)])
        writer.writerow(["Total Usage (m3)", round(total_usage_m3, 4)])
        writer.writerow(["Specific Power (kWh/m3)", get_kwh_per_m3()])
        writer.writerow(["Total Energy (kWh)", round(total_energy_kwh, 4)])
        writer.writerow(["Electricity Rate (KRW/kWh)", get_price_per_kwh()])
        writer.writerow(["Estimated Cost (KRW)", round(total_cost, 0)])
        writer.writerow(["CO2 Factor (kg/kWh)", get_co2_per_kwh()])
        writer.writerow(["Estimated CO2 (kg)", round(total_co2, 4)])
    else:
        selected = mode if mode in {"avg","max","min"} else "avg"
        selected_label = {"avg":"Selected Avg","max":"Selected Max","min":"Selected Min"}[selected]
        writer.writerow([f"{unit.title()} {field} Report"])
        writer.writerow(["Time Period",selected_label,"Average","Maximum","Minimum"])
        for r in rows:
            writer.writerow([
                r.get("period"),
                r.get(selected),
                r.get("avg"),
                r.get("max"),
                r.get("min"),
            ])
    output.seek(0)
    return output

# ?? ?몄뀡 ??????????????????????????????????????????????????
ams_session: Optional[requests.Session] = None

def reset_ams_session() -> None:
    global ams_session, device_connected
    if ams_session:
        try:
            ams_session.close()
        except Exception:
            pass
    ams_session = None
    device_connected = False

def login(sess: requests.Session) -> bool:
    try:
        host = get_ams_host()
        sess.get(f"{host}/web/index.html", timeout=3, verify=False)
        csrf     = sess.cookies.get("csrf", "")
        pass_hex = "".join(f"{ord(c):02x}" for c in get_ams_pass())
        value    = "0000" + pass_hex.ljust(32, "0")
        r = sess.post(f"{host}/api/adi/config/update.json",
                      data={"inst":33537,"value":value,"csrf":csrf}, timeout=3, verify=False)
        return r.status_code == 200
    except Exception as e:
        print(f"[AMS] login error: {type(e).__name__}: {e}")
        return False

def get_csrf(sess) -> str:
    return sess.cookies.get("csrf", "")

_last_connect_attempt: float = 0.0
_CONNECT_RETRY_INTERVAL_S = 30.0  # Minimum retry interval after auth/connect failure.

def try_connect(force: bool = False) -> bool:
    global ams_session, device_connected, _last_connect_attempt
    if not _acquisition_enabled:
        return False
    now = time.time()
    if not force and (now - _last_connect_attempt) < _CONNECT_RETRY_INTERVAL_S and not ams_session:
        return False
    _last_connect_attempt = now
    try:
        sess = requests.Session(); sess.verify = False
        ok   = login(sess)
        if ok:
            ams_session      = sess
            device_connected = True
            print(f"[AMS] connected -> {get_ams_host()}")
        else:
            device_connected = False
            ams_session      = None
            print(f"[AMS] auth failed -> {get_ams_host()}")
        return ok
    except Exception as e:
        device_connected = False
        ams_session      = None
        print(f"[AMS] connect failed -> {get_ams_host()} : {e}")
        return False

def ensure_session(force: bool = False) -> bool:
    global ams_session, device_connected
    if not _acquisition_enabled:
        return False
    if not ams_session:
        return try_connect(force=force)
    try:
        r = ams_session.get(f"{get_ams_host()}/api/adi/status/data.json",
                            params={"inst":33537,"count":1}, timeout=3, verify=False)
        if r.status_code in [401, 403]:
            return try_connect()
        device_connected = True
        return True
    except Exception as e:
        print(f"[AMS] session check failed: {type(e).__name__}: {e}")
        reset_ams_session()
        return try_connect(force=True)

@_command_generation()
def post_control(inst: int, value: str) -> dict:
    global device_connected
    if is_demo_data_source():
        return {"ok": True, "demo": True, "inst": inst, "value": value}
    if not ensure_session(force=True):
        return {"ok": False, "error": "device_disconnected"}
    csrf = get_csrf(ams_session)
    try:
        r = ams_session.post(f"{get_ams_host()}/api/adi/config/update.json",
                             data={"inst":inst,"value":value,"csrf":csrf}, timeout=3, verify=False)
        if r.status_code in [401, 403]:
            reset_ams_session()
            if not try_connect(force=True):
                return {"ok":False,"error":"device_disconnected"}
            csrf = get_csrf(ams_session)
            r = ams_session.post(f"{get_ams_host()}/api/adi/config/update.json",
                                 data={"inst":inst,"value":value,"csrf":csrf}, timeout=3, verify=False)
        return {"ok":r.status_code==200,"status_code":r.status_code}
    except Exception as e:
        print(f"[AMS] post failed at {inst}: {type(e).__name__}: {e}")
        reset_ams_session()
        if not try_connect(force=True):
            return {"ok":False,"error":str(e)}
        try:
            csrf = get_csrf(ams_session)
            r = ams_session.post(f"{get_ams_host()}/api/adi/config/update.json",
                                 data={"inst":inst,"value":value,"csrf":csrf}, timeout=3, verify=False)
            return {"ok":r.status_code==200,"status_code":r.status_code,"retried":True}
        except Exception as retry_error:
            reset_ams_session()
            return {"ok":False,"error":str(retry_error)}

CONTROL_PREP_INST = 0x8003
CONTROL_PREP_VALUE = "0107000001fe0e00"
CONTROL_TRIGGER_INST = 0x8101
MODE_PARAM_INST = 0x8116
HUB_WARMUP_TTL_S = 300
hub_warmed_at = 0.0
HUB_WARMUP_WRITES = [
    (33008, "0007003817010000"),
    (32769, "0107000001fe1300"),
    (32770, "0107000001fe1400"),
    (32784, "0007004320010000"),
    (32785, "0107000000fe0000"),
    (32786, "0107000000fe0200"),
    (32787, "0107000001fe1000"),
    (32788, "0107000001fe1100"),
    (32789, "0107000002000100"),
    (32790, "0107000001fe0a00"),
    (32791, "0107000000fe0100"),
    (32792, "0107000000fe0500"),
    (32793, "0107000000fe0400"),
    (32800, "0107000001fe0400"),
    (32801, "0107000001fe0500"),
    (32802, "0107000001fe0600"),
    (32803, "0107000001fe0700"),
    (32804, "0107000001fe0800"),
    (32805, "0107000001fe0900"),
    (32806, "0107000001fe0b00"),
    (32807, "0107000001fe0c00"),
    (32808, "0107000001fe0d00"),
    (32816, "0107000001fe0100"),
    (32817, "0107000001fe0200"),
    (32818, "0107000001fe0300"),
    (32819, "0107000001fe1200"),
    (32832, "0107000002000000"),
    (32833, "0107000002000400"),
    (32834, "0107000002000500"),
    (32835, "0107000002000800"),
    (32836, "0107000002000900"),
]

@_command_generation()
def warmup_hub_requests(force: bool = False) -> dict:
    global hub_warmed_at
    now = time.time()
    if not force and hub_warmed_at and (now - hub_warmed_at) < HUB_WARMUP_TTL_S:
        return {"ok":True,"cached":True,"age_s":round(now - hub_warmed_at, 1)}
    if not ensure_session(force=force):
        return {"ok": False, "error": "device_disconnected"}
    try:
        host = get_ams_host()
        for inst, value in HUB_WARMUP_WRITES:
            csrf = get_csrf(ams_session)
            r = ams_session.post(
                f"{host}/api/adi/config/update.json",
                data={"inst": inst, "value": value, "csrf": csrf},
                timeout=3,
                verify=False,
            )
            if r.status_code in [401, 403]:
                reset_ams_session()
                if not try_connect(force=True):
                    return {"ok":False,"error":f"hub warm-up auth failed at {inst}"}
                csrf = get_csrf(ams_session)
                r = ams_session.post(
                    f"{get_ams_host()}/api/adi/config/update.json",
                    data={"inst": inst, "value": value, "csrf": csrf},
                    timeout=3,
                    verify=False,
                )
            if r.status_code != 200:
                return {"ok":False,"error":f"hub warm-up failed at {inst}: HTTP {r.status_code}"}
            time.sleep(0.02)
        ams_session.get(
            f"{get_ams_host()}/api/adi/status/data.json",
            params={"inst": 33040, "count": 10},
            timeout=3,
            verify=False,
        )
        hub_warmed_at = time.time()
        return {"ok":True,"cached":False,"writes":len(HUB_WARMUP_WRITES)}
    except Exception as e:
        print(f"[AMS] hub warm-up failed: {type(e).__name__}: {e}")
        reset_ams_session()
        return {"ok":False,"error":str(e)}

def prepare_control(force: bool = False) -> dict:
    if is_demo_data_source():
        return {"ok": True, "demo": True, "cached": True}
    if is_modbus_data_source():
        return {"ok": True, "driver": "modbus-tcp", "cached": True}
    hub = warmup_hub_requests(force)
    if not hub.get("ok"):
        return {
            "ok": False,
            "error": hub.get("error", "hub warm-up failed"),
            "hub_warmup": hub,
        }
    prep = post_control(CONTROL_PREP_INST, CONTROL_PREP_VALUE)
    prep["hub_warmup"] = hub
    prep["ok"] = bool(prep.get("ok") and hub.get("ok"))
    return prep

def set_ams_mode(mode: int) -> dict:
    if mode not in [0,1,2,3]:
        return {"ok":False,"error":"mode must be 0~3"}
    value = f"{mode:02X}"
    prep = prepare_control()
    if not prep.get("ok"):
        return prep
    mode_write = post_control(MODE_PARAM_INST, value)
    trigger = post_control(CONTROL_TRIGGER_INST, "01")
    return {
        "ok": bool(prep.get("ok") and mode_write.get("ok") and trigger.get("ok")),
        "prep": prep,
        "mode_write": mode_write,
        "trigger": trigger,
        "mode_value": value,
    }

# ?? ?뚯떛 ??????????????????????????????????????????????????
def s16(h):
    v = int(h, 16); return v - 0x10000 if v >= 0x8000 else v

def safe_int(h, start, end, signed=False):
    if len(h) < end: return 0
    part = h[start:end]
    if not part: return 0
    try: return s16(part) if signed else int(part, 16)
    except Exception: return 0

AMS_STATUS_MAP = {
    0: "Initialising",
    1: "Operation Mode",
    2: "Waiting for Standby",
    3: "Standby",
    4: "Isolation",
    17: "Operation Mode",
    19: "Standby",
    20: "Isolation",
    35: "F-Standby",
    36: "Isolation",
}

def decode_ams_status(raw_status: int) -> dict:
    code = int(raw_status or 0)
    return {
        "code": code,
        "label": AMS_STATUS_MAP.get(code, f"Unknown({code})"),
        "source": "pf3a_status",
    }

def _has_live_hex_bytes(values) -> bool:
    for value in values or []:
        text = str(value or "").strip().upper()
        if text and text not in ("--", "00"):
            return True
    return False

def decode_port4_status(pqi: int, pdin_hex=None) -> str:
    if pqi & 0x01:
        return "Short L+"
    if pqi & 0x04:
        return "Short VP"
    if (pqi & 0x02) or _has_live_hex_bytes(pdin_hex):
        return "Operate"
    return "No live data"

def parse_process_hex(hex_str: str) -> dict:
    diag_flags = {0x80:"System error",0x40:"Error",0x10:"Pressure diag",0x08:"Temp diag",0x04:"Flow diag"}
    def field(start, end, signed=False, scale=1, digits=0):
        part = str(hex_str or "")[start:end]
        if len(part) != end - start or any(c not in "0123456789abcdefABCDEF" for c in part):
            return None
        value = s16(part) if signed else int(part, 16)
        return round(value * scale, digits) if scale != 1 else value

    acc = field(4, 12)
    flow = field(12, 16)
    temp = field(16, 20, True, 0.1, 1)
    pres = field(20, 24, True, 0.001, 3)
    diag_val = field(24, 26)
    code = field(26, 28)
    if code not in AMS_STATUS_MAP:
        code = None
    itv_p = field(28, 32, True, 0.001, 3)
    pqi = field(36, 38)
    diag_msgs = [t for b, t in diag_flags.items() if diag_val is not None and diag_val & b]
    state = decode_ams_status(code) if code is not None else {"label": "Unknown", "code": None, "source": "pf3a_status"}
    port_st = decode_port4_status(pqi) if pqi is not None else "Unavailable"
    return {
        "timestamp":          datetime.now().isoformat(timespec="seconds"),
        "accumulated_flow_l": acc,
        "instant_flow_l_min": flow,
        "temperature_c":      temp,
        "pressure_mpa":       pres,
        "itv_pressure_mpa":   itv_p,
        "field_quality": {key: "good" if value is not None else "unavailable" for key, value in {
            "accumulated_flow_l": acc, "instant_flow_l_min": flow, "temperature_c": temp,
            "pressure_mpa": pres, "itv_pressure_mpa": itv_p, "ams_code": code}.items()},
        "diagnostic":         "Unavailable" if diag_val is None else (", ".join(diag_msgs) if diag_msgs else "No error"),
        "ams_status":         state["label"],
        "ams_code":           state["code"],
        "ams_state_source":   state["source"],
        "port_status":        port_st,
    }

def _opcua_value_to_number(value, default=0):
    if value is None:
        return default
    try:
        if hasattr(value, "Value"):
            value = value.Value
        return float(value)
    except Exception:
        try:
            return float(str(value))
        except Exception:
            return default

def _opcua_value_to_int(value, default=0):
    return int(round(_opcua_value_to_number(value, default)))


def _opcua_bytes_to_hex(value, width=16):
    def byte_hex(raw):
        numeric = finite_number(raw)
        if numeric is None or not numeric.is_integer() or not 0 <= numeric <= 255:
            return "--"
        return f"{int(numeric):02X}"

    if isinstance(value, dict):
        return [byte_hex(value.get(str(idx), value.get(idx))) for idx in range(width)]
    if isinstance(value, (list, tuple, bytes, bytearray)):
        items = [byte_hex(raw) for raw in value[:width]]
        return items + ["--"] * max(0, width - len(items))
    return ["--"] * width


def _opcua_value_to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in ("true", "1", "on", "yes")


def _parse_ams00_opcua_values(values: dict) -> dict:
    err = _opcua_value_to_int(values.get("pf3a_error"))
    status = _opcua_value_to_int(values.get("pf3a_status"))
    flow = _opcua_value_to_int(values.get("flow"))
    temp = round(_opcua_value_to_number(values.get("temperature")) * 0.1, 1)
    pressure = round(_opcua_value_to_number(values.get("pressure")) * 0.001, 3)
    accumulated = _opcua_value_to_int(values.get("accumulated"))
    itv_pressure = round(_opcua_value_to_number(values.get("itv_value")) * 0.001, 3)
    port3_di = _opcua_value_to_int(values.get("ex_di"))
    port3_standby_bit = int(config_store.get("port3_standby_bit", 4))
    port3_isolation_bit = int(config_store.get("port3_isolation_bit", 2))
    port4_pin2_bit = int(config_store.get("port4_pin2_bit", 7))
    port4_pin4_bit = int(config_store.get("port4_pin4_bit", 6))
    port3_standby_signal = bool(port3_di & (1 << port3_standby_bit))
    port3_isolation_signal = bool(port3_di & (1 << port3_isolation_bit))
    port4_pin2_signal = bool(port3_di & (1 << port4_pin2_bit))
    port4_pin4_signal = bool(port3_di & (1 << port4_pin4_bit))
    port3_active_bits = [f"B{i}" for i in range(8) if port3_di & (1 << i)]
    if port3_standby_signal and port3_isolation_signal:
        port3_signal_label = "Standby + Isolation"
    elif port3_standby_signal:
        port3_signal_label = "Standby"
    elif port3_isolation_signal:
        port3_signal_label = "Isolation"
    elif port4_pin2_signal and port4_pin4_signal:
        port3_signal_label = "Port 4 Pin2 + Pin4"
    elif port4_pin2_signal:
        port3_signal_label = "Port 4 Pin2"
    elif port4_pin4_signal:
        port3_signal_label = "Port 4 Pin4"
    elif port3_active_bits:
        port3_signal_label = "Unmapped input"
    else:
        port3_signal_label = "No signal"
    port4_pqi = _opcua_value_to_int(values.get("ex_p4_pqi"))
    port4_do = _opcua_value_to_int(values.get("p4_do"))
    port4_pdin_hex = _opcua_bytes_to_hex(values.get("ex_p4_pdin"))
    port4_pdout_hex = _opcua_bytes_to_hex(values.get("p4_pdout"))
    diag = "No error" if err == 0 else f"PF3A error 0x{err:02X}"
    state = decode_ams_status(status)
    code = state["code"]
    port4_status = decode_port4_status(port4_pqi, port4_pdin_hex)
    return attach_iodd_context({
        "timestamp":              datetime.now().isoformat(timespec="seconds"),
        "accumulated_flow_l":     accumulated,
        "instant_flow_l_min":     flow,
        "temperature_c":          temp,
        "pressure_mpa":           pressure,
        "itv_pressure_mpa":       itv_pressure,
        "diagnostic":             diag,
        "ams_status":             state["label"],
        "ams_code":               code,
        "ams_state_source":       state["source"],
        "port_status":            port4_status,
        "pf3a_error":             err,
        "pf3a_status":            status,
        "port3_di":               port3_di,
        "port3_di_hex":           f"{port3_di & 0xFF:02X}",
        "port3_standby_signal":   port3_standby_signal,
        "port3_isolation_signal": port3_isolation_signal,
        "port3_standby_bit":      port3_standby_bit,
        "port3_isolation_bit":    port3_isolation_bit,
        "port3_active_bits":      port3_active_bits,
        "port3_signal_label":     port3_signal_label,
        "port4_pin2_signal":      port4_pin2_signal,
        "port4_pin4_signal":      port4_pin4_signal,
        "port4_pin2_bit":         port4_pin2_bit,
        "port4_pin4_bit":         port4_pin4_bit,
        "port4_pqi":              port4_pqi,
        "port4_pqi_hex":          f"{port4_pqi & 0xFF:02X}",
        "port4_status":           port4_status,
        "port4_pdin_hex":         port4_pdin_hex,
        "port4_pdin_text":        " ".join(port4_pdin_hex),
        "port4_do":               port4_do,
        "port4_do_hex":           f"{port4_do & 0xFF:02X}",
        "port4_pdout_hex":        port4_pdout_hex,
        "port4_pdout_text":       " ".join(port4_pdout_hex),
        "opcua_values":           {k: str(v) for k, v in values.items()},
        "data_source":            "opcua",
    }, "AMS00")

def parse_ams00_opcua_values(values: dict) -> dict:
    fields = {"flow": "instant_flow_l_min", "accumulated": "accumulated_flow_l",
              "pressure": "pressure_mpa", "temperature": "temperature_c", "itv_value": "itv_pressure_mpa",
              "pf3a_status": "ams_code", "pf3a_error": "pf3a_error", "ex_di": "port3_di", "p4_do": "port4_do",
              "ex_p4_pqi": "port4_pqi"}
    clean = dict(values)
    invalid = {key for key in fields if finite_number(values.get(key)) is None}
    ranges = {"pf3a_status": (0, 255), "pf3a_error": (0, 255), "ex_di": (0, 255),
              "p4_do": (0, 255), "ex_p4_pqi": (0, 255), "flow": (0, 65535),
              "accumulated": (0, 4294967295), "temperature": (-32768, 32767),
              "pressure": (-32768, 32767), "itv_value": (-32768, 32767)}
    for key, (low, high) in ranges.items():
        value = finite_number(values.get(key))
        if value is None or not value.is_integer() or not low <= value <= high:
            invalid.add(key)
    if finite_number(values.get("pf3a_status")) not in AMS_STATUS_MAP:
        invalid.add("pf3a_status")
    for key in invalid:
        clean[key] = 0  # Internal decoding only; unavailable fields are removed below.
    result = _parse_ams00_opcua_values(clean)
    result["field_quality"] = {field: "unavailable" if key in invalid else "good" for key, field in fields.items()}
    for key in invalid:
        result[fields[key]] = None
    if "pf3a_status" in invalid:
        result.update(ams_status="Unknown", pf3a_status=None)
    if "pf3a_error" in invalid:
        result["diagnostic"] = "PF3A diagnostic unavailable"
    if "ex_di" in invalid:
        for key in ("port3_standby_signal", "port3_isolation_signal", "port4_pin2_signal", "port4_pin4_signal"):
            result[key] = None
        result.update(port3_di_hex="--", port3_active_bits=[], port3_signal_label="Unavailable")
    if "p4_do" in invalid:
        result["port4_do_hex"] = "--"
    if "ex_p4_pqi" in invalid:
        result.update(port4_pqi_hex="--", port4_status="Unavailable", port_status="Unavailable")
    return result


def parse_remote_opcua_values(remote_id: str, values: dict) -> dict:
    data = parse_ams00_opcua_values(values)
    data["remote_id"] = remote_id
    data["name"] = remote_id
    return attach_iodd_context(data, remote_id)


_WORKER_FETCH_TTL_S = 0.8  # worker 罹먯떆 ?대쭅 理쒖냼 媛꾧꺽 (read interval 1s蹂대떎 吏㏐쾶)

_worker_cache_token = None
# Failure coalescing is separate from measurement freshness and success caching.
_worker_fetch_failure = None


def _worker_token_current(token):
    # Caller holds node_worker_lock. Generation lock never acquires config_lock.
    return (token is not None and token[0] == current_config_generation()
            and token[1] is node_worker_owner and token[2] is node_worker_proc
            and node_worker_proc is not None and node_worker_proc.poll() is None)


def _get_cached_remote(remote_id: str) -> Optional[dict]:
    return _get_cached_remotes_snapshot().get(remote_id)

def _get_cached_remotes_snapshot() -> dict:
    if str(config_store.get("data_source") or "opcua").lower() != "opcua":
        return {}
    with node_worker_lock:
        with worker_cache_lock:
            if not _worker_token_current(_worker_cache_token):
                return {}
            rows = copy.deepcopy(_worker_remotes_cache)
            now = time.time()
            for row in rows.values():
                measured = sample_time(row.get("timestamp"))
                if measured is None or not 0 <= now - measured.timestamp() <= 15:
                    row.update(stale=True, opcua_stale=True, device_connected=False, online=False)
                for field, stamp in (row.get("field_source_timestamps") or {}).items():
                    source_time = sample_time(stamp)
                    if source_time is not None and not 0 <= now - source_time.timestamp() <= 15:
                        row.setdefault("field_quality", {})[field] = "stale"
            return rows

def _fetch_worker_data() -> dict:
    if str(config_store.get("data_source") or "opcua").lower() != "opcua":
        return {}
    with worker_fetch_lock:
        return _fetch_worker_data_locked()


@_command_generation()
def _fetch_worker_data_locked() -> dict:
    """
    worker /data ?대쭅 ??_worker_remotes_cache 媛깆떊.
    TTL ?댁뿉 ?ы샇異???湲곗〈 罹먯떆 諛섑솚 (worker??5珥덈쭏??媛깆떊?섎?濡?留ㅼ큹 fetch 遺덊븘??.
    """
    global _worker_remotes_cache, _worker_last_fetch, _worker_cache_token, _worker_fetch_failure
    now = time.time()
    with node_worker_lock:
        token = (current_config_generation(), node_worker_owner, node_worker_proc)
        failure = _worker_fetch_failure
        if (failure is not None and failure[0][0] == token[0]
                and failure[0][1] is token[1] and failure[0][2] is token[2]
                and time.monotonic() - failure[1] < _WORKER_FETCH_TTL_S):
            return {"error": failure[2]}
        cache_matches = _worker_token_current(_worker_cache_token)
    if cache_matches and _worker_last_fetch and (now - _worker_last_fetch) < _WORKER_FETCH_TTL_S:
        rows = _get_cached_remotes_snapshot()
        return {"ok": any(sample_usable(row) for row in rows.values()),
                "connected": any(row.get("device_connected") for row in rows.values()), "remotes": {}}
    try:
        data, _status = _owned_worker_request("GET", "/data", timeout=3, generation=config_generation_snapshot())
    except Exception as e:
        with node_worker_lock:
            if (token[0] != current_config_generation() or token[1] is not node_worker_owner
                    or token[2] is not node_worker_proc):
                return {"error": "obsolete worker collection"}
            with worker_cache_lock:
                _worker_last_fetch = now
                for row in _worker_remotes_cache.values():
                    row.update(device_connected=False, online=False, stale=True, opcua_stale=True, error="worker_unreachable")
        maybe_restart_node_worker(
            f"worker read failed: {type(e).__name__}", expected_owner=token[1], expected_proc=token[2]
        )
        error = f"worker_unreachable: {type(e).__name__}: {e}"
        # Start the short retry window after the timeout/restart handling, not
        # before the request. A replacement worker has a different identity and
        # bypasses this failure immediately.
        _worker_fetch_failure = (token, time.monotonic(), error)
        return {"error": error}

    _worker_fetch_failure = None
    remotes_raw = data.get("remotes", {})

    new_remotes: dict = {}
    for remote_id, cache in remotes_raw.items():
        if cache and cache.get("values"):
            values = dict(cache["values"])
            for key, status in (cache.get("node_status") or {}).items():
                if not str(status).startswith("Good"):
                    values[key] = None
            parsed = parse_remote_opcua_values(remote_id, values)
            measured = sample_time(cache.get("read_at"))
            stale = bool(cache.get("stale")) or measured is None or not 0 <= now - measured.timestamp() <= 15
            parsed.update(timestamp=measured.isoformat() if measured else None, sample_id=cache.get("sample_id"),
                          connection_generation=cache.get("connection_generation"), stale=stale)
            parsed["device_connected"]     = bool(data.get("connected") and cache.get("connected") and not stale)
            parsed["read_latency_ms"]      = cache.get("read_latency_ms")
            parsed["opcua_stale"]          = stale
            parsed["opcua_last_error"]     = cache.get("last_error")
            parsed["opcua_driver"]         = "node-opcua-worker"
            source_fields = {"flow": "instant_flow_l_min", "accumulated": "accumulated_flow_l",
                             "pressure": "pressure_mpa", "temperature": "temperature_c", "itv_value": "itv_pressure_mpa",
                             "pf3a_status": "ams_code", "pf3a_error": "pf3a_error", "ex_di": "port3_di",
                             "p4_do": "port4_do", "ex_p4_pqi": "port4_pqi"}
            parsed["source_timestamps"] = copy.deepcopy(cache.get("source_timestamps") or {})
            parsed["node_status"] = copy.deepcopy(cache.get("node_status") or {})
            parsed["field_source_timestamps"] = {source_fields[key]: stamp for key, stamp in
                parsed["source_timestamps"].items() if key in source_fields}
            for field, stamp in parsed["field_source_timestamps"].items():
                source_time = sample_time(stamp)
                if stamp is not None and (source_time is None or not 0 <= now - source_time.timestamp() <= 15):
                    parsed["field_quality"][field] = "stale"
        else:
            parsed = {
                "remote_id":        remote_id,
                "name":             remote_id,
                "device_connected": False,
                "error":            (cache or {}).get("last_error") or "no_data",
                "opcua_stale":      True,
                "stale":            True,
                "timestamp":        (cache or {}).get("read_at"),
                "sample_id":        (cache or {}).get("sample_id"),
                "connection_generation": (cache or {}).get("connection_generation"),
                "node_status":      copy.deepcopy((cache or {}).get("node_status") or {}),
                "source_timestamps": copy.deepcopy((cache or {}).get("source_timestamps") or {}),
            }
        new_remotes[remote_id] = parsed

    with node_worker_lock:
        if not _worker_token_current(token):
            return {"error": "obsolete worker collection"}
        with worker_cache_lock:
            _worker_remotes_cache = new_remotes
            _worker_cache_token = token
            _worker_last_fetch = now
    return data



def _demo_clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _demo_mode_profile(mode: int, now_s: float) -> dict:
    """Return slow-moving targets that make the selected operating mode obvious."""
    slow = math.sin(now_s / 28.0)
    profiles = {
        1: {
            "phase": "operation",
            "label": "Operation Mode",
            "code": 17,
            "flow": 42.0 + 1.8 * slow,
            "pressure": 0.615 + 0.006 * slow,
            "temperature": 29.2 + 0.25 * math.sin(now_s / 55.0),
        },
        2: {
            "phase": "standby",
            "label": "Standby",
            "code": 19,
            "flow": 3.0 + 0.35 * slow,
            "pressure": 0.205 + 0.004 * slow,
            "temperature": 28.0 + 0.18 * math.sin(now_s / 60.0),
        },
        3: {
            "phase": "isolation",
            "label": "Isolation",
            "code": 20,
            "flow": 0.0,
            "pressure": 0.025 + 0.002 * slow,
            "temperature": 27.2 + 0.12 * math.sin(now_s / 70.0),
        },
    }
    # AMS AUTO is represented as normal operation in presentation mode.
    return profiles.get(mode, profiles[1])


def _step_demo_live_state(mode: int) -> tuple[dict, float, float, float, float]:
    """Advance the simulator once using elapsed wall time, independent of caller count."""
    global _demo_live_state
    with demo_live_lock:
        now_s = time.time()
        profile = _demo_mode_profile(mode, now_s)
        if _demo_live_state.get("started_at") is None:
            _demo_live_state["started_at"] = now_s
            _demo_live_state["raw_accumulated_l"] = float(
                config_store.get("dashboard_last_raw_accumulated_l") or 0.0
            )
            _demo_live_state["last_tick"] = now_s
            _demo_live_state["mode"] = mode
            _demo_live_state["flow"] = profile["flow"]
            _demo_live_state["pressure"] = profile["pressure"]
            _demo_live_state["temperature"] = profile["temperature"]

        last_tick = float(_demo_live_state.get("last_tick") or now_s)
        dt = max(0.0, min(5.0, now_s - last_tick))
        _demo_live_state["last_tick"] = max(last_tick, now_s)
        _demo_live_state["mode"] = mode

        alpha = 1.0 - math.exp(-dt / 5.0) if dt > 0 else 0.0
        for key in ("flow", "pressure", "temperature"):
            current = float(
                _demo_live_state.get(key)
                if _demo_live_state.get(key) is not None
                else profile[key]
            )
            _demo_live_state[key] = current + (float(profile[key]) - current) * alpha

        flow = _demo_clamp(float(_demo_live_state["flow"]), 0.0, 120.0)
        pressure = _demo_clamp(float(_demo_live_state["pressure"]), 0.0, 0.72)
        temperature = _demo_clamp(float(_demo_live_state["temperature"]), 24.0, 36.0)
        raw_acc = float(_demo_live_state.get("raw_accumulated_l") or 0.0) + flow * (dt / 60.0)
        _demo_live_state["raw_accumulated_l"] = raw_acc
        return dict(profile), flow, pressure, temperature, raw_acc


def fetch_process_data_demo() -> dict:
    """Synthetic live stream for presentation demos without AMS hardware.

    Values transition smoothly between Operation, Standby, and Isolation and
    are marked DEMO so history can distinguish them from real samples.
    """
    global device_connected
    mode = get_display_force_mode()
    if mode not in (1, 2, 3):
        mode = 1
    profile, flow, pressure, temp, raw_acc = _step_demo_live_state(mode)

    code = int(profile["code"])
    label = str(profile["label"])
    phase = str(profile["phase"])
    standby_on = mode == 2
    isolation_on = mode == 3
    standby_bit = int(config_store.get("port3_standby_bit", 4))
    isolation_bit = int(config_store.get("port3_isolation_bit", 2))
    port3_di = ((1 << standby_bit) if standby_on else 0) | ((1 << isolation_bit) if isolation_on else 0)

    # Keep operational label for mode UI, but force DEMO marks used by history/source badges.
    result = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "remote_id": "AMS00",
        "name": "AMS00",
        "accumulated_flow_l": round(raw_acc, 3),
        "instant_flow_l_min": round(flow, 2),
        "temperature_c": round(temp, 2),
        "pressure_mpa": round(pressure, 4),
        "itv_pressure_mpa": round(pressure, 4),
        "diagnostic": f"DEMO LIVE - {label}",
        "ams_status": "DEMO",
        "ams_code": code,
        "ams_state_source": "demo_live",
        "demo_phase": phase,
        "demo_mode_label": label,
        "port_status": "Operate",
        "pf3a_error": 0,
        "pf3a_status": code,
        "port3_di": port3_di,
        "port3_di_hex": f"{port3_di & 0xFF:02X}",
        "port3_standby_signal": standby_on,
        "port3_isolation_signal": isolation_on,
        "port3_standby_bit": standby_bit,
        "port3_isolation_bit": isolation_bit,
        "port3_active_bits": [f"B{i}" for i in range(8) if port3_di & (1 << i)],
        "port3_signal_label": label if (standby_on or isolation_on) else "No signal",
        "port4_pin2_signal": False,
        "port4_pin4_signal": False,
        "port4_pin2_bit": int(config_store.get("port4_pin2_bit", 7)),
        "port4_pin4_bit": int(config_store.get("port4_pin4_bit", 6)),
        "port4_pqi": 0x02,
        "port4_pqi_hex": "02",
        "port4_status": "Operate",
        "port4_pdin_hex": ["A1", "0F", "00", "00"] + ["00"] * 12,
        "port4_pdin_text": "A1 0F 00 00 00 00 00 00 00 00 00 00 00 00 00 00",
        "port4_do": 0,
        "port4_do_hex": "00",
        "port4_pdout_hex": ["00"] * 16,
        "port4_pdout_text": " ".join(["00"] * 16),
        "device_connected": True,
        "data_source": "demo",
        "is_demo_live": True,
    }
    result = attach_iodd_context(result, "AMS00")
    apply_usage_tracking(result, persist=False)
    apply_standby_signal(result)
    contact_mode = str(config_store.get("opcua_air_contact_mode", "NC") or "NC").upper()
    result["air_supply_enabled"] = not isolation_on
    result["air_supply_signal_on"] = (not isolation_on) if contact_mode == "NC" else isolation_on
    # Prefer a readable operating state for device/mode widgets while keeping DEMO marks.
    if result.get("ams_status") == "DEMO":
        result["ams_status_display"] = label
    device_connected = True
    return result


def fetch_process_data_web() -> dict:
    global device_connected
    if not ensure_session():
        return {"error":"device_disconnected","device_connected":False}
    try:
        inst = 0x8500 + get_ams_channel()
        r    = ams_session.get(f"{get_ams_host()}/api/adi/status/data.json",
                               params={"inst":inst,"count":1}, timeout=3, verify=False)
        if r.status_code in [401, 403]:
            device_connected = False
            return {"error":"device_disconnected","device_connected":False}
        raw = r.json()
        if not raw or not isinstance(raw, list):
            return {"error":"invalid_response","device_connected":True}
        result = parse_process_hex(raw[0])
        result["device_connected"] = True
        apply_usage_tracking(result, persist=False)
        apply_standby_signal(result)
        return result
    except Exception as e:
        device_connected = False
        return {"error":str(e),"device_connected":False}

# ?? ?ㅼ?以?????????????????????????????????????????????????
SCHEDULE_FILE   = BASE_DIR / "schedules.json"
schedules_store = []
from app.schedule_execution import ScheduleExecution, LIVE as SCHEDULE_LIVE, window as schedule_window
_schedule_execution = ScheduleExecution()
_schedule_origin = ContextVar("ams_schedule_origin", default=None)

def load_schedules():
    global schedules_store
    loaded = _load_json_with_backup(SCHEDULE_FILE, [])
    schedules_store = loaded if isinstance(loaded, list) else []
    _schedule_execution.load(schedules_store)
    _schedule_execution.publish(schedules_store)

def save_schedules():
    _config_journal().require_clear()
    with schedule_lock:
        _atomic_write_json(SCHEDULE_FILE, schedules_store, backup=True)


def _seed_runtime_files():
    DB_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    IODD_DIR.mkdir(exist_ok=True)
    if not CONFIG_FILE.exists():
        bundled_config = BUNDLE_DIR / "config.json"
        if bundled_config.exists():
            shutil.copy2(bundled_config, CONFIG_FILE)
    if not NODES_FILE.exists():
        bundled_nodes = BUNDLE_DIR / "nodes.json"
        if bundled_nodes.exists():
            shutil.copy2(bundled_nodes, NODES_FILE)


def initialize_runtime(*, base_dir=None, bundle_dir=None, assets_dir=None,
                       config=None, node_config=None, adapters=None,
                       persist: bool = True, persist_missing_state: bool = True):
    """Initialize the exported singleton once, without starting any device I/O.

    Supplied config/nodes are copied and replace disk inputs (config gets defaults).
    An injected base also becomes the default bundle, avoiding checkout fallbacks.
    persist=False suppresses bootstrap writes only, not subsequent route writes.
    No-argument calls are idempotent; live/initialized reconfiguration is rejected.
    This is an injection boundary, not an independent-app factory.
    """
    global BASE_DIR, BUNDLE_DIR, ASSETS_DIR, CONFIG_FILE, RUNTIME_STATE_FILE
    global NODES_FILE, DB_DIR, LOG_DIR, IODD_DIR, IODD_INDEX_FILE, SCHEDULE_FILE
    global _runtime_initialized, _runtime_adapters_override, _runtime_recovery_error
    global _exw1_topology_cache, _exw1_topology_signature, _hub_instance, _hub_signature
    explicit = any(value is not None for value in
                   (base_dir, bundle_dir, assets_dir, config, node_config, adapters))
    explicit = explicit or not persist or not persist_missing_state
    with _runtime_init_lock:
        if _runtime_initialized or _runtime_live:
            if explicit:
                raise RuntimeError("runtime singleton is initialized; reconfiguration is not supported")
            return
        if config is not None and not isinstance(config, dict):
            raise TypeError("config must be a dictionary")
        if node_config is not None and (not isinstance(node_config, dict)
                                       or not isinstance(node_config.get("remotes"), dict)):
            raise TypeError("node_config must contain a remotes dictionary")
        if adapters is not None and not isinstance(adapters, dict):
            raise TypeError("adapters must be a transport-to-adapter dictionary")
        with _configuration_admission.bootstrap():
            BASE_DIR = Path(base_dir) if base_dir is not None else APP_DIR
            BUNDLE_DIR = (Path(bundle_dir) if bundle_dir is not None else
                          BASE_DIR if base_dir is not None else Path(getattr(sys, "_MEIPASS", APP_DIR)))
            ASSETS_DIR = Path(assets_dir) if assets_dir is not None else BASE_DIR / "assets"
            if assets_dir is None and not ASSETS_DIR.exists():
                ASSETS_DIR = BUNDLE_DIR / "assets"
            CONFIG_FILE = BASE_DIR / "config.json"
            RUNTIME_STATE_FILE = BASE_DIR / "runtime_state.json"
            NODES_FILE = BASE_DIR / "nodes.json"
            DB_DIR, LOG_DIR = BASE_DIR / "db", BASE_DIR / "logs"
            IODD_DIR = BASE_DIR / "iodd_library"
            IODD_INDEX_FILE = IODD_DIR / "index.json"
            SCHEDULE_FILE = BASE_DIR / "schedules.json"
            try:
                _config_journal().recover(persist=persist)
            except RecoveryRequired:
                if not persist:
                    raise  # Explicit no-bootstrap-write contract, even for recovery.
                _runtime_recovery_error = "configuration_recovery_required"
                # Do not load guessed defaults or either possibly mixed store.
                # The local recovery endpoint/root stay available; no executable
                # registry, schedules, worker or periodic collection is created.
                config_store.clear()
                config_store.update({"device_profiles": {}, "device_profiles_explicit": True,
                                     "modbus_gateways": {}, "modbus_gateways_explicit": True})
                _runtime_initialized = True
                return
            _runtime_recovery_error = None
            loaded = ({**copy.deepcopy(DEFAULT_CONFIG), **copy.deepcopy(config)}
                      if config is not None else load_config())
            nodes = copy.deepcopy(node_config) if node_config is not None else load_node_config()
            read_maps, write_maps = _read_node_maps(nodes), _write_node_maps(nodes)
            if persist:
                for directory in (BASE_DIR, DB_DIR, LOG_DIR, IODD_DIR):
                    directory.mkdir(parents=True, exist_ok=True)
                if config is None and not CONFIG_FILE.exists():
                    bundled = BUNDLE_DIR / "config.json"
                    if bundled.exists():
                        shutil.copy2(bundled, CONFIG_FILE)
                        loaded = load_config()
                if node_config is None and not NODES_FILE.exists():
                    bundled = BUNDLE_DIR / "nodes.json"
                    if bundled.exists():
                        shutil.copy2(bundled, NODES_FILE)
            with config_lock:
                config_store.clear()
                config_store.update(loaded)
                if persist and persist_missing_state:
                    if not RUNTIME_STATE_FILE.exists():
                        save_runtime_state(config_store)
                    if config is None:
                        persisted_config = _load_json_with_backup(CONFIG_FILE, {})
                        if isinstance(persisted_config, dict) and any(key in persisted_config for key in RUNTIME_STATE_KEYS):
                            save_config(config_store)
                OPCUA_NODE_CONFIG.clear()
                OPCUA_NODE_CONFIG.update(nodes)
                REMOTE_NODE_MAPS.clear()
                REMOTE_NODE_MAPS.update(read_maps)
                REMOTE_SIGNAL_NODES.clear()
                REMOTE_SIGNAL_NODES.update(write_maps)
                AMS00_NODES.clear()
                AMS00_NODES.update(read_maps.get("AMS00", {}))
                AMS01_NODES.clear()
                AMS01_NODES.update(read_maps.get("AMS01", {}))
                # Bootstrap compares the last persisted measurement hashes before any I/O.
                # Store hashes only, never node descriptors or endpoint credentials.
                previous_sources = dict(config_store.get("measurement_sources") or {})
                current_sources = _measurement_sources(config_store)
                epochs = dict(config_store.get("measurement_epochs") or {})
                for device, previous in previous_sources.items():
                    if current_sources.get(device) != previous:
                        epochs[device] = uuid.uuid4().hex
                sources = {**previous_sources, **current_sources}
                if sources != previous_sources or epochs != (config_store.get("measurement_epochs") or {}):
                    candidate = {**config_store, "measurement_sources": sources, "measurement_epochs": epochs}
                    if persist:
                        _config_journal().commit(
                            {k: v for k, v in candidate.items() if k not in RUNTIME_STATE_KEYS},
                            {k: candidate.get(k) for k in RUNTIME_STATE_KEYS})
                    config_store.update(measurement_sources=sources, measurement_epochs=epochs)
                _runtime_adapters_override = dict(adapters) if adapters is not None else None
                _exw1_topology_cache = _exw1_topology_signature = None
                _hub_instance = _hub_signature = None
                get_exw1_topology()
            load_schedules()
            _assets_app.directory = str(ASSETS_DIR)
            _assets_app.all_directories = [str(ASSETS_DIR)]
            _assets_app.config_checked = False
            _runtime_initialized = True

DAY_MAP  = {"Monday":"MON","Tuesday":"TUE","Wednesday":"WED",
            "Thursday":"THU","Friday":"FRI","Saturday":"SAT","Sunday":"SUN"}
SCHEDULE_STANDBY_SIGNAL_MODE = 8
MODE_MAP = {0:"AMS",1:"Operating",2:"Standby",3:"Isolation",SCHEDULE_STANDBY_SIGNAL_MODE:"Standby Signal"}
STATUS_WAITING = "WAITING"
STATUS_RUNNING = "RUNNING"
STATUS_DONE = "DONE"
STATUS_FAIL = "FAILED"

def can_control_device() -> bool:
    return is_demo_data_source() or (is_modbus_data_source() and device_connected) or device_connected or ensure_session()

def get_config_force_mode() -> int:
    try:
        return int(config_store.get("force_mode", "0"))
    except Exception:
        return 0

def schedule_status_key(status: str) -> str:
    text = str(status or "").strip().lower()
    if text in ("running", "run", "active") or status == STATUS_RUNNING:
        return "running"
    if text in ("done", "completed", "complete") or status == STATUS_DONE:
        return "done"
    if text in ("fail", "failed", "error") or status == STATUS_FAIL:
        return "fail"
    return "waiting"

def get_running_schedule_mode() -> Optional[int]:
    modes = {run.get("mode") for run in _schedule_execution.runs.values()
             if run.get("state") == "RUNNING"}
    return next(iter(modes)) if len(modes) == 1 else None

def get_display_force_mode() -> int:
    scheduled = get_running_schedule_mode()
    if scheduled is not None and scheduled != SCHEDULE_STANDBY_SIGNAL_MODE:
        return scheduled
    return get_config_force_mode()

def get_standby_signal_status() -> dict:
    return {
        "enabled":     config_store.get("standby_signal_enabled", False),
        "forced":      config_store.get("standby_signal_forced", False),
        "node_id":     _signal_node("AMS00", "standby"),
    }

def get_forced_standby_status() -> dict:
    return {
        "enabled": config_store.get("forced_standby_enabled", False),
        "node_id": _signal_node("AMS00", "forced_standby"),
    }

def get_air_supply_status() -> dict:
    return {
        "enabled":      config_store.get("air_supply_enabled", True),
        "signal_on":    config_store.get("air_supply_signal_on", True),
        "contact_mode": config_store.get("opcua_air_contact_mode", "NC"),
        "nc_node":      _signal_node("AMS00", "air_nc"),
        "no_node":      _signal_node("AMS00", "air_no"),
    }

def apply_standby_signal(result: dict):
    result["standby_signal_enabled"] = config_store.get("standby_signal_enabled", False)
    result["forced_standby_enabled"] = config_store.get("forced_standby_enabled", False)
    result["air_supply_enabled"]     = config_store.get("air_supply_enabled", True)
    result["air_supply_signal_on"]   = config_store.get("air_supply_signal_on", True)
    result["opcua_air_contact_mode"] = config_store.get("opcua_air_contact_mode", "NC")

def opcua_write_bool(node_id: str, value: bool) -> dict:
    t0 = time.time()
    result = opcua_write_bool_node(node_id, value)
    node_ms = round((time.time() - t0) * 1000, 1)
    if result.get("ok"):
        print(f"[OPCUA] write OK (node-opcua/primary) {node_id}={value} | node_write={node_ms}ms total={node_ms}ms")
    else:
        print(f"[OPCUA] write FAIL (node-opcua/primary) {node_id}={value} | node_write={node_ms}ms error={result.get('error')}")
    return result

def _signal_node(remote_id: str, signal: str) -> str:
    target = current_target(remote_id)
    if target is not None:
        return target.mapping.get(signal, "")
    nodes = REMOTE_SIGNAL_NODES.get(remote_id) or {}
    node_id = nodes.get(signal)
    if node_id:
        return node_id
    if remote_id != "AMS00":
        return ""
    legacy_keys = {
        "standby":        "opcua_standby_node",
        "forced_standby": "opcua_forced_standby_node",
        "air_nc":         "opcua_air_nc_node",
        "air_no":         "opcua_air_no_node",
    }
    return config_store.get(legacy_keys.get(signal, ""), "")

def set_standby_signal_enabled(enabled: bool, remote_id: str | None = None) -> dict:
    return _legacy_hub_command(remote_id, "standby", {"enabled": enabled})

def set_forced_standby_enabled(enabled: bool, remote_id: str | None = None) -> dict:
    return _legacy_hub_command(remote_id, "forced_standby", {"enabled": enabled})

def set_air_supply(enabled: bool, contact_mode: str, remote_id: str | None = None) -> dict:
    return _legacy_hub_command(remote_id, "air_supply", {"enabled": enabled, "contact_mode": contact_mode})

def set_port4_pdout(bytes_value: list[int], remote_id: str | None = None) -> dict:
    try:
        normalized = validate_command_payload("port4_pdout", {"bytes": bytes_value})["bytes"]
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "remote_id": remote_id}
    return _legacy_hub_command(remote_id, "port4_pdout", {"bytes": normalized})

def port4_do_pin_bit(pin: int) -> Optional[int]:
    if pin == 2:
        return _admitted_config_value("port4_do_pin2_bit", _admitted_config_value("port4_pin2_bit", 7))
    if pin == 4:
        return _admitted_config_value("port4_do_pin4_bit", _admitted_config_value("port4_pin4_bit", 6))
    return None

def set_port4_do(value: int, remote_id: str | None = None) -> dict:
    return _legacy_hub_command(remote_id, "port4_do", {"value": value})

def set_port4_do_pin(pin: int, enabled: bool, remote_id: str | None = None) -> dict:
    return _legacy_hub_command(remote_id, "port4_do", {"pin": pin, "enabled": enabled})

def _owned_worker():
    with node_worker_lock:
        proc = node_worker_proc
        owner = node_worker_owner
        _require_owned_worker(owner, proc)
        return owner, proc


def _require_owned_worker(owner, proc):
    # Caller holds node_worker_lock through the complete HTTP transaction.
    if (owner is None or proc is None or node_worker_owner is not owner
            or node_worker_proc is not proc or proc.poll() is not None):
        raise RuntimeError("owned node worker is not running or ownership changed")


def _clear_worker_caches():
    global _worker_remotes_cache, _worker_last_fetch, _worker_status_cache, _worker_status_at
    with worker_cache_lock:
        _worker_remotes_cache = {}
        _worker_last_fetch = 0.0
    # Lifecycle callers already hold worker_status_lock before node_worker_lock.
    # Reacquiring the non-reentrant status lock here would deadlock.
    _worker_status_cache = {}
    _worker_status_at = 0.0


def _issue_owned_worker_http(owner, method: str, path: str, *, json_body=None, timeout: float = 3.0):
    # A fresh session must ignore ALL_PROXY, netrc and every ambient proxy setting.
    with requests.Session() as session:
        session.trust_env = False
        resp = session.request(
            method,
            owner.base_url + path,
            json=json_body,
            headers=owner.headers(),
            timeout=timeout,
            allow_redirects=False,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"owned worker HTTP {resp.status_code} for {path}")
        return resp.json(), resp


def _owned_worker_request(method: str, path: str, *, json_body=None, timeout: float = 3.0, generation=None):
    # Match status-reader lock ordering: requests take only node_worker_lock;
    # lifecycle takes worker_status_lock first, then node_worker_lock.
    with node_worker_lock:
        if path != "/shutdown" and not _acquisition_enabled:
            raise RuntimeError("Device acquisition is disconnected")
        if path != "/shutdown" and str(config_store.get("data_source") or "opcua").lower() != "opcua":
            raise RuntimeError("OPC UA is not the selected data source")
        owner, proc = _owned_worker()
        if generation is not None:
            _require_same_generation(generation)
            if generation.get("opcua_endpoint") != owner.endpoint:
                raise RuntimeError("owned worker endpoint no longer matches this command generation")
        if path != "/status":
            _require_owned_worker(owner, proc)
            identity, _resp = _issue_owned_worker_http(owner, "GET", "/status", timeout=min(timeout, 0.6))
            _require_owned_worker(owner, proc)
            if not owner.validate_status(identity, expected_pid=proc.pid):
                raise RuntimeError("owned worker status identity mismatch")
            if generation is not None:
                _require_same_generation(generation)
        _require_owned_worker(owner, proc)
        data, resp = _issue_owned_worker_http(owner, method, path, json_body=json_body, timeout=timeout)
        _require_owned_worker(owner, proc)
        if path == "/status" and not owner.validate_status(data, expected_pid=proc.pid):
            raise RuntimeError("owned worker status identity mismatch")
        if generation is not None:
            _require_same_generation(generation)
        return data, resp


def _rotate_log_file(path: Path, max_bytes: int = 5 * 1024 * 1024, backups: int = 3):
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
        oldest = path.with_name(f"{path.name}.{backups}")
        if oldest.exists():
            oldest.unlink()
        for index in range(backups - 1, 0, -1):
            src = path.with_name(f"{path.name}.{index}")
            if src.exists():
                os.replace(src, path.with_name(f"{path.name}.{index + 1}"))
        os.replace(path, path.with_name(f"{path.name}.1"))
    except Exception as e:
        print(f"[LOG] rotation failed for {path.name}: {type(e).__name__}: {e}")

def start_node_worker():
    if not _acquisition_enabled:
        return
    _config_journal().require_clear()
    if _runtime_recovery_error:
        raise RecoveryRequired("configuration recovery required; worker disabled")
    with worker_status_lock:
        _start_node_worker_locked()


def _start_node_worker_locked():
    global node_worker_proc, node_worker_stdout, node_worker_stderr, node_worker_owner
    with node_worker_lock:
        if not _acquisition_enabled or str(config_store.get("data_source") or "opcua").lower() != "opcua":
            return
        if not any(profile.transport == "opcua" for profile in _configured_device_registry().all()):
            return
        if node_worker_proc and node_worker_proc.poll() is None and node_worker_owner is not None:
            return
        nodes_path = NODES_FILE if NODES_FILE.exists() else BUNDLE_DIR / "nodes.json"
        owner = WorkerOwner.create(
            nodes_path=Path(nodes_path).resolve(),
            endpoint=str(config_store.get("opcua_endpoint") or ""),
            password=str(config_store.get("ams_password") or ""),
            port=WORKER_PORT,
        )
        worker_script = BASE_DIR / "worker.js"
        if not worker_script.exists():
            worker_script = BUNDLE_DIR / "worker.js"
        node_exe = BASE_DIR / "vendor" / "node" / "node.exe"
        if not node_exe.exists():
            node_exe = BUNDLE_DIR / "vendor" / "node" / "node.exe"
        node_cmd = str(node_exe) if node_exe.exists() else "node"
        node_modules = worker_script.parent / "node_modules"
        env = owner.spawn_environment(os.environ)
        env["AMS_CONFIG_PATH"] = str(CONFIG_FILE)
        if node_modules.exists():
            env["NODE_PATH"] = str(node_modules)
        LOG_DIR.mkdir(exist_ok=True)
        if node_worker_stdout:
            try: node_worker_stdout.close()
            except Exception: pass
        if node_worker_stderr:
            try: node_worker_stderr.close()
            except Exception: pass
        stdout_path = LOG_DIR / "worker.out.log"
        stderr_path = LOG_DIR / "worker.err.log"
        _rotate_log_file(stdout_path)
        _rotate_log_file(stderr_path)
        node_worker_stdout = open(stdout_path, "a", encoding="utf-8")
        node_worker_stderr = open(stderr_path, "a", encoding="utf-8")
        try:
            node_worker_proc = subprocess.Popen(
                [node_cmd, str(worker_script)],
                cwd=str(worker_script.parent),
                env=env,
                stdout=node_worker_stdout,
                stderr=node_worker_stderr,
            )
        except Exception:
            for handle in (node_worker_stdout, node_worker_stderr):
                if handle:
                    try: handle.close()
                    except Exception: pass
            node_worker_stdout = None
            node_worker_stderr = None
            node_worker_owner = None
            raise
        node_worker_owner = owner
        _clear_worker_caches()
        print(f"[NODE_WORKER] started pid={node_worker_proc.pid} port={owner.port} instance={owner.instance_id}")

def _close_worker_logs():
    global node_worker_stdout, node_worker_stderr
    for handle in (node_worker_stdout, node_worker_stderr):
        if handle:
            try: handle.close()
            except Exception: pass
    node_worker_stdout = None
    node_worker_stderr = None


def stop_node_worker(timeout_s: float = 3.0):
    with worker_status_lock:
        _stop_node_worker_locked(timeout_s)


def _stop_node_worker_locked(timeout_s: float = 3.0):
    global node_worker_proc, node_worker_owner
    with node_worker_lock:
        owner = node_worker_owner
        proc = node_worker_proc
        if not proc:
            node_worker_owner = None
            _close_worker_logs()
            return
        if proc.poll() is not None:
            node_worker_proc = None
            node_worker_owner = None
            _close_worker_logs()
            _clear_worker_caches()
            return
        try:
            if owner is not None:
                # Authenticate passive status for our still-live child first.
                # A foreign listener never receives a shutdown operation.
                _owned_worker_request("POST", "/shutdown", timeout=0.8)
        except Exception:
            pass
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=timeout_s)
        finally:
            node_worker_proc = None
            node_worker_owner = None
            _close_worker_logs()
            _clear_worker_caches()

def restart_node_worker():
    with worker_status_lock:
        with node_worker_lock:
            _stop_node_worker_locked()
            _start_node_worker_locked()

def maybe_restart_node_worker(reason: str, *, expected_owner, expected_proc) -> bool:
    global _worker_last_restart_attempt
    # Failure handling releases node_worker_lock before entering here. Recheck
    # its captured ownership under the lifecycle locks so a delayed failure
    # cannot stop a replacement, or consume that replacement's retry throttle.
    with worker_status_lock:
        with node_worker_lock:
            if node_worker_owner is not expected_owner or node_worker_proc is not expected_proc:
                return False
            now = time.time()
            if now - _worker_last_restart_attempt < _WORKER_RESTART_MIN_INTERVAL_S:
                return False
            _worker_last_restart_attempt = now
            print(f"[NODE_WORKER] restart requested: {reason}")
            try:
                _stop_node_worker_locked()
                _start_node_worker_locked()
                return True
            except Exception as e:
                print(f"[NODE_WORKER] restart failed: {type(e).__name__}: {e}")
                return False

def wait_for_worker_http(timeout_s: float = 3.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            _owned_worker_request("GET", "/status", timeout=0.4)
            return True
        except Exception:
            time.sleep(0.1)
    return False

def ensure_node_worker_ready(timeout_s: float = 3.0) -> bool:
    if str(config_store.get("data_source") or "opcua").lower() != "opcua":
        return False
    if not (node_worker_proc and node_worker_proc.poll() is None and node_worker_owner is not None):
        start_node_worker()
    return wait_for_worker_http(timeout_s)


def _opcua_owned_write(path: str, payload: dict) -> dict:
    generation = config_generation_snapshot()
    if not ensure_node_worker_ready(timeout_s=8.0):
        return {"ok": False, "driver": "node-opcua", "error": f"node worker not ready (port {WORKER_PORT})"}
    try:
        data, _resp = _owned_worker_request("POST", path, json_body=payload, timeout=10, generation=generation)
        data["driver"] = "node-opcua"
        return data
    except requests.exceptions.ConnectionError:
        return {"ok": False, "driver": "node-opcua", "error": f"node worker not running (port {WORKER_PORT})"}
    except Exception as e:
        return {"ok": False, "driver": "node-opcua", "error": f"node-opcua: {type(e).__name__}: {e}"}


def opcua_write_bool_node(node_id: str, value: bool) -> dict:
    if type(value) is not bool:
        return {"ok": False, "driver": "node-opcua", "error": "boolean value required"}
    return _opcua_owned_write("/write", {"nodeId": node_id, "value": value})

def opcua_write_bytes_node(node_id: str, bytes_value: list[int]) -> dict:
    try:
        values = validate_command_payload("port4_pdout", {"bytes": bytes_value})["bytes"]
    except ValueError as exc:
        return {"ok": False, "driver": "node-opcua", "error": str(exc)}
    return _opcua_owned_write("/write-bytes", {"nodeId": node_id, "bytes": values})

def opcua_read_byte_node(node_id: str) -> int:
    # /read performs a fresh session.read, never the worker's subscription cache.
    generation = config_generation_snapshot()
    if not ensure_node_worker_ready(timeout_s=8.0):
        raise ValueError("node worker not ready")
    data, _ = _owned_worker_request("POST", "/read", json_body={"nodeId": node_id},
                                    timeout=10, generation=generation)
    if data.get("ok") is not True or data.get("error"):
        raise ValueError(data.get("error") or "Port 4 DO read failed")
    return validate_command_payload("port4_do", {"value": data.get("value")})["value"]


def opcua_write_byte_node(node_id: str, value: int) -> dict:
    try:
        normalized = validate_command_payload("port4_do", {"value": value})["value"]
    except ValueError as exc:
        return {"ok": False, "driver": "node-opcua", "error": str(exc)}
    return _opcua_owned_write("/write-byte", {"nodeId": node_id, "value": normalized})

# ?? ?곹깭 API ??????????????????????????????????????????????
def _get_worker_status() -> dict:
    if is_modbus_data_source():
        return {"connected":bool(device_connected),"driver":"modbus-tcp","host":config_store.get("modbus_host"),"port":config_store.get("modbus_port",502),"last_error":_modbus_live_error}
    global _worker_status_cache, _worker_status_at
    if is_demo_data_source():
        return {"connected": False, "disabled": True, "reason": "demo_mode"}
    now = time.time()
    with worker_status_lock:
        if _worker_status_cache and now - _worker_status_at < 1.0:
            return copy.deepcopy(_worker_status_cache)
        try:
            status, _resp = _owned_worker_request("GET", "/status", timeout=0.6)
        except Exception as e:
            status = {"connected": False, "error": f"worker_unreachable: {e}"}
        _worker_status_cache = status
        _worker_status_at = time.time()
        return copy.deepcopy(status)

@app.get("/api/status")
def api_status():
    worker_status = _get_worker_status()
    return {
        "server":                "ok",
        "device_connected":      device_connected,
        "ams_host":              get_ams_host(),
        "ams_channel":           get_ams_channel(),
        "save_interval_s":       get_save_interval(),
        "server_port":           config_store.get("server_port", 8000),
        "data_source":           config_store.get("data_source", "opcua"),
        "is_demo_live":          str(config_store.get("data_source", "opcua") or "").lower() == "demo",
        "force_mode":            get_display_force_mode(),
        "base_force_mode":       get_config_force_mode(),
        "standby_signal":        get_standby_signal_status(),
        "forced_standby_signal": get_forced_standby_status(),
        "air_supply":            get_air_supply_status(),
        "opcua_endpoint":        config_store.get("opcua_endpoint", "opc.tcp://192.168.0.1:4840"),
        "worker":                worker_status,
        "worker_last_fetch":     _worker_last_fetch,
    }

@app.get("/api/worker/status")
def api_worker_status():
    return _get_worker_status()

@app.get("/api/nodes/status")
def api_nodes_status():
    remotes = {}
    for remote_id in sorted(set(REMOTE_NODE_MAPS) | set(REMOTE_SIGNAL_NODES)):
        read_nodes = REMOTE_NODE_MAPS.get(remote_id, {})
        write_nodes = REMOTE_SIGNAL_NODES.get(remote_id, {})
        remotes[remote_id] = {
            "read_count": len(read_nodes),
            "write_count": len(write_nodes),
            "read": read_nodes,
            "write": write_nodes,
        }
    return {
        "ok": True,
        "nodes_file": str(NODES_FILE if NODES_FILE.exists() else BUNDLE_DIR / "nodes.json"),
        "remotes": remotes,
    }

@app.get("/api/remotes/status")
def api_remotes_status():
    payload = _read_hub_with_dio()
    items = []
    for device in payload.get("devices", []):
        item = copy.deepcopy(device)
        item["id"] = item.get("device_id") or item.get("remote_id")
        if item.get("transport") == "modbus":
            item["modbus_map"] = copy.deepcopy(MODBUS_AMS_CHANNEL_MAP.get(item["id"]))
        items.append(item)
    combined = copy.deepcopy(payload.get("combined") or {})
    return {
        "ok": True, "data_source": payload.get("data_source"), "base": combined,
        "remotes": items, "updated_at": payload.get("updated_at"),
        "worker": {"connected": bool(combined.get("online")), "driver": "device-hub"},
    }

@app.get("/api/settings")
def api_settings():
    return config_snapshot(exclude=("ams_password",))

class IoddUploadRequest(BaseModel):
    filename: str
    content: str

class IoddAssignRequest(BaseModel):
    remote_id: Optional[str] = "AMS00"
    port: Optional[str] = "port4"
    iodd_id: Optional[str] = None

@app.get("/api/iodd/library")
def api_iodd_library():
    items = _load_iodd_index()
    changed = False
    for idx, item in enumerate(items):
        item, item_changed = _enrich_iodd_item(item)
        if item_changed:
            items[idx] = item
            changed = True
    if changed:
        _save_iodd_index(items)
    return {
        "ok": True,
        "items": items,
        "assignments": config_store.get("iodd_assignments", {}) or {},
    }

@app.post("/api/iodd/upload")
def api_iodd_upload(req: IoddUploadRequest):
    raw_name = _safe_iodd_filename(req.filename)
    content = req.content or ""
    if not content.strip():
        return {"ok": False, "error": "empty_iodd_file"}
    digest = hashlib.sha1((raw_name + "\n" + content).encode("utf-8", errors="ignore")).hexdigest()[:12]
    stored_name = f"{digest}_{raw_name}"
    path = IODD_DIR / stored_name
    path.write_text(content, encoding="utf-8")

    item = _parse_iodd_metadata(content, raw_name)
    item.update({
        "id": digest,
        "stored_filename": stored_name,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
    })
    items = [x for x in _load_iodd_index() if x.get("id") != digest]
    items.append(item)
    items.sort(key=lambda x: (str(x.get("vendor") or ""), str(x.get("device") or ""), str(x.get("filename") or "")))
    _save_iodd_index(items)
    return {"ok": True, "item": item, "items": items}

@app.post("/api/iodd/assign")
def api_iodd_assign(req: IoddAssignRequest):
    remote_id = (req.remote_id or "AMS00").upper()
    port = (req.port or "port4").lower()
    if port != "port4":
        return {"ok": False, "error": "only_port4_supported_now"}
    assignments = dict(config_store.get("iodd_assignments", {}) or {})
    key = _assignment_key(remote_id, port)
    if req.iodd_id:
        if not _get_iodd_by_id(req.iodd_id):
            return {"ok": False, "error": "iodd_not_found"}
        assignments[key] = req.iodd_id
    else:
        assignments.pop(key, None)
    update_config_values(iodd_assignments=assignments)
    return {
        "ok": True,
        "remote_id": remote_id,
        "port": port,
        "assignment": get_iodd_assignment(remote_id, port),
        "assignments": assignments,
    }
# ?? ?곌껐 ?ㅼ젙 API ?????????????????????????????????????????
@app.get("/api/acquisition")
def acquisition_status():
    hub = _hub_instance
    return {"ok": True, "active": _acquisition_enabled,
            "connected": _acquisition_enabled and hub is not None and any(
                row.get("online") for row in (hub.cached().get("devices") or [])),
            "data_source": config_store.get("data_source", "opcua"),
            "address": (str(config_store.get("modbus_host") or "") + ":" + str(config_store.get("modbus_port", 502))
                       if is_modbus_data_source() else str(config_store.get("opcua_endpoint") or config_store.get("ams_host") or "")),
            "connect_automatically": config_store.get("connect_automatically") is True}


def _disconnect_acquisition():
    global _acquisition_enabled, device_connected, ams_session, _hub_instance, _hub_signature
    with _configuration_admission.transition():
        _acquisition_enabled = False
        device_connected = False
        ams_session = None
        stop_node_worker()
        _clear_worker_caches()
        with _modbus_live_lock:
            _modbus_live_cache.clear()
        with _hub_lock:
            _hub_instance = _hub_signature = None
        _bump_config_generation()
    return acquisition_status()


@app.post("/api/acquisition/disconnect")
def disconnect_acquisition():
    return _disconnect_acquisition()


@app.post("/api/acquisition/connect")
def connect_acquisition():
    global _acquisition_enabled
    _config_journal().require_clear()
    with _configuration_admission.transition():
        _acquisition_enabled = True
    # Acquisition and worker startup belong to the existing coordinator, not HTTP.
    return {**acquisition_status(), "state": "connecting"}


class AutoConnectConfig(BaseModel):
    connect_automatically: bool


@app.post("/api/config/auto-connect")
def update_auto_connect(req: AutoConnectConfig):
    try:
        update_config_values(connect_automatically=req.connect_automatically)
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    return acquisition_status()


class ConnectionConfig(BaseModel):
    ams_host:     str
    ams_password: Optional[str] = None
    ams_channel:  int = 0

@app.get("/api/config/connection")
def get_connection_config():
    return {
        "ok": True,
        "ams_host": config_store.get("ams_host", ""),
        "ams_channel": int(config_store.get("ams_channel", 0)),
        "opcua_endpoint": config_store.get("opcua_endpoint", ""),
        "password_configured": bool(config_store.get("ams_password")),
    }

@app.post("/api/config/connection")
async def update_connection(req: ConnectionConfig):
    global ams_session, device_connected
    changes = {
        "ams_host":       req.ams_host,
        "ams_channel":    req.ams_channel,
        "opcua_endpoint": opcua_endpoint_from_ams_host(req.ams_host),
    }
    if req.ams_password:
        changes["ams_password"] = req.ams_password
    try:
        update_config_values(**changes)
    except (ValueError, OSError) as exc:
        return {"ok": False, "saved": False, "error": str(exc)}
    await asyncio.to_thread(_disconnect_acquisition)
    ok = False
    return {
        "ok": True,
        "saved": True,
        "device_connected": ok,
        "warning": None if ok else "saved_but_not_connected",
        "ams_host": get_ams_host(),
        "opcua_endpoint": config_store.get("opcua_endpoint"),
    }

# ?? ?먮꼫吏 湲곗?媛?API ?????????????????????????????????????
class EnergyConfig(BaseModel):
    kwh_per_m3:    Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    price_per_kwh: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    co2_per_kwh:   Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    tree_per_co2:  Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)

@app.post("/api/config/energy")
def update_energy_config(req: EnergyConfig):
    changes = {}
    if req.kwh_per_m3    is not None: changes["energy_kwh_per_m3"]    = req.kwh_per_m3
    if req.price_per_kwh is not None: changes["energy_price_per_kwh"] = req.price_per_kwh
    if req.co2_per_kwh   is not None: changes["energy_co2_per_kwh"]   = req.co2_per_kwh
    if req.tree_per_co2  is not None: changes["energy_tree_per_co2"]  = req.tree_per_co2
    if changes:
        update_config_values(**changes)
    return {"ok": True, "kwh_per_m3": get_kwh_per_m3(), "price_per_kwh": get_price_per_kwh(),
            "co2_per_kwh": get_co2_per_kwh(), "tree_per_co2": get_tree_per_co2()}


class DataSourceConfig(BaseModel):
    data_source: str


@app.get("/api/config/data-source")
def get_data_source_config():
    source = str(config_store.get("data_source", "opcua") or "opcua").lower()
    return {
        "ok": True,
        "data_source": source,
        "is_demo_live": source == "demo",
        "options": ["opcua", "web", "demo", "modbus"],
    }


@app.post("/api/config/data-source")
def update_data_source_config(req: DataSourceConfig):
    global device_connected, _demo_live_state
    source = str(req.data_source or "").strip().lower()
    if source not in {"opcua", "web", "demo", "modbus"}:
        return {"ok": False, "error": "data_source must be opcua, web, demo, or modbus"}
    def build_changes(current):
        changes = {"data_source": source}
        if source != str(current.get("data_source", "opcua") or "opcua").lower():
            # This reset is necessary: legacy usage tracking has no source key.
            changes["dashboard_last_raw_accumulated_l"] = None
        return changes
    try:
        update_config_values(_build_changes=build_changes)
    except (ValueError, OSError) as exc:
        return {"ok": False, "saved": False, "error": str(exc)}
    _disconnect_acquisition()
    if source == "demo":
        # reset motion clock so presentation starts cleanly when toggled on
        with demo_live_lock:
            _demo_live_state["started_at"] = None
            _demo_live_state["last_tick"] = None
            _demo_live_state["mode"] = None
            _demo_live_state["flow"] = None
            _demo_live_state["pressure"] = None
            _demo_live_state["temperature"] = None
        device_connected = False
        stop_node_worker()
    elif source == "opcua":
        device_connected = False
        start_node_worker()
    else:
        device_connected = False
        stop_node_worker()
    return {
        "ok": True,
        "data_source": source,
        "is_demo_live": source == "demo",
    }

class ModbusConnectionConfig(BaseModel):
    host: str
    port: int = 502
    unit_id: int = 1
    ch1_model: int = 40
    ch2_model: int = 40
    process_byte_swap: bool = True
    accumulator_word_swap: bool = True


def _modbus_gateways_for_connection(host: str, req: ModbusConnectionConfig, current=None) -> dict:
    current = config_store if current is None else current
    raw = copy.deepcopy(current.get("modbus_gateways", {}))
    if not isinstance(raw, dict):
        raise ValueError("repair invalid modbus_gateways through the topology editor")
    if not raw:
        if current.get("modbus_gateways_explicit"):
            raise ValueError("explicit empty topology has no gateway; configure topology first")
        candidate = {**current, "modbus_host": host, "modbus_port": int(req.port), "modbus_unit_id": int(req.unit_id), "modbus_exa1_ch1_model": int(req.ch1_model), "modbus_exa1_ch2_model": int(req.ch2_model)}
        raw = default_topology_config(candidate)["gateways"]
    gateway_id = next(iter(raw))
    gateway = raw[gateway_id]
    gateway.update({"host": host, "port": int(req.port), "unit_id": int(req.unit_id), "timeout_s": float(current.get("modbus_timeout_s", 1.5)), "diagnostics": "advanced", "max_slots": 15})
    for slot in gateway.get("slots") or []:
        if int(slot.get("channel", 0)) == 1:
            slot["model"] = int(req.ch1_model)
        elif int(slot.get("channel", 0)) == 2:
            slot["model"] = int(req.ch2_model)
    return raw


@app.get("/api/config/modbus")
def get_modbus_config():
    topology = get_exw1_topology()
    gateway = next(iter(topology.gateways.values()), None)
    return {"ok":True,"data_source":config_store.get("data_source"),"gateway_id":gateway.gateway_id if gateway else None,
            "host":gateway.host if gateway else None,"port":gateway.port if gateway else None,
            "unit_id":gateway.unit_id if gateway else None,"timeout_s":gateway.timeout_s if gateway else None,
            "ch1_model":config_store.get("modbus_exa1_ch1_model"),"ch2_model":config_store.get("modbus_exa1_ch2_model"),
            "process_byte_swap":bool(config_store.get("modbus_process_byte_swap",True)),"accumulator_word_swap":bool(config_store.get("modbus_accumulator_word_swap",True)),
            "connected":bool(device_connected) and bool(gateway),"last_error":_modbus_live_error,"topology":topology.to_dict(),
            "recovery":topology.recovery(),"raw_modbus_gateways":copy.deepcopy(config_store.get("modbus_gateways"))}


@app.post("/api/config/modbus")
def update_modbus_config(req: ModbusConnectionConfig):
    global device_connected, _modbus_live_cache, _modbus_live_at, _exw1_topology_cache, _exw1_topology_signature, _hub_instance, _hub_signature
    host=str(req.host or "").strip().replace("modbus://","").split("/")[0]
    if not host: return {"ok":False,"error":"Modbus host is required"}
    if not 1 <= int(req.port) <= 65535: return {"ok":False,"error":"port must be 1..65535"}
    if not 0 <= int(req.unit_id) <= 255: return {"ok":False,"error":"unit_id must be 0..255"}
    if req.ch1_model not in _EXA1_UNIT_IDS or req.ch2_model not in _EXA1_UNIT_IDS: return {"ok":False,"error":"EXA1 model must be 20, 30, 40, or 60"}
    def build_changes(current):
        gateways = _modbus_gateways_for_connection(host, req, current)
        return dict(modbus_host=host, modbus_port=int(req.port), modbus_unit_id=int(req.unit_id),
                    modbus_exa1_ch1_model=int(req.ch1_model), modbus_exa1_ch2_model=int(req.ch2_model),
                    modbus_process_byte_swap=bool(req.process_byte_swap),
                    modbus_accumulator_word_swap=bool(req.accumulator_word_swap),
                    modbus_gateways=gateways, data_source="modbus", dashboard_last_raw_accumulated_l=None)
    try:
        update_config_values(_build_changes=build_changes)
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        return {"ok": False, "saved": False, "error": str(exc)}
    with _exw1_topology_lock:
        _exw1_topology_cache=None; _exw1_topology_signature=None
    with _hub_lock:
        _hub_instance=None; _hub_signature=None
    _disconnect_acquisition()
    snapshot={}
    exa_ids=[device_id for device_id, profile in _enabled_modbus_profiles().items() if profile.metadata.get("device_kind") == "exa1"]
    connected=bool(exa_ids) and all(snapshot.get(remote_id,{}).get("device_connected") for remote_id in exa_ids)
    device_connected=any(item.get("device_connected") for item in snapshot.values())
    return {"ok":True,"data_source":"modbus","connected":connected,"partial":device_connected and not connected,"error":None if connected else _modbus_live_error,"config":get_modbus_config()}


@app.get("/api/modbus/status")
def api_modbus_status():
    if not is_modbus_data_source(): return {"ok":False,"connected":False,"error":"modbus_mode_not_active"}
    snapshot=fetch_modbus_remotes(True)
    topology=get_exw1_topology(); device_ids=list(_enabled_modbus_profiles()); online=[remote_id for remote_id in device_ids if snapshot.get(remote_id,{}).get("device_connected")]; gateways=[gateway.to_dict() for gateway in topology.gateways.values()]
    return {"ok":True,"connected":bool(device_ids) and len(online)==len(device_ids),"partial":bool(online) and len(online)<len(device_ids),"online_count":len(online),"device_count":len(device_ids),"gateways":gateways,"last_error":_modbus_live_error,"channels":snapshot,"topology":topology.to_dict()}
@app.get("/api/config/energy")
def get_energy_config():
    return {"kwh_per_m3":    get_kwh_per_m3(),
            "price_per_kwh": get_price_per_kwh(),
            "co2_per_kwh":   get_co2_per_kwh(),
            "tree_per_co2":  get_tree_per_co2()}

# ?? ?붾컮?댁뒪 ?ㅼ젙 ?쎄린 API ????????????????????????????????
# EXW1-BMTAC asynchronous parameter service (Modbus TCP).
# Request 0x1300..0x136F must always be written as 112 words (224 bytes).
_MODBUS_SERVICE_LOCK = threading.Lock()
_modbus_sequence = 0
_EXA1_UNIT_IDS = {20: 0x0386, 30: 0x0387, 40: 0x0388, 60: 0x0389}
# Register/param numbers verified against SMC's official EXA1-SA HUB Unit
# parameter table (DOC1069997, p.123) - the EXW1-BMTAC async service (0x1300
# request / 0x1400 response) addresses the same underlying EXA1-SA parameter
# index space that EtherNet/IP explicit messaging and PROFINET record access
# use, just over a different transport. 0x65-0x6D confirmed 1:1 against that
# table, including the per-model unit IDs in _EXA1_UNIT_IDS (0x386/7/8/9).
# "ramp_duration" is renamed to the official name "soft_start_time_s" below.
_EXA1_BMTAC_STATUS_TEXT = {
    0x00: "OK",
    0x10: "manufacturer mismatch (expected 0x0010)",
    0x11: "busy / previous request still in progress",
    0x12: "timeout waiting for the parameter service",
    0x13: "request payload length error",
    0x14: "unit_id not mapped to a remote EXA1",
    0x15: "wireless channel not registered on the base",
    0x16: "parameter number not supported on this unit",
    0x17: "parameter count error",
    0x18: "reserved field must be 0",
    0x1A: "queue overflow (too many queued requests)",
    0x1B: "wireless link to remote is down or unstable",
    0x1C: "remote rejected the value (hardware limit / lock)",
    0x1D: "read/write service code mismatch (expected 0x32 read / 0x33 write)",
    0x1E: "parameter type / size mismatch",
    0x1F: "value out of range, locked, or preconditions not met",
}
class BmtacServiceError(ValueError):
    """Raised when the EXW1-BMTAC parameter service returns a non-zero status."""
    def __init__(self, status, *, parameter_no=None, remote_id=None):
        self.status = int(status) & 0xFF
        self.parameter_no = parameter_no
        self.remote_id = remote_id
        super().__init__(self._describe())
    def _describe(self):
        return f"BMTAC service status 0x{self.status:02X} ({_EXA1_BMTAC_STATUS_TEXT.get(self.status, chr(34)+chr(117)+chr(110)+chr(107)+chr(110)+chr(111)+chr(119)+chr(110)+chr(34))})"
_EXA1_PARAMETERS = {
    "operation_kpa": (0x65, "u16", 0, 1050), "standby_kpa": (0x66, "u16", 0, 1050),
    "soft_start_time_s": (0x67, "u16", 0, 1500), "standby_threshold_lmin": (0x68, "u16", None, None),
    "standby_hysteresis_lmin": (0x69, "u16", None, None), "standby_on_delay_s": (0x6A, "u16", 0, 9999),
    "standby_off_delay_s": (0x6B, "u16", 0, 9999), "isolation_enabled": (0x6C, "u8", 0, 1),
    "isolation_delay_s": (0x6D, "u16", 0, 9999), "ar_itv_active": (0x73, "u8", 0, 1),
}
# AR/ITV Active Mode (0x73) is a diagnostic/status item per the official
# table, not a user-settable parameter - it stays in _EXA1_PARAMETERS so it
# is still read back with the rest of the settings, but writes to it are
# rejected below.
_EXA1_READONLY_PARAMETERS = {"ar_itv_active"}

@contextmanager
def _modbus_endpoint_operation(remote_id=None, gateway_id=None):
    """Admission freezes routing; physical endpoint lock replaces global I/O locks."""
    with _command_generation():
        if remote_id is not None:
            profile = _require_modbus_target(remote_id)
            target = _resolve_command_target(profile)
            with target_scope(target), _connection_contexts.context_for(profile).lock:
                yield
        else:
            topology = load_exw1_topology(_configuration_admission.current()["config"], strict=False)
            gateway = topology.gateway(gateway_id)
            profile = DeviceProfile(device_id="GATEWAY", transport="modbus",
                                    endpoint=f"{gateway.host}:{gateway.port}")
            with _connection_contexts.context_for(profile).lock:
                yield


def _modbus_request(function, payload, *, remote_id=None, gateway_id=None):
    with _modbus_endpoint_operation(remote_id, gateway_id):
        return _modbus_client_for(remote_id=remote_id, gateway_id=gateway_id).request(int(function), payload)


def _modbus_read_registers(address, count, *, remote_id=None, gateway_id=None):
    with _modbus_endpoint_operation(remote_id, gateway_id):
        return _modbus_client_for(remote_id=remote_id, gateway_id=gateway_id).read_holding_registers(int(address), int(count))


def _modbus_write_registers(address, values, *, remote_id=None, gateway_id=None):
    with _modbus_endpoint_operation(remote_id, gateway_id):
        _modbus_client_for(remote_id=remote_id, gateway_id=gateway_id).write_registers(int(address), values)

_modbus_live_lock = threading.Lock()
_modbus_live_cache = {}
_modbus_live_at = 0.0
_modbus_live_generation = None
_modbus_live_error = None


def is_modbus_data_source() -> bool:
    return str(config_store.get("data_source", "") or "").lower() == "modbus"


def _modbus_exa1_model(remote_id: str) -> int:
    target = current_target(remote_id)
    if target is not None:
        return int(json.loads(target.profile_json)["model"])
    try:
        slot = get_exw1_topology().slot_for_device(remote_id)
        if slot.kind != "exa1" or slot.model is None:
            raise ValueError(f"{remote_id} is not an EXA1 slot")
        return int(slot.model)
    except KeyError:
        key = "modbus_exa1_ch2_model" if str(remote_id).upper() == "AMS02" else "modbus_exa1_ch1_model"
        return int(config_store.get(key, config_store.get("modbus_exa1_model", 40)))


def _swap_word_bytes(value: int) -> int:
    value = int(value) & 0xFFFF
    return ((value & 0xFF) << 8) | (value >> 8)


def _modbus_logical_word(value: int) -> int:
    value = int(value) & 0xFFFF
    return value if bool(_admitted_config_value("modbus_process_byte_swap", True)) else _swap_word_bytes(value)


def _modbus_wire_word(value: int) -> int:
    return _modbus_logical_word(value)


def _decode_modbus_exa1(remote_id: str, raw_words: list[int], output_words: list[int]) -> dict:
    if len(raw_words) != 18 or len(output_words) != 9:
        raise ValueError(f"{remote_id} invalid process data size")
    words = [_modbus_logical_word(v) for v in raw_words]
    outputs = [_modbus_logical_word(v) for v in output_words]
    first, second = words[0], words[1]
    accumulated_raw = ((second << 16) | first) if bool(config_store.get("modbus_accumulator_word_swap", True)) else ((first << 16) | second)
    temperature_raw = words[3] - 0x10000 if words[3] & 0x8000 else words[3]
    status_word = words[5]; state_code = status_word & 0xFF; state = decode_ams_status(state_code)
    pressure_raw = words[4] - 0x10000 if words[4] & 0x8000 else words[4]
    p4_status_word = int(raw_words[9]) & 0xFFFF; p4_pqi = (p4_status_word >> 8) & 0xFF; port3_di = p4_status_word & 0xFF
    p4_in = []; p4_out = []
    for word in raw_words[10:18]: p4_in.extend([((int(word) & 0xFFFF) >> 8) & 0xFF, int(word) & 0xFF])
    for word in output_words[1:9]: p4_out.extend([((int(word) & 0xFFFF) >> 8) & 0xFF, int(word) & 0xFF])
    # EXA1 logical byte 0 is control and byte 1 is Port 4 DO. The BMTAC
    # Byte Swap setting decides which wire byte contains each logical byte.
    control = _modbus_logical_word(output_words[0]); control_hi = (control >> 8) & 0xFF; p4_do = control & 0xFF
    result = {
        "timestamp":datetime.now().isoformat(timespec="seconds"),
        "remote_id":remote_id,"name":remote_id,"online":True,"device_connected":True,"data_source":"modbus",
        "accumulated_flow_l":accumulated_raw * 10.0,"instant_flow_l_min":float(words[2]),
        "temperature_c":round(temperature_raw * 0.1,1),"pressure_mpa":round(pressure_raw * 0.001,3),
        "itv_pressure_mpa":round(words[6] * 0.001,3),"ams_code":state_code,
        "ams_status":state.get("label") or state.get("status") or str(state_code),
        "diagnostic":"No error" if ((status_word >> 8) & 0xC0) == 0 else f"AMS diagnostic 0x{(status_word >> 8) & 0xFF:02X}",
        "port3_di":port3_di,"port3_di_hex":f"{port3_di:02X}","port4_pqi":p4_pqi,"port4_pqi_hex":f"{p4_pqi:02X}",
        "port4_status":"Operate" if p4_pqi & 0x80 else "No live data",
        "port4_pdin_hex":[f"{v:02X}" for v in p4_in],"port4_pdin_text":" ".join(f"{v:02X}" for v in p4_in),
        "port4_do":p4_do,"port4_do_hex":f"{p4_do:02X}","port4_pdout_hex":[f"{v:02X}" for v in p4_out],
        "port4_pdout_text":" ".join(f"{v:02X}" for v in p4_out),"standby_signal":bool(control_hi & 1),
        "forced_standby":bool(control_hi & 2),"air_nc":bool(control_hi & 4),"air_no":bool(control_hi & 8),
    }
    return attach_iodd_context(result, remote_id)


def _words_to_hex(words: list[int]) -> list[str]:
    result = []
    for raw in words:
        word = int(raw) & 0xFFFF
        result.extend([f"{(word >> 8) & 0xFF:02X}", f"{word & 0xFF:02X}"])
    return result


def _byte_bits(hex_byte: str | None) -> list[bool]:
    # bit0 (LSB) first, matching how dio_code already reads bits 0-1.
    value = int(hex_byte, 16) if hex_byte else 0
    return [bool(value & (1 << i)) for i in range(8)]


def _decode_modbus_remote_io(remote_id: str, input_words: list[int], output_words: list[int], mapping: dict) -> dict:
    expected_input = int(mapping.get("input_words", 0))
    expected_output = int(mapping.get("output_words", 0))
    if len(input_words) != expected_input or len(output_words) != expected_output:
        raise ValueError(f"{remote_id} invalid Remote I/O process data size")
    input_hex = _words_to_hex(input_words)
    output_hex = _words_to_hex(output_words)
    logical_input_hex = _words_to_hex([_modbus_logical_word(word) for word in input_words])
    logical_output_hex = _words_to_hex([_modbus_logical_word(word) for word in output_words])
    dio_code = (int(logical_input_hex[0], 16) & 0x03) if logical_input_hex else 0
    # EXW1-RD is an 8-point DI / 8-point DO module - the physical bits live
    # in the first logical byte of the input/output block. The remaining
    # words in the block are reserved/unused padding.
    input_bits = _byte_bits(logical_input_hex[0] if logical_input_hex else None)
    output_bits = _byte_bits(logical_output_hex[0] if logical_output_hex else None)
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "remote_id": remote_id,
        "name": mapping.get("display_name") or remote_id,
        "online": True,
        "device_connected": True,
        "data_source": "modbus",
        "device_kind": "remote_io",
        "wireless_channel": mapping.get("wireless_channel"),
        "ams_code": 0,
        "ams_status": "Remote I/O",
        "diagnostic": "No error",
        "process_input_hex": input_hex,
        "process_input_text": " ".join(input_hex),
        "process_input_logical_hex": logical_input_hex,
        "dio_code": dio_code,
        "dio_code_binary": f"{dio_code:02b}",
        "input_bits": input_bits,
        "process_output_hex": output_hex,
        "process_output_text": " ".join(output_hex),
        "process_output_logical_hex": logical_output_hex,
        "output_bits": output_bits,
        "modbus_map": copy.deepcopy(mapping),
    }


def _modbus_failure(remote_id: str, mapping: dict, error: str) -> dict:
    return {
        "remote_id": remote_id,
        "name": mapping.get("display_name") or remote_id,
        "online": False,
        "device_connected": False,
        "data_source": "modbus",
        "device_kind": mapping.get("device_kind"),
        "wireless_channel": mapping.get("wireless_channel"),
        "modbus_map": copy.deepcopy(mapping),
        "error": error,
    }


def _wireless_channel_connected_map(words: list[int]) -> dict[int, bool] | None:
    # HR2050 - the 3rd word of the 5-word "advanced diagnostics" block at
    # base 2048 - is the "Remote connection status" word per SMC's EXW1-01
    # register table: low byte (byte 4) bit0 reserved, bit1..bit7 = CH1..CH7;
    # high byte (byte 5) bit0..bit7 = CH8..CH15. Confirmed against live
    # hardware (HR2050=0x0002, reg2052 registration status 0x2006 matching
    # the configured CH1/CH2/CH13 slots exactly under this same bit layout):
    # polarity is bit SET = connected, matching CH1 (bit1 set -> AMS01
    # connected) and CH2 (bit2 clear -> AMS02 not connected).
    if len(words) < 3:
        return None
    reg2050 = int(words[2]) & 0xFFFF
    low = reg2050 & 0xFF
    high = (reg2050 >> 8) & 0xFF
    connected: dict[int, bool] = {}
    for ch in range(1, 8):
        connected[ch] = bool(low & (1 << ch))
    for ch in range(8, 16):
        connected[ch] = bool(high & (1 << (ch - 8)))
    return connected


def _read_gateway_wireless_diagnostics(gateway) -> dict:
    # The topology reserves 5 holding registers (base 2048..2052, "advanced
    # diagnostics") immediately before the first channel's process-data
    # block. HR2050 (index 2) carries the real per-remote wireless
    # connection-status bitmap (see _wireless_channel_connected_map) -
    # separate from connection_context, which only reflects whether the
    # plain Modbus TCP read to the gateway itself succeeded, not whether a
    # given wireless remote is actually paired.
    if gateway.diagnostics != "advanced":
        return {}
    base = 2048
    try:
        client = _modbus_client_for(gateway_id=gateway.gateway_id)
        words = client.read_holding_registers(base, 5)
        if len(words) != 5:
            raise ValueError(f"Incomplete wireless diagnostics: expected 5 registers, got {len(words)}")
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    bits_by_word = {}
    for i, word in enumerate(words):
        bits_by_word[f"reg{base+i}"] = [bool(word & (1 << b)) for b in range(16)]
    return {
        "base_address": base,
        "raw_hex": [f"{w:04X}" for w in words],
        "bits_by_word": bits_by_word,
        "channel_connected": _wireless_channel_connected_map(words),
    }


def _read_modbus_slot_blocks(client, slots, direction: str) -> dict:
    # Coalesce adjacent admitted slots only. Never read across a disabled or
    # quarantined slot merely because valid slots exist on either side of it.
    groups = []
    for slot in sorted(slots, key=lambda item: getattr(item, f"{direction}_start")):
        start = getattr(slot, f"{direction}_start")
        count = getattr(slot, f"{direction}_words")
        if groups and groups[-1][1] == start and start + count - groups[-1][0] <= 125:
            groups[-1][1] += count
            groups[-1][2].append(slot)
        else:
            groups.append([start, start + count, [slot]])
    result = {}
    for start, end, members in groups:
        block = client.read_holding_registers(start, end - start)
        for slot in members:
            offset = getattr(slot, f"{direction}_start") - start
            count = getattr(slot, f"{direction}_words")
            result[slot.device_id.upper()] = block[offset:offset + count]
    return result


@_command_generation()
def fetch_modbus_remotes(force: bool = False) -> dict:
    global _modbus_live_cache, _modbus_live_at, _modbus_live_error, device_connected, _modbus_live_generation
    generation = current_config_generation()
    enabled = _enabled_modbus_profiles()
    with _modbus_live_lock:
        if not force and _modbus_live_generation == generation and _modbus_live_cache and time.time() - _modbus_live_at < 0.25:
            return copy.deepcopy({key: row for key, row in _modbus_live_cache.items() if key in enabled})
        topology = get_exw1_topology()
        result = {}
        errors = []
        for gateway_id, gateway in topology.gateways.items():
            slots = [slot for slot in topology.slots_for_gateway(gateway_id, device_only=True) if slot.device_id.upper() in enabled]
            if not slots:
                continue  # No diagnostics or block reads for an inactive gateway.
            mappings = {slot.device_id.upper(): MODBUS_AMS_CHANNEL_MAP[slot.device_id.upper()] for slot in slots}
            client = _modbus_client_for(gateway_id=gateway_id)
            gateway_diag = _read_gateway_wireless_diagnostics(gateway)
            exa_slots = [slot for slot in slots if slot.kind == "exa1"]
            io_slots = [slot for slot in slots if slot.kind == "remote_io"]
            gateway_failed = False
            if exa_slots:
                try:
                    input_blocks = _read_modbus_slot_blocks(client, exa_slots, "input")
                    output_blocks = _read_modbus_slot_blocks(client, exa_slots, "output")
                    for slot in exa_slots:
                        remote_id = slot.device_id.upper()
                        raw = input_blocks[remote_id]
                        output = output_blocks[remote_id]
                        decoded = _decode_modbus_exa1(remote_id, raw, output)
                        decoded.update({"device_kind": "exa1", "wireless_channel": slot.channel, "gateway_id": gateway_id, "modbus_map": copy.deepcopy(mappings[remote_id]), "gateway_diagnostics": gateway_diag})
                        wireless_connected = (gateway_diag.get("channel_connected") or {}).get(slot.channel)
                        decoded["wireless_connected"] = wireless_connected
                        if gateway_diag.get("error") or wireless_connected is None:
                            decoded["online"] = decoded["device_connected"] = False
                            decoded["error"] = gateway_diag.get("error") or f"Wireless connection status unknown for channel {slot.channel}"
                            errors.append(f"{gateway_id}/{remote_id}: {decoded['error']}")
                        elif wireless_connected is not None:
                            decoded["online"] = wireless_connected
                            decoded["device_connected"] = wireless_connected
                        result[remote_id] = decoded
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    errors.append(f"{gateway_id}: {error}")
                    gateway_failed = True
                    for slot in slots:
                        remote_id = slot.device_id.upper()
                        result[remote_id] = _modbus_failure(remote_id, mappings[remote_id], error)
            if gateway_failed:
                continue
            for slot in io_slots:
                remote_id = slot.device_id.upper()
                try:
                    raw = client.read_holding_registers(slot.input_start, slot.input_words)
                    output = client.read_holding_registers(slot.output_start, slot.output_words)
                    decoded = _decode_modbus_remote_io(remote_id, raw, output, mappings[remote_id])
                    decoded["gateway_id"] = gateway_id
                    decoded["gateway_diagnostics"] = gateway_diag
                    wireless_connected = (gateway_diag.get("channel_connected") or {}).get(slot.channel)
                    decoded["wireless_connected"] = wireless_connected
                    if gateway_diag.get("error") or wireless_connected is None:
                        decoded["online"] = decoded["device_connected"] = False
                        decoded["error"] = gateway_diag.get("error") or f"Wireless connection status unknown for channel {slot.channel}"
                        errors.append(f"{gateway_id}/{remote_id}: {decoded['error']}")
                    elif wireless_connected is not None:
                        decoded["online"] = wireless_connected
                        decoded["device_connected"] = wireless_connected
                    result[remote_id] = decoded
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    errors.append(f"{gateway_id}/{remote_id}: {error}")
                    result[remote_id] = _modbus_failure(remote_id, mappings[remote_id], error)
        _check_command_generation()
        _modbus_live_cache = result
        _modbus_live_generation = generation
        _modbus_live_at = time.time()
        _modbus_live_error = "; ".join(errors) or None
        device_connected = any(item.get("device_connected") for item in result.values())
        return copy.deepcopy(result)


def fetch_process_data_modbus() -> dict:
    remotes=fetch_modbus_remotes(); ch1=remotes.get("AMS01", {"error": "AMS01 is absent, disabled or quarantined"}); ch2=remotes.get("AMS02", {})
    if not ch1.get("device_connected"):
        return {"error":ch1.get("error","modbus_disconnected"),"device_connected":False,"data_source":"modbus"}
    result=copy.deepcopy(ch1); online=[r for r in (ch1,ch2) if r.get("device_connected")]
    result["combined_instant_flow_l_min"]=round(sum(float(r.get("instant_flow_l_min") or 0) for r in online),2)
    result["combined_accumulated_flow_l"]=round(sum(float(r.get("accumulated_flow_l") or 0) for r in online),2)
    result["modbus_remote_count"]=len(online)
    return apply_usage_tracking(result,persist=False)
@_command_generation()
def _modbus_update_output_control(remote_id: str, mutate) -> dict:
    global _modbus_live_cache, _modbus_live_at
    remote_id = _require_modbus_target(remote_id).device_id
    mapping = _command_mapping(remote_id)
    if not mapping or mapping.get("device_kind") != "exa1": return {"ok":False,"error":"modbus_exa1_not_mapped","remote_id":remote_id}
    with _modbus_endpoint_operation(remote_id):
        address=mapping["output_start"]
        current_wire=int(_modbus_read_registers(address,1,remote_id=remote_id)[0]) & 0xFFFF
        current=_modbus_logical_word(current_wire)
        high,low=mutate((current >> 8) & 0xFF,current & 0xFF)
        updated=((high & 0xFF) << 8) | (low & 0xFF)
        updated_wire=_modbus_wire_word(updated)
        _modbus_write_registers(address,[updated_wire],remote_id=remote_id)
        readback_wire=int(_modbus_read_registers(address,1,remote_id=remote_id)[0]) & 0xFFFF
        readback=_modbus_logical_word(readback_wire)
    verified = readback == updated
    # A successful write must invalidate the short-lived process-data cache;
    # otherwise the next UI poll can briefly restore the pre-write value.
    with _modbus_live_lock:
        _modbus_live_cache = {}
        _modbus_live_at = 0.0
    return {
        "ok": verified,
        "driver": "modbus-tcp",
        "remote_id": remote_id,
        "address": address,
        "byte_swap": bool(config_store.get("modbus_process_byte_swap", True)),
        "previous_output_control": current,
        "output_control": updated,
        "readback_output_control": readback,
        "wire_output_control": updated_wire,
        "wire_readback_output_control": readback_wire,
        "verified": verified,
        "error": None if verified else "modbus_write_readback_mismatch",
    }

def _modbus_set_bit(remote_id: str, bit: int, enabled: bool) -> dict:
    return _modbus_update_output_control(remote_id,lambda high,low:(((high | (1 << bit)) if enabled else (high & ~(1 << bit))),low))


def _modbus_set_port4_do(remote_id: str, value: int) -> dict:
    if type(value) is not int or not 0 <= value <= 255:
        return {"ok": False, "error": "value must be an integer 0..255", "remote_id": remote_id}
    result=_modbus_update_output_control(remote_id,lambda high,low:(high,value))
    result.update({"signal":"port4_do","value":value,"value_hex":f"{value:02X}"}); return result


def _modbus_set_port4_do_pin(remote_id: str, pin: int, enabled: bool) -> dict:
    validate_command_payload("port4_do", {"pin": pin, "enabled": enabled})
    bit = port4_do_pin_bit(pin)
    if type(bit) is not int or not 0 <= bit <= 7:
        raise ValueError("invalid Port 4 pin bit")
    mask = 1 << bit
    result = _modbus_update_output_control(remote_id, lambda high, low:
        (high, low | mask if enabled else low & ~mask))
    result.update({"signal": "port4_do", "pin": pin, "enabled": enabled, "bit": bit})
    if "output_control" in result:
        result.update({"previous_value": result["previous_output_control"] & 255,
                       "value": result["output_control"] & 255,
                       "readback_value": result["readback_output_control"] & 255})
    return result


@_command_generation()
def _modbus_set_port4_pdout(remote_id: str, bytes_value: list[int]) -> dict:
    remote_id = _require_modbus_target(remote_id).device_id
    mapping = _command_mapping(remote_id)
    if not mapping or mapping.get("device_kind") != "exa1": return {"ok":False,"error":"modbus_exa1_not_mapped","remote_id":remote_id}
    try:
        values = validate_command_payload("port4_pdout", {"bytes": bytes_value})["bytes"]
    except ValueError:
        return {"ok":False,"error":"invalid_pdout_bytes","remote_id":remote_id}
    padded = values  # Complete 8-register image, validated before I/O; no padding.
    words=[(padded[i] << 8) | padded[i+1] for i in range(0,16,2)]
    with _modbus_endpoint_operation(remote_id): _modbus_write_registers(mapping["output_start"]+1,[_modbus_wire_word(v) for v in words],remote_id=remote_id)
    return {"ok":True,"driver":"modbus-tcp","remote_id":remote_id,"bytes":padded,"bytes_hex":[f"{v:02X}" for v in padded]}


def _modbus_set_air(remote_id: str, enabled: bool, contact_mode: str) -> dict:
    contact_mode=str(contact_mode or "NC").upper(); bit=2 if contact_mode=="NC" else 3
    signal=bool(enabled) if contact_mode=="NC" else not bool(enabled)
    result=_modbus_set_bit(remote_id,bit,signal); result.update({"signal":"air_supply","supply_on":bool(enabled),"signal_on":signal,"contact_mode":contact_mode}); return result
@_command_generation()
def _exa1_service(remote_id, parameter_no, *, write_value=None, value_type="u16"):
    global _modbus_sequence
    remote_id = _require_modbus_target(remote_id).device_id
    channel = _command_mapping(remote_id).get("wireless_channel")
    if not channel: raise ValueError(f"Modbus mapping is unavailable for {remote_id}")
    model = _modbus_exa1_model(remote_id); unit_id = _EXA1_UNIT_IDS.get(model)
    if not unit_id: raise ValueError("modbus_exa1_model must be 20, 30, 40, or 60")
    with _MODBUS_SERVICE_LOCK:
        _modbus_sequence = (_modbus_sequence % 0xFFFF) + 1; sequence = _modbus_sequence
        is_write = write_value is not None
        values = [sequence, 0x0010, 0x0033 if is_write else 0x0032, unit_id, channel, parameter_no, 1, 0]
        if is_write:
            data = bytes([int(write_value) & 0xFF]) if value_type == "u8" else struct.pack(">H", int(write_value) & 0xFFFF)
            values += [len(data)] + [int.from_bytes(data[i:i+2].ljust(2, b"\0"), "big") for i in range(0, len(data), 2)]
        values += [0] * (112 - len(values)); _modbus_write_registers(0x1300, values, remote_id=remote_id)
        deadline = time.monotonic() + max(1.0, float(config_store.get("modbus_timeout_s", 1.5)) * 3)
        completed = 0xB3 if is_write else 0xB2
        while time.monotonic() < deadline:
            response = _modbus_read_registers(0x1400, 112, remote_id=remote_id)
            if len(response) < 3:
                raise ValueError("Truncated BMTAC service response header")
            if response[0] != sequence: time.sleep(.03); continue
            service, status = response[2] & 0xFF, response[2] >> 8
            if status: raise BmtacServiceError(status, parameter_no=parameter_no, remote_id=remote_id)
            if service == completed:
                if is_write: return None
                if len(response) < 9:
                    raise ValueError("Truncated BMTAC service response length")
                size = response[8]
                available = 2 * (len(response) - 9)
                required = 1 if value_type == "u8" else 2
                if size < required or size > available:
                    raise ValueError(f"Truncated BMTAC service payload: declared {size} bytes, available {available}, required {required}")
                raw = b"".join(struct.pack(">H", v) for v in response[9:])[:size]
                return raw[0] if value_type == "u8" else int.from_bytes(raw[:2], "big")
            if service == 0: time.sleep(.03); continue
            time.sleep(.03)
        raise TimeoutError("BMTAC service response timeout")

def _exa1_parameter_limits(name, remote_id="AMS01"):
    number, kind, low, high = _EXA1_PARAMETERS[name]
    model = _modbus_exa1_model(remote_id)
    if name == "standby_threshold_lmin": low, high = {20:(5,525),30:(10,1050),40:(20,2100),60:(40,4200)}[model]
    if name == "standby_hysteresis_lmin": low, high = {20:(0,520),30:(0,1040),40:(0,2080),60:(0,4100)}[model]
    return number, kind, low, high

_exa1_settings_log = logging.getLogger("ams.exa1_settings")


@_command_generation()
def get_modbus_exa1_settings(remote_id="AMS01"):
    t0 = time.monotonic()
    values = {}
    try:
        for name in _EXA1_PARAMETERS:
            no, kind, _, _ = _exa1_parameter_limits(name, remote_id)
            values[name] = _exa1_service(remote_id, no, value_type=kind)
    except Exception as exc:
        _exa1_settings_log.error(
            "READ %s FAILED after %s param(s) in %.2fs: %s: %s",
            remote_id, len(values), time.monotonic() - t0, type(exc).__name__, exc,
        )
        raise
    _exa1_settings_log.info(
        "READ %s ok in %.2fs via EXW1 BMTAC service (reg 0x1300/0x1400): %s",
        remote_id, time.monotonic() - t0, values,
    )
    return {"ok": True, "source": "modbus", "remote_id": remote_id, **values}

@_command_generation()
def write_modbus_exa1_settings(remote_id, changes):
    t0 = time.monotonic()
    written = []
    attempted = False
    try:
        pending = []
        for name, value in changes.items():
            if name not in _EXA1_PARAMETERS or value is None: continue
            if name in _EXA1_READONLY_PARAMETERS:
                _exa1_settings_log.info("WRITE %s skipped read-only diagnostic param %s (value=%s ignored)", remote_id, name, value)
                continue
            no, kind, low, high = _exa1_parameter_limits(name, remote_id); value = int(value)
            if low is not None and not low <= value <= high: raise ValueError(f"{name} must be {low}..{high}")
            pending.append((name, no, kind, value))
        for name, no, kind, value in pending:
            attempted = True
            _exa1_service(remote_id, no, write_value=value, value_type=kind); written.append(name)
        verified = {}
        for name in written:
            no_v, kind_v, _, _ = _exa1_parameter_limits(name, remote_id)
            try:
                verified[name] = _exa1_service(remote_id, no_v, value_type=kind_v)
            except Exception as verify_exc:
                _exa1_settings_log.warning(
                    "WRITE %s readback failed for %s (write itself already succeeded): %s: %s",
                    remote_id, name, type(verify_exc).__name__, verify_exc,
                )
                verified[name] = None
        # Keep applied writes truthful while distinguishing readback confirmation.
        # No replay or rollback follows a missing or mismatched observation.
    except Exception as exc:
        if not attempted:
            raise
        _exa1_settings_log.error(
            "WRITE %s FAILED (requested=%s, written=%s) in %.2fs: %s: %s",
            remote_id, changes, written, time.monotonic() - t0, type(exc).__name__, exc,
        )
        return {"ok": False, "partial": bool(written), "applied": attempted, "recovery_required": attempted,
                "verified": False, "written": written, "remote_id": remote_id,
                "error": str(exc), "outcome": "partial" if written else "failed"}
    _exa1_settings_log.info(
        "WRITE %s ok in %.2fs via EXW1 BMTAC service (reg 0x1300/0x1400): wrote=%s readback=%s",
        remote_id, time.monotonic() - t0, written, {k: verified[k] for k in written},
    )
    missing = [name for name in written if verified.get(name) is None]
    mismatched = [name for name, _, _, value in pending
                  if verified.get(name) is not None and verified[name] != value]
    if not written:
        return {"ok": True, "source": "modbus", "remote_id": remote_id,
                "written": [], "settings": {}, "applied": False, "outcome": "noop"}
    confirmed = not missing and not mismatched
    return {"ok": confirmed, "source": "modbus", "remote_id": remote_id,
            "written": written, "applied": bool(written), "verified": confirmed,
            "outcome": "verified" if confirmed else "verification_failed" if mismatched else "unverified",
            "verification_missing": missing, "verification_mismatched": mismatched,
            "settings": verified}
@_command_generation()
def _read_web_settings_direct() -> dict:
    if not ensure_session(): return {"ok": False, "error": "device_disconnected"}
    csrf = get_csrf(ams_session); idx = 0x0001
    for buf_num, sub, prm in [(0x30, 0xfe, 0x01), (0x31, 0xfe, 0x02), (0x20, 0xfe, 0x04)]:
        value = f"0107" + f"00{idx:04x}{sub:02x}{prm:02x}00"
        ams_session.post(f"{get_ams_host()}/api/adi/config/update.json", data={"inst": buf_num | 0x8000, "value": value, "csrf": csrf}, timeout=3, verify=False)
    time.sleep(1)
    itv = ams_session.get(f"{get_ams_host()}/api/adi/status/data.json", params={"inst": 33072, "count": 2}, timeout=3, verify=False).json()
    pf = ams_session.get(f"{get_ams_host()}/api/adi/status/data.json", params={"inst": 33056, "count": 1}, timeout=3, verify=False).json()
    return {
        "ok": True, "source": "web",
        "operation_kpa": int(itv[0], 16), "standby_kpa": int(itv[1], 16),
        "standby_threshold_lmin": int(pf[0], 16),
        "isolation_enabled": bool(config_store.get("pf3a_isolation_enabled", False)),
        "isolation_delay_s": int(config_store.get("pf3a_isolation_delay_s", 0) or 0),
    }


@_command_generation()
def _write_web_settings_direct(values: dict) -> dict:
    warmup = warmup_hub_requests(False)
    if not warmup.get("ok"): return warmup
    results = {}
    mapping = {
        "operation_kpa": 33072, "standby_kpa": 33073,
        "standby_threshold_lmin": 33056, "standby_hysteresis_lmin": 33057,
        "standby_on_delay_s": 33058, "standby_off_delay_s": 33059,
        "isolation_enabled": 33060, "isolation_delay_s": 33061,
    }
    for key, inst in mapping.items():
        if key not in values or values[key] is None: continue
        value = int(bool(values[key])) if key == "isolation_enabled" else int(values[key])
        results[key] = post_control(inst, f"{value:04x}")
    trigger = post_control(33026, "01")
    ok = bool(results) and all(item.get("ok") for item in results.values()) and trigger.get("ok")
    readback = _read_web_settings_direct() if ok else {}
    return {"ok": ok, "source": "web", "written": list(results), "results": results, "trigger": trigger, "settings": readback}


_hub_instance = None
_hub_signature = None
_runtime_adapters_override = None
_hub_lock = threading.RLock()
_connection_contexts = ConnectionContextManager()


def _device_registry_signature() -> str:
    payload = {"profiles": config_store.get("device_profiles"), "gateways": config_store.get("modbus_gateways"), "legacy_modbus": [config_store.get("modbus_host"), config_store.get("modbus_port"), config_store.get("modbus_unit_id"), config_store.get("modbus_timeout_s"), config_store.get("modbus_exa1_ch1_model"), config_store.get("modbus_exa1_ch2_model")], "legacy_source": config_store.get("data_source"), "opcua_endpoint": config_store.get("opcua_endpoint"), "ams_host": config_store.get("ams_host"), "ams_channel": config_store.get("ams_channel"), "explicit": [config_store.get("device_profiles_explicit"), config_store.get("modbus_gateways_explicit")], "nodes": sorted(set(REMOTE_NODE_MAPS) | set(REMOTE_SIGNAL_NODES))}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _resolve_command_target(profile):
    existing = current_target(profile.device_id)
    if existing is not None:
        return existing
    lease = _configuration_admission.current()
    if lease is None:
        raise ValueError("resolved target requires command admission")
    cfg = lease["config"]
    mapping, connection = {}, {}
    unit = None
    if profile.transport == "modbus":
        topology = load_exw1_topology(cfg, strict=False)
        slot = topology.slot_for_device(profile.device_id)
        gateway = topology.gateway(slot.gateway_id)
        connection = dict(host=gateway.host, port=gateway.port,
                          unit_id=gateway.unit_id, timeout_s=gateway.timeout_s)
        unit = gateway.unit_id
        mapping = topology.channel_map()[profile.device_id]
    elif profile.transport == "opcua":
        mapping = {signal: _signal_node(profile.device_id, signal) for signal in
                   ("standby", "forced_standby", "air_nc", "air_no", "p4_do", "p4_pdout")}
    encoding = {key: cfg.get(key) for key in
                ("modbus_process_byte_swap", "modbus_accumulator_word_swap")}
    return ResolvedCommandTarget(profile.device_id, profile.transport,
        str(profile.endpoint or cfg.get("ams_host") or ""), profile.channel, unit,
        lease["generation"], json.dumps(profile.to_dict()), json.dumps(mapping),
        json.dumps(encoding), json.dumps(cfg), json.dumps(connection))


def _command_mapping(remote_id):
    target = current_target(remote_id)
    return target.mapping if target is not None else MODBUS_AMS_CHANNEL_MAP.get(remote_id, {})


def _runtime_adapter_services() -> dict:
    return {
        "resolve_target": _resolve_command_target,
        "command_gate": _automatic_command_gate,
        "stamp_sample": _stamp_measurement,
        "fetch_modbus_remotes": fetch_modbus_remotes,
        "require_modbus_target": _require_modbus_target,
        "get_modbus_settings": get_modbus_exa1_settings,
        "write_modbus_settings": write_modbus_exa1_settings,
        "set_modbus_mode": set_modbus_ams_mode,
        "set_bit": _modbus_set_bit,
        "set_air": _modbus_set_air,
        "set_port4_do": _modbus_set_port4_do,
        "set_port4_do_pin": _modbus_set_port4_do_pin,
        "port4_do_pin_bit": port4_do_pin_bit,
        "read_byte_node": opcua_read_byte_node,
        "set_port4_pdout": _modbus_set_port4_pdout,
        "exa1_service": _exa1_service,
        "fetch_worker_data": _fetch_worker_data,
        "get_cached_remote": _get_cached_remote,
        "signal_node": _signal_node,
        "write_bool_node": opcua_write_bool_node,
        "write_byte_node": opcua_write_byte_node,
        "write_bytes_node": opcua_write_bytes_node,
        "fetch_web_data": fetch_process_data_web,
        "read_web_settings": _read_web_settings_direct,
        "write_web_settings": _write_web_settings_direct,
        "warmup_web": warmup_hub_requests,
        "post_control": post_control,
        "mode_parameter": MODE_PARAM_INST,
        "control_trigger": CONTROL_TRIGGER_INST,
        "fetch_demo_data": fetch_process_data_demo,
        "operation_scope": _command_generation,
        "get_config": _admitted_config_value,
        "update_config": update_config_values,
    }


def _hub_publication_guard(generation):
    @contextmanager
    def guard(profile, token=None):
        # A short admission lease makes generation verification and publication
        # indivisible with route replacement; it never holds config_lock at I/O.
        with _command_generation():
            if current_config_generation() != generation:
                raise ValueError("obsolete hub configuration generation")
            if profile.transport == "opcua":
                with node_worker_lock:
                    owner, proc = node_worker_owner, node_worker_proc
                    if token is not None and (token[1] is not owner or token[2] is not proc):
                        raise ValueError("obsolete worker ownership")
                    if token is not None and proc is not None and proc.poll() is not None:
                        raise ValueError("owned worker exited before publication")
                    yield (generation, owner, proc)
            else:
                yield (generation,)
    return guard


def _configured_device_registry():
    return DeviceRegistry.from_config(
        _effective_device_registry_config(),
        opcua_device_ids=set(REMOTE_NODE_MAPS) | set(REMOTE_SIGNAL_NODES), strict=False,
    )


@_command_generation()
def get_device_hub() -> DeviceHub:
    global _hub_instance, _hub_signature
    signature = (current_config_generation(), _device_registry_signature())
    with _hub_lock:
        if _hub_instance is None or _hub_signature != signature:
            registry = _configured_device_registry()
            source = str(config_store.get("data_source") or "opcua").lower()
            if source in {"opcua", "modbus"}:
                registry = DeviceRegistry(
                    (profile for profile in registry.all(enabled_only=False) if profile.transport == source),
                    quarantined=registry.quarantined,
                )
            adapters = (_runtime_adapters_override if _runtime_adapters_override is not None
                        else build_runtime_adapters(_runtime_adapter_services(), _connection_contexts))
            _hub_instance = DeviceHub(registry, adapters, publication_guard=_hub_publication_guard(current_config_generation()))
            _hub_signature = signature
        return _hub_instance

class HubProfilesRequest(BaseModel):
    device_profiles: dict


class HubSettingsRequest(BaseModel):
    values: dict


class HubCommandRequest(BaseModel):
    target: str | list[str]
    command: str
    payload: Optional[dict] = None


class HubTopologyRequest(BaseModel):
    modbus_gateways: dict


def _hub_capabilities(profile, hub) -> dict:
    adapter = hub.adapters.get(profile.transport)
    if adapter is None:
        return {}
    capabilities = adapter.capabilities(profile)
    if adapter.routing_error(profile):
        return {key: False for key in capabilities}
    return capabilities


def _resolve_hub_device_id(device_id: str | None, *, allow_default: bool = False) -> str:
    requested = str(device_id or "").upper()
    hub = get_device_hub()
    if not requested and allow_default:
        enabled = hub.registry.all()
        if enabled:
            return enabled[0].device_id
    if not requested:
        raise ValueError("an explicit device target is required")
    return hub.registry.require(requested).device_id


def _legacy_hub_command(device_id: str | None, command: str, payload: dict | None = None) -> dict:
    try:
        with _command_generation():
            payload = validate_command_payload(command, payload or {})
            target = _resolve_hub_device_id(device_id)
            batch = get_device_hub().execute(target, command, payload)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "device_id": device_id, "remote_id": device_id, "command": command, "error": str(exc)}
    result = copy.deepcopy((batch.get("results") or {}).get(target) or {})
    result.update({
        "ok": bool(batch.get("ok")), "partial": bool(batch.get("partial")),
        "remote_id": target, "device_id": target, "command": command,
        "batch": batch,
    })
    if not result.get("ok") and not result.get("error"):
        result["error"] = "hub_command_failed"
    return result

def _device_connection_snapshot(profile, hub) -> dict:
    # _connection_contexts is keyed by (transport, endpoint), not device_id -
    # every Modbus channel on the same EXW1-01 gateway shares one context, so
    # its "connected" flag is meaningless per-device once channels can differ
    # (e.g. one wireless remote paired, another not). The per-device cached
    # health.connected (populated from that device's own last telemetry row,
    # see HubAdapterBase._snapshot) is the reliable per-device signal - prefer
    # it here and only fall back to the shared context when no cache exists
    # yet (e.g. right after startup, before the first read).
    connection = _connection_contexts.snapshot(profile)
    cached_health = hub.cached(profile.device_id).get("health") or {}
    if "connected" in cached_health:
        connection = {**connection, "connected": cached_health["connected"],
                      "last_success_at": cached_health.get("last_success_at"),
                      "last_error": cached_health.get("error"),
                      "consecutive_failures": cached_health.get("consecutive_failures", 0)}
    return connection


@app.get("/api/hub/devices")
def api_hub_devices():
    hub = get_device_hub()
    devices = []
    registry = _configured_device_registry()
    for profile in registry.all(enabled_only=False):
        row = profile.to_dict()
        row["capabilities"] = _hub_capabilities(profile, hub)
        row["health"] = (hub.cached(profile.device_id).get("health") or {})
        row["connection"] = _device_connection_snapshot(profile, hub)
        devices.append(row)
    recovery = {**registry.recovery(), **get_exw1_topology().recovery()}
    recovery["required"] = bool(recovery["quarantined_profiles"] or recovery["quarantined_gateways"])
    return {"ok": True, "devices": devices, "combined_id": "COMBINED", "legacy_source": config_store.get("data_source"),
            "explicit_profiles": bool(config_store.get("device_profiles") or config_store.get("device_profiles_explicit")),
            "recovery": recovery, "raw_device_profiles": copy.deepcopy(config_store.get("device_profiles"))}


@app.get("/api/hub/connections")
def api_hub_connections():
    hub = get_device_hub()
    devices = []
    for profile in _configured_device_registry().all(enabled_only=False):
        devices.append({
            "device_id": profile.device_id,
            "transport": profile.transport,
            "endpoint": _connection_contexts.endpoint_for(profile),
            "enabled": profile.enabled,
            "capabilities": _hub_capabilities(profile, hub),
            "connection": _device_connection_snapshot(profile, hub),
        })
    return {"ok": True, "devices": devices}


@app.get("/api/hub/topology")
def api_hub_topology():
    topology = get_exw1_topology()
    active = _enabled_modbus_profiles()
    return {"ok": True, "topology": topology.to_dict(), "channel_map": {key: copy.deepcopy(row) for key, row in MODBUS_AMS_CHANNEL_MAP.items() if key in active},
            "clients": _modbus_client_pool.snapshot(), "recovery": topology.recovery(),
            "raw_modbus_gateways": copy.deepcopy(config_store.get("modbus_gateways"))}


@app.put("/api/hub/topology")
def api_hub_update_topology(req: HubTopologyRequest):
    global _exw1_topology_cache, _exw1_topology_signature, _hub_instance, _hub_signature, _modbus_live_cache, _modbus_live_at
    try:
        update_config_values(modbus_gateways=copy.deepcopy(req.modbus_gateways), modbus_gateways_explicit=True)
        with _exw1_topology_lock:
            _exw1_topology_cache = None
            _exw1_topology_signature = None
        with _hub_lock:
            _hub_instance = None
            _hub_signature = None
        with _modbus_live_lock:
            _modbus_live_cache = {}
            _modbus_live_at = 0.0
        refreshed = get_exw1_topology()
        return {"ok": True, "topology": refreshed.to_dict(), "devices": refreshed.device_profiles()}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.post("/api/hub/devices")
def api_hub_update_devices(req: HubProfilesRequest):
    global _hub_instance, _hub_signature
    try:
        published = update_config_values(device_profiles=copy.deepcopy(req.device_profiles), device_profiles_explicit=True)
        candidate = DeviceRegistry.from_config(_effective_device_registry_config(published), strict=False)
        with _hub_lock:
            _hub_instance = None
            _hub_signature = None
        if any(profile.transport == "opcua" for profile in candidate.all()):
            # lifespan() only starts the Node OPC UA worker once, at process
            # boot, based on whatever device_profiles existed then. Adding an
            # OPC UA device here later (through the Connections UI) rebuilds
            # the hub registry but never launched that worker process, so the
            # new device would read nothing even though it's now correctly
            # registered. start_node_worker() is already idempotent (it
            # no-ops if a matching worker is already running).
            try:
                start_node_worker()
            except Exception as worker_exc:
                print(f"[NODE_WORKER] start on device-profile save failed: {type(worker_exc).__name__}: {worker_exc}")
        return {"ok": True, "devices": _configured_device_registry().to_dict()}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


_DIO_LINK_LOCK = threading.RLock()
_dio_link_runtime: dict[str, dict] = {}
_DIO_CODE_ACTIONS = {
    0: {"command": "mode", "payload": {"mode": 3}, "action": "ISOLATION", "warning": False},
    1: {"command": "mode", "payload": {"mode": 1}, "action": "SUPPLY", "warning": False},
    2: {"command": "mode", "payload": {"mode": 3}, "action": "SAFE ISOLATION", "warning": True},
    # Code 11 drives the plain Standby request signal (bit0), not Forced Standby
    # (bit1) - forced standby is a separate manual override, not what the
    # wireless remote's standby input line means.
    3: {"command": "standby", "payload": {"enabled": True}, "action": "STANDBY", "warning": False},
}


class DioLinkRequest(BaseModel):
    enabled: bool


def _dio_link_configs() -> dict[str, dict]:
    stored = _admitted_config_value("dio_links", {}) or {}
    result = {}
    for channel in range(1, 11):
        device_id = f"AMS{channel:02d}"
        saved = stored.get(device_id) if isinstance(stored.get(device_id), dict) else {}
        assigned = device_id == "AMS01"
        result[device_id] = {
            "device_id": device_id,
            "assigned": assigned,
            "enabled": bool(saved.get("enabled", False)) if assigned else False,
            "source_id": "IO13" if assigned else None,
            "bit_offset": 0 if assigned else None,
            "bit_width": 2 if assigned else None,
        }
    return result


def _dio_link_statuses(payload: dict | None = None) -> dict[str, dict]:
    devices = {
        str(item.get("device_id") or item.get("remote_id") or "").upper(): item
        for item in ((payload or {}).get("devices") or [])
    }
    source = devices.get("IO13") or {}
    code = _control_code(source, "dio_code", range(4))
    statuses = {}
    for device_id, config in _dio_link_configs().items():
        runtime_state = copy.deepcopy(_dio_link_runtime.get(device_id) or {})
        action = _DIO_CODE_ACTIONS.get(code) if code is not None and config["assigned"] else None
        status = {
            **config,
            "code": code if config["assigned"] else None,
            "code_binary": f"{code:02b}" if code is not None and config["assigned"] else None,
            "action": action["action"] if action else None,
            "warning": bool(action and action["warning"]),
            "source_online": bool(source.get("online")) if config["assigned"] else False,
            "state": "UNASSIGNED" if not config["assigned"] else ("MANUAL" if not config["enabled"] else ("DIO LOST" if not source.get("online") else runtime_state.get("state", "ARMED"))),
            **runtime_state,
        }
        if not config["assigned"] or not config["enabled"]:
            status.update(state="UNASSIGNED" if not config["assigned"] else "MANUAL",
                          error=None, unsupported=False, recovery_required=False)
        elif code is None:
            status.update(state="DIO LOST", error="dio_source_unavailable")
        elif not _control_sample_usable(devices.get(device_id) or {}):
            status.update(state="TARGET OFFLINE", error="dio_target_unavailable")
        elif status["state"] == "APPLIED" and status.get("last_applied_code") != code:
            status.update(state="ARMED", error=None)
        status["applied"] = bool(config["enabled"] and status["state"] == "APPLIED"
                                 and status.get("last_applied_code") == code)
        statuses[device_id] = status
    return statuses


def _control_sample_usable(row: dict, field=None) -> bool:
    if (not row or row.get("error") or not row.get("online", row.get("device_connected", False))
            or not sample_usable(row, field)):
        return False
    measured = sample_time(row.get("timestamp"))
    if measured is None:
        try:
            measured = datetime.fromisoformat(str(row.get("timestamp"))).astimezone()
        except (TypeError, ValueError):
            return False
    return 0 <= time.time() - measured.timestamp() <= 15


def _control_code(row: dict, field: str, allowed):
    value = finite_number(row.get(field))
    return int(value) if _control_sample_usable(row, field) and value is not None and value.is_integer() and value in allowed else None


_automatic_origin = ContextVar("ams_internal_automatic_origin", default=None)
_automatic_payload = ContextVar("ams_internal_automatic_payload", default=None)


def _automatic_command_gate(profile, command):
    # Origin is process-internal context, never a field accepted from clients.
    owner = _automatic_origin.get()
    if owner == "dio":
        payload = _automatic_payload.get() or {}
        rows = {row.get("device_id"): row for row in payload.get("devices", [])}
        if (not _control_sample_usable(rows.get("IO13", {}), "dio_code")
                or not _control_sample_usable(rows.get("AMS01", {}))):
            raise ValueError("automatic_input_stale")
    if (profile.device_id == "AMS01" and _dio_link_configs()["AMS01"]["enabled"]
            and command in {"mode", "standby", "forced_standby", "air_supply"}
            and owner != "dio"):
        raise ValueError("automatic_output_owned: AMS01 DIO control")
    # Called inside the same endpoint lock as the write. Even an uncertain
    # manual attempt supersedes a previous run; an old restore must not win.
    if command in {"mode", "standby", "forced_standby", "air_supply"}:
        key = profile.device_id
        _schedule_execution.epochs[key] = _schedule_execution.epochs.get(key, 0) + 1


def _automatic_admission(origin):
    def decorate(callback):
        @wraps(callback)
        def run(payload, *args, **kwargs):
            with _command_generation():
                if payload.get("config_generation", current_config_generation()) != current_config_generation():
                    return payload
                token = _automatic_origin.set(origin)
                payload_token = _automatic_payload.set(payload)
                try:
                    return callback(payload, *args, **kwargs)
                finally:
                    _automatic_payload.reset(payload_token)
                    _automatic_origin.reset(token)
        return run
    return decorate


def _automatic_input_identity(payload, *rows):
    return (payload.get("config_generation", current_config_generation()),
            tuple((row.get("source_key"), row.get("measurement_generation"),
                   row.get("connection_generation")) for row in rows))


@_automatic_admission("dio")
def _apply_dio_links(payload: dict, *, force_target: str | None = None) -> dict:
    devices = {
        str(item.get("device_id") or item.get("remote_id") or "").upper(): item
        for item in (payload.get("devices") or [])
    }
    source = devices.get("IO13") or {}
    target = devices.get("AMS01") or {}
    config = _dio_link_configs()["AMS01"]
    with _DIO_LINK_LOCK:
        runtime_state = _dio_link_runtime.setdefault("AMS01", {})
        identity = _automatic_input_identity(payload, source, target)
        if runtime_state.get("input_identity") != identity:
            runtime_state.clear()
            runtime_state["input_identity"] = identity
        if config["enabled"]:
            code = _control_code(source, "dio_code", range(4))
            if code is None:
                runtime_state.update({"state": "DIO LOST", "error": "dio_source_unavailable"})
            elif not _control_sample_usable(target):
                runtime_state.update({"state": "TARGET OFFLINE", "error": "dio_target_unavailable"})
            else:
                action = _DIO_CODE_ACTIONS[code]
                now = time.monotonic()
                last_attempt = float(runtime_state.get("last_attempt_monotonic") or 0.0)
                should_apply = force_target == "AMS01" or runtime_state.get("last_applied_code") != code
                if runtime_state.get("last_attempt_failed"):
                    should_apply = force_target == "AMS01" or now - last_attempt >= 3.0
                elif runtime_state.get("error") and now - last_attempt >= 3.0:
                    should_apply = True
                if should_apply:
                    runtime_state["last_attempt_monotonic"] = now
                    # Restore only the existing single-command mapping; do not
                    # infer extra air/contact resets or intermediate writes.
                    try:
                        batch = get_device_hub().execute("AMS01", action["command"], action["payload"])
                        result = (batch.get("results") or {}).get("AMS01") or {}
                        nested = result.get("result")
                        nested = nested if isinstance(nested, dict) else {}
                        ok = bool(batch.get("ok") and result.get("ok")
                                  and batch.get("verified") is not False
                                  and not batch.get("error") and not result.get("error")
                                  and not result.get("skipped") and not result.get("unsupported")
                                  and result.get("verified") is not False
                                  and nested.get("ok") is not False
                                  and nested.get("verified") is not False
                                  and not nested.get("error"))
                        error = (nested.get("error") or result.get("error")
                                 or batch.get("error") or "dio_write_failed")
                    except Exception as exc:
                        ok = False
                        error = f"{type(exc).__name__}: {exc}"
                    runtime_state.update({
                        "state": "APPLIED" if ok else "WRITE FAILED",
                        "last_attempt_failed": not ok,
                        "last_seen_code": code,
                        "last_action": action["action"],
                        "last_applied_code": code if ok else runtime_state.get("last_applied_code"),
                        "last_applied_at": datetime.now().isoformat(timespec="seconds") if ok else runtime_state.get("last_applied_at"),
                        "error": None if ok else error,
                    })
        else:
            runtime_state.update({"state": "MANUAL", "error": None})
    statuses = _dio_link_statuses(payload)
    payload["dio_links"] = statuses
    for item in payload.get("devices") or []:
        device_id = str(item.get("device_id") or item.get("remote_id") or "").upper()
        if device_id in statuses:
            item["dio_link"] = copy.deepcopy(statuses[device_id])
    return payload


_CH1_LAMP_STATE: dict = {}
_ch1_lamp_log = logging.getLogger("ams.ch1_lamp")


def _ch1_lamp_bits(ams01: dict) -> tuple[int, int] | None:
    """Return (bit0, bit1) for IO13's output byte0, or None if unknown.

    Per SMC's AMS fieldbus status byte spec (PFxx-OMA1007 operation manual):
    the LOW NIBBLE of the status byte is the base state - 0 Initialising,
    1 Operation mode, 2 Waiting for standby signal, 3 Standby mode,
    4 Isolation mode - and the HIGH NIBBLE marks who forced it there
    (0x1_=button, 0x2_=PLC/OPC UA/Digital Input). That is why the combined
    codes are 17/19/20/35/36: 0x11=17 (forced Operation, button), 0x13=19
    (forced Standby, button/OPC UA), 0x14=20 (forced Isolation, button/web),
    0x23=35 (forced Standby, PLC/OPC UA - this project's own Modbus writes
    and DIO Link land here), 0x24=36 (forced Isolation, PLC/OPC UA/Digital
    Input - DIO Link's equipment-interlock isolation lands here). Masking
    with 0x0F reads the base state regardless of the force source.

    Requested mapping: Standby -> bit1 ON, Isolation -> both OFF, everything
    else (Operation/Waiting/Initialising) -> bit0 ON.
    """
    code = _control_code(ams01 or {}, "ams_code", AMS_STATUS_MAP)
    if code is None:
        # Unknown inputs never select a new physical output.
        return None
    base_state = code & 0x0F
    if base_state == 3:       # Standby (plain, button, or PLC/OPC UA forced)
        return (0, 1)
    if base_state == 4:       # Isolation (plain, button/web, or PLC forced)
        return (0, 0)
    return (1, 0)             # Operation / Waiting for standby / Initialising


@_automatic_admission("lamp")
def _apply_ch1_status_lamp(payload: dict) -> dict:
    devices = {
        str(item.get("device_id") or item.get("remote_id") or "").upper(): item
        for item in (payload.get("devices") or [])
    }
    io13 = devices.get("IO13")
    ams01 = devices.get("AMS01")
    mapping = _command_mapping("IO13")
    state = _CH1_LAMP_STATE.setdefault("IO13", {})
    identity = _automatic_input_identity(payload, io13 or {}, ams01 or {})
    if state.get("input_identity") != identity:
        state.clear()
        state["input_identity"] = identity
    if not io13 or not ams01 or not mapping or mapping.get("device_kind") != "remote_io":
        return payload
    if not _control_sample_usable(io13):
        if state.get("last_seen") != "io13_offline":
            _ch1_lamp_log.info("CH1 lamp: IO13 offline, write skipped")
            state["last_seen"] = "io13_offline"
        state["error"] = "io13_offline"
        return payload
    code = _control_code(ams01, "ams_code", AMS_STATUS_MAP)
    desired = _ch1_lamp_bits(ams01)
    seen_key = f"online={ams01.get('online')} code={code}"
    if state.get("last_seen") != seen_key:
        _ch1_lamp_log.info(
            "CH1 lamp: AMS01 online=%s ams_code=%s ams_status=%r -> desired_bits(bit0,bit1)=%s",
            ams01.get("online"), code, ams01.get("ams_status"), desired,
        )
        state["last_seen"] = seen_key
    if desired is None:
        return payload  # AMS01 offline or in a state the lamp doesn't map - leave output as-is
    # The dedup check AND the write must happen under the SAME lock. Each
    # connected browser tab polls on its own 1s timer via asyncio.to_thread,
    # so if the check happens before the lock, several threads can all see
    # "not written yet" at the same instant and each perform a redundant
    # read-modify-write to the same register (observed: 5 duplicate writes
    # within ~150ms in the log for one real state change). That floods the
    # wireless Modbus link with pointless extra traffic and can starve the
    # regular AMS01/AMS02/IO13 polls that share this same lock, which is what
    # made the whole dashboard look frozen, not just the lamp bit.
    with _modbus_endpoint_operation("IO13"):
        mapping = _command_mapping("IO13")
        if not _control_sample_usable(io13) or _ch1_lamp_bits(ams01) != desired:
            return payload
        if state.get("last_written_bits") == desired and not state.get("error"):
            return payload
        try:
            address = mapping["output_start"]
            current_wire = int(_modbus_read_registers(address, 1, remote_id="IO13")[0]) & 0xFFFF
            current = _modbus_logical_word(current_wire)
            high, low = (current >> 8) & 0xFF, current & 0xFF
            # byte0 (shown as output_bits[0]/[1] in the UI, same convention as
            # dio_code and _modbus_set_bit's control bits) is the HIGH byte -
            # not the low byte. bit0/bit1 of the low byte are different points.
            bit0, bit1 = desired
            high = (high | 0x01) if bit0 else (high & 0xFE)
            high = (high | 0x02) if bit1 else (high & 0xFD)
            updated_wire = _modbus_wire_word(((high & 0xFF) << 8) | (low & 0xFF))
            _modbus_write_registers(address, [updated_wire], remote_id="IO13")
            readback = _modbus_read_registers(address, 1, remote_id="IO13")[0]
            if readback != updated_wire:
                raise ValueError("lamp_write_readback_mismatch")
            state.update({"last_written_bits": desired, "error": None, "last_written_at": datetime.now().isoformat(timespec="seconds")})
            _ch1_lamp_log.info("CH1 lamp: wrote (bit0,bit1)=%s to IO13 output@%s", desired, address)
        except Exception as exc:
            state["error"] = f"{type(exc).__name__}: {exc}"
            _ch1_lamp_log.error("CH1 lamp: write FAILED: %s", state["error"])
    return payload


# Protected by _history_counter_lock. Only committed accounting values are cached;
# live measurements and their quality never use this cache.
_committed_usage_cache = {}
_committed_usage_cache_generation = None


def _prepare_committed_usage_cache():
    global _committed_usage_cache_generation
    generation = current_config_generation()
    if generation != _committed_usage_cache_generation:
        _committed_usage_cache.clear()
        _committed_usage_cache_generation = generation


def _committed_measurement_totals(cfg):
    _prepare_committed_usage_cache()
    totals = {}
    registry = DeviceRegistry.from_config(_effective_device_registry_config(cfg),
        opcua_device_ids=set(REMOTE_NODE_MAPS) | set(REMOTE_SIGNAL_NODES), strict=False)
    for profile in registry.all():
        source = history_contract.source_key(profile, cfg, REMOTE_NODE_MAPS.get(profile.device_id))
        epoch = str((cfg.get("measurement_epochs") or {}).get(profile.device_id, "initial"))
        identity = (profile.device_id, source, epoch, profile.transport == "simulator")
        if identity not in _committed_usage_cache:
            prior = history_contract.latest(DB_DIR, profile.device_id, source, epoch,
                                            simulated=profile.transport == "simulator")
            _committed_usage_cache[identity] = prior[2] if prior and prior[2] is not None else 0.0
        key = f"{profile.device_id}:{source}:{epoch}"
        total = _committed_usage_cache[identity]
        offset = float((cfg.get("measurement_display_offsets") or {}).get(key, 0))
        totals[profile.device_id] = {"key": key, "committed_total_flow_l": total,
            "dashboard_total_flow_l": max(0.0, total - offset),
            "simulated": profile.transport == "simulator", "measurement_generation": epoch,
            "source_key": source}
    return totals


def _with_committed_usage(payload):
    with config_lock, _history_counter_lock:
        totals = _committed_measurement_totals(config_snapshot())
    for row in payload.get("devices") or []:
        values = totals.get(row.get("device_id"))
        if values:
            row.update({k: v for k, v in values.items() if k != "key"})
    combined = payload.get("combined")
    if combined is not None:
        real = [value for value in totals.values() if not value["simulated"]]
        combined["committed_total_flow_l"] = sum(value["committed_total_flow_l"] for value in real)
        combined["dashboard_total_flow_l"] = sum(value["dashboard_total_flow_l"] for value in real)
        combined["raw_accumulated_flow_l"] = None
        combined["accumulated_flow_l"] = combined["dashboard_total_flow_l"]
    return payload


def _read_hub_with_dio(*, force_target: str | None = None, refresh: bool = False) -> dict:
    """Observation only; automatic evaluation belongs exclusively to the coordinator."""
    if not _acquisition_enabled:
        return {"scope": "hub", "devices": [], "combined": {"device_id": "COMBINED", "online": False},
                "data_source": str(config_store.get("data_source") or "opcua").lower(),
                "acquisition_enabled": False, "dio_links": {}}
    hub = get_device_hub()
    payload = hub.read_all() if refresh else hub.cached()
    payload["data_source"] = str(config_store.get("data_source") or "opcua").lower()
    statuses = _dio_link_statuses(payload)
    payload["dio_links"] = statuses
    for item in payload.get("devices") or []:
        device_id = str(item.get("device_id") or item.get("remote_id") or "").upper()
        if device_id in statuses:
            item["dio_link"] = copy.deepcopy(statuses[device_id])
    return _with_committed_usage(payload)


@app.get("/api/dio-links")
def api_dio_links():
    payload = _read_hub_with_dio()
    return {"ok": True, "links": payload.get("dio_links") or {}}


@app.post("/api/dio-links/{device_id}")
def api_set_dio_link(device_id: str, req: DioLinkRequest):
    device_id = str(device_id or "").upper()
    configs = _dio_link_configs()
    if device_id not in configs:
        return {"ok": False, "error": "invalid_exa1_channel", "device_id": device_id}
    if not configs[device_id]["assigned"]:
        return {"ok": False, "error": "dio_not_assigned_for_demo", "device_id": device_id}
    stored = copy.deepcopy(config_store.get("dio_links") or {})
    stored[device_id] = {"enabled": bool(req.enabled), "source_id": "IO13", "bit_offset": 0, "bit_width": 2}
    update_config_values(dio_links=stored)
    with _DIO_LINK_LOCK:
        _dio_link_runtime[device_id] = {"state": "ARMED" if req.enabled else "MANUAL", "error": None}
    payload = _read_hub_with_dio()
    status = (payload.get("dio_links") or {}).get(device_id) or {
        **configs[device_id], "enabled": bool(req.enabled), "applied": False,
        "state": "ARMED" if req.enabled else "MANUAL", "error": None,
    }
    # This acknowledges the saved enable setting, not a synchronous device write.
    return {"ok": True, "device_id": device_id, "enabled": bool(status.get("enabled")),
            "applied": bool(status.get("applied")), "dio_link": status}

@app.get("/api/hub/snapshot")
def api_hub_snapshot(refresh: bool = False):
    return _read_hub_with_dio(refresh=refresh)


@app.get("/api/hub/devices/{device_id}/settings")
def api_hub_device_settings(device_id: str):
    try:
        result = get_device_hub().read_settings(device_id)
        savings.remember(device_id, result)
        return result
    except Exception as e:
        return {"ok": False, "device_id": device_id.upper(), "error": f"{type(e).__name__}: {e}"}


@app.get("/api/hub/devices/{device_id}/savings")
def api_device_savings(device_id: str):
    profile = get_device_hub().registry.get(device_id)
    if profile is None:
        return {"available": False, "reason": "등록되지 않은 장비"}
    cfg = config_snapshot()
    return savings.today(profile.device_id, get_db_path(datetime.now()), get_db_conn,
                         get_save_interval(), get_kwh_per_m3(), get_price_per_kwh(),
                         source=_measurement_sources(cfg).get(profile.device_id),
                         generation=str((cfg.get("measurement_epochs") or {}).get(profile.device_id, "initial")),
                         site_timezone=cfg.get("site_timezone", "Asia/Seoul"))


@app.put("/api/hub/devices/{device_id}/settings")
def api_hub_write_device_settings(device_id: str, req: HubSettingsRequest):
    try:
        return get_device_hub().write_settings(device_id, req.values)
    except Exception as e:
        return {"ok": False, "device_id": device_id.upper(), "error": f"{type(e).__name__}: {e}"}

def recent_diagnostic_events(remote_id: str, limit: int = 6, lookback_hours: int = 24) -> dict:
    """Recent alert onsets for one device, derived at read time from ams_log.

    There is no discrete alarm-event table yet — ams_log only holds periodic
    samples. This walks the recent samples for one device and emits an event
    each time `diagnostic` changes, keeping only the transitions INTO a
    non-clear state (an alert "starting"), most recent first. Cheap: bounded
    by idx_remote_ts and a short lookback window.
    """
    remote_id = (remote_id or "").strip().upper() or "AMS00"
    lookback_hours = max(1, min(int(lookback_hours or 24), 24 * 31))
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(hours=lookback_hours)
    months = []
    cur = start_dt.replace(day=1)
    while cur <= end_dt:
        months.append(cur)
        cur = cur.replace(month=cur.month + 1) if cur.month < 12 else cur.replace(year=cur.year + 1, month=1)
    start_bound = start_dt.isoformat(timespec="seconds")
    end_bound = end_dt.isoformat(timespec="seconds")
    rows = []
    for m in months:
        db_path = get_db_path(m)
        if not db_path.exists():
            continue
        conn = get_db_conn(m)
        try:
            res = conn.execute(
                """
                SELECT timestamp, diagnostic, ams_status
                FROM ams_log
                WHERE remote_id=? AND timestamp>=? AND timestamp<=?
                ORDER BY timestamp ASC
                """,
                (remote_id, start_bound, end_bound),
            )
            rows.extend(res.fetchall())
        finally:
            conn.close()
    def _is_benign(diag: str) -> bool:
        d = (diag or "").strip()
        if d.upper().startswith("DEMO SEED"):
            return True
        return d.lower() in {"", "no error", "normal operation", "normal", "ok"}

    events = []
    prev_diag = None
    for ts, diag, status in rows:
        diag = diag or "No error"
        if diag != prev_diag:
            events.append({"timestamp": ts, "diagnostic": diag, "ams_status": status})
        prev_diag = diag
    alert_events = [e for e in events if not _is_benign(e["diagnostic"])]
    alert_events.reverse()
    return {
        "remote_id": remote_id,
        "lookback_hours": lookback_hours,
        "count_24h": len(alert_events),
        "events": alert_events[: max(1, limit)],
    }


@app.get("/api/hub/devices/{device_id}/recent-events")
def api_hub_recent_events(device_id: str, limit: int = 6, hours: int = 24):
    try:
        return {"ok": True, **recent_diagnostic_events(device_id, limit=limit, lookback_hours=hours)}
    except Exception as e:
        return {"ok": False, "device_id": device_id.upper(), "error": f"{type(e).__name__}: {e}"}



@app.post("/api/hub/command")
def api_hub_command(req: HubCommandRequest):
    try:
        if str(req.target).upper() == "COMBINED" and req.command in {"port4_do", "port4_pdout", "flow_reset"}:
            return {"ok": False, "error": f"{req.command} requires an explicit physical device target"}
        with _command_generation():
            payload = validate_command_payload(req.command, req.payload or {})
            return get_device_hub().execute(req.target, req.command, payload)
    except Exception as e:
        return {"ok": False, "command": req.command, "error": f"{type(e).__name__}: {e}"}

@app.get("/api/device/settings")
def read_device_settings(remote_id: str | None = None):
    device_id = remote_id
    try:
        device_id = _resolve_hub_device_id(remote_id, allow_default=True)
        values = get_device_hub().read_settings(device_id)
        result = copy.deepcopy(values)
        result.update({
            "remote_id": device_id, "device_id": device_id,
            "itv_operation_kpa": values.get("operation_kpa", values.get("itv_operation_kpa")),
            "itv_standby_kpa": values.get("standby_kpa", values.get("itv_standby_kpa")),
        })
        return result
    except Exception as e:
        return {"ok": False, "remote_id": device_id, "error": f"{type(e).__name__}: {e}"}


@app.get("/api/device/pf3a-settings")
def read_pf3a_settings(remote_id: str | None = None):
    device_id = remote_id
    try:
        device_id = _resolve_hub_device_id(remote_id, allow_default=True)
        values = get_device_hub().read_settings(device_id)
        return {**copy.deepcopy(values), "remote_id": device_id, "device_id": device_id}
    except Exception as e:
        return {"ok": False, "remote_id": device_id, "error": f"{type(e).__name__}: {e}"}

# ?? ?덉뒪?좊━ API ??????????????????????????????????????????
@app.post("/api/history/new-measurement")
def api_new_measurement(device_id: str):
    from app.device_hub import canonical_device_id
    device_id = canonical_device_id(device_id)
    def changes(cfg):
        sources = _measurement_sources(cfg)
        if device_id not in sources:
            raise ValueError("explicit enabled measurement device required")
        epochs = dict(cfg.get("measurement_epochs") or {})
        epochs[device_id] = uuid.uuid4().hex
        stored_sources = dict(cfg.get("measurement_sources") or {})
        stored_sources[device_id] = sources[device_id]
        return {"measurement_epochs": epochs, "measurement_sources": stored_sources}
    result = update_config_values(_build_changes=changes)
    return {"ok": True, "device_id": device_id,
            "measurement_generation": result["measurement_epochs"][device_id]}


@app.get("/api/history")
def api_history(start: str, end: str, unit: str = "hour", field: str = "flow", remote_id: str = "ALL",
                source_key: Optional[str] = None, measurement_generation: Optional[str] = None,
                include_simulated: Optional[bool] = None):
    try:
        data = query_history(start, end, unit, field, remote_id, source=source_key,
                             generation=measurement_generation, include_simulated=include_simulated)
        total_count = sum(int(r.get("count") or 0) for r in data)
        demo_count = sum(int(r.get("demo_count") or 0) for r in data)
        if total_count <= 0:
            source = "empty"
        elif demo_count >= total_count:
            source = "demo"
        elif demo_count > 0:
            source = "mixed"
        else:
            source = "live"
        return {
            "start": start,
            "end": end,
            "unit": unit,
            "field": field,
            "remote_id": remote_id,
            "source": source,
            "is_demo": source == "demo",
            "demo_count": demo_count,
            "row_count": total_count,
            "data": data,
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/history/csv")
def api_history_csv(start: str, end: str, unit: Optional[str] = None, field: Optional[str] = None,
                    mode: str = "avg", remote_id: str = "ALL", source_key: Optional[str] = None,
                    measurement_generation: Optional[str] = None, include_simulated: Optional[bool] = None):
    try:
        filters = dict(source=source_key, generation=measurement_generation, include_simulated=include_simulated)
        if unit and field:
            output = export_history_query_csv(start, end, unit, field, mode, remote_id, **filters)
            content = iter([output.getvalue()])
            filename = f"ams_query_{remote_id}_{field}_{unit}_{start}_{end}.csv"
        else:
            content = iter_export_csv(start, end, remote_id, **filters)
            filename = f"ams_data_{remote_id}_{start}_{end}.csv"
        return StreamingResponse(content,media_type="text/csv",
                                 headers={"Content-Disposition":f"attachment; filename={filename}"})
    except Exception as e: return {"error":str(e)}

# ?? ?쒖뼱 API ?????????????????????????????????????????????
class AMSModeRequest(BaseModel):    mode: StrictInt; remote_id: Optional[str] = None
class SaveIntervalRequest(BaseModel): interval_s: int
class StandbySignalRequest(BaseModel):
    enabled: StrictBool
    remote_id: Optional[str] = None
class ForcedStandbyRequest(BaseModel):
    enabled: StrictBool
    remote_id: Optional[str] = None
class AirSupplyRequest(BaseModel):
    enabled: StrictBool
    contact_mode: Optional[str] = None
    remote_id: Optional[str] = None
class Port4PdoutRequest(BaseModel):
    remote_id: Optional[str] = None
    bytes: list[StrictInt]
class Port4DoRequest(BaseModel):
    remote_id: Optional[str] = None
    value: Optional[StrictInt] = None
    pin: Optional[StrictInt] = None
    enabled: Optional[StrictBool] = None
class FlowResetRequest(BaseModel):
    remote_id: Optional[str] = None
class ITVPressureRequest(BaseModel):
    operation_kpa: Optional[int]=None; standby_kpa: Optional[int]=None; soft_start_time_s: Optional[int]=None; remote_id: Optional[str]=None
class PF3AParamRequest(BaseModel):
    standby_threshold_lmin: Optional[int]=None; standby_hysteresis_lmin: Optional[int]=None
    standby_on_delay_s: Optional[int]=None; standby_off_delay_s: Optional[int]=None
    isolation_enabled: Optional[bool]=None; isolation_delay_s: Optional[int]=None; remote_id: Optional[str]=None

def set_source_ams_mode(mode: int, remote_id: str | None = None) -> dict:
    return _legacy_hub_command(remote_id, "mode", {"mode": mode})


@_command_generation()
def set_modbus_ams_mode(mode: int, remote_id: str | None = None, contact_mode="NC") -> dict:
    if type(mode) is not int or mode not in (0, 1, 2, 3) or contact_mode not in ("NC", "NO"):
        return {"ok": False, "error": "invalid mode or contact_mode"}
    remote_id = str(remote_id or "").upper()
    try:
        _require_modbus_target(remote_id)
    except ValueError:
        return {"ok": False, "error": "modbus_remote_not_mapped", "remote_id": remote_id}
    steps = [lambda: _modbus_set_bit(remote_id, 0, False),
             lambda: _modbus_set_bit(remote_id, 1, mode == 2)]
    if mode != 2:
        steps.append(lambda: _modbus_set_air(remote_id, mode != 3, contact_mode))
    return {**execute_output_sequence(steps), "driver": "modbus-tcp",
            "remote_id": remote_id, "mode": mode}

@app.post("/api/control/prepare")
def ctrl_prepare():
    hub = get_device_hub()
    return {"ok": True, "cached": True, "driver": "device-hub", "devices": [profile.device_id for profile in hub.registry.all()]}


@app.post("/api/control/ams-mode")
def ctrl_ams_mode(req: AMSModeRequest):
    if req.mode not in [0, 1, 2, 3]:
        return {"ok": False, "error": "mode must be 0~3"}
    return _legacy_hub_command(req.remote_id, "mode", {"mode": req.mode})


@app.post("/api/control/standby-signal")
def ctrl_standby_signal(req: StandbySignalRequest):
    return _legacy_hub_command(req.remote_id, "standby", {"enabled": req.enabled})


@app.post("/api/control/forced-standby")
def ctrl_forced_standby(req: ForcedStandbyRequest):
    return _legacy_hub_command(req.remote_id, "forced_standby", {"enabled": req.enabled})


@app.post("/api/control/air-supply")
def ctrl_air_supply(req: AirSupplyRequest):
    payload = {"enabled": req.enabled}
    if "contact_mode" in req.model_fields_set:
        payload["contact_mode"] = req.contact_mode
    return _legacy_hub_command(req.remote_id, "air_supply", payload)


@app.post("/api/control/port4-pdout")
def ctrl_port4_pdout(req: Port4PdoutRequest):
    return _legacy_hub_command(req.remote_id, "port4_pdout", {"bytes": req.bytes})


@app.post("/api/control/port4-do")
def ctrl_port4_do(req: Port4DoRequest):
    payload = {key: getattr(req, key) for key in req.model_fields_set if key != "remote_id"}
    return _legacy_hub_command(req.remote_id, "port4_do", payload)


@app.post("/api/control/flow-reset")
def ctrl_flow_reset(req: FlowResetRequest):
    return _legacy_hub_command(req.remote_id, "flow_reset", {})

@app.post("/api/control/data-total-reset")
def ctrl_data_total_reset(device_id: str):
    from app.device_hub import canonical_device_id
    device_id = canonical_device_id(device_id)
    def changes(cfg):
        with _history_counter_lock:
            total = _committed_measurement_totals(cfg).get(device_id)
            if total is None:
                raise ValueError("explicit enabled measurement device required")
            offsets = dict(cfg.get("measurement_display_offsets") or {})
            offsets[total["key"]] = total["committed_total_flow_l"]
            return {"measurement_display_offsets": offsets}
    update_config_values(_build_changes=changes)
    return {"ok": True, "device_id": device_id, "dashboard_total_flow_l": 0.0,
            "basis": "display_offset_only"}

@app.post("/api/control/itv-pressure")
def ctrl_itv_pressure(req: ITVPressureRequest):
    try:
        device_id = _resolve_hub_device_id(req.remote_id)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "device_id": req.remote_id, "error": str(exc)}
    values = {
        "operation_kpa": req.operation_kpa,
        "standby_kpa": req.standby_kpa,
        "soft_start_time_s": req.soft_start_time_s,
    }
    try:
        return get_device_hub().write_settings(device_id, {key: value for key, value in values.items() if value is not None})
    except Exception as e:
        return {"ok": False, "device_id": device_id, "error": f"{type(e).__name__}: {e}"}


@app.post("/api/control/pf3a-param")
def ctrl_pf3a_param(req: PF3AParamRequest):
    try:
        device_id = _resolve_hub_device_id(req.remote_id)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "device_id": req.remote_id, "error": str(exc)}
    values = {
        "standby_threshold_lmin": req.standby_threshold_lmin,
        "standby_hysteresis_lmin": req.standby_hysteresis_lmin,
        "standby_on_delay_s": req.standby_on_delay_s,
        "standby_off_delay_s": req.standby_off_delay_s,
        "isolation_enabled": req.isolation_enabled,
        "isolation_delay_s": req.isolation_delay_s,
    }
    try:
        return get_device_hub().write_settings(device_id, {key: value for key, value in values.items() if value is not None})
    except Exception as e:
        return {"ok": False, "device_id": device_id, "error": f"{type(e).__name__}: {e}"}

@app.post("/api/control/save-interval")
def ctrl_save_interval(req: SaveIntervalRequest):
    if req.interval_s not in [1,2,5,10,30]: return {"ok":False,"error":"1,2,5,10,30 以??좏깮"}
    update_config_values(data_save_interval_s=req.interval_s)
    return {"ok":True,"interval_s":req.interval_s}

# ?? ?ㅼ?以?API ????????????????????????????????????????????
class ScheduleItem(BaseModel):
    name: str; start_time: str; end_time: str
    mode: int; repeat: str; days: list; active: bool = False
    remote_id: str = "AMS00"

@app.get("/api/schedules")
def get_schedules(): return schedules_store

@app.post("/api/schedules")
def add_schedule(item: ScheduleItem):
    with schedule_lock:
        if len(schedules_store) >= 10:
            return {"ok":False,"error":"理쒕? 10媛쒓퉴吏 ?깅줉 媛?ν빀?덈떎"}
        try:
            new_sch = item.model_dump() if hasattr(item, "model_dump") else item.dict()
            new_sch["id"]     = str(uuid.uuid4())[:8]
            new_sch["status"] = STATUS_WAITING
            schedules_store.append(new_sch)
            save_schedules()
            return {"ok":True,"schedule":new_sch,"schedule_file":str(SCHEDULE_FILE)}
        except Exception as e:
            if "new_sch" in locals() and new_sch in schedules_store:
                schedules_store.remove(new_sch)
            return {"ok":False,"error":f"schedule_save_failed: {e}"}

def _schedule_edit_transaction(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with schedule_lock:
            previous = copy.deepcopy(schedules_store)
            previous_runs = copy.deepcopy(_schedule_execution.runs)
            try:
                return function(*args, **kwargs)
            except Exception as exc:
                schedules_store[:] = previous
                _schedule_execution.runs = previous_runs
                return {"ok": False, "error": f"schedule_save_failed: {exc}"}
    return wrapped


@app.patch("/api/schedules/{sch_id}")
@_schedule_edit_transaction
def update_schedule(sch_id: str, item: ScheduleItem):
    with schedule_lock:
        for sch in schedules_store:
            if sch["id"] == sch_id:
                if _schedule_execution.live(sch_id):
                    return {"ok":False,"error":"stop_running_schedule_before_edit"}
                updated = item.model_dump() if hasattr(item, "model_dump") else item.dict()
                sch.update(updated)
                sch.pop("run", None)
                sch.pop("last_occurrence", None)
                _schedule_execution.runs.pop(sch_id, None)
                sch["id"] = sch_id
                if schedule_status_key(sch.get("status")) in ("done", "fail"):
                    sch["status"] = STATUS_WAITING
                else:
                    sch["status"] = sch.get("status") or STATUS_WAITING
                save_schedules()
                return {"ok":True,"schedule":sch}
    return {"ok":False,"error":"schedule_not_found"}

@app.delete("/api/schedules/{sch_id}")
@_schedule_edit_transaction
def delete_schedule(sch_id: str):
    global schedules_store
    with schedule_lock:
        if _schedule_execution.live(sch_id):
            return {"ok": False, "error": "stop_running_schedule_before_delete"}
        before          = len(schedules_store)
        schedules_store = [s for s in schedules_store if s["id"] != sch_id]
        save_schedules()
    return {"ok":len(schedules_store) < before}

@app.patch("/api/schedules/{sch_id}/toggle")
@_schedule_edit_transaction
def toggle_schedule(sch_id: str):
    with schedule_lock:
        for sch in schedules_store:
            if sch["id"] == sch_id:
                if _schedule_execution.live(sch_id):
                    return {"ok": False, "error": "stop_running_schedule_before_toggle"}
                sch["active"] = not sch.get("active", True)
                if sch["active"]:
                    sch.pop("run", None)
                    sch.pop("last_occurrence", None)
                    _schedule_execution.runs.pop(sch_id, None)
                    sch["status"] = STATUS_WAITING
                if sch["active"] and schedule_status_key(sch.get("status")) in ["done","fail"]:
                    sch["status"] = STATUS_WAITING
                save_schedules()
                return {"ok":True,"active":sch["active"]}
    return {"ok":False,"error":"not found"}

def _schedule_target(remote_id: str | None) -> str:
    requested = str(remote_id or "").upper()
    if requested in {"ALL", "ALL DEVICES", "COMBINED"}:
        return "COMBINED"
    return _resolve_hub_device_id(requested)


def _hub_current_mode(target: str) -> int | None:
    if target == "COMBINED":
        return None
    snapshot = get_device_hub().cached(target)
    if not snapshot:
        snapshot = get_device_hub().read_device(target)
    code = _control_code(snapshot or {}, "ams_code", AMS_STATUS_MAP)
    # Only observed, explicitly restorable states; no default Operation.
    return {1: 1, 17: 1, 3: 2, 19: 2, 35: 2, 4: 3, 20: 3, 36: 3}.get(code)


def _schedule_input_error(target: str, return_mode=None) -> dict | None:
    if _hub_current_mode(target) is None:
        return {"ok": False, "error": "schedule_input_unavailable", "recovery_required": True}
    if return_mode is not None and (isinstance(return_mode, bool) or return_mode not in (1, 2, 3)):
        return {"ok": False, "error": "schedule_restore_unavailable", "recovery_required": True}
    return None


def _restore_schedule_mode(target: str, mode, return_mode) -> dict:
    error = _schedule_input_error(target)
    if error:
        return error
    if mode == SCHEDULE_STANDBY_SIGNAL_MODE:
        return _run_schedule_hub_command(target, mode, standby_enabled=False)
    if isinstance(return_mode, bool) or return_mode not in (1, 2, 3):
        return {"ok": False, "error": "schedule_restore_unavailable", "recovery_required": True}
    return _run_schedule_hub_command(target, return_mode)


def _run_schedule_hub_command(target: str, mode: int, *, standby_enabled: bool = True) -> dict:
    if mode == SCHEDULE_STANDBY_SIGNAL_MODE:
        return get_device_hub().execute(target, "standby", {"enabled": standby_enabled})
    return get_device_hub().execute(target, "mode", {"mode": int(mode)})


def _persist_schedule_runs():
    _schedule_execution.publish(schedules_store)
    try:
        save_schedules()
    except Exception:
        for run in _schedule_execution.runs.values():
            if run.get("state") in SCHEDULE_LIVE:
                run.update(state="RECOVERY_REQUIRED", recovery_required=True,
                           error="schedule_journal_persistence_failed")
        _schedule_execution.publish(schedules_store)
        raise


def _schedule_device_action(run, entry, persist=None, *, restoring=False):
    device_id = entry["device_id"]
    with _command_generation():
        hub = get_device_hub()
        profile = hub.registry.require(device_id)
        with _connection_contexts.context_for(profile).lock:
            target = _resolve_command_target(profile)
            snapshot = hub.cached(device_id) or hub.read_device(device_id)
            source = (snapshot or {}).get("source_key")
            observed = _hub_current_mode(device_id)
            generation = current_config_generation()
            if restoring:
                if entry.get("ownership_epoch") != _schedule_execution.epochs.get(device_id, 0):
                    return {"ok": False, "superseded": True, "error": "schedule_ownership_superseded"}
                if (entry.get("source_key") != source or any(entry.get(key) != getattr(target, key)
                        for key in ("transport", "endpoint", "channel", "unit_id", "mapping", "encoding"))):
                    return {"ok": False, "recovery_required": True, "error": "schedule_target_changed"}
                if observed is None:
                    return {"ok": False, "recovery_required": True, "error": "schedule_input_unavailable"}
                if run["mode"] == SCHEDULE_STANDBY_SIGNAL_MODE:
                    if type(entry.get("return_standby")) is not bool:
                        return {"ok": False, "recovery_required": True, "error": "schedule_restore_unavailable"}
                    result = _run_schedule_hub_command(device_id, run["mode"], standby_enabled=entry["return_standby"])
                else:
                    result = _run_schedule_hub_command(device_id, entry["return_mode"])
                return result.get("results", {}).get(device_id, result)
            if observed is None or not source:
                entry["state"] = "FAILED"
                return {"ok": False, "error": "schedule_input_unavailable"}
            # Restore standby only when the previous output boolean was observed.
            if run["mode"] not in (1, 2, 3) and not (run["mode"] == SCHEDULE_STANDBY_SIGNAL_MODE and type(snapshot.get("standby_signal")) is bool):
                entry["state"] = "FAILED"
                return {"ok": False, "error": "schedule_restore_unavailable"}
            entry.update(config_generation=generation, source_key=source,
                         return_mode=observed, return_standby=snapshot.get("standby_signal"), transport=target.transport,
                         endpoint=target.endpoint, channel=target.channel, unit_id=target.unit_id,
                         mapping=target.mapping, encoding=target.encoding,
                         state="APPLYING", owned=False)
            persist()  # Durable intent BEFORE a possibly partially applied write.
            result = _run_schedule_hub_command(device_id, run["mode"])
            detail = result.get("results", {}).get(device_id, result)
            success = bool(detail.get("ok")) and not detail.get("skipped")
            entry.update(owned=success, state="APPLIED" if success else "FAILED",
                         ownership_epoch=_schedule_execution.epochs.get(device_id, 0))
            # A multi-output command may report failure after one write applied.
            if not success and (detail.get("partial") or detail.get("applied")):
                entry.update(owned=True, state="RECOVERY_REQUIRED")
            return detail


@app.post("/api/schedules/{sch_id}/execute")
def execute_schedule(sch_id: str):
    with schedule_lock:
        sch = next((s for s in schedules_store if s.get("id") == sch_id), None)
        if not sch:
            return {"ok": False, "error": "schedule_not_found"}
        try:
            with _command_generation():
                target = _schedule_target(sch.get("remote_id"))
                targets = [p.device_id for p in get_device_hub().registry.targets(target)]
                result = _schedule_execution.start(sch, datetime.now(), targets,
                    _schedule_device_action, _persist_schedule_runs)
        except Exception as exc:
            return {"ok": False, "outcome": "failed", "error": str(exc), "recovery_required": True}
        sch["status"] = result.get("run", {}).get("state", STATUS_FAIL)
        sch["last_result"] = result.get("result")
        _persist_schedule_runs()
        return result


class ScheduleRecoveryConfirmation(BaseModel):
    confirmed: StrictBool = False


@app.post("/api/schedules/{sch_id}/acknowledge-recovery")
def acknowledge_schedule_recovery(sch_id: str, req: ScheduleRecoveryConfirmation):
    if not req.confirmed:
        return {"ok": False, "error": "manual_device_state_confirmation_required"}
    with schedule_lock:
        run = _schedule_execution.runs.get(sch_id)
        sch = next((s for s in schedules_store if s.get("id") == sch_id), None)
        if not sch or not run or run.get("state") != "RECOVERY_REQUIRED":
            return {"ok": False, "error": "schedule_not_in_recovery"}
        previous_run, previous_sch = copy.deepcopy(run), copy.deepcopy(sch)
        for entry in run.get("targets", []):
            entry.update(owned=False, state="MANUALLY_RESOLVED")
        run.update(state="ACKNOWLEDGED", recovery_required=False, acknowledged_at=datetime.now().isoformat())
        sch.update(active=False, status="ACKNOWLEDGED", run=copy.deepcopy(run))
        try:
            save_schedules()
        except Exception as exc:
            run.clear(); run.update(previous_run)
            sch.clear(); sch.update(previous_sch)
            return {"ok": False, "error": f"schedule_save_failed: {exc}"}
        return {"ok": True, "output_changed": False, "state": "ACKNOWLEDGED"}


@app.post("/api/schedules/{sch_id}/stop")
def stop_schedule(sch_id: str):
    with schedule_lock:
        sch = next((s for s in schedules_store if s.get("id") == sch_id), None)
        if not sch:
            return {"ok": False, "error": "schedule_not_found"}
        result = _schedule_execution.stop(sch_id,
            lambda run, entry: _schedule_device_action(run, entry, restoring=True), _persist_schedule_runs)
        sch["last_restore_result"] = result.get("result")
        sch["status"] = result.get("run", {}).get("state", sch.get("status"))
        if sch["status"] == "COMPLETED" and sch.get("repeat") != "daily":
            sch["active"] = False
        _persist_schedule_runs()
        return result

# ?? OPC UA 吏꾨떒 API ???????????????????????????????????????
def _worker_read_node_raw(node_id: str) -> dict:
    """Owned worker /read for a single node. Diagnostics only."""
    try:
        data, _resp = _owned_worker_request(
            "POST", "/read", json_body={"nodeId": node_id}, timeout=10, generation=config_generation_snapshot()
        )
        data["driver"] = "node-opcua-worker"
        return data
    except Exception as e:
        return {"ok": False, "node_id": node_id, "error": f"worker_unreachable: {e}", "driver": "node-opcua-worker"}


@app.get("/api/opcua/read")
async def api_opcua_read(node_id: str):
    """?⑥씪 ?몃뱶 利됱떆 ?쎄린. ?node_id=ns=3;i=16847360"""
    if not node_id:
        return {"ok": False, "error": "node_id required"}
    return await asyncio.to_thread(_worker_read_node_raw, node_id)


class OpcuaWriteTestRequest(BaseModel):
    node_id: str
    value: bool


@app.post("/api/opcua/write-test")
async def api_opcua_write_test(req: OpcuaWriteTestRequest):
    """
    write ??利됱떆쨌0.5珥댟?.5珥?readback 鍮꾧탳.
    - write ?먯껜 ?ㅽ뙣?몄?
    - write ?깃났 ??媛믪씠 ??諛붾뚮뒗吏 (read-only ?곹깭 ?몃뱶)
    - 媛믪? 諛붾뚯?留?怨?蹂듦??섎뒗吏 (?λ퉬媛 ??뼱?)
    瑜??먮떒?섍린 ?꾪븳 吏꾨떒??
    """
    node_id = req.node_id
    value   = req.value

    # write
    wt0 = time.time()
    write_result = await asyncio.to_thread(opcua_write_bool, node_id, value)
    write_ms = round((time.time() - wt0) * 1000, 1)
    write_result["elapsed_ms"] = write_ms

    # readback ??踰?
    async def read_after(delay_s: float) -> dict:
        if delay_s > 0:
            await asyncio.sleep(delay_s)
        r = await asyncio.to_thread(_worker_read_node_raw, node_id)
        r["delay_s"] = delay_s
        return r

    rb_immediate = await read_after(0)
    rb_500ms     = await read_after(0.5)
    rb_1500ms    = await read_after(1.0)   # 珥?1.5珥?(?대? 0.5 吏??

    # 媛꾨떒 遺꾩꽍
    wrote_val = bool(value)
    def val_matches(rb: dict) -> Optional[bool]:
        if not rb.get("ok"):
            return None
        try:
            return bool(rb["value"]) == wrote_val
        except Exception:
            return None

    m0 = val_matches(rb_immediate)
    m1 = val_matches(rb_500ms)
    m2 = val_matches(rb_1500ms)

    if not write_result.get("ok"):
        analysis = "WRITE_FAILED: OPC UA server rejected the write, or the node is read-only / not writable."
    elif m0 is False and m1 is False and m2 is False:
        analysis = "WRITE_ACCEPTED_VALUE_UNCHANGED: write returned OK but readback did not change; this may be a status/readback node."
    elif m0 is True and m1 is False:
        analysis = "VALUE_REVERTED_FAST: value changed immediately but reverted within 0.5 seconds; device controller may overwrite it."
    elif m0 is True and m1 is True and m2 is False:
        analysis = "VALUE_REVERTED_SLOW: value held for 0.5 seconds but reverted by 1.5 seconds; device logic may be taking control."
    elif m0 is True and m1 is True and m2 is True:
        analysis = "WRITE_OK_VALUE_HELD: write succeeded and value was still held after 1.5 seconds; this looks like a command node."
    else:
        analysis = f"INCONCLUSIVE: immediate={m0}, 500ms={m1}, 1500ms={m2}"

    return {
        "node_id":        node_id,
        "write_value":    wrote_val,
        "write_result":   write_result,
        "readback": {
            "immediate": rb_immediate,
            "after_500ms":  rb_500ms,
            "after_1500ms": rb_1500ms,
        },
        "analysis": analysis,
    }


# ?? ?ㅼ?以??쒓컙 泥댄겕 (30珥?二쇨린) ?????????????????????????
def check_schedules():
    if not _acquisition_enabled or _runtime_recovery_error or _config_journal().path.exists():
        return
    now = datetime.now()
    with schedule_lock:
        # Restoration is driven by instances, never the enabled definition.
        for sch in list(schedules_store):
            run = _schedule_execution.runs.get(sch["id"], {})
            if run.get("state") in {"RUNNING", "PARTIAL"} and now >= datetime.fromisoformat(run["ends_at"]):
                stop_schedule(sch["id"])
        for sch in list(schedules_store):
            if not sch.get("active") or _schedule_execution.live(sch["id"]):
                continue
            try:
                start, end = schedule_window(sch, now)
            except (ValueError, KeyError, TypeError):
                continue
            occurrence = start.isoformat()
            if not start <= now < end or sch.get("last_occurrence") == occurrence:
                continue
            if sch.get("repeat") == "daily" and sch.get("days"):
                if ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][start.weekday()] not in sch["days"]:
                    continue
            previous = copy.deepcopy(sch)
            sch["last_occurrence"] = occurrence
            if sch.get("repeat") != "daily":
                sch["active"] = False
            try:
                save_schedules()
            except Exception:
                sch.clear()
                sch.update(previous)
                raise
            execute_schedule(sch["id"])


def _hub_live_payload() -> dict:
    payload = _read_hub_with_dio()
    payload["acquisition"] = acquisition_status()
    payload["save_interval_s"] = get_save_interval()
    payload["energy_config"] = {
        "kwh_per_m3": get_kwh_per_m3(),
        "price_per_kwh": get_price_per_kwh(),
        "co2_per_kwh": get_co2_per_kwh(),
        "tree_per_co2": get_tree_per_co2(),
    }
    return payload


async def _stream_hub(websocket: WebSocket, *, legacy: bool = False):
    if not await authenticate_websocket(websocket):
        return
    if _runtime_recovery_error or _config_journal().path.exists():
        await websocket.send_json(configuration_recovery_status())
        await websocket.close(code=1013)
        return
    try:
        while True:
            payload = await asyncio.to_thread(_hub_live_payload)
            data = payload
            if legacy:
                devices = payload.get("devices") or []
                primary = next((item for item in devices if item.get("online")), devices[0] if devices else {})
                data = dict(primary)
                data.update({
                    "hub": payload,
                    "devices": devices,
                    "combined": payload.get("combined"),
                    "save_interval_s": payload["save_interval_s"],
                    "energy_config": payload["energy_config"],
                })
            await websocket.send_json(data)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as exc:
        print(f"WebSocket error: {exc}")


@app.websocket("/ws/hub")
async def ws_hub(websocket: WebSocket):
    await _stream_hub(websocket)


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await _stream_hub(websocket, legacy=True)

from app.diagnostics import install as install_diagnostics
install_diagnostics(app, get_device_hub, api_hub_connections, lambda: BASE_DIR)

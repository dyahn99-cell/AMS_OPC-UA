from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests
import urllib3
import asyncio
import time
import sqlite3
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
from pathlib import Path
from urllib.parse import urlparse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

async def _periodic_save_loop():
    while True:
        await asyncio.sleep(get_save_interval())
        try:
            data = await asyncio.to_thread(fetch_process_data)
            if not data.get("error"):
                await asyncio.to_thread(save_to_db, data)
        except Exception as e:
            print(f"[SAVE] error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_node_worker()
    save_task = asyncio.create_task(_periodic_save_loop())
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_schedules, "interval", seconds=30, id="check_schedules")
    scheduler.start()
    yield
    save_task.cancel()
    stop_node_worker()
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
BASE_DIR = APP_DIR
ASSETS_DIR = APP_DIR / "assets"
if not ASSETS_DIR.exists():
    ASSETS_DIR = BUNDLE_DIR / "assets"

app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

@app.get("/", response_class=HTMLResponse)
def serve_root():
    return serve_dashboard()

@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
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

# ?? Config ????????????????????????????????????????????????
CONFIG_FILE = BASE_DIR / "config.json"
NODES_FILE = BASE_DIR / "nodes.json"
DB_DIR      = BASE_DIR / "db"
DB_DIR.mkdir(exist_ok=True)
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
IODD_DIR = BASE_DIR / "iodd_library"
IODD_DIR.mkdir(exist_ok=True)
IODD_INDEX_FILE = IODD_DIR / "index.json"
if not CONFIG_FILE.exists():
    bundled_config = BUNDLE_DIR / "config.json"
    if bundled_config.exists():
        shutil.copy2(bundled_config, CONFIG_FILE)
if not NODES_FILE.exists():
    bundled_nodes = BUNDLE_DIR / "nodes.json"
    if bundled_nodes.exists():
        shutil.copy2(bundled_nodes, NODES_FILE)

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
    "iodd_assignments":              {},
}

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                saved = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                saved.setdefault(k, v)
            return saved
        except Exception as e:
            print(f"[CONFIG] load failed: {type(e).__name__}: {e}")
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    with config_lock:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

def update_config_values(**changes):
    with config_lock:
        config_store.update(changes)
        save_config(config_store)

def config_snapshot(exclude: tuple = ()) -> dict:
    with config_lock:
        return {k: v for k, v in config_store.items() if k not in exclude}

config_lock       = threading.RLock()
schedule_lock     = threading.RLock()
worker_cache_lock = threading.RLock()  # node worker cache ?쎄린/?곌린 蹂댄샇
config_store     = load_config()
device_connected = False
_migrated_dbs: set = set()             # DB 留덉씠洹몃젅?댁뀡 1???ㅽ뻾 異붿쟻

def get_ams_host()       -> str:   return config_store["ams_host"]
def get_ams_pass()       -> str:   return config_store["ams_password"]
def get_ams_channel()    -> int:   return config_store.get("ams_channel", 0)
def get_save_interval()  -> int:   return config_store.get("data_save_interval_s", 5)
def get_kwh_per_m3()     -> float: return config_store.get("energy_kwh_per_m3", 0.11)
def get_price_per_kwh()  -> float: return config_store.get("energy_price_per_kwh", 170.0)
def get_co2_per_kwh()    -> float: return config_store.get("energy_co2_per_kwh", 0.454)
def get_tree_per_co2()   -> float: return config_store.get("energy_tree_per_co2", 6.0)

# ?? IODD library ?????????????????????????????????????????
def _load_iodd_index() -> list:
    if not IODD_INDEX_FILE.exists():
        return []
    try:
        with open(IODD_INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[IODD] index load failed: {type(e).__name__}: {e}")
        return []

def _save_iodd_index(items: list):
    with open(IODD_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

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
    raw = _hex_bytes_to_int(hex_bytes)
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
        entry["value"] = raw
        entry["hex"] = f"0x{raw:X}"
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

OPCUA_NODE_CONFIG = load_node_config()
REMOTE_NODE_MAPS = _read_node_maps(OPCUA_NODE_CONFIG)
REMOTE_SIGNAL_NODES = _write_node_maps(OPCUA_NODE_CONFIG)
AMS00_NODES = REMOTE_NODE_MAPS.get("AMS00", {})
AMS01_NODES = REMOTE_NODE_MAPS.get("AMS01", {})

main_loop        = None   # asyncio event loop, set in startup()
node_worker_proc = None   # persistent node-opcua worker subprocess
node_worker_stdout = None
node_worker_stderr = None
node_worker_lock = threading.RLock()
_worker_last_restart_attempt = 0.0
_WORKER_RESTART_MIN_INTERVAL_S = 5.0

WORKER_PORT     = int(os.environ.get("WORKER_PORT", "7100"))
WORKER_BASE_URL = f"http://127.0.0.1:{WORKER_PORT}"

_worker_remotes_cache: dict = {}   # remoteId ??parsed data dict
_worker_last_fetch: float   = 0.0  # epoch seconds of last /data call

# ?? ?먮꼫吏 怨꾩궛 ???????????????????????????????????????????
def calculate_energy(accumulated_flow_l: float) -> dict:
    rube = accumulated_flow_l / 1000.0
    kwh  = rube * get_kwh_per_m3()
    cost = kwh  * get_price_per_kwh()
    co2  = kwh  * get_co2_per_kwh()
    tree = co2  / get_tree_per_co2()
    return {
        "rube":     round(rube, 4),
        "kwh":      round(kwh,  4),
        "cost_krw": round(cost, 0),
        "co2_kg":   round(co2,  4),
        "tree":     round(tree, 4),
    }

def apply_usage_tracking(data: dict, persist: bool = False) -> dict:
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
    data["energy"] = calculate_energy(dashboard_total)
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
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    path_key = str(path)
    if path_key not in _migrated_dbs:
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON ams_log(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_remote ON ams_log(remote_id)")
        conn.commit()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(ams_log)").fetchall()]
        for col, typ in [
            ("energy_kwh","REAL"),("energy_cost","REAL"),("energy_co2","REAL"),
            ("raw_accumulated","REAL"),("delta_flow","REAL"),("reset_detected","INTEGER"),
            ("remote_id","TEXT"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE ams_log ADD COLUMN {col} {typ}")
        conn.commit()
        _migrated_dbs.add(path_key)
    return conn

def save_to_db(data: dict):
    try:
        data = apply_usage_tracking(data, persist=True)
        energy = data.get("energy", {})
        conn   = get_db_conn()
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
        conn.close()
    except Exception as e:
        print(f"[DB] ????ㅻ쪟: {e}")

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

def query_history(start: str, end: str, unit: str, field: str, remote_id: str = "AMS00"):
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
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt   = datetime.strptime(end,   "%Y-%m-%d").replace(hour=23, minute=59, second=59)
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
            remote_filter = "AND COALESCE(remote_id,'AMS00')=?" if remote_id else ""
            params_base   = (start_bound, end_bound, remote_id) if remote_id else (start_bound, end_bound)
            if field == "accumulated":
                res = conn.execute(f"""
                    SELECT strftime('{ts_fmt}',replace(timestamp,'T',' ')) AS period,
                           SUM(COALESCE(delta_flow,0)) AS usage_l,
                           MAX(accumulated) AS dashboard_total_l,
                           COUNT(*)
                    FROM ams_log
                    WHERE timestamp>=? AND timestamp<=? {remote_filter}
                    GROUP BY period ORDER BY period
                """, params_base)
            else:
                db_field = field_map[field]
                res = conn.execute(f"""
                    SELECT strftime('{ts_fmt}',replace(timestamp,'T',' ')) AS period,
                           AVG({db_field}), MAX({db_field}), MIN({db_field}), COUNT(*)
                    FROM ams_log
                    WHERE timestamp>=? AND timestamp<=? {remote_filter}
                    GROUP BY period ORDER BY period
                """, params_base)
            rows.extend(res.fetchall())
            conn.close()
        except Exception as e:
            print(f"[DB] 議고쉶 ?ㅻ쪟: {e}")
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
                })
                continue
            usage = float(r[1] or 0)
            cumulative += usage
            data.append({
                "period": period,
                "usage": round(usage, 4),
                "cumulative": round(cumulative, 4),
                "dashboard_total": round(r[2], 4) if r[2] is not None else None,
                "avg": round(usage, 4),
                "max": round(usage, 4),
                "min": round(usage, 4),
                "count": r[3],
            })
        return data
    row_map = {r[0]: r for r in rows}
    period_keys = _history_periods(start_dt, end_dt, unit) or [r[0] for r in rows]
    data = []
    for period in period_keys:
        r = row_map.get(period)
        if not r:
            data.append({"period":period,"avg":None,"max":None,"min":None,"count":0})
            continue
        data.append({"period":period,
                     "avg":round(r[1],4) if r[1] is not None else None,
                     "max":round(r[2],4) if r[2] is not None else None,
                     "min":round(r[3],4) if r[3] is not None else None,
                     "count":r[4]})
    return data

def export_csv(start: str, end: str, remote_id: str = "AMS00"):
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt   = datetime.strptime(end,   "%Y-%m-%d").replace(hour=23, minute=59, second=59)
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
            remote_filter = "AND COALESCE(remote_id,'AMS00')=?" if remote_id else ""
            params = (start_bound, end_bound, remote_id) if remote_id else (start_bound, end_bound)
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

def export_history_query_csv(start: str, end: str, unit: str, field: str, mode: str = "avg"):
    rows = query_history(start, end, unit, field)
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

def post_control(inst: int, value: str) -> dict:
    global device_connected
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
    acc      = safe_int(hex_str, 4,  12)
    flow     = safe_int(hex_str, 12, 16)
    temp     = round(safe_int(hex_str, 16, 20, True) * 0.1,   1)
    pres     = round(safe_int(hex_str, 20, 24, True) * 0.001, 3)
    diag_val = safe_int(hex_str, 24, 26)
    code     = safe_int(hex_str, 26, 28) & 0x0F
    itv_p    = round(safe_int(hex_str, 28, 32, True) * 0.001, 3)
    pqi      = safe_int(hex_str, 36, 38)
    diag_msgs = [t for b, t in diag_flags.items() if diag_val & b]
    state = decode_ams_status(code)
    port_st = decode_port4_status(pqi)
    return {
        "timestamp":          datetime.now().isoformat(timespec="seconds"),
        "accumulated_flow_l": acc,
        "instant_flow_l_min": flow,
        "temperature_c":      temp,
        "pressure_mpa":       pres,
        "itv_pressure_mpa":   itv_p,
        "diagnostic":         ", ".join(diag_msgs) if diag_msgs else "No error",
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
    if value is None:
        return ["--"] * width
    if isinstance(value, dict):
        items = []
        for idx in range(width):
            raw = value.get(str(idx), value.get(idx, None))
            items.append("--" if raw is None else f"{_opcua_value_to_int(raw) & 0xFF:02X}")
        return items
    if isinstance(value, (list, tuple)):
        items = [f"{_opcua_value_to_int(v) & 0xFF:02X}" for v in value[:width]]
        return items + ["--"] * max(0, width - len(items))
    return ["--"] * width


def _opcua_value_to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in ("true", "1", "on", "yes")


def parse_ams00_opcua_values(values: dict) -> dict:
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

def parse_remote_opcua_values(remote_id: str, values: dict) -> dict:
    data = parse_ams00_opcua_values(values)
    data["remote_id"] = remote_id
    data["name"] = remote_id
    return attach_iodd_context(data, remote_id)


_WORKER_FETCH_TTL_S = 0.8  # worker 罹먯떆 ?대쭅 理쒖냼 媛꾧꺽 (read interval 1s蹂대떎 吏㏐쾶)

def _get_cached_remote(remote_id: str) -> Optional[dict]:
    with worker_cache_lock:
        data = _worker_remotes_cache.get(remote_id)
        return copy.deepcopy(data) if data else None

def _get_cached_remotes_snapshot() -> dict:
    with worker_cache_lock:
        return copy.deepcopy(_worker_remotes_cache)

def _fetch_worker_data() -> dict:
    """
    worker /data ?대쭅 ??_worker_remotes_cache 媛깆떊.
    TTL ?댁뿉 ?ы샇異???湲곗〈 罹먯떆 諛섑솚 (worker??5珥덈쭏??媛깆떊?섎?濡?留ㅼ큹 fetch 遺덊븘??.
    """
    global _worker_remotes_cache, _worker_last_fetch
    now = time.time()
    if _worker_last_fetch and (now - _worker_last_fetch) < _WORKER_FETCH_TTL_S:
        return {"ok": True, "connected": True, "remotes": {}}  # caller uses _worker_remotes_cache directly
    if not (node_worker_proc and node_worker_proc.poll() is None):
        maybe_restart_node_worker("worker process is not running during read")
    try:
        resp = requests.get(f"{WORKER_BASE_URL}/data", timeout=3)
        data = resp.json()
    except Exception as e:
        _worker_last_fetch = now
        if node_worker_proc and node_worker_proc.poll() is not None:
            maybe_restart_node_worker(f"worker process exited after read failed: {type(e).__name__}")
        return {"error": f"worker_unreachable: {type(e).__name__}: {e}"}

    _worker_last_fetch = now
    remotes_raw = data.get("remotes", {})

    new_remotes: dict = {}
    for remote_id, cache in remotes_raw.items():
        if cache and cache.get("values"):
            parsed = parse_remote_opcua_values(remote_id, cache["values"])
            parsed["device_connected"]     = bool(cache.get("connected", False))
            parsed["read_latency_ms"]      = cache.get("read_latency_ms")
            parsed["opcua_stale"]          = bool(cache.get("stale", False))
            parsed["opcua_last_error"]     = cache.get("last_error")
            parsed["opcua_driver"]         = "node-opcua-worker"
        else:
            parsed = {
                "remote_id":        remote_id,
                "name":             remote_id,
                "device_connected": False,
                "error":            (cache or {}).get("last_error") or "no_data",
                "opcua_stale":      True,
            }
        new_remotes[remote_id] = parsed

    with worker_cache_lock:
        _worker_remotes_cache = new_remotes
    return data


def fetch_process_data_opcua() -> dict:
    """node-opcua worker 罹먯떆?먯꽌 理쒖떊 AMS00 ?곗씠??諛섑솚."""
    global device_connected

    raw = _fetch_worker_data()
    if "error" in raw:
        device_connected = False
        return {"error": raw["error"], "device_connected": False, "data_source": "opcua"}

    ams00 = _get_cached_remote("AMS00")
    if not ams00 or not ams00.get("device_connected"):
        device_connected = False
        err = (ams00 or {}).get("error") or (ams00 or {}).get("opcua_last_error") or "opcua_no_data"
        return {"error": err, "device_connected": False, "data_source": "opcua"}

    result = copy.deepcopy(ams00)
    result["data_source"] = "opcua"
    if result.get("opcua_stale"):
        result["opcua_cached"] = True
    apply_usage_tracking(result, persist=False)
    apply_standby_signal(result)
    device_connected = True
    return result

def fetch_process_data() -> dict:
    if config_store.get("data_source", "opcua") == "opcua":
        result = fetch_process_data_opcua()
        if not result.get("error"):
            return result
        # OPC UA ?ㅽ뙣 ?쒕쭔 web ?쒕룄 (rate-limited)
        fallback = fetch_process_data_web()
        if not fallback.get("error"):
            fallback["data_source"] = "web_fallback"
            fallback["opcua_error"] = result.get("error")
            return fallback
        return result
    return fetch_process_data_web()

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

def load_schedules():
    global schedules_store
    if SCHEDULE_FILE.exists():
        try:
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                schedules_store = json.load(f)
        except Exception as e:
            print(f"[SCHEDULE] load failed: {type(e).__name__}: {e}")
            schedules_store = []

def save_schedules():
    with schedule_lock:
        SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(schedules_store, f, indent=2, ensure_ascii=False)

load_schedules()

DAY_MAP  = {"Monday":"MON","Tuesday":"TUE","Wednesday":"WED",
            "Thursday":"THU","Friday":"FRI","Saturday":"SAT","Sunday":"SUN"}
SCHEDULE_STANDBY_SIGNAL_MODE = 8
MODE_MAP = {0:"AMS",1:"Operating",2:"Standby",3:"Isolation",SCHEDULE_STANDBY_SIGNAL_MODE:"Standby Signal"}
STATUS_WAITING = "WAITING"
STATUS_RUNNING = "RUNNING"
STATUS_DONE = "DONE"
STATUS_FAIL = "FAILED"

def can_control_device() -> bool:
    return device_connected or ensure_session()

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
    for sch in schedules_store:
        if sch.get("active", True) and schedule_status_key(sch.get("status")) == "running":
            try:
                return int(sch.get("mode", 2))
            except Exception:
                return 2
    return None

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

def set_standby_signal_enabled(enabled: bool, remote_id: str = "AMS00") -> dict:
    node_id = _signal_node(remote_id, "standby")
    if not node_id:
        return {"ok": False, "error": "standby_node_not_configured"}
    result = opcua_write_bool(node_id, enabled)
    if result.get("ok") and remote_id == "AMS00":
        update_config_values(standby_signal_enabled=enabled)
    result.update({"remote_id": remote_id, "signal": "standby", "value": enabled})
    return result

def set_forced_standby_enabled(enabled: bool, remote_id: str = "AMS00") -> dict:
    node_id = _signal_node(remote_id, "forced_standby")
    if not node_id:
        return {"ok": False, "error": "forced_standby_node_not_configured"}
    result = opcua_write_bool(node_id, enabled)
    if result.get("ok") and remote_id == "AMS00":
        update_config_values(forced_standby_enabled=enabled)
    result.update({"remote_id": remote_id, "signal": "forced_standby", "value": enabled})
    return result

def set_air_supply(enabled: bool, contact_mode: str, remote_id: str = "AMS00") -> dict:
    contact_mode = contact_mode or config_store.get("opcua_air_contact_mode", "NC")
    if contact_mode == "NC":
        node_id      = _signal_node(remote_id, "air_nc")
        signal_value = enabled
    else:
        node_id      = _signal_node(remote_id, "air_no")
        signal_value = not enabled
    if not node_id:
        return {"ok": False, "error": "air_node_not_configured"}
    result = opcua_write_bool(node_id, signal_value)
    if result.get("ok") and remote_id == "AMS00":
        update_config_values(
            air_supply_enabled=enabled,
            air_supply_signal_on=signal_value,
            opcua_air_contact_mode=contact_mode,
        )
    result.update({"remote_id": remote_id, "signal": "air_supply", "supply_on": enabled, "contact_mode": contact_mode})
    return result

def set_port4_pdout(bytes_value: list[int], remote_id: str = "AMS00") -> dict:
    remote_id = (remote_id or "AMS00").upper()
    node_id = _signal_node(remote_id, "p4_pdout")
    if not node_id:
        return {"ok": False, "error": "port4_pdout_node_not_configured", "remote_id": remote_id}
    if not bytes_value or len(bytes_value) > 16:
        return {"ok": False, "error": "bytes length must be 1..16", "remote_id": remote_id}
    normalized = []
    for index, item in enumerate(bytes_value):
        try:
            value = int(item)
        except Exception:
            return {"ok": False, "error": f"invalid byte at index {index}", "remote_id": remote_id}
        if value < 0 or value > 255:
            return {"ok": False, "error": f"byte out of range at index {index}", "remote_id": remote_id}
        normalized.append(value)
    padded = (normalized + [0] * 16)[:16]
    t0 = time.time()
    result = opcua_write_bytes_node(node_id, padded)
    node_ms = round((time.time() - t0) * 1000, 1)
    if result.get("ok"):
        print(f"[OPCUA] write OK (port4 pdout) {remote_id} {node_id} | bytes={' '.join(f'{b:02X}' for b in padded)} | node_write={node_ms}ms")
    else:
        print(f"[OPCUA] write FAIL (port4 pdout) {remote_id} {node_id} | node_write={node_ms}ms error={result.get('error')}")
    result.update({
        "remote_id": remote_id,
        "signal": "port4_pdout",
        "node_id": node_id,
        "bytes": padded,
        "bytes_hex": [f"{b:02X}" for b in padded],
    })
    return result

def port4_do_pin_bit(pin: int) -> Optional[int]:
    if pin == 2:
        return int(config_store.get("port4_do_pin2_bit", config_store.get("port4_pin2_bit", 7)))
    if pin == 4:
        return int(config_store.get("port4_do_pin4_bit", config_store.get("port4_pin4_bit", 6)))
    return None

def _current_port4_do(remote_id: str) -> int:
    cached = _get_cached_remote(remote_id) or {}
    try:
        return int(cached.get("port4_do") or 0) & 0xFF
    except Exception:
        return 0

def set_port4_do(value: int, remote_id: str = "AMS00") -> dict:
    remote_id = (remote_id or "AMS00").upper()
    node_id = _signal_node(remote_id, "p4_do")
    if not node_id:
        return {"ok": False, "error": "port4_do_node_not_configured", "remote_id": remote_id}
    try:
        normalized = int(value) & 0xFF
    except Exception:
        return {"ok": False, "error": "invalid_do_value", "remote_id": remote_id}
    t0 = time.time()
    result = opcua_write_byte_node(node_id, normalized)
    node_ms = round((time.time() - t0) * 1000, 1)
    if result.get("ok"):
        print(f"[OPCUA] write OK (port4 DO) {remote_id} {node_id} | value={normalized:02X} | node_write={node_ms}ms")
    else:
        print(f"[OPCUA] write FAIL (port4 DO) {remote_id} {node_id} | node_write={node_ms}ms error={result.get('error')}")
    result.update({
        "remote_id": remote_id,
        "signal": "port4_do",
        "node_id": node_id,
        "value": normalized,
        "value_hex": f"{normalized:02X}",
    })
    return result

def set_port4_do_pin(pin: int, enabled: bool, remote_id: str = "AMS00") -> dict:
    bit = port4_do_pin_bit(pin)
    if bit is None:
        return {"ok": False, "error": "pin must be 2 or 4", "remote_id": (remote_id or "AMS00").upper()}
    current = _current_port4_do((remote_id or "AMS00").upper())
    pin2_bit = port4_do_pin_bit(2) or 7
    pin4_bit = port4_do_pin_bit(4) or 6
    known_pin_mask = (1 << pin2_bit) | (1 << pin4_bit)
    mask = 1 << bit
    current_known = current & known_pin_mask
    value = (current_known | mask) if enabled else (current_known & ~mask)
    result = set_port4_do(value, remote_id)
    result.update({
        "pin": pin,
        "bit": bit,
        "enabled": bool(enabled),
        "previous_value": current,
        "previous_value_hex": f"{current:02X}",
        "previous_known_value": current_known,
        "previous_known_value_hex": f"{current_known:02X}",
        "mask": mask,
        "mask_hex": f"{mask:02X}",
    })
    return result

def _probe_worker_status(timeout_s: float = 0.5) -> Optional[dict]:
    try:
        resp = requests.get(f"{WORKER_BASE_URL}/status", timeout=timeout_s)
        if not resp.ok:
            return None
        return resp.json()
    except Exception:
        return None

def _request_external_worker_shutdown(timeout_s: float = 0.8):
    try:
        requests.post(f"{WORKER_BASE_URL}/shutdown", timeout=timeout_s)
    except Exception:
        pass

def start_node_worker():
    global node_worker_proc, node_worker_stdout, node_worker_stderr
    with node_worker_lock:
        if node_worker_proc and node_worker_proc.poll() is None:
            return
        desired_endpoint = str(config_store.get("opcua_endpoint", "opc.tcp://192.168.0.1:4840"))
        existing = _probe_worker_status(timeout_s=0.4)
        if existing:
            existing_endpoint = str(existing.get("endpoint") or "")
            if existing_endpoint == desired_endpoint:
                print(f"[NODE_WORKER] reuse existing worker on port {WORKER_PORT} endpoint={existing_endpoint}")
                return
            print(f"[NODE_WORKER] stopping stale worker on port {WORKER_PORT} endpoint={existing_endpoint}")
            _request_external_worker_shutdown(timeout_s=0.8)
            time.sleep(0.4)
        worker_script = BASE_DIR / "worker.js"
        if not worker_script.exists():
            worker_script = BUNDLE_DIR / "worker.js"
        node_exe = BASE_DIR / "vendor" / "node" / "node.exe"
        if not node_exe.exists():
            node_exe = BUNDLE_DIR / "vendor" / "node" / "node.exe"
        node_cmd = str(node_exe) if node_exe.exists() else "node"
        node_modules = worker_script.parent / "node_modules"
        env = os.environ.copy()
        env["WORKER_PORT"] = str(WORKER_PORT)
        env["AMS_CONFIG_PATH"] = str(CONFIG_FILE)
        env["AMS_NODES_PATH"] = str(NODES_FILE if NODES_FILE.exists() else BUNDLE_DIR / "nodes.json")
        env["OPCUA_ENDPOINT"] = desired_endpoint
        env["AMS_PASSWORD"] = str(config_store.get("ams_password", "admin"))
        if node_modules.exists():
            env["NODE_PATH"] = str(node_modules)
        LOG_DIR.mkdir(exist_ok=True)
        if node_worker_stdout:
            try: node_worker_stdout.close()
            except Exception: pass
        if node_worker_stderr:
            try: node_worker_stderr.close()
            except Exception: pass
        node_worker_stdout = open(LOG_DIR / "worker.out.log", "a", encoding="utf-8")
        node_worker_stderr = open(LOG_DIR / "worker.err.log", "a", encoding="utf-8")
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
            raise
        print(f"[NODE_WORKER] started pid={node_worker_proc.pid} port={WORKER_PORT}")

def stop_node_worker(timeout_s: float = 3.0):
    global node_worker_proc, node_worker_stdout, node_worker_stderr
    with node_worker_lock:
        if not node_worker_proc:
            for handle in (node_worker_stdout, node_worker_stderr):
                if handle:
                    try: handle.close()
                    except Exception: pass
            node_worker_stdout = None
            node_worker_stderr = None
            return
        if node_worker_proc.poll() is not None:
            node_worker_proc = None
            for handle in (node_worker_stdout, node_worker_stderr):
                if handle:
                    try: handle.close()
                    except Exception: pass
            node_worker_stdout = None
            node_worker_stderr = None
            return
        try:
            requests.post(f"{WORKER_BASE_URL}/shutdown", timeout=0.8)
        except Exception:
            pass
        try:
            node_worker_proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            node_worker_proc.terminate()
            try:
                node_worker_proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                node_worker_proc.kill()
                node_worker_proc.wait(timeout=timeout_s)
        finally:
            node_worker_proc = None
            for handle in (node_worker_stdout, node_worker_stderr):
                if handle:
                    try: handle.close()
                    except Exception: pass
            node_worker_stdout = None
            node_worker_stderr = None

def restart_node_worker():
    with node_worker_lock:
        stop_node_worker()
        start_node_worker()

def maybe_restart_node_worker(reason: str) -> bool:
    global _worker_last_restart_attempt
    now = time.time()
    with node_worker_lock:
        if now - _worker_last_restart_attempt < _WORKER_RESTART_MIN_INTERVAL_S:
            return False
        _worker_last_restart_attempt = now
    print(f"[NODE_WORKER] restart requested: {reason}")
    try:
        restart_node_worker()
        return True
    except Exception as e:
        print(f"[NODE_WORKER] restart failed: {type(e).__name__}: {e}")
        return False

def wait_for_worker_http(timeout_s: float = 3.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = requests.get(f"{WORKER_BASE_URL}/status", timeout=0.4)
            return resp.ok
        except Exception:
            time.sleep(0.1)
    return False

def ensure_node_worker_ready(timeout_s: float = 3.0) -> bool:
    if not (node_worker_proc and node_worker_proc.poll() is None):
        start_node_worker()
    return wait_for_worker_http(timeout_s)

def opcua_write_bool_node(node_id: str, value: bool) -> dict:
    if not ensure_node_worker_ready(timeout_s=8.0):
        return {"ok": False, "driver": "node-opcua", "error": f"node worker not ready (port {WORKER_PORT})"}
    try:
        resp = requests.post(
            f"{WORKER_BASE_URL}/write",
            json={"nodeId": node_id, "value": value},
            timeout=10,
        )
        data = resp.json()
        data["driver"] = "node-opcua"
        return data
    except requests.exceptions.ConnectionError:
        return {"ok": False, "driver": "node-opcua", "error": f"node worker not running (port {WORKER_PORT})"}
    except Exception as e:
        return {"ok": False, "driver": "node-opcua", "error": f"node-opcua: {type(e).__name__}: {e}"}

def opcua_write_bytes_node(node_id: str, bytes_value: list[int]) -> dict:
    if not ensure_node_worker_ready(timeout_s=8.0):
        return {"ok": False, "driver": "node-opcua", "error": f"node worker not ready (port {WORKER_PORT})"}
    try:
        resp = requests.post(
            f"{WORKER_BASE_URL}/write-bytes",
            json={"nodeId": node_id, "bytes": bytes_value},
            timeout=10,
        )
        data = resp.json()
        data["driver"] = "node-opcua"
        return data
    except requests.exceptions.ConnectionError:
        return {"ok": False, "driver": "node-opcua", "error": f"node worker not running (port {WORKER_PORT})"}
    except Exception as e:
        return {"ok": False, "driver": "node-opcua", "error": f"node-opcua: {type(e).__name__}: {e}"}

def opcua_write_byte_node(node_id: str, value: int) -> dict:
    if not ensure_node_worker_ready(timeout_s=8.0):
        return {"ok": False, "driver": "node-opcua", "error": f"node worker not ready (port {WORKER_PORT})"}
    try:
        resp = requests.post(
            f"{WORKER_BASE_URL}/write-byte",
            json={"nodeId": node_id, "value": int(value) & 0xFF},
            timeout=10,
        )
        data = resp.json()
        data["driver"] = "node-opcua"
        return data
    except requests.exceptions.ConnectionError:
        return {"ok": False, "driver": "node-opcua", "error": f"node worker not running (port {WORKER_PORT})"}
    except Exception as e:
        return {"ok": False, "driver": "node-opcua", "error": f"node-opcua: {type(e).__name__}: {e}"}

# ?? ?곹깭 API ??????????????????????????????????????????????
def _get_worker_status() -> dict:
    try:
        resp = requests.get(f"{WORKER_BASE_URL}/status", timeout=2)
        return resp.json()
    except Exception as e:
        return {"connected": False, "error": f"worker_unreachable: {e}"}

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
    remotes_snapshot = _get_cached_remotes_snapshot()
    items = []
    for idx in range(1, 11):
        remote_id = f"AMS{idx:02d}"
        data = remotes_snapshot.get(remote_id)
        if data and data.get("device_connected"):
            item = {
                "id":                remote_id,
                "name":              remote_id,
                "online":            True,
                "pressure_mpa":      data.get("pressure_mpa"),
                "instant_flow_l_min":data.get("instant_flow_l_min"),
                "temperature_c":     data.get("temperature_c"),
                "accumulated_flow_l":data.get("accumulated_flow_l"),
                "itv_pressure_mpa":  data.get("itv_pressure_mpa"),
                "diagnostic":        data.get("diagnostic"),
                "ams_status":        data.get("ams_status"),
                "ams_code":          data.get("ams_code"),
                "read_latency_ms":   data.get("read_latency_ms"),
                "stale":             data.get("opcua_stale", False),
                "port3_di":          data.get("port3_di"),
                "port3_di_hex":      data.get("port3_di_hex"),
                "port4_pqi":         data.get("port4_pqi"),
                "port4_pqi_hex":     data.get("port4_pqi_hex"),
                "port4_status":      data.get("port4_status"),
                "port4_pdin_hex":    data.get("port4_pdin_hex"),
                "port4_pdin_text":   data.get("port4_pdin_text"),
                "port4_do":          data.get("port4_do"),
                "port4_do_hex":      data.get("port4_do_hex"),
                "port4_pdout_hex":   data.get("port4_pdout_hex"),
                "port4_pdout_text":  data.get("port4_pdout_text"),
                "port4_iodd":        data.get("port4_iodd"),
                "port4_decoded":     data.get("port4_decoded"),
                "port4_decode_status": data.get("port4_decode_status"),
                "port4_analysis":    data.get("port4_analysis"),
                "standby_signal":    bool(data.get("opcua_values", {}).get("standby") in ("True", "true", "1", True)),
                "forced_standby":    bool(data.get("opcua_values", {}).get("forced_standby") in ("True", "true", "1", True)),
                "air_nc":            bool(data.get("opcua_values", {}).get("vp_itv_nc") in ("True", "true", "1", True)),
                "air_no":            bool(data.get("opcua_values", {}).get("vp_itv_no") in ("True", "true", "1", True)),
            }
        else:
            item = {
                "id": remote_id, "name": remote_id, "online": False,
                "error": (data or {}).get("error") or (data or {}).get("opcua_last_error"),
            }
        items.append(item)
    return {
        "ok":         True,
        "base":       remotes_snapshot.get("AMS00"),
        "remotes":    items,
        "updated_at": _worker_last_fetch,
        "worker":     _get_worker_status(),
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
class ConnectionConfig(BaseModel):
    ams_host:     str
    ams_password: str
    ams_channel:  int = 0

@app.post("/api/config/connection")
async def update_connection(req: ConnectionConfig):
    global ams_session, device_connected
    with config_lock:
        config_store.update({
            "ams_host":       req.ams_host,
            "ams_password":   req.ams_password,
            "ams_channel":    req.ams_channel,
            "opcua_endpoint": opcua_endpoint_from_ams_host(req.ams_host),
        })
        save_config(config_store)
    ams_session = None
    restart_node_worker()
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, try_connect)
    if not ok:
        ams_session = None
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
    kwh_per_m3:    Optional[float] = None
    price_per_kwh: Optional[float] = None
    co2_per_kwh:   Optional[float] = None
    tree_per_co2:  Optional[float] = None

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

@app.get("/api/config/energy")
def get_energy_config():
    return {"kwh_per_m3":    get_kwh_per_m3(),
            "price_per_kwh": get_price_per_kwh(),
            "co2_per_kwh":   get_co2_per_kwh(),
            "tree_per_co2":  get_tree_per_co2()}

# ?? ?붾컮?댁뒪 ?ㅼ젙 ?쎄린 API ????????????????????????????????
@app.get("/api/device/settings")
def read_device_settings():
    if not ensure_session(): return {"ok": False, "error": "device_disconnected"}
    csrf = get_csrf(ams_session); idx = 0x0001
    for buf_num, sub, prm in [(0x30,0xfe,0x01),(0x31,0xfe,0x02)]:
        v = f"0107" + f"00{idx:04x}{sub:02x}{prm:02x}00"
        ams_session.post(f"{get_ams_host()}/api/adi/config/update.json",
                         data={"inst":buf_num|0x8000,"value":v,"csrf":csrf},timeout=3,verify=False)
    time.sleep(1)
    try:
        r = ams_session.get(f"{get_ams_host()}/api/adi/status/data.json",
                            params={"inst":33072,"count":2},timeout=3,verify=False)
        vals = r.json()
        return {"itv_operation_kpa":int(vals[0],16),"itv_standby_kpa":int(vals[1],16)}
    except Exception as e: return {"ok":False,"error":str(e)}

@app.get("/api/device/pf3a-settings")
def read_pf3a_settings():
    if not ensure_session(): return {"ok": False, "error": "device_disconnected"}
    csrf = get_csrf(ams_session); idx = 0x0001
    v = f"0107" + f"00{idx:04x}{0xfe:02x}{0x04:02x}00"
    ams_session.post(f"{get_ams_host()}/api/adi/config/update.json",
                     data={"inst":0x20|0x8000,"value":v,"csrf":csrf},timeout=3,verify=False)
    time.sleep(1)
    try:
        r = ams_session.get(f"{get_ams_host()}/api/adi/status/data.json",
                            params={"inst":33056,"count":1},timeout=3,verify=False)
        return {
            "standby_threshold_lmin": int(r.json()[0],16),
            "isolation_enabled": bool(config_store.get("pf3a_isolation_enabled", False)),
            "isolation_delay_s": int(config_store.get("pf3a_isolation_delay_s", 0) or 0),
        }
    except Exception as e: return {"ok":False,"error":str(e)}

# ?? ?덉뒪?좊━ API ??????????????????????????????????????????
@app.get("/api/history")
def api_history(start: str, end: str, unit: str = "hour", field: str = "flow", remote_id: str = "AMS00"):
    try:
        return {"start":start,"end":end,"unit":unit,"field":field,"remote_id":remote_id,
                "data":query_history(start,end,unit,field,remote_id)}
    except Exception as e: return {"error":str(e)}

@app.get("/api/history/csv")
def api_history_csv(start: str, end: str, unit: Optional[str] = None, field: Optional[str] = None,
                    mode: str = "avg", remote_id: str = "AMS00"):
    try:
        if unit and field:
            output = export_history_query_csv(start, end, unit, field, mode)
            filename = f"ams_query_{remote_id}_{field}_{unit}_{start}_{end}.csv"
        else:
            output = export_csv(start, end, remote_id)
            filename = f"ams_data_{remote_id}_{start}_{end}.csv"
        return StreamingResponse(iter([output.getvalue()]),media_type="text/csv",
                                 headers={"Content-Disposition":f"attachment; filename={filename}"})
    except Exception as e: return {"error":str(e)}

# ?? ?쒖뼱 API ?????????????????????????????????????????????
class AMSModeRequest(BaseModel):    mode: int
class SaveIntervalRequest(BaseModel): interval_s: int
class StandbySignalRequest(BaseModel):
    enabled: bool
    remote_id: Optional[str] = "AMS00"
class ForcedStandbyRequest(BaseModel):
    enabled: bool
    remote_id: Optional[str] = "AMS00"
class AirSupplyRequest(BaseModel):
    enabled: bool
    contact_mode: Optional[str] = None
    remote_id: Optional[str] = "AMS00"
class Port4PdoutRequest(BaseModel):
    remote_id: Optional[str] = "AMS00"
    bytes: list[int]
class Port4DoRequest(BaseModel):
    remote_id: Optional[str] = "AMS00"
    value: Optional[int] = None
    pin: Optional[int] = None
    enabled: Optional[bool] = None
class ITVPressureRequest(BaseModel):
    operation_kpa: Optional[int]=None; standby_kpa: Optional[int]=None; ramp_duration: Optional[int]=None
class PF3AParamRequest(BaseModel):
    standby_threshold_lmin: Optional[int]=None; standby_hysteresis_lmin: Optional[int]=None
    standby_on_delay_s: Optional[int]=None; standby_off_delay_s: Optional[int]=None
    isolation_enabled: Optional[bool]=None; isolation_delay_s: Optional[int]=None

@app.post("/api/control/prepare")
def ctrl_prepare():
    return prepare_control(True)

@app.post("/api/control/ams-mode")
def ctrl_ams_mode(req: AMSModeRequest):
    if req.mode not in [0,1,2,3]: return {"ok":False,"error":"mode must be 0~3"}
    result = set_ams_mode(req.mode)
    update_config_values(force_mode=f"{req.mode:02d}", standby_signal_forced=False)
    result["mode"] = req.mode; return result

@app.post("/api/control/standby-signal")
def ctrl_standby_signal(req: StandbySignalRequest):
    return set_standby_signal_enabled(req.enabled, req.remote_id or "AMS00")

@app.post("/api/control/forced-standby")
def ctrl_forced_standby(req: ForcedStandbyRequest):
    return set_forced_standby_enabled(req.enabled, req.remote_id or "AMS00")

@app.post("/api/control/air-supply")
def ctrl_air_supply(req: AirSupplyRequest):
    return set_air_supply(req.enabled, req.contact_mode, req.remote_id or "AMS00")

@app.post("/api/control/port4-pdout")
def ctrl_port4_pdout(req: Port4PdoutRequest):
    return set_port4_pdout(req.bytes, req.remote_id or "AMS00")

@app.post("/api/control/port4-do")
def ctrl_port4_do(req: Port4DoRequest):
    if req.pin is not None:
        if req.enabled is None:
            return {"ok": False, "error": "enabled required when pin is provided"}
        return set_port4_do_pin(int(req.pin), bool(req.enabled), req.remote_id or "AMS00")
    if req.value is None:
        return {"ok": False, "error": "value or pin/enabled required"}
    return set_port4_do(int(req.value), req.remote_id or "AMS00")

@app.post("/api/control/flow-reset")
def ctrl_flow_reset():
    prep = prepare_control()
    if not prep.get("ok"): return prep
    reset_write = post_control(0x8103, "be")
    return {
        "ok": bool(prep.get("ok") and reset_write.get("ok")),
        "prep": prep,
        "reset_write": reset_write,
        "reset_inst": 0x8103,
        "reset_value": "be",
    }

@app.post("/api/control/data-total-reset")
def ctrl_data_total_reset():
    data = fetch_process_data()
    raw = float(data.get("accumulated_flow_l") or 0) if "error" not in data else config_store.get("dashboard_last_raw_accumulated_l")
    reset_at = datetime.now().isoformat(timespec="seconds")
    update_config_values(
        dashboard_total_flow_l=0.0,
        dashboard_last_raw_accumulated_l=raw,
        dashboard_total_reset_at=reset_at,
    )
    return {
        "ok": True,
        "dashboard_total_flow_l": 0.0,
        "raw_accumulated_flow_l": raw,
        "reset_at": reset_at,
    }

@app.post("/api/control/itv-pressure")
def ctrl_itv_pressure(req: ITVPressureRequest):
    prep = prepare_control()
    if not prep.get("ok"): return prep
    results = {}
    results["prep"] = prep
    changes = {}
    if req.operation_kpa is not None:
        results["operation"] = post_control(33072,f"{req.operation_kpa:04x}")
        changes["itv_operation_pressure_kpa"] = req.operation_kpa
    if req.standby_kpa is not None:
        results["standby"] = post_control(33073,f"{req.standby_kpa:04x}")
        changes["itv_standby_pressure_kpa"] = req.standby_kpa
    if req.ramp_duration is not None:
        results["ramp"] = post_control(33074,f"{req.ramp_duration:04x}")
    if changes:
        update_config_values(**changes)
    results["trigger"] = post_control(33026,"01"); return results

@app.post("/api/control/pf3a-param")
def ctrl_pf3a_param(req: PF3AParamRequest):
    prep = prepare_control()
    if not prep.get("ok"): return prep
    results = {}
    results["prep"] = prep
    changes = {}
    if req.standby_threshold_lmin is not None:
        results["threshold"]  = post_control(33056,f"{req.standby_threshold_lmin:04x}")
        changes["standby_flow_threshold_lmin"] = req.standby_threshold_lmin
    if req.standby_hysteresis_lmin is not None:
        results["hysteresis"] = post_control(33057,f"{req.standby_hysteresis_lmin:04x}")
        changes["standby_hysteresis_lmin"] = req.standby_hysteresis_lmin
    if req.standby_on_delay_s is not None:
        results["on_delay"]   = post_control(33058,f"{req.standby_on_delay_s:04x}")
        changes["standby_on_delay_s"] = req.standby_on_delay_s
    if req.standby_off_delay_s is not None:
        results["off_delay"]  = post_control(33059,f"{req.standby_off_delay_s:04x}")
        changes["standby_off_delay_s"] = req.standby_off_delay_s
    if req.isolation_enabled is not None:
        changes["pf3a_isolation_enabled"] = bool(req.isolation_enabled)
        results["isolation_enabled"] = post_control(33060, "01" if req.isolation_enabled else "00")
    if req.isolation_delay_s is not None:
        results["isolation_delay"] = post_control(33061, f"{req.isolation_delay_s:04x}")
        changes["pf3a_isolation_delay_s"] = req.isolation_delay_s
    if changes:
        update_config_values(**changes)
    results["trigger"] = post_control(33025,"01"); return results

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

@app.patch("/api/schedules/{sch_id}")
def update_schedule(sch_id: str, item: ScheduleItem):
    with schedule_lock:
        for sch in schedules_store:
            if sch["id"] == sch_id:
                if schedule_status_key(sch.get("status")) == "running":
                    return {"ok":False,"error":"stop_running_schedule_before_edit"}
                updated = item.model_dump() if hasattr(item, "model_dump") else item.dict()
                sch.update(updated)
                sch["id"] = sch_id
                if schedule_status_key(sch.get("status")) in ("done", "fail"):
                    sch["status"] = STATUS_WAITING
                else:
                    sch["status"] = sch.get("status") or STATUS_WAITING
                save_schedules()
                return {"ok":True,"schedule":sch}
    return {"ok":False,"error":"schedule_not_found"}

@app.delete("/api/schedules/{sch_id}")
def delete_schedule(sch_id: str):
    global schedules_store
    with schedule_lock:
        before          = len(schedules_store)
        schedules_store = [s for s in schedules_store if s["id"] != sch_id]
        save_schedules()
    return {"ok":len(schedules_store) < before}

@app.patch("/api/schedules/{sch_id}/toggle")
def toggle_schedule(sch_id: str):
    with schedule_lock:
        for sch in schedules_store:
            if sch["id"] == sch_id:
                sch["active"] = not sch.get("active", True)
                if sch["active"] and schedule_status_key(sch.get("status")) in ["done","fail"]:
                    sch["status"] = STATUS_WAITING
                save_schedules()
                return {"ok":True,"active":sch["active"]}
    return {"ok":False,"error":"not found"}

@app.post("/api/schedules/{sch_id}/execute")
def execute_schedule(sch_id: str):
    """?ㅼ?以?利됱떆 ?ㅽ뻾"""
    with schedule_lock:
        sch = next((s for s in schedules_store if s.get("id") == sch_id), None)
        if not sch:
            return {"ok":False,"error":"schedule_not_found"}
        mode = int(sch.get("mode", 2))
        remote_id = sch.get("remote_id", "AMS00")

    if mode != SCHEDULE_STANDBY_SIGNAL_MODE and not can_control_device():
        return {"ok":False,"error":"device_not_connected"}

    return_mode = get_config_force_mode()
    if mode == SCHEDULE_STANDBY_SIGNAL_MODE:
        result = set_standby_signal_enabled(True, remote_id)
    else:
        result = set_ams_mode(mode)

    if result.get("ok"):
        with schedule_lock:
            sch = next((s for s in schedules_store if s.get("id") == sch_id), None)
            if sch:
                if mode != SCHEDULE_STANDBY_SIGNAL_MODE:
                    sch["return_mode"] = return_mode
                sch["status"] = STATUS_RUNNING
                save_schedules()
        return {"ok":True,"mode":mode,"mode_name":MODE_MAP.get(mode,str(mode))}
    return {"ok":False,"error":"mode_change_failed"}

@app.post("/api/schedules/{sch_id}/stop")
def stop_schedule(sch_id: str):
    """?ㅼ?以?利됱떆 醫낅즺 (AMS ?먮룞紐⑤뱶 蹂듦?)"""
    with schedule_lock:
        sch = next((s for s in schedules_store if s.get("id") == sch_id), None)
        if not sch:
            return {"ok":False,"error":"schedule_not_found"}
        mode = int(sch.get("mode", 2))
        remote_id = sch.get("remote_id", "AMS00")
        repeat = sch.get("repeat")
        return_mode = int(sch.get("return_mode", get_config_force_mode()))

    if mode != SCHEDULE_STANDBY_SIGNAL_MODE and not can_control_device():
        return {"ok":False,"error":"device_not_connected"}

    if mode == SCHEDULE_STANDBY_SIGNAL_MODE:
        result = set_standby_signal_enabled(False, remote_id)
    else:
        result = set_ams_mode(return_mode)

    if result.get("ok"):
        with schedule_lock:
            sch = next((s for s in schedules_store if s.get("id") == sch_id), None)
            if sch:
                sch.pop("return_mode", None)
                if repeat == "daily":
                    sch["status"] = STATUS_WAITING
                else:
                    sch["status"] = STATUS_DONE
                    sch["active"] = False
                save_schedules()
        return {"ok":True}
    return {"ok":False,"error":"restore_failed"}

# ?? OPC UA 吏꾨떒 API ???????????????????????????????????????
def _worker_read_node_raw(node_id: str) -> dict:
    """worker /read 瑜??듯븳 ?⑥씪 ?몃뱶 利됱떆 ?쎄린. 吏꾨떒??"""
    try:
        resp = requests.post(f"{WORKER_BASE_URL}/read", json={"nodeId": node_id}, timeout=10)
        data = resp.json()
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
    now = datetime.now()
    now_str = now.strftime("%H:%M")
    actions = []
    with schedule_lock:
        for sch in schedules_store:
            if not sch.get("active", False):
                continue
            repeat  = sch.get("repeat", "once")
            days    = sch.get("days", [])
            start_t = sch.get("start_time", "")
            end_t   = sch.get("end_time", "")
            status  = sch.get("status", STATUS_WAITING)
            mode    = sch.get("mode", 2)
            if repeat == "daily":
                day_names = ["MON","TUE","WED","THU","FRI","SAT","SUN"]
                today = day_names[now.weekday()]
                if days and today not in days:
                    continue
            status_key = schedule_status_key(status)
            if status_key == "waiting" and start_t <= now_str < end_t:
                actions.append({
                    "type": "start",
                    "id": sch.get("id"),
                    "mode": int(mode),
                    "remote_id": sch.get("remote_id", "AMS00"),
                })
            elif status_key == "running" and now_str >= end_t:
                actions.append({
                    "type": "stop",
                    "id": sch.get("id"),
                    "mode": int(mode),
                    "remote_id": sch.get("remote_id", "AMS00"),
                    "repeat": repeat,
                    "return_mode": int(sch.get("return_mode", get_config_force_mode())),
                })

    for action in actions:
        mode = action["mode"]
        if action["type"] == "start":
            return_mode = get_config_force_mode()
            if mode == SCHEDULE_STANDBY_SIGNAL_MODE:
                result = set_standby_signal_enabled(True, action["remote_id"])
            else:
                result = set_ams_mode(mode)
            if result.get("ok"):
                with schedule_lock:
                    sch = next((s for s in schedules_store if s.get("id") == action["id"]), None)
                    if sch and sch.get("active", False):
                        if mode != SCHEDULE_STANDBY_SIGNAL_MODE:
                            sch["return_mode"] = return_mode
                        sch["status"] = STATUS_RUNNING
                        save_schedules()
                print(f"[SCHEDULE] started id={action['id']} mode={mode} remote={action['remote_id']}")
        else:
            if mode == SCHEDULE_STANDBY_SIGNAL_MODE:
                result = set_standby_signal_enabled(False, action["remote_id"])
            else:
                result = set_ams_mode(action["return_mode"])
            if result.get("ok"):
                with schedule_lock:
                    sch = next((s for s in schedules_store if s.get("id") == action["id"]), None)
                    if sch:
                        sch.pop("return_mode", None)
                        if action["repeat"] == "daily":
                            sch["status"] = STATUS_WAITING
                        else:
                            sch["status"] = STATUS_DONE
                            sch["active"] = False
                        save_schedules()
                print(f"[SCHEDULE] ended id={action['id']} mode={mode}")

# ?? WebSocket ?????????????????????????????????????????????
@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data          = await asyncio.to_thread(fetch_process_data)
            interval      = get_save_interval()
            data["save_interval_s"]  = interval
            data["device_connected"] = data.get("device_connected", device_connected)
            data["ams_host"]         = get_ams_host()
            data["force_mode"]       = get_display_force_mode()
            data["base_force_mode"]  = get_config_force_mode()
            data["schedule_mode"]    = get_running_schedule_mode()
            data["standby_signal"]   = get_standby_signal_status()
            data["forced_standby_signal"] = get_forced_standby_status()
            data["air_supply"]       = get_air_supply_status()
            data["energy_config"]    = {
                "kwh_per_m3":    get_kwh_per_m3(),
                "price_per_kwh": get_price_per_kwh(),
                "co2_per_kwh":   get_co2_per_kwh(),
                "tree_per_co2":  get_tree_per_co2(),
            }
            await websocket.send_json(data)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")




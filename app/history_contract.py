"""Source-scoped, commit-first measurement history. Existing rows remain legacy.

Callers serialize save() and admit the active source/generation before invoking it.
Read ranges are half-open [start, end), interpreted in the explicit site timezone.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .sample_quality import number, sample_time, usable

EXTRA_COLUMNS = {"source_key": "TEXT", "sample_id": "TEXT", "stored_at": "TEXT",
                 "quality": "TEXT", "gap": "INTEGER", "interval_start": "TEXT", "simulated": "INTEGER",
                 "measurement_generation": "TEXT", "schema_version": "INTEGER"}


def _endpoint(value):
    """Normalize endpoint identity without retaining credentials/query secrets."""
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text if "://" in text else "//" + text)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if ":" in host:
        host = "[" + host + "]"
    port = parsed.port
    if port == {"http": 80, "https": 443, "opc.tcp": 4840, "modbus": 502}.get(scheme):
        port = None
    authority = host + (f":{port}" if port is not None else "")
    return urlunsplit((scheme, authority, parsed.path.rstrip("/"), "", ""))


def source_descriptor(profile, config, nodes=None):
    """Measurement-only whitelist. Epoch is deliberately separate from source identity.

    nodes must be a measurement node map, not a worker configuration. Known output,
    command and credential entries are omitted; runtime supplies resolved input maps.
    """
    metadata = profile.metadata or {}
    measurement_nodes = None
    if profile.transport == "opcua" and nodes is not None:
        excluded = ("password", "secret", "token", "credential", "output", "pdout", "command", "write")
        def clean(value):
            if isinstance(value, dict):
                return {str(k): clean(v) for k, v in value.items()
                        if not any(part in str(k).lower() for part in excluded)
                        and str(k).lower() not in {"name", "label", "p4_do", "standby_signal", "forced_standby"}}
            if isinstance(value, (list, tuple)):
                return [clean(item) for item in value]
            return value
        measurement_nodes = clean(nodes)
    return {"transport": str(profile.transport).lower(), "endpoint": _endpoint(profile.endpoint),
            "channel": profile.channel, "model": profile.model,
            "mapping": {key: metadata[key] for key in
                        ("unit_id", "input_start", "input_count", "device_kind", "input_mapping") if key in metadata},
            "encoding": {key: config.get(key) for key in
                         ("modbus_process_byte_swap", "modbus_accumulator_word_swap")}
                        if profile.transport == "modbus" else {},
            "measurement": {key: metadata[key] for key in
                            ("unit", "units", "encoding", "scale", "offset", "measurement_fields") if key in metadata},
            "nodes": measurement_nodes}


def source_key(profile, config, nodes=None):
    return hashlib.sha256(json.dumps(source_descriptor(profile, config, nodes), sort_keys=True,
                                     separators=(",", ":"), default=str).encode()).hexdigest()


def stamp(profile, row, config, nodes=None):
    row = dict(row)
    measured = sample_time(row.get("timestamp"))
    if measured is None and row.get("timestamp"):
        try:
            # Live legacy drivers generate local time; historical rows are not rewritten.
            measured = datetime.fromisoformat(row["timestamp"]).astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    measured = measured or datetime.now(timezone.utc)
    row["timestamp"] = measured.astimezone(timezone.utc).isoformat(timespec="microseconds")
    row["source_key"] = source_key(profile, config, nodes)
    row["measurement_generation"] = str((config.get("measurement_epochs") or {}).get(profile.device_id, "initial"))
    row["sample_id"] = row.get("sample_id") or hashlib.sha256(
        (row["source_key"] + row["measurement_generation"] + row["timestamp"]).encode()).hexdigest()
    return row


def migrate(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(ams_log)")}
    for name, kind in EXTRA_COLUMNS.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE ams_log ADD COLUMN {name} {kind}")
    # Replace only our old index: sample IDs can legitimately repeat in a new epoch.
    conn.execute("DROP INDEX IF EXISTS idx_source_sample")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_source_generation_sample ON "
                 "ams_log(remote_id,source_key,measurement_generation,sample_id)")
    # Identity readers normalize legacy device IDs in Python; the unique index
    # above cannot serve their source-only predicate because remote_id leads it.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_source ON ams_log(source_key)")


def _records(directory, *, source=None):
    for path in sorted(directory.glob("ams_data_????_??.db")):
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ams_log'").fetchone():
                continue
            query = "SELECT * FROM ams_log"
            params = ()
            if source is not None:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(ams_log)")}
                if "source_key" not in columns:
                    continue  # Legacy-only months cannot match a source identity.
                query += " WHERE source_key = ?"
                params = (source,)
            for record in conn.execute(query + " ORDER BY timestamp", params):
                yield dict(record)
        finally:
            conn.close()


def _simulated(row):
    return (bool(row.get("simulated")) or str(row.get("ams_status", "")).upper() == "DEMO"
            or str(row.get("diagnostic", "")).startswith("DEMO SEED"))


def _identity_rows(directory, device, source, generation, simulated=None):
    for row in _records(directory, source=source):
        if (str(row.get("remote_id") or "AMS00").upper() != str(device).upper()
                or row.get("source_key") != source
                or str(row.get("measurement_generation")) != str(generation)
                or (simulated is not None and _simulated(row) != simulated)):
            continue
        observed = sample_time(row.get("timestamp"))
        if observed is not None:
            yield observed.astimezone(timezone.utc), row


def latest(directory, device, source, generation="initial", *, simulated=None):
    found = None
    for observed, row in _identity_rows(directory, device, source, generation, simulated):
        raw = number(row.get("raw_accumulated"))
        if row.get("quality") != "good" or raw is None or raw < 0:
            continue
        if found is None or observed > found[0]:
            found = (observed, raw, number(row.get("accumulated")))
    return (found[0].isoformat(timespec="microseconds"), found[1], found[2]) if found else None


def has_invalid_between(directory, device, source, start, end, generation="initial", *, simulated=None):
    start, end = sample_time(start), sample_time(end)
    return any(start < observed < end and row.get("quality") != "good"
               for observed, row in _identity_rows(directory, device, source, generation, simulated))


def save(directory, connect, data, energy):
    measured = sample_time(data.get("timestamp"))
    if measured is None or not data.get("source_key") or not data.get("sample_id"):
        return {"ok": False, "error": "measurement_identity_required"}
    measured = measured.astimezone(timezone.utc)
    device = str(data.get("device_id") or data.get("remote_id") or "").upper()
    if not device or device == "COMBINED":
        return {"ok": False, "error": "aggregate_history_uses_device_deltas" if device else "device_identity_required"}
    generation = str(data.get("measurement_generation", "initial"))
    simulated = _simulated(data)
    prior = None
    watermark = None
    invalid_times = []
    for observed, row in _identity_rows(directory, device, data["source_key"], generation):
        if str(row.get("sample_id")) == str(data["sample_id"]):
            return {"ok": True, "ignored": "duplicate_sample", "delta_flow_l": None, "committed": False}
        # Even a falsely reused source key must not bridge simulated and real raw.
        if _simulated(row) != simulated:
            continue
        watermark = max(watermark, observed) if watermark else observed
        old_raw = number(row.get("raw_accumulated"))
        if row.get("quality") == "good" and old_raw is not None and old_raw >= 0:
            if prior is None or observed > prior[0]:
                prior = (observed, old_raw, number(row.get("accumulated")))
        else:
            invalid_times.append(observed)
    if watermark is not None and measured <= watermark:
        return {"ok": True, "ignored": "out_of_order", "delta_flow_l": None, "committed": False}
    raw = number(data.get("accumulated_flow_l"))
    valid = usable(data) and usable(data, "accumulated_flow_l") and raw is not None and raw >= 0
    reset = bool(valid and prior and raw < prior[1])
    delta = raw - prior[1] if valid and prior and not reset else None
    total = ((prior[2] or 0) if prior else 0) + (delta or 0)
    gap = bool(prior and ((measured - prior[0]).total_seconds() > 15
                          or any(prior[0] < observed < measured for observed in invalid_times)))
    try:
        derived = energy(delta) if delta is not None else {}
    except Exception:
        derived = {"error": "energy_derivation_failed"}
    interval_start = prior[0].isoformat(timespec="microseconds") if prior and delta is not None else None
    conn = connect(measured)
    try:
        migrate(conn)
        cursor = conn.execute("""INSERT OR IGNORE INTO ams_log
            (timestamp,remote_id,pressure,temperature,flow,accumulated,raw_accumulated,delta_flow,
             reset_detected,ams_status,ams_code,diagnostic,energy_kwh,energy_cost,energy_co2,
             source_key,sample_id,stored_at,quality,gap,interval_start,simulated,measurement_generation,schema_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (measured.isoformat(timespec="microseconds"), device,
             number(data.get("pressure_mpa")) if usable(data) and usable(data, "pressure_mpa") else None,
             number(data.get("temperature_c")) if usable(data) and usable(data, "temperature_c") else None,
             number(data.get("instant_flow_l_min")) if usable(data) and usable(data, "instant_flow_l_min") else None,
             total, raw if valid else None, delta, int(reset), data.get("ams_status"), data.get("ams_code"),
             data.get("diagnostic"), derived.get("kwh"), derived.get("cost_krw"), derived.get("co2_kg"),
             data["source_key"], str(data["sample_id"]), datetime.now(timezone.utc).isoformat(),
             "good" if valid else "unavailable", int(gap), interval_start, int(simulated), generation, 3))
        conn.commit()
        if cursor.rowcount == 0:
            return {"ok": True, "ignored": "insert_ignored", "delta_flow_l": None, "committed": False}
        result = {"ok": True, "committed": True, "delta_flow_l": delta, "gap": gap,
                  "reset_detected": reset, "committed_total_flow_l": total,
                  "raw_accumulated_flow_l": raw if valid else None, "interval_start": interval_start,
                  "source_key": data["source_key"], "measurement_generation": generation,
                  "sample_id": str(data["sample_id"]), "timestamp": measured.isoformat(timespec="microseconds")}
        if derived.get("error"):
            result["energy_error"] = derived["error"]
        return result
    finally:
        conn.close()


def _zone(value):
    if isinstance(value, str):
        return ZoneInfo(value)
    return value or datetime.now().astimezone().tzinfo


def rows(directory, start, end, device="ALL", *, site_timezone=None, source=None,
         generation=None, include_simulated=None):
    """Read mixed schemas without migration; unknown legacy sources are never inferred.

    Naive bounds/legacy timestamps mean site-local wall time. Aware values are
    converted into that zone. ALL excludes simulation by default; explicit devices
    retain it unless include_simulated=False. source/generation are exact filters.
    """
    zone = _zone(site_timezone)
    def local(value):
        return value.astimezone(zone) if value.tzinfo else value.replace(tzinfo=zone)
    start, end = local(start), local(end)
    all_devices = str(device or "ALL").strip().upper() in {"ALL", "ALL DEVICES", "", "COMBINED"}
    include_simulated = not all_devices if include_simulated is None else include_simulated
    selected = []
    for row in _records(directory):
        remote = str(row.get("remote_id") or "AMS00").upper()
        if all_devices and remote in {"COMBINED", "IO13"}:
            continue
        if not all_devices and remote != str(device).strip().upper():
            continue
        if source is not None and row.get("source_key") != source:
            continue
        if generation is not None and str(row.get("measurement_generation")) != str(generation):
            continue
        simulated = _simulated(row)
        if not include_simulated and simulated:
            continue
        try:
            observed = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        legacy_time = observed.tzinfo is None
        observed = local(observed)
        if start <= observed < end:
            row.update(remote_id=remote, _local_time=observed.replace(tzinfo=None),
                       _observed_at=observed, _simulated=simulated,
                       timestamp_basis="legacy_local" if legacy_time else "utc",
                       legacy=legacy_time or not row.get("source_key") or not row.get("measurement_generation"))
            selected.append(row)
    selected.sort(key=lambda row: (row["_observed_at"].astimezone(timezone.utc), row["remote_id"]))
    yield from selected


def query(directory, start, end, unit, field, device, periods, energy, *, site_timezone=None,
          source=None, generation=None, include_simulated=None):
    formats = {"second": "%Y-%m-%d %H:%M:%S", "minute": "%Y-%m-%d %H:%M", "hour": "%Y-%m-%d %H",
               "day": "%Y-%m-%d", "month": "%Y-%m"}
    if unit not in formats or field not in {"flow", "pressure", "temperature", "accumulated", "energy_kwh", "energy_cost", "energy_co2"}:
        raise ValueError("unsupported history field or unit")
    all_devices = str(device or "ALL").strip().upper() in {"ALL", "ALL DEVICES", "", "COMBINED"}
    if all_devices and field in {"pressure", "temperature"}:
        raise ValueError("Select one device for pressure or temperature")
    def empty():
        return {"values": [], "seconds": {}, "count": 0, "demo": 0, "totals": {}, "unknown": 0, "legacy": 0}
    buckets = {}
    for row in rows(directory, start, end, device, site_timezone=site_timezone, source=source,
                    generation=generation, include_simulated=include_simulated):
        key = row["_local_time"].strftime(formats[unit])
        bucket = buckets.setdefault(key, empty())
        bucket["count"] += 1
        bucket["demo"] += int(row["_simulated"])
        bucket["legacy"] += int(row["legacy"])
        value = number(row.get("delta_flow" if field == "accumulated" or field.startswith("energy_") else field))
        if value is None:
            bucket["unknown"] += 1
        elif field == "flow" and all_devices:
            second = row["_observed_at"].astimezone(timezone.utc).replace(microsecond=0)
            bucket["seconds"][second] = bucket["seconds"].get(second, 0) + value
        else:
            bucket["values"].append(value)
        total = number(row.get("accumulated"))
        if total is not None:
            identity = (row["remote_id"], row.get("source_key"), row.get("measurement_generation"), row["_simulated"])
            bucket["totals"][identity] = total
    output, cumulative = [], 0.0
    for key in periods if periods is not None else sorted(buckets):
        b = buckets.get(key, empty())
        values = list(b["seconds"].values()) if field == "flow" and all_devices else b["values"]
        row = {"period": key, "count": b["count"], "demo_count": b["demo"], "legacy_count": b["legacy"],
               "is_demo": bool(b["count"] and b["demo"] == b["count"]), "unknown_count": b["unknown"],
               "quality": "partial" if b["unknown"] and values else "good" if values else "unavailable",
               "value_sum": sum(values) if values else None, "value_count": len(values)}
        if field == "accumulated" or field.startswith("energy_"):
            usage = sum(values) if values else None
            cumulative += usage or 0
            value = usage
            if field.startswith("energy_") and usage is not None:
                try:
                    value = number(energy(usage).get({"energy_kwh": "kwh", "energy_cost": "cost_krw", "energy_co2": "co2_kg"}[field]))
                except Exception:
                    value = None
                if value is None:
                    row["quality"] = "unavailable"
                    row["energy_error"] = "energy_derivation_failed"
            row.update(usage=usage, cumulative=cumulative,
                       dashboard_total=sum(b["totals"].values()) if b["totals"] else None,
                       avg=value, max=value, min=value, aggregation="period_total_from_usage",
                       coefficient_basis="current_configuration")
        else:
            row.update(avg=round(sum(values) / len(values), 4) if values else None,
                       max=max(values) if values else None, min=min(values) if values else None)
        output.append(row)
    return output

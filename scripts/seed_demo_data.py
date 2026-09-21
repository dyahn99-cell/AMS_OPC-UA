#!/usr/bin/env python3
"""Generate realistic demo history for AMS Dashboard charts and energy views.

Usage examples:
  py -3.12 scripts/seed_demo_data.py
  py -3.12 scripts/seed_demo_data.py --days 14 --interval-s 60 --remotes AMS00,AMS01
  py -3.12 scripts/seed_demo_data.py --replace-range
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "db"
CONFIG_PATH = ROOT / "config.json"
CONFIG_EXAMPLE_PATH = ROOT / "config.example.json"


def load_energy_config() -> dict:
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE_PATH
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        cfg = {}
    return {
        "kwh_per_m3": float(cfg.get("energy_kwh_per_m3", 0.11) or 0.11),
        "price_per_kwh": float(cfg.get("energy_price_per_kwh", 170.0) or 170.0),
        "co2_per_kwh": float(cfg.get("energy_co2_per_kwh", 0.45) or 0.45),
    }


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON ams_log(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_remote ON ams_log(remote_id)")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ams_log)").fetchall()}
    for col, typ in [
        ("energy_kwh", "REAL"),
        ("energy_cost", "REAL"),
        ("energy_co2", "REAL"),
        ("raw_accumulated", "REAL"),
        ("delta_flow", "REAL"),
        ("reset_detected", "INTEGER"),
        ("remote_id", "TEXT"),
        ("source_key", "TEXT"), ("measurement_generation", "TEXT"),
        ("sample_id", "TEXT"), ("simulated", "INTEGER"), ("schema_version", "INTEGER"),
        ("quality", "TEXT"), ("interval_start", "TEXT"), ("stored_at", "TEXT"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE ams_log ADD COLUMN {col} {typ}")
    conn.commit()


def month_db_path(dt: datetime) -> Path:
    return DB_DIR / f"ams_data_{dt.strftime('%Y_%m')}.db"


def get_conn(dt: datetime) -> sqlite3.Connection:
    path = month_db_path(dt)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    ensure_schema(conn)
    return conn


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def status_for_flow(flow: float):
    # Keep operational flavor in diagnostic, but always mark seed rows as DEMO
    # so the dashboard can clearly separate synthetic data from live hardware.
    if flow < 8:
        phase = "Low demand / idle"
    elif flow < 55:
        phase = "Normal operation"
    else:
        phase = "Peak production demand"
    return "DEMO", 900, f"DEMO SEED - synthetic history ({phase})"


def build_profile(remote_id: str) -> dict:
    if remote_id.upper() == "AMS01":
        return {
            "pressure_base": 0.58,
            "temp_base": 27.8,
            "flow_base": 34.0,
            "flow_amp": 18.0,
            "noise": 0.9,
            "seed": 101,
        }
    return {
        "pressure_base": 0.62,
        "temp_base": 28.4,
        "flow_base": 42.0,
        "flow_amp": 22.0,
        "noise": 1.0,
        "seed": 7,
    }


def sample_point(ts: datetime, profile: dict, rng: random.Random):
    hour = ts.hour + ts.minute / 60.0
    weekday = ts.weekday()
    is_weekend = weekday >= 5

    if is_weekend:
        demand = 0.28 + 0.12 * math.sin((hour - 10) / 24.0 * 2 * math.pi)
    elif 8 <= hour < 12:
        demand = 0.72 + 0.22 * math.sin((hour - 8) / 4.0 * math.pi)
    elif 12 <= hour < 13:
        demand = 0.35
    elif 13 <= hour < 18:
        demand = 0.78 + 0.18 * math.sin((hour - 13) / 5.0 * math.pi)
    elif 18 <= hour < 21:
        demand = 0.42 + 0.08 * math.sin((hour - 18) / 3.0 * math.pi)
    else:
        demand = 0.18

    if rng.random() < 0.015 and not is_weekend and 9 <= hour <= 17:
        demand = min(1.2, demand + rng.uniform(0.25, 0.55))

    flow = profile["flow_base"] * demand
    flow += profile["flow_amp"] * 0.12 * math.sin(hour / 24.0 * 4 * math.pi)
    flow += rng.uniform(-1.8, 1.8) * profile["noise"]
    flow = clamp(flow, 0.0, 120.0)

    pressure = profile["pressure_base"]
    pressure += 0.03 * math.sin(hour / 24.0 * 2 * math.pi)
    pressure -= 0.00035 * max(0.0, flow - 40.0)
    pressure += rng.uniform(-0.008, 0.008)
    pressure = clamp(pressure, 0.45, 0.72)

    temp = profile["temp_base"]
    temp += 1.6 * math.sin((hour - 14) / 24.0 * 2 * math.pi)
    temp += 0.012 * flow
    temp += rng.uniform(-0.25, 0.25)
    temp = clamp(temp, 24.0, 36.0)

    return round(pressure, 4), round(temp, 2), round(flow, 2)


def delete_range(remotes, start: datetime, end: datetime) -> int:
    months = []
    cur = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_month = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cur <= end_month:
        months.append(cur)
        cur = cur.replace(month=cur.month + 1) if cur.month < 12 else cur.replace(year=cur.year + 1, month=1)

    deleted = 0
    start_s = start.isoformat(timespec="seconds")
    end_s = end.isoformat(timespec="seconds")
    for month in months:
        path = month_db_path(month)
        if not path.exists():
            continue
        conn = sqlite3.connect(str(path))
        ensure_schema(conn)
        for remote in remotes:
            cur = conn.execute(
                "DELETE FROM ams_log WHERE COALESCE(remote_id,'AMS00')=? AND timestamp>=? AND timestamp<=?",
                (remote, start_s, end_s),
            )
            deleted += cur.rowcount if cur.rowcount is not None else 0
        conn.commit()
        conn.close()
    return deleted


def calculate_energy(total_l: float, cfg: dict) -> dict:
    rube = total_l / 1000.0
    kwh = rube * cfg["kwh_per_m3"]
    cost = kwh * cfg["price_per_kwh"]
    co2 = kwh * cfg["co2_per_kwh"]
    return {
        "kwh": round(kwh, 4),
        "cost_krw": round(cost, 0),
        "co2_kg": round(co2, 4),
    }


def generate(remotes, days: int, interval_s: int, end: datetime, replace_range: bool) -> dict:
    energy_cfg = load_energy_config()
    end = end.replace(microsecond=0)
    end = end.replace(tzinfo=ZoneInfo("Asia/Seoul")) if end.tzinfo is None else end
    end = end.astimezone(timezone.utc)
    epoch = uuid.uuid4().hex
    start = end - timedelta(days=days)
    removed = delete_range(remotes, start, end) if replace_range else 0

    inserted = 0
    totals = {}
    for remote in remotes:
        profile = build_profile(remote)
        rng = random.Random(profile["seed"] + days + interval_s)
        raw_acc = 0.0
        dash_total = 0.0
        ts = start
        batch = {}

        while ts <= end:
            pressure, temp, flow = sample_point(ts, profile, rng)
            delta = max(0.0, flow) * (interval_s / 60.0)
            raw_acc += delta
            dash_total += delta
            status, code, diag = status_for_flow(flow)
            energy = calculate_energy(delta, energy_cfg)

            key = ts.strftime("%Y_%m")
            batch.setdefault(key, []).append(
                (
                    ts.isoformat(timespec="seconds"),
                    remote,
                    pressure,
                    temp,
                    flow,
                    int(round(dash_total)),
                    round(raw_acc, 3),
                    round(delta, 3),
                    0,
                    status,
                    code,
                    diag,
                    energy["kwh"],
                    energy["cost_krw"],
                    energy["co2_kg"],
                    f"synthetic-seed:{remote}", epoch, f"{remote}:{ts.isoformat()}",
                    1, 3, "good", (ts - timedelta(seconds=interval_s)).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                )
            )
            ts += timedelta(seconds=interval_s)

        for month_key, rows in batch.items():
            year, month = map(int, month_key.split("_"))
            conn = get_conn(datetime(year, month, 1))
            conn.executemany(
                """
                INSERT INTO ams_log
                  (timestamp,remote_id,pressure,temperature,flow,accumulated,
                   raw_accumulated,delta_flow,reset_detected,
                   ams_status,ams_code,diagnostic,energy_kwh,energy_cost,energy_co2,
                   source_key,measurement_generation,sample_id,simulated,schema_version,
                   quality,interval_start,stored_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
            conn.commit()
            conn.close()
            inserted += len(rows)

        totals[remote] = round(dash_total, 3)

    return {
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "interval_s": interval_s,
        "days": days,
        "remotes": remotes,
        "removed": removed,
        "inserted": inserted,
        "totals_l": totals,
        "energy": energy_cfg,
    }


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Seed AMS Dashboard demo history data")
    p.add_argument("--days", type=int, default=14, help="How many days back to generate (default: 14)")
    p.add_argument(
        "--interval-s",
        type=int,
        default=60,
        help="Sample interval seconds (default: 60). Use 10 to match live save cadence.",
    )
    p.add_argument(
        "--remotes",
        type=str,
        default="AMS00,AMS01",
        help="Comma-separated remote ids (default: AMS00,AMS01)",
    )
    p.add_argument(
        "--end",
        type=str,
        default="",
        help="End timestamp ISO (default: now). Example: 2026-08-14T12:00:00",
    )
    p.add_argument(
        "--replace-range",
        action="store_true",
        help="Delete existing rows in the same range/remotes before insert",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.days < 1:
        print("days must be >= 1", file=sys.stderr)
        return 2
    if args.interval_s < 10:
        print("interval-s must be >= 10", file=sys.stderr)
        return 2

    remotes = [r.strip() for r in args.remotes.split(",") if r.strip()]
    if not remotes:
        print("at least one remote is required", file=sys.stderr)
        return 2

    end = datetime.fromisoformat(args.end) if args.end else datetime.now()
    result = generate(
        remotes=remotes,
        days=args.days,
        interval_s=args.interval_s,
        end=end,
        replace_range=bool(args.replace_range),
    )

    print("Demo history seed complete")
    print("  mark     : ams_status=DEMO / diagnostic starts with DEMO SEED")
    print(f"  range     : {result['start']} -> {result['end']}")
    print(f"  interval  : {result['interval_s']}s")
    print(f"  remotes   : {', '.join(result['remotes'])}")
    print(f"  removed   : {result['removed']}")
    print(f"  inserted  : {result['inserted']}")
    for remote, total in result["totals_l"].items():
        print(f"  total {remote}: {total:.1f} L")
    print(
        "  energy cfg: "
        f"{result['energy']['kwh_per_m3']} kWh/m3, "
        f"{result['energy']['price_per_kwh']} KRW/kWh, "
        f"{result['energy']['co2_per_kwh']} kg/kWh"
    )
    print(f"  db dir    : {DB_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

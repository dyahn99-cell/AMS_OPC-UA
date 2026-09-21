"""Pressure-based estimates; no device writes."""
import math
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from . import history_contract

_pressures = {}
_lock = threading.Lock()

def remember(device_id, settings):
    if settings.get('ok') is False:
        return
    try:
        op, sb = float(settings['operation_kpa']), float(settings['standby_kpa'])
        if not all(math.isfinite(v) and 0 <= v <= 1050 for v in (op, sb)):
            return
    except (KeyError, ValueError, TypeError):
        return
    with _lock:
        _pressures[device_id.upper()] = (op, sb, time.time())

def calculate(rows, operation, standby, kwh_per_m3, price, max_gap):
    litres = seconds = 0.0
    accepted = excluded = 0
    previous = None
    for stamp, code, delta, reset in rows:
        try:
            current, code = datetime.fromisoformat(stamp), int(code)
            if previous is not None:
                gap = (current-previous[0]).total_seconds()
                value = float(delta) if delta is not None else float('nan')
                if (code & 15) == 3 and (previous[1] & 15) == 3 and 0 < gap <= max_gap and not reset and math.isfinite(value) and value >= 0:
                    litres += value
                    seconds += gap
                    accepted += 1
                else:
                    excluded += 1
            previous = (current, code)
        except (TypeError, ValueError):
            previous = None
            excluded += 1
    ratio = (standby+100)/(operation+100)
    saved = litres/ratio-litres
    energy = saved/1000*kwh_per_m3
    return dict(standby_litres=litres, standby_seconds=seconds, saved_litres=saved,
                saved_kwh=energy, saved_won=energy*price, ratio=ratio,
                operation_kpa=operation, standby_kpa=standby, intervals=accepted,
                excluded_intervals=excluded, kwh_per_m3=kwh_per_m3, price_per_kwh=price)

def today(device_id, db_path, get_conn, interval, kwh_per_m3, price, *,
          source=None, generation=None, site_timezone="Asia/Seoul"):
    with _lock:
        pressure = _pressures.get(device_id.upper())
    base = dict(device_id=device_id, basis='current_pressure_today_records', estimated=True)
    if not pressure or time.time()-pressure[2] > 300:
        return {**base,'available':False,'reason':'현재 장비 압력 설정값 확인 필요'}
    now = datetime.now(ZoneInfo(site_timezone))
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    records = history_contract.rows(db_path.parent, start, now, device_id,
        site_timezone=site_timezone, source=source, generation=generation, include_simulated=False)
    rows = []
    previous = None
    for record in records:
        identity = (record.get("source_key"), record.get("measurement_generation"))
        eligible = (not record["legacy"] and record.get("quality") == "good"
                    and not record.get("gap") and record.get("interval_start")
                    and previous is not None and previous[0] == identity
                    and history_contract.sample_time(record["interval_start"]) == previous[1])
        rows.append((record["timestamp"], record.get("ams_code"),
                     record.get("delta_flow") if eligible else None,
                     record.get("reset_detected")))
        previous = (identity, history_contract.sample_time(record["timestamp"]))
    result = calculate(rows,pressure[0],pressure[1],float(kwh_per_m3),float(price),max(10,min(120,float(interval)*3)))
    return {**base,**result,'available':result['intervals']>0,'reason':'' if result['intervals'] else '연속된 스탠바이 사용량 기록 부족'}

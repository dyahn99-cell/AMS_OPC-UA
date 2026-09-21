"""Shared finite-value and source-time contracts. No device I/O or persistence."""
import math
from datetime import datetime, timezone


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def sample_time(value):
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def usable(row, field=None):
    if row.get("stale") or row.get("opcua_stale") or (row.get("health") or {}).get("stale"):
        return False
    if row.get("device_connected", row.get("online", True)) is False:
        return False
    if field is None:
        return not row.get("error")
    return number(row.get(field)) is not None and (row.get("field_quality") or {}).get(field, "good") == "good"

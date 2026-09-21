"""Strict hub-command payloads. Coercion such as bool("false") or value & 0xFF is rejected."""
from __future__ import annotations

from typing import Any, Mapping


COMMANDS_WITH_ENABLED = {"standby", "forced_standby", "air_supply"}
MODE_VALUES = {0, 1, 2, 3}
CONTACT_MODES = {"NC", "NO"}


def require_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if type(value) is not bool:
        raise ValueError(f"{key} must be a boolean")
    return value


def require_mode(payload: Mapping[str, Any]) -> int:
    value = payload.get("mode")
    if type(value) is not int or value not in MODE_VALUES:
        raise ValueError("mode must be 0~3")
    return value


def require_byte(payload: Mapping[str, Any], key: str = "value") -> int:
    value = payload.get(key)
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(f"{key} must be an integer 0..255")
    return value


def require_bytes(payload: Mapping[str, Any], key: str = "bytes") -> list[int]:
    values = payload.get(key)
    if not isinstance(values, list) or isinstance(values, (str, bytes)) or len(values) != 16:
        raise ValueError("bytes length must be exactly 16 (complete Port 4 process image)")
    out = []
    for index, item in enumerate(values):
        if type(item) is not int or not 0 <= item <= 255:
            raise ValueError(f"invalid byte at index {index}")
        out.append(item)
    return out


def require_contact_mode(payload: Mapping[str, Any], *, default: str | None = "NC") -> str:
    if "contact_mode" not in payload:
        if default is None:
            raise ValueError("contact_mode is required")
        value = default
    else:
        value = payload.get("contact_mode")
    if not isinstance(value, str) or value.upper() not in CONTACT_MODES:
        raise ValueError("contact_mode must be NC or NO")
    return value.upper()


def validate_command_payload(command: str, payload: Mapping[str, Any] | None) -> dict[str, Any]:
    parsed = dict(payload or {})
    if command in COMMANDS_WITH_ENABLED:
        require_bool(parsed, "enabled")
        if command == "air_supply":
            parsed["contact_mode"] = require_contact_mode(parsed)
    elif command == "mode":
        require_mode(parsed)
        if "contact_mode" in parsed:
            parsed["contact_mode"] = require_contact_mode(parsed)
        else:
            parsed["contact_mode"] = "NC"
    elif command == "port4_do":
        if set(parsed) == {"value"}:
            require_byte(parsed, "value")
        elif set(parsed) == {"pin", "enabled"}:
            if type(parsed["pin"]) is not int or parsed["pin"] not in (2, 4):
                raise ValueError("pin must be 2 or 4")
            require_bool(parsed, "enabled")
        else:
            raise ValueError("provide value or pin/enabled, not both")
    elif command == "port4_pdout":
        parsed["bytes"] = require_bytes(parsed)
    elif command == "flow_reset":
        pass
    return parsed

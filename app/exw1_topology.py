from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .device_hub import canonical_device_id


VALID_SLOT_KINDS = {"exa1", "dummy", "remote_io", "empty"}


@dataclass(frozen=True)
class Exw1Gateway:
    gateway_id: str
    name: str
    host: str
    port: int = 502
    unit_id: int = 1
    timeout_s: float = 1.5
    diagnostics: str = "advanced"
    max_slots: int = 15

    @property
    def endpoint(self) -> str:
        return f"{self.host}:{self.port}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gateway_id": self.gateway_id,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "unit_id": self.unit_id,
            "timeout_s": self.timeout_s,
            "endpoint": self.endpoint,
            "diagnostics": self.diagnostics,
            "max_slots": self.max_slots,
        }


@dataclass(frozen=True)
class Exw1Slot:
    gateway_id: str
    channel: int
    kind: str
    input_bytes: int
    output_bytes: int
    input_start: int
    output_start: int
    device_id: str | None = None
    name: str | None = None
    model: int | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def input_words(self) -> int:
        return self.input_bytes // 2

    @property
    def output_words(self) -> int:
        return self.output_bytes // 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "gateway_id": self.gateway_id,
            "channel": self.channel,
            "kind": self.kind,
            "device_id": self.device_id,
            "name": self.name,
            "model": self.model,
            "enabled": self.enabled,
            "input_bytes": self.input_bytes,
            "input_words": self.input_words,
            "input_start": self.input_start,
            "input_end": self.input_start + self.input_words - 1 if self.input_words else None,
            "output_bytes": self.output_bytes,
            "output_words": self.output_words,
            "output_start": self.output_start,
            "output_end": self.output_start + self.output_words - 1 if self.output_words else None,
            "metadata": dict(self.metadata),
        }


class Exw1Topology:
    def __init__(self, gateways: Iterable[Exw1Gateway], slots: Iterable[Exw1Slot], *, quarantined: Iterable[Mapping[str, Any]] = ()):
        self.quarantined = copy.deepcopy(list(quarantined))
        self.gateways = {gateway.gateway_id: gateway for gateway in gateways}
        self.slots = tuple(sorted(slots, key=lambda slot: (slot.gateway_id, slot.channel)))
        self._validate()

    def _validate(self) -> None:
        seen_channels: set[tuple[str, int]] = set()
        seen_devices: set[str] = set()
        for slot in self.slots:
            if slot.gateway_id not in self.gateways:
                raise ValueError(f"unknown EXW1 gateway: {slot.gateway_id}")
            gateway = self.gateways[slot.gateway_id]
            if not 1 <= slot.channel <= gateway.max_slots:
                raise ValueError(f"EXW1 channel must be 1..{gateway.max_slots}: {slot.channel}")
            if type(slot.enabled) is not bool:
                raise ValueError(f"enabled must be a boolean: CH{slot.channel}")
            if slot.kind not in VALID_SLOT_KINDS:
                raise ValueError(f"unsupported EXW1 slot kind: {slot.kind}")
            if slot.kind == "exa1" and (slot.input_bytes != 36 or slot.output_bytes != 18):
                raise ValueError(f"EXA1 process layout requires 36 input / 18 output bytes: CH{slot.channel}")
            if slot.model is not None and slot.model not in {20, 30, 40, 60}:
                raise ValueError(f"unsupported EXA1 model: {slot.model}")
            if slot.input_bytes < 0 or slot.output_bytes < 0 or slot.input_bytes % 2 or slot.output_bytes % 2:
                raise ValueError(f"EXW1 slot byte sizes must be non-negative even numbers: CH{slot.channel}")
            channel_key = (slot.gateway_id, slot.channel)
            if channel_key in seen_channels:
                raise ValueError(f"duplicate EXW1 channel: {slot.gateway_id}/CH{slot.channel}")
            seen_channels.add(channel_key)
            if slot.kind in {"exa1", "remote_io"} and not slot.device_id:
                raise ValueError(f"device_id is required for {slot.kind}: CH{slot.channel}")
            if slot.device_id:
                device_id = canonical_device_id(slot.device_id)
                if device_id == "COMBINED":
                    raise ValueError("COMBINED is not a physical slot")
                if device_id in seen_devices:
                    raise ValueError(f"duplicate EXW1 device_id: {device_id}")
                seen_devices.add(device_id)

    def gateway(self, gateway_id: str) -> Exw1Gateway:
        try:
            return self.gateways[gateway_id]
        except KeyError as exc:
            raise KeyError(f"EXW1 gateway not found: {gateway_id}") from exc

    def slot_for_device(self, device_id: str) -> Exw1Slot:
        requested = str(device_id).upper()
        for slot in self.slots:
            if str(slot.device_id or "").upper() == requested:
                return slot
        raise KeyError(f"EXW1 device not found: {requested}")

    def slots_for_gateway(self, gateway_id: str, *, device_only: bool = False) -> list[Exw1Slot]:
        rows = [slot for slot in self.slots if slot.gateway_id == gateway_id]
        return [slot for slot in rows if slot.device_id and slot.enabled] if device_only else rows

    def device_profiles(self) -> dict[str, dict[str, Any]]:
        profiles: dict[str, dict[str, Any]] = {}
        for slot in self.slots:
            if not slot.device_id or slot.kind not in {"exa1", "remote_io"}:
                continue
            gateway = self.gateway(slot.gateway_id)
            metadata = {
                **slot.metadata,
                "gateway_id": gateway.gateway_id,
                "unit_id": gateway.unit_id,
                "device_kind": slot.kind,
                "input_start": slot.input_start,
                "input_words": slot.input_words,
                "output_start": slot.output_start,
                "output_words": slot.output_words,
            }
            profiles[slot.device_id.upper()] = {
                "device_id": slot.device_id.upper(),
                "name": slot.name or slot.device_id.upper(),
                "role": "remote",
                "transport": "modbus",
                "enabled": slot.enabled,
                "channel": slot.channel,
                "endpoint": gateway.endpoint,
                "model": slot.model,
                "metadata": metadata,
            }
        return profiles

    def channel_map(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for slot in self.slots:
            if not slot.device_id or not slot.enabled:
                continue
            row = slot.to_dict()
            row.update({
                "display_name": slot.name or slot.device_id,
                "wireless_channel": slot.channel,
                "device_kind": slot.kind,
                "endpoint": self.gateway(slot.gateway_id).endpoint,
            })
            if slot.kind == "exa1":
                row["registers"] = {
                    "accumulated_flow": [slot.input_start, slot.input_start + 1],
                    "instant_flow": slot.input_start + 2,
                    "temperature": slot.input_start + 3,
                    "pressure": slot.input_start + 4,
                    "ams_state": slot.input_start + 5,
                    "port4_pqi": slot.input_start + 9,
                    "port4_pdin": [slot.input_start + 10, slot.input_start + 17],
                    "port4_output_control": slot.output_start,
                    "port4_pdout": [slot.output_start + 1, slot.output_start + 8],
                }
            else:
                row["registers"] = {
                    "process_input": [slot.input_start, slot.input_start + slot.input_words - 1],
                    "process_output": [slot.output_start, slot.output_start + slot.output_words - 1],
                }
            result[slot.device_id.upper()] = row
        return result

    def recovery(self) -> dict[str, Any]:
        return {"required": bool(self.quarantined), "quarantined_gateways": copy.deepcopy(self.quarantined)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "recovery": self.recovery(),
            "gateways": [gateway.to_dict() for gateway in self.gateways.values()],
            "slots": [slot.to_dict() for slot in self.slots],
            "devices": list(self.device_profiles().values()),
        }


def default_topology_config(config: Mapping[str, Any]) -> dict[str, Any]:
    gateway_id = "EXW1-01"
    slots = [
        {"channel": 1, "kind": "exa1", "device_id": "AMS01", "name": "EXA1 Ch1", "input_bytes": 36, "output_bytes": 18, "model": int(config.get("modbus_exa1_ch1_model", 40))},
        {"channel": 2, "kind": "exa1", "device_id": "AMS02", "name": "EXA1 Ch2", "input_bytes": 36, "output_bytes": 18, "model": int(config.get("modbus_exa1_ch2_model", 40))},
    ]
    slots.extend({"channel": channel, "kind": "dummy", "name": f"Dummy / Remote AMS Reserved Ch{channel}", "input_bytes": 36, "output_bytes": 18, "metadata": {"purpose": "remote_ams_reserved"}} for channel in range(3, 13))
    slots.append({"channel": 13, "kind": "remote_io", "device_id": "IO13", "name": "EXW1-RD Remote I/O Ch13", "input_bytes": 8, "output_bytes": 8, "metadata": {"part_no": "EXW1-RD#"}})
    slots.extend({"channel": channel, "kind": "empty", "input_bytes": 0, "output_bytes": 0, "enabled": False} for channel in (14, 15))
    return {
        "gateways": {
            gateway_id: {
                "name": "EXW1-BMTAC",
                "host": str(config.get("modbus_host") or ""),
                "port": int(config.get("modbus_port", 502)),
                "unit_id": int(config.get("modbus_unit_id", 1)),
                "timeout_s": float(config.get("modbus_timeout_s", 1.5)),
                "diagnostics": "advanced",
                "max_slots": 15,
                "slots": slots,
            }
        }
    }


def _load_gateway(gateway_id: str, gateway_raw: Mapping[str, Any], config: Mapping[str, Any]) -> Exw1Topology:
    if not isinstance(gateway_raw, Mapping):
        raise ValueError("gateway must be an object")
    canonical_device_id(gateway_id)
    for key in ("port", "unit_id", "max_slots"):
        if key in gateway_raw and type(gateway_raw[key]) is not int:
            raise ValueError(f"gateway {key} must be an integer")
    gateways: list[Exw1Gateway] = []
    slots: list[Exw1Slot] = []
    for gateway_id, gateway_raw in [(gateway_id, gateway_raw)]:
        gateway = Exw1Gateway(
            gateway_id=str(gateway_id),
            name=str(gateway_raw.get("name") or gateway_id),
            host=str(gateway_raw.get("host") or ""),
            port=int(gateway_raw.get("port", 502)),
            unit_id=int(gateway_raw.get("unit_id", 1)),
            timeout_s=float(gateway_raw.get("timeout_s", 1.5)),
            diagnostics=str(gateway_raw.get("diagnostics") or "advanced"),
            max_slots=int(gateway_raw.get("max_slots", 15)),
        )
        if not gateway.host or any(char.isspace() for char in gateway.host) or any(char in gateway.host for char in "/@?#"):
            raise ValueError(f"EXW1 gateway host is required without URL/path: {gateway.gateway_id}")
        if not 1 <= gateway.port <= 65535 or not 0 <= gateway.unit_id <= 255:
            raise ValueError("EXW1 port must be 1..65535 and unit_id 0..255")
        if not math.isfinite(gateway.timeout_s) or gateway.timeout_s <= 0:
            raise ValueError("EXW1 timeout_s must be finite and positive")
        if not 1 <= gateway.max_slots <= 15 or gateway.diagnostics not in {"advanced", "basic", "none"}:
            raise ValueError("EXW1 requires max_slots 1..15 and known diagnostics layout")
        gateways.append(gateway)
        input_cursor = 2048 + (5 if gateway.diagnostics == "advanced" else 0)
        output_cursor = 0
        raw_slots = gateway_raw.get("slots", [])
        if not isinstance(raw_slots, list) or any(not isinstance(item, Mapping) for item in raw_slots):
            raise ValueError("gateway slots must be a list of objects")
        for item in raw_slots:
            for key in ("channel", "input_bytes", "output_bytes", "model"):
                if item.get(key) is not None and type(item[key]) is not int:
                    raise ValueError(f"slot {key} must be an integer")
        raw_channels = [int(item.get("channel", 0)) for item in raw_slots]
        if len(raw_channels) != len(set(raw_channels)):
            raise ValueError(f"duplicate EXW1 channel in {gateway.gateway_id}")
        if any(channel < 1 or channel > gateway.max_slots for channel in raw_channels):
            raise ValueError(f"EXW1 channel must be 1..{gateway.max_slots}: {gateway.gateway_id}")
        by_channel = {int(item.get("channel")): dict(item) for item in raw_slots}
        for channel in range(1, gateway.max_slots + 1):
            item = by_channel.get(channel, {"channel": channel, "kind": "empty", "input_bytes": 0, "output_bytes": 0, "enabled": False})
            # Compatibility for topology files saved before CH13 was correctly
            # identified as Remote I/O and CH3-12 as Remote AMS reservations.
            legacy_kind = str(item.get("kind") or "").lower()
            if legacy_kind in {"remote_dm", "remote_io"}:
                item["kind"] = "remote_io"
                if str(item.get("device_id") or "").upper() == "AMS13":
                    item["device_id"] = "IO13"
                if str(item.get("name") or "").lower() in {"remote dm ch13", "remote i/o ch13"}:
                    item["name"] = "EXW1-RD Remote I/O Ch13"
                metadata = dict(item.get("metadata") or {})
                metadata.setdefault("part_no", "EXW1-RD#")
                item["metadata"] = metadata
            elif legacy_kind in {"dummy", "ams_reserved"} and 3 <= channel <= 12:
                item["kind"] = "dummy"
                item.setdefault("name", f"Dummy / Remote AMS Reserved Ch{channel}")
                metadata = dict(item.get("metadata") or {})
                metadata.setdefault("purpose", "remote_ams_reserved")
                item["metadata"] = metadata
            input_bytes = int(item.get("input_bytes", 0))
            output_bytes = int(item.get("output_bytes", 0))
            if (item.get("kind") == "dummy" and 3 <= channel <= 12
                    and input_bytes == 36 and output_bytes == 18
                    and item.get("metadata", {}).get("purpose") == "remote_ams_reserved"):
                # Resolve the reserved AMS allocation in memory, retaining its byte layout.
                item["kind"] = "exa1"
                item["device_id"] = item.get("device_id") or f"{gateway.gateway_id}_CH{channel:02d}"
                if item.get("model") is None:
                    item["model"] = int(config.get(f"modbus_exa1_ch{channel}_model",
                        config.get("modbus_exa1_ch1_model", config.get("modbus_exa1_model", 40))))
                item["name"] = f"EXA1 Ch{channel}"
                item["metadata"] = {**item["metadata"], "reserved_ams_allocation": True}
            slot = Exw1Slot(
                gateway_id=gateway.gateway_id,
                channel=channel,
                kind=str(item.get("kind") or "empty").lower(),
                input_bytes=input_bytes,
                output_bytes=output_bytes,
                input_start=input_cursor,
                output_start=output_cursor,
                device_id=canonical_device_id(item["device_id"]) if item.get("device_id") is not None else None,
                name=str(item["name"]) if item.get("name") else None,
                model=int(item["model"]) if item.get("model") is not None else None,
                enabled=item.get("enabled", True),
                metadata=dict(item.get("metadata") or {}),
            )
            slots.append(slot)
            input_cursor += slot.input_words
            output_cursor += slot.output_words
    return Exw1Topology(gateways, slots)


def load_exw1_topology(config: Mapping[str, Any], *, strict: bool = True) -> Exw1Topology:
    """Quarantine a whole gateway when a slot makes later addresses unknowable."""
    raw = config.get("modbus_gateways", {})
    errors: list[dict[str, Any]] = []
    try:
        if not isinstance(raw, Mapping):
            raise ValueError("modbus_gateways must be an object")
        if not raw and not config.get("modbus_gateways_explicit"):
            raw = default_topology_config(config)["gateways"]
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        if strict:
            raise ValueError(str(exc)) from exc
        return Exw1Topology([], [], quarantined=[{"gateway_id": None, "raw": copy.deepcopy(config.get("modbus_gateways")),
            "legacy_raw": {key: copy.deepcopy(value) for key, value in config.items() if key.startswith("modbus_")},
            "error": f"{type(exc).__name__}: {exc}"}])

    valid: dict[str, Exw1Topology] = {}
    for gateway_id, gateway_raw in raw.items():
        try:
            valid[gateway_id] = _load_gateway(gateway_id, gateway_raw, config)
        except (ValueError, TypeError, AttributeError, KeyError, OverflowError) as exc:
            if strict:
                raise ValueError(f"{gateway_id}: {exc}") from exc
            errors.append({"gateway_id": str(gateway_id), "raw": copy.deepcopy(gateway_raw), "error": f"{type(exc).__name__}: {exc}"})
    owners: dict[str, set[str]] = {}
    for gateway_id, topology in valid.items():
        for slot in topology.slots:
            if slot.device_id:
                owners.setdefault(slot.device_id, set()).add(gateway_id)
    conflicts = {owner for group in owners.values() if len(group) > 1 for owner in group}
    if conflicts and strict:
        raise ValueError("duplicate EXW1 device_id across gateways")
    for gateway_id in sorted(conflicts):
        errors.append({"gateway_id": gateway_id, "raw": copy.deepcopy(raw[gateway_id]), "error": "duplicate EXW1 device_id across gateways"})
        valid.pop(gateway_id)
    return Exw1Topology([gateway for topology in valid.values() for gateway in topology.gateways.values()],
                        [slot for topology in valid.values() for slot in topology.slots], quarantined=errors)


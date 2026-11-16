"""Model policy only: no device access and no inferred IO-Link layouts."""
from dataclasses import dataclass


COMMAND_CAPABILITY = {
    "mode": "mode", "standby": "signals", "forced_standby": "signals",
    "air_supply": "signals", "port4_do": "port4", "port4_pdout": "port4",
    "flow_reset": "flow_reset",
}


@dataclass(frozen=True)
class DeviceModel:
    key: str
    label: str
    capabilities: frozenset[str]
    input_bytes: int | None = None
    output_bytes: int | None = None


AMS = DeviceModel("exa1", "AMS (EXA1)", frozenset({
    "telemetry", "settings_read", "settings_write", "mode", "signals", "port4", "flow_reset",
}), 36, 18)
REMOTE_IO = DeviceModel("remote_io", "Remote I/O", frozenset({"telemetry", "raw_io_read"}))
UNKNOWN = DeviceModel("unknown", "장비 종류 미확인", frozenset({"telemetry"}))
MODELS = {model.key: model for model in (AMS, REMOTE_IO, UNKNOWN)}


def model_for(profile):
    # Missing kind is the pre-v2 AMS configuration contract. Explicit unknown,
    # empty or future kinds must never inherit that compatibility permission.
    kind = profile.metadata.get("device_kind", "exa1")
    return MODELS.get(str(kind).lower(), UNKNOWN)


def restrict_capabilities(profile, transport_capabilities):
    allowed = model_for(profile).capabilities
    return {key: bool(value) and key in allowed for key, value in transport_capabilities.items()}


def operation_capability(operation):
    if operation.startswith("command:"):
        return COMMAND_CAPABILITY.get(operation.split(":", 1)[1])
    return {"read_settings": "settings_read", "write_settings": "settings_write"}.get(operation)

"""Transport-neutral device models and aggregation for the AMS monitoring hub."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import threading
import re
from typing import Any, Iterable, Mapping, Protocol
from urllib.parse import urlsplit

from .command_payload import validate_command_payload
from .sample_quality import number, usable
from .device_models import model_for


TRANSPORTS = {"modbus", "opcua", "web", "simulator"}
PHYSICAL_ROLES = {"base", "remote"}
COMBINED_DEVICE_ID = "COMBINED"


def canonical_device_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value, flags=re.ASCII):
        raise ValueError("device_id must contain 1..64 ASCII letters, digits, underscores or hyphens")
    return value.upper()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class DeviceProfile:
    device_id: str
    name: str
    role: str
    transport: str
    enabled: bool = True
    channel: int | None = None
    endpoint: str | None = None
    model: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", canonical_device_id(self.device_id))
        object.__setattr__(self, "transport", str(self.transport).lower())
        object.__setattr__(self, "role", str(self.role).lower())
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if self.device_id == COMBINED_DEVICE_ID:
            raise ValueError("COMBINED is a virtual aggregate, not a physical device")
        if self.transport not in TRANSPORTS:
            raise ValueError(f"unsupported transport: {self.transport}")
        if self.role not in PHYSICAL_ROLES:
            raise ValueError(f"unsupported device role: {self.role}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeviceHealth:
    connected: bool = False
    stale: bool = False
    last_success_at: str | None = None
    last_attempt_at: str | None = None
    error: str | None = None
    latency_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeviceSnapshot:
    device_id: str
    transport: str
    online: bool
    telemetry: dict[str, Any] = field(default_factory=dict)
    health: DeviceHealth = field(default_factory=DeviceHealth)
    captured_at: str = field(default_factory=utc_now_iso)
    simulated: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = {
            "device_id": self.device_id,
            "remote_id": self.device_id,
            "transport": self.transport,
            "data_source": self.transport,
            "online": self.online,
            "device_connected": self.online,
            "captured_at": self.captured_at,
            "simulated": self.simulated,
            "health": self.health.to_dict(),
        }
        data.update(self.telemetry)
        return data


class TransportAdapter(Protocol):
    name: str

    def health(self, profile: DeviceProfile) -> DeviceHealth: ...
    def read_telemetry(self, profile: DeviceProfile) -> DeviceSnapshot: ...
    def read_settings(self, profile: DeviceProfile) -> dict[str, Any]: ...
    def write_settings(self, profile: DeviceProfile, values: Mapping[str, Any]) -> dict[str, Any]: ...
    def execute_command(self, profile: DeviceProfile, command: str, payload: Mapping[str, Any]) -> dict[str, Any]: ...


def validate_web_profile(profile: DeviceProfile, default_endpoint: str = "https://192.168.0.1") -> None:
    """The HTTP services only address the configured AMS base, not arbitrary profiles."""
    if profile.transport != "web":
        return
    endpoint = str(profile.endpoint or "").strip().rstrip("/")
    default_endpoint = str(default_endpoint or "").strip().rstrip("/")
    if profile.device_id != "AMS00" or profile.role != "base" or (endpoint and endpoint != default_endpoint):
        raise ValueError("web transport supports only AMS00/base at the configured ams_host (or an omitted endpoint)")


def normalize_opcua_endpoint(endpoint: str) -> str:
    """Compare only configured names; never resolve DNS or guess an address."""
    parsed = urlsplit(str(endpoint or "").strip())
    if (parsed.scheme.lower() != "opc.tcp" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment):
        raise ValueError("a configured opc.tcp endpoint without credentials/query/fragment is required")
    port = parsed.port if parsed.port is not None else 4840
    if not 1 <= port <= 65535:
        raise ValueError("OPC UA port must be 1..65535")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"opc.tcp://{host}:{port}{parsed.path.rstrip('/')}"


def validate_opcua_profile(profile: DeviceProfile, configured_endpoint: str) -> str:
    """The current worker owns exactly one endpoint, including omitted profiles."""
    configured = normalize_opcua_endpoint(configured_endpoint)
    resolved = normalize_opcua_endpoint(profile.endpoint or configured_endpoint)
    if resolved != configured:
        raise ValueError("opcua transport supports only the configured opcua_endpoint")
    return configured


def validate_opcua_web_fallback(profile: DeviceProfile, config: Mapping[str, Any]) -> None:
    endpoint = validate_opcua_profile(profile, str(config.get("opcua_endpoint") or ""))
    http = urlsplit(str(config.get("ams_host") or "").strip())
    opcua = urlsplit(endpoint)
    # Only the configured default base pairing is verified. Same ID alone, a
    # different hostname, custom OPC server path/port, or a remote HTTP channel
    # is not evidence that both transports address the same physical base.
    if (profile.device_id != "AMS00" or profile.role != "base"
            or http.scheme.lower() not in {"http", "https"} or not http.hostname
            or http.username is not None or http.password is not None
            or http.path not in {"", "/"} or http.query or http.fragment
            or http.hostname.lower() != opcua.hostname or opcua.port != 4840
            or opcua.path or config.get("ams_channel", 0) not in (0, "0")):
        raise ValueError("HTTP settings fallback requires AMS00/base and the verified configured HTTP/OPC base pairing")


class DeviceRegistry:
    def __init__(self, profiles: Iterable[DeviceProfile], *, quarantined: Iterable[Mapping[str, Any]] = ()):
        self.quarantined = copy.deepcopy(list(quarantined))
        self._profiles: dict[str, DeviceProfile] = {}
        opcua_targets = set()
        for profile in profiles:
            if profile.transport == "opcua" and profile.enabled:
                identity = (profile.endpoint or "", profile.device_id.replace("AMS_", "AMS"))
                if identity in opcua_targets:
                    raise ValueError(f"duplicate OPC UA alias: {profile.device_id}; register only one spelling per endpoint")
                opcua_targets.add(identity)
            if profile.device_id in self._profiles:
                raise ValueError(f"duplicate device id: {profile.device_id}")
            self._profiles[profile.device_id] = profile

    def all(self, *, enabled_only: bool = True) -> list[DeviceProfile]:
        profiles = self._profiles.values()
        if enabled_only:
            profiles = (profile for profile in profiles if profile.enabled)
        return sorted(profiles, key=lambda profile: profile.device_id)

    def get(self, device_id: str) -> DeviceProfile | None:
        return self._profiles.get(str(device_id or "").upper())

    def require(self, device_id: str) -> DeviceProfile:
        profile = self.get(device_id)
        if profile is None or not profile.enabled:
            raise KeyError(f"device is not registered or disabled: {device_id}")
        return profile

    def targets(self, target: str | Iterable[str]) -> list[DeviceProfile]:
        if isinstance(target, str):
            if target.upper() == COMBINED_DEVICE_ID:
                return self.all()
            return [self.require(target)]
        seen: set[str] = set()
        result: list[DeviceProfile] = []
        for device_id in target:
            profile = self.require(device_id)
            if profile.device_id not in seen:
                seen.add(profile.device_id)
                result.append(profile)
        return result

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {profile.device_id: profile.to_dict() for profile in self.all(enabled_only=False)}

    def recovery(self) -> dict[str, Any]:
        return {"required": bool(self.quarantined), "recovery_only": not bool(self.all()),
                "quarantined_profiles": copy.deepcopy(self.quarantined)}

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        opcua_device_ids: Iterable[str] = (),
        strict: bool = True,
        allow_legacy: bool = True,
    ) -> "DeviceRegistry":
        """Strict admission for saves; persisted-load callers explicitly opt into quarantine.

        Empty legacy profiles predate the registry. A saved explicit empty registry
        (or failed topology generation) is authoritative and must not synthesize I/O.
        """
        errors = copy.deepcopy(config.get("_profile_quarantine") or [])
        explicit = config.get("device_profiles", {})
        authoritative = (bool(explicit) or not isinstance(explicit, Mapping) or not allow_legacy
                         or config.get("device_profiles_explicit") or config.get("_profiles_authoritative"))
        if not authoritative:
            source = str(config.get("data_source") or "opcua").lower()
            if source == "modbus":
                explicit = {f"AMS{channel:02d}": {"transport": "modbus", "channel": channel,
                    "model": config.get(f"modbus_exa1_ch{channel}_model", 40)} for channel in (1, 2)}
            elif source in {"web", "demo"}:
                explicit = {"AMS00": {"transport": "web" if source == "web" else "simulator",
                    "endpoint": config.get("ams_host") if source == "web" else None}}
            else:
                ids = sorted({str(device_id).upper() for device_id in opcua_device_ids}) or ["AMS00"]
                ids = [device_id for device_id in ids if not (device_id.startswith("AMS_") and device_id.replace("AMS_", "AMS") in ids)]
                explicit = {device_id: {"transport": "opcua"} for device_id in ids}
        if not isinstance(explicit, Mapping):
            if strict:
                raise ValueError("device_profiles must be an object")
            errors.append({"device_id": None, "raw": copy.deepcopy(explicit), "error": "device_profiles must be an object"})
            return cls([], quarantined=errors)

        profiles: list[DeviceProfile] = []
        # Conflicting spellings/aliases quarantine every claimant, not whichever
        # happens to be loaded second (and must never pick one by JSON order).
        identities: dict[str, list[Any]] = {}
        opcua_aliases: dict[str, list[Any]] = {}
        for device_id, raw in explicit.items():
            identity = str(device_id).upper()
            identities.setdefault(identity, []).append(device_id)
            if isinstance(raw, Mapping) and str(raw.get("transport") or "opcua").lower() == "opcua":
                opcua_aliases.setdefault(identity.replace("AMS_", "AMS"), []).append(device_id)
        duplicates = {key for groups in (identities, opcua_aliases)
                      for keys in groups.values() if len(keys) > 1 for key in keys}
        for device_id, raw in explicit.items():
            try:
                if not isinstance(raw, Mapping):
                    raise ValueError("device profile must be an object")
                if device_id in duplicates:
                    raise ValueError(f"duplicate device id or OPC UA alias: {device_id}")
                canonical = canonical_device_id(device_id)
                if raw.get("device_id") is not None and canonical_device_id(raw["device_id"]) != canonical:
                    raise ValueError("profile device_id does not match its key")
                if raw.get("metadata") is not None and not isinstance(raw["metadata"], Mapping):
                    raise ValueError("metadata must be an object")
                channel = raw.get("channel")
                model = raw.get("model")
                if channel is not None and (type(channel) is not int or not 0 <= channel <= 15):
                    raise ValueError("channel must be an integer in 0..15")
                if model is not None and (type(model) is not int or model not in {20, 30, 40, 60}):
                    raise ValueError("model must be 20, 30, 40, or 60")
                if raw.get("endpoint") is not None and not isinstance(raw["endpoint"], str):
                    raise ValueError("endpoint must be a string or null")
                profile = DeviceProfile(
                    device_id=canonical, name=str(raw.get("name") or device_id),
                    role=str(raw.get("role") or ("base" if canonical == "AMS00" else "remote")),
                    transport=str(raw.get("transport") or "opcua"), enabled=raw.get("enabled", True),
                    channel=channel, endpoint=raw.get("endpoint") or None, model=model,
                    metadata=copy.deepcopy(dict(raw.get("metadata") or {})),
                )
                validate_web_profile(profile, str(config.get("ams_host") or "https://192.168.0.1"))
                if profile.transport == "opcua":
                    resolved = validate_opcua_profile(profile, str(config.get("opcua_endpoint", "opc.tcp://192.168.0.1:4840") or ""))
                    profile = DeviceProfile(**{**profile.to_dict(), "endpoint": resolved})
                profiles.append(profile)
            except (ValueError, TypeError, AttributeError) as exc:
                if strict:
                    raise ValueError(f"{device_id}: {exc}") from exc
                errors.append({"device_id": str(device_id), "raw": copy.deepcopy(raw),
                               "error": f"{type(exc).__name__}: {exc}"})
        if strict and errors:
            raise ValueError("; ".join(str(error.get("error")) for error in errors))
        return cls(profiles, quarantined=errors)


def aggregate_snapshots(snapshots: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(snapshot) for snapshot in snapshots]
    physical = [row for row in rows if str(row.get("device_id") or row.get("remote_id") or "").upper() != COMBINED_DEVICE_ID]
    online = [row for row in physical if bool(row.get("online", row.get("device_connected", False))) and usable(row)]
    real_online = [row for row in physical if not bool(row.get("simulated", False))]
    simulated_online = [row for row in physical if bool(row.get("simulated", False))]
    field_quality = {}

    def total(key: str, source: list[dict[str, Any]], output_key=None):
        valid = [number(row.get(key)) for row in source if row in online and usable(row, key)]
        field_quality[output_key or key] = "unavailable" if not valid else "good" if len(valid) == len(source) else "partial"
        return round(sum(valid), 3) if valid else None

    modes: dict[str, int] = {}
    warnings: list[dict[str, str]] = []
    for row in online:
        mode = str(row.get("ams_status") or "Unknown")
        modes[mode] = modes.get(mode, 0) + 1
        diagnostic = str(row.get("diagnostic") or "")
        if diagnostic and diagnostic.lower() not in {"no error", "normal", "ok"}:
            warnings.append({
                "device_id": str(row.get("device_id") or row.get("remote_id") or ""),
                "diagnostic": diagnostic,
            })

    # Production totals exclude simulator data. Simulation totals stay visible
    # separately so real and synthetic values can never be silently mixed.
    return {
        "device_id": COMBINED_DEVICE_ID,
        "remote_id": COMBINED_DEVICE_ID,
        "name": "ALL DEVICES",
        "virtual": True,
        "read_only": True,
        "online": bool(online),
        "device_connected": bool(online),
        "connection_state": "offline" if not online else ("online" if len(online) == len(physical) else "partial"),
        "device_count": len(physical),
        "online_count": len(online),
        "offline_count": len(physical) - len(online),
        "instant_flow_l_min": total("instant_flow_l_min", real_online),
        "accumulated_flow_l": total("accumulated_flow_l", real_online),
        "simulated_instant_flow_l_min": total("instant_flow_l_min", simulated_online, "simulated_instant_flow_l_min"),
        "simulated_accumulated_flow_l": total("accumulated_flow_l", simulated_online, "simulated_accumulated_flow_l"),
        "field_quality": field_quality,
        "warning_count": len(warnings),
        "warnings": warnings,
        "mode_counts": modes,
        "captured_at": utc_now_iso(),
    }


def batch_result(command: str, results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    normalized = {device_id: dict(result) for device_id, result in results.items()}
    skipped = [device_id for device_id, result in normalized.items() if bool(result.get("skipped"))]
    succeeded = [device_id for device_id, result in normalized.items() if bool(result.get("ok")) and device_id not in skipped]
    failed = [device_id for device_id, result in normalized.items() if not bool(result.get("ok")) and device_id not in skipped]
    return {
        "ok": bool(normalized) and not failed and bool(succeeded or skipped),
        "partial": bool(succeeded) and bool(failed),
        "command": command,
        "requested": len(normalized),
        "attempted": len(succeeded) + len(failed),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "skipped": len(skipped),
        "succeeded_devices": succeeded,
        "failed_devices": failed,
        "skipped_devices": skipped,
        "results": normalized,
    }

class DeviceHub:
    """Routes per-device operations to adapters and owns isolated snapshots."""

    def __init__(self, registry: DeviceRegistry, adapters: Mapping[str, TransportAdapter], *, publication_guard=None):
        self.registry = registry
        self.adapters = dict(adapters)
        self._publication_guard = publication_guard
        self._snapshot_tokens = {}
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def replace_registry(self, registry: DeviceRegistry) -> None:
        with self._lock:
            self.registry = registry
            valid_ids = {profile.device_id for profile in registry.all()}
            self._snapshots = {
                device_id: snapshot for device_id, snapshot in self._snapshots.items()
                if device_id in valid_ids
            }

    def _adapter(self, profile: DeviceProfile) -> TransportAdapter:
        adapter = self.adapters.get(profile.transport)
        if adapter is None:
            raise KeyError(f"adapter is not registered: {profile.transport}")
        return adapter

    def read_device(self, device_id: str) -> dict[str, Any]:
        profile = self.registry.require(device_id)
        guard = self._publication_guard
        token = None
        try:
            with guard(profile) if guard else nullcontext() as token:
                pass
            snapshot = self._adapter(profile).read_telemetry(profile).to_dict()
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            snapshot = DeviceSnapshot(
                device_id=profile.device_id,
                transport=profile.transport,
                online=False,
                telemetry={"error": message},
                health=DeviceHealth(connected=False, stale=True, last_attempt_at=utc_now_iso(), error=message),
                simulated=profile.transport == "simulator",
            ).to_dict()
        snapshot["model_definition"] = {"key": model_for(profile).key, "label": model_for(profile).label}
        capabilities = getattr(self._adapter(profile), "capabilities", None)
        if callable(capabilities):
            snapshot["capabilities"] = capabilities(profile)
        snapshot.update({"id": profile.device_id, "name": profile.name, "role": profile.role, "profile": profile.to_dict()})
        try:
            if guard and token is None:
                return snapshot
            with guard(profile, token) if guard else nullcontext():
                with self._lock:
                    previous_health = (self._snapshots.get(profile.device_id) or {}).get("health") or {}
                    health = snapshot.setdefault("health", {})
                    if snapshot.get("online"):
                        health.update(error=None, consecutive_failures=0)
                    else:
                        health["last_success_at"] = previous_health.get("last_success_at")
                        health["consecutive_failures"] = previous_health.get("consecutive_failures", 0) + 1
                    self._snapshots[profile.device_id] = copy.deepcopy(snapshot)
                    self._snapshot_tokens[profile.device_id] = token
        except (ValueError, RuntimeError) as exc:
            return {"id": profile.device_id, "device_id": profile.device_id,
                    "device_connected": False, "online": False, "stale": True,
                    "error": str(exc)}
        return snapshot

    def read_all(self) -> dict[str, Any]:
        profiles = self.registry.all()
        if not profiles:
            devices: list[dict[str, Any]] = []
        elif len(profiles) == 1:
            devices = [self.read_device(profiles[0].device_id)]
        else:
            # Preserve Registry order while independent endpoints are read concurrently.
            # Adapters that share one physical endpoint keep their own I/O lock/cache.
            with ThreadPoolExecutor(max_workers=min(8, len(profiles)), thread_name_prefix="device-hub") as pool:
                devices = list(pool.map(lambda profile: self.read_device(profile.device_id), profiles))
        return {"ok": True, "scope": "hub", "devices": devices, "combined": aggregate_snapshots(devices), "updated_at": utc_now_iso()}

    def cached(self, device_id: str | None = None) -> dict[str, Any]:
        if not device_id:
            devices = [row for profile in self.registry.all()
                       if (row := self.cached(profile.device_id))]
            return {"ok": True, "scope": "hub", "devices": devices, "combined": aggregate_snapshots(devices), "cached": True}
        key = device_id.upper()
        with self._lock:
            token = self._snapshot_tokens.get(key)
        guard = self._publication_guard
        if guard and token is None:
            return {}
        try:
            profile = self.registry.require(key)
            with guard(profile, token) if guard else nullcontext():
                with self._lock:
                    return copy.deepcopy(self._snapshots.get(key) or {})
        except (KeyError, ValueError, RuntimeError):
            return {}

    def read_settings(self, device_id: str) -> dict[str, Any]:
        profile = self.registry.require(device_id)
        result = dict(self._adapter(profile).read_settings(profile))
        result.update({"device_id": profile.device_id, "transport": profile.transport})
        return result

    def write_settings(self, device_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        profile = self.registry.require(device_id)
        result = dict(self._adapter(profile).write_settings(profile, values))
        result.update({"device_id": profile.device_id, "transport": profile.transport})
        return result

    def execute(self, target: str | Iterable[str], command: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = validate_command_payload(command, payload or {})
        results: dict[str, dict[str, Any]] = {}
        for profile in self.registry.targets(target):
            try:
                adapter = self._adapter(profile)
                guard = getattr(adapter, "routing_error", None)
                route_error = guard(profile) if callable(guard) else None
                supports = getattr(adapter, "supports_command", None)
                if route_error:
                    result = {"ok": False, "error": route_error, "command": command}
                elif callable(supports) and not supports(profile, command):
                    result = {"ok": True, "skipped": True, "unsupported": True, "command": command}
                else:
                    result = dict(adapter.execute_command(profile, command, payload))
            except Exception as exc:
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            result.setdefault("device_id", profile.device_id)
            result.setdefault("transport", profile.transport)
            results[profile.device_id] = result
        return batch_result(command, results)




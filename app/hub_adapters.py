from __future__ import annotations

from .output_sequence import execute_output_sequence
from .device_models import model_for, restrict_capabilities, operation_capability, COMMAND_CAPABILITY
import copy
from contextlib import nullcontext
from datetime import datetime
from typing import Any, Callable, Mapping

from .command_payload import require_bool, require_byte, require_bytes, require_contact_mode, require_mode, validate_command_payload
from .connection_context import ConnectionContextManager
from .command_target import target_scope
from .device_hub import DeviceHealth, DeviceProfile, DeviceSnapshot, validate_web_profile, validate_opcua_profile, validate_opcua_web_fallback


ServiceMap = Mapping[str, Any]


class HubAdapterBase:
    name = "base"

    def __init__(self, services: ServiceMap, contexts: ConnectionContextManager):
        self.services = services
        self.contexts = contexts

    def service(self, name: str) -> Callable[..., Any]:
        service = self.services.get(name)
        if not callable(service):
            raise KeyError(f"adapter service is not configured: {name}")
        return service

    @staticmethod
    def _result_ok(result: Any) -> bool:
        if not isinstance(result, dict):
            return True
        return bool(result.get("ok", not result.get("error")))

    @staticmethod
    def _telemetry_ok(result: Any) -> bool:
        return isinstance(result, dict) and not result.get("error") and bool(result.get("online", result.get("device_connected", False)))

    def routing_error(self, profile: DeviceProfile) -> str | None:
        return None if profile.enabled else "device is disabled"

    def capabilities(self, profile: DeviceProfile) -> dict:
        return restrict_capabilities(profile, {"telemetry": True, "settings_read": True, "settings_write": True,
                "mode": True, "signals": True, "port4": True, "flow_reset": True})

    def supports_command(self, profile: DeviceProfile, command: str) -> bool:
        return bool(self.capabilities(profile).get(COMMAND_CAPABILITY.get(command)))

    def _run(self, profile: DeviceProfile, operation: str, callback: Callable[[], Any], *, telemetry: bool = False) -> Any:
        capability = operation_capability(operation)
        if not telemetry and (capability is None or not self.capabilities(profile).get(capability)):
            return self._unsupported(profile, operation, "Model or transport does not support this operation")
        scope = self.services.get("operation_scope")
        # Admission precedes endpoint locking so a transition never drains an
        # operation that is waiting for a lock held by the publisher.
        with scope() if callable(scope) else nullcontext():
            error = self.routing_error(profile)
            if error:
                return {**self._unsupported(profile, operation, error), "error": "device_route_unavailable", "device_connected": False}
            predicate = self._telemetry_ok if telemetry else self._result_ok
            resolve = self.services.get("resolve_target")
            target = resolve(profile) if callable(resolve) and not telemetry else None
            with target_scope(target) if target is not None else nullcontext():
                def admitted_callback():
                    gate = self.services.get("command_gate")
                    if callable(gate) and operation.startswith("command:"):
                        gate(profile, operation.split(":", 1)[1])
                    return callback()
                return self.contexts.run(profile, operation, admitted_callback, retries=0, is_success=predicate)

    def _snapshot(self, profile: DeviceProfile, data: dict, *, simulated: bool = False) -> DeviceSnapshot:
        row = copy.deepcopy(data or {})
        stamp = self.services.get("stamp_sample")
        if callable(stamp):
            row = stamp(profile, row)
        stale = bool(row.get("stale") or row.get("opcua_stale") or (row.get("health") or {}).get("stale"))
        online = bool(row.get("online", row.get("device_connected", False))) and not bool(row.get("error")) and not stale
        error = str(row.get("error") or "") or None
        connection = self.contexts.snapshot(profile)
        latency = row.get("read_latency_ms", connection.get("latency_ms"))
        health = DeviceHealth(
            connected=online,
            stale=stale,
            last_success_at=row.get("timestamp") if online else None,
            last_attempt_at=connection.get("last_attempt_at") or datetime.now().isoformat(timespec="seconds"),
            error=error if online else error or "device_offline",
            latency_ms=float(latency) if latency is not None else None,
        )
        for key in ("id", "device_id", "remote_id", "transport", "data_source", "online", "device_connected", "health", "simulated"):
            row.pop(key, None)
        row["connection_context"] = connection
        return DeviceSnapshot(profile.device_id, profile.transport, online, row, health, simulated=simulated)

    def health(self, profile: DeviceProfile) -> DeviceHealth:
        return self.read_telemetry(profile).health

    @staticmethod
    def _unsupported(profile: DeviceProfile, operation: str, reason: str | None = None) -> dict:
        result = {"ok": False, "unsupported": True, "operation": operation, "device_id": profile.device_id, "transport": profile.transport}
        if reason:
            result["reason"] = reason
        return result


class ModbusHubAdapter(HubAdapterBase):
    name = "modbus"

    @staticmethod
    def _kind(profile: DeviceProfile) -> str:
        return model_for(profile).key

    def routing_error(self, profile: DeviceProfile) -> str | None:
        error = super().routing_error(profile)
        if error:
            return error
        resolve = self.services.get("require_modbus_target")
        if callable(resolve):
            try:
                current = resolve(profile.device_id)
                if (current.endpoint != profile.endpoint or current.channel != profile.channel
                        or any(current.metadata.get(key) != profile.metadata.get(key)
                               for key in ("gateway_id", "input_start", "output_start", "device_kind"))):
                    return "Modbus profile no longer matches its admitted topology route"
            except (KeyError, ValueError) as exc:
                return str(exc)
        return None

    def capabilities(self, profile: DeviceProfile) -> dict:
        if self._kind(profile) != "exa1":
            return restrict_capabilities(profile, {"telemetry": True, "raw_io_read": True, "raw_io_write": False,
                    "settings_read": False, "settings_write": False, "mode": False,
                    "signals": False, "port4": False, "flow_reset": False})
        return super().capabilities(profile)

    def supports_command(self, profile: DeviceProfile, command: str) -> bool:
        return super().supports_command(profile, command)

    def read_telemetry(self, profile: DeviceProfile) -> DeviceSnapshot:
        def load() -> dict:
            return self.service("fetch_modbus_remotes")().get(profile.device_id) or {"error": "modbus_device_not_mapped", "device_connected": False}
        return self._snapshot(profile, self._run(profile, "read_telemetry", load, telemetry=True))

    def read_settings(self, profile: DeviceProfile) -> dict:
        if self._kind(profile) != "exa1":
            return self._unsupported(profile, "read_settings", "Remote I/O parameter schema is not configured")
        return self._run(profile, "read_settings", lambda: self.service("get_modbus_settings")(profile.device_id))

    def write_settings(self, profile: DeviceProfile, values: Mapping[str, Any]) -> dict:
        if self._kind(profile) != "exa1":
            return self._unsupported(profile, "write_settings", "Remote I/O parameter schema is not configured")
        return self._run(profile, "write_settings", lambda: self.service("write_modbus_settings")(profile.device_id, dict(values)))

    def execute_command(self, profile: DeviceProfile, command: str, payload: Mapping[str, Any]) -> dict:
        payload = validate_command_payload(command, payload)
        if self._kind(profile) != "exa1":
            return self._unsupported(profile, command, "Remote I/O output schema is not configured")
        if command == "mode":
            callback = lambda: self.service("set_modbus_mode")(require_mode(payload), profile.device_id, require_contact_mode(payload))
        elif command == "standby":
            callback = lambda: self.service("set_bit")(profile.device_id, 0, require_bool(payload, "enabled"))
        elif command == "forced_standby":
            callback = lambda: self.service("set_bit")(profile.device_id, 1, require_bool(payload, "enabled"))
        elif command == "air_supply":
            callback = lambda: self.service("set_air")(profile.device_id, require_bool(payload, "enabled"), require_contact_mode(payload))
        elif command == "port4_do":
            if "pin" in payload:
                callback = lambda: self.service("set_port4_do_pin")(profile.device_id, payload["pin"], payload["enabled"])
            else:
                callback = lambda: self.service("set_port4_do")(profile.device_id, require_byte(payload, "value"))
        elif command == "port4_pdout":
            callback = lambda: self.service("set_port4_pdout")(profile.device_id, require_bytes(payload))
        elif command == "flow_reset":
            def callback() -> dict:
                self.service("exa1_service")(profile.device_id, 0x72, write_value=1, value_type="u8")
                return {"ok": True, "parameter": "0x72", "remote_id": profile.device_id}
        else:
            return self._unsupported(profile, command)
        return self._run(profile, f"command:{command}", callback)


class OpcuaHubAdapter(HubAdapterBase):
    name = "opcua"

    def _config(self) -> dict:
        get_config = self.services.get("get_config")
        if not callable(get_config):
            return {}
        return {key: get_config(key, default) for key, default in
                (("opcua_endpoint", ""), ("ams_host", ""), ("ams_channel", 0))}

    def routing_error(self, profile: DeviceProfile) -> str | None:
        error = super().routing_error(profile)
        if error:
            return error
        try:
            validate_opcua_profile(profile, self._config().get("opcua_endpoint", ""))
        except ValueError as exc:
            return str(exc)
        return None

    def _settings_error(self, profile: DeviceProfile, service: str) -> str | None:
        error = self.routing_error(profile)
        if error:
            return error
        try:
            validate_opcua_web_fallback(profile, self._config())
        except ValueError as exc:
            return str(exc)
        if not callable(self.services.get(service)):
            return "HTTP settings service is not configured"
        return None

    def capabilities(self, profile: DeviceProfile) -> dict:
        return restrict_capabilities(profile, {"telemetry": True,
                "settings_read": self._settings_error(profile, "read_web_settings") is None,
                "settings_write": self._settings_error(profile, "write_web_settings") is None,
                "mode": True, "signals": True, "port4": True, "flow_reset": False})

    def read_telemetry(self, profile: DeviceProfile) -> DeviceSnapshot:
        def load() -> dict:
            raw = self.service("fetch_worker_data")()
            if raw.get("error"):
                return {"error": raw.get("error"), "device_connected": False}
            return self.service("get_cached_remote")(profile.device_id) or {"error": "opcua_device_not_cached", "device_connected": False}
        return self._snapshot(profile, self._run(profile, "read_telemetry", load, telemetry=True))

    def read_settings(self, profile: DeviceProfile) -> dict:
        def execute():
            error = self._settings_error(profile, "read_web_settings")
            if error:
                return self._unsupported(profile, "read_settings", error)
            return self.service("read_web_settings")()
        return self._run(profile, "read_settings", execute)

    def write_settings(self, profile: DeviceProfile, values: Mapping[str, Any]) -> dict:
        def execute():
            error = self._settings_error(profile, "write_web_settings")
            if error:
                return self._unsupported(profile, "write_settings", error)
            return self.service("write_web_settings")(dict(values))
        return self._run(profile, "write_settings", execute)

    def _write_bool(self, profile: DeviceProfile, signal: str, enabled: bool) -> dict:
        node_id = self.service("signal_node")(profile.device_id, signal)
        if not node_id:
            return {"ok": False, "error": f"{signal}_node_not_configured"}
        result = self.service("write_bool_node")(node_id, enabled)
        result.update({"remote_id": profile.device_id, "signal": signal, "node_id": node_id, "value": enabled})
        return result

    def execute_command(self, profile: DeviceProfile, command: str, payload: Mapping[str, Any]) -> dict:
        payload = validate_command_payload(command, payload)
        def execute() -> dict:
            if command == "standby":
                return self._write_bool(profile, "standby", require_bool(payload, "enabled"))
            if command == "forced_standby":
                return self._write_bool(profile, "forced_standby", require_bool(payload, "enabled"))
            if command == "air_supply":
                contact = require_contact_mode(payload)
                supply = require_bool(payload, "enabled")
                signal = "air_nc" if contact == "NC" else "air_no"
                return self._write_bool(profile, signal, supply if contact == "NC" else not supply)
            if command == "port4_do":
                node_id = self.service("signal_node")(profile.device_id, "p4_do")
                if not node_id:
                    return {"ok": False, "error": "port4_do_node_not_configured"}
                if "pin" in payload:
                    bit = self.service("port4_do_pin_bit")(payload["pin"])
                    if type(bit) is not int or not 0 <= bit <= 7:
                        return {"ok": False, "error": "invalid Port 4 pin bit"}
                    current = require_byte({"value": self.service("read_byte_node")(node_id)})
                    mask = 1 << bit
                    value = current | mask if payload["enabled"] else current & ~mask
                    result = self.service("write_byte_node")(node_id, value)
                    if result.get("ok"):
                        readback = require_byte({"value": self.service("read_byte_node")(node_id)})
                        result.update({"ok": readback == value, "verified": readback == value,
                                       "readback_value": readback,
                                       "error": None if readback == value else "opcua_write_readback_mismatch"})
                    result.update({"pin": payload["pin"], "enabled": payload["enabled"],
                                   "bit": bit, "previous_value": current, "value": value})
                else:
                    result = self.service("write_byte_node")(node_id, require_byte(payload, "value"))
                result.update({"remote_id": profile.device_id, "node_id": node_id})
                return result
            if command == "port4_pdout":
                node_id = self.service("signal_node")(profile.device_id, "p4_pdout")
                if not node_id:
                    return {"ok": False, "error": "port4_pdout_node_not_configured"}
                values = require_bytes(payload)
                result = self.service("write_bytes_node")(node_id, values)
                result.update({"remote_id": profile.device_id, "node_id": node_id, "bytes": values})
                return result
            if command == "mode":
                mode = require_mode(payload)
                contact = require_contact_mode(payload)
                signal = "air_nc" if contact == "NC" else "air_no"
                supply = mode != 3
                steps = [lambda: self._write_bool(profile, "standby", False),
                         lambda: self._write_bool(profile, "forced_standby", mode == 2)]
                if mode != 2:
                    steps.append(lambda: self._write_bool(profile, signal, supply if contact == "NC" else not supply))
                return {**execute_output_sequence(steps), "mode": mode}
            return self._unsupported(profile, command)
        if command not in {"standby", "forced_standby", "air_supply", "port4_do", "port4_pdout", "mode"}:
            return self._unsupported(profile, command)
        return self._run(profile, f"command:{command}", execute)


class WebHubAdapter(HubAdapterBase):
    name = "web"

    def routing_error(self, profile: DeviceProfile) -> str | None:
        error = super().routing_error(profile)
        if error:
            return error
        get_config = self.services.get("get_config")
        endpoint = get_config("ams_host", "https://192.168.0.1") if callable(get_config) else "https://192.168.0.1"
        try:
            validate_web_profile(profile, endpoint)
        except ValueError as exc:
            return str(exc)
        return None

    def capabilities(self, profile: DeviceProfile) -> dict:
        return {**super().capabilities(profile), "signals": False, "port4": False}

    def _run(self, profile: DeviceProfile, operation: str, callback: Callable[[], Any], *, telemetry: bool = False) -> Any:
        get_config = self.services.get("get_config")
        endpoint = get_config("ams_host", "https://192.168.0.1") if callable(get_config) else "https://192.168.0.1"
        try:
            validate_web_profile(profile, endpoint)
        except ValueError as exc:
            return {**self._unsupported(profile, operation, str(exc)), "error": "unsupported_web_profile", "device_connected": False}
        return super()._run(profile, operation, callback, telemetry=telemetry)

    def read_telemetry(self, profile: DeviceProfile) -> DeviceSnapshot:
        return self._snapshot(profile, self._run(profile, "read_telemetry", self.service("fetch_web_data"), telemetry=True))

    def read_settings(self, profile: DeviceProfile) -> dict:
        return self._run(profile, "read_settings", self.service("read_web_settings"))

    def write_settings(self, profile: DeviceProfile, values: Mapping[str, Any]) -> dict:
        return self._run(profile, "write_settings", lambda: self.service("write_web_settings")(dict(values)))

    def execute_command(self, profile: DeviceProfile, command: str, payload: Mapping[str, Any]) -> dict:
        payload = validate_command_payload(command, payload)
        if command not in {"mode", "flow_reset"}:
            return self._unsupported(profile, command)

        def execute() -> dict:
            warmup = self.service("warmup_web")(False)
            if not warmup.get("ok"):
                return warmup
            if command == "flow_reset":
                return self.service("post_control")(0x8103, "be")
            mode = require_mode(payload)
            write = self.service("post_control")(self.services["mode_parameter"], f"{mode:02X}")
            trigger = self.service("post_control")(self.services["control_trigger"], "01")
            return {"ok": bool(write.get("ok") and trigger.get("ok")), "mode": mode, "write": write, "trigger": trigger}
        return self._run(profile, f"command:{command}", execute)


class SimulatorHubAdapter(HubAdapterBase):
    name = "simulator"

    def read_telemetry(self, profile: DeviceProfile) -> DeviceSnapshot:
        def load() -> dict:
            data = self.service("fetch_demo_data")()
            data["simulated"] = True
            return data
        return self._snapshot(profile, self._run(profile, "read_telemetry", load, telemetry=True), simulated=True)

    def read_settings(self, profile: DeviceProfile) -> dict:
        return self._run(profile, "read_settings", lambda: self._read_settings(profile))

    def _read_settings(self, profile: DeviceProfile) -> dict:
        get_config = self.service("get_config")
        return {
            "ok": True,
            "source": "simulator",
            "operation_kpa": int(get_config("itv_operation_pressure_kpa", 600)),
            "standby_kpa": int(get_config("itv_standby_pressure_kpa", 192)),
            "standby_threshold_lmin": int(get_config("standby_flow_threshold_lmin", 30)),
            "isolation_enabled": bool(get_config("pf3a_isolation_enabled", False)),
            "isolation_delay_s": int(get_config("pf3a_isolation_delay_s", 0) or 0),
        }

    def write_settings(self, profile: DeviceProfile, values: Mapping[str, Any]) -> dict:
        return self._run(profile, "write_settings", lambda: self._write_settings(profile, values))

    def _write_settings(self, profile: DeviceProfile, values: Mapping[str, Any]) -> dict:
        key_map = {"operation_kpa": "itv_operation_pressure_kpa", "standby_kpa": "itv_standby_pressure_kpa", "standby_threshold_lmin": "standby_flow_threshold_lmin", "isolation_enabled": "pf3a_isolation_enabled", "isolation_delay_s": "pf3a_isolation_delay_s"}
        changes = {key_map[key]: value for key, value in dict(values).items() if key in key_map and value is not None}
        if changes:
            self.service("update_config")(**changes)
        return {"ok": True, "source": "simulator", "written": list(changes), "settings": self.read_settings(profile)}

    def execute_command(self, profile: DeviceProfile, command: str, payload: Mapping[str, Any]) -> dict:
        payload = validate_command_payload(command, payload)
        return self._run(profile, f"command:{command}", lambda: self._execute(profile, command, payload))

    def _execute(self, profile, command, payload):
        if command == "mode":
            mode = require_mode(payload)
            self.service("update_config")(force_mode=f"{mode:02d}")
            return {"ok": True, "simulated": True, "mode": mode}
        if command in {"standby", "forced_standby", "air_supply", "port4_do", "port4_pdout", "flow_reset"}:
            return {"ok": True, "simulated": True, "command": command}
        return self._unsupported(profile, command)


def build_runtime_adapters(services: ServiceMap, contexts: ConnectionContextManager) -> dict[str, HubAdapterBase]:
    return {
        "modbus": ModbusHubAdapter(services, contexts),
        "opcua": OpcuaHubAdapter(services, contexts),
        "web": WebHubAdapter(services, contexts),
        "simulator": SimulatorHubAdapter(services, contexts),
    }

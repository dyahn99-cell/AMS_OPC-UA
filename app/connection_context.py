from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable, TypeVar

from .device_hub import DeviceProfile


T = TypeVar("T")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ConnectionContext:
    transport: str
    endpoint: str
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    connected: bool = False
    attempts: int = 0
    successes: int = 0
    consecutive_failures: int = 0
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None
    latency_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "transport": self.transport,
            "endpoint": self.endpoint,
            "connected": self.connected,
            "attempts": self.attempts,
            "successes": self.successes,
            "consecutive_failures": self.consecutive_failures,
            "last_attempt_at": self.last_attempt_at,
            "last_success_at": self.last_success_at,
            "last_error_at": self.last_error_at,
            "last_error": self.last_error,
            "latency_ms": self.latency_ms,
        }


class ConnectionContextManager:
    """Owns endpoint-scoped locks and health without retrying writes implicitly."""

    def __init__(self) -> None:
        self._contexts: dict[tuple[str, str], ConnectionContext] = {}
        self._lock = threading.RLock()

    @staticmethod
    def endpoint_for(profile: DeviceProfile) -> str:
        return str(profile.endpoint or profile.metadata.get("endpoint") or "default")

    def context_for(self, profile: DeviceProfile) -> ConnectionContext:
        key = (profile.transport, self.endpoint_for(profile))
        with self._lock:
            context = self._contexts.get(key)
            if context is None:
                context = ConnectionContext(*key)
                self._contexts[key] = context
            return context

    def run(
        self,
        profile: DeviceProfile,
        operation: str,
        callback: Callable[[], T],
        *,
        retries: int = 0,
        retry_delay_s: float = 0.05,
        is_success: Callable[[T], bool] | None = None,
    ) -> T:
        context = self.context_for(profile)
        last_error: Exception | None = None
        with context.lock:
            for attempt in range(max(0, retries) + 1):
                started = time.perf_counter()
                context.attempts += 1
                context.last_attempt_at = _utc_now()
                try:
                    result = callback()
                except Exception as exc:
                    last_error = exc
                    context.connected = False
                    context.consecutive_failures += 1
                    context.last_error = f"{type(exc).__name__}: {exc}"
                    context.last_error_at = _utc_now()
                    context.latency_ms = round((time.perf_counter() - started) * 1000, 2)
                    if attempt < retries:
                        time.sleep(retry_delay_s * (attempt + 1))
                        continue
                    raise
                context.latency_ms = round((time.perf_counter() - started) * 1000, 2)
                if is_success is not None and not is_success(result):
                    context.connected = False
                    context.consecutive_failures += 1
                    error = result.get("error") if isinstance(result, dict) else None
                    context.last_error = str(error or f"{operation}_failed")
                    context.last_error_at = _utc_now()
                    return result
                context.connected = True
                context.successes += 1
                context.consecutive_failures = 0
                context.last_success_at = _utc_now()
                context.last_error = None
                return result
        assert last_error is not None
        raise last_error

    def snapshot(self, profile: DeviceProfile | None = None) -> dict[str, Any]:
        if profile is not None:
            return self.context_for(profile).to_dict()
        with self._lock:
            return {
                f"{transport}:{endpoint}": context.to_dict()
                for (transport, endpoint), context in sorted(self._contexts.items())
            }




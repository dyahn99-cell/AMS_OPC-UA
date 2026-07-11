"""Shared runtime state and locks."""
from .runtime import (
    device_connected, schedule_lock, worker_cache_lock,
    _get_cached_remote, _get_cached_remotes_snapshot,
)

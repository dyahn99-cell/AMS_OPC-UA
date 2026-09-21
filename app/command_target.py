"""Immutable resolved route, scoped through real adapter/service callbacks."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json


_active = ContextVar("resolved_command_target", default=None)


@dataclass(frozen=True)
class ResolvedCommandTarget:
    device_id: str
    transport: str
    endpoint: str
    channel: int | None
    unit_id: int | None
    generation: int
    profile_json: str
    mapping_json: str
    encoding_json: str
    config_json: str = field(repr=False)
    connection_json: str = "{}"

    @property
    def mapping(self):
        return json.loads(self.mapping_json)

    @property
    def encoding(self):
        return json.loads(self.encoding_json)

    @property
    def config(self):
        return json.loads(self.config_json)

    @property
    def connection(self):
        return json.loads(self.connection_json)


def current_target(device_id=None):
    target = _active.get()
    if target is not None and device_id is not None and str(device_id).upper() != target.device_id:
        raise ValueError("operation attempted to leave its resolved device target")
    return target


@contextmanager
def target_scope(target):
    existing = _active.get()
    if existing is not None and existing != target:
        raise ValueError("nested operation attempted to replace its resolved target")
    token = _active.set(target)
    try:
        yield target
    finally:
        _active.reset(token)

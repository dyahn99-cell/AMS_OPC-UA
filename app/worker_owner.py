"""Pure ownership contract for the private Python -> Node loopback worker.

This module does not import the runtime, open sockets, or start/stop processes.
The runtime must keep each owner with its actual Popen handle, never adopt a
listener by endpoint, and validate owned status before any device operation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
from pathlib import Path
import re
import secrets
from typing import Mapping


WORKER_PROTOCOL = "ams-worker-owner-v1"
TOKEN_HEADER = "X-AMS-Worker-Token"
INSTANCE_HEADER = "X-AMS-Worker-Instance"
FINGERPRINT_HEADER = "X-AMS-Worker-Fingerprint"


def worker_fingerprint(nodes_bytes: bytes, endpoint: str, password: str) -> str:
    """Hash exact node-file bytes, framed UTF-8 endpoint, and password digest.

    SHA256(protocol + NUL + uint64be(nodes length) + nodes bytes +
           uint64be(endpoint UTF-8 length) + endpoint UTF-8 +
           SHA256(password UTF-8).digest()).
    No JSON reserialization, newline conversion, or path identity is involved.
    """
    if not isinstance(nodes_bytes, bytes):
        raise TypeError("nodes_bytes must be bytes")
    if not isinstance(endpoint, str) or not endpoint:
        raise ValueError("endpoint must be a nonempty string")
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    endpoint_bytes = endpoint.encode("utf-8")
    digest = hashlib.sha256((WORKER_PROTOCOL + "\0").encode("ascii"))
    for value in (nodes_bytes, endpoint_bytes):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    digest.update(hashlib.sha256(password.encode("utf-8")).digest())
    return digest.hexdigest()


def _same_text(actual: object, expected: str) -> bool:
    return (
        isinstance(actual, str)
        and len(actual) == len(expected)
        and actual.isascii()
        and hmac.compare_digest(actual, expected)
    )


@dataclass(frozen=True)
class WorkerOwner:
    """One immutable launch identity; do not persist or log the token/password."""

    nodes_path: Path
    endpoint: str
    password: str = field(repr=False)
    port: int
    token: str = field(repr=False)
    instance_id: str
    fingerprint: str

    def __post_init__(self) -> None:
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("worker port must be an integer 1..65535")
        if not isinstance(self.endpoint, str) or not self.endpoint:
            raise ValueError("endpoint must be a nonempty string")
        if not isinstance(self.password, str):
            raise TypeError("password must be a string")
        if not isinstance(self.nodes_path, Path) or not self.nodes_path.is_absolute():
            raise ValueError("nodes_path must be an absolute Path")
        for value, length in ((self.token, 64), (self.instance_id, 32), (self.fingerprint, 64)):
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{%d}" % length, value) is None:
                raise ValueError("worker ownership credentials missing or invalid")

    @classmethod
    def create(cls, *, nodes_path: Path, endpoint: str, password: str, port: int) -> WorkerOwner:
        """Snapshot launch inputs and generate fresh credentials for each spawn.

        A node-file change between this read and the child's read causes startup
        fingerprint verification to fail closed, not acceptance of a stale map.
        """
        nodes_path = Path(nodes_path).resolve()
        fingerprint = worker_fingerprint(nodes_path.read_bytes(), endpoint, password)
        return cls(
            nodes_path=nodes_path,
            endpoint=endpoint,
            password=password,
            port=port,
            token=secrets.token_hex(32),
            instance_id=secrets.token_hex(16),
            fingerprint=fingerprint,
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def headers(self) -> dict[str, str]:
        """Fresh headers for every request, including /status and /shutdown.

        Use only base_url, disable redirects, and never forward these headers to
        another authority. Host is deliberately canonical, not localhost.
        """
        return {
            "Host": f"127.0.0.1:{self.port}",
            TOKEN_HEADER: self.token,
            INSTANCE_HEADER: self.instance_id,
            FINGERPRINT_HEADER: self.fingerprint,
        }

    def spawn_environment(self, base_env: Mapping[str, str]) -> dict[str, str]:
        """Copy parent env and pin the effective inputs, not mutable config defaults."""
        env = dict(base_env)
        env.update({
            "WORKER_PORT": str(self.port),
            "AMS_NODES_PATH": str(self.nodes_path),
            "OPCUA_ENDPOINT": self.endpoint,
            "AMS_PASSWORD": self.password,
            "AMS_WORKER_OWNER_TOKEN": self.token,
            "AMS_WORKER_INSTANCE_ID": self.instance_id,
            "AMS_WORKER_FINGERPRINT": self.fingerprint,
        })
        return env

    def validate_status(self, payload: object, *, expected_pid: int) -> bool:
        """Validate a successful non-redirected /status response for our live child.

        Caller must also check Popen.poll() is None and HTTP status is 200. This
        does not trust an arbitrary server simply because its endpoint matches.
        """
        if not isinstance(payload, Mapping):
            return False
        if type(expected_pid) is not int or expected_pid <= 0:
            return False
        if type(payload.get("pid")) is not int or payload["pid"] != expected_pid:
            return False
        return (
            payload.get("worker_protocol") == WORKER_PROTOCOL
            and _same_text(payload.get("worker_instance_id"), self.instance_id)
            and _same_text(payload.get("worker_fingerprint"), self.fingerprint)
            and payload.get("endpoint") == self.endpoint
        )

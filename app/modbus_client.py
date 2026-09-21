from __future__ import annotations

from dataclasses import dataclass
import socket
import struct
import threading
import time
from typing import Iterable


@dataclass(frozen=True)
class ModbusEndpoint:
    host: str
    port: int = 502
    unit_id: int = 1
    timeout_s: float = 1.5

    @property
    def key(self) -> tuple[str, int, int]:
        return self.host, self.port, self.unit_id

    @property
    def label(self) -> str:
        return f"{self.host}:{self.port}/unit/{self.unit_id}"


class ModbusTcpClient:
    """Endpoint-owned Modbus TCP client. Each request uses a fresh socket."""

    def __init__(self, endpoint: ModbusEndpoint):
        if not endpoint.host:
            raise ValueError("Modbus endpoint host is required")
        if not 1 <= endpoint.port <= 65535:
            raise ValueError("Modbus endpoint port must be 1..65535")
        if not 0 <= endpoint.unit_id <= 255:
            raise ValueError("Modbus unit_id must be 0..255")
        self.endpoint = endpoint
        self._lock = threading.RLock()
        self._transaction = 0

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("modbus connection closed")
            data += chunk
        return data

    def request(self, function: int, payload: bytes) -> bytes:
        with self._lock:
            self._transaction = (self._transaction % 0xFFFF) + 1
            transaction = self._transaction
            pdu = bytes([function]) + payload
            packet = struct.pack(">HHHB", transaction, 0, len(pdu) + 1, self.endpoint.unit_id) + pdu
            timeout = max(0.2, float(self.endpoint.timeout_s))
            with socket.create_connection((self.endpoint.host, self.endpoint.port), timeout=timeout) as sock:
                sock.settimeout(timeout)
                sock.sendall(packet)
                header = self._recv_exact(sock, 7)
                tid, protocol, length, response_unit = struct.unpack(">HHHB", header)
                if tid != transaction or protocol != 0 or response_unit != self.endpoint.unit_id or length < 2:
                    raise ValueError("invalid Modbus TCP response")
                response = self._recv_exact(sock, length - 1)
            if response[0] == (function | 0x80):
                raise ValueError(f"modbus exception 0x{response[1]:02X}")
            if response[0] != function:
                raise ValueError("unexpected Modbus function response")
            return response[1:]

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        if not 1 <= count <= 125:
            raise ValueError("Modbus read count must be 1..125")
        body = self.request(3, struct.pack(">HH", int(address), int(count)))
        if not body or body[0] != count * 2:
            raise ValueError("invalid Modbus register response length")
        return list(struct.unpack(">" + "H" * count, body[1:]))

    def write_registers(self, address: int, values: Iterable[int]) -> None:
        words = [int(value) & 0xFFFF for value in values]
        if not 1 <= len(words) <= 123:
            raise ValueError("Modbus write count must be 1..123")
        raw = struct.pack(">" + "H" * len(words), *words)
        body = self.request(16, struct.pack(">HHB", int(address), len(words), len(raw)) + raw)
        if len(body) != 4 or struct.unpack(">HH", body) != (int(address), len(words)):
            raise ValueError("invalid Modbus write acknowledgement")


class ModbusClientPool:
    def __init__(self):
        self._clients: dict[tuple[str, int, int], ModbusTcpClient] = {}
        self._lock = threading.RLock()

    def get(self, endpoint: ModbusEndpoint) -> ModbusTcpClient:
        with self._lock:
            client = self._clients.get(endpoint.key)
            if client is None or client.endpoint.timeout_s != endpoint.timeout_s:
                client = ModbusTcpClient(endpoint)
                self._clients[endpoint.key] = client
            return client

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "host": client.endpoint.host,
                    "port": client.endpoint.port,
                    "unit_id": client.endpoint.unit_id,
                    "timeout_s": client.endpoint.timeout_s,
                    "endpoint": client.endpoint.label,
                }
                for client in self._clients.values()
            ]

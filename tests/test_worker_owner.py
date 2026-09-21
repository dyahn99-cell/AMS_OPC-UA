"""Pure offline worker-owner tests: no runtime import, server, process or socket."""
import dataclasses
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app.worker_owner import (
    FINGERPRINT_HEADER,
    INSTANCE_HEADER,
    TOKEN_HEADER,
    WORKER_PROTOCOL,
    WorkerOwner,
    worker_fingerprint,
)


NODES = b'{"remotes":{"AMS01":{"read":{"flow":"ns=4;s=flow"}}}}\r\n'
ENDPOINT = "opc.tcp://mock.invalid:4840"
PASSWORD = "offline-secret-é"
# Same independent framing vector is checked by scripts/check_worker_offline.cjs.
FINGERPRINT = "0e0e80f00845681d981e7f1d38ba0c7132f23eb75d7db1e63aed7007bc208663"


class WorkerFingerprintTests(unittest.TestCase):
    def test_cross_language_exact_bytes_vector(self):
        self.assertEqual(worker_fingerprint(NODES, ENDPOINT, PASSWORD), FINGERPRINT)

    def test_fingerprint_covers_nodes_endpoint_and_password(self):
        variants = (
            worker_fingerprint(NODES + b" ", ENDPOINT, PASSWORD),
            worker_fingerprint(NODES.replace(b"\r\n", b"\n"), ENDPOINT, PASSWORD),
            worker_fingerprint(NODES.replace(b"flow", b"mode"), ENDPOINT, PASSWORD),
            worker_fingerprint(NODES, ENDPOINT + "/other", PASSWORD),
            worker_fingerprint(NODES, ENDPOINT, PASSWORD + "changed"),
        )
        self.assertTrue(all(value != FINGERPRINT for value in variants))
        self.assertEqual(len(set(variants)), len(variants))

    def test_frame_boundaries_prevent_ambiguous_concatenation(self):
        self.assertNotEqual(
            worker_fingerprint(b"abc", "def", "secret"),
            worker_fingerprint(b"abcd", "ef", "secret"),
        )

    def test_empty_password_is_explicit_not_a_default(self):
        self.assertNotEqual(
            worker_fingerprint(NODES, ENDPOINT, ""),
            worker_fingerprint(NODES, ENDPOINT, "admin"),
        )

    def test_fingerprint_rejects_coercion(self):
        for args in (("nodes", ENDPOINT, PASSWORD), (NODES, "", PASSWORD), (NODES, 1, PASSWORD), (NODES, ENDPOINT, None)):
            with self.subTest(args=args), self.assertRaises((TypeError, ValueError)):
                worker_fingerprint(*args)


class WorkerOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.nodes_path = Path(self.temp.name) / "nodes.json"
        self.nodes_path.write_bytes(NODES)
        self.owner = self.create_owner()

    def create_owner(self, **overrides):
        args = dict(nodes_path=self.nodes_path, endpoint=ENDPOINT, password=PASSWORD, port=7100)
        args.update(overrides)
        return WorkerOwner.create(**args)

    def status(self, **overrides):
        payload = {
            "worker_protocol": WORKER_PROTOCOL,
            "worker_instance_id": self.owner.instance_id,
            "worker_fingerprint": self.owner.fingerprint,
            "endpoint": self.owner.endpoint,
            "pid": 4242,
            "connected": False,
        }
        payload.update(overrides)
        return payload

    def test_each_spawn_gets_fresh_immutable_identity(self):
        other = self.create_owner()
        self.assertNotEqual(self.owner.token, other.token)
        self.assertNotEqual(self.owner.instance_id, other.instance_id)
        self.assertEqual(self.owner.fingerprint, other.fingerprint)
        self.assertRegex(self.owner.token, r"^[0-9a-f]{64}$")
        self.assertRegex(self.owner.instance_id, r"^[0-9a-f]{32}$")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.owner.token = "changed"

    def test_owner_creation_performs_no_transport_or_process_action(self):
        with mock.patch("socket.socket", side_effect=AssertionError("socket forbidden")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("process forbidden")):
            owner = self.create_owner()
            self.assertEqual(owner.fingerprint, FINGERPRINT)
            self.assertTrue(owner.validate_status(self.status(
                worker_instance_id=owner.instance_id,
            ), expected_pid=4242))

    def test_headers_bind_all_identity_fields_and_canonical_loopback_host(self):
        self.assertEqual(self.owner.headers(), {
            "Host": "127.0.0.1:7100",
            TOKEN_HEADER: self.owner.token,
            INSTANCE_HEADER: self.owner.instance_id,
            FINGERPRINT_HEADER: FINGERPRINT,
        })
        headers = self.owner.headers()
        headers[TOKEN_HEADER] = "mutated"
        self.assertEqual(self.owner.headers()[TOKEN_HEADER], self.owner.token)
        self.assertEqual(self.owner.base_url, "http://127.0.0.1:7100")
        self.assertNotIn(self.owner.token, self.owner.base_url)

    def test_spawn_environment_pins_snapshotted_inputs_and_copies_parent(self):
        original = {
            "AMS_CONFIG_PATH": "other-config.json", "AMS_PASSWORD": "stale",
            "OPCUA_ENDPOINT": "wrong", "AMS_WORKER_OWNER_TOKEN": "stale", "KEEP": "1",
        }
        before = dict(original)
        env = self.owner.spawn_environment(original)
        self.assertEqual(original, before)
        self.assertEqual(env["AMS_CONFIG_PATH"], "other-config.json")
        self.assertEqual(env["KEEP"], "1")
        self.assertEqual(env["WORKER_PORT"], "7100")
        self.assertEqual(env["AMS_NODES_PATH"], str(self.nodes_path.resolve()))
        self.assertEqual(env["OPCUA_ENDPOINT"], ENDPOINT)
        self.assertEqual(env["AMS_PASSWORD"], PASSWORD)
        self.assertEqual(env["AMS_WORKER_OWNER_TOKEN"], self.owner.token)
        self.assertEqual(env["AMS_WORKER_INSTANCE_ID"], self.owner.instance_id)
        self.assertEqual(env["AMS_WORKER_FINGERPRINT"], FINGERPRINT)

    def test_node_file_change_does_not_mutate_existing_owner(self):
        self.nodes_path.write_bytes(NODES + b" ")
        self.assertEqual(self.owner.fingerprint, FINGERPRINT)
        self.assertEqual(self.owner.spawn_environment({})["AMS_WORKER_FINGERPRINT"], FINGERPRINT)
        self.assertNotEqual(self.create_owner().fingerprint, self.owner.fingerprint)

    def test_no_credentials_in_repr_or_status(self):
        self.assertNotIn(self.owner.token, repr(self.owner))
        self.assertNotIn(PASSWORD, repr(self.owner))
        self.assertNotIn(self.owner.token, json.dumps(self.status()))
        self.assertNotIn(PASSWORD, json.dumps(self.status()))

    def test_status_identity_is_not_connection_state(self):
        self.assertTrue(self.owner.validate_status(self.status(), expected_pid=4242))
        self.assertTrue(self.owner.validate_status(self.status(connected=True), expected_pid=4242))

    def test_status_rejects_unowned_or_mismatched_payload(self):
        for payload in (None, [], "ok", {}, {"endpoint": ENDPOINT},
                        self.status(worker_protocol="old"),
                        self.status(worker_instance_id="c" * 32),
                        self.status(worker_fingerprint="c" * 64),
                        self.status(endpoint=ENDPOINT + "/other"),
                        self.status(pid=999), self.status(pid="4242"), self.status(pid=True),
                        self.status(worker_instance_id="é" * 32),
                        self.status(worker_fingerprint="\ud800" * 64),
                        self.status(worker_fingerprint=[FINGERPRINT])):
            with self.subTest(payload=payload):
                self.assertFalse(self.owner.validate_status(payload, expected_pid=4242))
        for field in ("worker_protocol", "worker_instance_id", "worker_fingerprint", "pid", "endpoint"):
            payload = self.status()
            del payload[field]
            self.assertFalse(self.owner.validate_status(payload, expected_pid=4242))

    def test_status_requires_actual_expected_child_pid(self):
        for pid in (None, True, 0, -1, "4242", 4242.0, 999):
            with self.subTest(pid=pid):
                self.assertFalse(self.owner.validate_status(self.status(), expected_pid=pid))
        with self.assertRaises(TypeError):
            self.owner.validate_status(self.status())

    def test_invalid_ports_fail_closed(self):
        for port in (True, "7100", 7100.0, 0, -1, 65536):
            with self.subTest(port=port), self.assertRaises(ValueError):
                self.create_owner(port=port)

    def test_missing_node_file_fails_closed(self):
        with self.assertRaises(FileNotFoundError):
            self.create_owner(nodes_path=Path(self.temp.name) / "missing.json")

    def test_invalid_direct_owner_values_fail_closed(self):
        for values in ({"token": "abc"}, {"instance_id": "z" * 32},
                       {"fingerprint": ""}, {"nodes_path": Path("relative.json")}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                dataclasses.replace(self.owner, **values)


if __name__ == "__main__":
    unittest.main()

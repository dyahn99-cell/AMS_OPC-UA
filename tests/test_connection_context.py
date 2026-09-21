import concurrent.futures
import threading
import time
import unittest

from app.connection_context import ConnectionContextManager
from app.device_hub import DeviceProfile


class ConnectionContextTests(unittest.TestCase):
    def test_profiles_on_same_endpoint_share_serial_lock(self):
        manager = ConnectionContextManager()
        first = DeviceProfile("AMS01", "One", "remote", "modbus", endpoint="192.168.0.1:502")
        second = DeviceProfile("AMS02", "Two", "remote", "modbus", endpoint="192.168.0.1:502")
        active = 0
        maximum = 0
        guard = threading.Lock()

        def operation():
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.02)
            with guard:
                active -= 1
            return {"ok": True}

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda profile: manager.run(profile, "read", operation), [first, second]))
        self.assertEqual(maximum, 1)
        self.assertEqual(manager.snapshot(first)["attempts"], 2)

    def test_endpoints_keep_failure_state_isolated(self):
        manager = ConnectionContextManager()
        failed = DeviceProfile("AMS01", "One", "remote", "modbus", endpoint="gateway-a:502")
        healthy = DeviceProfile("AMS02", "Two", "remote", "modbus", endpoint="gateway-b:502")
        manager.run(failed, "read", lambda: {"ok": False, "error": "timeout"}, is_success=lambda result: result["ok"])
        manager.run(healthy, "read", lambda: {"ok": True}, is_success=lambda result: result["ok"])
        self.assertFalse(manager.snapshot(failed)["connected"])
        self.assertEqual(manager.snapshot(failed)["consecutive_failures"], 1)
        self.assertTrue(manager.snapshot(healthy)["connected"])
        self.assertEqual(manager.snapshot(healthy)["consecutive_failures"], 0)

    def test_write_has_no_implicit_retry(self):
        manager = ConnectionContextManager()
        profile = DeviceProfile("AMS01", "One", "remote", "modbus", endpoint="gateway:502")
        calls = 0

        def failing_write():
            nonlocal calls
            calls += 1
            raise TimeoutError("write timeout")

        with self.assertRaises(TimeoutError):
            manager.run(profile, "write", failing_write)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()

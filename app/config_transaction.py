"""Configuration admission without holding the configuration lock during device I/O."""
from contextlib import contextmanager
from contextvars import ContextVar
import threading


def reject_new_quarantine(previous, candidate, *, identity, label):
    """Allow existing raw quarantine to survive unrelated repairs, never grow it."""
    for error in candidate:
        if not any(error.get(identity) == old.get(identity)
                   and error.get("raw") == old.get("raw")
                   and error.get("legacy_raw") == old.get("legacy_raw")
                   and error.get("error") == old.get("error") for old in previous):
            raise ValueError(f"{label} {error.get(identity)}: {error.get('error')}")


class ConfigurationAdmission:
    def __init__(self):
        self._condition = threading.Condition(threading.RLock())
        self._transition_lock = threading.Lock()
        self._transitioning = False
        self._active = 0
        self._closed = False
        self._lease = ContextVar("configuration_admission_lease", default=None)

    @contextmanager
    def command(self, snapshot):
        existing = self._lease.get()
        if existing is not None:
            yield existing
            return
        with self._condition:
            if self._closed or self._transitioning:
                raise ValueError("runtime stopping or configuration transition in progress; retry the command")
            frozen = snapshot()
            self._active += 1
        token = self._lease.set(frozen)
        try:
            yield frozen
        finally:
            self._lease.reset(token)
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def current(self):
        return self._lease.get()

    def reopen(self):
        with self._condition:
            if self._active or self._transitioning:
                raise RuntimeError("cannot reopen admission with active operations")
            self._closed = False

    def close(self):
        with self._condition:
            self._closed = True

    def drain(self):
        if self.current() is not None:
            raise RuntimeError("cannot drain own operation")
        with self._transition_lock:
            with self._condition:
                while self._active:
                    self._condition.wait()

    @contextmanager
    def bootstrap(self):
        if self.current() is not None or not self._transition_lock.acquire(blocking=False):
            raise ValueError("cannot initialize while a runtime operation is active")
        try:
            with self._condition:
                if self._active or self._transitioning:
                    raise ValueError("cannot initialize while a runtime operation is active")
                self._transitioning = True
            try:
                yield
            finally:
                with self._condition:
                    self._transitioning = False
                    self._condition.notify_all()
        finally:
            self._transition_lock.release()

    @contextmanager
    def transition(self):
        # Never wait for the calling command's own lease. State-only writes do
        # not enter this method; a command cannot change its physical route.
        if self.current() is not None:
            raise ValueError("cannot change device routing from an active command")
        with self._transition_lock:
            with self._condition:
                if self._closed:
                    raise ValueError("runtime stopping")
                self._transitioning = True
                try:
                    while self._active:
                        self._condition.wait()
                except BaseException:
                    self._transitioning = False
                    self._condition.notify_all()
                    raise
            try:
                yield
            finally:
                with self._condition:
                    self._transitioning = False
                    self._condition.notify_all()

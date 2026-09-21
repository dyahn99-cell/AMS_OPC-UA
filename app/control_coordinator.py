"""One lifespan-owned collector. Stop joins real work rather than cancelling it."""
import logging
import threading
import time


class ControlCoordinator:
    def __init__(self, collect, save, save_interval, *, interval=1.0):
        self.collect = collect
        self.save = save
        self.save_interval = save_interval
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            raise RuntimeError("coordinator already started")
        self._thread = threading.Thread(target=self._run, name="ams-collector", daemon=False)
        self._thread.start()

    def request_stop(self):
        self._stop.set()

    def join(self):
        if self._thread is not None:
            self._thread.join()

    def _run(self):
        last_save = time.monotonic()
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                payload = self.collect()
                if not self._stop.is_set() and time.monotonic() - last_save >= self.save_interval():
                    self.save(payload)
                    last_save = time.monotonic()
            except Exception:
                logging.getLogger(__name__).exception("collection/save cycle failed")
            self._stop.wait(max(0.0, self.interval - (time.monotonic() - started)))

import logging
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

import bridge


def configure_logging() -> None:
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(getattr(handler, "_ams_dashboard", False) for handler in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console._ams_dashboard = True
        rotating = RotatingFileHandler(
            log_dir / "server.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        rotating.setFormatter(formatter)
        rotating._ams_dashboard = True
        root.addHandler(console)
        root.addHandler(rotating)


def open_dashboard(port: int) -> None:
    time.sleep(1.2)
    webbrowser.open(f"http://127.0.0.1:{port}/dashboard")


def main() -> None:
    bridge.initialize_runtime()
    configure_logging()
    port = int(bridge.config_store.get("server_port", 8000) or 8000)
    threading.Thread(target=open_dashboard, args=(port,), daemon=True).start()
    uvicorn.run(bridge.app, host="127.0.0.1", port=port, proxy_headers=False, log_level="info", log_config=None)


if __name__ == "__main__":
    main()

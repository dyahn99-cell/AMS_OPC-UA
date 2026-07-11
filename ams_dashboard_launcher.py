import threading
import time
import webbrowser

import uvicorn

import bridge


def open_dashboard(port: int) -> None:
    time.sleep(1.2)
    webbrowser.open(f"http://127.0.0.1:{port}/dashboard")


def main() -> None:
    port = int(bridge.config_store.get("server_port", 8000) or 8000)
    threading.Thread(target=open_dashboard, args=(port,), daemon=True).start()
    uvicorn.run(bridge.app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()

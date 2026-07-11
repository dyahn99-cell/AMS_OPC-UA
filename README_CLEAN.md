# AMS Dashboard

This folder is the maintained backend layout for the AMS Dashboard demo.

## Goal

Keep the existing dashboard API contract while making the backend easier to read,
package, and extend.

This folder is the active workspace. Older experimental folders are not part of
the runtime path.

## Runtime Shape

```text
bridge.py              Thin compatibility entrypoint for uvicorn/PyInstaller
app/runtime.py         Current FastAPI app and runtime implementation
app/main.py            FastAPI app entrypoint
app/config.py          Config loading/saving facade
app/state.py           Shared runtime state/cache facade
app/worker_client.py   Node OPC UA worker lifecycle and HTTP facade
app/ams_web.py         AMS web-server login/control facade
app/data_parser.py     Hex and OPC UA data parsing facade
app/energy.py          Energy and accumulated-flow calculations facade
app/database.py        SQLite/history/CSV facade
app/schedules.py       Schedule storage/execution facade
app/control.py         OPC UA demo-control facade
worker.js              Node OPC UA worker
nodes.json             Single source for OPC UA read/write node IDs
```

## Double-Click BAT Files

For demo use, these are the main files to click:

- `START_HERE_SETUP.bat`: install required Python packages.
- `START_DASHBOARD.bat`: start the dashboard server and open the browser.
- `CHECK_CODE.bat`: quick syntax/import check before packaging or sharing.
- `build_exe.bat`: build `dist\AMS_Dashboard.exe`.

## Responsibilities

- Python/FastAPI: dashboard hosting, API, DB, schedule, CSV, web-server control.
- Node worker: OPC UA read/write, remote cache, reconnect behavior.
- `nodes.json`: AMS00/AMS01 read nodes and OPC UA control write nodes.
- Dashboard HTML: current UI for demo and multi-monitor views.
- IODD library: uploaded XML files are stored in `iodd_library/` and assigned
  to Port 4 per AMS remote.
- IODD decoding: Port 4 keeps raw HEX visible and, when an IODD is assigned,
  uses a generic process-data field parser until a real device IODD is tuned.

## Preserved API

Existing dashboard routes are intentionally preserved, including:

- `/dashboard`
- `/ws/live`
- `/api/status`
- `/api/worker/status`
- `/api/nodes/status`
- `/api/remotes/status`
- `/api/control/*`
- `/api/config/*`
- `/api/history*`
- `/api/schedules*`

## Stability Changes

- Python OPC UA packages are no longer required.
- OPC UA node IDs are centralized in `nodes.json` for both Python and Node.
- OPC UA reads and writes go through `worker.js`.
- Worker startup is logged to `logs/worker.out.log` and `logs/worker.err.log`.
- Worker `/status` becomes available before heavy OPC UA connection loading.
- Worker read/write timeouts are explicit.
- Runtime cache reads use locks/snapshots.
- Port 4 can keep raw HEX visible while an uploaded IODD file is assigned for
  generic process-data decoding.

## Verification Without Device

```bat
py -3.12 -m py_compile bridge.py app\runtime.py app\main.py
vendor\node\node.exe --check worker.js
py -3.12 -c "import bridge; print(bridge.app)"
```

Device validation still needs actual AMS hardware/network.

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
- Demo accumulation advances from elapsed wall time under a lock, so browser
  connection count cannot inflate usage.
- Demo mode skips OPC UA worker polling; live worker status is cached briefly.
- Configuration, runtime state, schedules, and IODD index writes use atomic
  file replacement with backup recovery.
- Frequently changing accumulated-flow state is stored in `runtime_state.json`
  instead of rewriting `config.json` on every save cycle.
- SQLite uses WAL mode, a busy timeout, and a `(remote_id, timestamp)` index.
- Raw CSV downloads stream rows instead of loading the full export into memory.
- Aggregated history is limited to 20,000 periods and raw CSV to 366 days.
- Worker and server logs rotate at 5 MB with three backups.
- The dashboard launcher restarts after an abnormal server exit.
- Port 4 can keep raw HEX visible while an uploaded IODD file is assigned for
  generic process-data decoding.

## Verification Without Device

Run with an already-provisioned Python environment (3.12 or newer); the checker
never installs packages. `CHECK_CODE.bat` selects `py -3.12`, then `python`.

```bat
python scripts\check_offline.py
rem Established regressions only; deliberately omits the stage-1 contracts:
python scripts\check_offline.py --regressions-only
```

The default command separately reports `REGRESSIONS_SUMMARY` (the established
63 tests, including the nine-fix regressions) and `STAGE1_CONTRACTS_SUMMARY` (four
actual-module reproductions: persisted-profile recovery, explicit target,
disabled intent, and OPC UA endpoint guarding). At the stage-0 handoff those
four desired contracts still fail; they are not xfailed, skipped, or counted as
baseline failures. The default command exits nonzero until both groups and the
safety checks pass. `--regressions-only` is not a claim that stage 1 is complete.
Existing AST-extracted tests remain supplementary evidence, not integration tests.

The checker compiles Python in memory, copies only Python source/tests into a
fresh temporary checkout, creates synthetic inputs there, and imports the actual
runtime and bridge **only after** installing its guards. It never copies or parses
operational config, nodes, passwords, schedules, DBs, logs, or IODDs into the test
process as fixtures. Original artifacts are read as opaque bytes only for the
before/after integrity comparison. Do not use `import bridge` or direct runtime
`unittest` discovery in the live checkout; runtime test imports require the guarded
helper. Temporary files are removed after both passing and failing tests.

Fixture assumptions are explicit in `tests/offline_fixtures.py`: reserved `.invalid`
endpoints, fresh empty state/history, CH1/CH2 EXA1 plus CH3-12 reservations and CH13
remote I/O with advanced diagnostics, process byte swap **off**, accumulator word
swap **on**, and a frozen history date of **2026-09-12 10:00:00**. Individual swap
tests still exercise both values. This makes legacy topology/byte-order/date
assumptions reproducible without borrowing the site's current config. Port 4 PDin
remains **big-endian**, with `00 00 00 00 0F A0 30 00` decoding to flow **4000**.

Safety output reports the socket/DNS/process/outside-write/SQLite/thread guard
selfchecks, blocked attempts, and original artifact changes. The SHA-256 +
size/mtime inventory covers active app/test/script source, root entrypoints and
manifests, text assets, config/nodes/runtime-state/schedule files and their backups,
DB/log/IODD directories, and Git index/HEAD. It excludes `node_modules`, vendor and
build outputs, bytecode, binary assets, and source backups: **not a full-repository
integrity proof**. Before and after inventories run once each per verification.
A guarded urllib3 IPv6-availability socket-creation probe during dependency import
is separately reported (no socket is created); unexpected test-phase I/O attempts
make the checker fail even when application code catches the exception.

These are accidental-I/O guards for trusted tests, **not a security sandbox**.
They do not contain malicious code or all native-library/inherited-handle I/O.
SQLite connections are restricted to temporary paths or memory; extension loading,
ATTACH (including VACUUM INTO), and storage-directory pragmas are blocked. Existing
in-memory ThreadPoolExecutor tests are allowed; arbitrary background threads are
not. No server, lifespan scheduler, worker, or hardware transport is started.

ASGI/lifespan integration with mock transports, Node fake-session checks, browser
fake-fetch/clock checks, and launcher/frozen-package smoke remain separate future
verification stages and appear under `NOT_RUN`; this Python command does not
claim to cover them. If needed, Node syntax is a separate explicit command
(`vendor\node\node.exe --check worker.js`), not part of the guarded Python run.
Device compatibility and physical control safety still require approved hardware
validation.

## Demo History Data

For demos without live AMS hardware, generate multi-day history for the
DATA / ENERGY charts:

- Double-click `SEED_DEMO_DATA.bat`, or
- Run:

```bat
py -3.12 scripts\seed_demo_data.py --days 14 --interval-s 60 --remotes AMS00,AMS01 --replace-range
```

Default seed covers 14 days at 60-second samples for AMS00 and AMS01, with
working-hours demand curves, lunch dips, and energy totals derived from
`config.json`.

Seeded rows are marked so they are easy to separate from live hardware data:

- `ams_status = DEMO`
- `diagnostic` starts with `DEMO SEED`
- DATA / ENERGY query UI shows a **DEMO DATA** badge when the range is synthetic



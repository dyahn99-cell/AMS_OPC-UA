# Device configuration v2 — first increment

Base: a917e5e; isolated branch codex/device-config-v2.

Implemented a pure model policy in app/device_models.py. EXA1 capabilities and
36/18 process layout are defined there. Adapters intersect model permissions
with transport support, and reject unsupported commands/settings before I/O.
Snapshots publish model labels and capabilities; device navigation and AMS
target lists consume those capabilities. IDs and aliases are unchanged.

Compatibility boundary: profiles without device_kind retain the existing AMS
contract. Explicit unknown, empty, IO-Link and unimplemented model kinds cannot
write AMS outputs/settings. This is configured support, not hardware identity
verification. No discovered identity is claimed.

EXW1-RL automatic SMI discovery, firmware checks, port modes, lengths, byte order,
Y-branch topology and generic sensor rendering are NOT implemented in this step.
No inferred register map or duplicated manual IO-Link configuration was added.
Existing screens remain available. No server restart or hardware output test.

Validation: run scripts/check_offline.py with --regressions-only and a targeted
--pattern. New test_device_models.py covers legacy compatibility, transport
limits and zero output-service dispatch for unsupported kinds on four adapters.
The pre-existing full-suite failures documented in the snapshot remain outside
this increment; targeted success does not imply a green full suite.

Verified results (2026-09-28):
- New model policy tests: 3 passed (unsupported-kind cases cover four adapters).
- test_device_*.py: passed, including existing DeviceHub tests.
- test_review_regressions.py: 10 passed.
- check_panel_commands.cjs and navigation JS syntax: passed.
- test_exw1_topology.py: 2 passed, 2 failed. Reproduced both failures on an
  untouched git archive of a917e5e: reserved CH03..12 are promoted to EXA1,
  while tests still expect dummy slots and only three profiles.
- All guarded runs: no unexpected I/O attempts; scoped source integrity intact.
- Browser rendering and full suite were not run.

# Development snapshot — 2026-09-22

Checkpoint before configuration-driven remote device development. This is not a validated production release.

Includes accumulated control/schedule/history safeguards, connected-remote filtering, overview grid options, device navigation beta, tabbed fixed-size connection settings, channel/alias labels, and session-only Gemini key registration. Backend was restarted on September 22; hardware output verification remains outstanding.

Recent checks: panel-command regression and JavaScript syntax passed; isolated diagnostics-key unit test passed; channel/alias display checks passed. Browser checks covered settings tabs, fixed modal bounds, and sidebar placement. Brutal-mode selected navigation contrast was corrected, but final selected-state browser verification was interrupted.

The full regression suite is not green. See REVIEW_FIXES_2026-09-21.md for prior results; the latest offline harness also reported four existing stage-1 contract failures. An initial diagnostics test required an unavailable TestClient dependency and was replaced with a passing isolated endpoint unit test.

EXW1-RL configuration discovery, generic channel model definitions, and reusable per-port controls are planned, not implemented. Current channel aliases preserve internal IDs; changing a label does not add support for new hardware.

Local configuration, credentials, databases, logs, and timestamped backups are excluded. Use config.example.json for setup.

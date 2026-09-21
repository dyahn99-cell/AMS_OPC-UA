# Remote settings integration review

## Verified hardware support

SMC PFxx-OMA1007, Web Server connection, describes selecting individual remote AMS units from the base web server navigation. Older revision B page 44 explicitly shows remote 001 and 002 Air Management Hub entries. This confirms a remote UI exists, not the private HTTP wire format.

Sources:
- https://www.smcworld.com/assets/manual/en-jp/files/PFxx-OMA1007.pdf
- https://www.smcworld.com/upfiles/manual/en-jp/files/PFxx-OMA1007.pdf

## Current application

`_read_web_settings_direct` uses fixed request instances and a fixed request payload. `_write_web_settings_direct` uses fixed instances and trigger 33026. Neither accepts a remote ID or channel. `ams_channel` is used by process-data reads (0x8500 + channel); this is not evidence for the settings request format.

OPC UA remote settings remain blocked until that format is verified. Base settings retain their existing common web path. EXW1-BMTAC Modbus services remain a separate route.

## Required evidence before enabling writes

Capture the network requests when selecting Base, remote 001 and remote 002 in the AMS web UI and opening System Parameter/Sensor settings. Compare URL, query, payload, response and selected-channel state. Do not infer offsets from process data or OPC UA nodes. Read-only page navigation may itself issue POST requests; capture and inspect before replaying them. Remove session cookies, passwords and CSRF values from shared captures.

If the web server maintains a shared selected-channel buffer, selection + read/write + readback must be serialized per web endpoint. Each result must include device ID and channel. A reply for an earlier selection must never update the new selection. Enable writes only after target-specific readback is confirmed.

## Still open

- Multiple independent OPC UA server sessions.
- Device-level manual/DIO/schedule ownership and PLC interaction.
- Historical sample completeness and existing alias duplicate audit (do not delete historical data automatically).
- Dedicated IO, offline diagnostics and settings navigation.

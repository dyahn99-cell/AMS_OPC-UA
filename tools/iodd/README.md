# SMC IODD offline review and widgets

Entry point: outputs/iodd/all-widgets.html. No server or device connection is required.
The supplied archive contains 41 packages, 215 device identities and 239 definitions.
Every revision remains explicit; no latest-version inference occurs.

## Rebuild

From the repository root, after catalog.json and product-library.json exist:

```text
python tools/iodd/build_engineering_rules.py
python tools/iodd/expand_engineering_rules.py
python tools/iodd/build_diagnostic_profiles.py
python tools/iodd/audit_all_products.py
python tools/iodd/build_all_widgets.py
node scripts/check_iodd_widgets.cjs
node scripts/check_iodd_engineering.cjs
node scripts/check_all_iodd_widgets.cjs
node scripts/check_iodd_review.cjs
```

To recreate the source inventory:

```text
python tools/iodd/build_catalog.py <archive.zip> outputs/iodd/catalog.json
python tools/iodd/organize_library.py outputs/iodd/catalog.json <archive.zip> outputs/iodd/product-library.json
```

fetch_manual_index.py retrieves the official public SMC EU manual index.
fetch_review_manuals.py caches the selected official PDFs, SHA-256 and PDF-page text.
PDFium extraction is serialized to support rotated pages safely. Cached PDFs are reused.
manual_review_profiles.json contains authored findings, PDF page references and open issues.
These review profiles must not be inferred from model prefixes or download success.

## Supported scope

326 exact-definition/item conversion rules across 129 definitions are cross-checked against
manual coefficients and IODD presentation attributes. Four conflicting coefficients are
excluded. Engineering units require manual V_Unit confirmation; numeric, gauge and trend
views switch together. Acyclic fields retain their own Index/Subindex binding.
All 11,217 parsed fields can be inspected through common read-only/mock widgets.
Boolean labels preserve device semantics, including true meaning Disable.

Complex values and standard references remain unresolved. Diagnostic-dependent validity,
parameter dependencies, device commands, byte decoding and operational transport integration
are not implemented. Manual coverage means dashboard-relevant sections, not complete
per-parameter certification. Historical definitions remain independently selectable.

See outputs/iodd/MANUAL_REVIEW.md and FULL_PRODUCT_REVIEW.md for exact scope and exclusions.
Browser visual QA is incomplete: local-file navigation was blocked by browser security policy.
The Node checks use a mock DOM and do not substitute for browser layout verification.

## Device composition

Run `node tools/iodd/build_device_dashboards.cjs` to export all 239 exact-version dashboard definitions and 432 PD layout compositions. Run `node scripts/check_iodd_dashboard.cjs` to verify complete field coverage, no mixed layouts, valid widget views, and disabled writes. `build_all_widgets.py` embeds the same shared composition module into the gallery. Conditional PD layouts require manual selection; all dashboard widgets start with null samples. Groups use source, datatype and access rights, not inferred parameter semantics. Unknown access rights stay in settings definitions with writes disabled. This does not implement acquisition, freshness, command semantics or hardware diagnostic validity.

## EXW1-RL offline setup

The gallery includes a single-master manual configuration editor. See outputs/iodd/MASTER_CONFIGURATION.md for official evidence, limits and persistence scope. Validate with `node scripts/check_iodd_master.cjs`. The runtime topology and transport are not modified.

## PD byte-image stage

`node scripts/check_iodd_pd.cjs` verifies the pure decoder and reviewed ISE70/PF3W diagnostics. The packet lab accepts a manual full-master HEX input image. See outputs/iodd/PD_DECODER.md for the exact input contract and unsupported cases. It does not read or write hardware.

## Diagnostic and injected-reader increment

37 exact definitions / 155 layouts now have reviewed diagnostics. Run `node scripts/check_iodd_diagnostics.cjs` and `node scripts/check_iodd_register_input.cjs`. Pressure and older PF3W definitions require explicit V_diAG=1 confirmation; a clear diagnostic bit alone is insufficient. The register adapter accepts an injected read function and confirmed mapping; it does not provide a live Modbus client or infer addresses.

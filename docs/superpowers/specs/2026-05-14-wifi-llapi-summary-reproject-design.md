# WiFi LLAPI Summary Reproject Design

## Context

`wifi_llapi` already emits Excel, Markdown, JSON, and HTML report artifacts. The Excel
template now includes a `Summary` sheet, but its formulas and the Markdown/HTML/JSON
summary projections do not yet share one classification model.

This change defines a shared Hybrid summary model and a one-time offline reproject flow
for an already completed full run. The first input run is:

`plugins/wifi_llapi/reports/20260505_DUT-FW-VER_wifi_LLAPI_20260505T221246480726/20260505_DUT-FW-VER_wifi_LLAPI_20260505T221246480726.json`

No live DUT/STA/serialwrap test execution is in scope for the first implementation.

## Goals

1. Reproject the selected full-run JSON into a new report folder without modifying the
   original run folder.
2. Produce refreshed `.xlsx`, `.md`, `.html`, and `.json` artifacts using one shared
   summary model.
3. Preserve raw runtime band verdicts in `Wifi_LLAPI!I/J/K`.
4. Write fail reasoning into `Wifi_LLAPI!M`.
5. Render Hybrid statistics by band and major WiFi feature category.
6. Fail fast when the Excel template does not match the expected sheets and columns.

## Non-Goals

1. Do not rerun `testpilot wifi_llapi`.
2. Do not change case YAML semantics.
3. Do not alter the original `20260505T221246480726` artifact directory.
4. Do not treat every runtime `Fail` as a criteria failure.
5. Do not remove `Not Supported` or `Skip` as explicit summary buckets.

## Output Isolation

The reproject command or helper creates a new report folder under
`plugins/wifi_llapi/reports/`, for example:

`20260505_DUT-FW-VER_wifi_LLAPI_20260505T221246480726_summary_reproject_<timestamp>/`

The folder contains:

- `<folder_name>.xlsx`
- `<folder_name>.md`
- `<folder_name>.html`
- `<folder_name>.json`

The source JSON is read-only input. Existing report folders are not overwritten.

## Summary Categories

The primary Summary table aggregates by band and major object category:

- `WiFi.AccessPoint`
- `WiFi.EndPoint`
- `WiFi.Radio`
- `WiFi.SSID`
- `WiFi.wps_DefParam`
- `WiFi.Other`

`WiFi.Other` includes remaining WiFi families such as DataElements, DaemonMgt,
Capabilities, and other template object prefixes not covered by the five primary
categories. Detailed data can still retain the original object prefix.

## Band Bucket Rules

For each case and each band:

- `Pass`: raw band verdict is `Pass`.
- `Fail`: only clear pass criteria mismatch, such as evaluate-phase
  `pass_criteria not satisfied` or an equivalent criteria mismatch reason.
- `To be confirmed`: environment/configuration/session failures, inconclusive results,
  retry paths that did not reach valid criteria verification, and step command errors
  that do not clearly prove criteria mismatch.
- `Not Supported`: raw band verdict is explicitly `Not Supported`, `not_supported`,
  or an equivalent supported spelling.
- `Skip`: raw band verdict is explicitly `Skip` or `Skipped`.
- `N/A`: retained in details, but excluded from pass/fail/to-be-confirmed totals.

The raw `Wifi_LLAPI!I/J/K` cells remain the original runtime verdicts from JSON.
The summary model is a projection layer; it does not rewrite evidence.

## Fail Reasoning

`Wifi_LLAPI!M` stores a concise fail reasoning string for each reprojected case. The
reason should prefer structured runtime fields in this order:

1. `failure_snapshot.reason_code`
2. `failure_snapshot.comment`
3. `failure_snapshot.phase`
4. `diagnostic_status`
5. `comment`

The value should be compact enough for Excel review while preserving why a raw `Fail`
was classified as `Fail` or `To be confirmed`.

## Shared Summary Model

Add a reusable Python summary model used by Excel, Markdown, HTML, and JSON projection.
The model reads:

- case id
- source row
- raw band verdicts
- diagnostic status
- comment
- failure snapshot
- template object prefix by source row

The model emits:

- per-case band classification
- fail reason
- band/category summary counts
- diagnostic sub-counts, including env/config/inconclusive counts that were classified
  into `To be confirmed`
- raw verdict totals for traceability

This avoids separate Excel, Markdown, and HTML implementations drifting over time.

## Excel Template Validation

Before reprojecting or generating live summaries, validate the template and fail fast on
structural mismatch. Required checks:

- workbook has `Summary` and `Wifi_LLAPI` sheets
- `Wifi_LLAPI` expected columns exist:
  - object: `A`
  - LLAPI support: `E`
  - result columns: `I/J/K`
  - tester: `L`
  - comment/fail reason: `M`
- result headers resolve to `WiFi 5G`, `WiFi 6G`, and `WiFi 2.4G`
- `Summary` has the required summary headers:
  - module
  - object category
  - total items
  - tested items
  - pass
  - fail
  - to be confirmed
  - not supported
  - skip
  - pass rate
  - progress
- Summary rows keep the template-owned Hybrid category layout, formulas, styles, merged
  ranges, and percent number formats. Runtime/report projection must not delete or
  regenerate this sheet.
- Summary Pass Rate formulas count only confirmed pass/fail outcomes:
  `Pass / (Pass + Fail)`. `To be confirmed` is tracked in its own column and is
  intentionally excluded from the pass-rate denominator.

If validation fails, stop and report the exact sheet/cell/header mismatch. Do not emit a
partially trusted summary.

## Report Projection

The reproject flow:

1. Load the selected full-run JSON.
2. Validate the template workbook.
3. Copy the template into a new isolated report folder.
4. Fill `Wifi_LLAPI!G/H/I/J/K/L/M` from JSON case data:
   - `I/J/K` keep raw band verdicts.
   - `M` receives fail reasoning.
   - hidden `N/O/P` receive projected summary buckets so env/setup/counter-zero
     raw `Fail` results are counted as `To be confirmed`, while pass-criteria
     mismatch remains `Fail`.
5. Leave the `Summary` sheet untouched so its template formulas calculate from
   `Wifi_LLAPI` after workbook recalculation.
6. Generate Markdown, HTML, and JSON reports from the same summary model.
7. Preserve enough metadata in JSON to identify:
   - source JSON path
   - template path
   - reproject timestamp
   - summary classification policy version

## Markdown and HTML Shape

Markdown and HTML should expose:

- top-level KPI counts
- band/category Hybrid summary
- diagnostic sub-counts for values classified under `To be confirmed`
- per-case table with raw verdicts, projected bucket, diagnostic status, and fail reason
- existing collapsible case details where available

The visual style can reuse the current reporter style. The key requirement is semantic
alignment with the Excel Summary sheet.

## Testing and Verification

Offline tests only for the first implementation:

1. Unit tests for classification:
   - `FailEnv`, `FailConfig`, `Inconclusive` classify as `To be confirmed`
   - step command failure without criteria mismatch classifies as `To be confirmed`
   - evaluate-phase `pass_criteria not satisfied` classifies as `Fail`
   - raw `Not Supported` and `Skip` keep their own buckets
2. Unit tests for category mapping:
   - five primary categories map directly
   - DataElements/DaemonMgt/Capabilities and other WiFi prefixes map to `WiFi.Other`
3. Unit tests for template validation:
   - missing `Summary` sheet fails
   - missing `Wifi_LLAPI` sheet fails
   - result header mismatch fails
   - comment column mismatch fails
4. Reproject smoke test using the selected full-run JSON:
   - new folder is created
   - original folder is unchanged
   - `.xlsx`, `.md`, `.html`, and `.json` are created
   - `Wifi_LLAPI!I/J/K` keep raw verdicts
   - `Wifi_LLAPI!M` contains fail reasoning for failed cases
   - hidden `Wifi_LLAPI!N/O/P` projected buckets exclude env/setup/counter-zero
     causes from the Summary `Fail` count
   - `Summary` preserves template styles, merged ranges, percent formats, and formulas
     linked to `Wifi_LLAPI`

No live serialwrap, DUT, or STA commands are part of this verification.

## Open Implementation Notes

- Prefer a small dedicated module under `src/testpilot/reporting/` for the shared summary
  model.
- Prefer a CLI or script entry point that explicitly takes source JSON and output folder
  inputs so operators cannot accidentally overwrite historical runs.
- When wiring this model into the live pipeline later, reuse the same summary model rather
  than adding a second path.

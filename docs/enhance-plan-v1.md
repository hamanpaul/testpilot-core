# TestPilot wifi_llapi Enhancement Plan v1

> Status: 已整併進 `docs/plan.md`（Master Plan）。本文件保留作為歷史設計與實作紀錄。

## Goal
- Implement an Excel report pipeline in `wifi_llapi` plugin that keeps the exact `Wifi_LLAPI` worksheet style from source report.
- Generate report files as `YYYYMMDD_<DUT-FW-VER>_wifi_LLAPI.xlsx`.
- Store reports under `plugins/wifi_llapi/reports`.
- Build a template report first by extracting `Wifi_LLAPI` sheet and clearing all result/test-command fields.
- Reuse the template for subsequent runs and fill test command/result by case execution output.

## Scope
- In scope:
  - `wifi_llapi` reporting pipeline
  - CLI commands for template generation and report-driven run
  - Orchestrator integration for `wifi_llapi`
  - Tests for template generation and result filling
- Out of scope:
  - Broad architectural refactor for non-wifi plugins
  - Forcing non-wifi plugins to use Excel reports

## Mandatory Constraints
- Template and reports must preserve source worksheet format/style.
- Case order must remain identical to source worksheet order.
- Result and test-command columns must be cleared in template.
- Runtime report filling must map by `case.source.row`.
- Existing plugin flexibility for non-wifi plugins must remain.

## Design Decisions
- Use `openpyxl` for Excel style-preserving operations.
- Use source worksheet `Wifi_LLAPI` as single source of truth.
- Keep only extracted sheet in template workbook.
- Add hidden `_meta` sheet in generated run reports for traceability.
- Keep backward compatibility for non-wifi run behavior.

## File-Level Implementation

### New module: `src/testpilot/reporting/wifi_llapi_excel.py`
- Add dataclasses:
  - `ClearRules`
  - `TemplateBuildResult`
  - `ReportMeta`
  - `WifiLlapiCaseResult`
- Add functions:
  - `sanitize_fw_version`
  - `generate_report_filename`
  - `build_template_from_source`
  - `write_template_manifest`
  - `create_run_report_from_template`
  - `fill_case_results`
  - `finalize_report_metadata`
  - `ensure_template_report`
- Default sheet: `Wifi_LLAPI`
- Default clear columns:
  - `G`, `H`, `I`, `J`, `K`, `L`, `M`

### Orchestrator: `src/testpilot/core/orchestrator.py`
- Add `wifi_llapi` report source default:
  - `/mnt/c/Users/paul_chen/Downloads/0302-AT&T_LLAPI_Test_Report_20260107.xlsx`
- Implement `_run_wifi_llapi(...)`:
  - Load/discover cases
  - Build template (`reports/templates/wifi_llapi_template.xlsx`)
  - Create dated run report
  - Execute plugin hooks: `setup_env`, `verify_env`, `execute_step`, `evaluate`, `teardown`
  - Build `WifiLlapiCaseResult` per case
  - Fill Excel report by `source.row`
  - Write `_meta`
  - Return report summary payload
- Keep skeleton path for non-wifi plugins.

### CLI: `src/testpilot/cli.py`
- Extend `run` options:
  - `--dut-fw-ver`
  - `--report-source-xlsx`
- Add group:
  - `testpilot wifi-llapi build-template-report`
  - Arguments:
    - `--source-xlsx`
    - `--sheet` (default `Wifi_LLAPI`)
    - `--out` (default template path)

### Script: `scripts/wifi_llapi_build_template_report.py`
- Standalone builder for template + manifest generation.

### Package init
- Add `src/testpilot/reporting/__init__.py`.

### Dependencies
- `pyproject.toml`: add `openpyxl>=3.1`.

## Runtime Report Flow
1. On `run wifi_llapi`, ensure template exists or rebuild from source.
2. Copy template to dated report:
   - `plugins/wifi_llapi/reports/YYYYMMDD_<FW>_wifi_LLAPI.xlsx`
3. Execute selected cases.
4. For each case:
   - Collect executed command text
   - Collect command output
   - Determine pass/fail
   - Fill row via `source.row` into columns:
     - `G` test command
     - `H` command output
     - `I`/`J`/`K` result (5g/6g/2.4g)
     - `L` tester (`testpilot`)
     - `M` comment
5. Finalize `_meta`.

## Template Generation Rules
- Extract only `Wifi_LLAPI` sheet.
- Keep all styles/merge/width/format unchanged.
- Detect case rows from column `C` (Parameter Name), starting row 4.
- Stop scan when long empty streak is reached.
- Clear result/test-command columns only on detected case rows.

## Validation and Tests
- Add tests in `tests/test_wifi_llapi_excel_template.py`:
  - Build template and verify:
    - only `Wifi_LLAPI` sheet remains
    - case order preserved
    - target columns cleared
  - Create run report and fill case result:
    - target row/columns filled correctly
  - Verify filename format:
    - `YYYYMMDD_<DUT-FW-VER>_wifi_LLAPI.xlsx`

## Known Gaps After v1
- Full env gate enforcement across all 418 cases still depends on case field completeness (`env_verify`).
- Serial timing/retry by-case policy still needs a follow-up schema/runtime enhancement.
- Excel/YAML strict alignment checker script is planned as next increment.

## Next Increment (v2 Candidate)
- Add strict alignment validator:
  - compare `source.row/object/api` against source Excel sheet
  - block run on mismatch unless explicit override
- Add per-case timeout/retry schema:
  - `timeouts.step_default`, `retry.step_default`, step-level overrides
- Add richer pass criteria evaluation for real command outputs.

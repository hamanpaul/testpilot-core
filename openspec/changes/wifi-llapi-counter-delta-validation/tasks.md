## 1. Wave 1 — Runtime: Phase Schema & Delta Operators

- [x] 1.1 Add module-level constant `ZERO_DELTA_COMMENT = "fail 原因為 0，數值無變化"` in `plugins/wifi_llapi/plugin.py`
- [x] 1.2 Implement `_validate_phase_ordering(case) -> str | None` per design Decision 5 (returns error string or None)
- [x] 1.3 Wire `_validate_phase_ordering` into `Plugin.discover_cases()` so violating cases are marked BLOCKED with `blocked_reason="invalid_delta_schema: <error>"`; other cases continue loading unaffected
- [x] 1.4 Extract existing field-criterion evaluation logic from `Plugin.evaluate()` into `_evaluate_field_criterion()` (no behavior change)
- [x] 1.5 Implement `_evaluate_delta_criterion(case, context, criterion, idx)` covering both `delta_nonzero` and `delta_match` per spec scenarios
- [x] 1.6 Add evaluate dispatch: `if "delta" in criterion → _evaluate_delta_criterion else _evaluate_field_criterion`
- [x] 1.7 Reserve and apply five new reason_codes: `invalid_delta_schema`, `delta_value_not_numeric`, `delta_zero`, `delta_zero_side`, `delta_mismatch`
- [x] 1.8 Confirm `_compare()` signature and behavior remain unchanged

## 2. Wave 1 — Reporter: M Column

- [x] 2.1 Change `DEFAULT_TEMPLATE_MAX_COLUMN` from `"L"` to `"M"` in `wifi_llapi_excel.py`
- [x] 2.2 Add constant `COMMENT_HEADER = "Comment"`
- [x] 2.3 Add `"M"` to `DEFAULT_CLEAR_COLUMNS`
- [x] 2.4 Update `_normalize_template_headers()` to write `COMMENT_HEADER` at row 3 column 13
- [x] 2.5 Add `_truncate_comment(text, limit=200)` helper (return value: string ≤ 200 chars, append `"..."` if truncated, return empty string for empty input)
- [x] 2.6 Update `fill_case_results()` to call `_set_cell_value_safe(ws, row, "M", _truncate_comment(item.comment))` after the existing G–L writes
- [x] 2.7 Verify `fill_blocked_markers()` and `fill_skip_markers()` still write only column H and do NOT touch column M (regression guard, no code change expected)

## 3. Wave 1 — Documentation: CASE_YAML_SYNTAX.md

- [x] 3.1 Inventory all top-level fields actually used across `plugins/wifi_llapi/cases/*.yaml` (id / name / version / source / platform / hlapi_command / llapi_support / implemented_by / bands / topology / test_environment / setup_steps / sta_env_setup / test_procedure / steps / pass_criteria / verification_command)
- [x] 3.2 Inventory all step-level fields actually used (id / target / action / capture / command / depends_on / expected / description) plus the new `phase` field
- [x] 3.3 Document the three pass_criteria shapes: `field+value`, `field+reference`, `delta` (with optional `reference_delta`)
- [x] 3.4 Document the full operator list (existing `equals / != / contains / not_contains / regex / not_empty / empty / >= / <= / > / < / skip` + new `delta_nonzero / delta_match`)
- [x] 3.5 Document `llapi_support` values (`Support / Not Supported / Skip / Blocked`) and how each maps to step actions
- [x] 3.6 Document schema validation rules (required fields, mutual exclusions, phase ordering constraint)
- [x] 3.7 Add three worked examples: standard case (existing shape), counter-delta case (new shape), blocked case
- [x] 3.8 Document the five new reason_codes with one-line trigger description each
- [x] 3.9 Save as `plugins/wifi_llapi/CASE_YAML_SYNTAX.md` (colocated with plugin code, not under `docs/`)

## 4. Wave 1 — Tests: Unit (`tests/test_wifi_llapi_delta.py`)

- [x] 4.1 `test_delta_nonzero_pass` — baseline=10, verify=42 → PASS
- [x] 4.2 `test_delta_nonzero_fail_zero` — baseline=10, verify=10 → FAIL, reason_code=`delta_zero`, comment=`ZERO_DELTA_COMMENT`
- [x] 4.3 `test_delta_nonzero_fail_negative` — baseline=10, verify=5 → FAIL, reason_code=`delta_zero`
- [x] 4.4 `test_delta_nonzero_baseline_missing` — baseline path unresolved → FAIL, reason_code=`delta_value_not_numeric`
- [x] 4.5 `test_delta_nonzero_non_numeric` — verify=`"N/A"` → FAIL, reason_code=`delta_value_not_numeric`
- [x] 4.6 `test_delta_match_pass_within_tolerance` — api=100, drv=109, tol=10% → PASS
- [x] 4.7 `test_delta_match_pass_exact_match` — api=100, drv=100 → PASS
- [x] 4.8 `test_delta_match_fail_exceed_tolerance` — api=100, drv=120, tol=10% → FAIL, reason_code=`delta_mismatch`
- [x] 4.9 `test_delta_match_fail_one_side_zero` — api=100, drv=0 → FAIL, reason_code=`delta_zero_side`
- [x] 4.10 `test_delta_match_fail_both_zero` — api=0, drv=0 → FAIL, reason_code=`delta_zero_side`
- [x] 4.11 `test_delta_match_fail_negative_either_side` — any side negative → FAIL, reason_code=`delta_zero_side`
- [x] 4.12 `test_delta_match_tolerance_boundary` — api=100, drv=110, tol=10% → PASS (inclusive)
- [x] 4.13 `test_phase_ok_baseline_trigger_verify` — standard ordering → returns None
- [x] 4.14 `test_phase_no_delta_skip_check` — no delta criterion → returns None regardless of phase labels
- [x] 4.15 `test_phase_missing_trigger` — only baseline + verify → error string contains `"require at least one phase=trigger"`
- [x] 4.16 `test_phase_baseline_after_trigger` → error contains `"baseline step must precede trigger"`
- [x] 4.17 `test_phase_verify_before_trigger` → error contains `"verify step must follow trigger"`
- [x] 4.18 `test_phase_default_unmarked_is_verify` — step without phase field treated as verify
- [x] 4.19 `test_phase_invalid_value` — phase=`"warmup"` → error contains `"unknown phase: warmup"`
- [x] 4.20 `test_evaluate_field_path_unchanged` — regression guard for `field+value`, reason_code remains `pass_criteria_not_satisfied`
- [x] 4.21 `test_evaluate_delta_path_picks_new_dispatch` — `_compare()` not invoked when criterion contains `delta:`
- [x] 4.22 `test_evaluate_mixed_criteria` — first failing criterion halts evaluation regardless of type
- [x] 4.23 `test_invalid_delta_schema_marks_blocked` — phase-violating case is BLOCKED at discover time, never reaches evaluate

## 5. Wave 1 — Tests: Integration

- [x] 5.1 Create `tests/fixtures/wifi_llapi_delta/delta_nonzero_pass.yaml` (baseline/trigger/verify mock values produce PASS)
- [x] 5.2 Create `tests/fixtures/wifi_llapi_delta/delta_nonzero_fail.yaml` (verify equals baseline → FAIL)
- [x] 5.3 Create `tests/fixtures/wifi_llapi_delta/delta_match_pass.yaml` (api/drv both grow within tolerance)
- [x] 5.4 Create `tests/test_wifi_llapi_delta_integration.py` covering `discover_cases → execute_step (mocked transport) → evaluate → fill_case_results`; assert per-band verdict columns and M column comment match expectations for all three fixtures
- [x] 5.5 Extend `tests/test_wifi_llapi_excel.py`: `test_template_max_column_is_M`
- [x] 5.6 Extend `tests/test_wifi_llapi_excel.py`: `test_clear_columns_includes_M`
- [x] 5.7 Extend `tests/test_wifi_llapi_excel.py`: `test_fill_case_results_writes_M`
- [x] 5.8 Extend `tests/test_wifi_llapi_excel.py`: `test_fill_case_results_truncates_long_comment`
- [x] 5.9 Extend `tests/test_wifi_llapi_excel.py`: `test_fill_case_results_empty_comment` (no `"None"` written)
- [x] 5.10 Extend `tests/test_wifi_llapi_excel.py`: `test_blocked_marker_writes_H_not_M`
- [x] 5.11 Extend `tests/test_wifi_llapi_excel.py`: `test_skip_marker_writes_H_not_M`
- [x] 5.12 Run full `pytest tests/` and confirm zero regression

## 6. Wave 1 — Sample Case Migration

- [x] 6.1 Migrate `plugins/wifi_llapi/cases/D037_retransmissions.yaml` to delta range; remove `'Workbook v4.0.3 marks this API as Fail'` description line; ensure baseline → trigger → verify ordering and at least one `delta_nonzero` and one `delta_match`
- [x] 6.2 Migrate `plugins/wifi_llapi/cases/D313_getssidstats_retranscount.yaml` to delta range; remove the per-band `equals 0` criteria; add baseline/trigger/verify steps for each band with per-band `delta_nonzero` checks
- [x] 6.3 Run emulated transport suite for both samples; confirm verdicts match design expectations

## 7. Wave 1 — PR Gating

- [x] 7.1 Confirm Wave 1 PR description includes design link and sample case before/after diff
- [ ] 7.2 CI green on unit + integration tests
- [x] 7.3 `pytest tests/` full suite green (no regression in existing modules)
- [x] 7.4 Wave 1 PR merged to main BEFORE opening any Wave 2 / Wave 3 PR

## 8. Wave 2 — Stage A Migration (~30 cases)

- [x] 8.1 Sub-PR `wave2-associated-device`: migrate remaining D038, D051, D052, D054 (`D037` already completed in Wave 1)
- [ ] 8.2 Sub-PR `wave2-getradiostats-errors-discard`: migrate D267, D268, D269, D270
- [ ] 8.3 Sub-PR `wave2-getssidstats-errors-discard`: migrate D304, D305, D306, D307, D308
- [ ] 8.4 Sub-PR `wave2-getssidstats-retrans-unknown`: migrate remaining D316 (`D313` already completed in Wave 1)
- [ ] 8.5 Sub-PR `wave2-ssid-stats-errors-retrans`: migrate D325, D326, D327, D328, D329, D334
- [ ] 8.6 Sub-PR `wave2-radio-stats-errors-retry-retrans`: migrate D396, D397, D398, D399, D401, D402
- [ ] 8.7 Sub-PR `wave2-radio-stats-retry-preamble`: migrate D406, D407, D448, D451
- [ ] 8.8 Sub-PR `wave2-vendor-radio-retry-retrans`: migrate D452, D453, D454, D455, D457, D458
- [ ] 8.9 Sub-PR `wave2-affiliated-misc`: migrate D495, D580
- [ ] 8.10 Each Wave 2 sub-PR description includes emulated suite smoke evidence and case-list diff
- [ ] 8.11 Update `CASE_YAML_SYNTAX.md` if Wave 2 reveals any schema gap

## 9. Wave 3 — Stage B Migration (~50 cases)

- [x] 9.1 Sub-PR `wave3-associated-device-traffic`: migrate D039, D040, D041, D042, D053, D055, D056, D057; keep D031 as documented holdout because repo-local evidence still shows `MUMimoTxPktsCount` is a stubbed `Not Supported` field rather than a live traffic delta counter
- [ ] 9.2 Sub-PR `wave3-getstats-traffic`: migrate D128, D130, D131, D132, D135, D136, D137
- [x] 9.3 Sub-PR `wave3-getradiostats-bcast-mcast-bytes`: migrate D263–D266, D271–D276
- [ ] 9.4 Sub-PR `wave3-getssidstats-bcast-mcast-bytes`: migrate D300–D303, D309–D315
- [ ] 9.5 Sub-PR `wave3-ssid-stats-bcast-mcast-bytes`: migrate D321–D324, D330–D337
- [ ] 9.6 Sub-PR `wave3-radio-bytes-and-affiliated`: migrate D394, D395, D477, D576–D579
- [x] 9.7 Each Wave 3 sub-PR description includes emulated suite smoke evidence and case-list diff
- [ ] 9.8 Update `CASE_YAML_SYNTAX.md` if Wave 3 reveals any schema gap

## 10. Closeout

- [ ] 10.1 Confirm `grep -rn "equals" plugins/wifi_llapi/cases/ | grep "value: '0'"` returns only Stage C cases (settings/state assertions explicitly out of scope)
- [x] 10.2 Confirm zero references to `'Workbook v4.0.3 marks this API as Fail'` remain in migrated cases
- [x] 10.3 Run `openspec validate wifi-llapi-counter-delta-validation --strict` and confirm green
- [x] 10.4 Final `pytest tests/` full suite green
- [ ] 10.5 Archive change with `openspec archive wifi-llapi-counter-delta-validation`

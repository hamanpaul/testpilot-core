## 1. Dependencies & Scaffolding

- [x] 1.1 確認 `ruamel.yaml` 在 `pyproject.toml` dev / optional deps；若缺則新增（migration 工具用，非 runtime deps）
- [x] 1.2 確認 `scripts/` 目錄存在（通常已存在，否則建立）

## 2. Migration Script

- [x] 2.1 撰寫 `scripts/wifi_llapi_strip_oracle_metadata.py`
  - 參數: 預設 dry-run、`--apply`、`--cases-dir <path>`
  - 用 `ruamel.yaml.YAML(typ='rt')` 讀寫、保留 comment / key order / quoting
  - 掃 `plugins/wifi_llapi/cases/*.yaml`；刪 top-level `results_reference`；若 `source` 為 dict 則刪 `baseline` / `report` / `sheet`
  - Dry-run 時 stdout 列 `<file>: removed [<fields>]`；apply 時實際 dump 回檔
  - 結尾 summary：`<scanned> files scanned, <modified> modified, <clean> already clean`
  - Idempotent：已清過的 YAML 再跑不改檔、計入 "already clean"
  - `source` 非 dict 時略過 source-level 處理、仍處理 top-level
- [x] 2.2 撰寫 `tests/test_wifi_llapi_strip_oracle_metadata.py`
  - `test_strip_dry_run_no_write` — dry-run 不動檔、stdout 列清單
  - `test_strip_apply_removes_all_four_keys` — apply 後四欄位全刪
  - `test_strip_preserves_source_row_object_api` — `source.row/object/api` 保留
  - `test_strip_idempotent` — 第二次 apply 檔案 byte-identical
  - `test_strip_preserves_comments_and_ordering` — inline / standalone comment 保留
  - `test_strip_source_not_mapping` — `source: null` 或 string 時不爆，只處理 top-level
- [x] 2.3 執行 `uv run pytest tests/test_wifi_llapi_strip_oracle_metadata.py -q` 全綠

## 3. Schema Validator

- [x] 3.1 修改 `src/testpilot/schema/case_schema.py`
  - 加常數 `_WIFI_LLAPI_FORBIDDEN_TOP_KEYS = {"results_reference"}` 與 `_WIFI_LLAPI_FORBIDDEN_SOURCE_KEYS = {"baseline", "report", "sheet"}`
  - 新增 `validate_wifi_llapi_case(case, source)`：先呼叫 generic `validate_case(case, source)`，再檢 top-level forbidden keys，再檢 `source.*` forbidden keys；違反時 `raise CaseValidationError` 含 `#31 cleanup` 字樣與欄位名清單
- [x] 3.2 撰寫 / 擴充 `tests/test_case_schema.py`
  - `test_validate_wifi_llapi_rejects_results_reference` — 訊息含 `#31 cleanup` 與 `results_reference`
  - `test_validate_wifi_llapi_rejects_source_baseline` — 訊息含 `#31 cleanup` 與 `baseline`
  - `test_validate_wifi_llapi_rejects_source_report_and_sheet` — 兩 keys 均觸發 + 訊息提及
  - `test_validate_wifi_llapi_passes_clean_case` — 乾淨 case 不拋
- [x] 3.3 執行 `uv run pytest tests/test_case_schema.py -q` 全綠

## 4. Plugin Integration

- [x] 4.1 修改 `plugins/wifi_llapi/plugin.py`：case load / discover 路徑的 `validate_case(...)` 呼叫全換成 `validate_wifi_llapi_case(...)`（grep 確認無遺漏）

## 5. Runtime Code Simplification

- [x] 5.1 `src/testpilot/core/case_utils.py`：刪除 `baseline_results_reference()` function（L100-139 整段）
- [x] 5.2 `src/testpilot/core/case_utils.py`：簡化 `case_band_results(case, verdict)` 為 `status = "Pass" if verdict else "Fail"; return band_results(status, case.get("bands"))`
- [x] 5.3 `src/testpilot/core/orchestrator.py`：刪除 L38 `baseline_results_reference as _baseline_results_reference` import 與 L227-228 wrapper function
- [x] 5.4 Grep `baseline_results_reference` 全 repo，確認無遺漏 caller
- [x] 5.5 撰寫 / 擴充 `tests/test_case_utils.py`
  - `test_case_band_results_verdict_true_all_bands` — `("Pass","Pass","Pass")`
  - `test_case_band_results_verdict_true_partial_bands` — `("Pass","N/A","N/A")`
  - `test_case_band_results_verdict_false_two_bands` — `("Fail","Fail","N/A")`
  - `test_baseline_results_reference_removed` — `from testpilot.core.case_utils import baseline_results_reference` → `ImportError`
- [x] 5.6 修改 / 移除任何 `tests/` 或 `plugins/wifi_llapi/tests/` 既有 fixture 內 `results_reference` 使用（不然 fail）

## 6. YAML Mass Cleanup

- [x] 6.1 執行 `python scripts/wifi_llapi_strip_oracle_metadata.py` dry-run；確認 summary 的 `modified` 數字接近預期（~389）
- [x] 6.2 執行 `python scripts/wifi_llapi_strip_oracle_metadata.py --apply`
- [x] 6.3 `git diff --stat plugins/wifi_llapi/cases/` — 抽查 20 個 sample 檔確認格式正常、僅機械化刪 key
- [x] 6.4 YAML mass rewrite **獨立 commit**：`chore: strip results_reference/source.baseline/report/sheet from wifi_llapi cases`

## 7. Repo-scale Validation

- [x] 7.1 新增 `tests/test_wifi_llapi_cases_oracle_free.py::test_all_wifi_llapi_cases_pass_schema` — iterate 420 cases 呼叫 `validate_wifi_llapi_case`，全不得拋
- [x] 7.2 新增同檔 `test_no_shipped_case_contains_forbidden_fields` — 原始 text scan 確認零 occurrence
- [x] 7.3 `uv run pytest -q` 全綠（full suite）
- [ ] 7.4 Local smoke：`testpilot run wifi_llapi` 對一測試台跑完，對比 PR#32-only report vs 本 PR report
  - 預期：數百 case 報表值 `Not Supported → Pass`
  - 預期：artifact_dir 無 `alignment_issues.json`
  - 預期：log 無 `results_reference` 相關訊息
- [x] 7.5 Negative test：手動把 `D001_*.yaml` 加回 `results_reference: { foo: bar }` → `validate_wifi_llapi_case` 拋錯、訊息含 `#31 cleanup`；測完 revert

## 8. Docs & Rollout

- [x] 8.1 `CHANGELOG.md`：加入 `### Removed` + **BREAKING** entry（引用 proposal 的 CHANGELOG 段落）
- [x] 8.2 `AGENTS.md` §Case Discovery：加註 "`results_reference` / `source.baseline` / `source.report` / `source.sheet` 已移除；報表值反映 runtime verdict"
- [x] 8.3 `pyproject.toml`：version bump v0.2.1 → v0.2.2
- [x] 8.4 Code commit (task groups 1-5 + 7 + 8 的產出)：`feat: remove results_reference oracle from wifi_llapi runtime`
- [x] 8.5 開 PR、描述引用 proposal.md 並附加「`Not Supported → Pass` 不等於已驗證」警示段落、列出 pending audit case 清單（若 local smoke 有抓到大量異動）
- [x] 8.6 PR 合併後，執行 `openspec archive remove-wifi-llapi-results-reference` 歸檔

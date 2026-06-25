## Why

PR#32 移除了 `testpilot run wifi_llapi` 對 source workbook 檔案的 reference，但 YAML 內嵌的 `results_reference` 欄位與其配套 metadata（`source.baseline` / `source.report` / `source.sheet`）仍被 `src/testpilot/core/case_utils.py` 的 `case_band_results()` 讀取並 **覆蓋** 實際測試 verdict。結果：DUT 實測通過 `pass_criteria` 的 case，報表被寫成 `"Not Supported"`（從 YAML 抄的 workbook 答案），而非實際 Pass。這正是 #31 spec §1 批判的「workbook 當 oracle / 抄答案而不是跑測試」心智模型殘留。2026-04-23 最新 run 的 D308/D313/D316/D495 即為此症狀產物。

## What Changes

- **BREAKING**: `plugins/wifi_llapi/cases/` 420 個 YAML 移除四個 oracle metadata 欄位：`results_reference` / `source.baseline` / `source.report` / `source.sheet`。下游分支需 rebase 並重跑 migration script。
- **BREAKING**: `src/testpilot/core/case_utils.py` 的 `baseline_results_reference()` function 刪除；`case_band_results()` 僅依 verdict 與 `case.bands` 產生 per-band 結果，不再讀任何 YAML oracle 欄位。下游若有其他 caller 需重寫。
- 新增 `scripts/wifi_llapi_strip_oracle_metadata.py`：一次性 migration，dry-run 預設、`--apply` 實際寫入、idempotent。
- 新增 `validate_wifi_llapi_case()` in `src/testpilot/schema/case_schema.py`：wifi_llapi 專屬 validator（generic `validate_case()` + 四個 forbidden keys 檢查）；schema fail-fast 防止 oracle 欄位回歸。
- 報表行為變化：300+ case 的報表值從 `"Not Supported"` 改為實際 verdict（大多變 `"Pass"`）。此為 unmask、非 regression。
- 保留不動：`source.row` / `source.object` / `source.api` / `source.id`（PR#32 alignment 依賴）；YAML `steps:` 裡文字敘述（如 `DUT 5G baseline: ...`）；CLI `wifi-llapi baseline-qualify`（獨立命令）。

## Capabilities

### New Capabilities

- `wifi-llapi-oracle-free-verdict`: 定義 wifi_llapi runtime 的 oracle-free 行為 — 報表值僅依 DUT 實測 verdict 產生，不讀取任何 YAML 內嵌 oracle metadata；schema 禁止 oracle 欄位；migration script 規格與 idempotent 要求。

### Modified Capabilities

None (no archived specs in `openspec/specs/`; `wifi-llapi-runtime-boundary` 仍在 `wifi-llapi-runtime-alignment` change 未 archive，無法 delta modify)。

## Impact

**Code**:
- `src/testpilot/core/case_utils.py` — 刪 `baseline_results_reference()`；`case_band_results()` 從 26 行簡化到 3 行
- `src/testpilot/core/orchestrator.py` — 刪 `baseline_results_reference` import 與 wrapper（L38 / L227-228）
- `src/testpilot/schema/case_schema.py` — 新增 `validate_wifi_llapi_case()` + forbidden-keys 常數
- `plugins/wifi_llapi/plugin.py` — case load 路徑改呼叫 `validate_wifi_llapi_case()`
- `scripts/wifi_llapi_strip_oracle_metadata.py` — **新檔**
- `tests/test_case_utils.py` / `tests/test_case_schema.py` / `tests/test_wifi_llapi_strip_oracle_metadata.py` — 新增與改寫 fixture

**Data**:
- `plugins/wifi_llapi/cases/*.yaml` — migration 後約 389 個 YAML 被修改（刪四個 key），與 code change 同 PR 分兩個 commit

**CLI / API**:
- `baseline_results_reference` public function 移除（若有 external import 會 `ImportError`）
- Schema validation 新增 forbidden-keys 規則（下游合入帶 oracle 欄位 → `CaseValidationError`）

**Docs**:
- `CHANGELOG.md` — `### Removed: BREAKING` entry
- `AGENTS.md` — §Case Discovery 註記「oracle metadata 已移除；report 反映 runtime verdict」

**Dependencies**: 無新增；migration script 用既有 `ruamel.yaml`（若未安裝需加入 dev deps）

**Version**: v0.2.1 → v0.2.2（接 PR#32；schema/import 表面 breaking，pre-stable 走 patch bump）

**Out of scope**:
- `reporter.py` 的 `_NON_PASS_EXPECTED = {"not supported", ...}` 與 `html_reporter.py` 的 `"not_supported"` colour/counter — 變 dead code 但無害，留 Open Question 待下顆 cleanup PR
- `pass_criteria` 正確性校正 — 某些原本被 `Not Supported` 覆蓋藏住的假 Pass 會露出，歸 audit mode 處理（另議）
- 其他 plugin 是否有類似 oracle pattern — 目前未觀察到，不預作 abstraction

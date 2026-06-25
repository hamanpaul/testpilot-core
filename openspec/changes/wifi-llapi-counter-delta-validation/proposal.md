## Why

LLAPI counter 類測試（Retrans / Retry / Fail / Error / Drop / packet / byte stats 等）的核心目的是驗證「API ↔ driver wiring 是否相符」。目前 `wifi_llapi/plugin.py` 只支援單點 snapshot 比對，無法分辨「driver 真的沒有 traffic」與「LLAPI 沒有接到 driver」這兩種完全不同的失敗。issue **#13** 已要求改用 before/after delta 比對；issue **#38** 進一步要求對 fail/retry/error 類 counter 在 trigger 後 delta 仍為 0 必須判 FAIL，並在報告註解欄寫明「fail 原因為 0，數值無變化」，理由是「test 工況本身沒能讓 counter 動」即無法證明 wiring。本 change 一次解決這條技術線。

## What Changes

- **新增** yaml step 層級欄位 `phase: baseline | trigger | verify`（optional，預設 `verify` 向後相容）
- **新增** 兩個 pass_criteria operator：
  - `delta_nonzero` — 表達 #38 政策：trigger 後 delta 必須 > 0
  - `delta_match` — 表達 #13 政策：API delta 必須與 driver delta 一致（`tolerance_pct`）
- **新增** case 載入階段 phase ordering schema 驗證（baseline → trigger → verify），違規 case 標 BLOCKED
- **新增** 5 個 reason_code：`invalid_delta_schema` / `delta_value_not_numeric` / `delta_zero` / `delta_zero_side` / `delta_mismatch`
- **新增** xlsx 報告 M 欄 (`Comment`)，承載 evaluate 失敗註解；既有 G~L 欄與 BLOCKED/SKIP 寫入 H 欄路徑不變
- **將** `WifiLlapiCaseResult.comment` 從 dead field 接上 M 欄寫入路徑（含 200 字截斷）
- **遷移** ~30 個 Stage A case（明確 fail/retry/error/discard counter）到 delta 範式
- **遷移** ~50 個 Stage B case（流量類 generic counter）到 delta 範式
- **新增** `plugins/wifi_llapi/CASE_YAML_SYNTAX.md` long-lived yaml syntax reference
- **不改** Stage C ~50 個用 `equals '0'` 但實為設定/狀態斷言的 case（D064/D071/D076/D086/D098/D183/D354/D427-D435 等）
- **不改** `_compare()` 既有 operator 簽名與行為
- **不改** `pass_criteria_not_satisfied` reason_code（細化已開 #39 跟蹤）

## Capabilities

### New Capabilities

- `wifi-llapi-counter-validation`: counter 類 case 的 delta 比對語意 — phase 標註、`delta_nonzero` / `delta_match` operator、phase ordering schema 驗證、失敗 reason_code 體系、reporter M 欄失敗註解規則

### Modified Capabilities

（無 — `wifi-llapi-alignment-guardrails` 與本 change 不相關）

## Impact

- **Affected code:**
  - `plugins/wifi_llapi/plugin.py`：evaluate dispatch、`_evaluate_delta_criterion()`、`_validate_phase_ordering()`、`ZERO_DELTA_COMMENT` 常數
  - `src/testpilot/reporting/wifi_llapi_excel.py`：`DEFAULT_TEMPLATE_MAX_COLUMN` / `COMMENT_HEADER` / `DEFAULT_CLEAR_COLUMNS` / `_normalize_template_headers()` / `fill_case_results()`
  - `plugins/wifi_llapi/cases/`：~80 個 yaml case 重寫（Wave 2/3）
- **Affected APIs / 文件:**
  - `plugins/wifi_llapi/CASE_YAML_SYNTAX.md`（新增）
  - 既有 case yaml 中 `'Workbook v4.0.3 marks this API as Fail'` 類註解必須刪除（語意被新政策取代）
- **下游影響:**
  - xlsx 報告新增 M 欄 → 任何下游 grep / parser 若假設 `max_column = L` 會需要更新（目前未發現此類腳本）
  - 既有報告歷史檔案不會自動 backfill M 欄
- **依賴:** 無新增 Python 套件
- **PR sequencing:** Wave 1（基礎建設）必須先 merge 通過 review，再開 Wave 2/3 PR
- **CI:** `pytest tests/` 全 suite 必須無 regression
- **不影響:** `_compare()` 既有 operator、Stage C 既有設定類 case、BLOCKED/SKIP 視覺渲染、workbook source xlsx 結構

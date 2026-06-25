# wifi_llapi `results_reference` Oracle 清除 — Design

- Issue: #31 後續（PR#32 合併後觀察到 oracle 邏輯未完全移除）
- Status: Draft (2026-04-23)
- Depends on: PR#32 (`feat: 新增 wifi_llapi runtime alignment`, merged 2026-04-23 01:36 UTC)
- Follow-up: reporter dead-code cleanup（另議）、audit mode（另議）

## 1. Problem

PR#32 已移除 runtime 對 source workbook 檔案（`0401.xlsx` 等）的 reference，但 **YAML 內嵌的 `results_reference` 欄位與其配套 metadata 仍被 runtime 讀取並覆蓋實際測試結果**。

具體症狀：

- `plugins/wifi_llapi/cases/D308_getssidstats_failedretranscount.yaml` 等 300+ case 含有
  ```yaml
  results_reference:
    v4.0.3:
      5g: Not Supported
      6g: Not Supported
      2.4g: Not Supported
  ```
- `src/testpilot/core/case_utils.py:142-167` 的 `case_band_results()` 在 `verdict=True` 時用 `results_reference` 覆蓋 per-band 結果
- 結果：DUT 實測通過 `pass_criteria`（`verdict=True`）→ report 仍寫 `"Not Supported"`（抄 YAML 答案）
- 2026-04-23 的最新 run (`20260423_DUT-FW-VER_wifi_LLAPI_20260423T113226232295/`) 顯示 D308/D313/D316/D495 皆為 `Not Supported` 即為此邏輯產物

這正是 #31 spec §1 批判的「workbook 當 oracle / 抄答案而不是跑測試」心智模型殘留 — PR#32 的 scope 未涵蓋。

## 2. Goals

- **Runtime 純 verdict**：`case_band_results()` 僅依 `pass_criteria` 驗證結果產生 Pass/Fail/N/A，不讀任何 YAML oracle 欄位
- **YAML 乾淨**：`plugins/wifi_llapi/cases/` 420 個 case 移除 `results_reference` / `source.baseline` / `source.report` / `source.sheet` 四個 oracle metadata 欄位
- **Schema 防回歸**：wifi_llapi 專屬 validator 禁止這四個欄位，未來複製或合入帶回 → `CaseValidationError` fail fast
- **可重現的 migration**：一次性 script 掃描 + idempotent apply，保留 YAML 格式與註解

## 3. Non-Goals

- 不處理 `pass_criteria` 本身的正確性 — 若某 case `verdict=True` 是假 Pass（pass_criteria 寫錯），本 PR 僅「揭露」此狀況，不修。歸 audit 處理
- 不動 `src/testpilot/reporting/reporter.py` 的 `_NON_PASS_EXPECTED = {"not supported", ...}` 與 `src/testpilot/reporting/html_reporter.py` 的 `"not_supported"` colour/counter — 變 dead code 但無害，留 Open Question
- 不動 YAML `steps:` 裡文字敘述（如 `DUT 5G baseline: ...`）— 純敘述、與 metadata 無關
- 不動 `source.row` / `source.object` / `source.api` / `source.id` — PR#32 alignment 依賴
- 不動 CLI `wifi-llapi baseline-qualify` — 獨立命令，與此 scope 無牽連
- 不將 `results_reference` 搬去 archive file — 歷史要查翻 git log 即可；避免 YAGNI

## 4. 要移除的範圍

### YAML 欄位

| 欄位 | 位置 | 影響 cases 數 |
|---|---|---|
| `results_reference:` | top-level | ~300+ |
| `source.baseline:` | source dict | 371（299 用 `0310-BGW720-300` + 70 用 `BCM v4.0.3` + 12 quoted variants） |
| `source.report:` | source dict | 少數（如 D495） |
| `source.sheet:` | source dict | 同上 |

### 程式碼

**`src/testpilot/core/case_utils.py`**
- 刪 `baseline_results_reference()` 整個 function (L100-139)
- 簡化 `case_band_results()` (L142-167) 從 26 行 → 3 行

**`src/testpilot/core/orchestrator.py`**
- 刪 L38 `baseline_results_reference as _baseline_results_reference` import
- 刪 L227-228 `_baseline_results_reference` wrapper function

**`src/testpilot/schema/case_schema.py`**
- 新增 `validate_wifi_llapi_case()` — generic `validate_case()` + plugin-local forbidden-keys 檢查

**`plugins/wifi_llapi/plugin.py`**
- case load 路徑改呼叫 `validate_wifi_llapi_case()`（原本呼叫 `validate_case()`）

### 新增

- `scripts/wifi_llapi_strip_oracle_metadata.py` — 一次性 migration
- `tests/test_wifi_llapi_strip_oracle_metadata.py` — migration 測試

## 5. Migration Script 規格

**檔案**：`scripts/wifi_llapi_strip_oracle_metadata.py`

### 用法

```bash
# dry-run（預設）
python scripts/wifi_llapi_strip_oracle_metadata.py

# 實際寫入
python scripts/wifi_llapi_strip_oracle_metadata.py --apply

# 只掃特定目錄（測試用）
python scripts/wifi_llapi_strip_oracle_metadata.py --cases-dir <path> --apply
```

### 行為

1. **Loader**：`ruamel.yaml` RoundTripLoader，保留 comment / key order / quoting / 空行
2. **掃描**：`plugins/wifi_llapi/cases/*.yaml`
3. **每個 case**：
   - top-level 有 `results_reference` → 刪
   - `source` 是 dict 且有 `baseline` / `report` / `sheet` → 刪
4. **Source dict 空掉**：理論上不會（PR#32 alignment 需 `source.object/api/row`），但若真空了保留 `{}`
5. **Idempotent**：第二次跑無變更、exit 0
6. **輸出**：
   - Dry-run: `D308_getssidstats_failedretranscount.yaml: removed [results_reference, source.baseline]`
   - Apply 結束: `summary: 420 files scanned, 389 modified, 31 already clean`

### 邊界

| 情況 | 行為 |
|---|---|
| `source` 非 dict / None | 跳過 source-level，處理 top-level `results_reference` |
| YAML parse 失敗 | raise、log 檔名、整 script fail |
| 檔案 read-only | raise、不吞錯 |
| Comment 夾在刪除欄位間 | ruamel 預設保留；dangling comment 靠 review 抽查 |

## 6. Runtime Code 變更

### `case_utils.py:case_band_results`

```python
# Before
def case_band_results(case, verdict):
    default_status = "Pass" if verdict else "Fail"
    result_5g, result_6g, result_24g = band_results(default_status, case.get("bands"))
    reference = baseline_results_reference(case)
    if not reference:
        return result_5g, result_6g, result_24g
    by_band = {"5g": result_5g, "6g": result_6g, "2.4g": result_24g}
    for b in ("5g", "6g", "2.4g"):
        value = reference.get(b)
        if not isinstance(value, str):
            continue
        norm = value.strip()
        if not norm:
            continue
        if verdict:
            by_band[b] = norm
        elif norm in {"Skip", "N/A"}:
            by_band[b] = norm
    return by_band["5g"], by_band["6g"], by_band["2.4g"]

# After
def case_band_results(case, verdict):
    status = "Pass" if verdict else "Fail"
    return band_results(status, case.get("bands"))
```

### 行為變化（預警）

| 條件 | Before | After |
|---|---|---|
| verdict=True, band 在 `case.bands`, `results_reference` 寫 `"Not Supported"` | `Not Supported` | `Pass` |
| verdict=True, band 不在 `case.bands` | `N/A` | `N/A` |
| verdict=False, `results_reference` 寫 `"Skip"` | `Skip` | `Fail` |
| verdict=False, 無 `results_reference` | `Fail` | `Fail` |

**合併後首次 run 預期**：300+ case 報表值從 `Not Supported` 變 `Pass`、少數可能變 `Fail`（原本被 Skip 覆蓋）。此非 regression，是 unmask 真相。

## 7. Schema Enforcement

### Forbidden keys

```python
_WIFI_LLAPI_FORBIDDEN_TOP_KEYS = {"results_reference"}
_WIFI_LLAPI_FORBIDDEN_SOURCE_KEYS = {"baseline", "report", "sheet"}
```

### Validator

```python
def validate_wifi_llapi_case(case: dict[str, Any], source: Path | str = "<unknown>") -> None:
    """驗證 wifi_llapi case — generic validator + plugin-local forbidden keys."""
    validate_case(case, source)
    forbidden_top = _WIFI_LLAPI_FORBIDDEN_TOP_KEYS & set(case.keys())
    if forbidden_top:
        raise CaseValidationError(
            f"{source}: wifi_llapi cases must not contain {sorted(forbidden_top)} "
            f"(removed by #31 cleanup; use actual DUT verdict, not workbook oracle)"
        )
    src = case.get("source")
    if isinstance(src, dict):
        forbidden_src = _WIFI_LLAPI_FORBIDDEN_SOURCE_KEYS & set(src.keys())
        if forbidden_src:
            raise CaseValidationError(
                f"{source}: wifi_llapi source.* must not contain {sorted(forbidden_src)} "
                f"(removed by #31 cleanup)"
            )
```

### 呼叫時機

`plugins/wifi_llapi/plugin.py` 的 case 載入路徑（`discover_cases` / `load_case`）— 將既有 `validate_case(...)` 呼叫換成 `validate_wifi_llapi_case(...)`。discover 或 run 時立刻 fail fast。

### Error message 設計

訊息明示「`#31 cleanup` 移除」— 未來 dev 看到能一眼知道要刪欄位、不是補欄位。

## 8. Testing

### Migration script (`tests/test_wifi_llapi_strip_oracle_metadata.py`)

| Test | 場景 |
|---|---|
| `test_strip_removes_all_four_keys` | YAML 四欄位齊全 → 全刪 |
| `test_strip_preserves_source_row_object_api` | `source.row/object/api` 保留 |
| `test_strip_idempotent` | 已清過再跑 → diff 乾淨 |
| `test_strip_preserves_comments_and_ordering` | ruamel roundtrip 保留註解、順序 |
| `test_strip_source_not_dict` | `source:` 是 None/string → 只刪 top-level `results_reference`、不爆 |
| `test_strip_dry_run_no_write` | 預設 dry-run 不動檔、stdout 列清單 |

### Runtime behavior (`tests/test_case_utils.py`)

| Test | 場景 |
|---|---|
| `test_case_band_results_verdict_true_no_override` | verdict=True、bands=[5g,6g,2.4g] → `("Pass","Pass","Pass")` |
| `test_case_band_results_partial_bands` | verdict=True、bands=[5g] → `("Pass","N/A","N/A")` |
| `test_case_band_results_verdict_false` | verdict=False、bands=[5g,6g] → `("Fail","Fail","N/A")` |
| `test_baseline_results_reference_removed` | `from testpilot.core.case_utils import baseline_results_reference` → `ImportError` |

既有 test / fixture 中引用 `results_reference` / `baseline_results_reference` 的處一併移除或改寫（grep `tests/` 與 `plugins/wifi_llapi/tests/`）。

### Schema (`tests/test_case_schema.py`)

| Test | 場景 |
|---|---|
| `test_validate_wifi_llapi_rejects_results_reference` | 帶 `results_reference` → `CaseValidationError` 含 `"#31 cleanup"` |
| `test_validate_wifi_llapi_rejects_source_baseline` | `source.baseline` → 同 |
| `test_validate_wifi_llapi_rejects_source_report_sheet` | `source.report` / `source.sheet` → 同 |
| `test_validate_wifi_llapi_passes_clean_case` | 乾淨 case → 不拋 |

### Repo-scale smoke

- `test_all_wifi_llapi_cases_pass_schema`：對 `plugins/wifi_llapi/cases/` 420 個 real case 跑 `validate_wifi_llapi_case`，全過（PR 合入後一定要綠）

## 9. Rollout

### PR 結構

**單一 PR，兩個 commit**：

1. `feat: remove results_reference oracle from wifi_llapi runtime` — case_utils、orchestrator、schema、plugin、migration script、tests
2. `chore: strip results_reference/source.baseline/report/sheet from wifi_llapi cases` — 420 YAML mass rewrite（migration script 產出）

### 合併前驗證

- `uv run pytest -q` 全綠（含 repo-scale smoke）
- local 跑 `testpilot run wifi_llapi` smoke：
  - 對比 PR#32-only report vs 本 PR report → 預期數百 case 報表值從 `Not Supported` 變 `Pass`
  - artifact_dir 無 `alignment_issues.json`（PR#32 已處理）
  - 無 `results_reference` 相關 warning / log
- 故意把一個 case 加回 `results_reference` → schema validation fail、訊息含 `#31 cleanup`

### CHANGELOG

```
### Removed
- **BREAKING**: wifi_llapi cases no longer support `results_reference`,
  `source.baseline`, `source.report`, `source.sheet`. Report values now
  reflect actual DUT verdict instead of workbook oracle lookup. Downstream
  forks must rebase and re-run `scripts/wifi_llapi_strip_oracle_metadata.py`.
```

### Version bump

v0.2.1 → **v0.2.2**（接 PR#32；schema/CLI 表面 breaking）

### 回滾

- `git revert` PR commit 即可
- YAML 的 `results_reference` 可從 revert diff 還原，無資料遺失

### Docs sync

- **`AGENTS.md`**：§Case Discovery 加註「`results_reference` / `source.baseline` / `source.report` / `source.sheet` 已移除；report 值反映 runtime verdict」
- **`CHANGELOG.md`**：如上
- **`README.md`**：若有提及 `results_reference` 的段落一併更新

## 10. 風險

| 風險 | 影響 | 處置 |
|---|---|---|
| **Unmasked false-pass** | 某 case `pass_criteria` 寫錯 → verdict 假 True → 原本被 `Not Supported` 覆蓋藏住 → 現在看起來是 `Pass`，真相仍錯 | 非本 PR scope（§3 Non-Goal），歸 audit。PR 描述標示：`Not Supported → Pass` 不代表「已驗證」，可能是「未驗證」 |
| **Downstream 分支未 rebase** | 帶 `results_reference` 合回 → schema fail | error message 含 `#31 cleanup` 關鍵字；downstream owner 自行跑 migration |
| **ruamel 邊角格式偏移** | 少數 YAML 的 comment 位置 / quote style 微變 | Review 時抽查、不擋 merge（純格式） |
| **HTML `Not Supported (bands)` 欄位恆 0** | 視覺上有「死欄位」 | Open Question；下顆 PR 清 reporter dead code |

## 11. Open Questions

- `src/testpilot/reporting/reporter.py` 的 `_NON_PASS_EXPECTED = {"not supported", "not_supported", "skip", "n/a"}` 與 `src/testpilot/reporting/html_reporter.py` 的 `"not_supported"` colour/counter：本 PR 不動（dead code 無害）；下顆 cleanup PR 再收
- 其他 plugin 若也有「抄 workbook 答案」模式（目前未觀察到）— 同套做法可複用；不預作 abstraction（YAGNI）

## 12. Appendix — Baseline (2026-04-23)

- `origin/main` @ `91eb92a` (PR#32 merged)
- Total wifi_llapi discoverable cases: 420
- `source.baseline` 分布: `0310-BGW720-300` × 299, `BCM v4.0.3` × 70, quoted variants × 12
- 代表性樣本: D308, D313, D316, D495（2026-04-23 report 顯示 `Not Supported`，實測 verdict=True）

## Context

PR#32 合併後，`testpilot run wifi_llapi` 對 **source workbook 檔案**（如 `0401.xlsx`）的 runtime reference 已拔除。但 YAML 內嵌的 `results_reference` / `source.baseline` / `source.report` / `source.sheet` 四個 oracle metadata 欄位以及 `src/testpilot/core/case_utils.py:142-167` 的 `case_band_results()` override 分支仍在運作 — 實測通過 `pass_criteria` 的 case 報表值被覆蓋為從 YAML 抄的 `"Not Supported"`。

2026-04-23 最新 run (`20260423_DUT-FW-VER_wifi_LLAPI_20260423T113226232295/`) 的 D308 / D313 / D316 / D495 為此症狀具體實例。相關背景與完整 file map 見 `docs/superpowers/specs/2026-04-23-wifi-llapi-results-reference-cleanup-design.md`（brainstorming 階段產出）。

當前 baseline：
- `origin/main` @ `91eb92a` (PR#32 merged, 2026-04-23 01:36 UTC)
- wifi_llapi discoverable cases: 420
- `source.baseline` 分布: `0310-BGW720-300` × 299 / `BCM v4.0.3` × 70 / quoted variants × 12

## Goals / Non-Goals

**Goals:**

- Runtime 的 per-band 報表值僅由 `(verdict, case.bands)` 決定，不讀 YAML 任何 oracle 欄位
- `plugins/wifi_llapi/cases/` 下 420 個 YAML 完全不含 `results_reference` / `source.baseline` / `source.report` / `source.sheet`
- Schema 在 case load / validate 階段即拒絕帶 oracle 欄位的 case（fail-fast、含 `#31 cleanup` 關鍵字）
- Migration 工具可重複執行（idempotent）、預設 dry-run、保留 YAML 格式與註解

**Non-Goals:**

- 不修正 `pass_criteria` 本身的正確性（被 oracle 遮蔽的假 Pass 揭露後歸 audit）
- 不動 `src/testpilot/reporting/reporter.py` 的 `_NON_PASS_EXPECTED` 與 `html_reporter.py` 的 `"not_supported"` colour/counter
- 不動 YAML `steps:` 裡文字敘述中的 `baseline:` 字樣（純敘述）
- 不動 `source.row` / `source.object` / `source.api` / `source.id`（PR#32 alignment 依賴）
- 不動 CLI `wifi-llapi baseline-qualify`（獨立命令）
- 不將 oracle metadata 搬去 archive file（YAGNI；要查翻 git）

## Decisions

### D1: 一次性 Clean Cut，不走漸進式

**選**：單一 PR 同時拔程式、改 schema、重寫 420 YAML。
**替代**：(a) 兩步 — 先拔 runtime override、YAML 暫留；(b) 搬家到 registry file。
**理由**：`results_reference` 本質是 #31 批判的「workbook 當 oracle」殘留，留著（a）或搬家（b）都讓人誤以為仍有用。一次切乾淨：runtime 心智一致、schema 可即刻防回歸、歷史要查翻 git log 就夠。

### D2: 新 capability `wifi-llapi-oracle-free-verdict`，不 modify 既有 spec

**選**：新 capability。
**替代**：延伸 `wifi-llapi-runtime-boundary`（前個 change 定義）。
**理由**：`openspec/specs/` 未 archive、前個 change 未 apply，無法 delta modify 尚未 archive 的 spec。新 capability 與 `wifi-llapi-runtime-boundary` 概念互補：前者 workbook 檔案 boundary、本 capability YAML 內嵌 oracle boundary。

### D3: Migration 用 `ruamel.yaml`，不用 PyYAML

**選**：`ruamel.yaml` RoundTripLoader。
**替代**：PyYAML（`yaml.safe_load` + `yaml.dump`）。
**理由**：PyYAML 會重排 key 順序、吃掉註解、正規化 quote style；420 個 YAML diff 若摻雜這些「非本 PR 目的」的格式變動，review 成本爆炸、rebase 衝突難看。ruamel 保留 roundtrip fidelity，diff 只剩「刪四個 key」的機械化變動。

### D4: 報表變化（Not Supported → Pass）為 unmask、非 regression

**選**：直接讓 300+ case 報表值從 `Not Supported` 變 `Pass`，PR 描述明示。
**替代**：保留某種 fallback 層（例如 YAML 裡新欄位 `expected_not_supported`）供「明知不支援」的 case 繼續標 `Not Supported`。
**理由**：(a) 若 DUT 實測通過 `pass_criteria`，真相就是 Pass，報成 `Not Supported` 是假的；(b) 引入新欄位等於重新製造另一個 oracle、違反 #31 spec 精神；(c) 若未來真有「明知不支援」需求，那該進 `pass_criteria` 的條件式（DUT 回特定 error → Pass），由測試本身表達，不是 metadata 外掛。

### D5: Schema 驗證用 plugin-local validator，不改 generic `validate_case()`

**選**：新增 `validate_wifi_llapi_case()`（call generic + plugin-local forbidden-keys check），plugin.py 改呼叫這個。
**替代**：在 `validate_case()` 裡判 plugin 身分條件驗。
**理由**：generic validator 多 plugin 共用，加 plugin 條件判斷會污染 generic。類比既有 `validate_brcm_fw_upgrade_case()` 的做法，保持 plugin 邏輯 plugin-local。

## Risks / Trade-offs

- **[Unmasked false-pass]** 某 case `pass_criteria` 寫錯導致假 verdict=True、原本被 `Not Supported` 覆蓋藏住 → 現在露出變「Pass」但真相仍錯 → **Mitigation**: PR 描述明示「報表 `Not Supported → Pass` 不代表已驗證，可能是未驗證」；把 audit-required case 清單列在 PR 附件供 RD follow-up；正式校正在 audit mode 處理（另議）
- **[Downstream 分支未 rebase]** 合回 main 時帶著 oracle 欄位 → schema fail → **Mitigation**: error message 含 `#31 cleanup` + migration script 路徑；downstream owner 自行 rerun migration
- **[ruamel 邊角格式偏移]** 少數 YAML 的 comment 位置 / quote style 微變 → **Mitigation**: 420 YAML diff review 時抽查幾十個 sample；純格式不擋 merge；整體 diff 仍以「刪 key」為主
- **[HTML 報表 `Not Supported (bands)` 恆 0]** 視覺上變死欄位 → **Mitigation**: 留 Open Question，下一顆 reporter cleanup PR 處理；本 PR 不動 reporter 避免 scope creep
- **[`ruamel.yaml` 依賴]** 若目前 dev deps 未含則需加入 → **Mitigation**: 檢查 `pyproject.toml`，若缺則 PR 內一併加；migration script 是 dev 工具不是 runtime，不影響 prod deps

## Migration Plan

**PR 結構**：單一 PR，兩個 commit：

1. `feat: remove results_reference oracle from wifi_llapi runtime`
   - `src/testpilot/core/case_utils.py`（刪 function / simplify `case_band_results`）
   - `src/testpilot/core/orchestrator.py`（刪 import + wrapper）
   - `src/testpilot/schema/case_schema.py`（新增 `validate_wifi_llapi_case`）
   - `plugins/wifi_llapi/plugin.py`（改呼叫新 validator）
   - `scripts/wifi_llapi_strip_oracle_metadata.py`（新增）
   - `tests/test_case_utils.py` / `tests/test_case_schema.py` / `tests/test_wifi_llapi_strip_oracle_metadata.py`

2. `chore: strip results_reference/source.baseline/report/sheet from wifi_llapi cases`
   - `plugins/wifi_llapi/cases/*.yaml` — 由 migration script 產出、約 389 個 YAML 修改

**合併前驗證**：

- `uv run pytest -q` 全綠（含 repo-scale `test_all_wifi_llapi_cases_pass_schema`）
- local 跑 `testpilot run wifi_llapi` smoke：
  - 對比 PR#32-only report vs 本 PR report → 預期數百 case 報表值 `Not Supported → Pass`
  - 無 `alignment_issues.json`（PR#32 已處理）
  - 無 `results_reference` 相關 warning / log
- 故意把一個 case 加回 `results_reference` → schema fail、訊息含 `#31 cleanup`

**Rollback**：`git revert` PR；YAML oracle 欄位從 revert diff 還原，無資料遺失。

**Version bump**: v0.2.1 → **v0.2.2**（schema/import 表面 breaking，pre-stable 走 patch）。

## Open Questions

- `src/testpilot/reporting/reporter.py` 的 `_NON_PASS_EXPECTED` 與 `html_reporter.py` 的 `"not_supported"` colour/counter 後續清理時機（本 PR 不動）
- 若 audit mode 設計時證明 `pass_criteria` 不足以表達「DUT 回特定 error 視為 Pass」→ 是否需要 structured negative assertion 新欄位（非 oracle，而是 criteria 的一部分）— 暫列未決

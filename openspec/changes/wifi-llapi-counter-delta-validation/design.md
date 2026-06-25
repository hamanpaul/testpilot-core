## Context

`wifi_llapi/plugin.py` 目前的 `_compare()` 只支援 single-actual vs single-expected 的 operator（`equals / != / contains / regex / >= / <= / >` 等）。LLAPI counter 類測試（fail/retry/error/discard 與 packet/byte stats）因此被迫用兩種寫法表達：

1. **正向** — `field+reference equals` 比對 API 端與 driver 端 snapshot 是否一致（無法分辨「driver 沒 traffic」與「LLAPI 沒接到 driver」）
2. **倒裝** — 用 `equals '0'` 當 PASS 條件「斷言 LLAPI 仍然壞掉」（D037 / D052 等案例：description 註明「Workbook v4.0.3 marks this API as Fail」），語意倒裝、難以閱讀

issue #13 / #38 兩條技術線同時要求改用 trigger 前後 delta 比對。本 design 一次解決兩者。

reporter 端：`wifi_llapi_excel.py` 的 `WifiLlapiCaseResult` dataclass 已有 `comment` 欄位但未被寫入 xlsx（dead field）；`fill_case_results()` 只寫 G~L 欄，BLOCKED/SKIP 走 `fill_blocked_markers()` / `fill_skip_markers()` 覆寫 H 欄。本 design 必須選擇一個欄位承載 #38 要求的「失敗註解」。

## Goals / Non-Goals

**Goals:**

- 在 `wifi_llapi` plugin 內加入 trigger 前後 delta 比對的基礎建設（phase 標註 + delta operator）
- 表達 #38 政策：「fail/retry/error counter trigger 後 delta 為 0 一律 FAIL，並在報告註解寫『fail 原因為 0，數值無變化』」
- 表達 #13 政策：「API delta 必須與 driver delta 一致（含 tolerance）」
- 把 `WifiLlapiCaseResult.comment` 從 dead field 接上 xlsx 寫入路徑
- 新增 5 個細粒度 reason_code（限 delta 路徑），方便 reporter / 人工 debug 判斷失敗原因
- 提供 long-lived `CASE_YAML_SYNTAX.md` reference 文件
- 遷移 ~80 個存量 case 到新範式，徹底消除「workbook-expected-fail 的 negative-pass」這類語意倒裝寫法

**Non-Goals:**

- 把 counter validation 抽到 `src/testpilot/core/`（YAGNI；目前唯一 consumer 是 wifi_llapi）
- 修改 `_compare()` 既有 operator 簽名與行為
- 細化既有 `pass_criteria_not_satisfied` reason_code（已開 #39 跟蹤）
- 動 ~50 個 Stage C 設定/狀態類用 `equals '0'` 的 case（合法的 setpoint 等值斷言，非 counter）
- workbook source xlsx 結構驗證
- BLOCKED/SKIP 視覺渲染（仍寫 H 欄）
- 真實硬體 trigger workload 自動化（需 attenuator / 干擾源 HW，不適合 CI 化）

## Decisions

### Decision 1: 用 step-level `phase:` 欄位，不引入 `counter_validation:` 區塊

**選擇:** 在 step 上加 optional `phase: baseline | trigger | verify` 欄位；未標的 step 預設為 `verify`。

**Rationale:** 沿用既有 `for step in case.steps` 線性執行流，不動 step machinery；向後相容（既有 case 不需改），改動爆炸半徑最小。

**Alternatives considered:**

- 新增 `counter_validation: { baseline_steps: [...], trigger_steps: [...], verify_steps: [...] }` 區塊 — 動到 step 執行流，與既有 `step.id` / `depends_on` 機制重複表達，顯著增加 yaml 複雜度
- 用 step naming convention（如 `step_baseline_*` 自動推斷）— 隱式約定脆弱、人工易漏

### Decision 2: 只新增兩個 operator (`delta_nonzero` / `delta_match`)

**選擇:** `delta_nonzero` 表 #38 政策；`delta_match` 表 #13 政策（含 `tolerance_pct`）。

**Rationale:** 兩個 operator 涵蓋目前所有需求；其餘 corner case（如 `tolerance_abs`、`expected_min_delta`、`retry_trigger_n`）等真的有 case 需要再加（YAGNI）。

**Alternatives considered:**

- 通用 `delta` operator 加多個 sub-mode flag — 過度設計、yaml 表達性下降
- 三個 operator 分別處理 nonzero / match / mismatch — `delta_match` 失敗時自然涵蓋 mismatch 語意，無需獨立 operator

### Decision 3: failure comment 字串走 plugin 常數，case yaml 不可覆寫

**選擇:** `ZERO_DELTA_COMMENT = "fail 原因為 0，數值無變化"` 定義在 `plugins/wifi_llapi/plugin.py` 模組頂層；`delta_match` 失敗有對應的 `delta_mismatch` template。

**Rationale:** 一致性與可搜尋性 > 個別 case 表達力；下游 grep / 人工掃描報告時只要找一條固定字串即可。

**Alternatives considered:**

- 讓 case yaml 在 criterion 加 `on_zero_comment:` 欄位 — 個別 case 寫不一致字串會破壞下游 grep
- comment 模板在 reporter 端而非 plugin — comment 是「失敗原因」屬於 evaluate 語意，放 reporter 會洩漏領域知識

### Decision 4: dispatch 用 `"delta" in criterion` 判斷新舊路徑

**選擇:** evaluate 進入每個 criterion 時檢查 dict 是否含 `"delta"` key，是則走 `_evaluate_delta_criterion()`，否則走既有 field-based 邏輯。

**Rationale:** 零回歸風險（既有 `field+value/reference` criterion 完全不動）；不需在 yaml 引入 `criterion_type:` 額外欄位。

**Alternatives considered:**

- 為 criterion 加 `criterion_type: field | delta` — yaml 冗長、舊 case 需 backfill
- 把 delta 邏輯掛進 `_compare()` — 簽名不匹配（`_compare(actual, op, expected)` 是 single-value 形狀），硬掛會污染既有介面

### Decision 5: phase 違規走 BLOCKED 路徑、不 raise

**選擇:** `_validate_phase_ordering()` 在 case discover 階段執行；違規 case 標 BLOCKED（`blocked_reason="invalid_delta_schema: <error>"`），交給既有 `fill_blocked_markers()` 寫進 H 欄。其他 case 不受影響。

**Rationale:** Blast radius 最小（單一 case 出問題不拖垮 plugin load）；reporter 路徑現成；人工 debug 一看 H 欄就知道 yaml 哪裡寫錯。

**Alternatives considered:**

- 載入時 raise → plugin 全部 case 都跑不了，過於激進
- 執行時才檢查 → fail-late，浪費 transport setup 時間

### Decision 6: 新增 M 欄當 `Comment` 欄

**選擇:** xlsx template max column 從 L 擴到 M；新欄 header `Comment`；evaluate 失敗（含 delta 路徑與既有路徑）的 `WifiLlapiCaseResult.comment` 寫入 M 欄。

**Rationale:** 各既有欄位都有明確語意，疊加會破壞語意純粹性；新 M 欄專責「人類可讀失敗註解」是最乾淨的做法。

**Alternatives considered:**

- 寫入 H 欄與 `command_output` 並列 — H 欄已長，再塞註解難閱讀；BLOCKED/SKIP 也用 H 欄，三種語意混雜
- 寫入 I/J/K 後綴於 verdict（`"FAIL（fail 原因…）"`）— 破壞 result 欄純文字格式，下游解析腳本可能受影響
- 用 openpyxl `cell.comment`（懸浮 tooltip）— 列印 / PDF / grep 看不到，違背「可測」原則

### Decision 7: BLOCKED / SKIP 仍寫 H 欄、不搬到 M 欄

**選擇:** `fill_blocked_markers()` / `fill_skip_markers()` 行為不變；M 欄專責 evaluate 失敗註解。

**Rationale:** BLOCKED/SKIP 表示「沒測 / 需要重測」，與 evaluate 失敗（測了但沒過）是不同語意層級；分欄表達更利於人工掃描分類。

**Alternatives considered:**

- 一併搬到 M 欄統一「人類可讀說明」 — H 欄變得語意純粹但 BLOCKED/SKIP 與 FAIL 混在 M 欄反而不利分類

### Decision 8: PR 切分為三 wave，Wave 1 必須先 merge

**選擇:**

- Wave 1：runtime + reporter + CASE_YAML_SYNTAX.md + 2 個樣板 case（D037 / D313）
- Wave 2：~30 個 Stage A 案例
- Wave 3：~50 個 Stage B 案例

**Rationale:** Wave 1 定型 yaml schema 與 runtime 行為，Wave 2/3 才能確定遷移目標格式；若三 wave parallel 開發，schema 一旦改動 Wave 2/3 都要 rebase。

### Decision 9: tolerance 公式用 `max(|delta_a|, |delta_b|)` 為分母

**選擇:** `|delta_a - delta_b| / max(|delta_a|, |delta_b|) <= tolerance_pct/100`

**Rationale:** 對稱（不偏袒 API 或 driver 任一端）；前置條件「兩端皆 > 0」保證分母不為 0。絕對值是冗餘安全網（一旦前置條件被未來修改，公式仍 robust）。

## Risks / Trade-offs

- **存量遷移範圍大（~80 case）** → Mitigation：分 wave PR、每 wave 提供 emulated suite smoke 證據；Wave 2/3 可依 stat 群組（getradiostats / getssidstats / radio_stats / ssid_stats / associateddevice）切 sub-PR
- **trigger workload 需要硬體（attenuator / 干擾源），不適合 CI 化** → Mitigation：CI 只跑 emulated transport 的端到端測試；真實 workload 驗證留到 release smoke
- **既有 case 用 `equals '0'` 當 PASS 的「workbook-expected-fail」語意倒裝寫法將消失** → Mitigation：遷移時刪除 yaml 中對應的 description 註解（如 'Workbook v4.0.3 marks this API as Fail'）；Wave 2 PR diff 即為 audit trail
- **xlsx 報告新增 M 欄可能影響下游 parser** → Mitigation：grep 過 repo 確認無此類腳本；若未來發現，再以另一個 issue 處理
- **WifiLlapiCaseResult.comment 從 dead 變 active** → Mitigation：reporter test E 包含 truncate / empty / non-empty / BLOCKED 不寫 M 欄等 regression guard
- **未標 phase 的 step 預設為 verify 可能讓使用者誤以為「不標就 OK」而忽略 trigger** → Mitigation：phase ordering schema validator 在「有 delta criterion 但無 trigger step」時直接報錯標 BLOCKED（fail-fast）；CASE_YAML_SYNTAX.md 範例強調必須三段齊全

## Migration Plan

詳見 spec.md 與 tasks.md。摘要：

1. **Wave 1（基礎建設 PR）**: runtime + reporter + tests + CASE_YAML_SYNTAX.md + D037/D313 樣板，必須通過 review 並 merge
2. **Wave 2（Stage A migration PR）**: ~30 個明確 fail/retry/error counter
3. **Wave 3（Stage B migration PR）**: ~50 個流量類 generic counter
4. **Rollback strategy**: Wave 1 reverts cleanly（既有 case 不依賴新 schema、`field+value/reference` 路徑零改動）；Wave 2/3 reverts 即恢復 `equals '0'` / `equals reference` 寫法

## Open Questions

- 未來若有第二個 plugin 需要 delta 比對，再考慮把 counter validation 抽到 `src/testpilot/core/`（rule of three）
- Trigger workload 的硬體 setup（attenuator / 干擾源）由 case 設計者依現場資源決定，不在本 design 規範

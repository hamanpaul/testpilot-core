## Context

來源設計:`docs/superpowers/specs/2026-06-18-core-owned-execution-loop-design.md`。前置 B1(`RunBackend`)。MOC:`docs/superpowers/plugin-sdk-decoupling-MOC.md`。

P1b 已把整-run 迴圈獨立成 plugin-side `WifiLlapiRunner`,經 create_runner 委派。B2 把迴圈上移進 core(host 願景),並修正 run 路徑改寫 case YAML 的 audit-invariant 違規。

## Goals / Non-Goals

**Goals:**
- core 擁標準 run 迴圈(寫在 RunBackend + hooks);wifi 走預設、brcm 走 override。
- wifi production allow-list 清空。
- run 路徑 alignment 唯讀(修 audit-invariant 違規);drift 可見不靜默改檔。
- 行為位元級不變(drift 標記除外;golden 不受影響)。

**Non-Goals:**
- 不收 brcm 進 core 迴圈(firmware 燒錄本質不同 → create_runner override)。
- 不動 RunBackend / Transport / case 格式 / audit 模組。
- 不碰 P2/P3/P4。

## Decisions

### D1:core 擁標準迴圈,brcm 走 create_runner override(窄版)
- **理由**:符合 plugin-host 願景(core 主導);brcm = firmware 燒錄(自有 shells、無 RunBackend/retry)硬塞會弄髒通用迴圈。「預設迴圈 + 契約認可 override」≠ 雙軌。
- **替代**:寬版(統一 brcm+wifi)。否決——過度抽象、需重構 brcm、凹歪通用迴圈。

### D2:run 路徑 alignment 唯讀(修 audit-invariant 違規)
- run 不呼叫 `apply_alignment_mutations`、不寫 case 檔。`align_case` 唯讀計算對齊 row 供報表落點。
- drift(原 auto_aligned)case **照跑**;報表 reason 不論 pass/fail 標 `drift=blocked(需 audit)`;持久化只走 `audit apply`。
- **理由**:audit-mode spec 明文「run SHALL NOT 修改 plugin/cases/」;audit 自有 apply(不用此函式),移除安全;drift 應可見而非靜默修。
- **替代**:drift 直接從 run 排除(block 不跑)。否決——使用者要求「該筆照跑、只在 reason 標記」。

### D3:prepare_run 唯讀 hook
- `PluginBase.prepare_run(case_ids) -> PreparedRun{cases, artifacts}`,default = discover+filter。wifi 吸收 alignment 唯讀邏輯,回傳 runnable(含 drift 旗標 + in-memory 對齊 row)與報表 artifacts(blocked/skipped/summary)。
- **理由**:prep 是 host 呼叫的 plugin hook;唯讀契約確保不再有 run 路徑改檔。

### D4:run_loop 獨立成 core/run_loop.py
- 不塞進已龐大的 orchestrator;orchestrator 持有 run_backend + services,委派 run_loop。
- **理由**:isolation;orchestrator 已大。

### D5:create_runner 語意改為 override
- 預設(無 create_runner)→ core run_loop(非 skeleton)。create_runner 非 None → plugin 全權 override。
- **理由**:host 願景下 core 是預設;override 給本質不同工作。MODIFY P1b 的 create_runner 委派 requirement。

## Risks / Trade-offs

- **[行為保真(最大)]** 迴圈搬家 + alignment 唯讀 → 緩解:P1b 已獨立迴圈;golden 為準繩;in-memory 對齊 row 不變落點;golden fixture 無 drift。
- **[drift 行為改變]** auto_align(改檔)→ 唯讀 + reason 標記。正確化,非 regression。
- **[services 注入]** execution_engine/runner_selector/run_backend 如何傳入 run_loop → orchestrator 注入(plan 定形狀)。

## Migration Plan

1. `PluginBase.prepare_run`(default)+ `core/run_loop.py`(通用迴圈)。
2. orchestrator.run 委派:create_runner override 優先,否則 run_loop。
3. wifi:prepare_run(唯讀 alignment,移除 apply_alignment_mutations)、解散 WifiLlapiRunner、reporter 加 drift 標記 + template。
4. 清 allow-list(ExecutionEngine/build_case_session_plan 進 core)。
5. 守門(run 不改 cases/、allow-list 清空)+ golden + 全套回歸。
- **Rollback**:單一 change revert;迴圈搬位置、alignment 只移除寫檔。

## Open Questions

- `services` 注入形狀(dataclass vs orchestrator 子集),plan 階段定。

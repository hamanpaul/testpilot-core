# B2: core-owned execution loop（含 alignment 唯讀化）— 設計 spec

> 制定日期:2026-06-18
> 狀態:草案(brainstorm 已定調,待 review)
> MOC:`docs/superpowers/plugin-sdk-decoupling-MOC.md`
> 前置:B1(serialwrap → `RunBackend`,迴圈寫在其上)
> 相關:audit-mode capability(`openspec/specs/audit-mode/spec.md`)、P4 物理切分(`specs/2026-06-18-p4-physical-repo-split-design.md` §6 跨 stage 約束)

## Goal

把整-run 執行迴圈從 wifi plugin 的 `WifiLlapiRunner` **上移進 core**(寫在 B1 的 `RunBackend` + plugin hooks 上),落實「testpilot = 裝置中立的 plugin host」:**core 主導執行,plugin 提供 hook**。wifi 走預設 core 路徑(dogfood),`create_runner` 保留為本質不同工作(brcm firmware 燒錄)的契約認可 override。完成後 **wifi production 對 core/schema/reporting/transport 內部依賴歸零**(boundary allow-list 清空)。

**同時修正一個現行 audit-invariant 違規**:正常 run 路徑的 alignment 改寫 case YAML,違反「`testpilot run` SHALL NOT 修改 plugin/cases/」。本 change 把 run 路徑 alignment **唯讀化**。

## Motivation

- **執行歸屬決策(已定)**:不把執行 primitive 升 public(會把 serialwrap/session 內部凍結成永久契約),改 core-owned;plugin 透過 hook 接入。B1 已抽好 `RunBackend`;B2 把迴圈搬進 core 寫在其上。
- **真實耦合**:`WifiLlapiRunner.run(orchestrator)` 呼叫 6 個 orchestrator 私有方法 + `execution_engine` + `runner_selector` + 直接 import `ExecutionEngine`/`build_case_session_plan`。迴圈進 core 後,這些變成 core 用 core 自家模組(天經地義),wifi 不再 reach → allow-list 清空。守門 import-only 盲點也隨之消解。
- **audit-invariant 違規(必須一併修)**:`runner._prepare_alignment → apply_alignment_mutations` 對 `auto_aligned` case **改寫 source.row/id 並重命名檔**,且在正常 run 路徑無 gating。audit-mode spec 明文禁止;audit 自有 apply(不用此函式),故移除安全。

## Scope

- 新增 `src/testpilot/core/run_loop.py`:core-owned 標準 test-case 迴圈,寫在 `RunBackend`(B1)+ plugin hooks 上,產出 `RunResult`。
- `orchestrator.run()`:有 `create_runner()` → 走 plugin override(brcm);否則 → core `run_loop`。
- 新增 `PluginBase.prepare_run(case_ids) -> PreparedRun`(**唯讀**)hook;wifi 實作(吸收 alignment 的**唯讀**部分)。
- **alignment 唯讀化**:run 路徑 **不呼叫 `apply_alignment_mutations`**;in-memory 算對齊 row 供報表落點;drift case 照跑;持久化只留 `audit apply`。
- wifi:`WifiLlapiRunner` 解散;改提供 hooks;reporter 接 `RunResult`(沿用 P1b `build_reports`)。
- 補守門測試:`testpilot run` 不修改 `plugins/<plugin>/cases/`。
- 清 boundary allow-list 的 `ExecutionEngine`/`build_case_session_plan`(隨迴圈進 core)。

## Non-goals

- 不把 brcm 收進 core 迴圈(brcm = firmware 燒錄,本質不同,走 create_runner override)。
- 不動 B1 的 `RunBackend` 介面 / `Transport` / case YAML 格式 / 報表內容(drift 標記除外)。
- 不**搬** audit 模組(折出是 P4);但 B2 的 public 執行入口須能服務 audit `runner_facade`(見 §6)。不改 `audit apply` 的持久化角色。
- 不處理 entry_points(P2)/CLI(P3)/物理切出(P4)。

## Architecture

```
orchestrator.run(plugin, case_ids)
  ├─ plugin.create_runner() 非 None? ──► plugin override（brcm firmware）   ← 契約認可 escape hatch
  └─ 否 ──► core run_loop.run(plugin, case_ids, run_backend, services)
              prepared = plugin.prepare_run(case_ids)          # 唯讀:runnable + drift 標記 + 報表 artifacts
              handle = run_backend.setup_run(); run_backend.bind_sessions(devices)
              fw, src = resolve_fw(plugin, prepared.cases)      # 既有 capture_dut_firmware_version hook
              for case in prepared.cases:
                  runner = services.runner_selector.select_case_runner(...)
                  plan   = build_case_session_plan(...)          # core, optional
                  seq0   = run_backend.mark_position(handle)
                  retry  = services.execution_engine.execute_with_retry(...)
                  seq1   = run_backend.mark_position(handle); trace_write(...)
                  records.append(CaseRunRecord(case, retry, seq0, seq1, drift=case.drift, ...))
              export = run_backend.export_logs(...); run_backend.teardown_run()
              return plugin.create_reporter().build_reports(
                         RunResult(records, fw, export, prepared.artifacts))
```

### 1. core/run_loop.py（generic）
搬自現 `WifiLlapiRunner.run` 的**通用段**(serialwrap→RunBackend 生命週期、runner_select、session plan、execute_with_retry、trace、log seq、組 CaseRunRecord、組 RunResult)。execution import(`ExecutionEngine`/`build_case_session_plan`)落在 core(core 用 core)。不塞進已龐大的 orchestrator;orchestrator 持有 run_backend + services,委派 run_loop。

### 2. prepare_run hook（唯讀)
`PluginBase.prepare_run(case_ids) -> PreparedRun{cases, artifacts}`,default = `discover_cases` + case_ids 過濾。wifi 實作吸收現 `_prepare_alignment` 的**唯讀**邏輯:
- 對每個 case 用 `align_case`(read-only 計算 template 目標 row)得到狀態:`already_aligned` / `auto_aligned`(=drift)/ `blocked`(schema)/ `skipped`。
- **不呼叫 `apply_alignment_mutations`、不寫檔。**
- 回傳 `cases`(runnable,含 `already_aligned` 與 drift;每個帶 in-memory 對齊後的 row 供報表落點 + `drift: bool` 旗標)、`artifacts`(blocked/skipped/summary 供報表)。

### 3. drift 行為(唯讀 + 可見)
drift(原 `auto_aligned`)case:
- **照樣納入 run、照樣執行**取得 pass/fail(執行不變)。
- 報表落點用 **in-memory 對齊 row**(報表正確,檔案不動)。
- reporter 在組該 case 報表列時,**不論 pass/fail**,於 reason/comment **附加 `drift=blocked(需 audit)`** 標記。
- 持久化對齊請走 `testpilot audit apply`(唯一合法改檔途徑)。

### 4. wifi 變化
- `WifiLlapiRunner` **解散**:通用迴圈 → core;prep → `prepare_run` hook(唯讀);firmware/policy → 既有 hook。
- reporter 沿用 P1b `build_reports(run_result)`,新增 drift 標記輸出;把現 runner 建 xlsx-from-template 那步移進 reporter(core 迴圈不碰報表)。
- wifi production 不再 import `ExecutionEngine`/`build_case_session_plan`/`log_capture` → **allow-list 清空**。

### 5. brcm
不動(自有 CLI + run_cases)。`create_runner` 為其日後若走 orchestrator.run 的認可 override。

### 6. 跨 stage 約束:execution entry 經 `testpilot.api` 公開(P4 audit 折出)
迴圈上移 core 後,**core-owned 單-case 執行入口須經 `testpilot.api` 公開**。理由:wifi runner 不是唯一執行消費者——audit 的 `runner_facade.run_one_case_for_audit`(現 `from testpilot.core.orchestrator import Orchestrator` → `orchestrator.run(plugin, case_ids=[case_id])`)是**第二個消費者**。P4 把 audit 折進 wifi repo 後 runner_facade 變 plugin-side,只能依賴 `testpilot.api`。故 B2 須:
- 於 `testpilot.api` 公開單-case 執行入口(`orchestrator.run` 或等價 façade);
- 一併把 `case_d_number`(runner_facade 也用)納入 `testpilot.api`;
- B2 **不搬** audit(P4 做),但設計 public 執行面時把 audit `runner_facade` 列為已知第二消費者,避免 P4 才發現 api 缺口。

此約束亦支撐 P4 用 replay `RunBackend`(B1)接回 `tests/test_audit_runner_facade.py`(該測試正是經 runner_facade 驅動單-case 執行)。

## Risks / Trade-offs

- **[行為保真(最大)]** 迴圈搬家 + alignment 唯讀化 → 緩解:P1b 已把迴圈獨立成 runner(搬 core 風險可控);golden 報表測試為準繩;alignment 僅移除「寫檔」,in-memory 對齊 row 不變報表落點;golden fixture 已對齊無 drift,不受 drift 標記影響。
- **[drift 行為改變]** 原 auto_align(改檔)→ 現 唯讀對齊 + reason 標記。這是**正確化**(drift 可見、走 audit 修),非 regression。
- **[prepare_run 抽象涵蓋度]** 須涵蓋 alignment 的全部唯讀產物(runnable + drift + blocked/skipped/summary)→ 以現 `_prepare_alignment` 回傳物反推。
- **[orchestrator/run_loop 邊界]** services(execution_engine/runner_selector/run_backend)如何傳入 run_loop → orchestrator 持有並注入。

## Migration Plan

1. `PluginBase.prepare_run`(default discover+filter)+ `core/run_loop.py`(通用迴圈,寫在 RunBackend + hooks)。
2. orchestrator.run 委派:create_runner override 優先,否則 run_loop。
3. wifi:實作 `prepare_run`(唯讀 alignment,**移除 apply_alignment_mutations**);解散 `WifiLlapiRunner`;reporter 加 drift 標記 + 收 template 建立。
4. 清 allow-list(ExecutionEngine/build_case_session_plan 隨迴圈進 core)。
5. 守門測試:run 不改 cases/;allow-list 清空斷言;golden + 全套回歸。
- **Rollback**:單一 change revert;迴圈邏輯只搬位置,alignment 只移除寫檔。

## Open Questions

- 無阻擋。`services` 注入形狀(dataclass vs 直接傳 orchestrator 子集)於 plan 階段定。

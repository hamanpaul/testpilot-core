## Context

來源設計:`docs/superpowers/specs/2026-06-18-serialwrap-runbackend-abstraction-design.md`。MOC:`docs/superpowers/plugin-sdk-decoupling-MOC.md`。前置 Phase 1/2 已 merge。

serialwrap 雙層耦合:命令層(`Transport.execute`)已抽象;run-level daemon+WAL 層(orchestrator 33 + log_capture 23)寫死。本 change 只抽後者。

## Goals / Non-Goals

**Goals:**
- `RunBackend` 可換 provider 抽象(lifecycle + log capture 一體);serialwrap 為預設。
- core/reporting run-level 程式碼不再具名 serialwrap。
- 行為位元級不變(含報表日誌行範圍)。

**Non-Goals:**
- 不上移 run loop 進 core(Phase 4;迴圈位置不動)。
- 不實作 DirectTtyBackend(僅介面骨架)。
- 不動 `Transport` 命令層 / case YAML / 報表內容。

## Decisions

### D1:單一 `RunBackend` 介面(lifecycle + log capture 合一),非拆兩個
- **理由**:對 serialwrap 是同一 daemon、對 ttyUSB 是同一 port+檔;拆 `LogCapture`+`SessionProvider` 會逼出人為協調(capture 需知 session/seq 狀態)。命令層 `Transport` 維持獨立。
- **替代**:拆兩介面。否決——協調成本、provider 要湊兩個。

### D2:行為層 / 執行面分離,映射由 provider 持有
- case YAML 維持行為層(shell/行為),**零 case 要改**。`RunBackend` provider 持有「行為→具體指令」realization;serialwrap 用宣告式表(CLI 改→改表不改碼)。
- **理由**:映射若進 case 會把 400+ case 重新綁死後端,與解耦目標相反。此 change 先由 provider 內宣告式表錨定命名契約;把實際指令落入 per-case trace 需另案處理,以免踩到既有 trace/golden 輸出位元級不變紅線。

### D3:serialwrap 邏輯 verbatim 移入 backend,不改演算
- 現 `log_capture` 的 daemon/WAL/decode/seq 邏輯 + orchestrator 三方法 body 原樣收進 `SerialwrapBackend`(或 backend 私有 helper 模組)。
- **理由**:行為保真第一;這是搬位置不是改邏輯,golden/log_capture 測試為準繩。

### D4:行為集 = 現 orchestrator 三方法 + bind + mark 的自然邊界
- `setup_run`(=_start_serialwrap_for_run)、`export_logs`(=_export_serialwrap_logs)、`teardown_run`(=_stop_serialwrap)、`bind_sessions`(=setup_sessions)、`mark_position`(=get_current_seq)。
- **理由**:對齊真實使用點,Phase 4 與 ttyUSB 都好接。

## Risks / Trade-offs

- **[行為變動(最大)]** 56 觸點改寫,報表日誌行範圍最敏感 → 緩解:verbatim 移入、golden+log_capture 測試、先紅後綠。
- **[介面顆粒]** 過粗/過細 Phase4/ttyUSB 會痛 → 緩解:D4 對齊真實使用。
- **[provider 選擇一致性]** → 緩解:沿用 testbed config selector,預設 serialwrap。

## Migration Plan

1. `RunBackend` 介面 + 中性 dataclass。
2. `SerialwrapBackend`(verbatim 收 serialwrap 邏輯 + 宣告式 command 表,作為命名契約錨點)+ `DirectTtyBackend` stub。
3. orchestrator/reporting 改呼叫 RunBackend;移除 core/reporting serialwrap 具名 import。
4. provider 選擇(預設 serialwrap)。
5. 守門擴充 + golden + 全套回歸。
- **Rollback**:單一 change revert;邏輯只換位置。

## Open Questions

- `RunBackend` 放置(傾向新 `src/testpilot/runtime/`,與 transport 平行)。
- `log_capture.py` 整檔移入 vs 保留為 backend 私有 helper(傾向後者,改動小)。
- DirectTtyBackend stub 是否附介面測試(傾向附,鎖形狀)。

## Why

testpilot 的 run-level 執行/日誌目前**寫死 serialwrap**:`core/orchestrator`(33 觸點)直接驅動 serialwrap daemon、`reporting/log_capture.py`(23 觸點)整檔是 serialwrap RPC client + WAL 解碼。這違反「testpilot 對裝置存取方式中立」的自由原則,也讓 P7 物理切出時 plugin 會跨 repo reach 進 serialwrap 具名邏輯。命令執行層已有 `Transport` 抽象,但 run-level daemon + WAL 日誌層**沒有抽象**。

本 change(Phase 3 / B1)把這層抽到可換的 `RunBackend` provider 後:core 不再具名 serialwrap,serialwrap 變預設 provider,direct-ttyUSB 等後端可日後插入。行為位元級不變。

設計依據:`docs/superpowers/specs/2026-06-18-serialwrap-runbackend-abstraction-design.md`;路線圖:`docs/superpowers/plugin-sdk-decoupling-MOC.md`。

## What Changes

- **新增 `RunBackend` provider 介面**(run-level lifecycle + log capture 一體):`setup_run` / `bind_sessions` / `mark_position` / `export_logs` / `teardown_run`,搭配中性 dataclass(`RunHandle` / `ExportRequest` / `ExportResult`,無 serialwrap 具名)。
- **新增 `SerialwrapBackend`(預設 impl)**:把現有 serialwrap run-level 邏輯(`log_capture` 的 daemon/WAL/decode/seq + orchestrator 三方法 body)**verbatim 收進來**;behavior→serialwrap 指令以**宣告式表**表達,先錨定命名契約,不改既有 per-case trace。
- **新增 `DirectTtyBackend` 介面骨架**(stub / NotImplemented,僅鎖介面形狀,不實作)。
- **改寫** `core/orchestrator`:`_start_serialwrap_for_run`/`_export_serialwrap_logs`/`_stop_serialwrap` 改呼叫 `self.run_backend.*`;`reporting/log_capture` 的 serialwrap 具體邏輯移入 backend,core/reporting 其餘碼不再具名 import serialwrap。
- **provider 選擇**:沿用 testbed config selector,`run_backend` 預設 `"serialwrap"`。
- **守門擴充**:斷言 `core`/`reporting`(除 backend 模組)不再具名 serialwrap。
- **不改** case YAML(維持行為層)、`Transport` 命令層、報表輸出。

## Capabilities

### New Capabilities
- `run-backend-abstraction`: 規範 testpilot 的 run-level 裝置存取(daemon/port 生命週期、session 綁定、日誌擷取與 seq→行範圍)MUST 經由可換的 `RunBackend` provider;core/reporting MUST NOT 具名特定後端(serialwrap);serialwrap 為預設 provider,行為層(case)與執行面(provider 指令)分離且映射由 provider 持有。

### Modified Capabilities
<!-- 無既有 capability 的 requirement 改變;本 change 純新增抽象層,行為位元級不變。 -->

## Impact

- 新增:`RunBackend` 介面 + dataclass、`SerialwrapBackend`、`DirectTtyBackend` 骨架(置於新 `src/testpilot/runtime/`,plan 階段定案)。
- 改寫:`src/testpilot/core/orchestrator.py`(去 serialwrap 具名)、`src/testpilot/reporting/log_capture.py`(邏輯移入 backend)。
- 測試:守門斷言 core/reporting 不具名 serialwrap;新增 `RunBackend` 契約/介面測試;既有 serialwrap 路徑 golden/log_capture 測試保證行為不變。
- 對外行為:`testpilot wifi_llapi` UX 與報表輸出(含日誌行範圍)**不變**。
- 後續相依:Phase 4(core-owned loop)的 core 迴圈將寫在此 `RunBackend` 上。

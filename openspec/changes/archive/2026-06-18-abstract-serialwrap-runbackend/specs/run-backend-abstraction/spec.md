## ADDED Requirements

### Requirement: run-level 裝置存取經由可換的 RunBackend provider
testpilot 的 run-level 裝置存取(daemon/port 生命週期、session 綁定、日誌擷取與 seq→行範圍)MUST 經由 `RunBackend` provider 介面進行。`RunBackend` SHALL 提供行為方法:`setup_run`、`bind_sessions`、`mark_position`、`export_logs`、`teardown_run`。`core` 與 `reporting` 模組(除 backend 實作本身)MUST NOT 具名或直接依賴特定後端(serialwrap)。

#### Scenario: core/reporting 不再具名 serialwrap
- **WHEN** 對 `src/testpilot/core` 與 `src/testpilot/reporting`(排除 RunBackend 實作模組)grep `serialwrap`、`log_capture`、`wal`
- **THEN** 無 run-level serialwrap 具名依賴(具體邏輯只存在於 `SerialwrapBackend`)

#### Scenario: serialwrap 為預設 provider 且行為不變
- **WHEN** 未指定 run_backend 時執行一輪 wifi_llapi
- **THEN** 使用 `SerialwrapBackend`,且 xlsx/markdown/json/html 報表(含每-case `dut_log_lines`/`sta_log_lines` 日誌行範圍)與抽象化前的 golden snapshot 一致

#### Scenario: 後端可換
- **WHEN** testbed config 指定另一 `RunBackend` provider(如預留的 `DirectTtyBackend`)
- **THEN** orchestrator 經同一 `RunBackend` 介面執行,core 不需任何後端具名分支

### Requirement: 行為層與執行面分離,映射由 provider 持有
case YAML MUST 維持行為層(shell 指令 / 行為名),MUST NOT 攜帶特定後端的具體指令語法。「行為→具體指令」的 realization MUST 由 `RunBackend` provider 持有;`SerialwrapBackend` 以宣告式對照表表達。

#### Scenario: 換後端不需改 case
- **WHEN** 從 serialwrap 切換到另一 `RunBackend` provider
- **THEN** 無任何 case YAML 需要修改(case 僅描述行為)

#### Scenario: 命名契約先由 provider 錨定
- **WHEN** 一個行為被某 provider realize 執行
- **THEN** provider 以宣告式對照表持有「行為 → 實際後端指令」命名契約,case YAML 本身不含該指令,且本 change 不改既有 per-case trace 輸出

### Requirement: 抽象化不改變對外行為
引入 `RunBackend` 與改寫取用點 MUST NOT 改變 `testpilot wifi_llapi` 的 CLI UX 與報表輸出。

#### Scenario: 既有 serialwrap 路徑測試全綠
- **WHEN** 於改寫後執行既有 serialwrap/log_capture/golden 報表測試
- **THEN** 全數通過,輸出與改寫前一致

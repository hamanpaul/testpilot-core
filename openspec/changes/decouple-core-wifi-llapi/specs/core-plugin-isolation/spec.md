## ADDED Requirements

### Requirement: core 不得含特定 plugin 的具名知識
`src/testpilot/core`、`src/testpilot/schema`、`src/testpilot/reporting` 下的模組 MUST NOT import 或 reference 任何特定 plugin 的具名符號（如 `wifi_llapi_*`）。plugin 專屬行為只能透過 `PluginBase` hook 提供。

#### Scenario: core 不再 import wifi_llapi
- **WHEN** 對 `src/testpilot/core`、`src/testpilot/schema`、`src/testpilot/reporting` 執行 `grep -r wifi_llapi`
- **THEN** 無任何結果

#### Scenario: core 能對未知 plugin 跑完管線
- **WHEN** 一個 core 不認識的 plugin（如 `_template` 或 mock plugin）被載入並執行一個 case
- **THEN** setup → verify → steps → evaluate → teardown → 報表產出全程完成，core 不需任何 plugin 具名分支

### Requirement: plugin 透過契約 hook 提供專屬行為
`PluginBase` SHALL 提供下列 optional hook，且其 default 實作 MUST NOT 改變既有行為：`create_reporter()`（報表）、`validate_case(case)`（case 驗證）、`execution_policy(case)`（執行約束）、`register_cli(subparsers)`（CLI 子命令）。

#### Scenario: 未覆寫 hook 的 plugin 行為不變
- **WHEN** 一個只實作必要抽象方法、未覆寫上述 optional hook 的 plugin 執行 case
- **THEN** 使用 core 預設 reporter、不施加額外驗證、不施加執行約束、不註冊額外 CLI 命令

#### Scenario: wifi_llapi 透過 hook 提供報表
- **WHEN** wifi_llapi plugin 執行並產出報表
- **THEN** 報表由 `plugin.create_reporter()` 回傳的 reporter 產生（而非 core 直接呼叫 wifi_llapi 模組）

### Requirement: wifi_llapi 對外行為位元級不變
解耦 MUST NOT 改變 `testpilot wifi_llapi` 的對外 CLI UX 與報表輸出。

#### Scenario: wifi_llapi 報表輸出不變
- **WHEN** 解耦前後對相同 case 集執行 `testpilot wifi_llapi`
- **THEN** 產出的 xlsx/markdown/html 報表關鍵欄位與 golden snapshot 一致

#### Scenario: testpilot wifi_llapi 命令保留
- **WHEN** 使用者執行 `testpilot wifi_llapi`
- **THEN** 命令存在且行為與解耦前相同（由 `plugin.register_cli()` 註冊）

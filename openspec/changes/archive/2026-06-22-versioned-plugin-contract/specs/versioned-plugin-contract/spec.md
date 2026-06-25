## ADDED Requirements

### Requirement: SDK 契約版本(獨立於套件版本)
`testpilot.api` SHALL 提供 `API_VERSION`(semver `major.minor` 字串),為 SDK 對 plugin 承諾的契約版本。`API_VERSION` MUST 獨立於 testpilot 套件版本(`VERSION`):additive 變更 minor +1、breaking 變更 major +1,與套件 release 節奏解耦。

#### Scenario: API_VERSION 可由 testpilot.api 取得
- **WHEN** 讀取 `testpilot.api.API_VERSION`
- **THEN** 得到 semver `major.minor` 字串(初始 `"1.0"`)

### Requirement: plugin MUST 顯式宣告 api_version
`PluginBase` SHALL 提供 `api_version`(預設 `None`)。每個 plugin MUST 顯式覆寫為其 build against 的 API 版本(semver literal)。未宣告(`None`)MUST 於載入時被視為錯誤。

#### Scenario: in-repo plugin 宣告版本
- **WHEN** 檢視 wifi_llapi / brcm 的 plugin 類別
- **THEN** 各宣告 `api_version = "1.0"`

#### Scenario: 未宣告 api_version 載入報錯
- **WHEN** 載入一個未覆寫 `api_version`(為 None)的 plugin
- **THEN** raise `IncompatiblePluginError`,訊息指出該 plugin 未宣告 api_version

#### Scenario: api_version 格式錯誤載入報錯
- **WHEN** plugin 宣告的 `api_version` 不是 `major.minor` 字串
- **THEN** raise `IncompatiblePluginError`,訊息指出該 plugin 的版本格式錯誤

### Requirement: 載入時向後相容檢查
`loader.load()` SHALL 於實例化「前」檢查 plugin 的 `api_version` 與 `testpilot.api.API_VERSION`(fail-closed:不相容 plugin 的 `__init__` 不會被呼叫):當且僅當 `plugin.major == API.major` 且 `API.minor >= plugin.minor` 時通過;否則 raise `IncompatiblePluginError`(訊息含 plugin 名、要求版本、SDK 版本)。`IncompatiblePluginError` SHALL 由 `testpilot.api` 匯出。

#### Scenario: 向後相容通過
- **WHEN** plugin 宣告 `"1.0"` 而 `API_VERSION = "1.3"`
- **THEN** 載入成功(major 相同、SDK minor ≥ plugin minor)

#### Scenario: SDK 太舊報錯
- **WHEN** plugin 宣告 `"1.3"` 而 `API_VERSION = "1.0"`
- **THEN** raise `IncompatiblePluginError`(SDK minor < plugin minor)

#### Scenario: major 不符報錯
- **WHEN** plugin 宣告 `"2.0"` 而 `API_VERSION = "1.x"`
- **THEN** raise `IncompatiblePluginError`(major breaking)

#### Scenario: 相容檢查不改變相容 plugin 行為
- **WHEN** 相容 plugin(如 wifi_llapi `"1.0"` on SDK `"1.0"`)被載入並執行
- **THEN** 行為與本 change 前一致

#### Scenario: CLI 以乾淨錯誤呈現不相容 plugin
- **WHEN** CLI 載入 plugin 時遇到 `IncompatiblePluginError`
- **THEN** CLI 將其包裝為 user-facing Click error,不輸出 raw traceback

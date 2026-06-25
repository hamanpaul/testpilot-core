## Why

開放第三方 plugin 生態需要穩定、可演進的契約。目前 `PluginBase.version()` 只是 plugin **自身**版本,**沒有 SDK API 契約版本、沒有相容檢查**——SDK 介面一改,舊 plugin 可能靜默壞掉。母 spec 開放問題 #2 要求定版本策略。

本 change(P2b)讓 `testpilot.api` 宣告版本化 SDK 契約版本、plugin **顯式宣告**其 API 版本、載入時**相容檢查並明確報錯**,與 P2a 的 pip 版本約束互補。

設計:`docs/superpowers/specs/2026-06-18-versioned-plugin-contract-design.md`。前置:P2a(載入經 entry_points,檢查落在 `loader.load()`)。

## What Changes

- **`testpilot.api.API_VERSION`**(semver,e.g. `"1.0"`):SDK 契約版本,**獨立於 testpilot 套件版本**(additive→minor、breaking→major)。
- **`PluginBase.api_version`**(required,預設 `None`):plugin MUST 顯式宣告其 build against 的 API 版本(literal)。
- **`loader.load()` 相容檢查**:semver major.minor,`plugin.major == API.major AND API.minor >= plugin.minor` 才通過;未宣告(None)或不相容 → raise `IncompatiblePluginError`(明確訊息)。
- **`IncompatiblePluginError`**:新增於 core、由 `testpilot.api` re-export。
- wifi_llapi / brcm 設 `api_version = "1.0"`。
- **不改** 發現/packaging(P2a)、run loop、CLI、case 格式。

## Capabilities

### New Capabilities
- `versioned-plugin-contract`: 規範 SDK 契約版本(`testpilot.api.API_VERSION`,semver,獨立於套件版本)、plugin 顯式宣告 `api_version`、載入時向後相容檢查(major 相同且 SDK minor ≥ plugin minor)、不相容/未宣告明確報錯。

### Modified Capabilities
<!-- 無既有 capability 的 requirement 改變;為新增能力。 -->

## Impact

- 新增:`testpilot.api.API_VERSION`、`IncompatiblePluginError`(core 定義 + api re-export)、`PluginBase.api_version`。
- 改寫:`src/testpilot/core/plugin_loader.py`(load 加相容檢查)。
- plugin:wifi_llapi / brcm `plugin.py` 加 `api_version = "1.0"`。
- 測試:相容矩陣 + 未宣告報錯 + wifi/brcm 載入通過。
- 對外行為:相容 plugin 載入/行為不變;不相容 plugin 從「靜默壞」變「明確報錯」。
- 後續:第三方 plugin 套件 `depends testpilot>=1.0,<2.0` 與此 runtime 檢查互補。

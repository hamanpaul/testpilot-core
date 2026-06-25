## Context

來源設計:`docs/superpowers/specs/2026-06-18-versioned-plugin-contract-design.md`。前置 P2a(載入經 entry_points;檢查落在 `loader.load()`)。現況 `PluginBase.version()` 為 plugin 自身版本,無 SDK API 契約版本/相容檢查。

## Goals / Non-Goals

**Goals:**
- 版本化 SDK 契約(`testpilot.api.API_VERSION`,semver,獨立於套件版本)。
- plugin 顯式宣告 `api_version`;載入時向後相容檢查;不相容/未宣告明確報錯。

**Non-Goals:**
- 不做發現/packaging(P2a);不引入 patch 級契約語意;不從 pip metadata 推導契約版本。

## Decisions

### D1:semver(major.minor),向後相容區間
`plugin.major == API.major AND API.minor >= plugin.minor`。additive→minor、breaking→major。
- **理由**:第三方熟悉、與 pip 語意一致;exact 太脆(每次 minor bump 全破);整數 level 無法表達 minor 細粒度。

### D2:API 契約版本獨立於套件版本
`testpilot.api.API_VERSION` 自有常數,非 `VERSION`。
- **理由**:契約可跨多個 release 維持同版;解耦演進節奏。

### D3:plugin MUST 顯式宣告(預設 None → 報錯)
`PluginBase.api_version = None`;未覆寫即報錯。
- **理由**:plugin import 的是已安裝 testpilot 的 PluginBase;預設=當前版會使未宣告者檢查空轉。顯式 literal 才有牙齒、零灰區。

### D4:檢查在 loader.load,錯誤型別 IncompatiblePluginError
core 定義 `IncompatiblePluginError`,`testpilot.api` re-export;`load()` 實例化後檢查,訊息含 plugin 名/要求版本/SDK 版本。
- **理由**:load 是唯一載入點(P2a);明確錯誤(母 spec 要求);與 pip 互補。

## Risks / Trade-offs

- **[required 宣告負擔]** → 一行宣告;in-repo 同步設定;文件示範。
- **[契約版本 vs 套件版本混淆]** → spec/README/AGENTS 明述語意。
- **[semver 解析韌性]** → 嚴格 parse major.minor,格式錯明確報錯。

## Migration Plan

1. `testpilot.api.API_VERSION = "1.0"` + `IncompatiblePluginError`(core + api re-export)。
2. `PluginBase.api_version = None`。
3. `loader.load()` 加相容檢查(未宣告/不相容 raise)。
4. wifi_llapi / brcm 設 `api_version = "1.0"`。
5. 測試(相容矩陣 + 未宣告報錯 + wifi/brcm 通過)+ 全套回歸。
- **Rollback**:單一 change revert。

## Open Questions

- `IncompatiblePluginError` 定義位置(傾向 core 定義 + api re-export,與既有模式一致)。

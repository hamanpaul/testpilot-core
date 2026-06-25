# P2b: versioned plugin contract — 設計 spec

> 制定日期:2026-06-18
> 狀態:草案(brainstorm 已定調,待 review)
> MOC:`docs/superpowers/plugin-sdk-decoupling-MOC.md`
> 前置:P2a(發現/載入經 entry_points;相容檢查落在 `loader.load()`)、P1(`testpilot.api`)

## Goal

讓 `testpilot.api` 宣告一個**版本化的 SDK 契約版本**;plugin **顯式宣告**它實作/要求的 API 版本;testpilot 在載入 plugin 時**檢查相容性,不相容明確報錯**(而非靜默壞掉)。與 P2a 的 pip 套件版本約束互補。

## Motivation

開放第三方 plugin 生態需要穩定、可演進的契約。目前 `PluginBase.version()` 只是 plugin **自身**版本,**無 SDK API 契約版本、無相容檢查**:SDK 介面一變,舊 plugin 可能靜默壞掉。母 spec 開放問題 #2 要求定版本策略。

## Scope

- `testpilot.api.API_VERSION`(semver 字串,e.g. `"1.0"`),為 SDK 契約版本,**獨立於 testpilot 套件版本**。
- `PluginBase.api_version`(**required**:預設 `None`;plugin MUST 顯式宣告)。
- `loader.load()` 載入後做相容檢查:semver major.minor,`plugin.major == API.major AND API.minor >= plugin.minor` 才通過;否則 raise `IncompatiblePluginError`(明確訊息);未宣告(None)亦 raise(要求顯式)。
- in-repo wifi_llapi / brcm 設 `api_version = "1.0"`。

## Non-goals

- 不做發現/packaging(P2a)。
- 不引入 patch 級語意(只用 major.minor;patch 不影響契約相容)。
- 不自動從 pip metadata 推導(契約版本與套件版本刻意分離)。

## Architecture

### 1. SDK 契約版本
`testpilot.api.API_VERSION: str = "1.0"`。語意:**additive(新增 hook/symbol)→ minor +1;breaking(移除/改簽章)→ major +1**。與 testpilot 套件版本(`VERSION`)無關——契約可在多個套件 release 間保持同一 API 版本。

### 2. plugin 宣告(required)
`PluginBase.api_version: str | None = None`。plugin **MUST** 覆寫為其 build against 的 API 版本(literal 字串,如 `"1.0"`)。未覆寫(None)= 契約不誠實 → 載入報錯。

> 為何 required:plugin 安裝後 import 的是**已安裝** testpilot 的 PluginBase;若預設=當前 API_VERSION,未宣告者永遠回報當前版 → 檢查空轉。顯式 literal 才讓 runtime 檢查有牙齒。

### 3. 相容檢查(loader.load)
P2a 的 `load()` 在 `ep.load()()` 實例化後、回傳前:
```
declared = instance.api_version
if declared is None: raise IncompatiblePluginError(f"{name} 未宣告 api_version")
p_major, p_minor = parse(declared); a_major, a_minor = parse(API_VERSION)
if p_major != a_major or a_minor < p_minor:
    raise IncompatiblePluginError(
        f"{name} 要求 API {declared},但 testpilot 提供 {API_VERSION}")
```
- `1.0` plugin on SDK `1.3` → OK(向後相容)。
- `1.3` plugin on SDK `1.0` → 報錯(SDK 太舊)。
- `2.x` plugin on SDK `1.x` → 報錯(major breaking)。

### 4. 與 pip 互補
plugin 套件宣告 `dependencies = ["testpilot>=1.0,<2.0"]`(pip 擋不相容安裝);runtime 檢查為第二道、且明確報錯(母 spec 要求),並涵蓋 editable/dev 等 pip 未必擋到的情境。

### 5. `IncompatiblePluginError`
新增於 `testpilot.api`(或 core 並由 api re-export),供 host 捕捉/呈現;訊息含 plugin 名、要求版本、SDK 版本。

## Risks / Trade-offs

- **[required 宣告增加 plugin 作者負擔]** → 緩解:一行宣告即契約入口;in-repo wifi/brcm 同步設定;文件示範。
- **[API_VERSION 與套件版本分離易混淆]** → 緩解:spec/文件明述語意(契約 vs 套件);README/AGENTS 註明。
- **[semver 解析韌性]** → 緩解:嚴格 parse `major.minor`,格式錯誤明確報錯。

## Migration Plan

1. `testpilot.api.API_VERSION = "1.0"` + `IncompatiblePluginError`(api 匯出)。
2. `PluginBase.api_version = None`(required 語意)。
3. `loader.load()` 加相容檢查(未宣告/不相容 → raise)。
4. wifi_llapi / brcm 設 `api_version = "1.0"`。
5. 測試:相容矩陣(1.0/1.3/2.0 × SDK 1.x)、未宣告→報錯、wifi/brcm 載入通過;全套回歸。
- **Rollback**:單一 change revert。

## Open Questions

- `IncompatiblePluginError` 放 `testpilot.api` 直接定義還是 core 定義+api re-export(plan 定;傾向 core 定義、api re-export,與既有 re-export 模式一致)。

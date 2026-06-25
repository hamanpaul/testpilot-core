## 1. RED — 相容檢查契約先紅

- [x] 1.1 新增 `tests/test_versioned_plugin_contract.py`:斷言 `testpilot.api.API_VERSION` 存在(semver);相容矩陣(plugin "1.0" on API "1.0/1.3"→OK;"1.3" on "1.0"→raise;"2.0" on "1.x"→raise);未宣告→raise;`IncompatiblePluginError` 由 `testpilot.api` 匯出
- [x] 1.2 執行確認因 API_VERSION/api_version/檢查未存在而紅(理由正確),擷取 RED

## 2. GREEN — 契約版本與錯誤型別

- [x] 2.1 core 定義 `IncompatiblePluginError`;`testpilot.api` 加 `API_VERSION = "1.0"` 與 re-export `IncompatiblePluginError`(`__all__` 更新)
- [x] 2.2 `PluginBase.api_version: str | None = None`

## 3. GREEN — loader 相容檢查

- [x] 3.1 `loader.load()` 實例化後:未宣告(None)→ raise;parse major.minor,`plugin.major==API.major and API.minor>=plugin.minor` 否則 raise `IncompatiblePluginError`(訊息含 plugin 名/要求版本/SDK 版本)
- [x] 3.2 跑相容矩陣測試至綠

## 4. GREEN — in-repo plugin 宣告

- [x] 4.1 wifi_llapi / brcm `plugin.py` 加 `api_version = "1.0"`
- [x] 4.2 跑 wifi/brcm 載入通過

## 5. 回歸驗證

- [x] 5.1 既有 plugin/golden 測試全綠(相容 plugin 行為不變)
- [x] 5.2 全套 `pytest` 綠
- [x] 5.3 文件註明「API 契約版本 vs 套件版本」語意(README/AGENTS 視需要)

## 6. 收尾(workflow 後段)

- [x] 6.1 requesting-code-review(版本語意 / 檢查正確 / 行為保真)
- [x] 6.2 receiving-code-review + re-review 至無 Critical/Important
- [x] 6.3 openspec archive → policy → conventional commit → push → PR(R-12/R-17)

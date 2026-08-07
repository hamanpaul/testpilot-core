---
type: feat
scope: cli
issue: 30
---
`testpilot <PLUGIN_PATH>` 可直接執行磁碟上的 plugin 專案，不需先安裝進 registry（#30）。

## 兩種 invocation 形式

| 形式 | 解析方式 |
|---|---|
| `testpilot <PLUGIN_NAME> [ARGS]...` | registry mode——已安裝的 `testpilot.plugins` entry point（既有行為，未變） |
| `testpilot <PLUGIN_PATH> [ARGS]...` | path mode——磁碟上的 plugin 專案根目錄（新增） |

`PLUGIN_PATH` 指專案根目錄（含 `pyproject.toml` 那層）。專案自己的
`[project.entry-points."testpilot.plugins"]` 表是 plugin 名稱與 import 目標的唯一真實來源，
因此兩種模式對 plugin 身分的認定一致，只有解析路徑不同。

## 完整 parity，而非另一條簡化路徑

path mode 跑的是 plugin **自己** 透過 `register_cli` 註冊的 command，因此
`testpilot /path/to/p --flag` 與 `testpilot p --flag` 行為完全一致，plugin 專屬選項照常可用。
plugin 未註冊同名 command 時才退回核心 run 路徑。

這需要一個 loader 層的名稱 override：plugin 自有 command 內部會以**名稱**重新解析自己
（`get_orchestrator(ctx, name)` → `load_registered_plugin(name)`，且 `Orchestrator` 自建
一個新的 `PluginLoader`）。沒有 override 的話，path mode 會在乾淨環境直接找不到 plugin，
或在有安裝的環境**靜默跑到已安裝的那份**——後者比不支援還糟。`PluginLoader.register_override`
讓所有 loader 實例對「這個名字是誰」取得一致答案。

## 「跑到路徑那份」的保證

僅把專案路徑前插 `sys.path` 並不夠：同名發行版若已被 import，其 top-level package 已在
`sys.modules`，`import_module` 會直接回快取的那份。因此 path mode 會先驅逐不屬於本專案的
同名 top-level module，再 import，並**驗證載入結果確實位於專案根目錄之下**；驗證不過就
拒絕執行，而不是靜默測到錯的樹。

## Fail-closed 行為

- 路徑不存在 / 不是目錄 / 缺 `pyproject.toml` / 沒有 `testpilot.plugins` entry point：各自給出明確訊息。
- 專案宣告多個 plugin：**拒絕而不猜測**，並列出候選名稱，建議改為安裝後以名稱選取。
- entry point 值格式錯誤、屬性不存在、不是 `PluginBase` 子類：明確拒絕。
- path mode **不繞過** SDK API 版本閘，與 registry mode 共用同一個 `_check_api_compat`。
- 已註冊的 plugin 名稱永遠優先於同名資料夾，path mode 不可能遮蔽已安裝的 plugin。

## 實作

- 新增 `testpilot/core/plugin_project.py`：路徑解析、pyproject entry-point 讀取、
  專案優先 import 與位置驗證、plugin 實例化。
- `testpilot/core/plugin_loader.py`：新增 class 層級的名稱 override（`register_override` /
  `clear_overrides`），`load()` 優先查詢。
- `testpilot/cli.py`：`main` 改用 `PluginPathGroup`，`resolve_command` 在第一個 token 不是
  已註冊命令、且看起來像路徑時走 path mode。判定條件保守：含路徑分隔符、以 `.`／`~` 開頭、
  或該名稱確實是既有目錄。實作維持 plugin 零具名（`tests/test_cli_plugin_registration.py` 守門）。

## 測試與文件

新增 `tests/test_cli_plugin_path_mode.py`（11 個測試），含「同 package 名、已安裝那份已進
`sys.modules`」的碰撞情境——這正是不做 module 驅逐就會靜默跑錯樹的那一條。另有 registry mode
未回歸、相對路徑、四種 fail-closed 錯誤與 help 內容的覆蓋。

README（en/zh 兩段）新增兩種形式的對照表與 path mode 細節；`docs/plugin-dev-guide.md` 補上
「開發期免安裝跑法」；R-16 的 `testpilot-help` / `testpilot-update-help` marker 區塊已重生。

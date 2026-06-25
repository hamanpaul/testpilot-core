## ADDED Requirements

### Requirement: plugin 經 entry_points 被發現與載入
testpilot SHALL 經 Python `entry_points`(group `testpilot.plugins`)發現與載入 plugin。`PluginLoader.discover()` SHALL 回傳該 group 下所有 entry_point 名稱;`PluginLoader.load(name)` SHALL 以對應 entry_point 的 `.load()` 取得 `PluginBase` 子類並實例化。系統 MUST NOT 以掃目錄或 sys.path 插入方式發現/載入 plugin。repo 內的 `plugins/_template` 僅為 scaffold,除非有套件明確把它註冊成 `testpilot.plugins` entry point,否則 MUST NOT 被發現。

#### Scenario: 第三方 pip plugin 被發現
- **WHEN** 一個宣告 `[project.entry-points."testpilot.plugins"]` 的套件被 pip 安裝於環境
- **THEN** 其 plugin 出現在 `discover()` 結果且可被 `load()`,無需置於 repo 的 `plugins/` 目錄

#### Scenario: in-repo plugin 經 entry_point 註冊
- **WHEN** 於已安裝(`pip install -e .`)環境執行 `discover()`
- **THEN** bundled repo plugins 中只有 `wifi_llapi` 與 `brcm_fw_upgrade` 會被發現(由 testpilot pyproject 的 entry_points 註冊),而 `_template` 仍維持 scaffold-only

#### Scenario: _template scaffold 不可 discover
- **WHEN** repo 內存在 `plugins/_template/plugin.py`,但環境中沒有 `_template` 或 `template` 的 `testpilot.plugins` entry point
- **THEN** `discover()` 與 `testpilot list-plugins` 都不列出 `_template`,且測試以此為明確契約

#### Scenario: 不再掃目錄
- **WHEN** 檢視 `PluginLoader` 實作
- **THEN** 無掃 `plugins/` 目錄或 `spec_from_file_location` + sys.path 插入的發現/載入路徑

### Requirement: in-repo plugin 為正規可 import package
in-repo plugin MUST 為正規 Python package(具 `__init__.py`、內部 import 走 package 路徑),MUST NOT 依賴 loader 的 sys.path hack。

#### Scenario: plugin 內部 import 為 package 路徑
- **WHEN** 對 `plugins/wifi_llapi/**` production 掃描 import
- **THEN** 無對本地模組的 bare import(如 `from case_validation import`);皆為 `plugins.wifi_llapi.<mod>`

#### Scenario: plugin 檔案資源由模組位置解析
- **WHEN** plugin 需要其 `cases_dir` / reports / templates 路徑
- **THEN** 由 plugin 模組檔案位置推導,不依賴外部猜測 `plugins_dir/<name>`

### Requirement: 發現機制改變不改變對外行為
改用 entry_points MUST NOT 改變 `testpilot wifi_llapi` / `testpilot brcm-fw-upgrade` 的 UX 與輸出。

#### Scenario: 既有測試與 golden 全綠
- **WHEN** 於改動後(已安裝環境)執行既有 plugin / golden 報表測試
- **THEN** 全數通過,輸出與改動前一致

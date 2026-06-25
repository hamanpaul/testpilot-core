## 1. RED — 發現契約先紅

- [x] 1.1 新增 `tests/test_plugin_entry_points_discovery.py`:斷言 `discover()` 經 entry_points 回傳 `wifi_llapi`/`brcm_fw_upgrade`;`load()` 取得 PluginBase 子類;loader 無 dir-scan/sys.path 插入
- [x] 1.2 守門:`plugins/wifi_llapi/**` production 無本地模組 bare import(皆 `plugins.wifi_llapi.*`)
- [x] 1.3 執行確認因 loader 仍 dir-scan + wifi 仍 bare import + entry_points 未註冊而紅(理由正確),擷取 RED

## 2. GREEN — in-repo plugin 正規化為 package

- [x] 2.1 新增 `plugins/__init__.py`、`plugins/brcm_fw_upgrade/__init__.py`
- [x] 2.2 修 wifi 5 行 bare import → `plugins.wifi_llapi.<mod>`(`command_resolver.py:16`、`plugin.py:24-27`);同步 2 個 test 檔
- [x] 2.3 plugin 檔案資源(`cases_dir`/reports/templates)改由模組檔案位置推導(`Path(module.__file__).parent`)

## 3. GREEN — pyproject entry_points + 打包

- [x] 3.1 pyproject 加 `[project.entry-points."testpilot.plugins"]`(wifi_llapi / brcm_fw_upgrade);Hatch wheel `packages` 納入 `plugins`
- [x] 3.2 `pip install -e .`;確認 `python -c "from importlib.metadata import entry_points; print([e.name for e in entry_points(group='testpilot.plugins')])"` 列出兩 plugin

## 4. GREEN — loader 改 entry_points

- [x] 4.1 `plugin_loader.discover()`/`load()` 改 `importlib.metadata.entry_points` + `ep.load()`;移除 `spec_from_file_location` + sys.path 插入;保留型別檢查/快取/load_all
- [x] 4.2 orchestrator 取 plugin 檔案資源路徑改走模組位置(配合 2.3)
- [x] 4.3 跑發現契約 + 守門至綠

## 5. install-flow / 測試流程

- [x] 5.1 整理 stale editable install;dev/CI 文件/設定改以 `pip install -e .` 為發現前提(CI workflow 加安裝步驟)
- [x] 5.2 `realistic_runtime`(複製專案 + subprocess pytest)調整:複製環境安裝或改測法去 sys.path 依賴

## 6. 回歸驗證 — 行為不變

- [x] 6.1 既有 wifi_llapi / brcm 測試全綠(已安裝環境)
- [x] 6.2 golden 報表測試全綠
- [x] 6.3 全套 `pytest` 綠;`discover()` 名單與改動前一致
- [x] 6.4 grep 確認 loader 無 dir-scan/sys.path hack;wifi production 無本地 bare import

## 7. 收尾(workflow 後段)

- [x] 7.1 requesting-code-review(發現正確 / 行為保真 / packaging / install-flow)
- [x] 7.2 receiving-code-review + re-review 至無 Critical/Important
- [x] 7.3 openspec archive → policy → conventional commit → push → PR(R-12/R-17)

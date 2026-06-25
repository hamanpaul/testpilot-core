# P2a: entry_points 發現 + in-repo plugin packaging — 設計 spec

> 制定日期:2026-06-18
> 狀態:草案(brainstorm 已定調,待 review)
> MOC:`docs/superpowers/plugin-sdk-decoupling-MOC.md`
> 前置:無硬前置(與 B1/B2 檔域大致獨立);P4 物理切出依賴本案

## Goal

把 plugin 發現機制從**掃目錄 + sys.path hack** 改為 **Python `entry_points`**(group `testpilot.plugins`):第三方 pip plugin 宣告 entry_point 即被發現;in-repo plugin(wifi_llapi / brcm)同步**正規化為可安裝 package**並以 entry_point 註冊,**移除 dir-scan**(零雙軌)。行為位元級不變。

## Motivation

現況 `plugin_loader.discover()` 掃 `plugins/` 子目錄、`load()` 用 `spec_from_file_location` + 把 plugin 目錄塞進 `sys.path`,使 plugin 內 bare import(`from case_validation import …`)可解析。後果:
- **只認 repo 內**;pip 裝的第三方 plugin 找不到(違背開放生態目標)。
- sys.path hack 脆弱(子集測試 `realistic_runtime` 曾因此失敗)。
- `plugins/` 不在 Hatch wheel(`packages = ["src/testpilot"]`),in-repo plugin 非可安裝套件。

選定 **B(純 entry_points,現在就 packaging)**:零雙軌、且 packaging 本是 P4 必做(此處做一次,P4 退化成純搬檔)。

## Scope

- loader 改以 `importlib.metadata.entry_points(group="testpilot.plugins")` 發現/載入;移除 dir-scan 與 sys.path hack。
- in-repo plugin 正規化為 package:補 `__init__.py`、修 wifi 5 行 bare import 為 `plugins.wifi_llapi.*`(brcm 已無)、tests 同步。
- pyproject 宣告 `[project.entry-points."testpilot.plugins"]`(wifi_llapi / brcm_fw_upgrade);Hatch wheel 納入 `plugins`(過渡;P4 拆為獨立 dist)。
- dev/CI 改 `pip install -e .` 為發現前提;修現行 stale editable install;`realistic_runtime` 等需安裝的測試流調整。
- 行為不變:相同 plugin 被發現/載入、run 行為與報表不變。

## Non-goals

- 不把 plugin 物理移出 repo(P4);過渡期 in-repo plugin 仍隨 testpilot editable install 一起被發現。
- 不做 versioned contract(P2b)。
- 不碰 run loop(B1/B2)/ CLI(P3)/ case 格式。

## Architecture

### 1. 發現/載入(loader)
```
PluginLoader.discover() -> [ep.name for ep in entry_points(group="testpilot.plugins")]
PluginLoader.load(name) -> entry_points(group=..., name=name)[0].load()()  # ep.load() 取得 Plugin 類別,實例化
```
- 移除 `spec_from_file_location` + sys.path 插入。`ep.load()` 以正規 package import 取得 `plugins.wifi_llapi.plugin:Plugin`,plugin 內部 import 走 package 路徑(無需 hack)。
- 保留 `load()` 的 PluginBase 型別檢查、快取、`load_all()` 介面。
- orchestrator/runner_selector 仍以 `plugins_dir` 取報表/cases 實體路徑(entry_point 提供「程式碼發現」,檔案資源路徑另解析——見開放問題)。

### 2. in-repo plugin 正規化為 package
- 新增 `plugins/__init__.py`、`plugins/brcm_fw_upgrade/__init__.py`(wifi 已有)。
- 修 wifi 5 行 bare import → `plugins.wifi_llapi.<mod>`(`command_resolver.py:16`、`plugin.py:24-27`);對應 2 個 test 檔同步。
- 確認 `plugins.<plugin>.*` 在「已安裝」狀態可正規 import(不靠 pythonpath/rootdir 巧合)。

### 3. pyproject / 打包
```toml
[project.entry-points."testpilot.plugins"]
wifi_llapi = "plugins.wifi_llapi.plugin:Plugin"
brcm_fw_upgrade = "plugins.brcm_fw_upgrade.plugin:Plugin"
```
- Hatch wheel `packages` 納入 `plugins`(過渡)。
- `pip install -e .` 後,entry_points 註冊 + plugins 可 import。

### 4. dev/CI/test 流程
- dev/CI:以 `pip install -e .` 作為發現前提(取代 pythonpath-only 對 plugin 發現的依賴);整理現行指向某 worktree 的 stale editable install。
- `realistic_runtime`(複製專案 + subprocess pytest):改為在複製環境亦安裝,或改測法使其不依賴 sys.path hack。

## Risks / Trade-offs

- **[發現需安裝]** entry_points 靠已安裝 dist metadata → dev/CI 必須 editable install。緩解:本案明確納入 install-flow 整理;一次到位、且為 P4 既定現實。
- **[行為保真]** 載入路徑改變可能影響 plugin 內部 import 解析。緩解:bare import 全轉 package 路徑 + 既有 plugin/golden 測試把關;先確認 discover/load 回傳與現狀一致(相同 plugin 名單)。
- **[Hatch 打包 plugins]** 把 plugins 納入 testpilot wheel 是過渡權宜。緩解:P4 拆為獨立 dist;此處註明為過渡。

## Migration Plan

1. 正規化 package(`__init__.py` + 修 bare import + tests)。
2. loader 改 entry_points(discover/load),移除 dir-scan + sys.path hack。
3. pyproject entry_points + Hatch 納入 plugins;`pip install -e .`。
4. 修 install-flow(dev/CI/realistic_runtime)。
5. 守門:discover() 經 entry_points 回傳 wifi_llapi/brcm;dir-scan 已移除;golden + 全套回歸。
- **Rollback**:單一 change revert;loader/pyproject/imports 還原。

## Open Questions

- **檔案資源路徑(cases/reports/templates)解析**:entry_point 給「程式碼」位置;plugin 的 `cases_dir`/reports 仍需檔案路徑。現以 `plugins_dir/<name>` 解析;改 entry_points 後,以 plugin 模組檔案位置(`importlib.resources` / `Path(module.__file__).parent`)推導較穩。plan 階段定。
- **in-repo plugin 打包形態**:(a) 納入 testpilot wheel(過渡,輕)vs(b) 各自獨立 pyproject 可安裝套件(=P4 形態,重)。**傾向 (a) 過渡**,P4 再轉 (b)。
- brcm 是否一併轉 entry_points(移除 dir-scan 需兩者都轉)→ 是;brcm 無 bare import,成本低。

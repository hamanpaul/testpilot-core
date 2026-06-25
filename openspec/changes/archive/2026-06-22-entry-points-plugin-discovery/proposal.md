## Why

plugin 發現目前是 `plugin_loader` 掃 `plugins/` 子目錄 + sys.path hack 載入:**只認 repo 內**(pip 裝的第三方 plugin 找不到)、sys.path hack 脆弱(子集測試曾失敗)、`plugins/` 不在 Hatch wheel(非可安裝套件)。開放第三方 plugin 生態要求 `pip install their-plugin` 即被發現——這需要 `entry_points`。

本 change(P2a)把發現改走 Python `entry_points`(group `testpilot.plugins`),並把 in-repo plugin(wifi_llapi / brcm)正規化為可安裝 package、以 entry_point 註冊、**移除 dir-scan**(零雙軌)。packaging 本是 P4 必做,此處做一次、P4 退化成純搬檔。行為位元級不變。

設計:`docs/superpowers/specs/2026-06-18-entry-points-discovery-design.md`。

## What Changes

- **loader 改 entry_points**:`discover()`/`load()` 改用 `importlib.metadata.entry_points(group="testpilot.plugins")` + `ep.load()`;移除 `spec_from_file_location` 與 sys.path 插入;保留 PluginBase 型別檢查/快取/`load_all`。
- **in-repo plugin 正規化為 package**:補 `plugins/__init__.py`、`plugins/brcm_fw_upgrade/__init__.py`;修 wifi 5 行 bare import(`command_resolver.py:16`、`plugin.py:24-27`)為 `plugins.wifi_llapi.*`;對應 tests 同步。
- **pyproject**:新增 `[project.entry-points."testpilot.plugins"]`(wifi_llapi / brcm_fw_upgrade);Hatch wheel `packages` 納入 `plugins`(過渡)。
- **install-flow**:dev/CI 改以 `pip install -e .` 為發現前提;修現行指向 worktree 的 stale editable install;`realistic_runtime`(複製專案 + subprocess pytest)調整為可在複製環境發現。
- **不改** case YAML / 報表 / run loop / CLI;**不**物理移出 plugin(P4)。

## Capabilities

### New Capabilities
- `plugin-entry-points-discovery`: 規範 plugin 經 Python `entry_points`(group `testpilot.plugins`)被發現與載入;第三方 pip plugin 宣告 entry_point 即可用;in-repo plugin 亦為以 entry_point 註冊的正規 package;系統 MUST NOT 再以掃目錄/sys.path hack 發現 plugin。

### Modified Capabilities
<!-- 無既有 capability 的 requirement 改變;發現機制為新增能力,plugin 名單與行為不變。 -->

## Impact

- 改寫:`src/testpilot/core/plugin_loader.py`(entry_points 發現/載入)、`src/testpilot/core/orchestrator.py`(plugin 檔案資源路徑解析,見設計開放問題)。
- 新增/修改:`plugins/__init__.py`、`plugins/brcm_fw_upgrade/__init__.py`、wifi 5 行 import + 2 test 檔、`pyproject.toml`(entry_points + Hatch packages)。
- 流程:dev/CI `pip install -e .`;整理 stale editable install;`realistic_runtime` 測試調整。
- 對外行為:`testpilot wifi_llapi` / `testpilot brcm-fw-upgrade` UX 與輸出不變(發現到的 plugin 與行為相同)。
- 後續:P4 物理切出以本案為前置(plugin 已是 entry_point 套件,P4 退化為搬出 repo + 拆獨立 dist)。

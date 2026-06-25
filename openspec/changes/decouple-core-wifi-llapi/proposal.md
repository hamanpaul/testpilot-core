> **⚠️ SUPERSEDED(2026-06-18)** — 本 change(原 2026-06-14「core↔wifi_llapi 整包解耦」單一提案)已被**更細粒度的批次拆解取代**:B1(serialwrap→RunBackend)、B2(core-owned execution loop)、P2a(entry_points 發現)、P2b(versioned contract)、P3(CLI register_cli 解耦)、P4(physical-repo-split),各有獨立 spec / plan / OpenSpec change。**不再依本 change 實作**,保留僅供歷史脈絡;canonical 地圖見 `docs/superpowers/plugin-sdk-decoupling-MOC.md`。延後的後續抽取另立 issue #78(α)/ #79(β)。

## Why

testpilot 本有正規 plugin 系統（`core/plugin_base.py` 的 `PluginBase` + `core/plugin_loader.py`），契約甚至已含 `create_reporter()` / `report_formats()` 報表 hook。但 `wifi_llapi` 這個第一個大 plugin **繞過契約**，把自己的邏輯硬寫進 core：`reporting/` 有 7 個 `wifi_llapi_*` 模組、`orchestrator.py` 嵌了 ~350 行 wifi_llapi 報表對齊流（`_build/_prepare/_finalize_wifi_llapi_alignment`、`build_wifi_llapi_summary`）、`cli.py`/`schema/case_schema.py`/`case_utils.py`/`runner_selector.py`/`yaml_command_audit.py` 各有 wifi_llapi 具名邏輯。

後果：(1) plugin 邊界從「規則」退化成「建議」，第二個 plugin（qos/sigma）落地時報表/驗證/執行管線會發現是為第一個客戶特化的；(2) core 無法在不認識 wifi_llapi 的情況下被乾淨地抽出為可公開/可重用的框架。

本 change 把繞過契約的邏輯**收回契約**：core 對任何 plugin 零具名知識，wifi_llapi 完全透過 `PluginBase` hook 接入。

## What Changes

- **重用** 既有 `create_reporter()` / `report_formats()` hook：wifi_llapi 報表邏輯（7 模組 + orchestrator 對齊流 + reporter.py 引用）改由 wifi_llapi plugin 的 reporter 提供
- **新增** 3 個 plugin-agnostic optional hook 於 `PluginBase`（皆 default no-op / 中性值，向後相容）：
  - `validate_case(case) -> None` — 吸收 `schema.validate_wifi_llapi_case` + `yaml_command_audit` + `case_utils` 的 official/D### 判定
  - `execution_policy(case) -> dict` — 吸收 `runner_selector` 的 wifi_llapi 執行約束與 orchestrator execution-policy delegates
  - `register_cli(subparsers) -> None` — 吸收 `cli.py` 的 wifi_llapi 命令，保留 `testpilot wifi_llapi` UX
- **搬遷** 至 `plugins/wifi_llapi/`：7 個 `reporting/wifi_llapi_*` 模組、`yaml_command_audit.py`、`schema.validate_wifi_llapi_case`、orchestrator 的 `_*_wifi_llapi_alignment*` 方法群、`case_utils` 的 wifi_llapi helpers、`runner_selector` 的 wifi_llapi 約束
- **刪除** `reporting/wifi_llapi_compare_0401.py`（帶日期的一次性比對腳本；如仍需保留則移至 `plugins/wifi_llapi/scripts/`）
- **改寫** core 去具名化：`orchestrator` 改走 `plugin.create_reporter()/validate_case()/execution_policy()`；`reporter.py` 改讀 meta 內 plugin 提供的 generic summary；`cli.py` 改用 `plugin.register_cli()`
- **不改** verdict kernel ⊥ control-plane 的核心原則、`IReporter` 對 core 的契約方向、`testpilot wifi_llapi` 的對外 UX 與報表輸出（行為不變，測試保證）
- **不在本 change 範圍**：testpilot-core / plugins 的 repo 實體拆分與 public/private（後續 S2）；416 個 case YAML 的 case 庫分離（獨立議題）

## Impact

- 受影響 core 檔（去 wifi_llapi 化）：`core/orchestrator.py`、`cli.py`、`schema/case_schema.py`、`reporting/reporter.py`、`core/case_utils.py`、`core/runner_selector.py`、`yaml_command_audit.py`、`core/plugin_base.py`（加 hook）
- 新增/擴充 plugin：`plugins/wifi_llapi/`（reporter + validate + execution_policy + cli + 搬入的模組）
- 既有測試隨模組搬移更新 import；新增「core 不含 wifi_llapi」斷言 + 「core 能對未知 plugin 跑完報表流」的 second-plugin smoke
- 完成後可驗證標準：`grep -r wifi_llapi src/testpilot/core src/testpilot/schema src/testpilot/reporting` 為空

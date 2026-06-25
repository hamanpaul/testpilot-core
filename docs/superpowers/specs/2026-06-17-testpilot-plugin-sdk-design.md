# TestPilot Plugin SDK — 設計 spec

> 制定日期:2026-06-17
> 狀態:草案(待 review)
> 來源:brainstorming(目標形態 = 獨立 repo + pip;動機 = 開放第三方 plugin 生態;策略 = API-first)

## Goal

把 `wifi_llapi` 從 testpilot 主 repo 切成**獨立 repo + pip 套件**,透過 Python `entry_points` 被 testpilot 自動發現;testpilot 本體收斂為**裝置中立的 plugin host 框架**。

切分的真正交付物不是「搬走 wifi_llapi」,而是一個**穩定、可 versioned、願意對外承諾的 plugin contract(SDK)**。`wifi_llapi` 是這個 contract 的第一個驗收者(dogfood)。

## Motivation

開放第三方 plugin 生態:讓其他團隊 / 裝置能 `pip install testpilot` + `pip install their-plugin`,不必 fork 主 repo 就能掛自己的測試 plugin。這要求 core 對 plugin 的介面是公開、穩定、版本化的契約,而非現在這種「plugin 直接 reach 進 core 內部」的隱性耦合。

## 現況(brainstorming 已盤點)

解耦分三階段,#71 只完成第一階段:

| 階段 | 狀態 |
|------|------|
| 1. core 中立(`src/testpilot/{core,schema,reporting}` 對 plugin 零具名) | ✅ #71 |
| 2. CLI 中立(`cli.py` 不寫死 plugin) | ❌ #70 待辦,`cli.py` 具名 wifi_llapi 45 處 |
| 3. plugin 移出 repo 獨立 | ⬜ 本 spec 的目標 |

已鋪好的地基:`core/plugin_loader.py`(動態 importlib 載入)、`PluginBase` 的 hook 骨架(`create_reporter`/`validate_case`/`execution_policy`/`register_cli`)。

## Scope

涵蓋:
- 定義 `testpilot.api` 公開層(plugin contract 表面)。
- 堵掉 wifi_llapi 對 core 內部的洩漏依賴。
- plugin 發現機制改走 `entry_points`。
- PluginBase contract 版本化。
- CLI 解耦(`register_cli`,即 #70)。
- wifi_llapi 改成只依賴 `testpilot.api` 並物理移出 repo(dogfood 驗收)。

## Non-goals

- 不在本工程內擴充新裝置 plugin(brcm_fw_upgrade 等沿用,但不主動改造)。
- 不改變 wifi_llapi 的測試語意 / case 格式。
- 不處理 AI-agent 執行的可重現性議題(另案)。

## Architecture

### 1. 公開界線:`testpilot.api`

新增正式 public 層,收攏第三方 plugin「該用、且我們承諾穩定」的東西:

- `PluginBase` 與其生命週期 hook:`setup_env` / `verify_env` / `execute_step` / `teardown` / `create_reporter` / `validate_case` / `execution_policy` / `register_cli` / `discover_cases`。
- 報表:`MarkdownReporter` / `HtmlReporter` / `JsonReporter` + `reporting.excel_adapter`。
- transport:`transport.base`(serialwrap 等抽象)。
- case schema 驗證:`schema.case_schema`。
- testbed 取用:`TestbedConfig`(裝置設定 / 變數替換)。

凡未經 `testpilot.api` 匯出的符號,即為 core 私有,不對 plugin 承諾。

### 2. 堵洩漏(主要技術工作與風險)

wifi_llapi 現有三筆對 core 內部的反向依賴:

| 洩漏 import | 用途 | 處理方向 |
|------------|------|---------|
| `core.case_utils.stringify_step_command` / `step_command_lines`(`command_resolver.py`, `plugin.py`) | 命令文字處理 helper | **上提**為 `testpilot.api` 公開工具(低風險) |
| `core.execution_engine.ExecutionEngine`(`reporting/reporter.py`) | reporter 重建 case 執行以產報表 | **重設計**:reporter 不應依賴執行引擎;改由 plugin 在執行階段把所需資料交給 reporter(高風險) |
| `core.orchestrator.build_case_session_plan`(`reporting/reporter.py`, lazy import) | 同上,重建 session plan | 同上,連同 ExecutionEngine 一起釐清 |

`case_utils` 那筆單純;真正的工作在 **reporter 對 `execution_engine` / `orchestrator` 的依賴** —— 報表模組竟反向 reach 進執行編排內部。需釐清 reporter 真正需要的是什麼資料,改成由執行階段「推」給 reporter,而非 reporter「拉」core 內部。**這條沒切乾淨,contract 就不誠實,第三方會踩到內部。**

### 3. 發現機制:目錄掃描 → entry_points

`plugin_loader` 從掃 repo 內 `plugins/` 目錄,改為讀 `[project.entry-points."testpilot.plugins"]`。第三方套件宣告 entry_point 即被發現;repo 內 plugin 過渡期可兩者並存。

### 4. 版本化 contract

`PluginBase` 宣告所實作的 SDK API 版本;testpilot 啟動載入 plugin 時檢查相容性,不相容明確報錯而非靜默壞掉。版本策略(semver vs 整數 API level)待定(見開放問題)。

### 5. CLI 解耦(#70)= contract 的一部分

`cli.py` 45 處具名改用 `PluginBase.register_cli()`;plugin 透過此 hook 掛自己的子命令。這不只是清債,而是「plugin 如何擴充 CLI」這條對外契約。

### 6. dogfood:wifi_llapi 切出去 = contract 驗收

wifi_llapi 改成只依賴 `testpilot.api`,移除全部 core 內部 import,再物理移出 repo 成獨立套件。它切得乾不乾淨,就是 contract 完不完整的證明。

## 階段分解(此工程過大,不宜單一 plan)

建議拆成可獨立交付的 sub-project,每個各自 spec→plan:

1. **P1 — 公開層 + 堵洩漏**:建 `testpilot.api`;上提 case_utils helper;重設計 reporter↔execution 邊界(本工程最大塊)。
2. **P2 — entry_points 發現 + versioned contract**:plugin_loader 改 entry_points;PluginBase 加 API 版本與相容檢查。
3. **P3 — CLI 解耦(#70)**:cli.py 改 register_cli。
4. **P4 — wifi_llapi 物理切出**:移出 repo、獨立 pip 套件、entry_point 註冊、雙 repo CI。

P1 是其餘階段的前置與最大風險;P3 可與 P1/P2 並行。

## Risks

- **reporter↔execution 解耦(P1)**:reporter 對 `ExecutionEngine` / `build_case_session_plan` 的依賴可能牽連報表產生的資料流,重設計範圍待實作時量測。**最大未知。**
- **contract 過早固化**:第三方生態要求穩定 API,但目前只有 wifi_llapi 一個 consumer,單一樣本可能讓 contract 設計偏頗。緩解:dogfood 之外,至少用 brcm_fw_upgrade 當第二個對照,驗證 contract 不是只為 wifi_llapi 量身。
- **雙 repo 同步成本(P4)**:plugin 獨立後,SDK 變更要跨 repo 協調;版本相容檢查(P2)是緩解手段。

## 開放問題(待實作前或實作中釐清)

1. reporter 究竟需要 `ExecutionEngine` / `build_case_session_plan` 的哪些輸出?能否改由執行階段一次性提供?(P1 第一個要量測的)
2. 版本策略:PluginBase 用 semver 字串還是整數 API level?相容檢查多嚴(精確相等 / 向後相容範圍)?
3. `entry_points` group 命名與 plugin metadata schema。
4. brcm_fw_upgrade 是否同步納入 contract 驗證,還是僅 wifi_llapi dogfood?

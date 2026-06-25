## Why

monorepo 目前把 core(`testpilot`)、audit(`src/testpilot/audit/`)、vendor plugin(`plugins/wifi_llapi`、`plugins/brcm_fw_upgrade`)綁在同一 repo 與同一 git 歷史中,使 **core 無法獨立成 public**——歷史累積 lab config / vendor 詞彙 / 校準語料等受 `AI-SEC-001` 管制的內容,且 plugin 仍與 core 同 dist。母 spec P4(物理切出)要求 wifi_llapi 成獨立 repo + pip 套件、經 entry_point 被發現,並接回 skip 的 full-run 測試,達成「完全解耦可測」三判準。

本 change(P4)把 monorepo **物理切成多 repo**,**北極星=讓 core 獨立 public**;由此導出唯一硬安全邊界:**凡要 public 的 repo,git log 須無機敏**。

設計:`docs/superpowers/specs/2026-06-18-p4-physical-repo-split-design.md`。

## What Changes

- **三 repo 物理切分**(反向 big-bang,不留雙軌):
  - **core → 全新 public repo**(fresh、**無歷史**,防機敏外流);裝置中立 host + `testpilot.api` + 整體架構文件 + `plugins/_template` + governance scaffold。
  - **wifi_llapi → 現 repo 原地 rename**(private,**保留全歷史**);working tree 移除 core/brcm。
  - **brcm_fw_upgrade → 新 private repo**(`git filter-repo` 帶歷史過去)。
- **audit 折入 wifi_llapi**:`src/testpilot/audit/` 從 core 移進 wifi plugin 套件(脫 `testpilot.` namespace),**core 徹底甩掉 audit**;audit CLI 改由 plugin `register_cli()`(P3)註冊。解 audit→core 耦合:`validate_case`/`CaseValidationError`(已在 `testpilot.api`)換 import、`case_d_number` 經 api 公開、`Orchestrator`(runner_facade)走 **B2** core-owned 執行入口。
- **每 repo 獨立 pip dist**:pyproject 宣告 entry_points(P2a)、`api_version`(P2b)、`dependencies` pin `testpilot`(P2b);cases/reports/templates 隨套件以 `importlib.resources` 解析。**移除** P2a 過渡期把 plugins 塞進 testpilot wheel 的權宜。
- **CI 接回 full-run 測試**:wifi_llapi repo CI 以 **replay/fixture RunBackend**(B1)+ 錄製 golden serialwrap I/O,決定性重啟 `tests/test_audit_runner_facade.py`(原 `@pytest.mark.skip`)。跨 repo SDK 協調 = 釘選已發布版 + nightly 裝 `testpilot` main。
- **governance scaffold 落地每 repo**:接 `paulsha-conventions` reusable policy-check(pinned SHA)+ 從 `new-project-template` scaffold;**R-21 secret-scan = public core 發布閘**。
- **架構文件搬到 core**(public),經 policy/secret-scan 閘後落地。
- **不做(延後)**:rename `wifi_llapi→LLAPI-WIFI-BCM` + audit 抽 vendor 中立 `LLAPI-AUDIT`(issue α,gate 在 MTK);HLAPI 共用入口抽取(issue β);部署/發布 infra 實作(下游部署 stage,P4 只鎖契約)。

## Capabilities

### New Capabilities
- `plugin-physical-distribution`: 規範系統以多個獨立 pip dist + 多 repo 發布:core 為裝置中立、可獨立安裝、**不含任何 vendor plugin 與 audit**;plugin(含折入 audit 的 wifi)為獨立 dist,僅依賴 `testpilot.api`,與 core 共裝時經 entry_points 被發現;full-run audit 測試於 plugin repo CI 以 replay backend 接回;版本相容沿 P2b 強制。

### Modified Capabilities
<!-- 無既有(已 archive)capability 的 requirement 改變。P2a `plugin-entry-points-discovery` 仍為 in-flight change(未進 openspec/specs/),其過渡期 in-wheel bundling 由本 change 的 physical-distribution 取代,屬 sibling 規劃關係而非 spec modify;見 design.md。 -->

## Impact

- **新 repo / 可見性**:core(public,fresh)、wifi_llapi(現 repo rename,private,留歷史)、brcm_fw_upgrade(新 private,filter-repo)。
- **core 端移除**:`src/testpilot/audit/`、`plugins/wifi_llapi`、`plugins/brcm_fw_upgrade`;`cli.py` 移除 audit_group 具名掛載;pyproject 移除 plugins 的 in-wheel 打包與 entry_points;testpaths 去 plugin 測試。
- **wifi_llapi 端**:折入 audit(re-namespace + 解耦)、自有 pyproject(entry_point/api_version/pin testpilot)、CI 加 replay backend 接回測試、scaffold。
- **brcm 端**:自有 pyproject/scaffold/CI。
- **api 公開面**:`testpilot.api` 補 `case_d_number` 與 B2 的 core-owned 單-case 執行入口(見 B2 §6 跨 stage 約束)。
- **治理**:每 repo 接 paulsha-conventions policy-check;R-21 secret-scan 為 public core 閘;R-12/R-17 各 repo 沿用。
- **前置(須先實作 merge)**:B1、B2、P2a、P2b、P3;audit 折出前置健檢(validate_case/case_d_number/Orchestrator)。
- **延後**:issue α(rename + LLAPI-AUDIT,gate MTK)、issue β(HLAPI 共用入口)、下游部署 stage。
- **對外行為**:operator 安裝改為 `pip install testpilot` + plugin dist;`testpilot` 命令 UX 經 entry_points/register_cli 組裝後不變。

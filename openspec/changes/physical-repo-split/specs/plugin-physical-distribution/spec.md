## ADDED Requirements

### Requirement: Core 為裝置中立、可獨立安裝的發布單元

`testpilot` core SHALL 為可獨立安裝的 pip 套件,**不含任何 vendor plugin 程式碼,亦不含 audit 程式碼**。core 的測試套件 SHALL 在**未安裝任何 vendor plugin** 的情況下通過。

#### Scenario: core 單獨安裝可用且中立

- **WHEN** 在乾淨環境僅 `pip install testpilot`(無任何 plugin dist)
- **THEN** import `testpilot` 與 `testpilot.api` 成功,且 core 套件樹內不存在 `plugins/wifi_llapi`、`plugins/brcm_fw_upgrade`、`testpilot/audit` 任何模組

#### Scenario: core CI 在無 vendor plugin 下綠燈

- **WHEN** core repo CI 在無 vendor plugin 安裝下執行測試套件
- **THEN** 測試全數通過,且不引用任何 vendor plugin 或 audit 模組

### Requirement: Plugin 為獨立發布單元並經 entry_points 被發現

每個 plugin(wifi_llapi、brcm_fw_upgrade)SHALL 為**獨立 pip 發布單元**(不再 bundle 進 testpilot wheel);與 core 共裝時,SHALL 經 `entry_points`(group `testpilot.plugins`)被 core 發現。

#### Scenario: 共裝後被發現

- **WHEN** `pip install testpilot` 後再 `pip install` 某 plugin dist,並執行 plugin 發現
- **THEN** 該 plugin 出現在 `entry_points(group="testpilot.plugins")` 發現結果中,且其 cases/reports/templates 經 `importlib.resources` 解析自該套件

#### Scenario: plugin 可獨立安裝

- **WHEN** 對某 plugin dist 單獨建置/安裝
- **THEN** 安裝成功且其資源(cases/reports/templates)隨套件可用,不依賴 monorepo 目錄結構

### Requirement: audit 隨 wifi plugin 發布且僅依賴 testpilot.api

audit 程式碼 SHALL 隨 wifi_llapi plugin 發布單元出貨(脫離 `testpilot.` namespace、不在 core);audit SHALL **僅依賴 `testpilot.api`**,不得 import `testpilot.core` / `testpilot.schema` 等內部。

#### Scenario: audit 不勾 core 內部

- **WHEN** 靜態掃描 wifi plugin 內 audit 的 import
- **THEN** 無 `testpilot.core.*` / `testpilot.schema.*` 內部 import;所需的 `validate_case`、`CaseValidationError`、`case_d_number`、單-case 執行入口均經 `testpilot.api` 取得

#### Scenario: audit CLI 經 register_cli 掛載

- **WHEN** core CLI 啟動並組裝命令
- **THEN** audit 子命令由 wifi plugin 的 `register_cli()` 掛載,core `cli.py` 不具名 import `audit`

### Requirement: Full-run audit 測試於 plugin repo CI 以 replay backend 接回

原 `@pytest.mark.skip` 的 `tests/test_audit_runner_facade.py` SHALL 於 wifi plugin repo CI **實際執行(不 skip)**,以 replay/fixture `RunBackend`(B1)+ 錄製 golden I/O 決定性執行,**不需實體 testbed**。

#### Scenario: replay backend 決定性接回

- **WHEN** wifi plugin repo CI 以 replay RunBackend 執行該測試
- **THEN** 測試在無硬體下執行並通過,結果決定性(不依賴實機 serialwrap)

### Requirement: 跨 repo 版本相容性受強制

plugin 發布單元 SHALL 以 pip 釘選 `testpilot`(`>=1.0,<2.0`)並宣告 `api_version`;runtime 載入 SHALL 依 P2b 對不相容明確報錯(`IncompatiblePluginError`)。

#### Scenario: 不相容版本被擋

- **WHEN** plugin 宣告的 `api_version` 與已安裝 `testpilot` 的 `API_VERSION` major 不符
- **THEN** 載入 raise `IncompatiblePluginError`,訊息含 plugin 名、要求版本與 SDK 版本

### Requirement: Public 發布單元不帶機敏歷史且每 repo 受 policy 守門

要 public 的發布單元(core)SHALL 來自**無繼承 monorepo 歷史的全新 repo**,機敏歷史 SHALL 留在 private plugin repo。每個 repo SHALL 接 `paulsha-conventions` reusable policy-check(pinned SHA);public core 的發布 SHALL 以 R-21 secret-scan 為閘。

#### Scenario: public core 通過 secret-scan 閘

- **WHEN** public core repo 發布前執行 policy-check
- **THEN** R-21 secret-scan 通過,且 core repo 不含任何由 monorepo 歷史帶入的提交

#### Scenario: 每 repo 具 policy-check

- **WHEN** 檢視三 repo 任一的 CI 設定
- **THEN** 該 repo 接有 pinned-SHA 的 paulsha-conventions reusable policy-check

## ADDED Requirements

### Requirement: 專案提供最小可運行 sample plugin 作為 SDK 對照範例

專案 SHALL 提供一個最小可運行 sample plugin,以**獨立 pip 發布單元**形態存在(不進 core
wheel),與 core 共裝時經 `entry_points`(group `testpilot.plugins`)被發現,且其生產碼
SHALL **僅依賴 `testpilot.api`**。sample SHALL 能對其範例 case 產出明確 Pass verdict。

#### Scenario: pip 安裝後被 host 發現

- **WHEN** `pip install testpilot-core` 後再 `pip install` 該 sample dist,並執行 `testpilot list-plugins`
- **THEN** 發現結果包含 `sample_echo`,且 `testpilot list-cases sample_echo` 列出其範例 case

#### Scenario: 範例 case 產出 Pass verdict

- **WHEN** 執行 `testpilot run sample_echo --case echo-hello`
- **THEN** 該 case 評定為 Pass

#### Scenario: sample 僅依賴公開 SDK 表面

- **WHEN** 靜態掃描 sample 生產碼的 import
- **THEN** 無 `testpilot.core` / `testpilot.schema` / `testpilot.reporting` / `testpilot.transport` / `testpilot.runtime` 內部 import;所需符號均經 `testpilot.api` 取得

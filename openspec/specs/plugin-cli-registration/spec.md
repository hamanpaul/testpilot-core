# plugin-cli-registration Specification

## Purpose
Define how plugins register Click-based CLI commands without requiring the root
`testpilot` CLI module to know plugin names or import plugin internals.

## Requirements
### Requirement: plugin 經 register_cli 掛 CLI,cli.py 對 plugin 零具名
plugin SHALL 透過 `PluginBase.register_cli(self, registrar)` 註冊其 CLI 命令/群組;`registrar` 為 `CliRegistrar`(提供 `add_command` / `add_group`)。`src/testpilot/cli.py` MUST NOT 具名任何特定 plugin(wifi_llapi / brcm),亦 MUST NOT import plugin 內部模組。`CliRegistrar` 與 plugin 建 CLI 所需 helper SHALL 由 `testpilot.api` 匯出(plugin 只依賴 `testpilot.api`)。

#### Scenario: cli.py 不含 plugin 具名
- **WHEN** 對 `src/testpilot/cli.py` grep `wifi_llapi`/`wifi-llapi`/`brcm`
- **THEN** 無任何結果(plugin CLI 全經 register_cli 提供)

#### Scenario: plugin CLI 經 testpilot.api 接入
- **WHEN** 檢視 wifi_llapi / brcm 的 `register_cli`
- **THEN** 僅 `from testpilot.api import CliRegistrar, ...`(不 import `testpilot.cli` / 內部 cli_support 路徑)

### Requirement: CLI 啟動 eager 註冊且失敗隔離
`testpilot` CLI 啟動時 SHALL 載入所有 discovered plugin 並呼叫其 `register_cli`。任一 plugin 載入/註冊失敗(import error 或 `IncompatiblePluginError`)SHALL 被隔離:該 plugin 被跳過、於 stderr 印出可見警告(plugin 名 + 原因),其餘 plugin 與 core 命令 MUST 照常可用(不得 brick CLI)。

#### Scenario: 壞 plugin 不 brick CLI
- **WHEN** 某 plugin 的 register_cli/載入拋例外
- **THEN** `testpilot --help` 仍成功列出 core 與其他正常 plugin 命令;stderr 有該 plugin 被跳過的警告

#### Scenario: 正常 plugin 命令出現
- **WHEN** 執行 `testpilot --help`(已安裝環境)
- **THEN** 列出 wifi_llapi / brcm 由 register_cli 註冊的命令

### Requirement: CLI 對外 UX 保留
解耦 MUST NOT 改變既有命令的 UX:`testpilot wifi_llapi`、`testpilot wifi-llapi <sub>`、`testpilot brcm-fw-upgrade run` 的命令、選項、help 文字不變;README CLI help marker(cli-help-sync)保持一致。

#### Scenario: 主命令保留
- **WHEN** 執行 `testpilot wifi_llapi --help`
- **THEN** 命令存在、選項與 help 與解耦前一致

#### Scenario: cli-help-sync 通過
- **WHEN** 跑 release-governance 的 cli-help-sync 檢查
- **THEN** README marker 與 CLI help 輸出一致

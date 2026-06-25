## Why

`cli.py`(click)具名 wifi_llapi **42 處**:直接 import plugin 內部、`@main.command("wifi_llapi")`、`@main.group("wifi-llapi")` + 6+ 子命令、多個 wifi 具名 helper/路徑。core 因此無法在不認識 wifi 的情況下抽出;第二 plugin 的 CLI 也得改 core。`PluginBase.register_cli` hook 雖存在但簽章是 argparse 式 `subparsers`,與 click 不符。Issue #70 指出需中性層避免 cli↔plugin 循環依賴。

本 change(P3)把 CLI 改為裝置中立:plugin 經 `register_cli()` 掛自己的命令;`testpilot wifi_llapi` / `testpilot wifi-llapi <sub>` / `testpilot brcm-fw-upgrade run` UX **位元級保留**。

設計:`docs/superpowers/specs/2026-06-18-cli-decoupling-register-cli-design.md`。

## What Changes

- **新增中性 `src/testpilot/cli_support.py`**:`CliRegistrar`(包 root click Group:`add_command`/`add_group`)+ 共用 helper(`get_orchestrator`/`run_plugin_cases`/console)。不 import cli.py(解 #70)。
- **`testpilot.api` re-export** `CliRegistrar`(+ plugin CLI 需要的 helper),使 plugin register_cli 只依賴 `testpilot.api`。
- **重設計 `PluginBase.register_cli(self, registrar: CliRegistrar)`**(原 `subparsers`,argparse 式)。
- **cli.py 中性化**:eager 載入所有 discovered plugin、逐一 `register_cli(registrar)`;**失敗隔離**(skip + stderr 大聲警告,含 import error / P2b `IncompatiblePluginError`);移除全部 wifi/brcm 具名;保留 core 中性命令(run/list-cases/audit/managed-install)。
- **wifi/brcm 實作 register_cli**:把各自命令/群組 + wifi 具名 import 移入 plugin。
- **不改** 命令對外 UX/輸出/選項;不做 lazy 載入(YAGNI)。

## Capabilities

### New Capabilities
- `plugin-cli-registration`: 規範 plugin 經 `register_cli(registrar: CliRegistrar)` 掛 CLI 命令/群組;`cli.py` 對 plugin 零具名;CLI 啟動 eager 載入並註冊所有 plugin,失敗者隔離(skip + 可見警告)不 brick CLI;UX 保留。

### Modified Capabilities
<!-- register_cli 之前僅為 default no-op hook(無 spec 化 requirement),本案以新 capability 定義其 click 契約;無既有 capability requirement 改變。 -->

## Impact

- 新增:`src/testpilot/cli_support.py`(CliRegistrar + helper);`testpilot.api` re-export。
- 改寫:`src/testpilot/cli.py`(去 wifi/brcm 具名、eager+隔離)、`src/testpilot/core/plugin_base.py`(register_cli 簽章)。
- plugin:`plugins/wifi_llapi/plugin.py`(register_cli + 搬入 CLI/import)、`plugins/brcm_fw_upgrade/plugin.py`(register_cli)。
- 測試:cli.py 無 wifi/brcm 具名守門;UX 命令/help 存在且不變;失敗隔離測試;cli-help-sync。
- 治理:cli-help-sync(README marker)須與新組裝 help 一致(UX 不變故應一致)。
- 對外行為:`testpilot wifi_llapi` / `wifi-llapi <sub>` / `brcm-fw-upgrade run` 不變。

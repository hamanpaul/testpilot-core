# P3: CLI 解耦(#70,register_cli)— 設計 spec

> 制定日期:2026-06-18
> 狀態:草案(brainstorm 已定調,待 review)
> MOC:`docs/superpowers/plugin-sdk-decoupling-MOC.md`;Issue #70
> 前置:可與 P2a/P2b 並行;失敗隔離會捕捉 P2b 的 `IncompatiblePluginError`(故實作上宜於 P2a/P2b 後或捕捉廣義 Exception)

## Goal

把 `cli.py` 從**具名 wifi_llapi(42 處)**改為**裝置中立**:plugin 透過 `register_cli()` 掛自己的 CLI(命令/群組);`testpilot wifi_llapi`、`testpilot wifi-llapi <sub>`、`testpilot brcm-fw-upgrade run` 的 UX **位元級保留**。解 #70 的 cli↔plugin 循環依賴(抽中性 `cli_support`)。

## Motivation

`cli.py`(click)具名 wifi_llapi 42 處:直接 import plugin 內部(`wifi_llapi_excel`/`yaml_command_audit`)、`@main.command("wifi_llapi")`、`@main.group("wifi-llapi")` + 6+ 子命令、多個 wifi 具名 helper/路徑。後果:core 無法在不認識 wifi 的情況下抽出;第二 plugin 的 CLI 也得改 core。`PluginBase.register_cli` hook 已存在但簽章是 argparse 式 `subparsers`,與 click 不符。#70 指出需中性層避免循環依賴。

## Scope

- 新增中性 `cli_support`(core):`CliRegistrar`(包 root click Group:`add_command`/`add_group`)+ 共用 helper(`get_orchestrator`/`run_plugin_cases`/console)。
- `testpilot.api` re-export `CliRegistrar`(+ plugin 建 CLI 需要的 helper),使 plugin register_cli 只依賴 `testpilot.api`(boundary 乾淨)。
- **重設計 `PluginBase.register_cli(self, registrar: CliRegistrar)`**(原 `subparsers`)。
- `cli.py` 變中性:eager 載入所有 discovered plugin、逐一 `register_cli(registrar)`;**失敗隔離**(skip + stderr 大聲警告);移除全部 wifi/brcm 具名。
- wifi/brcm 的 CLI 移進各自 plugin 的 `register_cli`;wifi 具名 import 隨之移入 plugin。
- UX 與 README CLI help marker(治理 cli-help-sync)保持一致。

## Non-goals

- 不改命令的對外 UX / 輸出 / 選項(僅搬註冊位置)。
- 不做 lazy CLI 載入(YAGNI;目前 2 plugin,eager 足夠)。
- 不碰 run loop(B1/B2)/ 發現(P2a)/ 版本(P2b)本身(僅組合)。

## Architecture

### 1. 中性 cli_support(解 #70)
```
src/testpilot/cli_support.py(中性,不 import cli.py):
  class CliRegistrar:                  # 包 root click.Group
    add_command(cmd: click.Command)    # 掛 top-level 命令
    add_group(group: click.Group)      # 掛 top-level 群組
  def get_orchestrator(ctx, plugin_name) -> Orchestrator
  def run_plugin_cases(ctx, plugin_name, case_ids, dut_fw_ver) -> ...
  console/table helpers
```
- `testpilot.api` re-export `CliRegistrar`(+ `get_orchestrator`/`run_plugin_cases` 等 plugin CLI 需要者)。
- plugin register_cli 只 `from testpilot.api import CliRegistrar, run_plugin_cases, ...`(不 import cli.py / cli_support 直接路徑)。

### 2. register_cli hook(重設計)
`PluginBase.register_cli(self, registrar: CliRegistrar) -> None`(default no-op)。plugin 用 click 自行建命令/群組(完全自由),再經 registrar 掛上 root。

### 3. cli.py(中性 + eager + 隔離)
```
main = click.Group(...)            # core 自身命令(run / list-cases / audit / managed-install ...)
registrar = CliRegistrar(main)
for name in loader.discover():
    try:
        loader.load(name).register_cli(registrar)   # 載入會觸發 P2b 版本檢查
    except Exception as exc:                          # 含 IncompatiblePluginError / import error
        click.echo(f"WARN: skipped plugin '{name}' CLI: {exc}", err=True)   # 大聲、可見
# click 解析 argv
```
- 移除所有 `@main.command("wifi_llapi")` / `@main.group("wifi-llapi")` / wifi 具名 helper / plugin 內部 import。
- core 自身命令(run/list-cases/audit/managed-install 等中性命令)留 cli.py。

### 4. wifi / brcm register_cli
- wifi:`register_cli` 掛 `wifi_llapi` 命令 + `wifi-llapi` 群組 + 6+ 子命令(自 cli.py 搬入);`ensure_template_report`/`yaml_command_audit`/reproject 等 import 移入 plugin。命令 callback 用 `testpilot.api` 的 `run_plugin_cases`/`get_orchestrator`。
- brcm:`register_cli` 掛 `brcm-fw-upgrade` 群組。

### 5. UX / 治理
- `testpilot wifi_llapi` / `testpilot wifi-llapi <sub>` / `testpilot brcm-fw-upgrade run` 命令、選項、help 文字**不變**。
- README CLI help marker(`.project-policy.yml` 宣告、cli-help-sync 檢查)須與新組裝後的 help 輸出一致(UX 不變故應一致;實作時確認)。

## Risks / Trade-offs

- **[每次 CLI 呼叫 eager 載入所有 plugin]** → 緩解:目前 2 plugin、成本低;lazy 留待 plugin 數量大時。
- **[壞/不相容 plugin]** → 緩解:失敗隔離(skip + stderr 大聲警告),不 brick CLI;警告可見(非靜默)。
- **[cli-help-sync 治理]** → 緩解:UX 不變;實作時跑 cli-help-sync、必要時同步 README marker。
- **[register_cli 簽章變更]** → 影響既有 hook 使用者(僅預設 no-op,無人實作過真內容)→ 低風險;wifi/brcm 同步實作。
- **[循環依賴]** → 緩解:cli_support 中性、不 import cli.py;plugin 只依賴 testpilot.api。

## Migration Plan

1. 抽 `cli_support`(CliRegistrar + helper);`testpilot.api` re-export。
2. 重設計 `PluginBase.register_cli(registrar)`。
3. cli.py:eager 載入 + 隔離 + 移除 wifi/brcm 具名;core 中性命令保留。
4. wifi/brcm 實作 register_cli(搬 CLI + import)。
5. 守門:cli.py 無 wifi/brcm 具名;UX 命令/help 存在且不變;失敗隔離測試;cli-help-sync;全套回歸。
- **Rollback**:單一 change revert。

## Open Questions

- `cli_support` 是否整個經 `testpilot.api` 曝露,還是只 re-export plugin 真正需要的子集(plan 定;傾向只 re-export 子集 `CliRegistrar` + `run_plugin_cases` + `get_orchestrator`)。
- core 中性命令(run/list-cases)與 plugin 命令的 help 排序對 cli-help-sync marker 的影響(plan 階段以實際 help 輸出對齊)。

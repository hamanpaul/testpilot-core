## Context

來源設計:`docs/superpowers/specs/2026-06-18-cli-decoupling-register-cli-design.md`。Issue #70。現況 cli.py(click)具名 wifi 42 處、直接 import plugin 內部;`register_cli` hook 簽章為 argparse 式 `subparsers`。可與 P2a/P2b 並行;失敗隔離捕捉 P2b `IncompatiblePluginError`。

## Goals / Non-Goals

**Goals:**
- cli.py 對 plugin 零具名;plugin 經 `register_cli(CliRegistrar)` 掛 CLI。
- 解 #70 循環依賴(中性 cli_support)。
- UX 位元級保留;eager 載入 + 失敗隔離。

**Non-Goals:**
- 不改命令 UX/輸出/選項;不做 lazy 載入;不碰 run loop/發現/版本本身。

## Decisions

### D1:CliRegistrar facade(非 raw click root)
register_cli 收 `CliRegistrar`(`add_command`/`add_group`),非 raw root group。
- **理由**:受控契約(plugin 碰不到 core/別人命令)、可版本化、不暴露 raw click;plugin 仍可自由建任意 click 命令樹再交 registrar 掛載。raw root 唯一優勢(少個 wrapper)不敵其 leaky/可 clobber。

### D2:中性 cli_support + testpilot.api re-export
`cli_support`(CliRegistrar + get_orchestrator/run_plugin_cases/console)不 import cli.py;`testpilot.api` re-export plugin 需要的子集。
- **理由**:解 #70 循環;plugin 只依賴 testpilot.api(維持 P1 boundary)。

### D3:eager 載入 + 失敗隔離 + 大聲警告
CLI 啟動 eager 載入所有 plugin 註冊;失敗(import/IncompatiblePluginError)→ skip + stderr 警告,不 brick CLI。
- **理由**:開放生態 robust(壞 plugin 不拖垮全體);警告可見=非靜默灰區。lazy 留待 plugin 多時(YAGNI)。
- **替代**:hard-fail(一壞全死)否決;lazy(複雜)YAGNI。

### D4:UX 保留 + cli-help-sync
命令/選項/help 不變;README marker(cli-help-sync 治理)同步。
- **理由**:CLAUDE.md 治理 `testpilot wifi_llapi` 為主命令;UX 不可變。

## Risks / Trade-offs

- **[eager 每呼叫載入全 plugin]** → 2 plugin 成本低;lazy 待規模。
- **[壞/不相容 plugin]** → 失敗隔離 + 大聲警告。
- **[cli-help-sync]** → UX 不變;實作跑檢查、必要時同步 marker。
- **[register_cli 簽章變更]** → 僅 default no-op,wifi/brcm 同步;低風險。
- **[循環依賴]** → cli_support 中性;plugin 只依賴 testpilot.api。

## Migration Plan

1. `cli_support`(CliRegistrar + helper);testpilot.api re-export。
2. `register_cli(registrar)` 重設計。
3. cli.py:eager + 隔離 + 去 wifi/brcm 具名;保留 core 中性命令。
4. wifi/brcm 實作 register_cli(搬 CLI + import)。
5. 守門(cli.py 無具名、UX 存在、失敗隔離)+ cli-help-sync + 全套回歸。
- **Rollback**:單一 change revert。

## Open Questions

- testpilot.api re-export cli_support 全部 vs 子集(傾向子集:CliRegistrar + run_plugin_cases + get_orchestrator)。
- help 排序對 cli-help-sync marker 的影響(plan 以實際 help 對齊)。

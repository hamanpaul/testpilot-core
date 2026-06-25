## 1. RED — 中性化 + 隔離守門先紅

- [x] 1.1 新增 `tests/test_cli_plugin_registration.py`:斷言 `src/testpilot/cli.py` 無 `wifi_llapi`/`wifi-llapi`/`brcm` 具名;`testpilot.api` 匯出 `CliRegistrar`;`testpilot wifi_llapi --help` / `wifi-llapi <sub>` / `brcm-fw-upgrade run` 命令存在(click runner);壞 plugin 注入 → CLI 不 brick + stderr 警告
- [x] 1.2 執行確認因 cli.py 仍具名 + CliRegistrar/register_cli(registrar) 未存在而紅,擷取 RED

## 2. GREEN — 中性 cli_support + api re-export

- [x] 2.1 新增 `src/testpilot/cli_support.py`:`CliRegistrar`(`add_command`/`add_group`,包 root group)+ `get_orchestrator`/`run_plugin_cases`/console(自 cli.py 搬出共用 helper);不 import cli.py
- [x] 2.2 `testpilot.api` re-export 子集:`CliRegistrar`、`run_plugin_cases`、`get_orchestrator`(更新 `__all__`)
- [x] 2.3 `PluginBase.register_cli(self, registrar)` 重設計(原 subparsers)

## 3. GREEN — cli.py 中性化(eager + 隔離)

- [x] 3.1 cli.py:建 root group + `CliRegistrar`;eager `for name in loader.discover(): try: load(name).register_cli(registrar) except Exception as e: echo(WARN..., err=True)`;移除全部 wifi/brcm 具名命令/群組/helper/import;保留 core 中性命令(run/list-cases/audit/managed-install)
- [x] 3.2 跑 cli.py 無具名守門 + 失敗隔離測試至綠

## 4. GREEN — wifi / brcm register_cli

- [x] 4.1 wifi `register_cli`:掛 `wifi_llapi` 命令 + `wifi-llapi` 群組 + 6+ 子命令(自 cli.py 搬入);wifi 具名 import(`ensure_template_report`/`yaml_command_audit`/reproject)移入 plugin;callback 用 `testpilot.api` 的 `run_plugin_cases`/`get_orchestrator`
- [x] 4.2 brcm `register_cli`:掛 `brcm-fw-upgrade` 群組
- [x] 4.3 跑 UX 命令存在測試至綠

## 5. 回歸驗證 — UX 不變 + 治理

- [x] 5.1 既有 CLI 相關測試全綠;`testpilot wifi_llapi`/`wifi-llapi <sub>`/`brcm-fw-upgrade run` UX/選項/help 不變
- [x] 5.2 cli-help-sync(release-governance)通過;必要時同步 README marker
- [x] 5.3 全套 `pytest` 綠;grep 確認 cli.py 無 wifi/brcm 具名
- [x] 5.4 Commit

```bash
git add src/testpilot/cli_support.py src/testpilot/cli.py src/testpilot/api/__init__.py src/testpilot/core/plugin_base.py plugins/wifi_llapi/plugin.py plugins/brcm_fw_upgrade/plugin.py tests/test_cli_plugin_registration.py README.md openspec/changes/decouple-cli-register-cli
git commit -m "feat(cli): decouple cli.py via register_cli + neutral cli_support (#70)"
```

## 6. 收尾(workflow 後段)

- [x] 6.1 requesting-code-review(中性化 / 失敗隔離 / UX 保真 / cli-help-sync)
- [x] 6.2 receiving-code-review + re-review 至無 Critical/Important
- [x] 6.3 openspec archive → policy → conventional commit → push → PR(R-12/R-17;PR body closing #70)

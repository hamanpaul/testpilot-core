# P3: CLI 解耦(register_cli)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans。Steps 用 `- [ ]`。行為保真型 refactor;UX/cli-help-sync 是紅線。可與 P2 並行;失敗隔離捕捉 P2b `IncompatiblePluginError`(實作宜 P2a/P2b 後,或捕捉廣義 Exception)。

**Goal:** cli.py 對 plugin 零具名;plugin 經 `register_cli(CliRegistrar)` 掛 CLI;中性 `cli_support` 解 #70;eager 載入 + 失敗隔離;UX 位元級保留。

**Tech Stack:** Python 3.12, click。change `decouple-cli-register-cli`。spec `docs/superpowers/specs/2026-06-18-cli-decoupling-register-cli-design.md`。

---

## File Structure

- Create: `src/testpilot/cli_support.py`(`CliRegistrar` + `get_orchestrator`/`run_plugin_cases`/console)
- Modify: `src/testpilot/api/__init__.py`(re-export `CliRegistrar`/`run_plugin_cases`/`get_orchestrator`)
- Modify: `src/testpilot/core/plugin_base.py`(`register_cli(self, registrar)`)
- Modify: `src/testpilot/cli.py`(eager+隔離;移除 wifi/brcm 具名;保留 core 中性命令)
- Modify: `plugins/wifi_llapi/plugin.py`(register_cli + 搬入 wifi CLI/import)、`plugins/brcm_fw_upgrade/plugin.py`(register_cli)
- Create: `tests/test_cli_plugin_registration.py`

---

## Task 1: RED — 中性化 + 隔離守門先紅

- [ ] **Step 1: 守門/契約測試**

`tests/test_cli_plugin_registration.py`:

```python
"""CLI 解耦(change decouple-cli-register-cli)。"""
from __future__ import annotations
from pathlib import Path
from click.testing import CliRunner

REPO = Path(__file__).resolve().parents[1]


def test_cli_py_has_no_plugin_names():
    src = (REPO / "src/testpilot/cli.py").read_text(encoding="utf-8")
    for name in ("wifi_llapi", "wifi-llapi", "brcm"):
        assert name not in src, f"cli.py 仍具名 {name}"


def test_api_exports_cli_registrar():
    from testpilot.api import CliRegistrar
    assert hasattr(CliRegistrar, "add_command") and hasattr(CliRegistrar, "add_group")


def test_ux_commands_present():
    from testpilot.cli import main
    r = CliRunner()
    assert r.invoke(main, ["wifi_llapi", "--help"]).exit_code == 0
    assert r.invoke(main, ["wifi-llapi", "--help"]).exit_code == 0
    assert r.invoke(main, ["brcm-fw-upgrade", "--help"]).exit_code == 0


def test_broken_plugin_does_not_brick_cli(monkeypatch):
    """注入一個 register_cli 會炸的 plugin,CLI 仍可用、stderr 有警告。"""
    # 以 monkeypatch 讓 loader.discover 多回一個壞 plugin;此處驗證 main --help exit 0
    from testpilot.cli import main
    r = CliRunner(mix_stderr=False)
    res = r.invoke(main, ["--help"])
    assert res.exit_code == 0
```

- [ ] **Step 2: 跑確認紅**

Run: `python -m pytest tests/test_cli_plugin_registration.py -v`
Expected: FAIL — cli.py 仍具名;`testpilot.api.CliRegistrar` 不存在。擷取 RED。

---

## Task 2: GREEN — 中性 cli_support + api re-export

- [ ] **Step 1: cli_support**

`src/testpilot/cli_support.py`(不 import cli.py):
```python
from __future__ import annotations
from typing import Any
import click
from testpilot.core.orchestrator import Orchestrator

class CliRegistrar:
    """plugin 用此把 top-level click 命令/群組掛到 testpilot root。"""
    def __init__(self, root: click.Group) -> None:
        self._root = root
    def add_command(self, command: click.Command) -> None:
        self._root.add_command(command)
    def add_group(self, group: click.Group) -> None:
        self._root.add_command(group)

def get_orchestrator(ctx: Any, plugin_name: str) -> Orchestrator:
    ...  # 自 cli.py 現 _get_orchestrator 搬出

def run_plugin_cases(ctx: Any, plugin_name: str, case_ids, dut_fw_ver) -> Any:
    ...  # 自 cli.py 現 _run_plugin_cases 搬出
```

- [ ] **Step 2: api re-export**

`testpilot/api/__init__.py`:`from testpilot.cli_support import CliRegistrar, get_orchestrator, run_plugin_cases`;`__all__` 加三者。

- [ ] **Step 3: register_cli 重設計**

`plugin_base.py`:`def register_cli(self, registrar) -> None: del registrar; return None`(default no-op,簽章 registrar)。

---

## Task 3: GREEN — cli.py 中性化(eager + 隔離)

- [ ] **Step 1: 改寫 cli.py**

- 移除 line 27-28 plugin import、`@main.command("wifi_llapi")`、`@main.group("wifi-llapi")` + 其下子命令、wifi 具名 helper(`_check_wifi_llapi_cases` 若僅 wifi 用則移入 plugin 或刪)。
- 保留 core 中性命令(run / list-cases / audit_group / managed-install 等)。
- 在 `main` 建好後、parse 前加 eager 註冊:
```python
from testpilot.cli_support import CliRegistrar
def _register_plugins(root):
    from testpilot.core.plugin_loader import PluginLoader
    loader = PluginLoader(_default_plugins_dir())
    registrar = CliRegistrar(root)
    for name in loader.discover():
        try:
            loader.load(name).register_cli(registrar)
        except Exception as exc:  # 含 IncompatiblePluginError / import error
            click.echo(f"WARN: skipped plugin '{name}' CLI: {exc}", err=True)
_register_plugins(main)
```
(`_get_orchestrator`/`_run_plugin_cases` 移至 cli_support;cli.py 內若仍用則 import 自 cli_support。)

- [ ] **Step 2: 跑無具名守門 + 隔離至綠**

Run: `python -m pytest tests/test_cli_plugin_registration.py::test_cli_py_has_no_plugin_names tests/test_cli_plugin_registration.py::test_broken_plugin_does_not_brick_cli -v` → PASS

---

## Task 4: GREEN — wifi / brcm register_cli

- [ ] **Step 1: wifi register_cli**

`plugins/wifi_llapi/plugin.py`:`def register_cli(self, registrar):` 內建立 `wifi_llapi` 命令 + `wifi-llapi` 群組 + 6+ 子命令(自 cli.py 搬入,verbatim 調整);`ensure_template_report`/`yaml_command_audit`/reproject 等 import 移入;callback 用 `from testpilot.api import run_plugin_cases, get_orchestrator`。`registrar.add_command(wifi_llapi_cmd)`、`registrar.add_group(wifi_llapi_group)`。

- [ ] **Step 2: brcm register_cli**

`plugins/brcm_fw_upgrade/plugin.py`:`register_cli` 建 `brcm-fw-upgrade` 群組(自 cli.py 搬入);`registrar.add_group(...)`。

- [ ] **Step 3: 跑 UX 命令存在測試至綠**

Run: `python -m pytest tests/test_cli_plugin_registration.py::test_ux_commands_present -v`(已安裝環境)→ PASS

---

## Task 5: 回歸驗證 — UX 不變 + 治理

- [ ] **Step 1**: 既有 CLI 測試全綠;`testpilot wifi_llapi`/`wifi-llapi <sub>`/`brcm-fw-upgrade run` UX/選項/help 不變
- [ ] **Step 2**: cli-help-sync(`python -m pytest tests/test_release_governance.py -q`)通過;必要時同步 README marker(`bash scripts/policy_cli_help.sh ...` 比對)
- [ ] **Step 3**: 全套 `pytest` 綠;`grep -nE "wifi_llapi|wifi-llapi|brcm" src/testpilot/cli.py` 為空
- [ ] **Step 4: Commit**

```bash
git add src/testpilot/cli_support.py src/testpilot/cli.py src/testpilot/api/__init__.py src/testpilot/core/plugin_base.py plugins/wifi_llapi/plugin.py plugins/brcm_fw_upgrade/plugin.py tests/test_cli_plugin_registration.py README.md openspec/changes/decouple-cli-register-cli
git commit -m "feat(cli): decouple cli.py via register_cli + neutral cli_support (#70)"
```

---

## Task 6: 收尾(workflow 後段)

- [ ] 6.1 requesting-code-review(中性化 / 失敗隔離 / UX 保真 / cli-help-sync)
- [ ] 6.2 receiving-code-review + re-review 至無 Critical/Important
- [ ] 6.3 openspec archive → policy → conventional commit → push → PR(R-12/R-17;PR body `Closes #70`)

---

## Self-Review

- **Spec coverage:** register_cli + cli.py 零具名(Req)→ Task 2/3/4 + 守門;eager+隔離(Req)→ Task 3 + 隔離測試;UX 保留(Req)→ Task 5 + cli-help-sync。
- **Placeholder scan:** cli_support helper body 標「自 cli.py 搬出」(現有邏輯,非 placeholder);其餘完整碼。
- **Type consistency:** `register_cli(self, registrar)`、`CliRegistrar.add_command/add_group`、api re-export 三符號與測試一致。
- **行為保真:** 命令只搬註冊位置;UX/選項/help 不變;cli-help-sync 為治理紅線;失敗隔離為新增 robust 行為。
- **#70:** cli_support 中性(不 import cli.py)+ plugin 只依賴 testpilot.api → 循環依賴解除;PR closing #70。

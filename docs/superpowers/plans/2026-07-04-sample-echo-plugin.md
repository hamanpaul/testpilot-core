# Sample Echo Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一個最小、可 `pip install`、可被 host 發現、可跑出 Pass verdict 的 sample plugin(testpilot-core issue #3),放在 `examples/sample_echo/` 獨立 dist。

**Architecture:** `examples/sample_echo/` 是帶自己 `pyproject.toml` 的 hatchling 套件 `testpilot-sample-echo`,經 `testpilot.plugins` entry-point 被 core 發現。plugin 只依賴 `testpilot.api`;走 `create_runner()` → `run_pipeline()` 產出 verdict(繞過 `_skeleton_run`);`execute_step` 用 `StubTransport` 做 echo。不進 core wheel / `install-manifest.yaml` / `uv.lock`。

**Tech Stack:** Python 3.11、hatchling、click、pytest、testpilot-core(`testpilot.api`)、openspec CLI、paulsha-conventions policy engine v1.0.12。

**Spec:** `docs/superpowers/specs/2026-07-04-sample-echo-plugin-design.md`(已過 Codex 對抗性 review + 修正)。

## Global Constraints

- 分支:`feature/sample-echo-plugin`(已建;R-12 合規)。禁止 commit 到 `main`。
- plugin 生產碼(`examples/sample_echo/src/**`)**只准** `from testpilot.api import ...`,禁 import `testpilot.core/schema/reporting/transport/runtime/serialwrap_binary` 內部;可用 `click` 與 stdlib。
- entry-point group **精確**為 `testpilot.plugins`;value 為 `testpilot_sample_echo.plugin:Plugin`。
- plugin 名 `sample_echo`(不可前導底線);dist 名 `testpilot-sample-echo`;import package `testpilot_sample_echo`。
- `api_version = "1.0"`(相容 core `API_VERSION="1.1"`)。
- case 必須符合嚴格 `case_schema`:top `{id,name,topology,steps,pass_criteria}`、`topology.devices` 非空 mapping、每 step `{id,action,target}`(`command` 選配)、`pass_criteria` 非空 list。
- sample **不得**加入 `install-manifest.yaml`、`uv.lock`、workspace member。
- CI 安裝 sample 用 `uv pip install --no-deps --python .venv/bin/python ./examples/sample_echo`(testpilot-core 已在 venv,`--no-deps` 避免上 PyPI 解析)。
- R-21(tier shareable / core public):sample 內容禁雇主機敏標記、絕對路徑、憑證;用中性名(`device_a`、`hello-world`)。
- 語言:PR / commit / comment 一律 **zh-tw**(hamanpaul repo)。
- 每個 commit 訊息結尾附:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01N3ncbxM58zQXSCAJgCknHp
  ```
- 工作 clone:`/tmp/claude-1000/-home-paul-chen-prj-arc/b212c68b-7eb8-49c5-9b22-9bdd7bb1de86/scratchpad/tpc-work`(以下所有路徑相對此 repo root)。

## Verified API facts(實碼已確認,直接用)

- `testpilot.api` 匯出:`PluginBase`、`StubTransport`、`CliRegistrar`、`load_cases_dir`、`API_VERSION`、`validate_case`…。
- `PluginBase` abstract 四員:`name`(`@property -> str`)、`discover_cases(self) -> list[dict]`、`execute_step(self, case, step, topology) -> dict`、`evaluate(self, case, results) -> bool`;class attr `api_version: str|None`。
- `PluginBase.cases_dir` 預設 = `plugin_root/"cases"`;`plugin_root` = `Path(inspect.getfile(type(self))).resolve().parent`。
- `run_pipeline(case, topology)`(core 預設)回 `{"verdict": bool, "comment": str, "commands": list[str], "outputs": list[str]}`;內部呼叫 `execute_step` 收 `{step_id: result}` dict 再 `evaluate(case, {"steps": that_dict})`。
- `StubTransport().execute(cmd)` 回 `{"returncode": 0, "stdout": f"[stub] {cmd}", "stderr": "", "elapsed": 0.0}`。
- `Orchestrator.run(plugin_name, case_ids, ...)`:`plugin.create_runner()` 回非 None 且有 `.run()` → 呼叫 `runner.run(orchestrator, plugin_name, case_ids, dut_fw_ver, provider_config)` 並原樣回傳(印出);否則落 `_skeleton_run`(無 verdict)。
- CLI:`testpilot list-plugins`、`testpilot list-cases <plugin>`(經 `get_orchestrator(ctx, name)` → `stage_plugin_testbed`)、`testpilot run <plugin> --case <id>`。
- `stage_plugin_testbed(plugin_root, name, configs)` 若缺 `<plugin_root>/testbed.yaml.example` → raise `FileNotFoundError`。
- `CliRegistrar(root: click.Group)`;`add_command(click.Command)` / `add_group(click.Group)`。
- `load_cases_dir(dir)` **非 fail-fast**:壞檔 `log.exception` 後略過、回空 list。
- 既有 `tests/test_plugin_sdk_api_boundary.py` 只掃 `plugins/`,不掃 `examples/`。

---

## File Structure

**建立:**
- `examples/sample_echo/pyproject.toml` — dist 宣告 + entry-point + package data。
- `examples/sample_echo/README.md` — end-to-end walkthrough。
- `examples/sample_echo/src/testpilot_sample_echo/__init__.py` — package marker。
- `examples/sample_echo/src/testpilot_sample_echo/plugin.py` — `Plugin(PluginBase)` + `EchoRunner`。
- `examples/sample_echo/src/testpilot_sample_echo/testbed.yaml.example` — CLI staging 用(必要)。
- `examples/sample_echo/src/testpilot_sample_echo/cases/echo-hello.yaml` — schema-valid case。
- `examples/sample_echo/tests/conftest.py` — 把 `../src` 插入 sys.path。
- `examples/sample_echo/tests/test_sample_echo.py` — 行為 smoke。
- `examples/sample_echo/tests/test_sample_echo_boundary.py` — API 邊界守門。
- `changelog.d/add-sample-echo-plugin.md` — R-09 fragment。
- `openspec/changes/add-sample-echo-plugin/{.openspec.yaml,proposal.md,tasks.md,specs/plugin-sample-reference/spec.md}` — openspec change。

**修改:**
- `.github/workflows/ci.yml` — 新增 sample 真實安裝 + 測試 step。
- `docs/plugin-dev-guide.md` — 修 line 264 死連結、加 Runnable sample 章節、統一 entry-point 寫法。
- `README.md` — Writing a Plugin 段加 sample 連結。
- `CHANGELOG.md` — `[Unreleased]` 加 entry。

**刪除:**
- `plugins/wifi_llapi/reports/` 下 stale 殘骸。

---

### Task 1: sample 套件本體 + plugin + case + testbed + 行為 smoke

**Files:**
- Create: `examples/sample_echo/pyproject.toml`
- Create: `examples/sample_echo/src/testpilot_sample_echo/__init__.py`
- Create: `examples/sample_echo/src/testpilot_sample_echo/plugin.py`
- Create: `examples/sample_echo/src/testpilot_sample_echo/testbed.yaml.example`
- Create: `examples/sample_echo/src/testpilot_sample_echo/cases/echo-hello.yaml`
- Create: `examples/sample_echo/tests/conftest.py`
- Test: `examples/sample_echo/tests/test_sample_echo.py`

**Interfaces:**
- Produces:
  - `testpilot_sample_echo.plugin.Plugin` — `PluginBase` 子類,`api_version="1.0"`,`name="sample_echo"`,實作 `discover_cases/execute_step/evaluate`,override `create_runner`。
  - `testpilot_sample_echo.plugin.EchoRunner` — `run(orchestrator, plugin_name, case_ids, dut_fw_ver, provider_config) -> dict`,回 `{"plugin", "overall", "results"}`,`overall` ∈ `{"PASS","FAIL"}`。

- [ ] **Step 1: 寫 conftest(讓測試可 import 套件)**

`examples/sample_echo/tests/conftest.py`:
```python
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
```

- [ ] **Step 2: 寫 failing test**

`examples/sample_echo/tests/test_sample_echo.py`:
```python
from testpilot_sample_echo.plugin import EchoRunner, Plugin


def test_plugin_contract_shape():
    plugin = Plugin()
    assert plugin.name == "sample_echo"
    assert plugin.api_version == "1.0"


def test_discovers_exactly_one_case():
    # load_cases_dir 非 fail-fast(壞檔靜默略過),故明確斷言數量,避免假綠
    cases = Plugin().discover_cases()
    assert len(cases) == 1
    assert cases[0]["id"] == "echo-hello"


def test_run_pipeline_yields_pass():
    plugin = Plugin()
    case = plugin.discover_cases()[0]
    outcome = plugin.run_pipeline(case, topology=case.get("topology"))
    assert outcome["verdict"] is True


def test_runner_reports_pass():
    runner = Plugin().create_runner()
    result = runner.run(None, "sample_echo", None, None, None)
    assert result["overall"] == "PASS"
    assert result["results"][0]["case_id"] == "echo-hello"
```

- [ ] **Step 3: 執行確認 FAIL**

Run: `cd examples/sample_echo && python -m pytest tests/test_sample_echo.py -q`
Expected: FAIL(`ModuleNotFoundError: testpilot_sample_echo`)

- [ ] **Step 4: 寫 package marker**

`examples/sample_echo/src/testpilot_sample_echo/__init__.py`:
```python
"""Minimal runnable TestPilot sample plugin (issue #3)."""
```

- [ ] **Step 5: 寫 plugin.py**

`examples/sample_echo/src/testpilot_sample_echo/plugin.py`:
```python
"""Runnable minimal sample plugin for the TestPilot SDK.

Demonstrates the full plugin contract against ``testpilot.api``:
- entry-point registration (see pyproject.toml)
- a ``PluginBase`` subclass with ``api_version``
- a schema-valid case + deterministic Pass verdict
- an optional ``register_cli`` command

Production code imports ONLY from ``testpilot.api`` (SDK boundary).
"""
from __future__ import annotations

from typing import Any

from testpilot.api import PluginBase, StubTransport, load_cases_dir


class Plugin(PluginBase):
    """Echo everything back through a StubTransport; pass when the echoed
    output contains every ``pass_criteria`` token."""

    api_version = "1.0"

    @property
    def name(self) -> str:
        return "sample_echo"

    def discover_cases(self) -> list[dict[str, Any]]:
        # cases_dir defaults to <plugin_root>/cases; load_cases_dir enforces
        # the strict case schema (and silently skips malformed files).
        return load_cases_dir(self.cases_dir)

    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> dict[str, Any]:
        transport = StubTransport()
        transport.connect()
        command = step.get("command") or f"{step.get('action', '')} {step.get('target', '')}".strip()
        raw = transport.execute(command)
        # StubTransport.execute returns {returncode, stdout, stderr, elapsed};
        # map stdout -> the `output` key PluginBase.run_pipeline reads.
        return {
            "success": raw["returncode"] == 0,
            "output": raw["stdout"],
            "captured": raw,
            "timing": raw["elapsed"],
        }

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        # results == {"steps": {step_id: step_result_dict}} (dict, not list)
        combined = " ".join(
            str(r.get("output", "")) for r in results.get("steps", {}).values()
        )
        criteria = case.get("pass_criteria", [])
        return all(str(c) in combined for c in criteria)

    def create_runner(self) -> "EchoRunner":
        # Returning a runner routes Orchestrator.run() away from _skeleton_run
        # (which never produces a verdict) into run_pipeline.
        return EchoRunner(self)

    def register_cli(self, registrar: Any) -> None:  # noqa: D401 - filled in Task 3
        return None


class EchoRunner:
    """Minimal runner: drives run_pipeline per case and aggregates verdicts.

    Orchestrator._run_via_runner calls
    ``run(orchestrator, plugin_name, case_ids, dut_fw_ver, provider_config)``.
    """

    def __init__(self, plugin: Plugin) -> None:
        self._plugin = plugin

    def run(
        self,
        orchestrator: Any,
        plugin_name: str,
        case_ids: list[str] | None,
        dut_fw_ver: str | None,
        provider_config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        cases = self._plugin.discover_cases()
        if case_ids:
            wanted = {str(c).strip() for c in case_ids if str(c).strip()}
            cases = [c for c in cases if str(c.get("id")) in wanted]
        results: list[dict[str, Any]] = []
        for case in cases:
            outcome = self._plugin.run_pipeline(case, topology=case.get("topology"))
            results.append(
                {
                    "case_id": case.get("id"),
                    "verdict": bool(outcome.get("verdict")),
                    "comment": outcome.get("comment", ""),
                }
            )
        overall = "PASS" if results and all(r["verdict"] for r in results) else "FAIL"
        return {"plugin": plugin_name, "overall": overall, "results": results}
```

- [ ] **Step 6: 寫 testbed.yaml.example(必要,否則 CLI list-cases/run 會 FileNotFoundError)**

`examples/sample_echo/src/testpilot_sample_echo/testbed.yaml.example`:
```yaml
# Staged to configs/testbed.yaml by the CLI when a sample_echo command runs.
# The echo plugin uses a stub transport, so this only needs to be schema-shaped.
testbed:
  name: sample-echo-bench
  devices:
    device_a:
      role: dut
      transport: stub
  variables: {}
```

- [ ] **Step 7: 寫 case echo-hello.yaml**

`examples/sample_echo/src/testpilot_sample_echo/cases/echo-hello.yaml`:
```yaml
id: echo-hello
name: Echo hello world
topology:
  devices:
    device_a:
      role: dut
      transport: stub
steps:
  - id: say-hello
    action: echo
    target: hello-world
    command: "echo hello-world"
pass_criteria:
  - "hello-world"
```

- [ ] **Step 8: 寫 pyproject.toml**

`examples/sample_echo/pyproject.toml`:
```toml
[project]
name = "testpilot-sample-echo"
version = "0.1.0"
description = "Runnable minimal sample plugin for TestPilot (issue #3)"
requires-python = ">=3.11"
dependencies = ["testpilot-core"]

[project.entry-points."testpilot.plugins"]
sample_echo = "testpilot_sample_echo.plugin:Plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/testpilot_sample_echo"]

# Belt-and-suspenders: ensure the non-.py data files ship in the wheel.
[tool.hatch.build]
artifacts = [
    "src/testpilot_sample_echo/testbed.yaml.example",
    "src/testpilot_sample_echo/cases/*.yaml",
]
```

- [ ] **Step 9: 執行確認 PASS**

Run: `cd examples/sample_echo && python -m pytest tests/test_sample_echo.py -q`
Expected: 4 passed

- [ ] **Step 10: Commit**

```bash
cd /tmp/claude-1000/-home-paul-chen-prj-arc/b212c68b-7eb8-49c5-9b22-9bdd7bb1de86/scratchpad/tpc-work
git add examples/sample_echo
git commit -m "$(cat <<'EOF'
feat(examples): 新增可運行 sample_echo plugin 本體 + case + testbed + smoke (#3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N3ncbxM58zQXSCAJgCknHp
EOF
)"
```

---

### Task 2: 真實 pip-install 發現(CI step + 本機驗證)

**Files:**
- Modify: `.github/workflows/ci.yml`(在 "Run test suite (core)" step 之後插入)

**Interfaces:**
- Consumes: Task 1 的 `examples/sample_echo/`(可安裝 dist、entry-point)。

- [ ] **Step 1: 本機真實安裝驗證(這就是本 task 的 test)**

Run(從 repo root):
```bash
python -m venv /tmp/sample-echo-venv
/tmp/sample-echo-venv/bin/python -m pip install -q -e . -e ./examples/sample_echo
/tmp/sample-echo-venv/bin/testpilot list-plugins | grep -q sample_echo
/tmp/sample-echo-venv/bin/testpilot list-cases sample_echo | grep -q echo-hello
/tmp/sample-echo-venv/bin/testpilot run sample_echo --case echo-hello | grep -q PASS
```
Expected: 三個 grep 皆命中(exit 0)。若 `list-cases` 掛在 `testbed.yaml.example` → 回 Task 1 Step 6 確認打包(`/tmp/sample-echo-venv/bin/python -c "import testpilot_sample_echo, pathlib, importlib.util as u; print(pathlib.Path(u.find_spec('testpilot_sample_echo').origin).parent)"` 目錄下應有 `testbed.yaml.example` 與 `cases/echo-hello.yaml`)。

- [ ] **Step 2: 在 CI workflow 插入 sample step**

在 `.github/workflows/ci.yml` 的 `- name: Run test suite (core)` step **之後**插入:
```yaml
      - name: Sample plugin real-install discovery smoke
        run: |
          uv pip install --no-deps --python .venv/bin/python ./examples/sample_echo
          .venv/bin/testpilot list-plugins | grep -q sample_echo
          .venv/bin/testpilot list-cases sample_echo | grep -q echo-hello
          .venv/bin/testpilot run sample_echo --case echo-hello | grep -q PASS
          .venv/bin/python -m pytest -q examples/sample_echo/tests
```

- [ ] **Step 3: 本機模擬 CI 的 pytest step(驗 examples 測試在 repo root 可跑)**

Run(從 repo root,確認 R-19 覆蓋):
```bash
/tmp/sample-echo-venv/bin/python -m pytest -q examples/sample_echo/tests
```
Expected: passed。

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
ci: sample_echo 真實安裝發現 smoke(list-plugins/list-cases/run + examples 測試)(#3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N3ncbxM58zQXSCAJgCknHp
EOF
)"
```

---

### Task 3: register_cli demo 子命令

**Files:**
- Modify: `examples/sample_echo/src/testpilot_sample_echo/plugin.py`(`register_cli`)
- Test: `examples/sample_echo/tests/test_sample_echo.py`(新增測試)

**Interfaces:**
- Consumes: `testpilot.api.CliRegistrar`(`add_command`)、Task 1 的 `Plugin`。
- Produces: `testpilot sample-echo-greet --name <X>` click 命令。

- [ ] **Step 1: 寫 failing test**

在 `examples/sample_echo/tests/test_sample_echo.py` 追加:
```python
import click
from click.testing import CliRunner

from testpilot.api import CliRegistrar


def test_register_cli_greet_command():
    root = click.Group()
    Plugin().register_cli(CliRegistrar(root))
    result = CliRunner().invoke(root, ["sample-echo-greet", "--name", "X"])
    assert result.exit_code == 0
    assert "[stub] echo hello X" in result.output
```

- [ ] **Step 2: 執行確認 FAIL**

Run: `cd examples/sample_echo && python -m pytest tests/test_sample_echo.py::test_register_cli_greet_command -q`
Expected: FAIL(命令不存在 → `exit_code != 0`)

- [ ] **Step 3: 實作 register_cli**

把 `plugin.py` 的 `register_cli` 換成:
```python
    def register_cli(self, registrar: Any) -> None:
        import click

        @click.command("sample-echo-greet")
        @click.option("--name", default="world", help="Name to greet.")
        def greet(name: str) -> None:
            """Echo a greeting through the stub transport (sample CLI hook)."""
            transport = StubTransport()
            transport.connect()
            click.echo(transport.execute(f"echo hello {name}")["stdout"])

        registrar.add_command(greet)
```

- [ ] **Step 4: 執行確認 PASS**

Run: `cd examples/sample_echo && python -m pytest tests/test_sample_echo.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add examples/sample_echo/src/testpilot_sample_echo/plugin.py examples/sample_echo/tests/test_sample_echo.py
git commit -m "$(cat <<'EOF'
feat(examples): sample_echo 示範 register_cli(sample-echo-greet)(#3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N3ncbxM58zQXSCAJgCknHp
EOF
)"
```

---

### Task 4: sample 專屬 API 邊界守門測試

**Files:**
- Test: `examples/sample_echo/tests/test_sample_echo_boundary.py`

**Interfaces:**
- Consumes: `examples/sample_echo/src/testpilot_sample_echo/**/*.py` 生產碼。

- [ ] **Step 1: 寫測試(既有 boundary 只掃 plugins/,不涵蓋 examples/,故自帶一份)**

`examples/sample_echo/tests/test_sample_echo_boundary.py`:
```python
"""Boundary guard: sample production code may only reach testpilot via
``testpilot.api`` — never core/schema/reporting/transport/runtime internals.

The core repo's tests/test_plugin_sdk_api_boundary.py only scans plugins/,
so examples/ needs its own guard.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "testpilot_sample_echo"
GUARDED_PREFIXES = (
    "testpilot.core",
    "testpilot.schema",
    "testpilot.reporting",
    "testpilot.transport",
    "testpilot.runtime",
    "testpilot.serialwrap_binary",
)


def _guarded(module: str | None) -> bool:
    if not module:
        return False
    return any(module == p or module.startswith(p + ".") for p in GUARDED_PREFIXES)


def test_sample_production_code_only_imports_testpilot_api():
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and _guarded(node.module):
                violations.append(f"{path.name}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _guarded(alias.name):
                        violations.append(f"{path.name}: import {alias.name}")
    assert not violations, f"guarded imports in sample production code: {violations}"
```

- [ ] **Step 2: 執行確認 PASS(sample 只 import testpilot.api + click + stdlib)**

Run: `cd examples/sample_echo && python -m pytest tests/test_sample_echo_boundary.py -q`
Expected: 1 passed

- [ ] **Step 3: Commit**

```bash
git add examples/sample_echo/tests/test_sample_echo_boundary.py
git commit -m "$(cat <<'EOF'
test(examples): sample_echo API 邊界守門(只准 testpilot.api)(#3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N3ncbxM58zQXSCAJgCknHp
EOF
)"
```

---

### Task 5: sample README + 文件清理(dev-guide 死連結 / README 連結 / wifi_llapi reports)

**Files:**
- Create: `examples/sample_echo/README.md`
- Modify: `docs/plugin-dev-guide.md`(line 264 死連結 + 新增 Runnable sample 章節)
- Modify: `README.md`(Writing a Plugin 段加 sample 連結)
- Delete: `plugins/wifi_llapi/reports/` 下 stale 殘骸

- [ ] **Step 1: 寫 sample README**

`examples/sample_echo/README.md`:
```markdown
# testpilot-sample-echo

A minimal, runnable TestPilot plugin — the reference example for the
`testpilot.api` SDK (issue #3). It is a standalone pip distribution that the
host discovers through the `testpilot.plugins` entry-point group.

## What it demonstrates

- `entry_points` registration (`[project.entry-points."testpilot.plugins"]`)
- a `PluginBase` subclass with `api_version = "1.0"`
- a schema-valid case (`cases/echo-hello.yaml`) with a deterministic Pass
- an optional `register_cli` command (`testpilot sample-echo-greet`)
- discovery after a real `pip install` (no monkeypatching)

Production code imports **only** from `testpilot.api`.

## Try it

```bash
pip install testpilot-core          # the host
pip install -e ./examples/sample_echo  # this sample

testpilot list-plugins              # -> sample_echo
testpilot list-cases sample_echo    # -> echo-hello
testpilot run sample_echo --case echo-hello   # -> verdict PASS
testpilot sample-echo-greet --name you        # CLI hook demo
```

## Layout

```
src/testpilot_sample_echo/
  plugin.py            # Plugin(PluginBase) + EchoRunner
  testbed.yaml.example # staged to configs/testbed.yaml by the CLI
  cases/echo-hello.yaml
tests/                 # behaviour smoke + API-boundary guard
```
```

- [ ] **Step 2: 修 docs/plugin-dev-guide.md line 264 死連結**

把:
```
參考：`plugins/wifi_llapi/cases/_template.yaml`
```
改為:
```
參考：可運行範例 `examples/sample_echo/`（`pip install -e ./examples/sample_echo` 後 `testpilot run sample_echo --case echo-hello`）。
```

- [ ] **Step 3: dev-guide 末尾新增 Runnable sample 章節**

在 `docs/plugin-dev-guide.md` 檔尾追加:
```markdown

## Runnable sample

`examples/sample_echo/` 是最小可運行 plugin 範例(獨立 pip dist,經 `testpilot.plugins`
entry-point 被發現)。它示範 entry-point 宣告、`PluginBase` 子類、`api_version`、
schema-valid case + 測試,以及 `pip install` 後被 host 發現的完整路徑:

```bash
pip install -e ./examples/sample_echo
testpilot list-plugins            # -> sample_echo
testpilot list-cases sample_echo  # -> echo-hello
testpilot run sample_echo --case echo-hello   # -> PASS
```

> entry-point value 用 top-level import package 路徑(`testpilot_sample_echo.plugin:Plugin`),
> 這對獨立安裝的 dist 才穩定;`plugins.x.plugin:Plugin` 形式需該 dist 有打包 `plugins` package。
```

- [ ] **Step 4: README.md「Writing a Plugin」段加 sample 連結**

在 `README.md` `### Writing a Plugin` 段(約 line 266,`See plugins/_template/README.md ...` 附近)後追加一句:
```markdown

For a complete, runnable reference (installable + discoverable via
`testpilot.plugins`), see `examples/sample_echo/` and its README.
```

- [ ] **Step 5: 刪 wifi_llapi/reports stale 殘骸**

Run:
```bash
git rm -r --ignore-unmatch plugins/wifi_llapi/reports
```
(若該目錄僅含 `.gitkeep` 之類且屬有意保留,改只刪 stale 檔;以 `git status` 確認刪的是執行殘骸而非結構檔。)

- [ ] **Step 6: 驗證死連結已除 + docs 對齊測試**

Run(從 repo root):
```bash
! grep -rn "plugins/wifi_llapi/cases/_template.yaml" docs/ README.md
uv run pytest -q tests/test_cli_doc_alignment.py
```
Expected: grep 無命中(exit 0);doc-alignment 測試 passed。

- [ ] **Step 7: Commit**

```bash
git add examples/sample_echo/README.md docs/plugin-dev-guide.md README.md
git add -A plugins/wifi_llapi/reports 2>/dev/null || true
git commit -m "$(cat <<'EOF'
docs(examples): sample README + dev-guide 死連結修正/Runnable sample 章節 + 清 wifi_llapi/reports (#3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N3ncbxM58zQXSCAJgCknHp
EOF
)"
```

---

### Task 6: openspec change + CHANGELOG / changelog.d

**Files:**
- Create: `openspec/changes/add-sample-echo-plugin/.openspec.yaml`
- Create: `openspec/changes/add-sample-echo-plugin/proposal.md`
- Create: `openspec/changes/add-sample-echo-plugin/tasks.md`
- Create: `openspec/changes/add-sample-echo-plugin/specs/plugin-sample-reference/spec.md`
- Create: `changelog.d/add-sample-echo-plugin.md`
- Modify: `CHANGELOG.md`(`[Unreleased]`)

- [ ] **Step 1: `.openspec.yaml`**

`openspec/changes/add-sample-echo-plugin/.openspec.yaml`:
```yaml
schema: spec-driven
created: 2026-07-04
```

- [ ] **Step 2: `proposal.md`**

`openspec/changes/add-sample-echo-plugin/proposal.md`:
```markdown
## Why

testpilot-core 目前只有 `plugins/_template/`(刻意不可運行、不註冊的 scaffold),
第三方開發者手上沒有一個「照著抄就能跑」的活範例,`docs/plugin-dev-guide.md` 也沒有
指向任何可運行 sample(且死連結指向已拆分的 wifi_llapi)。issue #3 要求提供一個最小、
可 `pip install`、可被 host 發現、可跑出 verdict 的 sample。

## What Changes

- 新增 `examples/sample_echo/`:獨立 pip dist `testpilot-sample-echo`,經 `testpilot.plugins`
  entry-point 被發現;只依賴 `testpilot.api`;走 `create_runner()` → `run_pipeline()` 產出
  Pass verdict;示範選配 `register_cli`。
- 不進 core wheel / `install-manifest.yaml` / `uv.lock`(維持 core 中立契約)。
- CI 新增真實安裝發現 smoke(補現況只 monkeypatch 假 entry_points 的缺口)。
- 文件:修 dev-guide 死連結、加 Runnable sample 章節、README 連結;清 `plugins/wifi_llapi/reports/` 殘骸。

## Capabilities

### New Capabilities
- `plugin-sample-reference`: 專案 SHALL 提供一個最小可運行 sample plugin 作為 SDK 對照範例,
  以獨立 dist 形態經 entry_points 被發現,且僅依賴 `testpilot.api`。

## Impact

- 新增 `examples/sample_echo/`(非 core wheel、非 workspace member)。
- `.github/workflows/ci.yml` 新增 sample 安裝發現 step。
- `docs/plugin-dev-guide.md` / `README.md` 文件更新;`plugins/wifi_llapi/reports/` 清理。
- 對 core 行為 / 契約 / 中立性零影響。
```

- [ ] **Step 3: `tasks.md`**

`openspec/changes/add-sample-echo-plugin/tasks.md`:
```markdown
## 1. sample 本體
- [x] 1.1 `examples/sample_echo/` 套件骨架 + pyproject + entry-point + package data
- [x] 1.2 `Plugin(PluginBase)` + `EchoRunner`(run_pipeline → verdict)
- [x] 1.3 schema-valid `cases/echo-hello.yaml` + `testbed.yaml.example`
- [x] 1.4 行為 smoke 測試(discover=1、verdict Pass)

## 2. 發現與 CLI
- [x] 2.1 CI 真實安裝發現 smoke(list-plugins/list-cases/run)
- [x] 2.2 `register_cli` demo 子命令 + 測試

## 3. 守門與文件
- [x] 3.1 sample 專屬 API 邊界測試
- [x] 3.2 sample README + dev-guide 死連結/Runnable sample + README 連結
- [x] 3.3 清 `plugins/wifi_llapi/reports/` 殘骸
```

- [ ] **Step 4: spec delta**

`openspec/changes/add-sample-echo-plugin/specs/plugin-sample-reference/spec.md`:
```markdown
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
```

- [ ] **Step 5: 驗證 openspec change 格式**

Run(從 repo root):
```bash
openspec validate add-sample-echo-plugin --strict
```
Expected: 驗證通過(no errors)。若報格式錯,依訊息修正上述四檔後重跑至綠。

- [ ] **Step 6: changelog.d fragment**

`changelog.d/add-sample-echo-plugin.md`:
```markdown
---
type: feat
scope: examples
---
新增可運行的最小 sample plugin `examples/sample_echo`(獨立 dist `testpilot-sample-echo`,經 `testpilot.plugins` entry-point 被發現、只依賴 `testpilot.api`、走 `create_runner`→`run_pipeline` 產出 Pass verdict,含 `register_cli` demo 與 API 邊界測試);CI 補真實安裝發現 smoke;修 `docs/plugin-dev-guide.md` 死連結並加 Runnable sample 章節、清 `plugins/wifi_llapi/reports/` 殘骸。對照 issue #3。
```

- [ ] **Step 7: CHANGELOG.md `[Unreleased]` 加 entry**

把 `## [Unreleased]` 段改為:
```markdown
## [Unreleased]

### Added
- 可運行的最小 sample plugin `examples/sample_echo`(獨立 dist `testpilot-sample-echo`,經 `testpilot.plugins` entry-point 被發現、僅依賴 `testpilot.api`、`create_runner`→`run_pipeline` 產出 Pass verdict,含 `register_cli` demo);CI 加真實安裝發現 smoke;dev-guide/README 指向 sample 並修死連結、清 `plugins/wifi_llapi/reports/`。對照 #3。
```

- [ ] **Step 8: Commit**

```bash
git add openspec/changes/add-sample-echo-plugin changelog.d/add-sample-echo-plugin.md CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(openspec): add-sample-echo-plugin change + CHANGELOG/changelog.d (#3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N3ncbxM58zQXSCAJgCknHp
EOF
)"
```

---

### Task 7: requesting-code-review → openspec archive → policy check → push → PR

> 本 task 由主 session(非 fresh subagent)執行:含 code review skill、外部工具與 PR 建立。

- [ ] **Step 1: 全套件測試綠**

Run(從 repo root):
```bash
uv run pytest -q                                   # core 套件
/tmp/sample-echo-venv/bin/python -m pytest -q examples/sample_echo/tests  # sample 套件
```
Expected: 皆 passed。

- [ ] **Step 2: requesting-code-review**

Invoke `superpowers:requesting-code-review`(對整個 branch diff)。修正 review 發現(依 `superpowers:receiving-code-review`),回到相關 task 補測試/實作,重跑至綠。

- [ ] **Step 3: openspec archive**

Run(從 repo root):
```bash
openspec archive add-sample-echo-plugin --yes
openspec validate --strict
git status
```
Expected:change 移到 `openspec/changes/archive/2026-07-04-add-sample-echo-plugin/`,`openspec/specs/plugin-sample-reference/spec.md` 產生/更新。確認 diff 合理。

- [ ] **Step 4: policy check(v1.0.12 引擎,勿 pip install 外部 repo)**

Run:
```bash
# clone 引擎到 scratchpad(若尚未),pin v1.0.12 = 25d31e02
ENGINE=/tmp/claude-1000/-home-paul-chen-prj-arc/b212c68b-7eb8-49c5-9b22-9bdd7bb1de86/scratchpad/psc-engine
[ -d "$ENGINE" ] || git clone git@github.com:hamanpaul/paulsha-conventions.git "$ENGINE"
git -C "$ENGINE" fetch --all -q && git -C "$ENGINE" checkout -q 25d31e021e45c2991c718923ae2dd49bc3d0b542
cd /tmp/claude-1000/-home-paul-chen-prj-arc/b212c68b-7eb8-49c5-9b22-9bdd7bb1de86/scratchpad/tpc-work
PYTHONPATH="$ENGINE" python -m policy_check --repo .
```
Expected: **no failure**(R-18/R-22 既有 advisory warn 可接受,非阻擋)。有 failure 就修到綠。

- [ ] **Step 5: 最終 commit(archive/policy 產物)+ push**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore(openspec): archive add-sample-echo-plugin + specs 落地 (#3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N3ncbxM58zQXSCAJgCknHp
EOF
)"
git push -u origin feature/sample-echo-plugin
```

- [ ] **Step 6: 開 PR(zh-tw,Closes #3)**

```bash
gh pr create --repo hamanpaul/testpilot-core --base main --head feature/sample-echo-plugin \
  --title "feat(examples): 可運行的最小 sample plugin sample_echo (#3)" \
  --body "$(cat <<'EOF'
## 摘要
為 issue #3 交付最小可運行 sample plugin `examples/sample_echo`(獨立 dist `testpilot-sample-echo`)。

## 變更
- `examples/sample_echo/`:`PluginBase` 子類 + `EchoRunner`(`create_runner`→`run_pipeline` 出 Pass verdict)、schema-valid `echo-hello` case、`testbed.yaml.example`、`register_cli` demo(`sample-echo-greet`)、行為 smoke + API 邊界測試。
- entry-point group `testpilot.plugins`,value `testpilot_sample_echo.plugin:Plugin`;只依賴 `testpilot.api`。
- 不進 core wheel / `install-manifest.yaml` / `uv.lock`(維持 core 中立)。
- CI:真實安裝發現 smoke(list-plugins/list-cases/run + examples 測試)。
- 文件:修 dev-guide 死連結、加 Runnable sample 章節、README 連結;清 `plugins/wifi_llapi/reports/`。
- openspec:`plugin-sample-reference` capability(已 archive)。

## 設計 / 審查
- spec:`docs/superpowers/specs/2026-07-04-sample-echo-plugin-design.md`(已過 Codex 對抗性 review)。
- plan:`docs/superpowers/plans/2026-07-04-sample-echo-plugin.md`。

Closes #3
EOF
)"
```

- [ ] **Step 7: PR checklist / labels**

依 `.github/PULL_REQUEST_TEMPLATE.md` 勾選 checklist;無需豁免 label(docs 已同步、CI 有測試、無機敏)。

---

## Self-Review

**1. Spec coverage** — 對照 spec 各節:
- 落點/封裝(examples/ 獨立 dist)→ Task 1 pyproject/entry-point。
- Plugin(4 abstract + api_version + create_runner)→ Task 1 plugin.py。
- execute_step stdout→output adapter → Task 1 Step 5。
- evaluate dict `.values()` → Task 1 plugin.py。
- discover_cases + load_cases_dir 非 fail-fast → Task 1 test(斷言數=1)。
- Runner 繞過 skeleton → Task 1 `EchoRunner`。
- case echo-hello schema-valid + command → Task 1 Step 7。
- testbed.yaml.example(必要)→ Task 1 Step 6;list-cases/run 驗證 → Task 2。
- register_cli + 撞名 → Task 3。
- 單元 smoke + boundary 測試 → Task 1 / Task 4。
- CI 真實安裝(list-plugins/list-cases/run,不動 uv.lock)→ Task 2。
- 連帶清理(dead link/README/reports)→ Task 5。
- DoD 全項 → Task 2/3/4/7。
- 治理(openspec/changelog/policy/PR)→ Task 6/7。

**2. Placeholder scan** — 各 code step 皆為可貼上的完整內容;無 TBD/TODO。(openspec spec delta 若 validator 有格式意見,Task 6 Step 5 明確以 validator 輸出收斂。)

**3. Type consistency** — `Plugin.create_runner() -> EchoRunner`;`EchoRunner.run(orchestrator, plugin_name, case_ids, dut_fw_ver, provider_config)` 與 `Orchestrator._run_via_runner` 呼叫簽名一致;`run_pipeline` 回 `{"verdict":...}`,`EchoRunner` 讀 `outcome["verdict"]`;`execute_step` 回 key `{success,output,captured,timing}` 與 `run_pipeline`/`evaluate` 讀取一致;`evaluate` 讀 `results["steps"].values()` 與 `run_pipeline` 傳的 `{"steps": step_results}` 一致。

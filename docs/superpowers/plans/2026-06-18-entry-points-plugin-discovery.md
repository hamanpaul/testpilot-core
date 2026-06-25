# P2a: entry_points 發現 + in-repo packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans。Steps 用 `- [ ]`。行為保真型 refactor;發現名單不變 + golden 是紅線。**注意:本案後測試需 `pip install -e .`(entry_points 靠已安裝 metadata)。**

**Goal:** 發現/載入改走 `entry_points`(group `testpilot.plugins`);in-repo plugin 正規化為 entry_point 套件;移除 dir-scan + sys.path hack。行為不變。

**Architecture:** `PluginLoader.discover/load` → `importlib.metadata.entry_points`;`plugins/*` 變正規 package(`__init__.py` + package import);pyproject 宣告 entry_points + Hatch 納入 plugins;dev/CI `pip install -e .`。

**Tech Stack:** Python 3.12, Hatch, pytest。change `entry-points-plugin-discovery`。spec `docs/superpowers/specs/2026-06-18-entry-points-discovery-design.md`。

---

## File Structure

- Create: `plugins/__init__.py`、`plugins/brcm_fw_upgrade/__init__.py`
- Modify: `plugins/wifi_llapi/command_resolver.py:16`、`plugins/wifi_llapi/plugin.py:24-27`(bare→package import)+ 2 test 檔
- Modify: `src/testpilot/core/plugin_loader.py`(entry_points 發現/載入)
- Modify: `src/testpilot/core/orchestrator.py`(plugin 檔案資源路徑由模組位置推導)
- Modify: `pyproject.toml`(entry_points + Hatch packages)
- Modify: CI workflow(加 `pip install -e .`)、`realistic_runtime` 測試
- Create: `tests/test_plugin_entry_points_discovery.py`

---

## Task 1: RED — 發現契約 + bare-import 守門先紅

- [ ] **Step 1: 發現契約測試**

`tests/test_plugin_entry_points_discovery.py`:

```python
"""plugin 經 entry_points 發現/載入(change entry-points-plugin-discovery)。"""
from __future__ import annotations
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_discover_via_entry_points():
    from testpilot.core.plugin_loader import PluginLoader
    names = set(PluginLoader(REPO / "plugins").discover())
    assert {"wifi_llapi", "brcm_fw_upgrade"} <= names


def test_load_returns_plugin_base():
    from testpilot.core.plugin_loader import PluginLoader
    from testpilot.core.plugin_base import PluginBase
    assert isinstance(PluginLoader(REPO / "plugins").load("wifi_llapi"), PluginBase)


def test_loader_has_no_dir_scan_or_syspath_hack():
    src = (REPO / "src/testpilot/core/plugin_loader.py").read_text(encoding="utf-8")
    assert "spec_from_file_location" not in src
    assert "sys.path.insert" not in src
    assert "iterdir" not in src


def test_wifi_no_local_bare_imports():
    root = REPO / "plugins" / "wifi_llapi"
    local = {"baseline_qualifier", "case_validation", "command_resolver",
             "yaml_command_audit", "run_result", "runner"}
    hits = []
    for p in root.rglob("*.py"):
        if "tests" in p.relative_to(root).parts:
            continue
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "") in local and node.level == 0:
                hits.append(f"{p.name}:{node.lineno} {node.module}")
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in local:
                        hits.append(f"{p.name}:{node.lineno} {a.name}")
    assert not hits, "wifi 仍有本地 bare import:\n" + "\n".join(hits)
```

- [ ] **Step 2: 跑確認紅**

Run: `python -m pytest tests/test_plugin_entry_points_discovery.py -v`
Expected: FAIL — discover 仍 dir-scan(entry_points 未註冊)、loader 仍有 spec_from_file_location/sys.path、wifi 仍 bare import。擷取 RED。

---

## Task 2: GREEN — package 正規化

- [ ] **Step 1: __init__.py**

新增空 `plugins/__init__.py`、`plugins/brcm_fw_upgrade/__init__.py`。

- [ ] **Step 2: wifi bare import → package**

- `command_resolver.py:16`:`from yaml_command_audit import (...)` → `from plugins.wifi_llapi.yaml_command_audit import (...)`
- `plugin.py:24-27`:
  - `from baseline_qualifier import BaselineQualifier` → `from plugins.wifi_llapi.baseline_qualifier import BaselineQualifier`
  - `from case_validation import load_wifi_band_baselines, validate_wifi_llapi_case` → `from plugins.wifi_llapi.case_validation import ...`
  - `from command_resolver import CommandResolver` → `from plugins.wifi_llapi.command_resolver import CommandResolver`
  - `from yaml_command_audit import looks_like_shell_command` → `from plugins.wifi_llapi.yaml_command_audit import looks_like_shell_command`
- 同步 `plugins/wifi_llapi/tests/test_command_resolver.py`、`test_wifi_llapi_plugin_runtime.py` 的對應 bare import。

- [ ] **Step 3: 檔案資源路徑由模組位置推導**

plugin `cases_dir`/reports 等改用 `Path(__file__).parent`(plugin.py 內已可),移除對外部 `plugins_dir/<name>` 的依賴(orchestrator 端 Task 4.2 對應)。

---

## Task 3: GREEN — pyproject entry_points + 打包

- [ ] **Step 1: pyproject**

```toml
[project.entry-points."testpilot.plugins"]
wifi_llapi = "plugins.wifi_llapi.plugin:Plugin"
brcm_fw_upgrade = "plugins.brcm_fw_upgrade.plugin:Plugin"

[tool.hatch.build.targets.wheel]
packages = ["src/testpilot", "plugins"]
```

- [ ] **Step 2: 安裝並驗證 entry_points**

Run: `pip install -e . && python -c "from importlib.metadata import entry_points as e; print(sorted(x.name for x in e(group='testpilot.plugins')))"`
Expected: `['brcm_fw_upgrade', 'wifi_llapi']`

---

## Task 4: GREEN — loader 改 entry_points

- [ ] **Step 1: 改寫 discover/load**

`plugin_loader.py`:

```python
from importlib.metadata import entry_points

_GROUP = "testpilot.plugins"

def discover(self) -> list[str]:
    return sorted(ep.name for ep in entry_points(group=_GROUP))

def load(self, name: str) -> PluginBase:
    if name in self._plugins:
        return self._plugins[name]
    eps = [ep for ep in entry_points(group=_GROUP) if ep.name == name]
    if not eps:
        raise FileNotFoundError(f"plugin entry_point not found: {name}")
    plugin_cls = eps[0].load()
    instance = plugin_cls()
    if not isinstance(instance, PluginBase):
        raise TypeError(f"Plugin must inherit PluginBase: {plugin_cls}")
    self._plugins[name] = instance
    log.info("loaded plugin: %s v%s", instance.name, instance.version)
    return instance
```
移除 `spec_from_file_location`、sys.path 插入、`iterdir` 掃描。`__init__` 的 `plugins_dir` 可保留(供檔案資源 fallback)但發現不再依賴它。

- [ ] **Step 2: orchestrator 檔案資源路徑**

`orchestrator` 取 plugin reports/cases 路徑改走 `Path(plugin.__module__ 模組檔).parent`(或 plugin 提供 `plugin_root` property),配合 Task 2.3。

- [ ] **Step 3: 跑發現契約 + 守門至綠**

Run: `python -m pytest tests/test_plugin_entry_points_discovery.py -v` → PASS

---

## Task 5: install-flow / 測試流程

- [ ] **Step 1: CI / dev**

CI workflow 加 `pip install -e .` 步驟(發現前提);文件註明 dev setup;整理現行指向 worktree 的 stale editable install。

- [ ] **Step 2: realistic_runtime**

`plugins/wifi_llapi/tests/test_orchestrator_realistic_runtime.py`(複製專案 + subprocess pytest):改測法使其不依賴 sys.path hack(複製環境亦 `pip install -e .`,或改為 in-process + entry_points)。

---

## Task 6: 回歸驗證 — 行為不變

- [ ] **Step 1**: `pip install -e .` 後跑既有 wifi_llapi/brcm 測試 → PASS
- [ ] **Step 2**: golden 報表測試 → PASS
- [ ] **Step 3**: 全套 `pytest` → PASS;`discover()` 名單與改動前一致(wifi_llapi/brcm)
- [ ] **Step 4**: grep 確認 `plugin_loader.py` 無 `spec_from_file_location`/`sys.path.insert`/`iterdir`;wifi production 無本地 bare import
- [ ] **Step 5: Commit**

```bash
git add plugins/__init__.py plugins/brcm_fw_upgrade/__init__.py plugins/wifi_llapi src/testpilot/core/plugin_loader.py src/testpilot/core/orchestrator.py pyproject.toml tests/ .github openspec/changes/entry-points-plugin-discovery
git commit -m "feat(loader): discover plugins via entry_points; package in-repo plugins"
```

---

## Task 7: 收尾(workflow 後段)

- [ ] 7.1 requesting-code-review(發現正確 / 行為保真 / packaging / install-flow)
- [ ] 7.2 receiving-code-review + re-review 至無 Critical/Important
- [ ] 7.3 openspec archive → policy → conventional commit → push → PR(R-12/R-17)

---

## Self-Review

- **Spec coverage:** entry_points 發現(Req)→ Task 3/4 + 契約測試;in-repo 正規 package(Req)→ Task 2 + bare-import 守門;行為不變(Req)→ Task 6。
- **Placeholder scan:** 無 TBD;loader/pyproject/契約測試為完整碼;檔案資源路徑推導於 Task 2.3/4.2 具體化。
- **Type consistency:** `discover()->list[str]`、`load(name)->PluginBase` 簽章不變;entry_point target `plugins.<name>.plugin:Plugin` 與 pyproject 一致。
- **行為保真重點:** discover 名單須與改動前相同(wifi_llapi/brcm);plugin 載入後行為由既有 golden/plugin 測試把關;**測試需已安裝環境**(entry_points 前提)。

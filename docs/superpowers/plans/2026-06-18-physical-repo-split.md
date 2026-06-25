# P4: 物理切分(core 獨立 public)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(建議)或 superpowers:executing-plans 逐 task 實作。Steps 用 `- [ ]`。**兩類 task**:(A) in-monorepo 重構=TDD(RED→GREEN);(B) repo 物理操作=程序 + 驗證閘(無單元測試,以明確指令 + 預期輸出驗收)。**先做完所有 (A) 讓物理切分退化成純搬檔,再做 (B)。**

**Goal:** monorepo 物理切成 3 repo——core 獨立 public(fresh 無歷史、裝置中立)、wifi_llapi(現 repo rename、private、留歷史、含折入 audit)、brcm_fw_upgrade(新 private、filter-repo 帶歷史)——各為獨立 pip dist 經 entry_points 串接,full-run 測試以 replay backend 接回。

**Architecture:** 先在 monorepo 內把 audit 折入 wifi、解 audit→core 耦合、收斂獨立 dist packaging、加 replay backend 接回測試(全 TDD/golden 守門);再做 git 物理操作(brcm filter-repo → core fresh repo → 現 repo rename)。北極星=core 可 public;硬邊界=凡 public,git log 無機敏(R-21 secret-scan 為閘)。

**Tech Stack:** Python 3.12、hatchling、click、pytest、`git filter-repo`、`importlib.metadata` entry_points、paulsha-conventions reusable policy-check。change `physical-repo-split`。spec `docs/superpowers/specs/2026-06-18-p4-physical-repo-split-design.md`。

**前置(硬閘,須先 merge):** B1(RunBackend)、B2(core-owned execution loop + §6 api 約束)、P2a(entry_points + packaging)、P2b(versioned contract)、P3(register_cli)。

---

## File Structure

**in-monorepo 變更(Task 1–5,切分前):**
- Modify: `src/testpilot/api/__init__.py` — re-export `case_d_number` + B2 core-owned 單-case 執行入口
- Move: `src/testpilot/audit/` → `plugins/wifi_llapi/audit/`(脫 `testpilot.` namespace)
- Modify: `plugins/wifi_llapi/audit/cli.py` — import 改 `testpilot.api`
- Modify: `plugins/wifi_llapi/audit/runner_facade.py` — 改 `testpilot.api`,去 `testpilot.core.*`
- Modify: `plugins/wifi_llapi/plugin.py` — `register_cli()` 掛 audit 子命令
- Modify: `src/testpilot/cli.py` — 移除 `audit_group` 具名掛載
- Create: `plugins/wifi_llapi/pyproject.toml`、`plugins/brcm_fw_upgrade/pyproject.toml`(獨立 dist)
- Modify: `pyproject.toml`(root)— 收斂為 core-only(去 plugins/audit 打包、entry_points、testpaths)
- Create: `plugins/wifi_llapi/run_backend/replay.py`(replay provider,寫在 B1 RunBackend 上;確切目錄以 B1 provider 慣例為準)
- Create: `plugins/wifi_llapi/tests/fixtures/audit_runner_facade/`(golden serialwrap I/O)
- Modify: `tests/test_audit_runner_facade.py` → 移入 wifi plugin tests + 去 skip
- Create: `tests/test_core_neutrality_guard.py`、`tests/test_audit_import_boundary.py`(守門)

**repo 物理操作(Task 6–9,切分):** 不在單一工作樹內;產出 3 個 git repo(見各 task)。

---

## Task 0: 前置健檢閘(驗證,非程式)

**Files:** 無(只驗證)

- [ ] **Step 1: 確認前置 stage 已 merge**

Run: `git log --oneline main | grep -Ei "B1|B2|P2a|P2b|P3|runbackend|core-owned|entry.point|versioned|register_cli"`
Expected: 五前置 stage 的 merge 提交都在 main。

- [ ] **Step 2: 確認 allow-list 清空**

Run: `python -m pytest tests/ -k "boundary or allow_list" -v`
Expected: PASS(wifi production 僅依賴 `testpilot.api`)。

- [ ] **Step 3: 確認 B2 §6 約束已落實**

Run: `python -c "import testpilot.api as a; print('run entry' , hasattr(a,'run_one_case') or 'orchestrator-run-exposed')"`
Expected: core-owned 單-case 執行入口經 `testpilot.api` 可取用(實際符號名以 B2 實作為準)。若缺 → 回頭補 B2,**不得繞道 import `testpilot.core`**。

---

## Task 1: `testpilot.api` 補齊 audit 折出所需符號

**Files:**
- Test: `tests/test_api_surface_for_audit.py`
- Modify: `src/testpilot/api/__init__.py`

- [ ] **Step 1: 寫失敗測試**

```python
"""P4: audit 折出前,api 須公開其所需符號(change physical-repo-split)。"""
from __future__ import annotations
import importlib


def test_api_exposes_audit_symbols():
    api = importlib.import_module("testpilot.api")
    # validate_case / CaseValidationError 已存在(P1);case_d_number 為本 task 新增
    for sym in ("validate_case", "CaseValidationError", "case_d_number"):
        assert sym in api.__all__, f"{sym} 不在 testpilot.api.__all__"
        assert hasattr(api, sym), f"testpilot.api 缺 {sym}"


def test_api_exposes_single_case_run_entry():
    api = importlib.import_module("testpilot.api")
    # B2 §6:core-owned 單-case 執行入口(符號名以 B2 為準,二擇一存在即可)
    assert any(hasattr(api, n) for n in ("run_one_case", "run_cases")), \
        "testpilot.api 未公開 core-owned 執行入口"
```

- [ ] **Step 2: 跑測試確認紅**

Run: `pytest tests/test_api_surface_for_audit.py -v`
Expected: FAIL（`case_d_number` 不在 `__all__`）。

- [ ] **Step 3: 最小實作**

於 `src/testpilot/api/__init__.py` import 並加入 `__all__`:
```python
from testpilot.core.case_utils import case_d_number
# ... __all__ 內新增 "case_d_number"
```
（執行入口若 B2 已 re-export 則免動；未 re-export 則於此補上 B2 提供的入口。）

- [ ] **Step 4: 跑測試確認綠**

Run: `pytest tests/test_api_surface_for_audit.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_surface_for_audit.py src/testpilot/api/__init__.py
git commit -m "feat(api): expose case_d_number + run entry for audit fold-out (P4)"
```

---

## Task 2: audit re-home 進 wifi 套件 + 解 core 耦合

**Files:**
- Test: `tests/test_audit_import_boundary.py`
- Move: `src/testpilot/audit/` → `plugins/wifi_llapi/audit/`
- Modify: `plugins/wifi_llapi/audit/cli.py`、`plugins/wifi_llapi/audit/runner_facade.py`

- [ ] **Step 1: 寫失敗的 import-boundary 守門測試**

```python
"""P4: 折入 wifi 的 audit 僅可依賴 testpilot.api(change physical-repo-split)。"""
from __future__ import annotations
import ast
import pathlib

AUDIT_DIR = pathlib.Path("plugins/wifi_llapi/audit")
FORBIDDEN_PREFIXES = ("testpilot.core", "testpilot.schema", "testpilot.reporting", "testpilot.transport")


def _imports(py: pathlib.Path):
    tree = ast.parse(py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for n in node.names:
                yield n.name


def test_audit_only_depends_on_public_api():
    assert AUDIT_DIR.is_dir(), "audit 尚未 re-home 進 plugins/wifi_llapi/audit"
    bad = []
    for py in AUDIT_DIR.rglob("*.py"):
        for mod in _imports(py):
            if any(mod.startswith(p) for p in FORBIDDEN_PREFIXES):
                bad.append(f"{py}: {mod}")
    assert not bad, "audit 仍勾 core 內部:\n" + "\n".join(bad)
```

- [ ] **Step 2: 跑測試確認紅**

Run: `pytest tests/test_audit_import_boundary.py -v`
Expected: FAIL（`plugins/wifi_llapi/audit` 不存在 / 仍有 `testpilot.core` import）。

- [ ] **Step 3: 搬檔 + re-namespace**

```bash
git mv src/testpilot/audit plugins/wifi_llapi/audit
```
全域把 `testpilot.audit` 改為 wifi 套件內路徑（plugin 安裝後的模組名,如 `wifi_llapi.audit`）。

- [ ] **Step 4: 解 `cli.py` 耦合**

`plugins/wifi_llapi/audit/cli.py`:
```python
# was: from testpilot.schema.case_schema import CaseValidationError, validate_case
from testpilot.api import CaseValidationError, validate_case
```

- [ ] **Step 5: 解 `runner_facade.py` 耦合**

`plugins/wifi_llapi/audit/runner_facade.py`:
```python
# was: from testpilot.core.orchestrator import Orchestrator
#      from testpilot.core.case_utils import case_d_number
from testpilot.api import case_d_number  # 並改用 B2 core-owned 執行入口取代直接 Orchestrator
# run_one_case_for_audit 改呼叫 testpilot.api 的執行入口(B2 §6),不再 new Orchestrator()
```

- [ ] **Step 6: 跑守門 + audit 既有測試確認綠**

Run: `pytest tests/test_audit_import_boundary.py plugins/wifi_llapi/tests/ -v`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(audit): re-home into wifi plugin, depend only on testpilot.api (P4)"
```

---

## Task 3: audit CLI 改 register_cli;core cli.py 去具名

**Files:**
- Test: `tests/test_core_cli_no_audit.py`
- Modify: `plugins/wifi_llapi/plugin.py`、`src/testpilot/cli.py`

- [ ] **Step 1: 寫失敗測試**

```python
"""P4: core cli.py 不再具名掛 audit;audit 經 wifi register_cli(change physical-repo-split)。"""
from __future__ import annotations
import pathlib
from click.testing import CliRunner


def test_core_cli_has_no_named_audit_import():
    src = pathlib.Path("src/testpilot/cli.py").read_text(encoding="utf-8")
    assert "audit_group" not in src, "core cli.py 仍具名掛 audit_group"
    assert "testpilot.audit" not in src and "wifi_llapi.audit" not in src, "core cli.py 仍 import audit"


def test_audit_subcommand_present_when_wifi_installed():
    from testpilot.cli import main  # eager 載入 + register_cli 組裝
    res = CliRunner().invoke(main, ["--help"])
    assert res.exit_code == 0
    assert "audit" in res.output  # 由 wifi register_cli 掛上
```

- [ ] **Step 2: 跑測試確認紅**

Run: `pytest tests/test_core_cli_no_audit.py -v`
Expected: FAIL（`audit_group` 仍在 core cli.py）。

- [ ] **Step 3: wifi `register_cli` 掛 audit**

`plugins/wifi_llapi/plugin.py` 的 `register_cli(self, registrar)` 內:
```python
from wifi_llapi.audit.cli import audit_group
registrar.add_group(audit_group)
```

- [ ] **Step 4: core cli.py 去具名**

移除 `from testpilot.audit.cli import audit_group` 與 `main.add_command(audit_group)`。

- [ ] **Step 5: 跑測試確認綠**

Run: `pytest tests/test_core_cli_no_audit.py -v`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(cli): audit subcommand via wifi register_cli; core neutral (P4)"
```

---

## Task 4: 獨立 dist packaging + core-only 收斂

**Files:**
- Test: `tests/test_core_neutrality_guard.py`
- Create: `plugins/wifi_llapi/pyproject.toml`、`plugins/brcm_fw_upgrade/pyproject.toml`
- Modify: `pyproject.toml`(root → core-only)

- [ ] **Step 1: 寫失敗的中立守門測試**

```python
"""P4: core wheel 不含 vendor plugin / audit(change physical-repo-split)。"""
from __future__ import annotations
import tomllib
import pathlib


def test_root_pyproject_is_core_only():
    data = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
    wheel = data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {})
    pkgs = wheel.get("packages", [])
    assert pkgs == ["src/testpilot"], f"core wheel 應只含 src/testpilot,實得 {pkgs}"
    # 過渡期 in-wheel plugins 應移除
    text = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
    assert "plugins" not in wheel.get("force-include", {}), "core wheel 仍 force-include plugins"
    assert 'entry-points."testpilot.plugins"' not in text, "core pyproject 仍宣告 plugin entry_points"


def test_plugin_pyprojects_declare_contract():
    for name in ("wifi_llapi", "brcm_fw_upgrade"):
        p = pathlib.Path(f"plugins/{name}/pyproject.toml")
        assert p.is_file(), f"缺 {p}"
        text = p.read_text(encoding="utf-8")
        assert 'testpilot.plugins' in text, f"{name} 未宣告 entry_point"
        assert "testpilot>=1.0,<2.0" in text.replace(" ", ""), f"{name} 未 pin testpilot"
```

- [ ] **Step 2: 跑測試確認紅**

Run: `pytest tests/test_core_neutrality_guard.py -v`
Expected: FAIL（plugin pyproject 不存在 / root 仍打包 plugins）。

- [ ] **Step 3: 建 plugin pyproject**

`plugins/wifi_llapi/pyproject.toml`(brcm 同式):
```toml
[project]
name = "wifi_llapi"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["testpilot>=1.0,<2.0"]

[project.entry-points."testpilot.plugins"]
wifi_llapi = "wifi_llapi.plugin:Plugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 4: root pyproject 收斂 core-only**

移除 P2a 過渡期 in-wheel plugins 打包 + `[project.entry-points."testpilot.plugins"]`;`packages = ["src/testpilot"]`;`testpaths` 去 plugin 測試。

- [ ] **Step 5: 跑測試 + 全套回歸確認綠**

Run: `pytest tests/test_core_neutrality_guard.py -q && pytest -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "build: independent plugin dists; core-only root pyproject (P4)"
```

---

## Task 5: replay RunBackend 接回 full-run 測試

**Files:**
- Create: `plugins/wifi_llapi/run_backend/replay.py`
- Create: `plugins/wifi_llapi/tests/test_replay_backend.py`
- Create: `plugins/wifi_llapi/tests/fixtures/audit_runner_facade/golden_io.json`
- Modify/Move: `tests/test_audit_runner_facade.py` → `plugins/wifi_llapi/tests/test_audit_runner_facade.py`(去 skip)

- [ ] **Step 1: 寫 replay backend 的失敗測試**

```python
"""P4: replay RunBackend 決定性重放(change physical-repo-split)。"""
from __future__ import annotations
import json
import pathlib

from wifi_llapi.run_backend.replay import ReplayRunBackend  # 寫在 B1 RunBackend 介面上

FIX = pathlib.Path(__file__).parent / "fixtures" / "audit_runner_facade" / "golden_io.json"


def test_replay_backend_returns_recorded_output():
    backend = ReplayRunBackend.from_fixture(FIX)
    handle = backend.setup_run()
    out = backend.run_command(handle, "ubus-cli \"WiFi.Radio.1.IEEE80211ax.NonSRGOBSSPDMaxOffset?\"")
    expected = json.loads(FIX.read_text())["commands"][0]["output"]
    assert out == expected
    backend.teardown_run()
```

- [ ] **Step 2: 跑測試確認紅**

Run: `pytest plugins/wifi_llapi/tests/test_replay_backend.py -v`
Expected: FAIL（`ReplayRunBackend` 不存在）。

- [ ] **Step 3: 實作 replay provider + 錄 fixture**

`plugins/wifi_llapi/run_backend/replay.py`:實作 B1 `RunBackend` 介面,`from_fixture()` 載入錄製 I/O,`run_command`/`mark_position`/`export_logs` 由 fixture 回放(命令→輸出 map;標注 fixture 來源與錄製日期)。以一次真 testbed run 錄 `golden_io.json`(含 `test_audit_runner_facade` 所需 case 的 I/O)。

- [ ] **Step 4: 跑測試確認綠**

Run: `pytest plugins/wifi_llapi/tests/test_replay_backend.py -v`
Expected: PASS。

- [ ] **Step 5: 移入並去 skip full-run 測試**

```bash
git mv tests/test_audit_runner_facade.py plugins/wifi_llapi/tests/test_audit_runner_facade.py
```
移除 `@pytest.mark.skip`;改注入 `ReplayRunBackend`(經 B2 core-owned 執行入口 + B1 backend 注入點)。

- [ ] **Step 6: 跑接回測試確認綠**

Run: `pytest plugins/wifi_llapi/tests/test_audit_runner_facade.py -v`
Expected: PASS（無硬體,決定性）。

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "test(ci): reconnect audit_runner_facade via replay RunBackend (P4)"
```

---

## Task 6: brcm 抽出新 private repo（程序 + 驗證）

**Files:** 新 git repo `brcm_fw_upgrade`(private)

- [ ] **Step 1: filter-repo 抽出 brcm 歷史**

```bash
git clone <current-repo> /tmp/brcm-extract && cd /tmp/brcm-extract
git filter-repo --path plugins/brcm_fw_upgrade
```
Expected: 新樹只含 brcm 路徑歷史。

- [ ] **Step 2: 驗證歷史只含 brcm**

Run: `git -C /tmp/brcm-extract log --name-only --pretty=format: | sort -u | grep -v '^$' | grep -v 'plugins/brcm_fw_upgrade' | head`
Expected: 空（無其他路徑外洩）。

- [ ] **Step 3: scaffold + pyproject + policy-check**

從 `new-project-template` scaffold;放 `pyproject.toml`(entry_point/api_version/pin testpilot);接 `paulsha-conventions` reusable policy-check(pinned SHA,同現 `.project-policy.yml` 形)。

- [ ] **Step 4: push 至新 private repo + CI 綠**

建 private remote → push;CI 裝釘選版 testpilot + nightly main。
Expected: brcm repo CI 綠燈。

- [ ] **Step 5: Commit(在 brcm repo)**

```bash
git commit -m "chore: bootstrap brcm_fw_upgrade as independent private dist (P4)"
```

---

## Task 7: core fresh public repo（程序 + secret-scan 閘)

**Files:** 新 git repo `testpilot`(public,fresh)

- [ ] **Step 1: fresh git init + 搬 sanitized core**

新目錄 `git init`;複製(非 git mv,**不帶歷史**)`src/testpilot/`(去 audit)、core `tests/`、`plugins/_template`、core-only `pyproject.toml`、架構文件(`docs/`、`openspec/`)、scaffold。

- [ ] **Step 2: secret-scan 閘必過**

Run: `<paulsha-conventions policy-check 本機等價 / R-21 secret-scan>`
Expected: PASS(無機敏)。**不過則修到過,絕不繞**。

- [ ] **Step 3: 驗證 fresh 無歷史**

Run: `git -C <core-repo> log --oneline | wc -l`
Expected: `1`(僅首 commit,無 monorepo 歷史)。

- [ ] **Step 4: 驗證中立 + CI 綠**

Run: `python -c "import pathlib; assert not pathlib.Path('src/testpilot/audit').exists(); assert not pathlib.Path('plugins/wifi_llapi').exists()"` 然後 `pytest -q`
Expected: 無 audit/vendor;測試在無 plugin 下綠燈。

- [ ] **Step 5: push 至 public repo（設 public)**

Expected: public core repo 上線,policy-check 綠。

---

## Task 8: 現 repo rename → wifi_llapi（private,留歷史)

**Files:** 現 repo（改名）

- [ ] **Step 1: rename repo + 開切分 branch**

repo 改名為 wifi_llapi(host 端設定 + remote);`git switch -c feature/physical-split-wifi`。

- [ ] **Step 2: 移除 core/brcm working tree（歷史保留)**

```bash
git rm -r src/testpilot plugins/brcm_fw_upgrade plugins/_template
# 保留 plugins/wifi_llapi/(含折入的 audit)
```
（`src/testpilot/audit` 已於 Task 2 搬走,故此處 `src/testpilot` 為 core-only。）

- [ ] **Step 3: 落定 wifi dist 結構**

把 `plugins/wifi_llapi/` 提為套件根(或設 pyproject 指向);pyproject + scaffold + policy-check 就位;CI 接 replay backend + 釘選版/nightly。

- [ ] **Step 4: 驗證 wifi repo 自足**

Run: `pip install -e . && pytest -q`(需先 `pip install testpilot` 釘選版)
Expected: 安裝成功;含接回的 full-run 測試全綠。

- [ ] **Step 5: 驗證歷史保留**

Run: `git log --oneline | wc -l`
Expected: 遠大於 1(全 monorepo 歷史在 private repo 內)。

- [ ] **Step 6: Commit + merge 切分 branch**

```bash
git add -A && git commit -m "refactor: strip core/brcm; wifi_llapi as standalone private dist (P4)"
```

---

## Task 9: 跨 repo 驗收 + 治理 + issues

**Files:** 無(驗收) + 更新 `docs/superpowers/plugin-sdk-decoupling-MOC.md`

- [ ] **Step 1: 跨 repo 安裝發現驗收**

乾淨 venv:`pip install testpilot`(core)+ `pip install wifi_llapi` + `pip install brcm_fw_upgrade`。
Run: `python -c "from importlib.metadata import entry_points; print(sorted(e.name for e in entry_points(group='testpilot.plugins')))"`
Expected: `['brcm_fw_upgrade', 'wifi_llapi']`。

- [ ] **Step 2: golden + full-run 驗收**

Run(wifi repo):`pytest -q`(golden 報表位元級不變 + 接回的 `test_audit_runner_facade` 綠)。
Run(core repo):`pytest -q`(中立綠燈)。

- [ ] **Step 3: 三判準確認**

確認:(1) allow-list 清空、(2) 物理獨立(wifi/brcm 獨立 dist + core public repo)、(3) full-run CI 接回。

- [ ] **Step 4: 不留雙軌確認**

Run(core repo):`grep -rn "wifi_llapi\|brcm_fw_upgrade" src/ | grep -v _template | head`
Expected: 空（core 無可跑 vendor 殘留)。

- [ ] **Step 5: 更新 MOC + 治理**

MOC 標 P4 ✅;各 repo R-12(branch)/R-17(PR keyword)滿足。

- [ ] **Step 6: 開延後 issues**

開 issue α(rename `wifi_llapi→LLAPI-WIFI-BCM` + vendor 中立 `LLAPI-AUDIT`,gate 在 MTK)、issue β(HLAPI 共用入口抽取);建下游「部署 stage」待辦(publish index/憑證/managed install/多 repo release governance)。

---

## Notes / 風險提醒

- **Task 5 replay fixture 與真機 drift**:fixture 標來源、定期以真 testbed 重錄;replay 為 CI 決定性閘,非取代實機驗收。
- **Task 7 secret-scan 是硬閘**:public core 首 commit 不過 R-21 則修到過,絕不繞道。
- **執行順序**:Task 1–5(in-monorepo,可逐一 merge 進現 main)務必先於 Task 6–9(物理操作);物理操作具不可逆性,每步先驗證再前進。
- **符號名彈性**:Task 0/1 的 B2 執行入口符號名以 B2 實作為準;若 B2 未涵蓋 audit runner_facade 路徑,回頭補 B2(B2 §6 已記此約束),不得在 wifi 側 import `testpilot.core`。

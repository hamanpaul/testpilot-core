# B2: core-owned execution loop（含 alignment 唯讀化）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans。Steps 用 `- [ ]`。本案為**行為保真型 refactor**;golden 報表 + 「run 不改 case 檔」守門是紅線。
> **前置:B1(`RunBackend`)必須已 merge**——core 迴圈寫在 `RunBackend` 上。

**Goal:** run loop 從 `WifiLlapiRunner` 上移進 `core/run_loop.py`(寫在 `RunBackend` + plugin hooks 上);wifi 走 core 預設路徑、brcm 走 create_runner override;run 路徑 alignment 唯讀(修 audit-invariant 違規);wifi production allow-list 清空。

**Architecture:** `orchestrator.run` → create_runner 有? 走 override(brcm):走 `run_loop`(wifi)。`run_loop` 用 `plugin.prepare_run()`(唯讀)取 runnable+drift,跑 RunBackend+execute_with_retry,產 `RunResult` → `plugin.create_reporter().build_reports()`。

**Tech Stack:** Python 3.12, pytest(`pythonpath=["src"]`)。change `core-owned-execution-loop`。spec `docs/superpowers/specs/2026-06-18-core-owned-execution-loop-design.md`。

---

## File Structure

- Create: `src/testpilot/core/run_loop.py` — core-owned 通用迴圈(搬自 `WifiLlapiRunner.run` 通用段)
- Modify: `src/testpilot/core/plugin_base.py` — 加 `prepare_run`(default discover+filter)
- Modify: `src/testpilot/core/orchestrator.py` — `run()` 委派:create_runner override 否則 run_loop;注入 run_backend+services
- Modify: `plugins/wifi_llapi/plugin.py` — 加 `prepare_run`(唯讀 alignment)、**移除 `create_runner`**
- Delete/empty: `plugins/wifi_llapi/runner.py` — `WifiLlapiRunner` 解散(prep→hook、loop→core);保留檔案僅留 wifi prep helper 或刪除
- Modify: `plugins/wifi_llapi/run_result.py` — `CaseRunRecord` 加 `drift: bool = False`
- Modify: `plugins/wifi_llapi/reporting/reporter.py` — `build_reports` 加 drift 標記輸出 + 收 xlsx-template 建立
- Modify: `tests/test_plugin_sdk_api_boundary.py` — wifi production allow-list 清空斷言
- Create: `tests/test_run_does_not_mutate_cases.py` — audit-invariant 守門
- Create: `tests/test_core_run_loop_contract.py`

---

## Task 1: RED — 守門 + 契約先紅

- [ ] **Step 1: audit-invariant 守門**

`tests/test_run_does_not_mutate_cases.py`:

```python
"""testpilot run 路徑 MUST NOT 修改 plugins/<plugin>/cases/(audit-mode invariant)。"""
from __future__ import annotations
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _cases_snapshot() -> dict[str, float]:
    cases = REPO / "plugins" / "wifi_llapi" / "cases"
    return {str(p): p.stat().st_mtime for p in sorted(cases.glob("*.y*ml"))}


def test_prepare_run_does_not_mutate_case_files(tmp_path):
    """wifi prepare_run(吸收 alignment)唯讀:呼叫後 case 檔不得變更。"""
    from testpilot.core.plugin_loader import PluginLoader
    loader = PluginLoader(REPO / "plugins")
    plugin = loader.load("wifi_llapi")
    before = _cases_snapshot()
    plugin.prepare_run(None)            # 唯讀
    after = _cases_snapshot()
    assert before == after, "prepare_run 改了 case 檔(違反 audit-invariant)"
    # 且 cases 目錄無未追蹤/修改(git 層級)
    out = subprocess.run(
        ["git", "status", "--porcelain", "plugins/wifi_llapi/cases"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.strip()
    assert out == "", f"run 路徑改了 case 檔:\n{out}"
```

- [ ] **Step 2: run_loop + prepare_run 契約**

`tests/test_core_run_loop_contract.py`:

```python
from __future__ import annotations
import inspect


def test_plugin_base_has_prepare_run():
    from testpilot.core.plugin_base import PluginBase
    assert hasattr(PluginBase, "prepare_run")
    params = list(inspect.signature(PluginBase.prepare_run).parameters)
    assert params[:2] == ["self", "case_ids"], params


def test_core_run_loop_module_exists():
    import importlib
    m = importlib.import_module("testpilot.core.run_loop")
    assert hasattr(m, "run") or hasattr(m, "run_cases")


def test_case_run_record_has_drift_flag():
    import dataclasses
    from plugins.wifi_llapi.run_result import CaseRunRecord
    names = {f.name for f in dataclasses.fields(CaseRunRecord)}
    assert "drift" in names
```

- [ ] **Step 3: boundary 守門擴充(wifi production 無 execution import)**

在 `tests/test_plugin_sdk_api_boundary.py`:把 `ALLOWLIST` 的 `execution_engine.ExecutionEngine` / `orchestrator.build_case_session_plan` / `reporting.log_capture` 三筆**移除**(B2 後 wifi 不該再有);保留 `case_validation` 的 schema 私有 helper(P2 才清)。

- [ ] **Step 4: 跑確認因正確理由紅**

Run: `python -m pytest tests/test_run_does_not_mutate_cases.py tests/test_core_run_loop_contract.py tests/test_plugin_sdk_api_boundary.py -v`
Expected: FAIL — run_loop/prepare_run/drift 未存在;wifi 仍 import execution(boundary)。擷取 RED。

---

## Task 2: GREEN — prepare_run hook（唯讀)

- [ ] **Step 1: PluginBase.prepare_run default**

`plugin_base.py` 加:

```python
def prepare_run(self, case_ids: list[str] | None) -> Any:
    """唯讀:回傳可執行 case 集 + 報表 artifacts。MUST NOT 改 case 檔。

    Default：discover_cases 後依 case_ids 過濾。
    """
    from testpilot.core.case_utils import case_matches_requested_ids
    cases = self.discover_cases()
    if case_ids:
        ids = {str(c).strip() for c in case_ids if str(c).strip()}
        cases = [c for c in cases if case_matches_requested_ids(c, ids)]
    return cases   # 形狀於 plan Step 2 以 PreparedRun 收斂
```

> `PreparedRun` 中性 dataclass(`cases`, `artifacts`)置於 `run_result.py`(與 RunResult 同處)。

- [ ] **Step 2: wifi prepare_run（唯讀 alignment,移除 mutation)**

`plugins/wifi_llapi/plugin.py` 加 `prepare_run`:把現 `runner._prepare_alignment` 邏輯搬來但**移除 `apply_alignment_mutations` 呼叫**,改為:
- 對每 case `align_case`(唯讀)取狀態;
- `already_aligned` → runnable(drift=False);
- `auto_aligned` → **in-memory** 套用 `source_row_after`/`id_after` 到 case dict,runnable(**drift=True**);**不寫檔**;
- `blocked`/`skipped` → artifacts(blocked/skipped/summary);
回傳 `PreparedRun(cases=[...帶 drift 旗標], artifacts=WifiLlapiAlignmentPrep(...))`。

- [ ] **Step 3: 跑 audit-invariant + prepare_run 契約至綠**

Run: `python -m pytest tests/test_run_does_not_mutate_cases.py tests/test_core_run_loop_contract.py::test_plugin_base_has_prepare_run -v` → PASS

---

## Task 3: GREEN — core/run_loop.py（搬通用迴圈)

- [ ] **Step 1: 建 run_loop**

`src/testpilot/core/run_loop.py`:`def run(plugin, plugin_name, case_ids, run_backend, services, dut_fw_ver=None, provider_config=None) -> dict`。把現 `WifiLlapiRunner.run` 的**通用段** verbatim 搬入,並把:
- serialwrap 呼叫 → `run_backend.setup_run/bind_sessions/mark_position/export_logs/teardown_run`(B1)
- `orchestrator.runner_selector` → `services.runner_selector`;`orchestrator.execution_engine` → `services.execution_engine`;`build_case_session_plan`/`ExecutionEngine` import 落 core
- prep 段 → `plugin.prepare_run(case_ids)`(取 cases+artifacts)
- 每 case 組 `CaseRunRecord(... , drift=case_drift)`;末端 `plugin.create_reporter().build_reports(RunResult(... , alignment_prep=prepared.artifacts))`

- [ ] **Step 2: CaseRunRecord 加 drift**

`run_result.py`:`CaseRunRecord` 加 `drift: bool = False`。

- [ ] **Step 3: 跑 run_loop 契約至綠**

Run: `python -m pytest tests/test_core_run_loop_contract.py -v` → PASS

---

## Task 4: GREEN — orchestrator 委派 + wifi 收尾

- [ ] **Step 1: orchestrator.run 委派**

`orchestrator.run()`:
```python
plugin = self.loader.load(plugin_name)
runner = plugin.create_runner()
if runner is not None and hasattr(runner, "run"):
    return self._run_via_runner(...)              # override(brcm)
from testpilot.core import run_loop
return run_loop.run(plugin, plugin_name, case_ids, self.run_backend,
                    services=self, dut_fw_ver=dut_fw_ver, provider_config=provider_config)
```
(`services=self` 或注入 orchestrator 子集;plan 可改 dataclass。移除舊 skeleton 預設分支或保留為「無 hooks」退路。)

- [ ] **Step 2: wifi 解散 runner + 收尾**

- `plugins/wifi_llapi/plugin.py`:**移除 `create_runner`**(改走 core 預設);`prepare_run` 已於 Task 2。
- `plugins/wifi_llapi/runner.py`:`WifiLlapiRunner` 解散;通用迴圈已進 core;prep 已進 prepare_run。檔案若無剩餘 helper 則刪除。
- `reporting/reporter.py`:`build_reports` 對 `run_result.cases` 中 `drift=True` 者,於組 `WifiLlapiCaseResult` 的 comment/reason **不論 pass/fail 附加** `drift=blocked(需 audit)`;把現 runner 的 xlsx-from-template 建立移進 build_reports 開頭。
- 移除 wifi production 對 `ExecutionEngine`/`build_case_session_plan`/`log_capture` 的 import。

- [ ] **Step 3: 跑 boundary 守門至綠**

Run: `python -m pytest tests/test_plugin_sdk_api_boundary.py -v` → PASS(allow-list 已無 execution 三筆)

---

## Task 5: 回歸驗證 — 行為位元級不變

- [ ] **Step 1: audit-invariant + allow-list**

Run: `python -m pytest tests/test_run_does_not_mutate_cases.py tests/test_plugin_sdk_api_boundary.py -q` → PASS

- [ ] **Step 2: golden 報表(fixture 已對齊無 drift,輸出不變)**

Run: `python -m pytest tests/test_wifi_llapi_report_golden.py plugins/wifi_llapi/tests -q` → PASS

- [ ] **Step 3: drift 行為測試**

新增/確認:對一個刻意 drift 的 case(fixture),執行後 verdict 正常、報表 reason 含 `drift=blocked`;case 檔未被改。

- [ ] **Step 4: 全套 + grep**

Run: `python -m pytest -q` → PASS;
`grep -rnE "execution_engine|build_case_session_plan|log_capture" plugins/wifi_llapi --include=*.py | grep -v /tests/ | grep -v __pycache__` → 空。

- [ ] **Step 5: Commit**

```bash
git add src/testpilot/core/run_loop.py src/testpilot/core/plugin_base.py src/testpilot/core/orchestrator.py plugins/wifi_llapi tests/ openspec/changes/core-owned-execution-loop
git commit -m "feat(core): core-owned execution loop + read-only run-path alignment"
```

---

## Task 6: 收尾(workflow 後段)

- [ ] 6.1 requesting-code-review(行為保真 / 迴圈正確 / audit-invariant / 契約純淨)
- [ ] 6.2 receiving-code-review + re-review 至無 Critical/Important
- [ ] 6.3 openspec archive → policy → conventional commit → push → PR(R-12/R-17)

---

## Self-Review

- **Spec coverage:** core 擁迴圈(Req)→ Task 3/4;prepare_run 唯讀(Req)→ Task 2 + Task 1 守門;run 不改 case(Req)→ Task 1 守門 + Task 2 移除 mutation;create_runner override(MODIFIED)→ Task 4.1。
- **Placeholder scan:** 無 TBD;守門/契約測試完整;通用迴圈搬移以「verbatim + RunBackend/services 代換」界定。
- **Type consistency:** `prepare_run(self, case_ids)`、`CaseRunRecord.drift`、`PreparedRun{cases, artifacts}` 與契約測試一致;`build_reports(run_result)` 沿用 P1b。
- **行為保真重點:** 通用迴圈只搬位置 + RunBackend 代換;alignment 只移除寫檔(in-memory 對齊 row 不變落點);drift 標記只對真 drift case 出現,golden fixture(已對齊)不受影響。

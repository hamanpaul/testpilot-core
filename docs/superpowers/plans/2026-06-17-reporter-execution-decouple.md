# P1b reporter↔execution 解耦 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本案為**順序型 refactor**,task 間有強依賴,須依序執行。

**Goal:** 把 wifi_llapi 整-run 執行迴圈從「reporter」拆到新 `WifiLlapiRunner`,reporter 變純格式化(execution import=0),以 raw `RunResult` 交接。行為位元級不變。

**Architecture:** `Orchestrator.run()` →(委派 `create_runner()`)→ `WifiLlapiRunner.run()`(prep+serialwrap+逐case執行+log匯出 → 組 `RunResult` → `reporter.build_reports(run_result)`)。reporter 只吃 `RunResult`。

**Tech Stack:** Python 3.12, pytest(`pythonpath=["src"]`)。change `decouple-reporter-from-execution`。設計 `docs/superpowers/specs/2026-06-17-reporter-execution-decouple-design.md`。

---

## File Structure

- Create: `plugins/wifi_llapi/run_result.py` — `CaseRunRecord` + `RunResult` + 搬入 `WifiLlapiAlignmentPrep`(中性 dataclass,無執行引擎 import)
- Create: `plugins/wifi_llapi/runner.py` — `WifiLlapiRunner`(執行迴圈;execution import 落此)
- Modify: `plugins/wifi_llapi/reporting/reporter.py` — 純化為 `generate`(IReporter)+ `build_reports(run_result)`;移除 execution import 與執行 helper
- Modify: `src/testpilot/core/plugin_base.py` — 加 `create_runner()`(default None)
- Modify: `src/testpilot/core/orchestrator.py` — `_run_via_reporter` → `_run_via_runner`
- Modify: `plugins/wifi_llapi/plugin.py` — 加 `create_runner()`
- Modify: `tests/test_plugin_sdk_api_boundary.py` — reporter 純淨斷言
- Create: `tests/test_wifi_llapi_run_result_contract.py` — RunResult 契約 + reporter 簽章

**搬移對照(現 `reporting/reporter.py`):**
- → runner.py:`_resolve_firmware_version`(98-115)、`_load_case_pairs`(116-139)、`_build_alignment_summary`(143-174)、`_prepare_alignment`(176-226)、`_apply_plugin_execution_policy`(240-271)、`run()` 執行段(275-492:prep→serialwrap→逐case execute_with_retry→trace→log匯出,即建 `case_results`/`case_seq_ranges`/log paths 之前的全部執行)
- → reporter.build_reports():`run()` 報表尾段(494-582:fill_case_results、`_finalize_alignment_artifacts`、finalize_report_metadata、timing、summary、generate_reports、回傳 dict)
- → run_result.py:`WifiLlapiAlignmentPrep`(69-75)
- 留 reporter.py:`__init__`(83-84)、`generate`(88-94 IReporter)、`_finalize_alignment_artifacts`(228-238)

---

## Task 1: RED — 契約測試先紅

**Files:** Modify `tests/test_plugin_sdk_api_boundary.py`;Create `tests/test_wifi_llapi_run_result_contract.py`

- [ ] **Step 1: 擴充 boundary guard — reporter 純淨斷言**

在 `tests/test_plugin_sdk_api_boundary.py` 末加:

```python
def test_wifi_llapi_reporter_has_no_execution_imports():
    """reporter 模組不得依賴執行引擎(P1b:reporter↔execution 解耦)。"""
    import ast
    reporter = WIFI_LLAPI_ROOT / "reporting" / "reporter.py"
    tree = ast.parse(reporter.read_text(encoding="utf-8"), filename=str(reporter))
    forbidden = {
        ("testpilot.core.execution_engine", None),
        ("testpilot.core.orchestrator", "build_case_session_plan"),
        ("testpilot.reporting", "log_capture"),
    }
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "testpilot.core.execution_engine":
                hits.append(f"{reporter.name}:{node.lineno} {node.module}")
            if node.module == "testpilot.core.orchestrator":
                for a in node.names:
                    if a.name == "build_case_session_plan":
                        hits.append(f"{reporter.name}:{node.lineno} {a.name}")
            if node.module == "testpilot.reporting":
                for a in node.names:
                    if a.name == "log_capture":
                        hits.append(f"{reporter.name}:{node.lineno} {a.name}")
    assert not hits, "reporter 仍含 execution import:\n" + "\n".join(hits)
```

- [ ] **Step 2: RunResult 契約測試**

Create `tests/test_wifi_llapi_run_result_contract.py`:

```python
"""RunResult 契約 + reporter 純消費簽章(change decouple-reporter-from-execution)。"""
from __future__ import annotations

import dataclasses
import inspect


def test_run_result_dataclasses_exist_with_fields():
    from plugins.wifi_llapi.run_result import CaseRunRecord, RunResult

    crr = {f.name for f in dataclasses.fields(CaseRunRecord)}
    assert {"case", "retry", "source_row", "trace_path",
            "seq_start", "seq_end", "started_at", "finished_at",
            "duration_seconds"} <= crr

    rr = {f.name for f in dataclasses.fields(RunResult)}
    assert {"cases", "run_id", "run_date", "plugin_name", "fw_ver",
            "fw_ver_source", "artifact_dir", "template_path", "report_path",
            "agent_trace_dir", "dut_log_path", "sta_log_path", "timing_rows",
            "alignment_prep", "execution_policy"} <= rr


def test_reporter_build_reports_consumes_run_result():
    from plugins.wifi_llapi.reporting.reporter import WifiLlapiReporter

    sig = inspect.signature(WifiLlapiReporter.build_reports)
    params = list(sig.parameters)
    assert params == ["self", "run_result"], params


def test_runner_exists_with_run():
    from plugins.wifi_llapi.runner import WifiLlapiRunner

    assert hasattr(WifiLlapiRunner, "run")
```

- [ ] **Step 3: 跑測試確認因正確理由紅**

Run: `python -m pytest tests/test_plugin_sdk_api_boundary.py::test_wifi_llapi_reporter_has_no_execution_imports tests/test_wifi_llapi_run_result_contract.py -v`
Expected: 全 FAIL — reporter 仍含 execution import;`run_result`/`runner` 模組與 `build_reports` 尚未存在。擷取 RED 證據。

---

## Task 2: GREEN — RunResult dataclass

**Files:** Create `plugins/wifi_llapi/run_result.py`

- [ ] **Step 1: 寫 dataclass(raw 粒度,零執行引擎 import)**

```python
"""RunResult — wifi_llapi 執行階段推給報表階段的結構化交接物。

只存值,不 import 執行引擎;型別以 Any/字串標註避免反向依賴 core 執行。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class WifiLlapiAlignmentPrep:
    runnable_cases: list[dict[str, Any]]
    blocked_results: list[Any]
    skipped_results: list[Any]
    alignment_summary: dict[str, Any]


@dataclass
class CaseRunRecord:
    case: dict[str, Any]
    retry: Any                      # core.execution_engine.RetryResult(不在此 import)
    source_row: int
    trace_path: str
    seq_start: int | None
    seq_end: int | None
    started_at: str
    finished_at: str
    duration_seconds: float


@dataclass
class RunResult:
    cases: list[CaseRunRecord]
    run_id: str
    run_date: date
    plugin_name: str
    fw_ver: str
    fw_ver_source: str
    artifact_dir: Path
    template_path: Path
    report_path: Path
    agent_trace_dir: Path
    dut_log_path: str
    sta_log_path: str
    timing_rows: list[dict[str, Any]]
    alignment_prep: WifiLlapiAlignmentPrep
    execution_policy: dict[str, Any]
    run_started_at: str = ""
    first_case_started_at: str = ""
    first_case_started_monotonic: float | None = None
    run_started_monotonic: float = 0.0
```

> 註:`WifiLlapiAlignmentPrep` 從 reporter.py(69-75)搬來;reporter.py 改 import 自此。`timing`/monotonic 欄位給 reporter 重建 timing_rows;若 runner 已組好 timing_rows 則 reporter 直接用,monotonic 欄位可省(實作時二擇一,契約測試只檢核心欄位)。

- [ ] **Step 2: 跑契約測試結構部分**

Run: `python -m pytest tests/test_wifi_llapi_run_result_contract.py::test_run_result_dataclasses_exist_with_fields -v`
Expected: PASS。

---

## Task 3: GREEN — runner 接手執行迴圈

**Files:** Create `plugins/wifi_llapi/runner.py`

- [ ] **Step 1: 建 runner,搬入執行 helper 與迴圈**

`WifiLlapiRunner`:
- import:`ExecutionEngine`(`testpilot.core.execution_engine`)、`build_case_session_plan`(`testpilot.core.orchestrator`,lazy 同現狀)、`log_capture`(`testpilot.reporting`,lazy 同現狀)、testpilot.api 的 case helper、wifi_llapi align/excel/case_validation/command 模組(依現 reporter.py import 搬移)。
- 方法搬移(verbatim,改 `self.` 維持):`_resolve_firmware_version`、`_load_case_pairs`、`_build_alignment_summary`、`_prepare_alignment`、`_apply_plugin_execution_policy`(現 reporter.py 98-271)。
- `run(self, orchestrator, plugin_name, case_ids, dut_fw_ver, provider_config=None) -> dict[str, Any]`:把現 `reporter.run()` 275-492 的執行段 verbatim 搬入(prep、serialwrap 起、fw 解析、report 從 template 建立、逐 case execute_with_retry+trace+log seq、serialwrap log 匯出);把迴圈內建立的 `WifiLlapiCaseResult` 改為改建 `CaseRunRecord`(只存 raw:case/retry/source_row/trace_path/seq_start/seq_end/started_at/finished_at/duration_seconds)——**不在 runner 算 band results/status**。
- 組 `RunResult`(填上 cases/run_id/run_date/plugin_name/fw_ver/fw_ver_source/artifact_dir/template_path/report_path/agent_trace_dir/dut_log_path/sta_log_path/timing 基礎/alignment_prep/execution_policy)。
- 末端:`from plugins.wifi_llapi.reporting.reporter import WifiLlapiReporter` →`return WifiLlapiReporter().build_reports(run_result)`。

> 搬移要點:現迴圈中 `result_5g/6g/24g`、`status`、attempt status 充實、`WifiLlapiCaseResult(...)` 與 pass/fail 計數**移到 reporter**(它們是格式化)。runner 只把每 case 的 `retry_result` 原樣存進 `CaseRunRecord`。trace 寫檔(`ExecutionEngine.write_case_trace`)留 runner(執行 trace);但 trace payload 內的 `status`/band 充實若需要,改在 runner 用 raw verdict 計或延後——以行為不變為準,實作時對齊 golden。

- [ ] **Step 2: 跑 runner 存在性測試**

Run: `python -m pytest tests/test_wifi_llapi_run_result_contract.py::test_runner_exists_with_run -v`
Expected: PASS。

---

## Task 4: GREEN — reporter 純化

**Files:** Modify `plugins/wifi_llapi/reporting/reporter.py`

- [ ] **Step 1: 移除 execution import 與執行 helper**

- 刪 `from testpilot.core.execution_engine import ExecutionEngine`、`from testpilot.core.orchestrator import build_case_session_plan`(lazy)、`from testpilot.reporting import log_capture`(lazy)。
- 刪已搬到 runner 的 helper(`_resolve_firmware_version`/`_load_case_pairs`/`_build_alignment_summary`/`_prepare_alignment`/`_apply_plugin_execution_policy`)與整段 `run()`。
- `WifiLlapiAlignmentPrep` 改 `from plugins.wifi_llapi.run_result import WifiLlapiAlignmentPrep`。
- 保留:`__init__`、`generate`(IReporter)、`_finalize_alignment_artifacts`。

- [ ] **Step 2: 加 `build_reports(run_result)`**

把現 `run()` 報表尾段(494-582)搬成 `def build_reports(self, run_result):`:
- 從 `run_result.cases`(`CaseRunRecord`)逐筆算 `_case_band_results`/`_overall_case_status`、組 `WifiLlapiCaseResult`、pass/fail 計數、attempt status 充實(若 golden 需要)。
- `fill_case_results`、`self._finalize_alignment_artifacts(report_path=run_result.report_path, artifact_dir=run_result.artifact_dir, prep=run_result.alignment_prep)`、`finalize_report_metadata`、timing_rows(用 run_result.timing 基礎)、`build_wifi_llapi_summary`+`write_summary_sheet`、`generate_reports`。
- 回傳與現 `run()` **完全相同**的結果 dict(plugin/plugin_version/cases_count/pass/fail/status/artifact_dir/template_path/report_path/md·json·html_report_path/dut·sta_log_path/run_id/agent_trace_dir/agent_trace_count)。
- `plugin_version` 來源:run_result 需帶或由 reporter 經 plugin 取得 —— 實作時把 `plugin.version` 在 runner 放進 run_result(加欄位 `plugin_version`),或 reporter 不需要時改用 run_result 既有值。對齊現輸出。

- [ ] **Step 3: 跑 boundary 純淨 + 契約簽章測試**

Run: `python -m pytest tests/test_plugin_sdk_api_boundary.py tests/test_wifi_llapi_run_result_contract.py -v`
Expected: 全 PASS。

---

## Task 5: GREEN — 委派接線

**Files:** Modify `src/testpilot/core/plugin_base.py`、`src/testpilot/core/orchestrator.py`、`plugins/wifi_llapi/plugin.py`

- [ ] **Step 1: PluginBase.create_runner**

在 `plugin_base.py` 的 reporter hook 附近加:

```python
def create_runner(self) -> Any:
    """Return a runner that owns the full run loop, or None.

    Plugins that drive their own run/report pipeline override this.
    Default None → orchestrator uses skeleton behavior.
    """
    return None
```

- [ ] **Step 2: orchestrator 委派改 runner**

`orchestrator.py`:把 `_run_via_reporter`(401-416)改為 `_run_via_runner`:`runner = self.loader.load(plugin_name).create_runner(); return runner.run(self, plugin_name, case_ids, dut_fw_ver, provider_config)`。`run()`(420-444)的判斷由 `create_reporter()...has run` 改為 `create_runner() is not None`。移除舊 reporter.run 委派分支。

- [ ] **Step 3: wifi plugin 實作 create_runner**

`plugins/wifi_llapi/plugin.py`:加
```python
def create_runner(self) -> Any:
    from plugins.wifi_llapi.runner import WifiLlapiRunner
    return WifiLlapiRunner()
```
(保留 `create_reporter()` 供 IReporter.generate 與 runner 內部使用。)

- [ ] **Step 4: 跑 orchestrator 相關測試**

Run: `python -m pytest plugins/wifi_llapi/tests/test_orchestrator_per_case_agent.py plugins/wifi_llapi/tests/test_orchestrator_realistic_runtime.py -q`
Expected: PASS。

---

## Task 6: 回歸驗證 — 行為位元級不變

- [ ] **Step 1: wifi_llapi 報表測試**

Run: `python -m pytest plugins/wifi_llapi/tests tests/test_wifi_llapi_report_golden.py tests/test_wifi_llapi_excel.py tests/test_wifi_llapi_summary.py tests/test_wifi_llapi_reproject.py -q`
Expected: 全 PASS(golden 報表位元級不變)。

- [ ] **Step 2: 全套**

Run: `python -m pytest -q`
Expected: 全 PASS / 僅既有 skip。

- [ ] **Step 3: Commit**

```bash
git add plugins/wifi_llapi src/testpilot/core/plugin_base.py src/testpilot/core/orchestrator.py tests/test_plugin_sdk_api_boundary.py tests/test_wifi_llapi_run_result_contract.py openspec/changes/decouple-reporter-from-execution
git commit -m "feat(plugin): decouple reporter from execution via WifiLlapiRunner + RunResult"
```

---

## Self-Review

- **Spec coverage:** reporter 純淨(Req: reporter 不含執行依賴)→ Task 1.1 + Task 4;runner→RunResult→reporter(Req: 執行/報表分離)→ Task 2/3/4 + 契約測試;create_runner 委派(Req)→ Task 5;行為不變(Req)→ Task 6。
- **Placeholder scan:** 無 TBD;新檔/測試含完整碼;大段 verbatim 搬移以行號+轉換說明界定(避免轉錄分歧)。
- **Type consistency:** `build_reports(self, run_result)`、`RunResult`/`CaseRunRecord` 欄位名與契約測試一致;`WifiLlapiAlignmentPrep` 單一定義(run_result.py)、reporter import 之。
- **行為保真重點(實作須對齊 golden):** band results/status/`WifiLlapiCaseResult`/pass-fail/trace payload 的 status 充實移到 reporter 後,輸出須與現狀一致——以既有 golden 測試為準繩。

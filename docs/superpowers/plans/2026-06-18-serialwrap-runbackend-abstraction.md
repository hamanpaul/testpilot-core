# Phase 3 (B1): serialwrap → RunBackend 抽象 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans。Steps 用 `- [ ]`。本案為**行為保真型 refactor**(56 觸點搬位置、不改演算),golden/log_capture 測試是紅線。

**Goal:** 把 serialwrap 的 run-level 邏輯抽到可換的 `RunBackend` provider 後;`core`/`reporting` 不再具名 serialwrap,serialwrap 為預設 provider。行為位元級不變。

**Architecture:** 新 `src/testpilot/runtime/`:`RunBackend` ABC + 中性 dataclass、`SerialwrapBackend`(預設,收編現 `log_capture` 邏輯為私有 helper + 宣告式 command 表)、`DirectTtyBackend`(stub)。`orchestrator` 持有 `run_backend`,三個 serialwrap 方法改為**薄 delegator**;`reporting`/`runner` 不再直接 import serialwrap/log_capture。

**Tech Stack:** Python 3.12, pytest(`pythonpath=["src"]`)。change `abstract-serialwrap-runbackend`。spec `docs/superpowers/specs/2026-06-18-serialwrap-runbackend-abstraction-design.md`。

---

## File Structure

- Create: `src/testpilot/runtime/__init__.py`
- Create: `src/testpilot/runtime/run_backend.py` — `RunBackend` ABC + `RunHandle`/`ExportRequest`/`ExportResult`
- Create: `src/testpilot/runtime/serialwrap_backend.py` — `SerialwrapBackend`(預設)
- Create: `src/testpilot/runtime/_serialwrap_log.py` — 由 `reporting/log_capture.py` **整檔移入**(SerialwrapBackend 私有 helper)
- Create: `src/testpilot/runtime/direct_tty_backend.py` — `DirectTtyBackend` stub
- Create: `src/testpilot/runtime/factory.py` — `create_run_backend(kind, config)`(預設 `"serialwrap"`)
- Modify: `src/testpilot/core/orchestrator.py` — 持有 `self.run_backend`;三方法改薄 delegator;移除 `log_capture` import
- Modify: `src/testpilot/reporting/__init__.py` / 任何 `from testpilot.reporting import log_capture` — 改道(reporting 不再導出 serialwrap)
- Modify: `plugins/wifi_llapi/runner.py` — `log_capture.get_current_seq()` → `orchestrator.run_backend.mark_position()`;移除 `log_capture` import(清 allow-list)
- Modify: `tests/test_plugin_sdk_api_boundary.py` — 守門斷言 core/reporting 不具名 serialwrap
- Create: `tests/test_run_backend_contract.py`

**現 `log_capture` → `RunBackend` 行為對照(realization map):**
| RunBackend 行為 | 收編的現有函式 |
|---|---|
| `setup_run` | `configure`+`daemon_status`/`start_daemon`+`clean_wal`/`wal_reset`+`get_wal_path` |
| `bind_sessions` | `setup_sessions` |
| `mark_position` | `get_current_seq`/`wal_current_seq` |
| `export_logs` | `export_records`+`decode_log`+`save_decoded_log`+`build_seq_to_line_map`+`seq_range_to_line_range` |
| `teardown_run` | 現 `_stop_serialwrap`(keep-alive) |

---

## Task 1: RED — 契約 + 守門先紅

**Files:** Create `tests/test_run_backend_contract.py`; Modify `tests/test_plugin_sdk_api_boundary.py`

- [ ] **Step 1: RunBackend 契約測試**

```python
"""RunBackend 契約 + serialwrap 為預設 provider(change abstract-serialwrap-runbackend)。"""
from __future__ import annotations
import inspect


def test_run_backend_interface_methods():
    from testpilot.runtime.run_backend import RunBackend
    for m in ("setup_run", "bind_sessions", "mark_position", "export_logs", "teardown_run"):
        assert hasattr(RunBackend, m), f"RunBackend missing {m}"


def test_serialwrap_backend_implements_runbackend():
    from testpilot.runtime.run_backend import RunBackend
    from testpilot.runtime.serialwrap_backend import SerialwrapBackend
    assert issubclass(SerialwrapBackend, RunBackend)


def test_factory_defaults_to_serialwrap():
    from testpilot.runtime.factory import create_run_backend
    from testpilot.runtime.serialwrap_backend import SerialwrapBackend
    assert isinstance(create_run_backend(None, {}), SerialwrapBackend)


def test_direct_tty_backend_exists_as_stub():
    from testpilot.runtime.run_backend import RunBackend
    from testpilot.runtime.direct_tty_backend import DirectTtyBackend
    assert issubclass(DirectTtyBackend, RunBackend)
```

- [ ] **Step 2: 守門斷言 core/reporting 不具名 serialwrap**

在 `tests/test_plugin_sdk_api_boundary.py` 末加:

```python
def test_core_and_reporting_have_no_serialwrap_names():
    """run-level serialwrap 具體邏輯只能存在於 runtime backend(P3)。"""
    import re
    targets = [REPO_ROOT / "src" / "testpilot" / "core",
               REPO_ROOT / "src" / "testpilot" / "reporting"]
    pat = re.compile(r"serialwrap|log_capture|\bwal\b", re.IGNORECASE)
    hits = []
    for root in targets:
        for p in root.rglob("*.py"):
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if pat.search(line):
                    hits.append(f"{p.relative_to(REPO_ROOT)}:{i}: {line.strip()}")
    assert not hits, "core/reporting 仍具名 serialwrap:\n" + "\n".join(hits)
```

- [ ] **Step 3: 跑確認因正確理由紅**

Run: `python -m pytest tests/test_run_backend_contract.py tests/test_plugin_sdk_api_boundary.py::test_core_and_reporting_have_no_serialwrap_names -v`
Expected: FAIL — `testpilot.runtime.*` 未存在;core/reporting 仍滿是 serialwrap。擷取 RED。

---

## Task 2: GREEN — RunBackend 介面 + 中性 dataclass

**Files:** Create `src/testpilot/runtime/__init__.py`, `src/testpilot/runtime/run_backend.py`

- [ ] **Step 1: 寫介面 + dataclass**

```python
"""RunBackend — run-level 裝置存取的可換 provider(lifecycle + log capture)。

core/reporting 只依賴此抽象;具體後端(serialwrap / direct-tty)各自 impl。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunHandle:
    wal_path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExportRequest:
    run_id: str
    artifact_dir: Path
    case_seq_ranges: dict[str, dict[str, int | None]]
    case_results: list[Any]
    run_seq_start: int | None = None
    run_seq_end: int | None = None
    dut_com: str | None = None
    sta_com: str | None = None


@dataclass
class ExportResult:
    dut_log_path: str = ""
    sta_log_path: str = ""


class RunBackend(ABC):
    @abstractmethod
    def setup_run(self) -> RunHandle: ...
    @abstractmethod
    def bind_sessions(self, devices: Any) -> None: ...
    @abstractmethod
    def mark_position(self, handle: RunHandle | None = None) -> int | None: ...
    @abstractmethod
    def export_logs(self, request: ExportRequest) -> ExportResult: ...
    @abstractmethod
    def teardown_run(self) -> None: ...
```

- [ ] **Step 2: 跑契約介面測試至綠**

Run: `python -m pytest tests/test_run_backend_contract.py::test_run_backend_interface_methods -v` → PASS

---

## Task 3: GREEN — SerialwrapBackend(verbatim 收編)

**Files:** Create `runtime/_serialwrap_log.py`, `runtime/serialwrap_backend.py`, `runtime/direct_tty_backend.py`, `runtime/factory.py`

- [ ] **Step 1: 移入 log 邏輯**

`git mv src/testpilot/reporting/log_capture.py src/testpilot/runtime/_serialwrap_log.py`(整檔搬,內容不改演算)。

- [ ] **Step 2: SerialwrapBackend 包裝**

`runtime/serialwrap_backend.py`:`class SerialwrapBackend(RunBackend)`,5 個行為方法的 body = 現 `orchestrator._start_serialwrap_for_run`/`_export_serialwrap_logs`/`_stop_serialwrap` + `mark_position`(get_current_seq)+ `bind_sessions`(setup_sessions),內部呼叫 `from testpilot.runtime import _serialwrap_log as sw`。behavior→serialwrap 指令對照集中為模組級宣告式 dict(`_COMMANDS = {...}`),realize 時記入 trace。**邏輯 verbatim 自現 orchestrator 三方法搬移**。

- [ ] **Step 3: DirectTtyBackend stub**

```python
from testpilot.runtime.run_backend import RunBackend, RunHandle, ExportRequest, ExportResult

class DirectTtyBackend(RunBackend):
    """介面預留:pyserial + tee 檔。尚未實作。"""
    def setup_run(self) -> RunHandle: raise NotImplementedError("DirectTtyBackend pending")
    def bind_sessions(self, devices): raise NotImplementedError("DirectTtyBackend pending")
    def mark_position(self, handle=None): raise NotImplementedError("DirectTtyBackend pending")
    def export_logs(self, request) -> ExportResult: raise NotImplementedError("DirectTtyBackend pending")
    def teardown_run(self) -> None: raise NotImplementedError("DirectTtyBackend pending")
```

- [ ] **Step 4: factory**

```python
from testpilot.runtime.run_backend import RunBackend
from testpilot.runtime.serialwrap_backend import SerialwrapBackend

def create_run_backend(kind: str | None, config: dict | None = None) -> RunBackend:
    normalized = (kind or "serialwrap").strip().lower()
    if normalized in {"serialwrap", "serial", ""}:
        return SerialwrapBackend(config or {})
    if normalized in {"direct_tty", "ttyusb"}:
        from testpilot.runtime.direct_tty_backend import DirectTtyBackend
        return DirectTtyBackend(config or {})
    raise ValueError(f"unknown run_backend: {kind}")
```

- [ ] **Step 5: 跑 Task1 契約測試(serialwrap/factory/stub)全綠**

Run: `python -m pytest tests/test_run_backend_contract.py -v` → PASS

---

## Task 4: GREEN — 取用點改寫(去 serialwrap 具名)

**Files:** Modify `core/orchestrator.py`, `reporting/` 引用, `plugins/wifi_llapi/runner.py`

- [ ] **Step 1: orchestrator 持有 run_backend + 薄 delegator**

`orchestrator.__init__`:`self.run_backend = create_run_backend(self.config.raw.get("testbed", {}).get("run_backend"), self.config.raw.get("testbed", {}))`。移除 `from testpilot.reporting import log_capture` 與 `log_capture.configure(...)`。把 `_start_serialwrap_for_run`/`_export_serialwrap_logs`/`_stop_serialwrap` 改為薄 delegator(各自 `return self.run_backend.setup_run()` / `.export_logs(ExportRequest(...))` / `.teardown_run()`),保留方法名讓 runner 既有呼叫不必動。

- [ ] **Step 2: runner 的 log_capture 改走 run_backend**

`plugins/wifi_llapi/runner.py`:`log_capture.get_current_seq(wal_path)`(3 處)→ `orchestrator.run_backend.mark_position(handle)`;移除 `from testpilot.reporting import log_capture`。`build_case_session_plan`/`ExecutionEngine` 暫不動(屬 Phase 4 allow-list)。

- [ ] **Step 3: 清掉 reporting 對 log_capture 的再導出**

確認 `from testpilot.reporting import log_capture` 在 core/reporting/runner 全數消失(改走 run_backend / runtime)。

- [ ] **Step 4: 跑守門至綠**

Run: `python -m pytest tests/test_plugin_sdk_api_boundary.py -v` → PASS(含新 serialwrap 守門)

---

## Task 5: 回歸驗證 — 行為位元級不變

- [ ] **Step 1: serialwrap/log 測試**

Run: `python -m pytest tests/test_log_capture.py -q`（若測試 import 路徑隨搬移調整,更新為 `testpilot.runtime._serialwrap_log`）→ PASS

- [ ] **Step 2: golden 報表(日誌行範圍不變)**

Run: `python -m pytest tests/test_wifi_llapi_report_golden.py plugins/wifi_llapi/tests -q` → PASS

- [ ] **Step 3: 全套**

Run: `python -m pytest -q` → PASS / 僅既有 skip

- [ ] **Step 4: grep 確認**

Run: `grep -rniE "serialwrap|log_capture|\bwal\b" src/testpilot/core src/testpilot/reporting --include=*.py | grep -v __pycache__`
Expected: 空(具體邏輯只在 `src/testpilot/runtime/`)

- [ ] **Step 5: Commit**

```bash
git add src/testpilot/runtime src/testpilot/core/orchestrator.py src/testpilot/reporting plugins/wifi_llapi/runner.py tests/test_run_backend_contract.py tests/test_plugin_sdk_api_boundary.py openspec/changes/abstract-serialwrap-runbackend
git commit -m "feat(runtime): abstract serialwrap behind RunBackend provider"
```

---

## Task 6: 收尾(workflow 後段)

- [ ] 6.1 requesting-code-review(行為保真 / 抽象正確 / 契約純淨）
- [ ] 6.2 receiving-code-review + re-review 至無 Critical/Important
- [ ] 6.3 openspec archive → policy → conventional commit → push → PR(R-12/R-17)

---

## Self-Review

- **Spec coverage:** RunBackend 抽象(Req1)→ Task 2/3/4 + 契約測試;行為/執行分離+映射在 provider(Req2)→ Task 3 宣告式表 + case 不動 + trace;行為不變(Req3)→ Task 5。
- **Placeholder scan:** 無 TBD;介面/factory/stub/守門為完整碼;verbatim 搬移以 realization map + `git mv` 界定。
- **Type consistency:** `RunBackend` 5 方法與契約測試一致;`ExportRequest`/`ExportResult` 欄位對齊現 `_export_serialwrap_logs` 的輸入輸出;orchestrator 薄 delegator 保留原方法名故 runner 既有呼叫相容。
- **行為保真重點:** serialwrap 邏輯只搬位置(`git mv` + verbatim)不改演算;報表 `dut/sta_log_lines` 行範圍以 golden 為準繩。

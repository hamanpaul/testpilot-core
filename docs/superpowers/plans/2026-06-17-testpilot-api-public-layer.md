# testpilot.api 公開契約層 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 立起 `testpilot.api` 作為 plugin 唯一公開契約表面,堵掉 wifi_llapi 對 core 內部的低風險洩漏,並以 boundary 守門測試把界線鎖死。

**Architecture:** `testpilot.api` 為薄 re-export 層(零新邏輯);wifi_llapi production 的低風險 import 全 repoint 至 `testpilot.api`;高風險(reporter↔execution)與私有 schema helper 洩漏以 AST boundary 守門測試的明列 allow-list 隔離,每筆標註後續消除 change。對外行為位元級不變。

**Tech Stack:** Python 3.12, pytest 8/9, `ast`(靜態 import 掃描)。OpenSpec change: `establish-testpilot-api-public-layer`。

---

## File Structure

- Create: `src/testpilot/api/__init__.py` — 公開符號 re-export + `__all__`(契約表面)
- Create: `src/testpilot/api/excel_adapter.py` — `reporting.excel_adapter` 之公開子模組 re-export
- Create: `tests/test_plugin_sdk_api_boundary.py` — 公開層完整性 + wifi_llapi 越界守門
- Modify(repoint,純 import 來源變更):
  - `plugins/wifi_llapi/command_resolver.py:15`
  - `plugins/wifi_llapi/plugin.py:15,16,18,19`
  - `plugins/wifi_llapi/reporting/reporter.py:26-31,33,34`(僅低風險;保留 32/282/283 高風險)
  - `plugins/wifi_llapi/case_validation.py:22`(拆公開/私有)
  - `plugins/wifi_llapi/reporting/wifi_llapi_excel.py:22`
  - `plugins/wifi_llapi/reporting/wifi_llapi_inventory.py:14`
  - `plugins/wifi_llapi/reporting/wifi_llapi_reproject.py:34`

---

## Task 1: RED — boundary 守門測試先紅

**Files:**
- Create: `tests/test_plugin_sdk_api_boundary.py`

- [ ] **Step 1: 寫守門測試(公開層完整性 + wifi_llapi 越界 allow-list)**

```python
"""Boundary guard for the testpilot.api plugin contract.

change: establish-testpilot-api-public-layer

兩個保證:
1. testpilot.api 匯出已承諾的公開契約表面(且為與原模組相同的物件)。
2. plugins/wifi_llapi production code 不得 reach 進 testpilot.core/schema/reporting
   內部,除非列於明示 allow-list(每筆標註負責消除的後續 change)。
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WIFI_LLAPI_ROOT = REPO_ROOT / "plugins" / "wifi_llapi"

# 公開符號 -> 其原始模組(用 identity 比對,確保 re-export 非複製)
PUBLIC_SURFACE = {
    "PluginBase": "testpilot.core.plugin_base",
    "IReporter": "testpilot.reporting.reporter",
    "MarkdownReporter": "testpilot.reporting.reporter",
    "JsonReporter": "testpilot.reporting.reporter",
    "HtmlReporter": "testpilot.reporting.html_reporter",
    "generate_reports": "testpilot.reporting.reporter",
    "TransportBase": "testpilot.transport.base",
    "StubTransport": "testpilot.transport.base",
    "load_case": "testpilot.schema.case_schema",
    "load_cases_dir": "testpilot.schema.case_schema",
    "CaseValidationError": "testpilot.schema.case_schema",
    "validate_case": "testpilot.schema.case_schema",
    "TestbedConfig": "testpilot.core.testbed_config",
    "stringify_step_command": "testpilot.core.case_utils",
    "step_command_lines": "testpilot.core.case_utils",
    "case_band_results": "testpilot.core.case_utils",
    "case_matches_requested_ids": "testpilot.core.case_utils",
    "overall_case_status": "testpilot.core.case_utils",
    "sanitize_case_id": "testpilot.core.case_utils",
}

# plugin 不得直接 reach 進的內部命名空間
GUARDED_PREFIXES = ("testpilot.core", "testpilot.schema", "testpilot.reporting")

# 已知、已記錄、尚未消除的洩漏。(module, symbol) -> 負責消除的後續 change。
ALLOWLIST = {
    ("testpilot.core.execution_engine", "ExecutionEngine"):
        "P1b: decouple reporter from execution",
    ("testpilot.core.orchestrator", "build_case_session_plan"):
        "P1b: decouple reporter from execution",
    ("testpilot.reporting", "log_capture"):
        "P1b: decouple reporter from execution",
    ("testpilot.schema.case_schema", "_require_non_empty_string"):
        "follow-up: schema validation contract",
    ("testpilot.schema.case_schema", "_validate_string_list"):
        "follow-up: schema validation contract",
}


def _is_guarded(module: str) -> bool:
    return any(module == p or module.startswith(p + ".") for p in GUARDED_PREFIXES)


def _production_py_files():
    for path in sorted(WIFI_LLAPI_ROOT.rglob("*.py")):
        parts = path.relative_to(WIFI_LLAPI_ROOT).parts
        if "tests" in parts or "scripts" in parts:
            continue
        yield path


def test_public_surface_exports_same_objects():
    api = importlib.import_module("testpilot.api")
    assert hasattr(api, "__all__"), "testpilot.api must declare __all__"
    for name, origin_mod in PUBLIC_SURFACE.items():
        assert name in api.__all__, f"{name} missing from testpilot.api.__all__"
        origin = importlib.import_module(origin_mod)
        assert getattr(api, name) is getattr(origin, name), (
            f"testpilot.api.{name} is not the same object as {origin_mod}.{name}"
        )
    excel = importlib.import_module("testpilot.api.excel_adapter")
    origin_excel = importlib.import_module("testpilot.reporting.excel_adapter")
    for fn in ("col_to_index", "is_merged_cell", "open_workbook"):
        assert getattr(excel, fn) is getattr(origin_excel, fn), (
            f"testpilot.api.excel_adapter.{fn} mismatch"
        )


def test_wifi_llapi_does_not_breach_core_boundary():
    violations = []
    for path in _production_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if not _is_guarded(node.module):
                continue
            for alias in node.names:
                if (node.module, alias.name) not in ALLOWLIST:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno} "
                        f"-> from {node.module} import {alias.name}"
                    )
    assert not violations, (
        "wifi_llapi production code breaches testpilot.api boundary "
        "(repoint to testpilot.api or add to ALLOWLIST with a follow-up change):\n"
        + "\n".join(violations)
    )
```

- [ ] **Step 2: 跑測試確認因正確理由而紅**

Run: `python -m pytest tests/test_plugin_sdk_api_boundary.py -v`
Expected: 兩個測試皆 FAIL — `test_public_surface_...` 因 `ModuleNotFoundError: testpilot.api`;`test_wifi_llapi_...` 因多筆低風險 import 仍越界(case_utils/plugin_base/case_schema/reporter/excel_adapter/transport.base 不在 allow-list)。擷取輸出為 RED 證據。

- [ ] **Step 3: 不 commit,進 Task 2(先綠公開層)**

---

## Task 2: GREEN — 建立 `testpilot.api` 公開層

**Files:**
- Create: `src/testpilot/api/__init__.py`
- Create: `src/testpilot/api/excel_adapter.py`

- [ ] **Step 1: 寫 `src/testpilot/api/__init__.py`**

```python
"""testpilot.api — plugin 的唯一公開契約表面。

凡未經本模組匯出之符號,即為 core 私有,不對 plugin 承諾穩定。
本層僅 re-export 既有符號,不含新邏輯(契約宣告與實作分離)。
"""
from __future__ import annotations

from testpilot.core.case_utils import (
    case_band_results,
    case_matches_requested_ids,
    overall_case_status,
    sanitize_case_id,
    step_command_lines,
    stringify_step_command,
)
from testpilot.core.plugin_base import PluginBase
from testpilot.core.testbed_config import TestbedConfig
from testpilot.reporting.html_reporter import HtmlReporter
from testpilot.reporting.reporter import (
    IReporter,
    JsonReporter,
    MarkdownReporter,
    generate_reports,
)
from testpilot.schema.case_schema import (
    CaseValidationError,
    load_case,
    load_cases_dir,
    validate_case,
)
from testpilot.transport.base import StubTransport, TransportBase

from testpilot.api import excel_adapter  # noqa: F401  (公開子模組)

__all__ = [
    "PluginBase",
    "IReporter",
    "MarkdownReporter",
    "JsonReporter",
    "HtmlReporter",
    "generate_reports",
    "TransportBase",
    "StubTransport",
    "load_case",
    "load_cases_dir",
    "CaseValidationError",
    "validate_case",
    "TestbedConfig",
    "stringify_step_command",
    "step_command_lines",
    "case_band_results",
    "case_matches_requested_ids",
    "overall_case_status",
    "sanitize_case_id",
    "excel_adapter",
]
```

- [ ] **Step 2: 寫 `src/testpilot/api/excel_adapter.py`**

```python
"""testpilot.api.excel_adapter — reporting.excel_adapter 的公開 re-export。"""
from __future__ import annotations

from testpilot.reporting.excel_adapter import (
    col_to_index,
    is_merged_cell,
    open_workbook,
)

__all__ = ["col_to_index", "is_merged_cell", "open_workbook"]
```

- [ ] **Step 3: 跑公開層測試確認轉綠**

Run: `python -m pytest tests/test_plugin_sdk_api_boundary.py::test_public_surface_exports_same_objects -v`
Expected: PASS。(`test_wifi_llapi_...` 仍 FAIL,待 Task 3。)

---

## Task 3: GREEN — repoint wifi_llapi 低風險 import

逐檔做精確 import 來源變更。**只動 import 行,不動使用碼**(符號名與別名保持不變)。

- [ ] **Step 1: `command_resolver.py:15`**

將 `from testpilot.core.case_utils import stringify_step_command, step_command_lines`
改為 `from testpilot.api import stringify_step_command, step_command_lines`

- [ ] **Step 2: `plugin.py` 四行**

- `:15` `from testpilot.core.case_utils import stringify_step_command, step_command_lines` → `from testpilot.api import stringify_step_command, step_command_lines`
- `:16` `from testpilot.core.plugin_base import PluginBase` → `from testpilot.api import PluginBase`
- `:18` `from testpilot.schema.case_schema import load_cases_dir` → `from testpilot.api import load_cases_dir`
- `:19` `from testpilot.transport.base import StubTransport` → `from testpilot.api import StubTransport`

- [ ] **Step 3: `reporting/reporter.py`(僅低風險,保留高風險)**

將 26-31 行的 case_utils 區塊
```python
from testpilot.core.case_utils import (
    case_band_results as _case_band_results,
    case_matches_requested_ids as _case_matches_requested_ids,
    overall_case_status as _overall_case_status,
    sanitize_case_id as _sanitize_case_id,
)
```
改為(來源換成 testpilot.api,別名不變)
```python
from testpilot.api import (
    case_band_results as _case_band_results,
    case_matches_requested_ids as _case_matches_requested_ids,
    overall_case_status as _overall_case_status,
    sanitize_case_id as _sanitize_case_id,
)
```
第 33 行 `from testpilot.reporting.reporter import MarkdownReporter, generate_reports` → `from testpilot.api import MarkdownReporter, generate_reports`
第 34 行 `from testpilot.schema.case_schema import load_case` → `from testpilot.api import load_case`
**保留不動**:第 32 行 `ExecutionEngine`、第 282 行 `log_capture`、第 283 行 `build_case_session_plan`(allow-list,P1b)。

- [ ] **Step 4: `case_validation.py:22`(拆公開/私有)**

將
```python
from testpilot.schema.case_schema import (
    CaseValidationError,
    _require_non_empty_string,
    _validate_string_list,
    validate_case,
)
```
改為
```python
from testpilot.api import CaseValidationError, validate_case
from testpilot.schema.case_schema import (  # allow-list: 私有驗證 helper,待 schema 驗證契約另案
    _require_non_empty_string,
    _validate_string_list,
)
```

- [ ] **Step 5: `reporting/wifi_llapi_excel.py:22`**

將
```python
from testpilot.reporting.excel_adapter import (
    col_to_index as column_index_from_string,
    is_merged_cell,
    open_workbook as load_workbook,
)
```
改為(來源換成 testpilot.api.excel_adapter,別名不變)
```python
from testpilot.api.excel_adapter import (
    col_to_index as column_index_from_string,
    is_merged_cell,
    open_workbook as load_workbook,
)
```

- [ ] **Step 6: `reporting/wifi_llapi_inventory.py:14`**

`from testpilot.schema.case_schema import load_case` → `from testpilot.api import load_case`

- [ ] **Step 7: `reporting/wifi_llapi_reproject.py:34`**

`from testpilot.reporting.reporter import generate_reports` → `from testpilot.api import generate_reports`

- [ ] **Step 8: 跑守門測試確認全綠**

Run: `python -m pytest tests/test_plugin_sdk_api_boundary.py -v`
Expected: 兩測試皆 PASS。

---

## Task 4: 回歸驗證 — 行為位元級不變

**Files:** 無(只跑測試)

- [ ] **Step 1: wifi_llapi 測試集**

Run: `python -m pytest plugins/wifi_llapi/tests -q`
Expected: 全綠(repoint 為純來源變更,行為不變)。

- [ ] **Step 2: 全套測試**

Run: `python -m pytest -q`
Expected: 全綠,無回歸(testpaths = tests + plugins/wifi_llapi/tests + plugins/brcm_fw_upgrade/tests)。

- [ ] **Step 3: grep 確認 production 殘留只剩 allow-list**

Run: `grep -rn "from testpilot.core\|from testpilot.schema\|from testpilot.reporting import\|from testpilot.reporting.reporter\|from testpilot.reporting.excel_adapter" plugins/wifi_llapi --include="*.py" | grep -v "/tests/" | grep -v __pycache__`
Expected: 僅剩 `reporter.py` 的 ExecutionEngine/log_capture/build_case_session_plan 與 `case_validation.py` 的兩個底線 helper。

- [ ] **Step 4: Commit(全部變更一次)**

```bash
git add src/testpilot/api tests/test_plugin_sdk_api_boundary.py plugins/wifi_llapi
git commit -m "feat(api): establish testpilot.api public contract layer + repoint wifi_llapi low-risk leaks"
```

---

## Task 5: 收尾(pipeline 後段)

- [ ] **Step 1:** requesting-code-review(boundary 測試 + 公開層 + repoint diff)
- [ ] **Step 2:** receiving-code-review,逐項處理,re-review 至無 Critical/Important
- [ ] **Step 3:** policy 檢查 → openspec archive → conventional commit → push → PR(branch `feature/testpilot-api-public-layer`,PR body 含 closing keyword,R-12/R-17)

---

## Self-Review

- **Spec coverage:** 公開層完整性(Requirement 1)→ Task 1 Step1 PUBLIC_SURFACE + Task 2;plugin 不越界(Requirement 2)→ Task 1 守門 + Task 3 repoint + allow-list;行為不變(Requirement 3)→ Task 4。三 Requirement 皆有對應 task。
- **Placeholder scan:** 無 TBD/TODO;所有 import 變更含 before/after 完整碼;守門測試與公開層為完整檔案。
- **Type consistency:** `_case_band_results` 等別名在 reporter.py 前後一致;PUBLIC_SURFACE 的符號名與 `__all__`、各 import 行一致;excel 別名 `column_index_from_string`/`load_workbook` 保持不變。

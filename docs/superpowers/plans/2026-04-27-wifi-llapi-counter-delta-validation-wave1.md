# wifi_llapi Counter Delta Validation — Wave 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the runtime + reporter foundation for delta-based counter validation in `wifi_llapi`, plus migrate two sample cases (D037 / D313) that prove the new format end-to-end.

**Architecture:** Add a `phase: baseline | trigger | verify` step label, two new pass_criteria operators (`delta_nonzero`, `delta_match`), a load-time phase ordering validator that marks violators BLOCKED, a new `Comment` column M in the xlsx report carrying evaluate-failure notes. Existing `field+value`/`field+reference` evaluation paths remain unchanged.

**Tech Stack:** Python 3.11+, `openpyxl` for xlsx writing, `pytest` for tests, `PyYAML` for case files.

**Reference:** Spec at `docs/superpowers/specs/2026-04-27-issue-38-counter-delta-validation-design.md`; OpenSpec change at `openspec/changes/wifi-llapi-counter-delta-validation/`.

**Out of scope (Wave 2/3):** ~30 Stage A case migrations and ~50 Stage B case migrations. They each get their own plan after Wave 1 ships.

---

## File Structure

**Modified files:**
- `plugins/wifi_llapi/plugin.py` — add `ZERO_DELTA_COMMENT` constant, `_validate_phase_ordering()`, `_evaluate_delta_criterion()`, evaluate dispatch refactor, `discover_cases` hook
- `src/testpilot/reporting/wifi_llapi_excel.py` — bump `DEFAULT_TEMPLATE_MAX_COLUMN` to `"M"`, add `COMMENT_HEADER`, `_truncate_comment()` helper, write M column in `fill_case_results()`
- `src/testpilot/core/orchestrator.py` — merge `plugin._phase_blocked` (new attr) into `prep.blocked_results` during `_prepare_wifi_llapi_alignment`
- `tests/test_wifi_llapi_excel.py` — extend with M column / truncate / regression tests
- `plugins/wifi_llapi/cases/D037_retransmissions.yaml` — migrated to delta range
- `plugins/wifi_llapi/cases/D313_getssidstats_retranscount.yaml` — migrated to delta range

**New files:**
- `plugins/wifi_llapi/CASE_YAML_SYNTAX.md` — long-lived yaml syntax reference
- `tests/test_wifi_llapi_delta.py` — unit tests for delta operators + phase validator
- `tests/test_wifi_llapi_delta_integration.py` — end-to-end test: discover → execute (mocked) → evaluate → reporter
- `tests/fixtures/wifi_llapi_delta/delta_nonzero_pass.yaml`
- `tests/fixtures/wifi_llapi_delta/delta_nonzero_fail.yaml`
- `tests/fixtures/wifi_llapi_delta/delta_match_pass.yaml`
- `tests/fixtures/wifi_llapi_delta/phase_invalid.yaml`

Each file has one clear responsibility — runtime decisions live in `plugin.py`; xlsx layout in `wifi_llapi_excel.py`; orchestration glue in `orchestrator.py`; documentation in `CASE_YAML_SYNTAX.md`.

---

## Task 1: Reporter — Add `COMMENT_HEADER` constant and bump max column to M

**Files:**
- Modify: `src/testpilot/reporting/wifi_llapi_excel.py:27-44`
- Test: `tests/test_wifi_llapi_excel.py`

- [ ] **Step 1.1: Write the failing test**

Append to `tests/test_wifi_llapi_excel.py`:

```python
def test_default_template_max_column_is_M():
    from testpilot.reporting.wifi_llapi_excel import DEFAULT_TEMPLATE_MAX_COLUMN
    assert DEFAULT_TEMPLATE_MAX_COLUMN == "M"


def test_comment_header_constant_exists():
    from testpilot.reporting.wifi_llapi_excel import COMMENT_HEADER
    assert COMMENT_HEADER == "Comment"


def test_default_clear_columns_includes_M():
    from testpilot.reporting.wifi_llapi_excel import DEFAULT_CLEAR_COLUMNS
    assert "M" in DEFAULT_CLEAR_COLUMNS
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `pytest tests/test_wifi_llapi_excel.py::test_default_template_max_column_is_M tests/test_wifi_llapi_excel.py::test_comment_header_constant_exists tests/test_wifi_llapi_excel.py::test_default_clear_columns_includes_M -v`
Expected: 3 failures (`assert "L" == "M"`, `ImportError: cannot import name 'COMMENT_HEADER'`, `assert "M" in (...)` false)

- [ ] **Step 1.3: Apply minimal change**

Edit `src/testpilot/reporting/wifi_llapi_excel.py` lines 29-44:

```python
DEFAULT_TEMPLATE_MAX_COLUMN = "M"
RESULT_GROUP_HEADER = "Result"
RESULT_HEADERS_BY_COLUMN = {
    "I": "WiFi 5G",
    "J": "WiFi 6G",
    "K": "WiFi 2.4G",
}
TESTER_HEADER = "Tester"
COMMENT_HEADER = "Comment"
DEFAULT_CLEAR_COLUMNS = (
    "G",   # Test steps
    "H",   # Driver-level verified command output
    "I",   # ARC 5g result
    "J",   # ARC 6g result
    "K",   # ARC 2.4g result
    "L",   # ARC tester
    "M",   # Evaluate-failure comment
)
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `pytest tests/test_wifi_llapi_excel.py -v`
Expected: previously failing 3 tests pass; existing tests still pass.

- [ ] **Step 1.5: Commit**

```bash
git add src/testpilot/reporting/wifi_llapi_excel.py tests/test_wifi_llapi_excel.py
git commit -m "reporter(wifi_llapi): bump template max column to M, add COMMENT_HEADER"
```

---

## Task 2: Reporter — Header normalization writes "Comment" at row 3 column 13

**Files:**
- Modify: `src/testpilot/reporting/wifi_llapi_excel.py:_normalize_template_headers`
- Test: `tests/test_wifi_llapi_excel.py`

- [ ] **Step 2.1: Write the failing test**

Append to `tests/test_wifi_llapi_excel.py`:

```python
def test_normalize_template_headers_writes_comment_in_M(tmp_path):
    """Row 3 column 13 must contain COMMENT_HEADER after header normalization."""
    from openpyxl import Workbook
    from testpilot.reporting.wifi_llapi_excel import (
        _normalize_template_headers,
        COMMENT_HEADER,
        DEFAULT_SHEET_NAME,
    )

    wb = Workbook()
    ws = wb.active
    ws.title = DEFAULT_SHEET_NAME
    _normalize_template_headers(ws)
    assert ws.cell(row=3, column=13).value == COMMENT_HEADER
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `pytest tests/test_wifi_llapi_excel.py::test_normalize_template_headers_writes_comment_in_M -v`
Expected: FAIL with `assert None == "Comment"`.

- [ ] **Step 2.3: Modify `_normalize_template_headers()`**

In `src/testpilot/reporting/wifi_llapi_excel.py`, locate the function (around line 304) and add the comment header line at the end:

```python
def _normalize_template_headers(ws) -> None:
    """Normalize Wifi_LLAPI result/tester header semantics for columns I~M."""
    for merged in list(ws.merged_cells.ranges):
        if merged.max_row < 2 or merged.min_row > 2:
            continue
        if merged.max_col < 9 or merged.min_col > 13:
            continue
        ws.unmerge_cells(str(merged))

    ws.merge_cells(start_row=2, end_row=2, start_column=9, end_column=11)
    ws.cell(row=2, column=9).value = RESULT_GROUP_HEADER
    ws.cell(row=2, column=12).value = TESTER_HEADER
    ws.cell(row=3, column=9).value = RESULT_HEADERS_BY_COLUMN["I"]
    ws.cell(row=3, column=10).value = RESULT_HEADERS_BY_COLUMN["J"]
    ws.cell(row=3, column=11).value = RESULT_HEADERS_BY_COLUMN["K"]
    ws.cell(row=3, column=12).value = TESTER_HEADER
    ws.cell(row=3, column=13).value = COMMENT_HEADER
```

(Note: also bumped `merged.min_col > 12` to `> 13` so any future M-column merges aren't accidentally preserved.)

- [ ] **Step 2.4: Run test to verify it passes**

Run: `pytest tests/test_wifi_llapi_excel.py -v`
Expected: previously failing test passes; existing tests still pass.

- [ ] **Step 2.5: Commit**

```bash
git add src/testpilot/reporting/wifi_llapi_excel.py tests/test_wifi_llapi_excel.py
git commit -m "reporter(wifi_llapi): write Comment header in column M during template normalization"
```

---

## Task 3: Reporter — `_truncate_comment()` helper

**Files:**
- Modify: `src/testpilot/reporting/wifi_llapi_excel.py` (add helper near other small utilities, e.g. after `normalize_command_block`)
- Test: `tests/test_wifi_llapi_excel.py`

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_wifi_llapi_excel.py`:

```python
def test_truncate_comment_short_text_unchanged():
    from testpilot.reporting.wifi_llapi_excel import _truncate_comment
    assert _truncate_comment("hello") == "hello"


def test_truncate_comment_exactly_200_unchanged():
    from testpilot.reporting.wifi_llapi_excel import _truncate_comment
    text = "a" * 200
    assert _truncate_comment(text) == text


def test_truncate_comment_201_chars_truncates():
    from testpilot.reporting.wifi_llapi_excel import _truncate_comment
    text = "a" * 201
    out = _truncate_comment(text)
    assert len(out) == 203  # 200 + "..."
    assert out.endswith("...")
    assert out.startswith("a" * 200)


def test_truncate_comment_empty_returns_empty():
    from testpilot.reporting.wifi_llapi_excel import _truncate_comment
    assert _truncate_comment("") == ""


def test_truncate_comment_none_returns_empty():
    from testpilot.reporting.wifi_llapi_excel import _truncate_comment
    assert _truncate_comment(None) == ""
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `pytest tests/test_wifi_llapi_excel.py -k truncate_comment -v`
Expected: 5 failures (`ImportError: cannot import name '_truncate_comment'`).

- [ ] **Step 3.3: Add the helper**

In `src/testpilot/reporting/wifi_llapi_excel.py`, after the `normalize_command_block` function (around line 154), insert:

```python
def _truncate_comment(text: str | None, *, limit: int = 200) -> str:
    """Truncate evaluate-failure comments to fit M column display.

    Returns "" for None / empty input. Appends '...' when the source string
    exceeds `limit` characters; otherwise returns the input unchanged.
    """
    if text is None:
        return ""
    s = str(text)
    if len(s) <= limit:
        return s
    return s[:limit] + "..."
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `pytest tests/test_wifi_llapi_excel.py -k truncate_comment -v`
Expected: 5 PASS.

- [ ] **Step 3.5: Commit**

```bash
git add src/testpilot/reporting/wifi_llapi_excel.py tests/test_wifi_llapi_excel.py
git commit -m "reporter(wifi_llapi): add _truncate_comment helper for M column"
```

---

## Task 4: Reporter — `fill_case_results()` writes `comment` to M column

**Files:**
- Modify: `src/testpilot/reporting/wifi_llapi_excel.py:fill_case_results` (~line 434-458)
- Test: `tests/test_wifi_llapi_excel.py`

- [ ] **Step 4.1: Write the failing test**

Append to `tests/test_wifi_llapi_excel.py`:

```python
def test_fill_case_results_writes_M_column(tmp_path):
    """fill_case_results writes WifiLlapiCaseResult.comment to column M."""
    from openpyxl import Workbook, load_workbook
    from testpilot.reporting.wifi_llapi_excel import (
        DEFAULT_SHEET_NAME,
        WifiLlapiCaseResult,
        fill_case_results,
        _normalize_template_headers,
    )

    # Build a minimal report with one data row at row 4.
    report = tmp_path / "report.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = DEFAULT_SHEET_NAME
    _normalize_template_headers(ws)
    wb.save(report)

    item = WifiLlapiCaseResult(
        case_id="D037",
        source_row=4,
        executed_test_command="echo cmd",
        command_output="output",
        result_5g="FAIL",
        result_6g="N/A",
        result_24g="N/A",
        comment="fail 原因為 0，數值無變化",
    )
    fill_case_results(report, [item])

    wb2 = load_workbook(report)
    ws2 = wb2[DEFAULT_SHEET_NAME]
    assert ws2.cell(row=4, column=13).value == "fail 原因為 0，數值無變化"


def test_fill_case_results_empty_comment_leaves_M_empty(tmp_path):
    from openpyxl import Workbook, load_workbook
    from testpilot.reporting.wifi_llapi_excel import (
        DEFAULT_SHEET_NAME,
        WifiLlapiCaseResult,
        fill_case_results,
        _normalize_template_headers,
    )
    report = tmp_path / "report.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = DEFAULT_SHEET_NAME
    _normalize_template_headers(ws)
    wb.save(report)

    item = WifiLlapiCaseResult(
        case_id="D200",
        source_row=4,
        executed_test_command="echo cmd",
        command_output="output",
        result_5g="PASS",
        result_6g="PASS",
        result_24g="PASS",
        comment="",
    )
    fill_case_results(report, [item])

    wb2 = load_workbook(report)
    ws2 = wb2[DEFAULT_SHEET_NAME]
    assert ws2.cell(row=4, column=13).value in (None, "")  # not "None" string


def test_fill_case_results_truncates_long_comment(tmp_path):
    from openpyxl import Workbook, load_workbook
    from testpilot.reporting.wifi_llapi_excel import (
        DEFAULT_SHEET_NAME,
        WifiLlapiCaseResult,
        fill_case_results,
        _normalize_template_headers,
    )
    report = tmp_path / "report.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = DEFAULT_SHEET_NAME
    _normalize_template_headers(ws)
    wb.save(report)

    long_comment = "x" * 250
    item = WifiLlapiCaseResult(
        case_id="D300",
        source_row=4,
        executed_test_command="echo cmd",
        command_output="output",
        result_5g="FAIL",
        result_6g="N/A",
        result_24g="N/A",
        comment=long_comment,
    )
    fill_case_results(report, [item])

    wb2 = load_workbook(report)
    ws2 = wb2[DEFAULT_SHEET_NAME]
    cell = ws2.cell(row=4, column=13).value
    assert isinstance(cell, str)
    assert len(cell) == 203
    assert cell.endswith("...")
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `pytest tests/test_wifi_llapi_excel.py -k fill_case_results -v`
Expected: 3 new tests fail (M column is None for all because writer not yet writing it).

- [ ] **Step 4.3: Modify `fill_case_results()`**

In `src/testpilot/reporting/wifi_llapi_excel.py`, locate `fill_case_results` (~line 434) and add the M write after the L write:

```python
def fill_case_results(
    report_xlsx: Path | str,
    case_results: Iterable[WifiLlapiCaseResult],
    *,
    sheet_name: str = DEFAULT_SHEET_NAME,
) -> Path:
    """Batch fill test command and result columns by source row."""
    path = Path(report_xlsx)
    wb = load_workbook(path)
    ws = _get_sheet(wb, sheet_name)

    for item in case_results:
        if item.source_row <= 0:
            continue
        row = item.source_row
        _set_cell_value_safe(ws, row, "G", normalize_command_block(item.executed_test_command))
        _set_cell_value_safe(ws, row, "H", sanitize_report_output(item.command_output))
        _set_cell_value_safe(ws, row, "I", item.result_5g)
        _set_cell_value_safe(ws, row, "J", item.result_6g)
        _set_cell_value_safe(ws, row, "K", item.result_24g)
        _set_cell_value_safe(ws, row, "L", item.tester)
        _set_cell_value_safe(ws, row, "M", _truncate_comment(item.comment) or None)

    wb.save(path)
    wb.close()
    return path
```

(Note: `or None` keeps cell empty when comment is "" rather than writing the empty string — matches `test_fill_case_results_empty_comment_leaves_M_empty`.)

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `pytest tests/test_wifi_llapi_excel.py -k fill_case_results -v`
Expected: all 3 new tests + any existing fill_case_results tests PASS.

- [ ] **Step 4.5: Commit**

```bash
git add src/testpilot/reporting/wifi_llapi_excel.py tests/test_wifi_llapi_excel.py
git commit -m "reporter(wifi_llapi): write WifiLlapiCaseResult.comment to M column with truncation"
```

---

## Task 5: Reporter — Regression guard: BLOCKED / SKIP markers don't touch M

**Files:**
- Test only: `tests/test_wifi_llapi_excel.py`

- [ ] **Step 5.1: Write the regression tests**

Append to `tests/test_wifi_llapi_excel.py`:

```python
def test_blocked_marker_writes_H_not_M(tmp_path):
    """fill_blocked_markers must not write to column M."""
    from dataclasses import dataclass
    from openpyxl import Workbook, load_workbook
    from testpilot.reporting.wifi_llapi_excel import (
        DEFAULT_SHEET_NAME,
        fill_blocked_markers,
        _normalize_template_headers,
    )

    @dataclass
    class _BlockedStub:
        source_row_before: int
        blocked_reason: str

    report = tmp_path / "report.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = DEFAULT_SHEET_NAME
    _normalize_template_headers(ws)
    # extend rows so row=4 is addressable
    ws.cell(row=4, column=1).value = "anchor"
    wb.save(report)

    fill_blocked_markers(report, [_BlockedStub(source_row_before=4, blocked_reason="some_reason")])

    wb2 = load_workbook(report)
    ws2 = wb2[DEFAULT_SHEET_NAME]
    assert ws2.cell(row=4, column=8).value == "BLOCKED: some_reason"  # H
    assert ws2.cell(row=4, column=13).value in (None, "")               # M empty


def test_skip_marker_writes_H_not_M(tmp_path):
    """fill_skip_markers must not write to column M."""
    from dataclasses import dataclass
    from openpyxl import Workbook, load_workbook
    from testpilot.reporting.wifi_llapi_excel import (
        DEFAULT_SHEET_NAME,
        fill_skip_markers,
        _normalize_template_headers,
    )

    @dataclass
    class _SkipStub:
        source_row_before: int
        template_row: int

    report = tmp_path / "report.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = DEFAULT_SHEET_NAME
    _normalize_template_headers(ws)
    ws.cell(row=4, column=1).value = "anchor"
    ws.cell(row=10, column=1).value = "anchor10"
    wb.save(report)

    fill_skip_markers(report, [_SkipStub(source_row_before=4, template_row=10)])

    wb2 = load_workbook(report)
    ws2 = wb2[DEFAULT_SHEET_NAME]
    assert ws2.cell(row=4, column=8).value == "SKIP: duplicate with D010"   # H
    assert ws2.cell(row=4, column=13).value in (None, "")                   # M empty
```

- [ ] **Step 5.2: Run tests — they should already pass without code change**

Run: `pytest tests/test_wifi_llapi_excel.py -k "blocked_marker or skip_marker" -v`
Expected: both PASS without any source change (regression guard against future drift).

- [ ] **Step 5.3: Commit**

```bash
git add tests/test_wifi_llapi_excel.py
git commit -m "test(wifi_llapi_excel): regression guards that BLOCKED/SKIP markers do not touch M column"
```

---

## Task 6: Plugin — Add `ZERO_DELTA_COMMENT` constant

**Files:**
- Modify: `plugins/wifi_llapi/plugin.py` (module-level, near other constants)
- Test: `tests/test_wifi_llapi_delta.py` (new file)

- [ ] **Step 6.1: Write the failing test**

Create `tests/test_wifi_llapi_delta.py` with:

```python
"""Unit tests for wifi_llapi delta-validation runtime (Wave 1 of #38/#13)."""

from __future__ import annotations


def test_zero_delta_comment_constant():
    from plugins.wifi_llapi.plugin import ZERO_DELTA_COMMENT
    assert ZERO_DELTA_COMMENT == "fail 原因為 0，數值無變化"
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `pytest tests/test_wifi_llapi_delta.py::test_zero_delta_comment_constant -v`
Expected: `ImportError: cannot import name 'ZERO_DELTA_COMMENT'`.

- [ ] **Step 6.3: Add the constant**

In `plugins/wifi_llapi/plugin.py`, immediately after the imports / module docstring (look for the first non-import line near the top, e.g. before `class Plugin`), add:

```python
ZERO_DELTA_COMMENT = "fail 原因為 0，數值無變化"
DELTA_VALUE_NOT_NUMERIC_COMMENT = "fail 原因為 delta 端點非數值"
DELTA_MISMATCH_COMMENT_TEMPLATE = "fail 原因為 delta 不一致：api={a} drv={b} tol={t}%"
```

- [ ] **Step 6.4: Run test to verify it passes**

Run: `pytest tests/test_wifi_llapi_delta.py::test_zero_delta_comment_constant -v`
Expected: PASS.

- [ ] **Step 6.5: Commit**

```bash
git add plugins/wifi_llapi/plugin.py tests/test_wifi_llapi_delta.py
git commit -m "plugin(wifi_llapi): add ZERO_DELTA_COMMENT and related comment constants"
```

---

## Task 7: Plugin — `_evaluate_delta_criterion()` for `delta_nonzero`

**Files:**
- Modify: `plugins/wifi_llapi/plugin.py` (add method to `Plugin` class)
- Test: `tests/test_wifi_llapi_delta.py`

- [ ] **Step 7.1: Write the failing tests**

Append to `tests/test_wifi_llapi_delta.py`:

```python
import pytest

from plugins.wifi_llapi.plugin import Plugin


def _build_context(values: dict[str, dict[str, object]]) -> dict[str, object]:
    """Build an eval_context shape matching what _build_eval_context returns:

    For each capture name, store as both `context[name]` (a dict) and an entry
    under `context["steps"]` so _resolve_field can find it via dotted lookup.
    """
    ctx: dict[str, object] = {"steps": {}, "_aggregate_output": "", "_capture_raw": {}}
    for cap, payload in values.items():
        ctx[cap] = payload
        ctx["steps"][cap] = {"success": True, "output": "", "captured": payload, "returncode": 0}
    return ctx


def _make_plugin() -> Plugin:
    return Plugin()


def test_delta_nonzero_pass():
    plugin = _make_plugin()
    ctx = _build_context({"before_5g": {"X": 10}, "after_5g": {"X": 42}})
    case = {"id": "T1", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_5g.X", "verify": "after_5g.X"},
        "operator": "delta_nonzero",
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is True
    assert "_last_failure" not in case


def test_delta_nonzero_fail_zero():
    plugin = _make_plugin()
    ctx = _build_context({"before_5g": {"X": 10}, "after_5g": {"X": 10}})
    case = {"id": "T2", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_5g.X", "verify": "after_5g.X"},
        "operator": "delta_nonzero",
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is False
    assert case["_last_failure"]["reason_code"] == "delta_zero"
    assert case["_last_failure"]["comment"] == "fail 原因為 0，數值無變化"


def test_delta_nonzero_fail_negative():
    plugin = _make_plugin()
    ctx = _build_context({"before_5g": {"X": 10}, "after_5g": {"X": 5}})
    case = {"id": "T3", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_5g.X", "verify": "after_5g.X"},
        "operator": "delta_nonzero",
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is False
    assert case["_last_failure"]["reason_code"] == "delta_zero"


def test_delta_nonzero_baseline_missing():
    plugin = _make_plugin()
    ctx = _build_context({"after_5g": {"X": 5}})
    case = {"id": "T4", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_5g.X", "verify": "after_5g.X"},
        "operator": "delta_nonzero",
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is False
    assert case["_last_failure"]["reason_code"] == "delta_value_not_numeric"
    assert case["_last_failure"]["comment"] == "fail 原因為 delta 端點非數值"


def test_delta_nonzero_non_numeric():
    plugin = _make_plugin()
    ctx = _build_context({"before_5g": {"X": 10}, "after_5g": {"X": "N/A"}})
    case = {"id": "T5", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_5g.X", "verify": "after_5g.X"},
        "operator": "delta_nonzero",
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is False
    assert case["_last_failure"]["reason_code"] == "delta_value_not_numeric"
```

- [ ] **Step 7.2: Run tests to verify they fail**

Run: `pytest tests/test_wifi_llapi_delta.py -k delta_nonzero -v`
Expected: 5 failures (`AttributeError: 'Plugin' object has no attribute '_evaluate_delta_criterion'`).

- [ ] **Step 7.3: Implement `_evaluate_delta_criterion()` (delta_nonzero only first)**

In `plugins/wifi_llapi/plugin.py`, add this method to the `Plugin` class (place it near `_compare`, around line 1046):

```python
def _evaluate_delta_criterion(
    self,
    case: dict[str, Any],
    context: dict[str, Any],
    criterion: dict[str, Any],
    idx: int,
) -> bool:
    """Evaluate a delta-shaped pass_criteria entry.

    Supported operators: delta_nonzero, delta_match.
    """
    operator = str(criterion.get("operator", "")).strip().lower()
    delta_spec = criterion.get("delta")
    if not isinstance(delta_spec, dict):
        self._record_runtime_failure(
            case,
            phase="evaluate",
            comment=DELTA_VALUE_NOT_NUMERIC_COMMENT,
            category="test",
            reason_code="delta_value_not_numeric",
            metadata={"idx": idx, "issue": "missing_delta_block"},
        )
        return False

    baseline_a = self._resolve_field(context, str(delta_spec.get("baseline", "")))
    verify_a = self._resolve_field(context, str(delta_spec.get("verify", "")))
    baseline_a_num = self._to_number(baseline_a)
    verify_a_num = self._to_number(verify_a)
    if baseline_a_num is None or verify_a_num is None:
        self._record_runtime_failure(
            case,
            phase="evaluate",
            comment=DELTA_VALUE_NOT_NUMERIC_COMMENT,
            category="test",
            reason_code="delta_value_not_numeric",
            metadata={
                "idx": idx,
                "baseline_field": delta_spec.get("baseline"),
                "verify_field": delta_spec.get("verify"),
                "baseline_value": self._preview_value(baseline_a),
                "verify_value": self._preview_value(verify_a),
            },
        )
        return False

    delta_a = verify_a_num - baseline_a_num

    if operator == "delta_nonzero":
        if delta_a > 0:
            return True
        self._record_runtime_failure(
            case,
            phase="evaluate",
            comment=ZERO_DELTA_COMMENT,
            category="test",
            reason_code="delta_zero",
            metadata={"idx": idx, "delta_a": delta_a},
        )
        return False

    # delta_match handled in Task 8
    log.warning("[%s] _evaluate_delta_criterion: unsupported operator %s", self.name, operator)
    self._record_runtime_failure(
        case,
        phase="evaluate",
        comment=f"fail 原因為未知 delta operator: {operator}",
        category="test",
        reason_code="delta_unknown_operator",
        metadata={"idx": idx, "operator": operator},
    )
    return False
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `pytest tests/test_wifi_llapi_delta.py -k delta_nonzero -v`
Expected: 5 PASS.

- [ ] **Step 7.5: Commit**

```bash
git add plugins/wifi_llapi/plugin.py tests/test_wifi_llapi_delta.py
git commit -m "plugin(wifi_llapi): implement _evaluate_delta_criterion for delta_nonzero"
```

---

## Task 8: Plugin — `_evaluate_delta_criterion()` for `delta_match`

**Files:**
- Modify: `plugins/wifi_llapi/plugin.py:_evaluate_delta_criterion`
- Test: `tests/test_wifi_llapi_delta.py`

- [ ] **Step 8.1: Write the failing tests**

Append to `tests/test_wifi_llapi_delta.py`:

```python
def test_delta_match_pass_within_tolerance():
    plugin = _make_plugin()
    ctx = _build_context({
        "before_api": {"X": 0}, "after_api": {"X": 100},
        "before_drv": {"Y": 0}, "after_drv": {"Y": 109},
    })
    case = {"id": "T6", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_api.X", "verify": "after_api.X"},
        "reference_delta": {"baseline": "before_drv.Y", "verify": "after_drv.Y"},
        "operator": "delta_match",
        "tolerance_pct": 10,
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is True


def test_delta_match_pass_exact_match():
    plugin = _make_plugin()
    ctx = _build_context({
        "before_api": {"X": 0}, "after_api": {"X": 100},
        "before_drv": {"Y": 0}, "after_drv": {"Y": 100},
    })
    case = {"id": "T7", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_api.X", "verify": "after_api.X"},
        "reference_delta": {"baseline": "before_drv.Y", "verify": "after_drv.Y"},
        "operator": "delta_match",
        "tolerance_pct": 10,
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is True


def test_delta_match_tolerance_boundary():
    plugin = _make_plugin()
    ctx = _build_context({
        "before_api": {"X": 0}, "after_api": {"X": 100},
        "before_drv": {"Y": 0}, "after_drv": {"Y": 110},
    })
    case = {"id": "T8", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_api.X", "verify": "after_api.X"},
        "reference_delta": {"baseline": "before_drv.Y", "verify": "after_drv.Y"},
        "operator": "delta_match",
        "tolerance_pct": 10,
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is True


def test_delta_match_fail_exceed_tolerance():
    plugin = _make_plugin()
    ctx = _build_context({
        "before_api": {"X": 0}, "after_api": {"X": 100},
        "before_drv": {"Y": 0}, "after_drv": {"Y": 120},
    })
    case = {"id": "T9", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_api.X", "verify": "after_api.X"},
        "reference_delta": {"baseline": "before_drv.Y", "verify": "after_drv.Y"},
        "operator": "delta_match",
        "tolerance_pct": 10,
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is False
    assert case["_last_failure"]["reason_code"] == "delta_mismatch"
    assert case["_last_failure"]["comment"] == "fail 原因為 delta 不一致：api=100 drv=120 tol=10%"


def test_delta_match_fail_one_side_zero():
    plugin = _make_plugin()
    ctx = _build_context({
        "before_api": {"X": 0}, "after_api": {"X": 100},
        "before_drv": {"Y": 5}, "after_drv": {"Y": 5},  # delta_b = 0
    })
    case = {"id": "T10", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_api.X", "verify": "after_api.X"},
        "reference_delta": {"baseline": "before_drv.Y", "verify": "after_drv.Y"},
        "operator": "delta_match",
        "tolerance_pct": 10,
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is False
    assert case["_last_failure"]["reason_code"] == "delta_zero_side"
    assert case["_last_failure"]["comment"] == "fail 原因為 0，數值無變化"


def test_delta_match_fail_both_zero():
    plugin = _make_plugin()
    ctx = _build_context({
        "before_api": {"X": 5}, "after_api": {"X": 5},
        "before_drv": {"Y": 5}, "after_drv": {"Y": 5},
    })
    case = {"id": "T11", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_api.X", "verify": "after_api.X"},
        "reference_delta": {"baseline": "before_drv.Y", "verify": "after_drv.Y"},
        "operator": "delta_match",
        "tolerance_pct": 10,
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is False
    assert case["_last_failure"]["reason_code"] == "delta_zero_side"


def test_delta_match_fail_negative_either_side():
    plugin = _make_plugin()
    ctx = _build_context({
        "before_api": {"X": 10}, "after_api": {"X": 5},  # delta_a < 0
        "before_drv": {"Y": 0}, "after_drv": {"Y": 100},
    })
    case = {"id": "T12", "_attempt_index": 1}
    criterion = {
        "delta": {"baseline": "before_api.X", "verify": "after_api.X"},
        "reference_delta": {"baseline": "before_drv.Y", "verify": "after_drv.Y"},
        "operator": "delta_match",
        "tolerance_pct": 10,
    }
    assert plugin._evaluate_delta_criterion(case, ctx, criterion, 0) is False
    assert case["_last_failure"]["reason_code"] == "delta_zero_side"
```

- [ ] **Step 8.2: Run tests to verify they fail**

Run: `pytest tests/test_wifi_llapi_delta.py -k delta_match -v`
Expected: 7 failures (current implementation logs `delta_unknown_operator` for `delta_match`).

- [ ] **Step 8.3: Extend `_evaluate_delta_criterion` for `delta_match`**

Replace the body of `_evaluate_delta_criterion` after the `delta_a` calculation. The full function now reads:

```python
def _evaluate_delta_criterion(
    self,
    case: dict[str, Any],
    context: dict[str, Any],
    criterion: dict[str, Any],
    idx: int,
) -> bool:
    operator = str(criterion.get("operator", "")).strip().lower()
    delta_spec = criterion.get("delta")
    if not isinstance(delta_spec, dict):
        self._record_runtime_failure(
            case,
            phase="evaluate",
            comment=DELTA_VALUE_NOT_NUMERIC_COMMENT,
            category="test",
            reason_code="delta_value_not_numeric",
            metadata={"idx": idx, "issue": "missing_delta_block"},
        )
        return False

    baseline_a = self._resolve_field(context, str(delta_spec.get("baseline", "")))
    verify_a = self._resolve_field(context, str(delta_spec.get("verify", "")))
    baseline_a_num = self._to_number(baseline_a)
    verify_a_num = self._to_number(verify_a)
    if baseline_a_num is None or verify_a_num is None:
        self._record_runtime_failure(
            case,
            phase="evaluate",
            comment=DELTA_VALUE_NOT_NUMERIC_COMMENT,
            category="test",
            reason_code="delta_value_not_numeric",
            metadata={
                "idx": idx,
                "baseline_field": delta_spec.get("baseline"),
                "verify_field": delta_spec.get("verify"),
                "baseline_value": self._preview_value(baseline_a),
                "verify_value": self._preview_value(verify_a),
            },
        )
        return False

    delta_a = verify_a_num - baseline_a_num

    if operator == "delta_nonzero":
        if delta_a > 0:
            return True
        self._record_runtime_failure(
            case,
            phase="evaluate",
            comment=ZERO_DELTA_COMMENT,
            category="test",
            reason_code="delta_zero",
            metadata={"idx": idx, "delta_a": delta_a},
        )
        return False

    if operator == "delta_match":
        ref_spec = criterion.get("reference_delta")
        if not isinstance(ref_spec, dict):
            self._record_runtime_failure(
                case,
                phase="evaluate",
                comment=DELTA_VALUE_NOT_NUMERIC_COMMENT,
                category="test",
                reason_code="delta_value_not_numeric",
                metadata={"idx": idx, "issue": "missing_reference_delta"},
            )
            return False
        baseline_b = self._resolve_field(context, str(ref_spec.get("baseline", "")))
        verify_b = self._resolve_field(context, str(ref_spec.get("verify", "")))
        baseline_b_num = self._to_number(baseline_b)
        verify_b_num = self._to_number(verify_b)
        if baseline_b_num is None or verify_b_num is None:
            self._record_runtime_failure(
                case,
                phase="evaluate",
                comment=DELTA_VALUE_NOT_NUMERIC_COMMENT,
                category="test",
                reason_code="delta_value_not_numeric",
                metadata={
                    "idx": idx,
                    "ref_baseline_field": ref_spec.get("baseline"),
                    "ref_verify_field": ref_spec.get("verify"),
                    "ref_baseline_value": self._preview_value(baseline_b),
                    "ref_verify_value": self._preview_value(verify_b),
                },
            )
            return False
        delta_b = verify_b_num - baseline_b_num
        if delta_a <= 0 or delta_b <= 0:
            self._record_runtime_failure(
                case,
                phase="evaluate",
                comment=ZERO_DELTA_COMMENT,
                category="test",
                reason_code="delta_zero_side",
                metadata={"idx": idx, "delta_a": delta_a, "delta_b": delta_b},
            )
            return False
        tolerance_pct = float(criterion.get("tolerance_pct", 0) or 0)
        # symmetric relative diff: |a - b| / max(|a|, |b|)
        denominator = max(abs(delta_a), abs(delta_b))
        relative = abs(delta_a - delta_b) / denominator
        if relative <= tolerance_pct / 100.0:
            return True
        self._record_runtime_failure(
            case,
            phase="evaluate",
            comment=DELTA_MISMATCH_COMMENT_TEMPLATE.format(
                a=int(delta_a) if delta_a.is_integer() else delta_a,
                b=int(delta_b) if delta_b.is_integer() else delta_b,
                t=int(tolerance_pct) if float(tolerance_pct).is_integer() else tolerance_pct,
            ),
            category="test",
            reason_code="delta_mismatch",
            metadata={
                "idx": idx,
                "delta_a": delta_a,
                "delta_b": delta_b,
                "tolerance_pct": tolerance_pct,
                "relative": relative,
            },
        )
        return False

    log.warning("[%s] _evaluate_delta_criterion: unsupported operator %s", self.name, operator)
    self._record_runtime_failure(
        case,
        phase="evaluate",
        comment=f"fail 原因為未知 delta operator: {operator}",
        category="test",
        reason_code="delta_unknown_operator",
        metadata={"idx": idx, "operator": operator},
    )
    return False
```

- [ ] **Step 8.4: Run tests to verify they pass**

Run: `pytest tests/test_wifi_llapi_delta.py -v`
Expected: all delta_nonzero AND delta_match tests PASS.

- [ ] **Step 8.5: Commit**

```bash
git add plugins/wifi_llapi/plugin.py tests/test_wifi_llapi_delta.py
git commit -m "plugin(wifi_llapi): implement delta_match operator with tolerance and zero-side guards"
```

---

## Task 9: Plugin — Refactor `evaluate()` to dispatch on `delta` key

**Files:**
- Modify: `plugins/wifi_llapi/plugin.py:Plugin.evaluate` (~line 3289)
- Test: `tests/test_wifi_llapi_delta.py`

- [ ] **Step 9.1: Write the failing dispatch tests**

Append to `tests/test_wifi_llapi_delta.py`:

```python
def test_evaluate_field_path_unchanged():
    """Existing field+value criterion still produces pass_criteria_not_satisfied."""
    plugin = _make_plugin()
    case = {
        "id": "T20",
        "_attempt_index": 1,
        "pass_criteria": [
            {"field": "step1.X", "operator": "equals", "value": "expected"},
        ],
        "steps": [],
    }
    results = {"steps": {"step1": {"output": "X=actual\n", "success": True}}}
    assert plugin.evaluate(case, results) is False
    assert case["_last_failure"]["reason_code"] == "pass_criteria_not_satisfied"


def test_evaluate_delta_path_picks_new_dispatch(monkeypatch):
    """When criterion has 'delta' key, _compare must NOT be invoked."""
    plugin = _make_plugin()
    compare_called = []

    def _spy_compare(self, *a, **kw):
        compare_called.append((a, kw))
        return True

    monkeypatch.setattr(Plugin, "_compare", _spy_compare)

    case = {
        "id": "T21",
        "_attempt_index": 1,
        "pass_criteria": [
            {
                "delta": {"baseline": "before.X", "verify": "after.X"},
                "operator": "delta_nonzero",
            },
        ],
        "steps": [],
    }
    results = {"steps": {
        "before": {"output": "X=10\n", "success": True, "captured": {"X": 10}},
        "after":  {"output": "X=42\n", "success": True, "captured": {"X": 42}},
    }}
    assert plugin.evaluate(case, results) is True
    assert compare_called == [], "delta path must not call _compare"


def test_evaluate_mixed_criteria_halts_on_first_fail():
    """First failing criterion (any type) halts evaluation."""
    plugin = _make_plugin()
    case = {
        "id": "T22",
        "_attempt_index": 1,
        "pass_criteria": [
            {
                "delta": {"baseline": "before.X", "verify": "after.X"},
                "operator": "delta_nonzero",
            },
            {"field": "before.X", "operator": "equals", "value": "999"},
        ],
        "steps": [],
    }
    # delta passes (10 → 42), field criterion would fail; but evaluate must keep going
    results = {"steps": {
        "before": {"output": "X=10\n", "success": True, "captured": {"X": 10}},
        "after":  {"output": "X=42\n", "success": True, "captured": {"X": 42}},
    }}
    assert plugin.evaluate(case, results) is False
    assert case["_last_failure"]["reason_code"] == "pass_criteria_not_satisfied"
```

- [ ] **Step 9.2: Run tests to verify dispatch behaviour fails**

Run: `pytest tests/test_wifi_llapi_delta.py -k evaluate_ -v`
Expected: `test_evaluate_field_path_unchanged` PASSES (existing path); `test_evaluate_delta_path_picks_new_dispatch` and `test_evaluate_mixed_criteria_halts_on_first_fail` FAIL because evaluate hasn't been taught about `delta:` yet.

- [ ] **Step 9.3: Refactor `Plugin.evaluate()` to dispatch by `delta` key**

In `plugins/wifi_llapi/plugin.py`, replace the body of `Plugin.evaluate` (around line 3289). The new structure extracts the existing field-criterion logic into a helper and adds dispatch:

```python
def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
    """評估通過條件。"""
    context = self._build_eval_context(case, results)
    criteria = case.get("pass_criteria")
    if not isinstance(criteria, list) or not criteria:
        return False

    for idx, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            log.warning("[%s] evaluate: invalid criteria[%d]", self.name, idx)
            return False
        if "delta" in criterion:
            ok = self._evaluate_delta_criterion(case, context, criterion, idx)
        else:
            ok = self._evaluate_field_criterion(case, context, criterion, idx)
        if not ok:
            return False
    return True


def _evaluate_field_criterion(
    self,
    case: dict[str, Any],
    context: dict[str, Any],
    criterion: dict[str, Any],
    idx: int,
) -> bool:
    """Existing field+value/reference evaluation logic, behavior unchanged."""
    aggregate_output = str(context.get("_aggregate_output", ""))
    field = str(criterion.get("field", "")).strip()
    operator = str(criterion.get("operator", "contains"))
    expected = criterion.get("value")
    reference = str(criterion.get("reference", "")).strip()

    actual = self._resolve_field(context, field) if field else None
    capture_raw = self._as_mapping(context.get("_capture_raw"))
    if field and "." not in field and isinstance(actual, dict):
        raw_output = capture_raw.get(field)
        if isinstance(raw_output, str) and raw_output:
            actual = raw_output
    if isinstance(actual, dict) and "captured" in actual and "output" in actual:
        captured = actual.get("captured")
        if isinstance(captured, dict) and len(captured) == 1:
            actual = next(iter(captured.values()))
    if actual is None:
        log.warning("[%s] evaluate: field not found (%s), fallback aggregate output", self.name, field)
        actual = self._field_fallback_output(aggregate_output, field)

    if expected is None and reference:
        expected = self._resolve_field(context, reference)
        if expected is None:
            log.warning(
                "[%s] evaluate: reference not found (%s), fallback aggregate output",
                self.name,
                reference,
            )
            expected = aggregate_output

    if not self._compare(actual, operator, expected):
        self._record_runtime_failure(
            case,
            phase="evaluate",
            comment="pass_criteria not satisfied",
            category="test",
            reason_code="pass_criteria_not_satisfied",
            output=self._preview_value(actual),
            metadata={
                "field": field,
                "operator": operator,
                "expected": self._preview_value(expected),
                "actual": self._preview_value(actual),
            },
        )
        log.info(
            "[%s] evaluate failed: field=%s op=%s expected=%s actual=%s",
            self.name,
            field,
            operator,
            self._preview_value(expected),
            self._preview_value(actual),
        )
        return False
    return True
```

- [ ] **Step 9.4: Run tests to verify they pass**

Run: `pytest tests/test_wifi_llapi_delta.py -v`
Expected: ALL 18 tests now pass (5 nonzero + 7 match + 3 dispatch + 1 constant + previously written ones).

- [ ] **Step 9.5: Run full wifi_llapi test suite to confirm no regression**

Run: `pytest tests/ -k wifi -v`
Expected: existing tests still pass (this proves the field-criterion refactor preserves behavior).

- [ ] **Step 9.6: Commit**

```bash
git add plugins/wifi_llapi/plugin.py tests/test_wifi_llapi_delta.py
git commit -m "plugin(wifi_llapi): dispatch evaluate by 'delta' key, extract field-criterion helper"
```

---

## Task 10: Plugin — `_validate_phase_ordering()` pure helper

**Files:**
- Modify: `plugins/wifi_llapi/plugin.py` (add static method to `Plugin`)
- Test: `tests/test_wifi_llapi_delta.py`

- [ ] **Step 10.1: Write the failing tests**

Append to `tests/test_wifi_llapi_delta.py`:

```python
def test_phase_ok_baseline_trigger_verify():
    case = {
        "pass_criteria": [{"delta": {"baseline": "b.X", "verify": "v.X"}, "operator": "delta_nonzero"}],
        "steps": [
            {"id": "s1", "phase": "baseline"},
            {"id": "s2", "phase": "trigger"},
            {"id": "s3", "phase": "verify"},
        ],
    }
    assert Plugin._validate_phase_ordering(case) is None


def test_phase_no_delta_skip_check():
    case = {
        "pass_criteria": [{"field": "x", "operator": "equals", "value": "y"}],
        "steps": [{"id": "s1", "phase": "verify"}, {"id": "s2", "phase": "baseline"}],
    }
    assert Plugin._validate_phase_ordering(case) is None


def test_phase_missing_trigger():
    case = {
        "pass_criteria": [{"delta": {"baseline": "b.X", "verify": "v.X"}, "operator": "delta_nonzero"}],
        "steps": [{"id": "s1", "phase": "baseline"}, {"id": "s2", "phase": "verify"}],
    }
    err = Plugin._validate_phase_ordering(case)
    assert err is not None
    assert "require at least one phase=trigger" in err


def test_phase_baseline_after_trigger():
    case = {
        "pass_criteria": [{"delta": {"baseline": "b.X", "verify": "v.X"}, "operator": "delta_nonzero"}],
        "steps": [
            {"id": "s1", "phase": "baseline"},
            {"id": "s2", "phase": "trigger"},
            {"id": "s3", "phase": "baseline"},
            {"id": "s4", "phase": "verify"},
        ],
    }
    err = Plugin._validate_phase_ordering(case)
    assert err is not None
    assert "baseline step must precede trigger" in err


def test_phase_verify_before_trigger():
    case = {
        "pass_criteria": [{"delta": {"baseline": "b.X", "verify": "v.X"}, "operator": "delta_nonzero"}],
        "steps": [
            {"id": "s1", "phase": "baseline"},
            {"id": "s2", "phase": "verify"},
            {"id": "s3", "phase": "trigger"},
        ],
    }
    err = Plugin._validate_phase_ordering(case)
    assert err is not None
    assert "verify step must follow trigger" in err


def test_phase_default_unmarked_is_verify():
    """Steps without a phase field count as verify (backward compatibility)."""
    case = {
        "pass_criteria": [{"delta": {"baseline": "b.X", "verify": "v.X"}, "operator": "delta_nonzero"}],
        "steps": [
            {"id": "s1", "phase": "baseline"},
            {"id": "s2", "phase": "trigger"},
            {"id": "s3"},  # no phase = verify
        ],
    }
    assert Plugin._validate_phase_ordering(case) is None


def test_phase_invalid_value():
    case = {
        "pass_criteria": [{"delta": {"baseline": "b.X", "verify": "v.X"}, "operator": "delta_nonzero"}],
        "steps": [
            {"id": "s1", "phase": "baseline"},
            {"id": "s2", "phase": "warmup"},
            {"id": "s3", "phase": "verify"},
        ],
    }
    err = Plugin._validate_phase_ordering(case)
    assert err is not None
    assert "unknown phase: warmup" in err
```

- [ ] **Step 10.2: Run tests to verify they fail**

Run: `pytest tests/test_wifi_llapi_delta.py -k test_phase -v`
Expected: 7 failures (`AttributeError: type object 'Plugin' has no attribute '_validate_phase_ordering'`).

- [ ] **Step 10.3: Implement `_validate_phase_ordering()`**

In `plugins/wifi_llapi/plugin.py`, add this `@staticmethod` to the `Plugin` class (place near other static helpers):

```python
@staticmethod
def _validate_phase_ordering(case: dict[str, Any]) -> str | None:
    """Validate baseline → trigger → verify ordering for delta-using cases.

    Returns None when the case is well-formed (or when no delta criterion is
    present); otherwise returns a single-line error description.
    """
    criteria = case.get("pass_criteria") or []
    has_delta = any(
        isinstance(c, dict) and "delta" in c for c in criteria
    )
    if not has_delta:
        return None

    valid_phases = {"baseline", "trigger", "verify"}
    phases: list[str] = []
    for step in case.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        raw = step.get("phase")
        if raw is None:
            phases.append("verify")  # backward compatibility default
            continue
        norm = str(raw).strip().lower()
        if norm not in valid_phases:
            return f"unknown phase: {norm}"
        phases.append(norm)

    last_baseline = max((i for i, p in enumerate(phases) if p == "baseline"), default=-1)
    first_trigger = next((i for i, p in enumerate(phases) if p == "trigger"), -1)
    last_trigger = max((i for i, p in enumerate(phases) if p == "trigger"), default=-1)
    first_verify = next((i for i, p in enumerate(phases) if p == "verify"), -1)

    if first_trigger == -1:
        return "delta_* operators require at least one phase=trigger step"
    if last_baseline >= 0 and last_baseline >= first_trigger:
        return (
            f"baseline step must precede trigger; "
            f"last_baseline={last_baseline}, first_trigger={first_trigger}"
        )
    if first_verify == -1 or first_verify <= last_trigger:
        return (
            f"verify step must follow trigger; "
            f"last_trigger={last_trigger}, first_verify={first_verify}"
        )
    return None
```

- [ ] **Step 10.4: Run tests to verify they pass**

Run: `pytest tests/test_wifi_llapi_delta.py -k test_phase -v`
Expected: 7 PASS.

- [ ] **Step 10.5: Commit**

```bash
git add plugins/wifi_llapi/plugin.py tests/test_wifi_llapi_delta.py
git commit -m "plugin(wifi_llapi): add _validate_phase_ordering static helper"
```

---

## Task 11: Plugin — Hook validator into `discover_cases`, collect violators in `_phase_blocked`

**Files:**
- Modify: `plugins/wifi_llapi/plugin.py:Plugin.discover_cases` and `__init__`
- Test: `tests/test_wifi_llapi_delta.py`

- [ ] **Step 11.1: Write the failing test (use a temp dir of fixture yaml)**

Append to `tests/test_wifi_llapi_delta.py`:

```python
def test_discover_cases_marks_phase_invalid_into__phase_blocked(tmp_path, monkeypatch):
    """Cases with bad phase ordering are removed from runnable list and recorded."""
    import yaml
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()

    good_yaml = {
        "id": "good",
        "name": "good",
        "source": {"row": 1, "object": "X.", "api": "Y"},
        "topology": {"devices": {"DUT": {"role": "ap", "transport": "serial", "selector": "COM1"}}},
        "steps": [
            {"id": "s1", "phase": "baseline", "command": "echo 1", "capture": "b"},
            {"id": "s2", "phase": "trigger", "command": "echo 2"},
            {"id": "s3", "phase": "verify", "command": "echo 3", "capture": "v"},
        ],
        "pass_criteria": [
            {"delta": {"baseline": "b.X", "verify": "v.X"}, "operator": "delta_nonzero"},
        ],
    }
    bad_yaml = {
        "id": "bad",
        "name": "bad",
        "source": {"row": 2, "object": "X.", "api": "Y"},
        "topology": {"devices": {"DUT": {"role": "ap", "transport": "serial", "selector": "COM1"}}},
        "steps": [  # missing trigger
            {"id": "s1", "phase": "baseline", "command": "echo 1", "capture": "b"},
            {"id": "s2", "phase": "verify",  "command": "echo 2", "capture": "v"},
        ],
        "pass_criteria": [
            {"delta": {"baseline": "b.X", "verify": "v.X"}, "operator": "delta_nonzero"},
        ],
    }
    (cases_dir / "good.yaml").write_text(yaml.safe_dump(good_yaml))
    (cases_dir / "bad.yaml").write_text(yaml.safe_dump(bad_yaml))

    plugin = Plugin()
    monkeypatch.setattr(type(plugin), "cases_dir", property(lambda self: cases_dir))

    runnable = plugin.discover_cases()
    runnable_ids = [c.get("id") for c in runnable]
    assert "good" in runnable_ids
    assert "bad" not in runnable_ids

    blocked = getattr(plugin, "_phase_blocked", [])
    assert any(getattr(b, "id_before", "") == "bad" for b in blocked)
    bad_entry = next(b for b in blocked if getattr(b, "id_before", "") == "bad")
    assert getattr(bad_entry, "status", "") == "blocked"
    assert "invalid_delta_schema" in (getattr(bad_entry, "blocked_reason", "") or "")
```

- [ ] **Step 11.2: Run test to verify it fails**

Run: `pytest tests/test_wifi_llapi_delta.py::test_discover_cases_marks_phase_invalid_into__phase_blocked -v`
Expected: FAIL — bad case still in runnable list, `_phase_blocked` doesn't exist.

- [ ] **Step 11.3: Modify `discover_cases` and `__init__`**

In `plugins/wifi_llapi/plugin.py`:

(a) Add an import at the top of the file (alongside other testpilot imports):

```python
from testpilot.reporting.wifi_llapi_align import AlignResult
```

(b) In `Plugin.__init__` (or, if no `__init__` is defined, add one), initialize the attribute. Locate the `class Plugin(PluginBase):` line and add at the very top of its body:

```python
class Plugin(PluginBase):
    def __init__(self) -> None:
        super().__init__()
        self._phase_blocked: list[Any] = []
```

(c) Replace `discover_cases`:

```python
def discover_cases(self) -> list[dict[str, Any]]:
    raw = load_cases_dir(self.cases_dir, validator=validate_wifi_llapi_case)
    self._phase_blocked = []
    runnable: list[dict[str, Any]] = []
    cases_root = Path(self.cases_dir)
    for case in raw:
        err = self._validate_phase_ordering(case)
        if err is None:
            runnable.append(case)
            continue
        case_id = str(case.get("id", "")).strip() or "<unknown>"
        # Best-effort source row + filename for marker compat.
        source = case.get("source") or {}
        source_row = int(source.get("row") or 0) if isinstance(source, dict) else 0
        filename = str(case.get("_source_file", "")) or f"{case_id}.yaml"
        self._phase_blocked.append(
            AlignResult(
                case_file=cases_root / filename,
                status="blocked",
                source_row_before=source_row,
                source_row_after=None,
                source_object=str((source or {}).get("object", "")),
                source_api=str((source or {}).get("api", "")),
                filename_before=filename,
                filename_after=None,
                id_before=case_id,
                id_after=None,
                blocked_reason=f"invalid_delta_schema: {err}",
            )
        )
        log.warning(
            "[%s] phase ordering invalid for case %s: %s",
            self.name,
            case_id,
            err,
        )
    return runnable
```

(`load_cases_dir` already attaches `_source_file` for case yaml; `cases_root / filename` reconstructs a path that satisfies `AlignResult.case_file`.)

- [ ] **Step 11.4: Run test to verify it passes**

Run: `pytest tests/test_wifi_llapi_delta.py::test_discover_cases_marks_phase_invalid_into__phase_blocked -v`
Expected: PASS.

- [ ] **Step 11.5: Run full wifi_llapi suite**

Run: `pytest tests/ -k wifi -v`
Expected: existing tests still pass.

- [ ] **Step 11.6: Commit**

```bash
git add plugins/wifi_llapi/plugin.py tests/test_wifi_llapi_delta.py
git commit -m "plugin(wifi_llapi): block phase-invalid cases at discover, collect into _phase_blocked"
```

---

## Task 12: Orchestrator — merge `plugin._phase_blocked` into `prep.blocked_results`

**Files:**
- Modify: `src/testpilot/core/orchestrator.py:_prepare_wifi_llapi_alignment` (~line 509-536)
- Test: `tests/test_wifi_llapi_delta.py`

- [ ] **Step 12.1: Write the failing test**

Append to `tests/test_wifi_llapi_delta.py`:

```python
def test_orchestrator_merges_phase_blocked_into_prep(tmp_path, monkeypatch):
    """When plugin._phase_blocked is non-empty, _prepare_wifi_llapi_alignment
    merges those entries into prep.blocked_results so they reach
    fill_blocked_markers."""
    from pathlib import Path as _Path
    from unittest.mock import MagicMock
    from testpilot.core.orchestrator import Orchestrator, WifiLlapiAlignmentPrep
    from testpilot.reporting.wifi_llapi_align import AlignResult

    fake_blocked = AlignResult(
        case_file=_Path("/tmp/bad.yaml"),
        status="blocked",
        source_row_before=99,
        source_row_after=None,
        source_object="WiFi.Foo.",
        source_api="Bar",
        filename_before="bad.yaml",
        filename_after=None,
        id_before="bad",
        id_after=None,
        blocked_reason="invalid_delta_schema: missing trigger",
    )

    fake_plugin = MagicMock()
    fake_plugin._phase_blocked = [fake_blocked]
    fake_plugin.cases_dir = tmp_path

    # _load_wifi_llapi_case_pairs returns []; build_template_index returns a
    # minimal index; align_case is patched to a no-op.
    monkeypatch.setattr(
        Orchestrator, "_load_wifi_llapi_case_pairs",
        lambda self, *, plugin, case_ids: [],
    )

    import testpilot.core.orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "build_template_index", lambda p: MagicMock())
    monkeypatch.setattr(orch_mod, "align_case", lambda case, idx, path: None)
    monkeypatch.setattr(orch_mod, "_resolve_collisions", lambda r: None)
    monkeypatch.setattr(orch_mod, "apply_alignment_mutations", lambda r: None)

    orchestrator = Orchestrator.__new__(Orchestrator)  # bypass __init__
    prep = Orchestrator._prepare_wifi_llapi_alignment(
        orchestrator,
        plugin=fake_plugin,
        case_ids=None,
        template_path=tmp_path / "tmpl.xlsx",
    )
    assert isinstance(prep, WifiLlapiAlignmentPrep)
    assert any(b.id_before == "bad" for b in prep.blocked_results)
    assert any(
        "invalid_delta_schema" in (b.blocked_reason or "")
        for b in prep.blocked_results
    )
```

- [ ] **Step 12.2: Run test to verify it fails**

Run: `pytest tests/test_wifi_llapi_delta.py::test_orchestrator_merges_phase_blocked_into_prep -v`
Expected: FAIL — `phase_blocked` is not merged.

- [ ] **Step 12.3: Modify `_prepare_wifi_llapi_alignment`**

In `src/testpilot/core/orchestrator.py`, locate `_prepare_wifi_llapi_alignment` and append the merge step before `return WifiLlapiAlignmentPrep(...)`:

```python
def _prepare_wifi_llapi_alignment(
    self,
    *,
    plugin: Any,
    case_ids: list[str] | None,
    template_path: Path,
) -> WifiLlapiAlignmentPrep:
    case_pairs = self._load_wifi_llapi_case_pairs(plugin=plugin, case_ids=case_ids)
    index = build_template_index(template_path)
    align_results = [align_case(case, index, path) for path, case in case_pairs]
    _resolve_collisions(align_results)
    apply_alignment_mutations(align_results)
    runnable_results = [
        result
        for result in align_results
        if result.status in {"already_aligned", "auto_aligned"}
    ]
    blocked_results = [result for result in align_results if result.status == "blocked"]
    skipped_results = [result for result in align_results if result.status == "skipped"]

    # Merge phase-ordering BLOCKED entries detected by plugin.discover_cases
    phase_blocked = list(getattr(plugin, "_phase_blocked", []) or [])
    if phase_blocked:
        blocked_results = blocked_results + phase_blocked

    return WifiLlapiAlignmentPrep(
        runnable_cases=[
            load_case(result.case_file, validator=validate_wifi_llapi_case)
            for result in runnable_results
        ],
        blocked_results=blocked_results,
        skipped_results=skipped_results,
        alignment_summary=self._build_wifi_llapi_alignment_summary(
            align_results + phase_blocked
        ),
    )
```

(Note: `phase_blocked` also gets folded into `_build_wifi_llapi_alignment_summary` so the summary "blocked" count is accurate.)

- [ ] **Step 12.4: Run test to verify it passes**

Run: `pytest tests/test_wifi_llapi_delta.py::test_orchestrator_merges_phase_blocked_into_prep -v`
Expected: PASS.

- [ ] **Step 12.5: Run full orchestrator regression**

Run: `pytest tests/ -k orchestrator -v`
Expected: PASS.

- [ ] **Step 12.6: Commit**

```bash
git add src/testpilot/core/orchestrator.py tests/test_wifi_llapi_delta.py
git commit -m "orchestrator(wifi_llapi): merge plugin._phase_blocked into alignment blocked_results"
```

---

## Task 13: Integration test — yaml fixtures + end-to-end run with reporter

**Files:**
- Create: `tests/fixtures/wifi_llapi_delta/delta_nonzero_pass.yaml`
- Create: `tests/fixtures/wifi_llapi_delta/delta_nonzero_fail.yaml`
- Create: `tests/fixtures/wifi_llapi_delta/delta_match_pass.yaml`
- Create: `tests/test_wifi_llapi_delta_integration.py`

- [ ] **Step 13.1: Create fixtures**

Create `tests/fixtures/wifi_llapi_delta/delta_nonzero_pass.yaml`:

```yaml
id: fixture-delta-nonzero-pass
name: delta_nonzero PASS fixture
source: {row: 9001, object: WiFi.Test.{i}., api: TestCounter}
topology:
  devices:
    DUT: {role: ap, transport: stub, selector: dummy}
steps:
- {id: s1, phase: baseline, command: "echo X=10", capture: before}
- {id: s2, phase: trigger,  command: "echo trigger"}
- {id: s3, phase: verify,   command: "echo X=42", capture: after}
pass_criteria:
- delta: {baseline: before.X, verify: after.X}
  operator: delta_nonzero
```

Create `tests/fixtures/wifi_llapi_delta/delta_nonzero_fail.yaml`:

```yaml
id: fixture-delta-nonzero-fail
name: delta_nonzero FAIL fixture
source: {row: 9002, object: WiFi.Test.{i}., api: TestCounter}
topology:
  devices:
    DUT: {role: ap, transport: stub, selector: dummy}
steps:
- {id: s1, phase: baseline, command: "echo X=10", capture: before}
- {id: s2, phase: trigger,  command: "echo trigger"}
- {id: s3, phase: verify,   command: "echo X=10", capture: after}
pass_criteria:
- delta: {baseline: before.X, verify: after.X}
  operator: delta_nonzero
```

Create `tests/fixtures/wifi_llapi_delta/delta_match_pass.yaml`:

```yaml
id: fixture-delta-match-pass
name: delta_match PASS fixture
source: {row: 9003, object: WiFi.Test.{i}., api: TestCounter}
topology:
  devices:
    DUT: {role: ap, transport: stub, selector: dummy}
steps:
- {id: s1, phase: baseline, command: "echo X=0",  capture: api_before}
- {id: s2, phase: baseline, command: "echo Y=0",  capture: drv_before}
- {id: s3, phase: trigger,  command: "echo trigger"}
- {id: s4, phase: verify,   command: "echo X=100", capture: api_after}
- {id: s5, phase: verify,   command: "echo Y=109", capture: drv_after}
pass_criteria:
- delta: {baseline: api_before.X, verify: api_after.X}
  operator: delta_nonzero
- delta: {baseline: api_before.X, verify: api_after.X}
  reference_delta: {baseline: drv_before.Y, verify: drv_after.Y}
  operator: delta_match
  tolerance_pct: 10
```

- [ ] **Step 13.2: Write the failing integration test**

Create `tests/test_wifi_llapi_delta_integration.py`:

```python
"""End-to-end integration test for wifi_llapi delta runtime (Wave 1)."""

from __future__ import annotations

from pathlib import Path

import pytest


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "wifi_llapi_delta"


def _load_case(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text())


def _stub_results_for(case: dict) -> dict:
    """Produce a results dict that mirrors what the runner would emit:

    For each step, parse its `echo K=V` command into a captured dict.
    """
    out: dict[str, dict] = {"steps": {}}
    for step in case.get("steps", []):
        cmd = str(step.get("command", "")).strip()
        captured: dict[str, object] = {}
        if cmd.startswith("echo "):
            payload = cmd[len("echo "):].strip().strip("\"")
            for token in payload.split():
                if "=" in token:
                    k, v = token.split("=", 1)
                    try:
                        captured[k] = int(v)
                    except ValueError:
                        captured[k] = v
        sid = str(step.get("id", ""))
        out["steps"][sid] = {
            "success": True,
            "output": payload if cmd.startswith("echo ") else "",
            "captured": captured,
            "returncode": 0,
        }
    return out


def test_delta_nonzero_pass_fixture():
    from plugins.wifi_llapi.plugin import Plugin
    case = _load_case(FIXTURE_DIR / "delta_nonzero_pass.yaml")
    plugin = Plugin()
    results = _stub_results_for(case)
    assert plugin.evaluate(case, results) is True


def test_delta_nonzero_fail_fixture():
    from plugins.wifi_llapi.plugin import Plugin
    case = _load_case(FIXTURE_DIR / "delta_nonzero_fail.yaml")
    plugin = Plugin()
    results = _stub_results_for(case)
    assert plugin.evaluate(case, results) is False
    assert case["_last_failure"]["reason_code"] == "delta_zero"
    assert case["_last_failure"]["comment"] == "fail 原因為 0，數值無變化"


def test_delta_match_pass_fixture():
    from plugins.wifi_llapi.plugin import Plugin
    case = _load_case(FIXTURE_DIR / "delta_match_pass.yaml")
    plugin = Plugin()
    results = _stub_results_for(case)
    assert plugin.evaluate(case, results) is True


def test_delta_failure_propagates_to_xlsx_M_column(tmp_path):
    """End-to-end: fail fixture's comment is written to M column via fill_case_results."""
    from openpyxl import Workbook, load_workbook
    from plugins.wifi_llapi.plugin import Plugin
    from testpilot.reporting.wifi_llapi_excel import (
        DEFAULT_SHEET_NAME,
        WifiLlapiCaseResult,
        fill_case_results,
        _normalize_template_headers,
    )
    case = _load_case(FIXTURE_DIR / "delta_nonzero_fail.yaml")
    plugin = Plugin()
    results = _stub_results_for(case)
    assert plugin.evaluate(case, results) is False

    # Build a single-row report and pipe the comment through.
    report = tmp_path / "report.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = DEFAULT_SHEET_NAME
    _normalize_template_headers(ws)
    ws.cell(row=4, column=1).value = "anchor"
    wb.save(report)

    item = WifiLlapiCaseResult(
        case_id=case["id"],
        source_row=4,
        executed_test_command="",
        command_output="",
        result_5g="FAIL",
        result_6g="N/A",
        result_24g="N/A",
        comment=case["_last_failure"]["comment"],
    )
    fill_case_results(report, [item])

    wb2 = load_workbook(report)
    ws2 = wb2[DEFAULT_SHEET_NAME]
    assert ws2.cell(row=4, column=13).value == "fail 原因為 0，數值無變化"
```

- [ ] **Step 13.3: Run integration tests**

Run: `pytest tests/test_wifi_llapi_delta_integration.py -v`
Expected: 4 PASS.

- [ ] **Step 13.4: Commit**

```bash
git add tests/fixtures/wifi_llapi_delta/ tests/test_wifi_llapi_delta_integration.py
git commit -m "test(wifi_llapi): end-to-end delta fixtures + xlsx M column propagation"
```

---

## Task 14: Documentation — `plugins/wifi_llapi/CASE_YAML_SYNTAX.md`

**Files:**
- Create: `plugins/wifi_llapi/CASE_YAML_SYNTAX.md`

This is a documentation deliverable, not test-driven. Write the file in one shot, then verify it renders by inspection.

- [ ] **Step 14.1: Inventory top-level fields actually in use**

Run: `grep -h "^[a-z_]*:" plugins/wifi_llapi/cases/D*.yaml | sort -u`

Capture the full set; expect: `id, name, version, source, platform, hlapi_command, llapi_support, implemented_by, bands, topology, test_environment, setup_steps, sta_env_setup, test_procedure, steps, pass_criteria, verification_command, sta_baseline, dut_bounce, ping`

- [ ] **Step 14.2: Inventory step-level fields**

Run: `grep -E "^\s*-\s*id:|^\s*[a-z_]+:" plugins/wifi_llapi/cases/D037_retransmissions.yaml | head -30`

Confirm step keys: `id, action, target, command, capture, depends_on, expected, description`. Add `phase` (newly introduced).

- [ ] **Step 14.3: Write `CASE_YAML_SYNTAX.md`**

Create `plugins/wifi_llapi/CASE_YAML_SYNTAX.md` with this content:

````markdown
# wifi_llapi Test Case YAML Syntax Reference

> Long-lived reference. Updated in lockstep with `plugin.py` schema changes.
> When this file goes out of date, fix it before adding new schema features.

## Case-level fields

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Unique case identifier (kebab or snake) |
| `name` | yes | Human-readable display name |
| `version` | no | Spec version (e.g. `'1.1'`) |
| `source` | yes | `{row: int, object: str, api: str}` — workbook row mapping |
| `platform` | no | `{prplos: str, bdk: str}` |
| `hlapi_command` | no | The HLAPI command this case verifies |
| `llapi_support` | no | One of `Support / Not Supported / Skip / Blocked` |
| `implemented_by` | no | Vendor module name (e.g. `pWHM`) |
| `bands` | no | List of bands targeted (`5g / 6g / 2.4g`) |
| `topology` | yes | `{devices: {NAME: {role, transport, selector, config?}}, links?: [...]}` |
| `test_environment` | no | Free-form preamble |
| `setup_steps` | no | Free-form prose |
| `sta_env_setup` | no | Free-form prose for STA env setup |
| `test_procedure` | no | Free-form prose for human readers |
| `steps` | yes | Ordered list of step dicts (see below) |
| `pass_criteria` | yes | Ordered list of criterion dicts (see below) |
| `verification_command` | no | Reference list of commands a human can re-run |

## Step-level fields

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Unique within the case (referenced by `depends_on`) |
| `target` | no | Device name from `topology.devices` (default DUT) |
| `action` | no | One of `read / exec / skip` (default `exec`) |
| `command` | yes (unless `action: skip`) | Shell command run on `target` |
| `capture` | no | Captured output is also exposed as `<capture>.<key>` in eval context |
| `depends_on` | no | Step `id` that must succeed first |
| `expected` | no | Free-form description, no runtime semantics |
| `description` | no | Free-form display text |
| `phase` | no | One of `baseline / trigger / verify`. Default: `verify`. **Required when the case uses any `delta_*` operator** (validated at load time). |

### Phase ordering rule

When any `pass_criteria` entry contains a `delta:` key, the runtime enforces:

1. At least one step with `phase: trigger` MUST exist.
2. All `phase: baseline` steps MUST appear before all `phase: trigger` steps.
3. All `phase: verify` steps MUST appear after all `phase: trigger` steps.

Cases that violate these rules are marked BLOCKED with `blocked_reason` beginning with `invalid_delta_schema:` and are excluded from the runnable list.

## pass_criteria shapes

### Shape 1 — `field + value`

```yaml
- field: capture_name.Key
  operator: equals     # or != / contains / not_contains / regex / not_empty / empty / >= / <= / > / < / skip
  value: '0'
  description: optional human note
```

### Shape 2 — `field + reference`

```yaml
- field: api_capture.Key
  operator: equals
  reference: driver_capture.OtherKey
  description: 'API value must match driver readback'
```

### Shape 3 — `delta` (counter validation, requires `phase` labels on steps)

```yaml
# delta_nonzero — counter must grow under trigger
- delta: {baseline: before.X, verify: after.X}
  operator: delta_nonzero
  description: 'optional'

# delta_match — API delta must match driver delta within tolerance
- delta: {baseline: api_before.X, verify: api_after.X}
  reference_delta: {baseline: drv_before.Y, verify: drv_after.Y}
  operator: delta_match
  tolerance_pct: 10
```

## Operators

| Operator | Shape | Pass condition |
|---|---|---|
| `equals` / `==` / `eq` | field+value/ref | `actual == expected` (numeric & MAC-aware) |
| `!=` / `not_equals` / `ne` | field+value/ref | inverse of `equals` |
| `contains` | field+value/ref | substring match (whitespace-tolerant) |
| `not_contains` | field+value/ref | inverse of `contains` |
| `regex` / `matches` | field+value/ref | `re.search(expected, actual)` |
| `not_empty` | field | `bool(actual.strip())` |
| `empty` | field | inverse of `not_empty` |
| `>` / `>=` / `<` / `<=` | field+value/ref | numeric (or string fallback) comparison |
| `skip` | field | always passes (used by Blocked cases) |
| `delta_nonzero` | delta | `verify - baseline > 0` (strict) |
| `delta_match` | delta + reference_delta | both deltas > 0 AND `\|a-b\|/max(\|a\|,\|b\|) <= tolerance_pct/100` |

## reason_codes (delta path)

| reason_code | When |
|---|---|
| `invalid_delta_schema` | Phase ordering invalid (BLOCKED path) |
| `delta_value_not_numeric` | Either endpoint cannot resolve to a number |
| `delta_zero` | `delta_nonzero` saw `verify - baseline <= 0` |
| `delta_zero_side` | `delta_match` saw at least one delta `<= 0` |
| `delta_mismatch` | `delta_match` saw both grow but exceeded tolerance |
| `pass_criteria_not_satisfied` | (Existing) any field-shape criterion failed; refinement tracked in #39 |

## Failure comments

Plugin-level constants (case yaml MUST NOT override):

- `delta_zero` / `delta_zero_side` → `"fail 原因為 0，數值無變化"`
- `delta_mismatch` → `"fail 原因為 delta 不一致：api={a} drv={b} tol={t}%"`
- `delta_value_not_numeric` → `"fail 原因為 delta 端點非數值"`

These appear in the xlsx report's column M (`Comment`).

## llapi_support semantics

| Value | Behavior |
|---|---|
| `Support` | Standard execution; pass_criteria evaluated normally |
| `Not Supported` | Step `action: skip` recommended; pass_criteria typically uses `operator: skip` |
| `Skip` | Same — case is skipped from execution |
| `Blocked` | Case requires manual gating; `step.action: skip` + `pass_criteria.operator: skip` |

## Worked Examples

### Example A — Standard case (existing shape, no delta)

```yaml
id: example-standard
name: Example
source: {row: 100, object: WiFi.Foo., api: Bar}
topology:
  devices: {DUT: {role: ap, transport: serial, selector: COM1}}
steps:
- id: read
  command: ubus-cli "WiFi.Foo.Bar?"
  capture: result
pass_criteria:
- field: result.Bar
  operator: equals
  value: 'expected'
```

### Example B — Counter-delta case (new shape)

```yaml
id: example-delta
name: Example delta counter
source: {row: 200, object: WiFi.Foo., api: BarCounter}
topology:
  devices: {DUT: {role: ap, transport: serial, selector: COM1}}
steps:
- id: api_before
  phase: baseline
  command: ubus-cli "WiFi.Foo.BarCounter?"
  capture: api_before
- id: drv_before
  phase: baseline
  command: wl -i wl0 read_counter | grep BarCounter
  capture: drv_before
- id: trigger
  phase: trigger
  command: <workload that drives the counter>
- id: api_after
  phase: verify
  command: ubus-cli "WiFi.Foo.BarCounter?"
  capture: api_after
- id: drv_after
  phase: verify
  command: wl -i wl0 read_counter | grep BarCounter
  capture: drv_after
pass_criteria:
- delta: {baseline: api_before.BarCounter, verify: api_after.BarCounter}
  operator: delta_nonzero
- delta: {baseline: api_before.BarCounter, verify: api_after.BarCounter}
  reference_delta: {baseline: drv_before.BarCounter, verify: drv_after.BarCounter}
  operator: delta_match
  tolerance_pct: 10
```

### Example C — Blocked case (live probe known broken)

```yaml
id: example-blocked
name: Example blocked
source: {row: 300, object: WiFi.Foo., api: Baz}
llapi_support: Blocked
topology:
  devices: {DUT: {role: ap, transport: serial, selector: COM1}}
steps:
- id: skip_step
  action: skip
  command: "echo blocked"
  description: "live probe shows 0; needs workload to confirm wiring"
pass_criteria:
- field: skip
  operator: skip
  value: "needs workload to confirm wiring"
```
````

- [ ] **Step 14.4: Verify the file renders sensibly**

Run: `head -100 plugins/wifi_llapi/CASE_YAML_SYNTAX.md`
Expected: clean markdown table, no template artifacts.

- [ ] **Step 14.5: Commit**

```bash
git add plugins/wifi_llapi/CASE_YAML_SYNTAX.md
git commit -m "docs(wifi_llapi): add CASE_YAML_SYNTAX.md long-lived schema reference"
```

---

## Task 15: Migrate sample case D037

**Files:**
- Modify: `plugins/wifi_llapi/cases/D037_retransmissions.yaml`

This is a yaml refactor. The case must:
1. Add `phase` labels to all steps (split the existing `step1/2/3` into baseline/trigger/verify trios for the 5G band).
2. Add a trigger step that is plausible (iperf3 UDP from STA to DUT).
3. Replace `equals '0'` pass_criteria with `delta_nonzero` + `delta_match`.
4. Delete the description line that says `'Workbook v4.0.3 marks this API as Fail: ...'`.

- [ ] **Step 15.1: Read the current case to confirm what needs to change**

Run: `cat plugins/wifi_llapi/cases/D037_retransmissions.yaml | head -160`

Confirm: 3 steps, pass_criteria uses `equals '0'` with the workbook-fail description.

- [ ] **Step 15.2: Replace `steps:` and `pass_criteria:` blocks**

Edit `plugins/wifi_llapi/cases/D037_retransmissions.yaml`. Keep the top-level metadata (`id, name, version, source, platform, hlapi_command, llapi_support, implemented_by, bands, topology, test_environment, setup_steps, sta_env_setup, test_procedure`). Replace `steps:` and `pass_criteria:` (and `verification_command:` if present) with:

```yaml
steps:
- id: step1_resolve_assoc
  phase: baseline
  action: exec
  target: DUT
  command: ubus-cli "WiFi.AccessPoint.1.AssociatedDevice.1.MACAddress?"
  capture: assoc_entry
  description: Resolve the live 5G STA MAC for AP1 AssociatedDevice.1.
- id: step2_api_baseline
  phase: baseline
  action: exec
  target: DUT
  command: ubus-cli "WiFi.AccessPoint.1.AssociatedDevice.1.Retransmissions?"
  capture: api_before_5g
  description: API-side baseline reading of Retransmissions.
- id: step3_drv_baseline
  phase: baseline
  action: exec
  target: DUT
  command: 'STA_MAC=$(ubus-cli "WiFi.AccessPoint.1.AssociatedDevice.1.MACAddress?"
    | sed -n ''s/.*MACAddress="\([^"]*\)".*/\1/p''); [ -n "$STA_MAC" ] && wl -i wl0
    sta_info $STA_MAC | sed -n ''s/.*tx pkts retries: *\([0-9][0-9]*\).*/DriverRetransmissions=\1/p'''
  capture: drv_before_5g
  description: Driver-side baseline of tx pkts retries for the same STA.
- id: step4_trigger
  phase: trigger
  action: exec
  target: STA
  command: iperf3 -u -c 192.168.88.1 -b 100M -l 1400 -t 5 --pacing-timer 1
  description: Burst UDP downlink to drive AP-side retransmissions.
- id: step5_api_verify
  phase: verify
  action: exec
  target: DUT
  command: ubus-cli "WiFi.AccessPoint.1.AssociatedDevice.1.Retransmissions?"
  capture: api_after_5g
  description: API-side verify reading of Retransmissions after trigger.
- id: step6_drv_verify
  phase: verify
  action: exec
  target: DUT
  command: 'STA_MAC=$(ubus-cli "WiFi.AccessPoint.1.AssociatedDevice.1.MACAddress?"
    | sed -n ''s/.*MACAddress="\([^"]*\)".*/\1/p''); [ -n "$STA_MAC" ] && wl -i wl0
    sta_info $STA_MAC | sed -n ''s/.*tx pkts retries: *\([0-9][0-9]*\).*/DriverRetransmissions=\1/p'''
  capture: drv_after_5g
  description: Driver-side verify of tx pkts retries after trigger.
pass_criteria:
- field: assoc_entry.MACAddress
  operator: regex
  value: ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$
  description: AP1 AssociatedDevice.1 must first resolve to the live 5G STA MAC.
- delta: {baseline: api_before_5g.Retransmissions, verify: api_after_5g.Retransmissions}
  operator: delta_nonzero
  description: 5g API Retransmissions must grow after the trigger workload.
- delta: {baseline: api_before_5g.Retransmissions, verify: api_after_5g.Retransmissions}
  reference_delta: {baseline: drv_before_5g.DriverRetransmissions, verify: drv_after_5g.DriverRetransmissions}
  operator: delta_match
  tolerance_pct: 10
  description: 5g API delta must agree with driver delta within ±10%.
verification_command:
- ubus-cli "WiFi.AccessPoint.1.AssociatedDevice.1.Retransmissions?"
- iperf3 -u -c 192.168.88.1 -b 100M -l 1400 -t 5 --pacing-timer 1
- 'STA_MAC=$(ubus-cli "WiFi.AccessPoint.1.AssociatedDevice.1.MACAddress?" | sed -n ''s/.*MACAddress="\([^"]*\)".*/\1/p''); [ -n "$STA_MAC" ] && wl -i wl0 sta_info $STA_MAC'
```

(Note: the trigger uses the STA's iperf3 hitting the DUT bridge IP `192.168.88.1`, matching `sta_env_setup` from the existing case.)

- [ ] **Step 15.3: Verify the case parses and schema is valid**

Run:
```bash
python -c "
from plugins.wifi_llapi.plugin import Plugin
import yaml, pathlib
case = yaml.safe_load(pathlib.Path('plugins/wifi_llapi/cases/D037_retransmissions.yaml').read_text())
print('phase ordering:', Plugin._validate_phase_ordering(case))
"
```
Expected output: `phase ordering: None`

- [ ] **Step 15.4: Run wifi_llapi tests to confirm nothing broke**

Run: `pytest tests/ -k wifi -v`
Expected: green.

- [ ] **Step 15.5: Commit**

```bash
git add plugins/wifi_llapi/cases/D037_retransmissions.yaml
git commit -m "case(wifi_llapi): migrate D037 Retransmissions to delta range (sample for #38/#13)"
```

---

## Task 16: Migrate sample case D313

**Files:**
- Modify: `plugins/wifi_llapi/cases/D313_getssidstats_retranscount.yaml`

D313 already has 3 steps (one per band reading getSSIDStats). Each band needs baseline → trigger → verify.

- [ ] **Step 16.1: Read the current case**

Run: `cat plugins/wifi_llapi/cases/D313_getssidstats_retranscount.yaml`

Confirm: 3 read-stats steps + `equals 0` pass_criteria for each band.

- [ ] **Step 16.2: Replace `steps:` and `pass_criteria:` blocks**

Edit `plugins/wifi_llapi/cases/D313_getssidstats_retranscount.yaml`. Keep top-level metadata. Replace steps and pass_criteria with:

```yaml
steps:
- id: step_5g_baseline
  phase: baseline
  action: exec
  target: DUT
  command: ubus-cli "WiFi.SSID.4.getSSIDStats()"
  capture: stats_5g_before
- id: step_6g_baseline
  phase: baseline
  action: exec
  target: DUT
  command: ubus-cli "WiFi.SSID.6.getSSIDStats()"
  capture: stats_6g_before
- id: step_24g_baseline
  phase: baseline
  action: exec
  target: DUT
  command: ubus-cli "WiFi.SSID.8.getSSIDStats()"
  capture: stats_24g_before
- id: step_trigger
  phase: trigger
  action: exec
  target: STA
  command: iperf3 -u -c 192.168.88.1 -b 100M -l 1400 -t 5 --pacing-timer 1
  description: Drive retransmissions across all bands by sustained UDP burst.
- id: step_5g_verify
  phase: verify
  action: exec
  target: DUT
  command: ubus-cli "WiFi.SSID.4.getSSIDStats()"
  capture: stats_5g_after
- id: step_6g_verify
  phase: verify
  action: exec
  target: DUT
  command: ubus-cli "WiFi.SSID.6.getSSIDStats()"
  capture: stats_6g_after
- id: step_24g_verify
  phase: verify
  action: exec
  target: DUT
  command: ubus-cli "WiFi.SSID.8.getSSIDStats()"
  capture: stats_24g_after
pass_criteria:
- delta: {baseline: stats_5g_before.RetransCount, verify: stats_5g_after.RetransCount}
  operator: delta_nonzero
  description: 5g SSID.4 RetransCount must grow under trigger.
- delta: {baseline: stats_6g_before.RetransCount, verify: stats_6g_after.RetransCount}
  operator: delta_nonzero
  description: 6g SSID.6 RetransCount must grow under trigger.
- delta: {baseline: stats_24g_before.RetransCount, verify: stats_24g_after.RetransCount}
  operator: delta_nonzero
  description: 2.4g SSID.8 RetransCount must grow under trigger.
```

- [ ] **Step 16.3: Validate the case**

Run:
```bash
python -c "
from plugins.wifi_llapi.plugin import Plugin
import yaml, pathlib
case = yaml.safe_load(pathlib.Path('plugins/wifi_llapi/cases/D313_getssidstats_retranscount.yaml').read_text())
print('phase ordering:', Plugin._validate_phase_ordering(case))
"
```
Expected output: `phase ordering: None`

- [ ] **Step 16.4: Run full wifi_llapi test suite**

Run: `pytest tests/ -k wifi -v`
Expected: green.

- [ ] **Step 16.5: Commit**

```bash
git add plugins/wifi_llapi/cases/D313_getssidstats_retranscount.yaml
git commit -m "case(wifi_llapi): migrate D313 RetransCount to delta range (sample for #38/#13)"
```

---

## Task 17: Final regression + Wave 1 closeout

**Files:** none (smoke run + audit)

- [ ] **Step 17.1: Full pytest suite**

Run: `pytest tests/ -v 2>&1 | tail -40`
Expected: 0 failures. Note any new test count.

- [ ] **Step 17.2: Confirm dispatch zero-regression on `_compare`**

Run: `pytest tests/ -k "compare" -v`
Expected: existing comparison tests untouched.

- [ ] **Step 17.3: Audit — no remaining `equals '0'` workbook-fail prose in migrated cases**

Run: `grep -nE "Workbook v4.0.3 marks this API as Fail" plugins/wifi_llapi/cases/D037_retransmissions.yaml plugins/wifi_llapi/cases/D313_getssidstats_retranscount.yaml`
Expected: no matches.

- [ ] **Step 17.4: OpenSpec change validation**

Run: `openspec validate wifi-llapi-counter-delta-validation --strict`
Expected: `Change 'wifi-llapi-counter-delta-validation' is valid`.

- [ ] **Step 17.5: Mark Wave 1 PR-ready**

Inspect the commit log:

Run: `git log --oneline main..HEAD`
Expected: ~16-17 commits, each one focused, all green.

- [ ] **Step 17.6: Push branch and open PR**

(Manual — only when authorized by user.)

```bash
# Run only after user explicitly says "push" / "open PR".
git push -u origin <branch-name>
gh pr create --title "feat(wifi_llapi): counter delta validation Wave 1 (#38, #13)" --body "$(cat <<'EOF'
Wave 1 (foundation) for the wifi_llapi counter delta validation initiative.

## Scope

- Runtime: `phase: baseline | trigger | verify` step label, `delta_nonzero` and `delta_match` operators, phase ordering schema validator (BLOCKED path).
- Reporter: new column M `Comment`, `WifiLlapiCaseResult.comment` written with truncation, BLOCKED/SKIP unchanged.
- Sample cases: D037 (Retransmissions), D313 (RetransCount) migrated to delta range.
- Documentation: `plugins/wifi_llapi/CASE_YAML_SYNTAX.md` long-lived schema reference.

## Spec & change

- Spec: `docs/superpowers/specs/2026-04-27-issue-38-counter-delta-validation-design.md`
- OpenSpec: `openspec/changes/wifi-llapi-counter-delta-validation/`

## Test plan

- [x] `pytest tests/test_wifi_llapi_delta.py` — unit tests for delta operators + phase validator + dispatch
- [x] `pytest tests/test_wifi_llapi_delta_integration.py` — end-to-end fixtures + xlsx M column propagation
- [x] `pytest tests/test_wifi_llapi_excel.py` — extended for M column behaviour & BLOCKED/SKIP regression guards
- [x] `pytest tests/` full suite — no regression
- [x] `openspec validate wifi-llapi-counter-delta-validation --strict`
- [x] D037 / D313 schema validates after migration

## Out of scope (subsequent waves)

- Wave 2: ~30 Stage A case migrations
- Wave 3: ~50 Stage B case migrations
- `pass_criteria_not_satisfied` reason_code refinement (#39)
EOF
)"
```

---

## Self-Review

### Spec coverage check

Walking through `openspec/changes/wifi-llapi-counter-delta-validation/specs/wifi-llapi-counter-validation/spec.md`:

| Spec Requirement | Plan Coverage |
|---|---|
| `phase` field accepted on steps | Tasks 10, 11 + integration Task 13 |
| `phase` defaults to `verify` | Task 10 step 10.3 (default branch); Task 13 fixtures + Task 11 test |
| Unknown phase rejected | Task 10 (test_phase_invalid_value) |
| Phase ordering validated at load when delta present | Tasks 10 + 11 |
| `delta_nonzero` semantics | Tasks 6, 7 |
| `delta_match` semantics + tolerance | Task 8 |
| Evaluate dispatch by `delta` key | Task 9 |
| Comment as plugin-level constant | Tasks 6 + 7/8 (uses ZERO_DELTA_COMMENT) |
| M column header + write + truncate | Tasks 1, 2, 3, 4 |
| BLOCKED/SKIP not in M | Task 5 (regression guards) |
| Five new reason_codes | Tasks 7, 8 (delta_*) and Task 11 (invalid_delta_schema flow via `blocked_reason`) |
| `pass_criteria_not_satisfied` preserved | Task 9 (test_evaluate_field_path_unchanged) |

All spec requirements covered.

### Placeholder scan

No `TBD` / `TODO` / "implement later" anywhere; every code block is concrete; every test has assertions; every command has expected output described. Migration trigger workloads use a concrete iperf3 invocation (matching the existing STA env baseline), not a placeholder.

### Type / signature consistency

- `_evaluate_delta_criterion(case, context, criterion, idx) -> bool` — used identically in Tasks 7, 8, 9.
- `_validate_phase_ordering(case) -> str | None` — used identically in Tasks 10, 11.
- `_truncate_comment(text: str | None, *, limit: int = 200) -> str` — used identically in Tasks 3, 4.
- `Plugin._phase_blocked: list[Any]` — initialized in Task 11, consumed in Task 12.
- `WifiLlapiCaseResult.comment` is the existing dataclass field — wired in Task 4.

Consistent.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-27-wifi-llapi-counter-delta-validation-wave1.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**

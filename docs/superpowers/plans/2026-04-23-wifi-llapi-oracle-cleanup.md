# wifi_llapi Oracle Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除 wifi_llapi 的 YAML 內嵌 oracle metadata (`results_reference` / `source.baseline` / `source.report` / `source.sheet`) 與其 runtime override 邏輯，使報表值只依 DUT 實測 verdict 產生。

**Architecture:** 單一 PR、兩個 commit。Commit 1 改程式（案件 schema validator、runtime simplification、migration script、tests、docs）；Commit 2 是 migration script 產出的 420 YAML 機械化變更。Schema validator fail-fast 防 oracle 欄位回歸。

**Tech Stack:** Python 3.11 / pytest / `ruamel.yaml` (新 dev dep) / 既有 `pyyaml` / `click` / `openpyxl` 不變

**References:**
- Spec: `docs/superpowers/specs/2026-04-23-wifi-llapi-results-reference-cleanup-design.md`
- OpenSpec change: `openspec/changes/remove-wifi-llapi-results-reference/`

---

## File map

### Create

- `.` 新 worktree `../testpilot-oracle-cleanup` on branch `feat/wifi-llapi-oracle-cleanup`
- `scripts/wifi_llapi_strip_oracle_metadata.py` — 一次性 migration CLI（dry-run 預設、`--apply` 實際寫入、idempotent）
- `tests/test_wifi_llapi_strip_oracle_metadata.py` — migration 測試
- `tests/test_case_utils.py` — `case_band_results` verdict-only 行為 + `baseline_results_reference` 被刪除的 ImportError 驗證
- `tests/test_wifi_llapi_cases_oracle_free.py` — repo-scale smoke：420 case 全過 `validate_wifi_llapi_case` + 文字 scan 確認零 forbidden key

### Modify

- `pyproject.toml` — dev deps 加 `ruamel.yaml>=0.18,<1.0`；version `0.2.1` → `0.2.2`
- `src/testpilot/core/case_utils.py` — 刪 `baseline_results_reference()`；簡化 `case_band_results()` 為 3 行
- `src/testpilot/core/orchestrator.py` — 刪 L38 import 與 L227-228 wrapper
- `src/testpilot/schema/case_schema.py` — 新增 `_WIFI_LLAPI_FORBIDDEN_TOP_KEYS` / `_WIFI_LLAPI_FORBIDDEN_SOURCE_KEYS` 常數與 `validate_wifi_llapi_case()`
- `plugins/wifi_llapi/plugin.py` — `discover_cases()` 載入後逐 case 跑 `validate_wifi_llapi_case`
- `tests/test_case_schema.py` — 擴充 4 個 wifi_llapi validator 測試
- `plugins/wifi_llapi/cases/*.yaml` — migration script 產出 YAML 變更（Task 7 執行，獨立 commit）
- `CHANGELOG.md` — `### Removed: BREAKING ...` 段落
- `AGENTS.md` — §Case Discovery 註記 oracle metadata 已移除

### Verify after merge

- `openspec archive remove-wifi-llapi-results-reference` 歸檔

---

## Task 1: 建立 worktree 與依賴

**Files:**
- Create: `../testpilot-oracle-cleanup` (worktree + branch `feat/wifi-llapi-oracle-cleanup`)
- Modify: `pyproject.toml`

- [ ] **Step 1: 建 worktree 與 branch**

```bash
git worktree add ../testpilot-oracle-cleanup -b feat/wifi-llapi-oracle-cleanup
cd ../testpilot-oracle-cleanup
uv pip install -e ".[dev]"
```

Expected: `../testpilot-oracle-cleanup` 存在、切到新 branch。`uv pip install` 成功。

- [ ] **Step 2: 確認目前 ruamel.yaml 未安裝**

Run: `python -c "import ruamel.yaml" 2>&1`
Expected: `ModuleNotFoundError: No module named 'ruamel'`

- [ ] **Step 3: `pyproject.toml` 加入 ruamel.yaml 到 dev deps**

於 `[project.optional-dependencies]` 的 `dev = [` list 加一行：

```toml
    "ruamel.yaml>=0.18,<1.0",
```

保持字母序插入。

- [ ] **Step 4: 重裝 dev deps**

Run: `uv pip install -e ".[dev]" && python -c "import ruamel.yaml; print(ruamel.yaml.__version__)"`
Expected: 印出 `0.18.x` 版本、無錯誤。

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml
git commit -m "chore(deps): add ruamel.yaml for wifi_llapi oracle migration"
```

---

## Task 2: Migration script — dry-run 骨架（TDD）

**Files:**
- Create: `scripts/wifi_llapi_strip_oracle_metadata.py`
- Create: `tests/test_wifi_llapi_strip_oracle_metadata.py`

- [ ] **Step 1: 寫第一個 failing test — dry-run 不改檔**

Create `tests/test_wifi_llapi_strip_oracle_metadata.py`:

```python
"""Tests for scripts/wifi_llapi_strip_oracle_metadata.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "wifi_llapi_strip_oracle_metadata.py"

SAMPLE_WITH_ORACLE = """\
id: d001-sample
name: Sample
source:
  row: 1
  object: WiFi.SSID.{i}.
  api: getSSIDStats()
  baseline: 0310-BGW720-300
  report: 0310-BGW720-300_LLAPI_Test_Report.xlsx
  sheet: Wifi_LLAPI
bands:
- 5g
results_reference:
  v4.0.3:
    5g: Not Supported
topology:
  devices:
    DUT:
      role: ap
steps:
- id: step1
  target: dut
  action: read
  command: ubus-cli "x"
pass_criteria:
- field: x
  operator: equals
  value: 0
"""


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_strip_dry_run_no_write(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    case_file = case_dir / "D001_sample.yaml"
    case_file.write_text(SAMPLE_WITH_ORACLE, encoding="utf-8")
    before = case_file.read_bytes()

    result = _run(["--cases-dir", str(case_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert case_file.read_bytes() == before, "dry-run must not modify files"
    assert "D001_sample.yaml" in result.stdout
    assert "results_reference" in result.stdout
    assert "source.baseline" in result.stdout
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_wifi_llapi_strip_oracle_metadata.py::test_strip_dry_run_no_write -v`
Expected: FAIL with `FileNotFoundError` (script 還不存在)

- [ ] **Step 3: 建立 script 骨架**

Create `scripts/wifi_llapi_strip_oracle_metadata.py`:

```python
#!/usr/bin/env python3
"""Strip wifi_llapi oracle metadata (results_reference / source.{baseline,report,sheet}).

Removes the four oracle metadata fields introduced by the pre-#31 workbook-oracle
pattern. Preserves YAML formatting, comments, and key order via ruamel.yaml
round-trip. Idempotent — re-running on already-clean YAML is a no-op.

Usage:
    python scripts/wifi_llapi_strip_oracle_metadata.py              # dry-run
    python scripts/wifi_llapi_strip_oracle_metadata.py --apply      # write
    python scripts/wifi_llapi_strip_oracle_metadata.py --cases-dir <path> --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ruamel.yaml import YAML

FORBIDDEN_TOP_KEYS = ("results_reference",)
FORBIDDEN_SOURCE_KEYS = ("baseline", "report", "sheet")


def _default_cases_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "plugins" / "wifi_llapi" / "cases"


def _scan_and_strip(case_file: Path, yaml_rt: YAML, apply: bool) -> list[str]:
    """Return list of removed field names; write back to disk if apply=True."""
    with case_file.open("r", encoding="utf-8") as f:
        data = yaml_rt.load(f)

    if not isinstance(data, dict):
        return []

    removed: list[str] = []
    for key in FORBIDDEN_TOP_KEYS:
        if key in data:
            removed.append(key)
            if apply:
                del data[key]

    source = data.get("source")
    if isinstance(source, dict):
        for key in FORBIDDEN_SOURCE_KEYS:
            if key in source:
                removed.append(f"source.{key}")
                if apply:
                    del source[key]

    if apply and removed:
        with case_file.open("w", encoding="utf-8") as f:
            yaml_rt.dump(data, f)

    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases-dir", type=Path, default=_default_cases_dir())
    parser.add_argument("--apply", action="store_true", help="actually write changes (default: dry-run)")
    args = parser.parse_args(argv)

    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 4096  # don't re-wrap long lines

    cases_dir: Path = args.cases_dir
    if not cases_dir.is_dir():
        print(f"error: cases dir not found: {cases_dir}", file=sys.stderr)
        return 2

    files = sorted(cases_dir.glob("*.yaml"))
    scanned = modified = already_clean = 0
    for case_file in files:
        scanned += 1
        removed = _scan_and_strip(case_file, yaml_rt, apply=args.apply)
        if removed:
            modified += 1
            print(f"{case_file.name}: removed {removed}")
        else:
            already_clean += 1

    mode = "apply" if args.apply else "dry-run"
    print(
        f"summary ({mode}): {scanned} files scanned, "
        f"{modified} {'modified' if args.apply else 'would be modified'}, "
        f"{already_clean} already clean"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/test_wifi_llapi_strip_oracle_metadata.py::test_strip_dry_run_no_write -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/wifi_llapi_strip_oracle_metadata.py tests/test_wifi_llapi_strip_oracle_metadata.py
git commit -m "feat(migration): scaffold wifi_llapi oracle-metadata strip script"
```

---

## Task 3: Migration script — --apply removes all four keys

**Files:**
- Modify: `tests/test_wifi_llapi_strip_oracle_metadata.py`

- [ ] **Step 1: Add failing test for --apply behavior**

Append to `tests/test_wifi_llapi_strip_oracle_metadata.py`:

```python
def test_strip_apply_removes_all_four_keys(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    case_file = case_dir / "D001_sample.yaml"
    case_file.write_text(SAMPLE_WITH_ORACLE, encoding="utf-8")

    result = _run(["--cases-dir", str(case_dir), "--apply"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    after_text = case_file.read_text(encoding="utf-8")
    assert "results_reference" not in after_text
    assert "baseline:" not in after_text.split("steps:")[0]  # only check header before steps
    assert "report:" not in after_text.split("steps:")[0]
    assert "sheet:" not in after_text.split("steps:")[0]
    # Surviving keys
    assert "row: 1" in after_text
    assert "object: WiFi.SSID.{i}." in after_text
    assert "api: getSSIDStats()" in after_text


def test_strip_preserves_source_row_object_api(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    case_file = case_dir / "D001_sample.yaml"
    case_file.write_text(SAMPLE_WITH_ORACLE, encoding="utf-8")

    _run(["--cases-dir", str(case_dir), "--apply"], cwd=tmp_path)

    import yaml as pyyaml
    data = pyyaml.safe_load(case_file.read_text(encoding="utf-8"))
    assert data["source"]["row"] == 1
    assert data["source"]["object"] == "WiFi.SSID.{i}."
    assert data["source"]["api"] == "getSSIDStats()"
    assert "baseline" not in data["source"]
    assert "report" not in data["source"]
    assert "sheet" not in data["source"]
    assert "results_reference" not in data
```

- [ ] **Step 2: Run — expect PASS (script already handles --apply)**

Run: `uv run pytest tests/test_wifi_llapi_strip_oracle_metadata.py -v`
Expected: All 3 tests PASS (Task 2 scaffold already implemented --apply behaviour)

If any test FAILs, fix the script in `scripts/wifi_llapi_strip_oracle_metadata.py` until green.

- [ ] **Step 3: Commit**

```bash
git add tests/test_wifi_llapi_strip_oracle_metadata.py
git commit -m "test(migration): cover --apply removes oracle keys, preserves survivors"
```

---

## Task 4: Migration script — idempotency, comments, source-not-mapping

**Files:**
- Modify: `tests/test_wifi_llapi_strip_oracle_metadata.py`

- [ ] **Step 1: Add idempotency test**

Append to `tests/test_wifi_llapi_strip_oracle_metadata.py`:

```python
def test_strip_idempotent(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    case_file = case_dir / "D001_sample.yaml"
    case_file.write_text(SAMPLE_WITH_ORACLE, encoding="utf-8")

    _run(["--cases-dir", str(case_dir), "--apply"], cwd=tmp_path)
    first_pass = case_file.read_bytes()

    result2 = _run(["--cases-dir", str(case_dir), "--apply"], cwd=tmp_path)
    assert result2.returncode == 0
    assert case_file.read_bytes() == first_pass, "second --apply must be a no-op"
    assert "already clean" in result2.stdout
```

- [ ] **Step 2: Add comments/ordering preservation test**

Append:

```python
SAMPLE_WITH_COMMENTS = """\
# Top-level case comment
id: d002-commented
name: Commented sample  # inline
source:
  # kept fields first
  row: 2
  object: WiFi.Radio.{i}.
  api: getRadioStats()
  baseline: 0310-BGW720-300  # to be stripped
bands:
- 5g
results_reference:
  v4.0.3:
    5g: Pass
topology:
  devices:
    DUT:
      role: ap
steps:
- id: step1
  target: dut
  action: read
  command: ubus-cli "x"
pass_criteria:
- field: x
  operator: equals
  value: 0
"""


def test_strip_preserves_comments_and_ordering(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    case_file = case_dir / "D002_commented.yaml"
    case_file.write_text(SAMPLE_WITH_COMMENTS, encoding="utf-8")

    _run(["--cases-dir", str(case_dir), "--apply"], cwd=tmp_path)

    after_text = case_file.read_text(encoding="utf-8")
    assert "# Top-level case comment" in after_text
    assert "# kept fields first" in after_text
    assert "# inline" in after_text
    # Surviving key order
    lines = [ln.strip() for ln in after_text.splitlines() if ln.strip().startswith(("row:", "object:", "api:"))]
    assert lines[0].startswith("row:")
    assert lines[1].startswith("object:")
    assert lines[2].startswith("api:")
```

- [ ] **Step 3: Add source-not-mapping test**

Append:

```python
SAMPLE_SOURCE_NULL = """\
id: d003-source-null
name: Null source
source: null
bands:
- 5g
results_reference:
  v4.0.3:
    5g: Pass
topology:
  devices:
    DUT:
      role: ap
steps:
- id: step1
  target: dut
  action: read
  command: ubus-cli "x"
pass_criteria:
- field: x
  operator: equals
  value: 0
"""


def test_strip_source_not_mapping(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    case_file = case_dir / "D003_null_source.yaml"
    case_file.write_text(SAMPLE_SOURCE_NULL, encoding="utf-8")

    result = _run(["--cases-dir", str(case_dir), "--apply"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    after_text = case_file.read_text(encoding="utf-8")
    assert "results_reference" not in after_text
    # source: null preserved (not touched)
    assert "source: null" in after_text or "source:\n" in after_text
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_wifi_llapi_strip_oracle_metadata.py -v`
Expected: All tests PASS (script in Task 2 already handles these cases)

If any fail, fix `_scan_and_strip` accordingly.

- [ ] **Step 5: Commit**

```bash
git add tests/test_wifi_llapi_strip_oracle_metadata.py
git commit -m "test(migration): cover idempotency, comment preservation, null source"
```

---

## Task 5: Schema validator — forbidden-keys check (TDD)

**Files:**
- Modify: `src/testpilot/schema/case_schema.py`
- Modify: `tests/test_case_schema.py`

- [ ] **Step 1: Add failing test — top-level results_reference rejected**

Append to `tests/test_case_schema.py`:

```python
from testpilot.schema.case_schema import (
    CaseValidationError,
    validate_wifi_llapi_case,
)


def _clean_wifi_llapi_case() -> dict:
    return {
        "id": "d001-clean",
        "name": "Clean sample",
        "source": {
            "row": 1,
            "object": "WiFi.SSID.{i}.",
            "api": "getSSIDStats()",
        },
        "bands": ["5g"],
        "topology": {"devices": {"DUT": {"role": "ap"}}},
        "steps": [
            {"id": "s1", "target": "dut", "action": "read", "command": 'ubus-cli "x"'},
        ],
        "pass_criteria": [{"field": "x", "operator": "equals", "value": 0}],
    }


def test_validate_wifi_llapi_rejects_results_reference():
    case = _clean_wifi_llapi_case()
    case["results_reference"] = {"v4.0.3": {"5g": "Not Supported"}}
    with pytest.raises(CaseValidationError) as exc_info:
        validate_wifi_llapi_case(case, source="test.yaml")
    msg = str(exc_info.value)
    assert "#31 cleanup" in msg
    assert "results_reference" in msg


def test_validate_wifi_llapi_rejects_source_baseline():
    case = _clean_wifi_llapi_case()
    case["source"]["baseline"] = "0310-BGW720-300"
    with pytest.raises(CaseValidationError) as exc_info:
        validate_wifi_llapi_case(case, source="test.yaml")
    msg = str(exc_info.value)
    assert "#31 cleanup" in msg
    assert "baseline" in msg


def test_validate_wifi_llapi_rejects_source_report_and_sheet():
    case = _clean_wifi_llapi_case()
    case["source"]["report"] = "foo.xlsx"
    case["source"]["sheet"] = "Wifi_LLAPI"
    with pytest.raises(CaseValidationError) as exc_info:
        validate_wifi_llapi_case(case, source="test.yaml")
    msg = str(exc_info.value)
    assert "#31 cleanup" in msg
    assert "report" in msg
    assert "sheet" in msg


def test_validate_wifi_llapi_passes_clean_case():
    case = _clean_wifi_llapi_case()
    validate_wifi_llapi_case(case, source="test.yaml")  # must not raise
```

(Ensure `import pytest` exists at top of the file; add if missing.)

- [ ] **Step 2: Run — expect failure (ImportError)**

Run: `uv run pytest tests/test_case_schema.py -v -k wifi_llapi`
Expected: FAIL with `ImportError: cannot import name 'validate_wifi_llapi_case'`

- [ ] **Step 3: Implement `validate_wifi_llapi_case`**

In `src/testpilot/core/schema/case_schema.py`, add after the existing `validate_case` function (around L534):

```python
_WIFI_LLAPI_FORBIDDEN_TOP_KEYS: set[str] = {"results_reference"}
_WIFI_LLAPI_FORBIDDEN_SOURCE_KEYS: set[str] = {"baseline", "report", "sheet"}


def validate_wifi_llapi_case(case: dict[str, Any], source: Path | str = "<unknown>") -> None:
    """Additional wifi_llapi-specific validation on top of generic ``validate_case``.

    Rejects the four oracle metadata fields removed by #31 cleanup. Intended to be
    called AFTER ``validate_case`` (or ``load_case``) has already run; this function
    only performs the plugin-local forbidden-keys check.
    """
    forbidden_top = _WIFI_LLAPI_FORBIDDEN_TOP_KEYS & set(case.keys())
    if forbidden_top:
        raise CaseValidationError(
            f"{source}: wifi_llapi cases must not contain {sorted(forbidden_top)} "
            f"(removed by #31 cleanup; use actual DUT verdict, not workbook oracle)"
        )
    src = case.get("source")
    if isinstance(src, dict):
        forbidden_src = _WIFI_LLAPI_FORBIDDEN_SOURCE_KEYS & set(src.keys())
        if forbidden_src:
            raise CaseValidationError(
                f"{source}: wifi_llapi source.* must not contain {sorted(forbidden_src)} "
                f"(removed by #31 cleanup; workbook metadata no longer used at runtime)"
            )
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_case_schema.py -v -k wifi_llapi`
Expected: All 4 new tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/testpilot/schema/case_schema.py tests/test_case_schema.py
git commit -m "feat(schema): add validate_wifi_llapi_case forbidden-keys check"
```

---

## Task 6: Runtime simplification — case_band_results verdict-only (TDD)

**Files:**
- Create: `tests/test_case_utils.py`
- Modify: `src/testpilot/core/case_utils.py`

- [ ] **Step 1: Write failing tests for simplified case_band_results**

Create `tests/test_case_utils.py`:

```python
"""Tests for testpilot.core.case_utils — verdict-only behaviour after #31 cleanup."""

from __future__ import annotations

import pytest

from testpilot.core.case_utils import case_band_results


def test_case_band_results_verdict_true_all_bands():
    case = {"bands": ["5g", "6g", "2.4g"]}
    assert case_band_results(case, True) == ("Pass", "Pass", "Pass")


def test_case_band_results_verdict_true_partial_bands():
    case = {"bands": ["5g"]}
    assert case_band_results(case, True) == ("Pass", "N/A", "N/A")


def test_case_band_results_verdict_false_two_bands():
    case = {"bands": ["5g", "6g"]}
    assert case_band_results(case, False) == ("Fail", "Fail", "N/A")


def test_case_band_results_ignores_results_reference():
    """Even if a stray results_reference is present, runtime MUST ignore it."""
    case = {
        "bands": ["5g"],
        "source": {"baseline": "v4.0.3"},
        "results_reference": {"v4.0.3": {"5g": "Not Supported"}},
    }
    # Post-cleanup: must be Pass (from verdict), not "Not Supported" (from oracle)
    assert case_band_results(case, True) == ("Pass", "N/A", "N/A")


def test_baseline_results_reference_removed():
    """`baseline_results_reference` MUST be deleted (not just deprecated)."""
    with pytest.raises(ImportError):
        from testpilot.core.case_utils import baseline_results_reference  # noqa: F401
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_case_utils.py -v`
Expected: 
- `test_case_band_results_ignores_results_reference` FAILS with `AssertionError: ('Not Supported', 'N/A', 'N/A') != ('Pass', 'N/A', 'N/A')`
- `test_baseline_results_reference_removed` FAILS (import succeeds; function still exists)
- Other three PASS (existing behaviour handles them)

- [ ] **Step 3: Simplify `case_band_results` and delete `baseline_results_reference`**

In `src/testpilot/core/case_utils.py`:

**(a)** Delete the entire `baseline_results_reference` function (L100-139).

**(b)** Replace `case_band_results` (L142-167) with:

```python
def case_band_results(case: dict[str, Any], verdict: bool) -> tuple[str, str, str]:
    """Return per-band (5g, 6g, 2.4g) results from verdict and case.bands only."""
    status = "Pass" if verdict else "Fail"
    return band_results(status, case.get("bands"))
```

**(c)** Remove the now-unused `import re` check: keep `import re` if other functions use it. Grep to confirm:

```bash
grep -n "re\." src/testpilot/core/case_utils.py
```

`sanitize_case_id` uses `re.sub` → keep `import re`.

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_case_utils.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/testpilot/core/case_utils.py tests/test_case_utils.py
git commit -m "refactor(case_utils): drop results_reference oracle from case_band_results"
```

---

## Task 7: Orchestrator cleanup — remove re-export

**Files:**
- Modify: `src/testpilot/core/orchestrator.py`

- [ ] **Step 1: Grep current references**

Run: `grep -n "baseline_results_reference\|_baseline_results_reference" src/testpilot/core/orchestrator.py`
Expected: two hits — L38 import, L227-228 wrapper.

- [ ] **Step 2: Delete L38 import**

Find and remove the line:

```python
from testpilot.core.case_utils import (
    ...
    baseline_results_reference as _baseline_results_reference,
    ...
)
```

Delete only the `baseline_results_reference as _baseline_results_reference,` line inside the import tuple; leave other imports untouched.

- [ ] **Step 3: Delete L227-228 wrapper**

Remove:

```python
def _baseline_results_reference(case: dict[str, Any]) -> dict[str, Any] | None:
    return _baseline_results_reference(case)
```

(The shadowing is obvious from context; delete the function definition entirely.)

- [ ] **Step 4: Grep external callers**

Run: `grep -rn "baseline_results_reference" src/ plugins/ tests/ --include="*.py"`
Expected: zero results (all caller sites removed).

If any remain, investigate each and remove or replace with direct `case_band_results` / `band_results` usage.

- [ ] **Step 5: Run orchestrator-adjacent tests**

Run: `uv run pytest plugins/wifi_llapi/tests/ tests/test_case_utils.py tests/test_case_schema.py -v 2>&1 | tail -30`
Expected: All pass. If any existing fixture uses `results_reference`, update in next task.

- [ ] **Step 6: Commit**

```bash
git add src/testpilot/core/orchestrator.py
git commit -m "refactor(orchestrator): remove baseline_results_reference re-export"
```

---

## Task 8: Clean up existing test fixtures using results_reference

**Files:**
- Modify: tests / plugin test fixtures (grep-driven)

- [ ] **Step 1: Grep for results_reference in tests**

Run: 
```bash
grep -rn "results_reference\|baseline_results_reference" tests/ plugins/wifi_llapi/tests/ --include="*.py"
```

Expected: some hits in older fixtures. Record the list.

- [ ] **Step 2: For each hit, update fixture**

For each file listed, open and remove `results_reference: {...}` entries from inline fixture data. If a test's expectation depends on oracle-override behaviour ("assert this returns 'Not Supported'"), update the expectation to verdict-based ("assert this returns 'Pass'" or similar).

If a test file is *purely* exercising the removed `baseline_results_reference` behaviour with no other purpose, delete the test — do not preserve dead tests.

- [ ] **Step 3: Grep again — confirm zero**

Run: `grep -rn "results_reference\|baseline_results_reference" tests/ plugins/wifi_llapi/tests/ --include="*.py"`
Expected: no hits (except possibly a historical comment with `#31 cleanup` context — that's fine).

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -q`
Expected: all pass. Any failing tests should be addressed before commit.

- [ ] **Step 5: Commit**

```bash
git add tests/ plugins/wifi_llapi/tests/
git commit -m "test(wifi_llapi): remove stale results_reference fixtures"
```

---

## Task 9: Plugin integration — hook validator into discover_cases

**Files:**
- Modify: `plugins/wifi_llapi/plugin.py`

- [ ] **Step 1: Read current discover_cases**

Reference: `plugins/wifi_llapi/plugin.py:127-128`:

```python
def discover_cases(self) -> list[dict[str, Any]]:
    return load_cases_dir(self.cases_dir)
```

- [ ] **Step 2: Modify import**

At top of `plugins/wifi_llapi/plugin.py`, change:

```python
from testpilot.schema.case_schema import load_cases_dir, load_wifi_band_baselines
```

to:

```python
from testpilot.schema.case_schema import (
    load_cases_dir,
    load_wifi_band_baselines,
    validate_wifi_llapi_case,
)
```

- [ ] **Step 3: Update discover_cases**

Replace the body of `discover_cases`:

```python
def discover_cases(self) -> list[dict[str, Any]]:
    cases = load_cases_dir(self.cases_dir)
    for case in cases:
        case_id = case.get("id", "<unknown>")
        validate_wifi_llapi_case(case, source=case_id)
    return cases
```

- [ ] **Step 4: Verify plugin discovery still works against test fixtures**

Run: `uv run pytest plugins/wifi_llapi/tests/ -q -k discover 2>&1 | tail -15`
Expected: existing discovery tests pass against test fixtures (not production cases — those still contain oracle keys until Task 11).

If discovery tests exercise **real** production cases directly, they'll fail here due to real YAML still containing oracle keys — that's expected. Record failing test names; they'll go green after Task 11's mass rewrite.

- [ ] **Step 5: Commit**

```bash
git add plugins/wifi_llapi/plugin.py
git commit -m "feat(wifi_llapi): validate_wifi_llapi_case in discover_cases"
```

---

## Task 10: Repo-scale smoke test (failing, will go green post-migration)

**Files:**
- Create: `tests/test_wifi_llapi_cases_oracle_free.py`

- [ ] **Step 1: Write the test**

Create `tests/test_wifi_llapi_cases_oracle_free.py`:

```python
"""Repo-scale assertion: no shipped wifi_llapi case contains oracle metadata."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from testpilot.schema.case_schema import (
    CaseValidationError,
    load_case,
    validate_wifi_llapi_case,
)

CASES_DIR = Path(__file__).resolve().parents[1] / "plugins" / "wifi_llapi" / "cases"
FORBIDDEN_TOP = {"results_reference"}
FORBIDDEN_SOURCE = {"baseline", "report", "sheet"}


@pytest.mark.parametrize(
    "case_path",
    sorted(CASES_DIR.glob("*.yaml")),
    ids=lambda p: p.name,
)
def test_all_wifi_llapi_cases_pass_schema(case_path: Path) -> None:
    data = load_case(case_path)
    validate_wifi_llapi_case(data, source=case_path)


def test_no_shipped_case_contains_forbidden_fields() -> None:
    offenders: dict[str, list[str]] = {}
    for case_path in sorted(CASES_DIR.glob("*.yaml")):
        data = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        found: list[str] = []
        for key in FORBIDDEN_TOP:
            if key in data:
                found.append(key)
        src = data.get("source")
        if isinstance(src, dict):
            for key in FORBIDDEN_SOURCE:
                if key in src:
                    found.append(f"source.{key}")
        if found:
            offenders[case_path.name] = found
    assert offenders == {}, f"forbidden oracle keys still present: {offenders}"
```

- [ ] **Step 2: Run — expect MANY failures (300+ cases still have oracle keys)**

Run: `uv run pytest tests/test_wifi_llapi_cases_oracle_free.py -q 2>&1 | tail -10`
Expected: 300+ parametrized cases FAIL. **This is expected** — Task 11 will fix them.

- [ ] **Step 3: Commit** (failing test is intentional here — Task 11 makes it green)

```bash
git add tests/test_wifi_llapi_cases_oracle_free.py
git commit -m "test(wifi_llapi): add repo-scale oracle-free smoke (fails until migration)"
```

---

## Task 11: Execute YAML mass rewrite (commit 2)

**Files:**
- Modify: `plugins/wifi_llapi/cases/*.yaml` (~389 files)

- [ ] **Step 1: Dry-run against production cases**

Run: `python scripts/wifi_llapi_strip_oracle_metadata.py 2>&1 | tail -30`
Expected: `summary (dry-run): 420 files scanned, ~389 would be modified, ~31 already clean`

Note the exact count; will be used in commit message.

- [ ] **Step 2: Apply**

Run: `python scripts/wifi_llapi_strip_oracle_metadata.py --apply 2>&1 | tail -10`
Expected: `summary (apply): 420 files scanned, <N> modified, <M> already clean`

- [ ] **Step 3: Verify diff is mechanical (no format explosion)**

Run: `git diff --stat plugins/wifi_llapi/cases/ | tail -10`
Expected: ~389 files, each with small line-count deltas (typically 2-10 lines removed per file).

Run: `git diff plugins/wifi_llapi/cases/ | head -100`
Spot-check: removals limited to `results_reference` blocks and `source.{baseline,report,sheet}` lines. No wholesale reformatting, no quote-style churn on surrounding fields.

If diffs look wrong (e.g., mass key re-ordering, comment loss), revert: `git checkout -- plugins/wifi_llapi/cases/`, investigate ruamel `width` / preserve_quotes setting.

- [ ] **Step 4: Run repo-scale smoke — expect pass**

Run: `uv run pytest tests/test_wifi_llapi_cases_oracle_free.py -q 2>&1 | tail -10`
Expected: All 420 parametrized cases PASS; `test_no_shipped_case_contains_forbidden_fields` PASSes.

- [ ] **Step 5: Idempotency sanity check**

Run: `python scripts/wifi_llapi_strip_oracle_metadata.py --apply 2>&1 | tail -3`
Expected: `summary (apply): 420 files scanned, 0 modified, 420 already clean`

Run: `git status plugins/wifi_llapi/cases/`
Expected: nothing staged / modified in the second run.

- [ ] **Step 6: Commit YAML rewrite as a separate commit**

```bash
git add plugins/wifi_llapi/cases/
git commit -m "chore(wifi_llapi): strip results_reference/source.{baseline,report,sheet} from cases

Mass rewrite via scripts/wifi_llapi_strip_oracle_metadata.py.
<N> YAML files modified, <M> already clean. Format preserved via
ruamel.yaml round-trip.

Runtime reports now reflect DUT verdict instead of workbook oracle lookup."
```

---

## Task 12: Full suite + local smoke

**Files:** none (validation only)

- [ ] **Step 1: Full pytest**

Run: `uv run pytest -q 2>&1 | tail -10`
Expected: all tests PASS.

- [ ] **Step 2: Local `testpilot run wifi_llapi` smoke**

If a testbed is available:

```bash
testpilot run wifi_llapi --testbed <lab-config> 2>&1 | tail -30
```

Expected: run completes; artifact directory produced. Verify:

```bash
ls plugins/wifi_llapi/reports/<latest>/
```

Expected absence: no `alignment_issues.json`. (PR#32 already removed this; confirm still gone.)

Inspect the report .md:

```bash
grep -c "Not Supported" plugins/wifi_llapi/reports/<latest>/*.md
grep -c "Pass" plugins/wifi_llapi/reports/<latest>/*.md
```

Expected: "Not Supported" count drops sharply vs a pre-cleanup report; "Pass" count rises correspondingly.

If no testbed is available, skip this step and note in the PR body.

- [ ] **Step 3: Negative test — schema rejection**

Temporarily edit one YAML to add oracle metadata back:

```bash
head -20 plugins/wifi_llapi/cases/D001_*.yaml  # note the first case file name
```

Insert `results_reference: {foo: bar}` at top-level, save, then:

```bash
uv run pytest tests/test_wifi_llapi_cases_oracle_free.py -q -k D001 2>&1 | tail -20
```

Expected: test FAILS with message containing `#31 cleanup` and `results_reference`.

Revert the YAML: `git checkout -- plugins/wifi_llapi/cases/D001_*.yaml`

- [ ] **Step 4: No commit** (this task is verification only)

---

## Task 13: Docs + version bump

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`
- Modify: `pyproject.toml`

- [ ] **Step 1: Update CHANGELOG.md**

At the top of `CHANGELOG.md`, under the next unreleased version heading (create `## [0.2.2] - 2026-04-23` if none), add:

```markdown
### Removed

- **BREAKING**: wifi_llapi cases no longer support `results_reference`,
  `source.baseline`, `source.report`, `source.sheet`. Report values now reflect
  actual DUT verdict instead of workbook oracle lookup. Downstream forks must
  rebase and re-run `scripts/wifi_llapi_strip_oracle_metadata.py --apply`.
- `baseline_results_reference()` removed from `testpilot.core.case_utils`.
  External callers must switch to verdict-based `case_band_results()` directly.
```

- [ ] **Step 2: Update AGENTS.md**

In `AGENTS.md` §Case Discovery (find the existing section; add a new bullet/note):

```markdown
- `results_reference`, `source.baseline`, `source.report`, `source.sheet` are removed
  from all wifi_llapi cases as of #31 cleanup. Reports reflect runtime verdict only.
  `validate_wifi_llapi_case()` enforces this at case-load time.
```

- [ ] **Step 3: Version bump**

In `pyproject.toml`:

```toml
version = "0.2.2"
```

(Change from whatever was there previously, matching v0.2.1 → v0.2.2 per the spec.)

- [ ] **Step 4: Run full pytest once more**

Run: `uv run pytest -q 2>&1 | tail -5`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md AGENTS.md pyproject.toml
git commit -m "docs: document #31 oracle cleanup; bump to 0.2.2"
```

---

## Task 14: Open PR and archive OpenSpec change

**Files:** none (git + openspec operations)

- [ ] **Step 1: Verify commits**

Run: `git log --oneline origin/main..HEAD`
Expected: ~6-8 commits on `feat/wifi-llapi-oracle-cleanup` branch. (The final PR can be squashed or kept as-is per project convention; note spec guidance recommends keeping "code change" separate from "YAML mass rewrite" — commits from Task 1-10+13 form the code change, Task 11 is the YAML rewrite.)

- [ ] **Step 2: Push branch**

```bash
git push -u origin feat/wifi-llapi-oracle-cleanup
```

- [ ] **Step 3: Open PR**

```bash
gh pr create --title "feat(wifi_llapi): remove results_reference oracle (#31 follow-up)" --body "$(cat <<'EOF'
## Summary

Follow-up to PR#32: removes YAML-embedded oracle metadata (`results_reference` / `source.baseline` / `source.report` / `source.sheet`) and the `case_band_results` override branch, so reports reflect actual DUT verdict instead of workbook lookups.

## What changed

- `baseline_results_reference()` deleted; `case_band_results()` simplified to verdict-only
- New `validate_wifi_llapi_case()` schema validator forbids the four oracle keys
- `scripts/wifi_llapi_strip_oracle_metadata.py` migration (ruamel-based, idempotent)
- ~389 YAML files in `plugins/wifi_llapi/cases/` rewritten (separate commit)

## Reference

- Spec: `docs/superpowers/specs/2026-04-23-wifi-llapi-results-reference-cleanup-design.md`
- OpenSpec: `openspec/changes/remove-wifi-llapi-results-reference/`

## ⚠️ Unmasked false-pass

Report values changing from `Not Supported` → `Pass` **do not mean "verified Pass"** —
some may be `pass_criteria` bugs previously hidden by the oracle override. Audit
mode (separate thread) will surface and fix those. This PR exposes the truth; it
does not re-verify it.

## Test plan

- [ ] `uv run pytest -q` green on CI
- [ ] Repo-scale smoke `test_all_wifi_llapi_cases_pass_schema` green
- [ ] Negative schema test: adding `results_reference` back triggers `#31 cleanup` error
- [ ] Local `testpilot run wifi_llapi` smoke: report values reflect verdict

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: After PR merges, archive the OpenSpec change**

Run (after merge, on `main`):

```bash
git checkout main && git pull
openspec archive remove-wifi-llapi-results-reference
git add openspec/
git commit -m "chore(openspec): archive remove-wifi-llapi-results-reference"
git push
```

---

## Self-Review Checklist

Completed while writing this plan:

- **Spec coverage**: all 4 Requirements in `specs/wifi-llapi-oracle-free-verdict/spec.md` have tasks — verdict-only (Task 6/10), schema rejection (Task 5/12), migration script (Task 2-4/11), all-cases-oracle-free (Task 10-11).
- **Placeholder scan**: every code step has complete code; no TBD / "similar to Task N" / open-ended "add error handling".
- **Type consistency**: `validate_wifi_llapi_case(case, source)` signature matches across Tasks 5, 9, 10. `case_band_results(case, verdict)` signature matches Tasks 6, 8. `_scan_and_strip(case_file, yaml_rt, apply)` internal to migration, not exposed.
- **Scope**: single PR, single worktree. Non-goals (reporter dead code, `pass_criteria` audit) explicitly excluded in task 13 CHANGELOG and PR body's "Unmasked false-pass" warning.

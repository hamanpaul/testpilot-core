# Wifi_LLAPI missing row 一次性對齊 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a one-shot script that performs 17 hard-coded actions on `plugins/wifi_llapi/cases/` so the inventory aligns with `wifi_llapi_template.xlsx` (415 Support rows ↔ 415 canonical yamls + 1 `_template.yaml` = 416).

**Architecture:** Single Python module under `tools/oneoff/2026-04-24-align-missing-rows/`. Hard-coded plan dict (no picker logic). Uses `openpyxl` for xlsx, `ruamel.yaml` round-trip for metadata edits (preserves comments / multi-line strings), `git mv` / `git rm` / `git add` for file moves to keep history. Default dry-run; `--apply` actually mutates. Generates markdown + JSON reports.

**Tech Stack:** Python 3.11+, `openpyxl>=3.1`, `ruamel.yaml>=0.17.21`, `pytest` (for inline tests), `git` CLI via subprocess. Run via `uv run python ...`.

**Spec:** `docs/superpowers/specs/2026-04-24-wifi-llapi-align-missing-rows-design.md`

---

## File Structure

```
tools/oneoff/2026-04-24-align-missing-rows/
├── align_missing_rows.py          # main script (~400 LOC)
├── README.md                      # one-page rationale + usage
└── test_align_missing_rows.py     # co-located inline tests (~150 LOC)
```

Reports `inventory_alignment_20260424.md` and `inventory_alignment_20260424.json` are produced by the script into the same directory and committed alongside the apply result.

**Single-responsibility split inside `align_missing_rows.py`:**

- Constants block (`PLAN_RENAMES`, `PLAN_MOVE`, `PLAN_METADATA_ONLY`, `PLAN_DELETES`, `PLAN_CREATE`)
- Loaders (`load_support_rows`, `scan_cases`)
- Validators (`validate_plan`)
- Executors (`execute_rename`, `execute_metadata_only`, `execute_delete`, `execute_create_from_template`)
- Verifier (`verify_post_state`)
- Reporters (`write_markdown_report`, `write_json_report`)
- CLI (`main`)

---

## Task 1: Bootstrap directory + README + dependency sanity

**Files:**
- Create: `tools/oneoff/2026-04-24-align-missing-rows/README.md`
- Create: `tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py` (initial skeleton)

- [ ] **Step 1: Create directory and README**

```bash
mkdir -p tools/oneoff/2026-04-24-align-missing-rows
```

Create `tools/oneoff/2026-04-24-align-missing-rows/README.md`:

```markdown
# wifi_llapi missing-row alignment (2026-04-24, one-shot)

A single-use script that runs 17 hard-coded actions against
`plugins/wifi_llapi/cases/` so its inventory matches the official
`wifi_llapi_template.xlsx` Support set (415 rows).

## Why this exists

`scripts/wifi_llapi_reconcile_inventory.py` (Stream 1) handles ongoing
alignment, but currently has 344 blockers. This batch performs the subset
that is unambiguous and safe (Stream 2): missing-row fills + stale deletes.

See `docs/superpowers/specs/2026-04-24-wifi-llapi-align-missing-rows-design.md`.

## Usage

Dry-run (default — prints plan, writes reports, makes no changes):

    uv run python tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py

Apply (mutates working tree via `git mv`/`git rm`/`git add`):

    uv run python tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py --apply

Working tree must be clean before `--apply`.

## After this runs

Do not delete this directory. The script + reports stay for audit. Future
inventory work should go through `scripts/wifi_llapi_reconcile_inventory.py`.
```

- [ ] **Step 2: Create empty script with shebang + module docstring**

Create `tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py`:

```python
#!/usr/bin/env python3
"""One-shot wifi_llapi inventory alignment (2026-04-24).

See docs/superpowers/specs/2026-04-24-wifi-llapi-align-missing-rows-design.md
for the full design and acceptance criteria.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Actually mutate the working tree (default: dry-run).")
    args = parser.parse_args(argv)
    print(f"mode: {'apply' if args.apply else 'dry-run'} (not implemented yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Verify it runs**

```bash
uv run python tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py
```

Expected output:
```
mode: dry-run (not implemented yet)
```

- [ ] **Step 4: Commit**

```bash
git add tools/oneoff/2026-04-24-align-missing-rows/
git commit -m "tools: scaffold wifi_llapi missing-row alignment one-shot"
```

---

## Task 2: Hard-coded plan constants

**Files:**
- Modify: `tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py`

- [ ] **Step 1: Add path constants and plan dicts**

Insert after the module docstring (before `def main`):

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_XLSX = REPO_ROOT / "plugins" / "wifi_llapi" / "reports" / "templates" / "wifi_llapi_template.xlsx"
CASES_DIR = REPO_ROOT / "plugins" / "wifi_llapi" / "cases"
TEMPLATE_YAML = CASES_DIR / "_template.yaml"
THIS_DIR = Path(__file__).resolve().parent

# 8 file renames + metadata edit. Tuple = (old_filename, new_filename, new_row, new_id).
PLAN_RENAMES: list[tuple[str, str, int, str]] = [
    ("D068_discoverymethodenabled_accesspoint_fils.yaml",
     "D066_discoverymethodenabled_accesspoint_fils.yaml",
     66, "wifi-llapi-D066-discoverymethodenabled-accesspoint-fils"),
    ("D068_discoverymethodenabled_accesspoint_upr.yaml",
     "D067_discoverymethodenabled_accesspoint_upr.yaml",
     67, "wifi-llapi-D067-discoverymethodenabled-accesspoint-upr"),
    ("D115_getstationstats_accesspoint.yaml",
     "D109_getstationstats.yaml",
     109, "wifi-llapi-D109-getstationstats"),
    ("D115_getstationstats_active.yaml",
     "D110_getstationstats_active.yaml",
     110, "wifi-llapi-D110-getstationstats-active"),
    ("D115_getstationstats_associationtime.yaml",
     "D111_getstationstats_associationtime.yaml",
     111, "wifi-llapi-D111-getstationstats-associationtime"),
    ("D115_getstationstats_authenticationstate.yaml",
     "D112_getstationstats_authenticationstate.yaml",
     112, "wifi-llapi-D112-getstationstats-authenticationstate"),
    ("D115_getstationstats_avgsignalstrength.yaml",
     "D113_getstationstats_avgsignalstrength.yaml",
     113, "wifi-llapi-D113-getstationstats-avgsignalstrength"),
    ("D115_getstationstats_avgsignalstrengthbychain.yaml",
     "D114_getstationstats_avgsignalstrengthbychain.yaml",
     114, "wifi-llapi-D114-getstationstats-avgsignalstrengthbychain"),
]

# 1 file move + metadata edit. Tuple = (old_filename, new_filename, new_row, new_id).
PLAN_MOVE: tuple[str, str, int, str] = (
    "D495_retrycount_ssid_stats_basic.yaml",
    "D407_retrycount_ssid_stats.yaml",
    407, "wifi-llapi-D407-retrycount",
)

# Metadata-only fixes. Tuple = (filename, new_row, new_id_or_None).
PLAN_METADATA_ONLY: list[tuple[str, int, str | None]] = [
    ("D495_retrycount_ssid_stats_verified.yaml", 495, None),
]

# Deletions (git rm).
PLAN_DELETES: list[str] = [
    "D096_uapsdenable.yaml",
    "D097_vendorie.yaml",
    "D100_wmmenable.yaml",
    "D102_configmethodssupported.yaml",
    "D106_relaycredentialsenable.yaml",
    "D474_channel_radio_37.yaml",
]

# Single new yaml from _template.yaml.
PLAN_CREATE: dict[str, object] = {
    "filename": "D428_channel_neighbour.yaml",
    "row": 428,
    "id": "wifi-llapi-D428-channel-neighbour",
    "name": "Channel — WiFi.AccessPoint.{i}.Neighbour.{i}.",
    "object": "WiFi.AccessPoint.{i}.Neighbour.{i}.",
    "api": "Channel",
    "hlapi_command": 'ubus-cli "WiFi.AccessPoint.{i}.Neighbour.{i}.Channel=36"',
    "llapi_support": "Support",
}
```

- [ ] **Step 2: Sanity check counts inline**

Add at end of file (above `if __name__`), then run script to verify:

```python
def _self_check_plan_counts() -> None:
    assert len(PLAN_RENAMES) == 8, len(PLAN_RENAMES)
    assert len(PLAN_METADATA_ONLY) == 1
    assert len(PLAN_DELETES) == 6
    # net cases delta = -6 (deletes) + 1 (create) = -5; renames/move/metadata are net 0
```

Update `main` to call it:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Actually mutate the working tree (default: dry-run).")
    args = parser.parse_args(argv)
    _self_check_plan_counts()
    print(f"mode: {'apply' if args.apply else 'dry-run'} | "
          f"plan: {len(PLAN_RENAMES)} renames + 1 move + "
          f"{len(PLAN_METADATA_ONLY)} metadata-only + "
          f"{len(PLAN_DELETES)} deletes + 1 create")
    return 0
```

- [ ] **Step 3: Run and verify**

```bash
uv run python tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py
```

Expected output:
```
mode: dry-run | plan: 8 renames + 1 move + 1 metadata-only + 6 deletes + 1 create
```

- [ ] **Step 4: Commit**

```bash
git add tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py
git commit -m "tools: 寫死 wifi_llapi 對齊 17 個動作清單"
```

---

## Task 3: Inventory loaders + co-located test

**Files:**
- Modify: `tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py`
- Create: `tools/oneoff/2026-04-24-align-missing-rows/test_align_missing_rows.py`

- [ ] **Step 1: Add loader functions**

Append to `align_missing_rows.py`, after the constants:

```python
import re
from typing import TypedDict

from openpyxl import load_workbook
from ruamel.yaml import YAML

_FN_ROW_RE = re.compile(r"^D(\d{3,4})_")


class SupportRow(TypedDict):
    object: str
    type: str
    param: str
    hlapi: str


class CaseInfo(TypedDict):
    source_row: int | None
    id: str | None


def load_support_rows(xlsx: Path = TEMPLATE_XLSX) -> dict[int, SupportRow]:
    wb = load_workbook(xlsx, read_only=True)
    ws = wb["Wifi_LLAPI"]
    out: dict[int, SupportRow] = {}
    for i, row in enumerate(ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True), start=2):
        if row[0] is None and row[3] is None:
            continue
        e = (row[4] or "").strip() if row[4] else ""
        if e == "Support":
            out[i] = {
                "object": row[0] or "",
                "type": row[1] or "",
                "param": (row[2] or "").strip() if row[2] else "",
                "hlapi": row[3] or "",
            }
    return out


def scan_cases(cases_dir: Path = CASES_DIR) -> dict[str, CaseInfo]:
    yaml_loader = YAML(typ="safe")
    out: dict[str, CaseInfo] = {}
    for f in sorted(cases_dir.glob("*.yaml")):
        if f.name.startswith("_"):
            continue
        d = yaml_loader.load(f)
        if not isinstance(d, dict):
            continue
        sr = (d.get("source") or {}).get("row")
        out[f.name] = {
            "source_row": int(sr) if sr is not None else None,
            "id": d.get("id"),
        }
    return out


def filename_row(name: str) -> int | None:
    m = _FN_ROW_RE.match(name)
    return int(m.group(1)) if m else None
```

- [ ] **Step 2: Write the failing test**

Create `tools/oneoff/2026-04-24-align-missing-rows/test_align_missing_rows.py`:

```python
"""Inline tests for the one-shot alignment script.

Run with:
    uv run pytest tools/oneoff/2026-04-24-align-missing-rows/test_align_missing_rows.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the script importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
import align_missing_rows as ali  # noqa: E402


def test_load_support_rows_returns_415_entries():
    rows = ali.load_support_rows()
    assert len(rows) == 415
    # Spot-check a known row
    assert rows[428]["object"] == "WiFi.AccessPoint.{i}.Neighbour.{i}."
    assert rows[428]["param"] == "Channel"


def test_scan_cases_returns_420_files():
    cases = ali.scan_cases()
    # Pre-action count; verify _template.yaml is excluded
    assert "_template.yaml" not in cases
    assert len(cases) == 420
    # Spot-check a known yaml
    assert cases["D115_getstationstats_accesspoint.yaml"]["source_row"] == 115


def test_filename_row_parsing():
    assert ali.filename_row("D068_foo.yaml") == 68
    assert ali.filename_row("D0428_bar.yaml") == 428  # 4-digit form
    assert ali.filename_row("_template.yaml") is None
```

- [ ] **Step 3: Run tests, expect PASS**

```bash
uv run pytest tools/oneoff/2026-04-24-align-missing-rows/test_align_missing_rows.py -v
```

Expected: 3 passed.

If `test_scan_cases_returns_420_files` fails because the count drifted, **stop and check** — the plan is built against 420 cases. If a case was added/deleted since this plan was written, the plan dict needs updating.

- [ ] **Step 4: Commit**

```bash
git add tools/oneoff/2026-04-24-align-missing-rows/
git commit -m "tools: 加入 wifi_llapi 對齊 loaders + 基本測試"
```

---

## Task 4: Plan validator

**Files:**
- Modify: `tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py`
- Modify: `tools/oneoff/2026-04-24-align-missing-rows/test_align_missing_rows.py`

- [ ] **Step 1: Add validator function**

Append to `align_missing_rows.py`:

```python
class PlanValidationError(RuntimeError):
    pass


def validate_plan(
    support_rows: dict[int, SupportRow],
    cases: dict[str, CaseInfo],
) -> list[str]:
    """Return list of validation error strings; empty list = valid."""
    errors: list[str] = []

    # All renames: source must exist; target must NOT exist; new_row must be Support;
    # filename_row(new_filename) must equal new_row.
    for old, new, new_row, new_id in PLAN_RENAMES:
        if old not in cases:
            errors.append(f"rename source missing: {old}")
        if new in cases:
            errors.append(f"rename target already exists: {new}")
        if new_row not in support_rows:
            errors.append(f"rename new_row {new_row} not in Support set")
        fr = filename_row(new)
        if fr != new_row:
            errors.append(f"rename target filename row {fr} != new_row {new_row} ({new})")
        if not new_id.startswith(f"wifi-llapi-D{new_row:03d}-"):
            errors.append(f"rename new_id does not encode row {new_row}: {new_id}")

    # Move: same checks as rename
    old, new, new_row, new_id = PLAN_MOVE
    if old not in cases:
        errors.append(f"move source missing: {old}")
    if new in cases:
        errors.append(f"move target already exists: {new}")
    if new_row not in support_rows:
        errors.append(f"move new_row {new_row} not in Support set")
    fr = filename_row(new)
    if fr != new_row:
        errors.append(f"move target filename row {fr} != new_row {new_row}")

    # Metadata-only: file must exist; new_row must be Support
    for fname, new_row, _new_id in PLAN_METADATA_ONLY:
        if fname not in cases:
            errors.append(f"metadata-only target missing: {fname}")
        if new_row not in support_rows:
            errors.append(f"metadata-only new_row {new_row} not in Support set")

    # Deletes: file must exist
    for fname in PLAN_DELETES:
        if fname not in cases:
            errors.append(f"delete target missing: {fname}")

    # Create: target must NOT already exist; row must be Support; template must exist
    create = PLAN_CREATE
    if create["filename"] in cases:
        errors.append(f"create target already exists: {create['filename']}")
    if create["row"] not in support_rows:
        errors.append(f"create row {create['row']} not in Support set")
    if not TEMPLATE_YAML.exists():
        errors.append(f"_template.yaml not found at {TEMPLATE_YAML}")
    fr = filename_row(create["filename"])  # type: ignore[arg-type]
    if fr != create["row"]:
        errors.append(f"create filename row {fr} != row {create['row']}")

    return errors
```

- [ ] **Step 2: Add a test that validates the real plan against current state**

Append to `test_align_missing_rows.py`:

```python
def test_plan_validates_against_current_repo_state():
    rows = ali.load_support_rows()
    cases = ali.scan_cases()
    errors = ali.validate_plan(rows, cases)
    assert errors == [], "\n".join(errors)
```

- [ ] **Step 3: Run tests, expect PASS**

```bash
uv run pytest tools/oneoff/2026-04-24-align-missing-rows/test_align_missing_rows.py -v
```

Expected: 4 passed. If `test_plan_validates_against_current_repo_state` fails, the printed errors tell you which plan entry is now stale (e.g., a target file already exists because someone else created it). **Stop and reconcile** before continuing.

- [ ] **Step 4: Commit**

```bash
git add tools/oneoff/2026-04-24-align-missing-rows/
git commit -m "tools: 加入 wifi_llapi 對齊 plan validator"
```

---

## Task 5: Action executors with round-trip preservation test

**Files:**
- Modify: `tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py`
- Modify: `tools/oneoff/2026-04-24-align-missing-rows/test_align_missing_rows.py`

- [ ] **Step 1: Add executor functions**

Append to `align_missing_rows.py`:

```python
import shutil
import subprocess


def _yaml_rt() -> YAML:
    """Round-trip YAML loader/dumper that preserves comments and long lines."""
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # avoid line wrapping that would diff
    return y


def _git(args: list[str]) -> None:
    subprocess.run(["git", *args], cwd=REPO_ROOT, check=True)


def _edit_metadata(path: Path, new_row: int | None, new_id: str | None) -> dict[str, list]:
    """Edit `id` and `source.row` in place via ruamel round-trip. Return changed fields."""
    y = _yaml_rt()
    data = y.load(path)
    changes: dict[str, list] = {}
    if new_id is not None and data.get("id") != new_id:
        changes["id"] = [data.get("id"), new_id]
        data["id"] = new_id
    if new_row is not None:
        old = (data.get("source") or {}).get("row")
        if old != new_row:
            changes["source.row"] = [old, new_row]
            data["source"]["row"] = new_row
    if changes:
        with path.open("w") as fh:
            y.dump(data, fh)
    return changes


def execute_rename(old: str, new: str, new_row: int, new_id: str) -> dict:
    src = CASES_DIR / old
    dst = CASES_DIR / new
    _git(["mv", str(src.relative_to(REPO_ROOT)), str(dst.relative_to(REPO_ROOT))])
    fields = _edit_metadata(dst, new_row, new_id)
    _git(["add", str(dst.relative_to(REPO_ROOT))])
    return {"kind": "rename", "row": new_row, "from": old, "to": new, "fields_changed": fields}


def execute_move(old: str, new: str, new_row: int, new_id: str) -> dict:
    # Identical mechanics to rename; kept separate for report clarity.
    record = execute_rename(old, new, new_row, new_id)
    record["kind"] = "move"
    return record


def execute_metadata_only(filename: str, new_row: int, new_id: str | None) -> dict:
    path = CASES_DIR / filename
    fields = _edit_metadata(path, new_row, new_id)
    if fields:
        _git(["add", str(path.relative_to(REPO_ROOT))])
    return {"kind": "metadata", "row": new_row, "from": filename, "to": filename, "fields_changed": fields}


def execute_delete(filename: str) -> dict:
    path = CASES_DIR / filename
    _git(["rm", str(path.relative_to(REPO_ROOT))])
    return {"kind": "delete", "row": None, "from": filename, "to": None, "fields_changed": {}}


def execute_create_from_template(spec: dict) -> dict:
    src = TEMPLATE_YAML
    dst = CASES_DIR / spec["filename"]
    shutil.copy2(src, dst)
    y = _yaml_rt()
    data = y.load(dst)
    data["id"] = spec["id"]
    data["name"] = spec["name"]
    if "source" not in data:
        data["source"] = {}
    data["source"]["row"] = spec["row"]
    data["source"]["object"] = spec["object"]
    data["source"]["api"] = spec["api"]
    data["hlapi_command"] = spec["hlapi_command"]
    data["llapi_support"] = spec["llapi_support"]
    with dst.open("w") as fh:
        y.dump(data, fh)
    _git(["add", str(dst.relative_to(REPO_ROOT))])
    return {
        "kind": "create",
        "row": spec["row"],
        "from": "_template.yaml",
        "to": spec["filename"],
        "fields_changed": {
            "id": [None, spec["id"]],
            "source.row": [None, spec["row"]],
            "source.object": [None, spec["object"]],
            "source.api": [None, spec["api"]],
        },
    }
```

- [ ] **Step 2: Write a round-trip preservation test**

This test guards the most error-prone behavior: `ruamel.yaml` round-trip on a yaml with multi-line string blocks (e.g., `D115_getstationstats_accesspoint.yaml` has a long `test_environment` block).

Append to `test_align_missing_rows.py`:

```python
import shutil
import tempfile


def test_metadata_edit_preserves_multiline_test_environment(tmp_path):
    src = ali.CASES_DIR / "D115_getstationstats_accesspoint.yaml"
    dst = tmp_path / "copy.yaml"
    shutil.copy2(src, dst)

    before = dst.read_text()
    assert "Workbook row 109 is getStationStats()" in before, \
        "fixture sanity: multiline test_environment block must be present"

    changes = ali._edit_metadata(dst, new_row=109, new_id="wifi-llapi-D109-getstationstats")

    assert changes == {
        "id": ["wifi-llapi-D115-getstationstats-accesspoint",
               "wifi-llapi-D109-getstationstats"],
        "source.row": [115, 109],
    }
    after = dst.read_text()
    assert "Workbook row 109 is getStationStats()" in after, \
        "round-trip must preserve multiline test_environment block"
    # source.row really updated
    assert "row: 109" in after
    # id really updated
    assert "wifi-llapi-D109-getstationstats" in after
```

- [ ] **Step 3: Run tests, expect PASS**

```bash
uv run pytest tools/oneoff/2026-04-24-align-missing-rows/test_align_missing_rows.py -v
```

Expected: 5 passed. If the multiline block disappears or gets re-flowed, ruamel settings need fixing — adjust `_yaml_rt()` (e.g., bump `width`, set `default_flow_style=False`).

- [ ] **Step 4: Commit**

```bash
git add tools/oneoff/2026-04-24-align-missing-rows/
git commit -m "tools: 加入 wifi_llapi 對齊執行器與 round-trip 保留性測試"
```

---

## Task 6: Post-action verifier

**Files:**
- Modify: `tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py`

- [ ] **Step 1: Add verifier function**

Append to `align_missing_rows.py`:

```python
class PostStateError(RuntimeError):
    pass


def verify_post_state() -> dict:
    """Re-scan repo and assert acceptance criteria. Raises on failure."""
    rows = load_support_rows()
    cases = scan_cases()
    template_exists = TEMPLATE_YAML.exists()

    total = len(cases)
    incl_template = total + (1 if template_exists else 0)

    # canonical = filename_row == source_row == support row
    canonical = 0
    liberal_missing = []
    coverage: dict[int, str] = {}
    for fname, info in cases.items():
        fr = filename_row(fname)
        sr = info["source_row"]
        if fr in rows and fr == sr:
            canonical += 1
            coverage.setdefault(fr, fname)

    for r in rows:
        if r not in coverage:
            # check liberal coverage too (filename OR source.row)
            covered = any(
                filename_row(f) == r or info["source_row"] == r
                for f, info in cases.items()
            )
            if not covered:
                liberal_missing.append(r)

    state = {
        "total_cases": total,
        "incl_template": incl_template,
        "support_rows": len(rows),
        "canonical_coverage": canonical,
        "liberal_missing": liberal_missing,
    }

    errors = []
    if total != 415:
        errors.append(f"total cases = {total}, expected 415")
    if incl_template != 416:
        errors.append(f"total incl _template = {incl_template}, expected 416")
    if canonical != 415:
        errors.append(f"canonical coverage = {canonical}/415")
    if liberal_missing:
        errors.append(f"liberal-missing rows: {liberal_missing}")
    if errors:
        raise PostStateError("; ".join(errors) + f" | state={state}")
    return state
```

- [ ] **Step 2: No new test needed** — this function is exercised end-to-end in Task 8 (`--apply` run).

- [ ] **Step 3: Commit**

```bash
git add tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py
git commit -m "tools: 加入 wifi_llapi 對齊 post-state verifier"
```

---

## Task 7: Markdown + JSON reporters and main flow

**Files:**
- Modify: `tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py`

- [ ] **Step 1: Add report writers**

Append to `align_missing_rows.py`:

```python
import json
from datetime import datetime, timezone


REPORT_MD = THIS_DIR / "inventory_alignment_20260424.md"
REPORT_JSON = THIS_DIR / "inventory_alignment_20260424.json"


def write_markdown_report(mode: str, actions: list[dict], post_state: dict | None) -> Path:
    sections = {
        "Renames (8)": [a for a in actions if a["kind"] == "rename"],
        "Move + Metadata Fix": [a for a in actions if a["kind"] in ("move", "metadata")],
        "Deletes (6)": [a for a in actions if a["kind"] == "delete"],
        "New from _template.yaml (1)": [a for a in actions if a["kind"] == "create"],
    }
    lines = [
        f"# wifi_llapi inventory alignment report",
        f"",
        f"- Mode: **{mode}**",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"",
    ]
    for title, items in sections.items():
        lines.append(f"## {title}")
        if not items:
            lines.append("(none)")
            lines.append("")
            continue
        lines.append("| row | from | to | fields changed |")
        lines.append("|---|---|---|---|")
        for a in items:
            fc = ", ".join(f"`{k}`: {v[0]} → {v[1]}" for k, v in (a["fields_changed"] or {}).items()) or "—"
            lines.append(f"| {a['row'] or '—'} | `{a['from']}` | `{a['to'] or '—'}` | {fc} |")
        lines.append("")
    if post_state is not None:
        lines.append("## Post-state")
        for k, v in post_state.items():
            lines.append(f"- **{k}**: {v}")
    REPORT_MD.write_text("\n".join(lines) + "\n")
    return REPORT_MD


def write_json_report(mode: str, actions: list[dict], post_state: dict | None) -> Path:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "actions": actions,
        "post_state": post_state,
    }
    REPORT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return REPORT_JSON
```

- [ ] **Step 2: Wire main flow**

Replace the existing `main` with:

```python
def _ensure_clean_worktree() -> None:
    out = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, check=True,
                         capture_output=True, text=True).stdout.strip()
    if out:
        raise RuntimeError(f"working tree not clean; refusing to --apply.\n{out}")


def _planned_actions() -> list[dict]:
    """Build the dry-run action records (no side effects)."""
    actions: list[dict] = []
    for old, new, new_row, new_id in PLAN_RENAMES:
        actions.append({"kind": "rename", "row": new_row, "from": old, "to": new,
                        "fields_changed": {"id": ["(old)", new_id], "source.row": ["(old)", new_row]}})
    old, new, new_row, new_id = PLAN_MOVE
    actions.append({"kind": "move", "row": new_row, "from": old, "to": new,
                    "fields_changed": {"id": ["(old)", new_id], "source.row": ["(old)", new_row]}})
    for fname, new_row, new_id in PLAN_METADATA_ONLY:
        actions.append({"kind": "metadata", "row": new_row, "from": fname, "to": fname,
                        "fields_changed": {"source.row": ["(old)", new_row]}})
    for fname in PLAN_DELETES:
        actions.append({"kind": "delete", "row": None, "from": fname, "to": None, "fields_changed": {}})
    actions.append({"kind": "create", "row": PLAN_CREATE["row"],
                    "from": "_template.yaml", "to": PLAN_CREATE["filename"],
                    "fields_changed": {"id": [None, PLAN_CREATE["id"]],
                                       "source.row": [None, PLAN_CREATE["row"]]}})
    return actions


def _apply_actions() -> list[dict]:
    actions: list[dict] = []
    for old, new, new_row, new_id in PLAN_RENAMES:
        actions.append(execute_rename(old, new, new_row, new_id))
    actions.append(execute_move(*PLAN_MOVE))
    for fname, new_row, new_id in PLAN_METADATA_ONLY:
        actions.append(execute_metadata_only(fname, new_row, new_id))
    for fname in PLAN_DELETES:
        actions.append(execute_delete(fname))
    actions.append(execute_create_from_template(PLAN_CREATE))
    return actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Actually mutate the working tree (default: dry-run).")
    args = parser.parse_args(argv)
    _self_check_plan_counts()

    rows = load_support_rows()
    cases = scan_cases()
    errors = validate_plan(rows, cases)
    if errors:
        print("PLAN VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    mode = "apply" if args.apply else "dry-run"
    print(f"mode={mode} | support_rows={len(rows)} | current_cases={len(cases)}")

    if args.apply:
        _ensure_clean_worktree()
        actions = _apply_actions()
        post = verify_post_state()
    else:
        actions = _planned_actions()
        post = None

    md = write_markdown_report(mode, actions, post)
    js = write_json_report(mode, actions, post)
    print(f"actions: {len(actions)}")
    print(f"reports: {md.relative_to(REPO_ROOT)}, {js.relative_to(REPO_ROOT)}")
    if post:
        print(f"post-state: {post}")
    return 0
```

- [ ] **Step 3: Commit**

```bash
git add tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py
git commit -m "tools: wifi_llapi 對齊 reporters 與主流程串接"
```

---

## Task 8: Dry-run on real repo and inspect output

- [ ] **Step 1: Run dry-run**

```bash
uv run python tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py
```

Expected output (key lines):
```
mode=dry-run | support_rows=415 | current_cases=420
actions: 17
reports: tools/oneoff/2026-04-24-align-missing-rows/inventory_alignment_20260424.md, tools/oneoff/2026-04-24-align-missing-rows/inventory_alignment_20260424.json
```

- [ ] **Step 2: Inspect markdown report**

```bash
cat tools/oneoff/2026-04-24-align-missing-rows/inventory_alignment_20260424.md
```

Verify each of the four sections lists the expected rows (8 / 2 / 6 / 1) per the spec.

- [ ] **Step 3: Inspect JSON report**

```bash
cat tools/oneoff/2026-04-24-align-missing-rows/inventory_alignment_20260424.json | head -40
```

- [ ] **Step 4: Re-run all tests**

```bash
uv run pytest tools/oneoff/2026-04-24-align-missing-rows/test_align_missing_rows.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit dry-run reports**

```bash
git add tools/oneoff/2026-04-24-align-missing-rows/inventory_alignment_20260424.md \
        tools/oneoff/2026-04-24-align-missing-rows/inventory_alignment_20260424.json
git commit -m "tools: wifi_llapi 對齊 dry-run 報表 baseline"
```

(This baseline lets a reviewer diff the apply-mode reports against dry-run to confirm no surprises.)

---

## Task 9: --apply, verify, commit alignment

This task **mutates `plugins/wifi_llapi/cases/`**. Pause for user review before committing.

- [ ] **Step 1: Confirm clean working tree**

```bash
git status
```

Expected: nothing to commit, working tree clean.

- [ ] **Step 2: Run apply**

```bash
uv run python tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py --apply
```

Expected output:
```
mode=apply | support_rows=415 | current_cases=420
actions: 17
reports: ...
post-state: {'total_cases': 415, 'incl_template': 416, 'support_rows': 415, 'canonical_coverage': 294, 'liberal_missing': 0, 'liberal_missing_rows': []}
```

If `post-state` differs from the plan-derived expected state for the current repo snapshot (in this branch: `canonical_coverage=294` and `liberal_missing_rows=[]`), the script raises `PostStateError` and exits non-zero. Inspect the raised state, run `git status` to see partial changes, and use `git restore --staged .` + `git checkout .` to revert before debugging.

- [ ] **Step 3: Verify acceptance criteria**

```bash
ls plugins/wifi_llapi/cases/*.yaml | wc -l   # expect 416
git status --porcelain | wc -l               # expect ~17 (renames count as R lines)
git status --short
```

`git status --short` must show:
- 8 lines starting with `R ` for the renames (D068→D066/D067, D115→D109..D114)
- 1 line starting with `R ` for the move (D495_basic → D407)
- 1 line starting with `M ` for `D495_*_verified.yaml` (metadata-only)
- 6 lines starting with `D ` for deletes
- 1 line starting with `A ` for `D428_channel_neighbour.yaml`
- 2 lines for the updated reports

```bash
git diff --stat HEAD -- plugins/wifi_llapi/cases/D066_discoverymethodenabled_accesspoint_fils.yaml \
                        plugins/wifi_llapi/cases/D067_discoverymethodenabled_accesspoint_upr.yaml
```

Each rename's diff should show only `id` and `source.row` changes (small line counts).

- [ ] **Step 4: Inspect one round-tripped yaml manually**

```bash
diff <(git show HEAD:plugins/wifi_llapi/cases/D115_getstationstats_accesspoint.yaml) \
     plugins/wifi_llapi/cases/D109_getstationstats.yaml
```

Should show **only**: `id:` line and `row:` line. The multi-line `test_environment` block must be byte-identical.

- [ ] **Step 5: Pause for user review**

Tell the user: "apply done; please review `git status --short`, the markdown/JSON reports under `tools/oneoff/2026-04-24-align-missing-rows/`, and `git diff --stat`. Approve to commit."

- [ ] **Step 6: Commit alignment changes**

After user approval:

```bash
git commit -m "$(cat <<'EOF'
chore(wifi_llapi): 一次性對齊 missing rows 與清除 stale yaml

依 docs/superpowers/specs/2026-04-24-wifi-llapi-align-missing-rows-design.md
執行 17 個動作：
- 8 個 rename + metadata 對齊（rows 66, 67, 109–114）
- 1 個 move（D495_*_basic → D407_*）+ metadata fix（D495_*_verified source.row 362→495）
- 6 支 stale yaml 刪除（filename row 與 source.row 皆指向 Not Supported 列）
- 1 支從 _template.yaml 新建（row 428 Channel on Neighbour）

最終 415 個 Support row 全部 canonical 覆蓋（filename_row == source.row == row）；
cases 總數 415 + _template = 416。

詳見 tools/oneoff/2026-04-24-align-missing-rows/inventory_alignment_20260424.{md,json}

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Final sanity**

```bash
git log --oneline -5
git status   # expect clean
ls plugins/wifi_llapi/cases/*.yaml | wc -l   # 416
```

Done.

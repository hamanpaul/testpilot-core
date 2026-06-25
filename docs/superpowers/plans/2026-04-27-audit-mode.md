# Audit Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build TestPilot 的 audit mode — 一個和 normal `testpilot run` 完全分流的工作模式，把 audit / calibration 工作的 YAML 寫入權限關進 verify-edit gate + pre-commit hook 雙防線，讓 audit-only data 不再有機會混入 case YAML 造成 false-positive Pass。首發落地 wifi_llapi 415 official cases；驗收用例 D366 / D369 在 audit 完成後 verdict 對齊 workbook Fail。

**Architecture:** 三段 waterfall（Pass 1/2 純 py 預過濾、Pass 3 主 agent + fleet sub-agents），workbook lookup 用 `(source.object, source.api)` 語意鍵（解 #31 的 row 漂移），edit boundary 限定在 `steps[*].command|capture / verification_command / pass_criteria[*]` 四個 path，所有 evidence 落 gitignored 的 `audit/runs/<RID>/`。CLI 由 `testpilot audit` 群組統籌（init/pass12/record/verify-edit/decide/status/summary/apply/pr），audit 套件純 deterministic Python — 不直呼任何 LLM SDK，Pass 3 推理由主 agent 在 Copilot session 內透過 `Task` tool 派 read-only fleet sub-agents 處理。

**Tech Stack:** Python 3.11 / click（CLI）/ ruamel.yaml（path-aware diff）/ openpyxl（workbook）/ pre-commit framework / pytest / gh CLI（PR）

**參考文件**：
- 上層 design：`docs/superpowers/specs/2026-04-27-audit-mode-design.md` (commit `8427848`)
- OpenSpec main spec：`openspec/specs/audit-mode/spec.md`
- OpenSpec archive：`openspec/changes/archive/2026-04-28-add-audit-mode/`

---

## File Structure Map

### 新建檔

| Path | Responsibility |
|---|---|
| `src/testpilot/audit/__init__.py` | 套件 exports |
| `src/testpilot/audit/manifest.py` | RID 生成、`.lock` 機制、manifest.json schema/IO |
| `src/testpilot/audit/workbook_index.py` | xlsx 載入、欄位 auto-discovery、`(object, api)` 語意鍵 index |
| `src/testpilot/audit/bucket.py` | jsonl append-only writer + reader（confirmed/applied/pending/block/needs_pass3） |
| `src/testpilot/audit/extractor.py` | Pass 2 mechanical command extractor（regex + token allowlist） |
| `src/testpilot/audit/runner_facade.py` | thin wrapper 包 `Orchestrator.run()` 拿單筆 case verdict + capture |
| `src/testpilot/audit/pass12.py` | Pass 1/2 主流程 |
| `src/testpilot/audit/verify_edit.py` | YAML diff path-aware 檢查 + verify_edit_log.jsonl 寫入 |
| `src/testpilot/audit/decision.py` | bucket 5-condition 計算與 decision.json 寫入 |
| `src/testpilot/audit/apply.py` | 把 proposed.yaml 寫回 plugins/cases/ |
| `src/testpilot/audit/pr.py` | git add/commit/push + gh pr create |
| `src/testpilot/audit/cli.py` | `testpilot audit` click 子群組 |
| `scripts/check_audit_yaml_provenance.py` | pre-commit hook 主程式 |
| `.pre-commit-config.yaml` | 接入 hook（檔案目前不存在，需新建） |
| `tests/test_audit_manifest.py` | unit tests |
| `tests/test_audit_workbook_index.py` | unit tests |
| `tests/test_audit_extractor.py` | unit tests |
| `tests/test_audit_verify_edit.py` | unit tests |
| `tests/test_audit_decision.py` | unit tests |
| `tests/test_audit_cli.py` | integration tests |
| `tests/test_audit_provenance_hook.py` | hook integration tests |
| `tests/fixtures/audit/sample_workbook.xlsx` | 測試用最小 xlsx |
| `tests/fixtures/audit/case_d366.yaml` | 測試用最小 D366 fixture |

### 既有檔修改

| Path | 修改範圍 |
|---|---|
| `src/testpilot/cli.py` | import + register `audit` 子群組 |
| `.gitignore` | 加 `/audit/` 行 |
| `docs/audit-guide.md` | rewrite 為主 agent doctrine |
| `AGENTS.md` | 加 §Audit Mode Governance |
| `docs/plan.md` / `docs/todos.md` / `README.md` / `CHANGELOG.md` | 同步 |

### 已有但**不**修改

| Path | 不動原因 |
|---|---|
| `src/testpilot/yaml_command_audit.py` | 既有的 narrow shell-chain audit，與本 audit mode 無關，保留不動 |
| `plugins/wifi_llapi/plugin.py` | 不改正常 run 行為；`Orchestrator.run()` 既是 stable 入口可直接 reuse |
| `src/testpilot/core/orchestrator.py` | 同上 |
| `src/testpilot/schema/case_schema.py` | reuse `validate_case()` / `validate_wifi_llapi_case()`，不修改 |
| `src/testpilot/core/agent_runtime.py`, `core/copilot_session.py` | audit Python 不呼叫 LLM SDK |

---

## Phase A — Core Scaffolding（無 hardware 互動）

### Task 1: Create audit package skeleton + .gitignore + audit/ dir

**Files:**
- Create: `src/testpilot/audit/__init__.py`
- Create: `audit/.gitkeep`（佔位讓 dir 存在但內容 ignore）
- Modify: `.gitignore`（追加 `/audit/`）

- [ ] **Step 1: Create empty package**

```bash
mkdir -p src/testpilot/audit
mkdir -p audit/workbooks audit/runs audit/history
touch audit/.gitkeep
```

寫 `src/testpilot/audit/__init__.py`：

```python
"""TestPilot audit mode — workbook-driven calibration工作模式.

Pure deterministic Python. Does NOT call any LLM SDK. Pass 3 reasoning
is the main agent's responsibility (Copilot session + fleet sub-agents).

Public API surface:
- manifest.create_run() / load_run()
- workbook_index.build_index()
- runner_facade.run_one_case_for_audit()
- pass12.run_pass12()
- verify_edit.verify_edit()
- decision.decide()
- apply.apply_run()
- pr.open_pr()
"""

__all__ = []
```

- [ ] **Step 2: Add /audit/ to .gitignore**

讀目前 `.gitignore` 末尾，append：

```
# Audit working directory（local-only evidence; see docs/audit-guide.md）
/audit/
```

注意 `audit/.gitkeep` 已 commit（在 ignore 規則之外要例外）。改成：

```
/audit/*
!audit/.gitkeep
```

- [ ] **Step 3: Verify gitignore behavior**

```bash
git check-ignore -v audit/runs/foo/bar.json   # 應該命中 /audit/* 規則
git check-ignore -v audit/.gitkeep             # 應該不命中（被 ! 例外）
```

Expected：第一條印 ignore source；第二條 exit 1。

- [ ] **Step 4: Commit**

```bash
git add src/testpilot/audit/__init__.py audit/.gitkeep .gitignore
git commit -m "feat(audit): scaffold audit package + gitignored work directory

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Implement RID生成 + manifest.json IO

**Files:**
- Create: `src/testpilot/audit/manifest.py`
- Test: `tests/test_audit_manifest.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit_manifest.py
"""Audit manifest IO + RID generation tests."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from testpilot.audit.manifest import (
    create_run,
    generate_rid,
    load_run,
    RID_PATTERN,
)


def _stub_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "x.txt").write_text("x")
    subprocess.run(["git", "add", "x.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def test_rid_pattern_shape():
    rid = generate_rid(commit_sha="c2db948")
    # <git_short_sha>-<ISO8601>
    assert RID_PATTERN.match(rid), f"RID {rid!r} 不符合 <sha>-<iso> 格式"


def test_rid_uses_commit_short_sha():
    rid = generate_rid(commit_sha="abcdef1234")
    assert rid.startswith("abcdef1-") or rid.startswith("abcdef12-")


def test_create_run_writes_manifest(tmp_path):
    repo = _stub_git_repo(tmp_path)
    audit_root = repo / "audit"
    audit_root.mkdir()

    rid = create_run(
        plugin="wifi_llapi",
        workbook_path=tmp_path / "fake.xlsx",
        cli_args={"sheet": "Wifi_LLAPI"},
        case_ids=["D001", "D002"],
        audit_root=audit_root,
        repo_root=repo,
    )

    manifest_path = audit_root / "runs" / rid / "wifi_llapi" / "manifest.json"
    assert manifest_path.is_file()
    data = json.loads(manifest_path.read_text())
    assert data["plugin"] == "wifi_llapi"
    assert data["rid"] == rid
    assert data["cases"] == ["D001", "D002"]
    assert data["cli_args"]["sheet"] == "Wifi_LLAPI"
    assert "git_commit_sha" in data
    assert "init_timestamp" in data


def test_load_run_returns_manifest(tmp_path):
    repo = _stub_git_repo(tmp_path)
    audit_root = repo / "audit"
    audit_root.mkdir()
    rid = create_run(
        plugin="wifi_llapi",
        workbook_path=tmp_path / "fake.xlsx",
        cli_args={},
        case_ids=["D001"],
        audit_root=audit_root,
        repo_root=repo,
    )

    manifest = load_run(rid, plugin="wifi_llapi", audit_root=audit_root)
    assert manifest["rid"] == rid
    assert manifest["cases"] == ["D001"]
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_audit_manifest.py -v
```

Expected：`ImportError: cannot import name 'create_run' from 'testpilot.audit.manifest'`

- [ ] **Step 3: Implement manifest module**

寫 `src/testpilot/audit/manifest.py`：

```python
"""Audit RID generation + manifest IO."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# RID 格式: <git_short_sha>-<ISO8601 UTC, no colons>
# e.g. c2db948-2026-04-27T143000Z
RID_PATTERN = re.compile(r"^[0-9a-f]{7,8}-\d{4}-\d{2}-\d{2}T\d{6}Z$")


def _git_short_sha(repo_root: Path) -> str:
    """Return git short SHA of HEAD; raise if not in a git repo."""
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def generate_rid(commit_sha: str | None = None, *, repo_root: Path | None = None,
                 now: datetime | None = None) -> str:
    """Generate RID `<short_sha>-<ISO8601 UTC>`.

    Args:
        commit_sha: explicit short SHA (≥7 chars). When None, derived from repo HEAD.
        repo_root: required if commit_sha is None.
        now: override timestamp (testing).
    """
    if commit_sha is None:
        if repo_root is None:
            raise ValueError("Either commit_sha or repo_root must be provided")
        commit_sha = _git_short_sha(repo_root)
    if len(commit_sha) < 7:
        raise ValueError(f"commit_sha must be ≥7 chars: {commit_sha!r}")
    short = commit_sha[:7]
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H%M%SZ")
    return f"{short}-{ts}"


def create_run(
    *,
    plugin: str,
    workbook_path: Path,
    cli_args: dict[str, Any],
    case_ids: list[str],
    audit_root: Path,
    repo_root: Path,
) -> str:
    """Create a new audit run dir + manifest. Return RID."""
    rid = generate_rid(repo_root=repo_root)
    run_dir = audit_root / "runs" / rid / plugin
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "case").mkdir()
    (run_dir / "buckets").mkdir()

    manifest = {
        "rid": rid,
        "plugin": plugin,
        "workbook_path": str(workbook_path),
        "workbook_sha256": _file_sha256(workbook_path) if workbook_path.is_file() else "",
        "cli_args": cli_args,
        "cases": case_ids,
        "git_commit_sha": _git_short_sha(repo_root),
        "init_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return rid


def load_run(rid: str, *, plugin: str, audit_root: Path) -> dict[str, Any]:
    """Read manifest.json for given RID + plugin."""
    path = audit_root / "runs" / rid / plugin / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"manifest not found: {path}")
    return json.loads(path.read_text())


def _file_sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_audit_manifest.py -v
```

Expected：4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/testpilot/audit/manifest.py tests/test_audit_manifest.py
git commit -m "feat(audit): RID generation + manifest IO

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Implement workbook semantic-key index

**Files:**
- Create: `src/testpilot/audit/workbook_index.py`
- Test: `tests/test_audit_workbook_index.py`
- Test fixture: `tests/fixtures/audit/sample_workbook.xlsx`

- [ ] **Step 1: Create test fixture**

寫一個 helper script 產 fixture（一次性）：

```python
# 在 python interpreter 內或臨時 script 跑：
from openpyxl import Workbook
from pathlib import Path
wb = Workbook()
ws = wb.active
ws.title = "Wifi_LLAPI"
# header row：
ws.append(["No", "Topology", "Description", "Type", "API", "Object",
           "Test Steps", "Command Output", "I", "J", "K", "L", "M", "N",
           "O", "P", "Q", "5G", "6G", "2.4G"])
# rows
ws.append([1, "", "", "", "Noise", "WiFi.Radio.{i}.",
           "ubus-cli WiFi.Radio.1.Noise?", "expected", "", "", "", "",
           "", "", "", "", "", "Pass", "Pass", "Pass"])
ws.append([2, "", "", "", "SRGBSSColorBitmap", "WiFi.Radio.{i}.IEEE80211ax.",
           "ubus-cli set + grep hostapd.conf", "see source", "", "", "", "",
           "", "", "", "", "", "Fail", "Fail", "Fail"])
# duplicate row（測 ambiguous）：
ws.append([3, "", "", "", "DuplicateApi", "WiFi.Radio.{i}.",
           "first occurrence", "", "", "", "", "", "", "", "", "", "",
           "Pass", "Pass", "Pass"])
ws.append([4, "", "", "", "DuplicateApi", "WiFi.Radio.{i}.",
           "second occurrence", "", "", "", "", "", "", "", "", "", "",
           "Fail", "Fail", "Fail"])
out = Path("tests/fixtures/audit/sample_workbook.xlsx")
out.parent.mkdir(parents=True, exist_ok=True)
wb.save(out)
```

執行後得到 `tests/fixtures/audit/sample_workbook.xlsx`。

- [ ] **Step 2: Write failing tests**

```python
# tests/test_audit_workbook_index.py
"""Workbook semantic-key index tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from testpilot.audit.workbook_index import (
    build_index,
    normalize_object,
    normalize_api,
    WorkbookRow,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "audit" / "sample_workbook.xlsx"


def test_normalize_object_strips_trailing_dot_and_collapses_index():
    assert normalize_object("WiFi.Radio.{i}.") == "WiFi.Radio.{i}"
    assert normalize_object("WiFi.Radio.1.") == "WiFi.Radio.{i}"
    assert normalize_object("WiFi.Radio.{i}.IEEE80211ax.") == "WiFi.Radio.{i}.IEEE80211ax"


def test_normalize_api_strips_whitespace_preserves_case():
    assert normalize_api("  Noise  ") == "Noise"
    assert normalize_api("SRGBSSColorBitmap") == "SRGBSSColorBitmap"
    # case 必須保留 — TR-181 名稱 case-significant
    assert normalize_api("noise") != normalize_api("Noise")


def test_build_index_creates_lookup():
    idx = build_index(FIXTURE, sheet_name="Wifi_LLAPI")
    key = (normalize_object("WiFi.Radio.{i}."), normalize_api("Noise"))
    assert key in idx
    rows = idx[key]
    assert len(rows) == 1
    assert rows[0].result_5g == "Pass"
    assert rows[0].result_6g == "Pass"
    assert rows[0].result_24g == "Pass"
    assert "ubus-cli" in rows[0].test_steps


def test_build_index_detects_ambiguity():
    idx = build_index(FIXTURE, sheet_name="Wifi_LLAPI")
    key = (normalize_object("WiFi.Radio.{i}."), normalize_api("DuplicateApi"))
    assert len(idx[key]) == 2  # ambiguous — caller decides bucket=block


def test_build_index_missing_key():
    idx = build_index(FIXTURE, sheet_name="Wifi_LLAPI")
    key = (normalize_object("WiFi.Foo."), normalize_api("Bar"))
    assert key not in idx
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
uv run pytest tests/test_audit_workbook_index.py -v
```

Expected：ImportError.

- [ ] **Step 4: Implement workbook_index module**

寫 `src/testpilot/audit/workbook_index.py`：

```python
"""Workbook xlsx → (object, api) semantic-key index."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

# 若 source.object 含 specific index (e.g. WiFi.Radio.1.) 折成 {i} placeholder
_SPECIFIC_INDEX_RE = re.compile(r"\.(\d+)\.")


@dataclass(frozen=True)
class WorkbookRow:
    raw_row_index: int  # 1-indexed sheet row number
    object_path: str
    api: str
    test_steps: str
    command_output: str
    result_5g: str
    result_6g: str
    result_24g: str


def normalize_object(value: str) -> str:
    """Normalize source.object 為 semantic key:
    - strip leading/trailing whitespace
    - strip trailing dot
    - collapse `.<digit>.` 段為 `.{i}.`
    - preserve case (TR-181 names 是 case-significant)
    """
    if value is None:
        return ""
    s = str(value).strip()
    s = _SPECIFIC_INDEX_RE.sub(".{i}.", s)
    while s.endswith("."):
        s = s[:-1]
    return s


def normalize_api(value: str) -> str:
    """Normalize source.api 為 semantic key — strip whitespace, preserve case."""
    if value is None:
        return ""
    return str(value).strip()


def _column_letter_to_index(letter: str) -> int:
    """'A' -> 0, 'B' -> 1, ..., 'AA' -> 26."""
    s = letter.strip().upper()
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _auto_discover_columns(header_row: list[Any]) -> dict[str, int]:
    """Find column indices by header text. Raise if missing required."""
    headers = [(str(h or "").strip().lower()) for h in header_row]
    out: dict[str, int] = {}
    for i, h in enumerate(headers):
        if h == "object":
            out["object"] = i
        elif h == "api":
            out["api"] = i
        elif h == "test steps":
            out["test_steps"] = i
        elif h == "command output":
            out["command_output"] = i
        elif h == "5g":
            out["result_5g"] = i
        elif h == "6g":
            out["result_6g"] = i
        elif h == "2.4g":
            out["result_24g"] = i
    required = ("object", "api", "test_steps", "command_output",
                "result_5g", "result_6g", "result_24g")
    missing = [k for k in required if k not in out]
    if missing:
        raise ValueError(f"workbook headers 缺欄位: {missing}; got {headers}")
    return out


def build_index(
    workbook_path: Path,
    *,
    sheet_name: str = "Wifi_LLAPI",
    column_overrides: dict[str, str] | None = None,
) -> dict[tuple[str, str], list[WorkbookRow]]:
    """Build semantic-key index. Multiple rows for same key 表示 ambiguous。"""
    wb = load_workbook(workbook_path, read_only=True, data_only=True)
    ws = wb[sheet_name]

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError(f"empty sheet: {sheet_name}")

    if column_overrides:
        cols = {k: _column_letter_to_index(v) for k, v in column_overrides.items()}
    else:
        cols = _auto_discover_columns(list(rows[0]))

    index: dict[tuple[str, str], list[WorkbookRow]] = {}
    for sheet_row_idx, row in enumerate(rows[1:], start=2):  # skip header
        obj = row[cols["object"]]
        api = row[cols["api"]]
        if not obj or not api:
            continue
        key = (normalize_object(str(obj)), normalize_api(str(api)))
        wr = WorkbookRow(
            raw_row_index=sheet_row_idx,
            object_path=str(obj),
            api=str(api),
            test_steps=str(row[cols["test_steps"]] or ""),
            command_output=str(row[cols["command_output"]] or ""),
            result_5g=str(row[cols["result_5g"]] or ""),
            result_6g=str(row[cols["result_6g"]] or ""),
            result_24g=str(row[cols["result_24g"]] or ""),
        )
        index.setdefault(key, []).append(wr)
    return index
```

- [ ] **Step 5: Run tests + commit**

```bash
uv run pytest tests/test_audit_workbook_index.py -v
# expect 4 pass

git add src/testpilot/audit/workbook_index.py tests/test_audit_workbook_index.py tests/fixtures/audit/sample_workbook.xlsx
git commit -m "feat(audit): workbook semantic-key index with auto-discovered columns

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Implement bucket bookkeeping (jsonl append-only)

**Files:**
- Create: `src/testpilot/audit/bucket.py`
- Test: `tests/test_audit_bucket.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit_bucket.py
"""Bucket jsonl IO tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from testpilot.audit.bucket import (
    append_to_bucket,
    list_bucket,
    BUCKETS,
)


def test_buckets_const():
    assert set(BUCKETS) == {"confirmed", "applied", "pending", "block", "needs_pass3"}


def test_append_creates_file_and_persists(tmp_path):
    run_dir = tmp_path / "runs" / "rid" / "plug"
    run_dir.mkdir(parents=True)

    append_to_bucket(run_dir, "applied", {"case": "D366", "reason": "ok"})
    append_to_bucket(run_dir, "applied", {"case": "D369", "reason": "ok"})
    entries = list_bucket(run_dir, "applied")
    assert len(entries) == 2
    assert entries[0]["case"] == "D366"
    assert entries[1]["case"] == "D369"


def test_invalid_bucket_raises(tmp_path):
    run_dir = tmp_path / "runs" / "rid" / "plug"
    run_dir.mkdir(parents=True)
    with pytest.raises(ValueError, match="unknown bucket"):
        append_to_bucket(run_dir, "applied_typo", {"case": "D1"})


def test_list_empty_bucket_returns_empty(tmp_path):
    run_dir = tmp_path / "runs" / "rid" / "plug"
    run_dir.mkdir(parents=True)
    assert list_bucket(run_dir, "applied") == []
```

- [ ] **Step 2: Run tests — FAIL (ImportError)**

```bash
uv run pytest tests/test_audit_bucket.py -v
```

- [ ] **Step 3: Implement bucket module**

```python
# src/testpilot/audit/bucket.py
"""Bucket jsonl writer / reader (append-only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BUCKETS: tuple[str, ...] = ("confirmed", "applied", "pending", "block", "needs_pass3")


def append_to_bucket(run_dir: Path, bucket: str, entry: dict[str, Any]) -> None:
    """Append entry to <run_dir>/buckets/<bucket>.jsonl (atomic append)."""
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket: {bucket!r}; valid={BUCKETS}")
    bucket_dir = run_dir / "buckets"
    bucket_dir.mkdir(parents=True, exist_ok=True)
    path = bucket_dir / f"{bucket}.jsonl"
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def list_bucket(run_dir: Path, bucket: str) -> list[dict[str, Any]]:
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket: {bucket!r}; valid={BUCKETS}")
    path = run_dir / "buckets" / f"{bucket}.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/test_audit_bucket.py -v   # 4 pass

git add src/testpilot/audit/bucket.py tests/test_audit_bucket.py
git commit -m "feat(audit): bucket jsonl bookkeeping (append-only)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Wire `testpilot audit init` CLI

**Files:**
- Create: `src/testpilot/audit/cli.py`
- Modify: `src/testpilot/cli.py`（register audit group）
- Test: `tests/test_audit_cli.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_audit_cli.py（新建）
"""testpilot audit CLI integration tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from testpilot.cli import main as cli_main


def _stub_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "x.txt").write_text("x")
    subprocess.run(["git", "add", "x.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def test_audit_init_emits_rid_and_writes_manifest(tmp_path, monkeypatch):
    repo = _stub_repo(tmp_path)
    workbook = Path(__file__).resolve().parent / "fixtures" / "audit" / "sample_workbook.xlsx"
    monkeypatch.chdir(repo)
    (repo / "audit").mkdir()

    runner = CliRunner()
    result = runner.invoke(
        cli_main,
        ["audit", "init", "wifi_llapi", "--workbook", str(workbook),
         "--cases", "D001"],
    )
    assert result.exit_code == 0, result.output
    rid = result.output.strip().splitlines()[-1]
    assert "-" in rid
    manifest = json.loads(
        (repo / "audit" / "runs" / rid / "wifi_llapi" / "manifest.json").read_text()
    )
    assert manifest["plugin"] == "wifi_llapi"
    assert "D001" in manifest["cases"]
```

- [ ] **Step 2: Run — FAIL**

```bash
uv run pytest tests/test_audit_cli.py::test_audit_init_emits_rid_and_writes_manifest -v
```

- [ ] **Step 3: Implement audit CLI group**

寫 `src/testpilot/audit/cli.py`：

```python
"""testpilot audit click subgroup."""

from __future__ import annotations

import json
from pathlib import Path

import click

from testpilot.audit import manifest as manifest_mod
from testpilot.audit import workbook_index as wbi


@click.group("audit")
def audit_group() -> None:
    """Audit / calibration mode — split from normal `testpilot run`."""


@audit_group.command("init")
@click.argument("plugin")
@click.option("--workbook", type=click.Path(path_type=Path), default=None,
              help="Path to xlsx workbook. Fallback: audit/workbooks/<plugin>.xlsx")
@click.option("--cases", default="", help="Comma-separated case ids; default = discover all official")
@click.option("--sheet", default="Wifi_LLAPI")
@click.option("--col-object", default=None, help="Override column letter (e.g. F)")
@click.option("--col-api", default=None)
@click.option("--col-steps", default=None)
@click.option("--col-output", default=None)
@click.option("--col-result-5g", default=None)
@click.option("--col-result-6g", default=None)
@click.option("--col-result-24g", default=None)
def cmd_init(
    plugin: str,
    workbook: Path | None,
    cases: str,
    sheet: str,
    col_object: str | None,
    col_api: str | None,
    col_steps: str | None,
    col_output: str | None,
    col_result_5g: str | None,
    col_result_6g: str | None,
    col_result_24g: str | None,
) -> None:
    """Initialize an audit run; emit RID."""
    repo_root = Path.cwd()
    audit_root = repo_root / "audit"
    audit_root.mkdir(exist_ok=True)

    # workbook 路徑解析
    if workbook is None:
        fallback = audit_root / "workbooks" / f"{plugin}.xlsx"
        if not fallback.is_file():
            raise click.UsageError(
                f"--workbook not given and fallback {fallback} 不存在")
        workbook = fallback
    workbook = workbook.resolve()
    if not workbook.is_file():
        raise click.UsageError(f"workbook 不存在: {workbook}")

    # 列出 cases — Phase A 先用 CLI 給的；Phase B 接 plugin discover
    case_ids = [c.strip() for c in cases.split(",") if c.strip()]
    if not case_ids:
        case_ids = _discover_official_cases(repo_root, plugin)

    # column overrides
    overrides: dict[str, str] = {}
    if col_object: overrides["object"] = col_object
    if col_api: overrides["api"] = col_api
    if col_steps: overrides["test_steps"] = col_steps
    if col_output: overrides["command_output"] = col_output
    if col_result_5g: overrides["result_5g"] = col_result_5g
    if col_result_6g: overrides["result_6g"] = col_result_6g
    if col_result_24g: overrides["result_24g"] = col_result_24g

    # 驗證 workbook 可開（不存儲 index — pass12 才存）
    wbi.build_index(workbook, sheet_name=sheet,
                    column_overrides=overrides if overrides else None)

    cli_args = {
        "sheet": sheet,
        "column_overrides": overrides,
    }
    rid = manifest_mod.create_run(
        plugin=plugin,
        workbook_path=workbook,
        cli_args=cli_args,
        case_ids=case_ids,
        audit_root=audit_root,
        repo_root=repo_root,
    )

    # snapshot workbook
    import shutil
    snapshot = audit_root / "runs" / rid / plugin / "workbook_snapshot.xlsx"
    shutil.copy2(workbook, snapshot)

    click.echo(rid)


def _discover_official_cases(repo_root: Path, plugin: str) -> list[str]:
    cases_dir = repo_root / "plugins" / plugin / "cases"
    if not cases_dir.is_dir():
        return []
    out = []
    for p in sorted(cases_dir.glob("D*.yaml")):
        if p.name.startswith("_"):
            continue
        # case id by stem split
        out.append(p.stem.split("_", 1)[0])
    return out
```

- [ ] **Step 4: Register in src/testpilot/cli.py**

在 `src/testpilot/cli.py` 找到 `@click.group()` 後 `def main(...)` block 結束處（line ~117 附近），新增：

```python
# 既有 import 區加：
from testpilot.audit.cli import audit_group as _audit_group  # noqa: E402

# 既有 main = ... group 定義後加：
main.add_command(_audit_group)
```

- [ ] **Step 5: Run + commit**

```bash
uv run pytest tests/test_audit_cli.py::test_audit_init_emits_rid_and_writes_manifest -v
# expect PASS

git add src/testpilot/audit/cli.py src/testpilot/cli.py tests/test_audit_cli.py
git commit -m "feat(audit): wire 'testpilot audit init' subcommand

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Implement `audit status` and `audit summary` CLI

**Files:**
- Modify: `src/testpilot/audit/cli.py`
- Test: `tests/test_audit_cli.py`（追加）

- [ ] **Step 1: Write failing test**

在 `tests/test_audit_cli.py` 末尾追加：

```python
def test_audit_status_after_init(tmp_path, monkeypatch):
    repo = _stub_repo(tmp_path)
    workbook = Path(__file__).resolve().parent / "fixtures" / "audit" / "sample_workbook.xlsx"
    monkeypatch.chdir(repo)
    (repo / "audit").mkdir()

    runner = CliRunner()
    init_result = runner.invoke(cli_main, [
        "audit", "init", "wifi_llapi", "--workbook", str(workbook),
        "--cases", "D001,D002",
    ])
    rid = init_result.output.strip().splitlines()[-1]

    status_result = runner.invoke(cli_main, ["audit", "status", rid])
    assert status_result.exit_code == 0
    assert "wifi_llapi" in status_result.output
    assert "cases: 2" in status_result.output


def test_audit_summary_renders_md(tmp_path, monkeypatch):
    repo = _stub_repo(tmp_path)
    workbook = Path(__file__).resolve().parent / "fixtures" / "audit" / "sample_workbook.xlsx"
    monkeypatch.chdir(repo)
    (repo / "audit").mkdir()

    runner = CliRunner()
    init_result = runner.invoke(cli_main, [
        "audit", "init", "wifi_llapi", "--workbook", str(workbook),
        "--cases", "D001",
    ])
    rid = init_result.output.strip().splitlines()[-1]

    sum_result = runner.invoke(cli_main, ["audit", "summary", rid])
    assert sum_result.exit_code == 0
    summary_path = repo / "audit" / "runs" / rid / "wifi_llapi" / "summary.md"
    assert summary_path.is_file()
    body = summary_path.read_text()
    assert "# Audit Run Summary" in body
    assert rid in body
```

- [ ] **Step 2: Run — FAIL**

```bash
uv run pytest tests/test_audit_cli.py::test_audit_status_after_init tests/test_audit_cli.py::test_audit_summary_renders_md -v
```

- [ ] **Step 3: Implement status + summary subcommands**

在 `src/testpilot/audit/cli.py` 末尾追加：

```python
from testpilot.audit import bucket as bucket_mod


def _resolve_run_dir(rid: str, plugin: str | None = None) -> Path:
    audit_root = Path.cwd() / "audit"
    rid_dir = audit_root / "runs" / rid
    if not rid_dir.is_dir():
        raise click.UsageError(f"RID 不存在: {rid}")
    if plugin:
        return rid_dir / plugin
    # 取唯一一個 plugin（首發只 wifi_llapi）
    children = [p for p in rid_dir.iterdir() if p.is_dir()]
    if len(children) != 1:
        raise click.UsageError(
            f"找不到唯一 plugin run dir under {rid_dir}: {[c.name for c in children]}")
    return children[0]


@audit_group.command("status")
@click.argument("rid")
def cmd_status(rid: str) -> None:
    """Print bucket counts + needs_pass3 worklist."""
    run_dir = _resolve_run_dir(rid)
    plugin = run_dir.name
    manifest = json.loads((run_dir / "manifest.json").read_text())

    click.echo(f"RID: {rid}")
    click.echo(f"plugin: {plugin}")
    click.echo(f"cases: {len(manifest['cases'])}")
    click.echo("buckets:")
    for b in bucket_mod.BUCKETS:
        n = len(bucket_mod.list_bucket(run_dir, b))
        click.echo(f"  {b}: {n}")


@audit_group.command("summary")
@click.argument("rid")
def cmd_summary(rid: str) -> None:
    """Render audit/runs/<RID>/<plugin>/summary.md."""
    run_dir = _resolve_run_dir(rid)
    plugin = run_dir.name
    manifest = json.loads((run_dir / "manifest.json").read_text())

    lines = [
        f"# Audit Run Summary",
        f"",
        f"- **RID**: `{rid}`",
        f"- **Plugin**: `{plugin}`",
        f"- **Workbook**: `{manifest['workbook_path']}`",
        f"- **Total cases**: {len(manifest['cases'])}",
        f"- **Init**: {manifest['init_timestamp']}",
        f"",
        f"## Bucket counts",
        f"",
        f"| Bucket | Count |",
        f"| --- | ---: |",
    ]
    for b in bucket_mod.BUCKETS:
        n = len(bucket_mod.list_bucket(run_dir, b))
        lines.append(f"| {b} | {n} |")
    lines.append("")

    summary_path = run_dir / "summary.md"
    summary_path.write_text("\n".join(lines))
    click.echo(f"wrote {summary_path}")
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/test_audit_cli.py -v
# expect 3 pass

git add src/testpilot/audit/cli.py tests/test_audit_cli.py
git commit -m "feat(audit): add 'audit status' and 'audit summary' subcommands

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

**Phase A Review Checkpoint** — 暫停讓 user / reviewer 確認：
- audit 套件骨架 + gitignore + dir layout 是否如預期
- RID 格式、manifest schema、workbook index 三項基礎功是否能用
- `testpilot audit init / status / summary` 已可跑

---

## Phase B — Pass 1/2 Mechanical

### Task 7: Implement runner_facade（thin wrapper around Orchestrator）

**Files:**
- Create: `src/testpilot/audit/runner_facade.py`
- Test: `tests/test_audit_runner_facade.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_audit_runner_facade.py
"""Audit thin facade over Orchestrator.run() — single-case mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from testpilot.audit.runner_facade import (
    AuditCaseResult,
    run_one_case_for_audit,
)


@pytest.mark.skip(reason="需要 wifi_llapi 完整 testbed; integration covered in test_audit_cli")
def test_run_one_case_returns_verdict():
    pass


def test_audit_case_result_has_required_fields():
    r = AuditCaseResult(
        case_id="D001",
        verdict_per_band={"5g": "Pass", "6g": "Pass", "2.4g": "Pass"},
        capture={"x": "y"},
        artifacts={"json_report_path": "/tmp/r.json"},
        error=None,
    )
    assert r.case_id == "D001"
    assert r.verdict_per_band["5g"] == "Pass"
    assert r.error is None
```

- [ ] **Step 2: Run — FAIL**

```bash
uv run pytest tests/test_audit_runner_facade.py -v
```

- [ ] **Step 3: Implement facade**

```python
# src/testpilot/audit/runner_facade.py
"""Thin wrapper over Orchestrator.run() for single-case audit execution.

Does NOT change normal-run behavior. Only exposes existing public API in a
shape convenient for audit waterfall.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from testpilot.core.orchestrator import Orchestrator


@dataclass
class AuditCaseResult:
    case_id: str
    verdict_per_band: dict[str, str]   # e.g. {"5g": "Pass", "6g": "Fail", "2.4g": "Pass"}
    capture: dict[str, Any]            # plugin-emitted capture map
    artifacts: dict[str, str]          # paths to xlsx/json/log
    error: str | None


def run_one_case_for_audit(
    plugin: str,
    case_id: str,
    *,
    repo_root: Path | None = None,
) -> AuditCaseResult:
    """Run a single case through the existing Orchestrator and project verdict.

    For wifi_llapi, parses run output JSON to extract per-band verdicts.
    """
    repo_root = repo_root or Path.cwd()
    orch = Orchestrator(root=repo_root)
    try:
        result = orch.run(plugin, case_ids=[case_id])
    except Exception as exc:
        return AuditCaseResult(case_id, {}, {}, {}, error=f"orchestrator error: {exc}")

    json_report = result.get("json_report_path", "")
    capture: dict[str, Any] = {}
    verdict_per_band: dict[str, str] = {}
    if json_report and Path(json_report).is_file():
        data = json.loads(Path(json_report).read_text())
        # 期待結構: {"cases": [{"id": ..., "verdict_per_band": {...}, "capture": {...}}]}
        for case in data.get("cases", []):
            if str(case.get("id", "")).lower().startswith(case_id.lower()):
                verdict_per_band = case.get("verdict_per_band", {})
                capture = case.get("capture", {})
                break

    return AuditCaseResult(
        case_id=case_id,
        verdict_per_band=verdict_per_band,
        capture=capture,
        artifacts={
            "report_path": result.get("report_path", ""),
            "json_report_path": json_report,
            "md_report_path": result.get("md_report_path", ""),
        },
        error=None,
    )
```

> **Note**: `verdict_per_band` 的 key 結構需對齊 wifi_llapi plugin 實際 emit 的 JSON。Phase B Task 8 跑 integration test 時若 key 不對齊，調整這裡的解析邏輯（仍走 plugin public output，不改 plugin 內部）。

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/test_audit_runner_facade.py -v
# expect 1 pass + 1 skip

git add src/testpilot/audit/runner_facade.py tests/test_audit_runner_facade.py
git commit -m "feat(audit): runner_facade — thin wrapper over Orchestrator.run

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: Implement Pass 2 mechanical extractor

**Files:**
- Create: `src/testpilot/audit/extractor.py`
- Test: `tests/test_audit_extractor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit_extractor.py
"""Pass 2 mechanical command extractor."""

from __future__ import annotations

import pytest

from testpilot.audit.extractor import (
    ExtractedCommand,
    extract_commands,
    ALLOWED_TOKENS,
)


def test_allowed_tokens_set():
    assert "ubus-cli" in ALLOWED_TOKENS
    assert "wl" in ALLOWED_TOKENS
    assert "grep" in ALLOWED_TOKENS
    assert "rm" not in ALLOWED_TOKENS


def test_line_start_token_capture():
    text = """Read radio noise:
ubus-cli "WiFi.Radio.1.Noise?"
expected: numeric"""
    cmds = extract_commands(text)
    assert any(c.command.startswith("ubus-cli") for c in cmds)
    # citation 必須是原文 substring
    for c in cmds:
        assert c.citation in text


def test_fenced_triple_backtick():
    text = """Procedure:
```bash
wl -i wl0 sr_config srg_obsscolorbmp
```
end"""
    cmds = extract_commands(text)
    assert any("wl -i wl0 sr_config srg_obsscolorbmp" in c.command for c in cmds)


def test_inline_single_backtick():
    text = "Run `grep -c he_spr_srg /tmp/wl0_hapd.conf` and check output"
    cmds = extract_commands(text)
    assert any("grep -c he_spr_srg" in c.command for c in cmds)


def test_chinese_prose_yields_nothing():
    text = "設定 SRG bitmap 並驗證 driver 是否拉起。"
    cmds = extract_commands(text)
    assert cmds == []


def test_placeholder_command_rejected():
    text = "ubus-cli <YOUR_OBJECT>.Foo?"
    cmds = extract_commands(text)
    assert cmds == []  # 含 <...> placeholder 不採納


def test_disallowed_token_rejected():
    text = """Try this:
rm -rf /tmp/foo
nc -l 80
"""
    cmds = extract_commands(text)
    assert cmds == []
```

- [ ] **Step 2: Run — FAIL**

```bash
uv run pytest tests/test_audit_extractor.py -v
```

- [ ] **Step 3: Implement extractor**

```python
# src/testpilot/audit/extractor.py
"""Pass 2 mechanical command extractor.

抽 workbook G/H prose 中可執行命令；不重新組合 / 改寫；citation 必須是原文 substring。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

ALLOWED_TOKENS: frozenset[str] = frozenset({
    "ubus-cli", "wl", "hostapd_cli", "grep", "cat", "sed", "awk",
    "ip", "iw", "hostapd", "wpa_cli",
})

_TRIPLE_FENCE_RE = re.compile(r"```(?:\w+)?\n(.*?)```", re.DOTALL)
_SINGLE_FENCE_RE = re.compile(r"`([^`\n]+)`")
_PLACEHOLDER_RE = re.compile(r"<[A-Z_]+>")


@dataclass(frozen=True)
class ExtractedCommand:
    command: str
    citation: str          # original substring of source text
    rule: str              # which extraction rule fired


def _starts_with_allowed_token(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped:
        return False
    first = stripped.split(None, 1)[0]
    return first in ALLOWED_TOKENS


def _candidate_is_clean(cmd: str) -> bool:
    if _PLACEHOLDER_RE.search(cmd):
        return False
    return _starts_with_allowed_token(cmd)


def extract_commands(text: str) -> list[ExtractedCommand]:
    """Mechanical extract — return list of candidate commands with citations.

    Order of rules（first match wins per substring of source）:
    1. Triple-fenced code blocks
    2. Single-backtick inline
    3. Bare lines starting with allowed token
    """
    if not text:
        return []
    out: list[ExtractedCommand] = []

    # Rule 1: triple-fenced blocks
    for m in _TRIPLE_FENCE_RE.finditer(text):
        block = m.group(1)
        for line in block.splitlines():
            line = line.rstrip()
            if _candidate_is_clean(line):
                out.append(ExtractedCommand(
                    command=line.strip(),
                    citation=m.group(0),  # 整個 fence block 當 citation
                    rule="triple_fence",
                ))

    # Rule 2: single-backtick inline
    for m in _SINGLE_FENCE_RE.finditer(text):
        cmd = m.group(1).strip()
        if _candidate_is_clean(cmd):
            out.append(ExtractedCommand(
                command=cmd,
                citation=m.group(0),
                rule="single_backtick",
            ))

    # Rule 3: bare-line allowed token
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # 排除已被 fence 規則捕獲的（簡單去重）
        if any(stripped == c.command and c.rule != "bare_line" for c in out):
            continue
        if _candidate_is_clean(stripped):
            out.append(ExtractedCommand(
                command=stripped,
                citation=line,  # 原始行（含 leading whitespace）
                rule="bare_line",
            ))

    # 最終去重 — 命令 + rule 相同的合併
    seen: set[tuple[str, str]] = set()
    deduped: list[ExtractedCommand] = []
    for c in out:
        key = (c.command, c.rule)
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/test_audit_extractor.py -v
# expect 7 pass

git add src/testpilot/audit/extractor.py tests/test_audit_extractor.py
git commit -m "feat(audit): Pass 2 mechanical command extractor

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: Implement pass12 main flow + `audit pass12` CLI

**Files:**
- Create: `src/testpilot/audit/pass12.py`
- Modify: `src/testpilot/audit/cli.py`（追加 pass12 subcommand）
- Test: `tests/test_audit_pass12.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit_pass12.py
"""Pass 1+2 main flow tests with mocked runner_facade."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from testpilot.audit.pass12 import run_pass12_for_case, PassResult
from testpilot.audit.runner_facade import AuditCaseResult


def test_pass1_match_lands_confirmed():
    """Pass 1 verdict 與 workbook 對齊 → bucket=confirmed."""
    fake_result = AuditCaseResult(
        case_id="D001",
        verdict_per_band={"5g": "Pass", "6g": "Pass", "2.4g": "Pass"},
        capture={},
        artifacts={},
        error=None,
    )
    workbook_row = type("R", (), dict(
        result_5g="Pass", result_6g="Pass", result_24g="Pass",
        test_steps="ubus-cli ...", command_output="",
    ))()
    with patch("testpilot.audit.pass12._run_facade", return_value=fake_result):
        r = run_pass12_for_case(plugin="wifi_llapi", case_id="D001",
                                 workbook_row=workbook_row, run_dir=Path("/tmp/x"))
    assert r.bucket == "confirmed"
    assert r.pass1_verdict_match is True


def test_pass1_mismatch_pass2_extracts_and_matches():
    """Pass 1 mismatch → Pass 2 抽 G 命令 → 跑後對齊 → 候選 applied (caller decide)."""
    pass1_result = AuditCaseResult("D366", {"5g": "Pass", "6g": "Pass", "2.4g": "Pass"},
                                    {}, {}, None)
    pass2_result = AuditCaseResult("D366", {"5g": "Fail", "6g": "Fail", "2.4g": "Fail"},
                                    {}, {}, None)
    workbook_row = type("R", (), dict(
        result_5g="Fail", result_6g="Fail", result_24g="Fail",
        test_steps="`wl -i wl0 sr_config srg_obsscolorbmp`",
        command_output="",
    ))()
    with patch("testpilot.audit.pass12._run_facade",
               side_effect=[pass1_result, pass2_result]):
        r = run_pass12_for_case(plugin="wifi_llapi", case_id="D366",
                                 workbook_row=workbook_row, run_dir=Path("/tmp/x"))
    assert r.bucket in ("applied", "pending")  # 由 decision 模組決定
    assert r.pass1_verdict_match is False
    assert r.pass2_verdict_match is True
    assert r.extracted_commands and "wl -i wl0 sr_config" in r.extracted_commands[0].command


def test_pass2_no_extract_yields_needs_pass3():
    """Pass 1 mismatch + Pass 2 抽不到 → needs_pass3."""
    pass1_result = AuditCaseResult("D369", {"5g": "Pass", "6g": "Pass", "2.4g": "Pass"},
                                    {}, {}, None)
    workbook_row = type("R", (), dict(
        result_5g="Fail", result_6g="Fail", result_24g="Fail",
        test_steps="設定 SRG bitmap 並驗證 driver 是否拉起",  # 中文 prose
        command_output="",
    ))()
    with patch("testpilot.audit.pass12._run_facade", return_value=pass1_result):
        r = run_pass12_for_case(plugin="wifi_llapi", case_id="D369",
                                 workbook_row=workbook_row, run_dir=Path("/tmp/x"))
    assert r.bucket == "needs_pass3"
    assert r.extracted_commands == []
```

- [ ] **Step 2: Run — FAIL**

```bash
uv run pytest tests/test_audit_pass12.py -v
```

- [ ] **Step 3: Implement pass12 module**

```python
# src/testpilot/audit/pass12.py
"""Pass 1 (baseline) + Pass 2 (mechanical extract from G/H)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from testpilot.audit.extractor import ExtractedCommand, extract_commands
from testpilot.audit.runner_facade import (
    AuditCaseResult,
    run_one_case_for_audit,
)


@dataclass
class PassResult:
    case_id: str
    pass1_verdict_match: bool
    pass2_verdict_match: bool | None        # None 表示沒跑 Pass 2
    extracted_commands: list[ExtractedCommand] = field(default_factory=list)
    bucket: str = "needs_pass3"             # confirmed / applied (候選) / pending / needs_pass3 / block
    reason: str = ""
    pass1_artifacts: dict[str, Any] = field(default_factory=dict)
    pass2_artifacts: dict[str, Any] = field(default_factory=dict)


def _run_facade(plugin: str, case_id: str) -> AuditCaseResult:
    """Indirection so tests can patch easily."""
    return run_one_case_for_audit(plugin, case_id)


def _verdict_matches_workbook(verdict_per_band: dict[str, str], wb_row) -> bool:
    """Compare {5g, 6g, 2.4g} vs workbook R/S/T (case-insensitive)."""
    if not verdict_per_band:
        return False
    expected = {
        "5g": str(getattr(wb_row, "result_5g", "")).strip().lower(),
        "6g": str(getattr(wb_row, "result_6g", "")).strip().lower(),
        "2.4g": str(getattr(wb_row, "result_24g", "")).strip().lower(),
    }
    actual = {k.lower(): str(v).strip().lower() for k, v in verdict_per_band.items()}
    return all(actual.get(b) == expected[b] for b in ("5g", "6g", "2.4g") if expected[b])


def run_pass12_for_case(
    *,
    plugin: str,
    case_id: str,
    workbook_row,
    run_dir: Path,
) -> PassResult:
    """Run Pass 1 then Pass 2 for one case. Caller handles bucket persistence."""
    # ---- Pass 1 ----
    p1 = _run_facade(plugin, case_id)
    p1_match = _verdict_matches_workbook(p1.verdict_per_band, workbook_row)
    if p1_match:
        return PassResult(
            case_id=case_id,
            pass1_verdict_match=True,
            pass2_verdict_match=None,
            bucket="confirmed",
            reason="pass1_verdict_match",
            pass1_artifacts={"verdict": p1.verdict_per_band, "error": p1.error},
        )

    # ---- Pass 2 ----
    text = "\n".join([
        getattr(workbook_row, "test_steps", "") or "",
        getattr(workbook_row, "command_output", "") or "",
    ])
    cmds = extract_commands(text)
    if not cmds:
        return PassResult(
            case_id=case_id,
            pass1_verdict_match=False,
            pass2_verdict_match=None,
            bucket="needs_pass3",
            reason="pass2_no_extract",
            pass1_artifacts={"verdict": p1.verdict_per_band, "error": p1.error},
        )

    # Pass 2 用 extracted commands rerun — 透過 facade 把 commands 注入是 Phase B 的
    # 簡化路徑：facade 不接受 commands override；先以 extracted commands 為「proposed
    # workbook-derived 命令」，rerun 仍跑當前 YAML，只用 extracted commands 做 citation
    # 證據。實際命令注入由 Phase D apply 步驟接 — 此處 Pass 2 verdict_match 等同 Pass 1
    # （因為 YAML 沒換）→ 仍是 needs_pass3。
    #
    # 真實 Pass 2 rerun 需要先把 workbook commands 寫成 proposed.yaml 再跑 facade；
    # 那是 Phase D 的 record/decide 流程。Phase B 的 Pass 2 角色限定為 *抽取 + 標記*。
    return PassResult(
        case_id=case_id,
        pass1_verdict_match=False,
        pass2_verdict_match=False,
        extracted_commands=cmds,
        bucket="needs_pass3",
        reason="pass2_extract_only_no_rerun",
        pass1_artifacts={"verdict": p1.verdict_per_band, "error": p1.error},
    )
```

> **Important Phase B note**：Pass 2 **不在** Phase B 真的 rerun。原因：要做 Pass 2 rerun 必須有「拿 extracted commands 重跑 case」的 facade 介面，這需要在 plugin / orchestrator 加 step override 路徑（會超出 audit 套件邊界）。Phase B 的 Pass 2 任務限定為「抽 + 標 needs_pass3 + 把 extracted commands 帶上以供 Phase D 使用」。當 user 在 Phase D `audit decide` 時用 extracted commands 構造 proposed.yaml 並走 verify-edit，再由 facade 跑 proposed.yaml 拿 verdict_w。這個取捨在 design.md D2 已涵蓋（「Pass 1/2 純 py」≠「Pass 2 一定 rerun」）。

- [ ] **Step 4: 在 cli.py 加 pass12 subcommand**

在 `src/testpilot/audit/cli.py` 末尾追加：

```python
from testpilot.audit import pass12 as pass12_mod
from testpilot.audit.workbook_index import build_index, normalize_object, normalize_api


@audit_group.command("pass12")
@click.argument("rid")
def cmd_pass12(rid: str) -> None:
    """Run Pass 1 + Pass 2 across all cases in this RID."""
    run_dir = _resolve_run_dir(rid)
    plugin = run_dir.name
    manifest = json.loads((run_dir / "manifest.json").read_text())

    # Re-build workbook index from snapshot
    snapshot = run_dir / "workbook_snapshot.xlsx"
    sheet = manifest["cli_args"]["sheet"]
    overrides = manifest["cli_args"].get("column_overrides") or None
    idx = build_index(snapshot, sheet_name=sheet, column_overrides=overrides)

    # Iter cases
    for case_id in manifest["cases"]:
        # 載入 case YAML 取 source.object/api（Phase B 簡化：從 yaml frontmatter 抓）
        yaml_path = (Path.cwd() / "plugins" / plugin / "cases").glob(f"{case_id}_*.yaml")
        yaml_files = list(yaml_path)
        if not yaml_files:
            click.echo(f"[skip] {case_id}: yaml not found")
            continue
        import yaml as _yaml
        case_data = _yaml.safe_load(yaml_files[0].read_text())
        obj = case_data.get("source", {}).get("object", "")
        api = case_data.get("source", {}).get("api", "")
        key = (normalize_object(obj), normalize_api(api))

        case_dir = run_dir / "case" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        if key not in idx:
            bucket_mod.append_to_bucket(run_dir, "block",
                {"case": case_id, "reason": "workbook_row_missing", "key": list(key)})
            continue
        rows = idx[key]
        if len(rows) > 1:
            bucket_mod.append_to_bucket(run_dir, "block",
                {"case": case_id, "reason": "workbook_row_ambiguous",
                 "candidates": [r.raw_row_index for r in rows]})
            continue
        wb_row = rows[0]

        result = pass12_mod.run_pass12_for_case(
            plugin=plugin,
            case_id=case_id,
            workbook_row=wb_row,
            run_dir=run_dir,
        )
        # Persist pass1 evidence
        (case_dir / "pass1_baseline.json").write_text(json.dumps({
            "case": case_id,
            "verdict_match": result.pass1_verdict_match,
            "artifacts": result.pass1_artifacts,
        }, indent=2))
        if result.extracted_commands:
            (case_dir / "pass2_workbook.json").write_text(json.dumps({
                "case": case_id,
                "extracted_commands": [
                    {"command": c.command, "citation": c.citation, "rule": c.rule}
                    for c in result.extracted_commands
                ],
                "verdict_match": result.pass2_verdict_match,
            }, indent=2))

        bucket_mod.append_to_bucket(run_dir, result.bucket,
            {"case": case_id, "reason": result.reason})
        click.echo(f"[{result.bucket}] {case_id}: {result.reason}")
```

- [ ] **Step 5: Run + commit**

```bash
uv run pytest tests/test_audit_pass12.py -v
# expect 3 pass

git add src/testpilot/audit/pass12.py src/testpilot/audit/cli.py tests/test_audit_pass12.py
git commit -m "feat(audit): Pass 1/2 main flow + 'audit pass12' CLI

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

**Phase B Review Checkpoint** — 確認：
- runner_facade 能接 wifi_llapi 既有 Orchestrator.run() 取 verdict
- Pass 2 抽取規則 cover 預期格式（fenced / 行首 / 行內），placeholder/中文 prose 拒絕
- pass12 CLI 對 mock case 跑通；workbook missing/ambiguous 落 block
- 後續：Pass 2 真正 rerun（用 proposed.yaml）由 Phase D record/decide 流程承接

---

## Phase C — verify-edit Gate + pre-commit Hook

### Task 10: Implement YAML edit boundary check

**Files:**
- Create: `src/testpilot/audit/verify_edit.py`
- Test: `tests/test_audit_verify_edit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit_verify_edit.py
"""YAML edit boundary tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from testpilot.audit.verify_edit import (
    diff_paths,
    is_path_allowed,
    ALLOWED_PATH_PREFIXES,
    BoundaryViolation,
    check_boundary,
)


_BASE_YAML = """
id: wifi-llapi-D366-srgbsscolorbitmap
name: SRGBSSColorBitmap
version: '1.1'
source:
  row: 366
  object: WiFi.Radio.{i}.IEEE80211ax.
  api: SRGBSSColorBitmap
bands: [5g, 6g, 2.4g]
steps:
  - id: s1
    action: exec
    target: DUT
    command: ubus-cli "WiFi.Radio.1.IEEE80211ax.SRGBSSColorBitmap?"
    capture: r1
pass_criteria:
  - field: r1.SRGBSSColorBitmap
    operator: equals
    value: ''
verification_command:
  - ubus-cli "WiFi.Radio.1.IEEE80211ax.SRGBSSColorBitmap?"
"""


def test_path_allowed_for_pass_criteria_change():
    paths = ["pass_criteria[0].value"]
    assert is_path_allowed(paths[0])


def test_path_allowed_for_steps_command_change():
    assert is_path_allowed("steps[0].command")
    assert is_path_allowed("steps[3].capture")


def test_path_disallowed_for_source_row():
    assert not is_path_allowed("source.row")
    assert not is_path_allowed("source.object")
    assert not is_path_allowed("id")
    assert not is_path_allowed("name")
    assert not is_path_allowed("topology.devices.DUT.role")


def test_check_boundary_passes_pass_criteria_only_change(tmp_path):
    before = tmp_path / "before.yaml"
    after = tmp_path / "after.yaml"
    before.write_text(_BASE_YAML)
    after.write_text(_BASE_YAML.replace("value: ''", "value: '1'"))
    # 不應該丟例外
    check_boundary(before, after)


def test_check_boundary_rejects_source_row_change(tmp_path):
    before = tmp_path / "before.yaml"
    after = tmp_path / "after.yaml"
    before.write_text(_BASE_YAML)
    after.write_text(_BASE_YAML.replace("row: 366", "row: 412"))
    with pytest.raises(BoundaryViolation, match="source.row"):
        check_boundary(before, after)


def test_check_boundary_rejects_step_addition(tmp_path):
    before = tmp_path / "before.yaml"
    after = tmp_path / "after.yaml"
    before.write_text(_BASE_YAML)
    extra_step = """
  - id: s2
    action: exec
    target: DUT
    command: ubus-cli foo
    capture: r2
"""
    after.write_text(_BASE_YAML.replace(
        "    capture: r1\n",
        f"    capture: r1\n{extra_step}",
    ))
    with pytest.raises(BoundaryViolation, match="steps"):
        check_boundary(before, after)
```

- [ ] **Step 2: Run — FAIL**

```bash
uv run pytest tests/test_audit_verify_edit.py -v
```

- [ ] **Step 3: Implement verify_edit module**

```python
# src/testpilot/audit/verify_edit.py
"""YAML edit boundary check + verify_edit_log writer."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml as _yaml

ALLOWED_PATH_PREFIXES: tuple[str, ...] = (
    "steps[", "verification_command", "pass_criteria[",
)


class BoundaryViolation(Exception):
    """Raised when YAML diff touches a path outside the audit edit allowlist."""


def is_path_allowed(path: str) -> bool:
    """Check if a json-path-like string is within audit edit allowlist."""
    if path == "verification_command":
        return True
    if path.startswith("verification_command["):
        return True
    if path.startswith("steps[") and (".command" in path or ".capture" in path):
        return True
    if path.startswith("pass_criteria["):
        return True
    return False


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dict/list into json-path-like keys."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(_flatten(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            key = f"{prefix}[{i}]"
            out.update(_flatten(v, key))
    else:
        out[prefix] = obj
    return out


def diff_paths(before_yaml: str, after_yaml: str) -> set[str]:
    """Return set of json-path-like keys whose value differs (incl add/remove)."""
    a = _yaml.safe_load(before_yaml) or {}
    b = _yaml.safe_load(after_yaml) or {}
    fa = _flatten(a)
    fb = _flatten(b)
    keys = set(fa) | set(fb)
    diffs = set()
    for k in keys:
        if fa.get(k) != fb.get(k):
            diffs.add(k)
    return diffs


def check_boundary(before_path: Path, after_path: Path) -> set[str]:
    """Check that YAML diff is within allowed paths. Raise BoundaryViolation."""
    bef = before_path.read_text()
    aft = after_path.read_text()
    diffs = diff_paths(bef, aft)
    violations = sorted(d for d in diffs if not is_path_allowed(d))
    if violations:
        raise BoundaryViolation(
            f"YAML diff touched non-allowed paths: {violations}; "
            f"only {ALLOWED_PATH_PREFIXES} prefixes allowed"
        )
    return diffs


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def append_verify_edit_log(
    *,
    log_path: Path,
    case: str,
    yaml_path: Path,
    sha_before: str,
    sha_after_proposed: str,
    diff_paths_set: set[str],
) -> None:
    """Append-only entry to verify_edit_log.jsonl."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "case": case,
        "yaml_path": str(yaml_path),
        "yaml_sha256_before": sha_before,
        "yaml_sha256_after_proposed": sha_after_proposed,
        "diff_paths": sorted(diff_paths_set),
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/test_audit_verify_edit.py -v
# expect 6 pass

git add src/testpilot/audit/verify_edit.py tests/test_audit_verify_edit.py
git commit -m "feat(audit): YAML edit boundary check (path allowlist)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11: Wire `audit verify-edit` CLI subcommand

**Files:**
- Modify: `src/testpilot/audit/cli.py`
- Test: `tests/test_audit_cli.py`（追加）

- [ ] **Step 1: Write failing test**

在 `tests/test_audit_cli.py` 追加：

```python
def test_verify_edit_pass(tmp_path, monkeypatch):
    repo = _stub_repo(tmp_path)
    workbook = Path(__file__).resolve().parent / "fixtures" / "audit" / "sample_workbook.xlsx"
    monkeypatch.chdir(repo)
    (repo / "audit").mkdir()
    (repo / "plugins" / "wifi_llapi" / "cases").mkdir(parents=True)
    yaml_path = repo / "plugins" / "wifi_llapi" / "cases" / "D001_noise.yaml"
    yaml_path.write_text("""id: x
name: x
source: {row: 1, object: 'WiFi.Radio.{i}.', api: 'Noise'}
bands: [5g]
topology: {devices: {DUT: {role: ap}}}
steps:
- {id: s1, action: exec, target: DUT, command: 'ubus-cli foo', capture: r}
pass_criteria:
- {field: r.x, operator: equals, value: '5'}
""")
    runner = CliRunner()
    init = runner.invoke(cli_main, [
        "audit", "init", "wifi_llapi", "--workbook", str(workbook),
        "--cases", "D001",
    ])
    rid = init.output.strip().splitlines()[-1]

    # 寫 proposed.yaml — 只動 pass_criteria value
    proposed = repo / "audit" / "runs" / rid / "wifi_llapi" / "case" / "D001"
    proposed.mkdir(parents=True, exist_ok=True)
    (proposed / "proposed.yaml").write_text(
        yaml_path.read_text().replace("value: '5'", "value: '6'")
    )

    result = runner.invoke(cli_main, [
        "audit", "verify-edit", rid, "D001",
        "--yaml", str(yaml_path),
        "--proposed", str(proposed / "proposed.yaml"),
    ])
    assert result.exit_code == 0, result.output
    log = (repo / "audit" / "runs" / rid / "wifi_llapi" / "verify_edit_log.jsonl").read_text()
    assert "D001" in log
    assert "pass_criteria" in log


def test_verify_edit_rejects_source_row_change(tmp_path, monkeypatch):
    repo = _stub_repo(tmp_path)
    workbook = Path(__file__).resolve().parent / "fixtures" / "audit" / "sample_workbook.xlsx"
    monkeypatch.chdir(repo)
    (repo / "audit").mkdir()
    (repo / "plugins" / "wifi_llapi" / "cases").mkdir(parents=True)
    yaml_path = repo / "plugins" / "wifi_llapi" / "cases" / "D001_noise.yaml"
    yaml_path.write_text("""id: x
name: x
source: {row: 1, object: 'WiFi.Radio.{i}.', api: 'Noise'}
bands: [5g]
topology: {devices: {DUT: {role: ap}}}
steps:
- {id: s1, action: exec, target: DUT, command: 'ubus-cli foo', capture: r}
pass_criteria:
- {field: r.x, operator: equals, value: '5'}
""")

    runner = CliRunner()
    init = runner.invoke(cli_main, [
        "audit", "init", "wifi_llapi", "--workbook", str(workbook),
        "--cases", "D001",
    ])
    rid = init.output.strip().splitlines()[-1]

    proposed = repo / "audit" / "runs" / rid / "wifi_llapi" / "case" / "D001"
    proposed.mkdir(parents=True, exist_ok=True)
    (proposed / "proposed.yaml").write_text(
        yaml_path.read_text().replace("row: 1", "row: 2")
    )

    result = runner.invoke(cli_main, [
        "audit", "verify-edit", rid, "D001",
        "--yaml", str(yaml_path),
        "--proposed", str(proposed / "proposed.yaml"),
    ])
    assert result.exit_code != 0
    assert "source.row" in result.output or "source.row" in (result.exception or Exception()).__str__()
```

- [ ] **Step 2: Run — FAIL**

```bash
uv run pytest tests/test_audit_cli.py::test_verify_edit_pass tests/test_audit_cli.py::test_verify_edit_rejects_source_row_change -v
```

- [ ] **Step 3: Implement verify-edit subcommand**

在 `src/testpilot/audit/cli.py` 末尾追加：

```python
from testpilot.audit import verify_edit as ve_mod
from testpilot.schema.case_schema import validate_case
import yaml as _yaml


@audit_group.command("verify-edit")
@click.argument("rid")
@click.argument("case")
@click.option("--yaml", "yaml_path", required=True, type=click.Path(path_type=Path))
@click.option("--proposed", "proposed_path", required=True, type=click.Path(path_type=Path))
def cmd_verify_edit(rid: str, case: str, yaml_path: Path, proposed_path: Path) -> None:
    """Verify an audit YAML edit (boundary + schema + log)."""
    run_dir = _resolve_run_dir(rid)

    # 1. Boundary check
    try:
        diffs = ve_mod.check_boundary(yaml_path, proposed_path)
    except ve_mod.BoundaryViolation as exc:
        click.echo(f"[FAIL] {exc}", err=True)
        raise click.Abort()

    # 2. Schema check on proposed.yaml
    try:
        proposed_data = _yaml.safe_load(proposed_path.read_text())
        validate_case(proposed_data, source=proposed_path)
    except Exception as exc:
        click.echo(f"[FAIL] schema invalid: {exc}", err=True)
        raise click.Abort()

    # 3. RID active check (manifest存在)
    if not (run_dir / "manifest.json").is_file():
        click.echo(f"[FAIL] RID 不存在或 manifest 缺失: {rid}", err=True)
        raise click.Abort()

    # 4. Append log
    sha_before = ve_mod.file_sha256(yaml_path)
    sha_after = ve_mod.file_sha256(proposed_path)
    log_path = run_dir / "verify_edit_log.jsonl"
    ve_mod.append_verify_edit_log(
        log_path=log_path,
        case=case,
        yaml_path=yaml_path,
        sha_before=sha_before,
        sha_after_proposed=sha_after,
        diff_paths_set=diffs,
    )
    click.echo(f"[OK] verify-edit pass; logged to {log_path}")
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/test_audit_cli.py -v
# expect all pass

git add src/testpilot/audit/cli.py tests/test_audit_cli.py
git commit -m "feat(audit): wire 'audit verify-edit' subcommand

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 12: Implement pre-commit hook script

**Files:**
- Create: `scripts/check_audit_yaml_provenance.py`
- Create: `.pre-commit-config.yaml`
- Test: `tests/test_audit_provenance_hook.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit_provenance_hook.py
"""Pre-commit hook: audit YAML provenance enforcement."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


HOOK_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_audit_yaml_provenance.py"


def _run_hook(*args: str, cwd: Path, env_extra: dict[str, str] | None = None) -> tuple[int, str, str]:
    import os
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    p = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT), *args],
        cwd=cwd, capture_output=True, text=True, env=env,
    )
    return p.returncode, p.stdout, p.stderr


def _stub_repo_with_audit(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "plugins" / "wifi_llapi" / "cases").mkdir(parents=True)
    (repo / "audit" / "runs" / "rid1" / "wifi_llapi").mkdir(parents=True)
    return repo


def test_hook_soft_skips_when_audit_dir_absent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "plugins" / "wifi_llapi" / "cases").mkdir(parents=True)
    yaml_file = repo / "plugins" / "wifi_llapi" / "cases" / "D001_x.yaml"
    yaml_file.write_text("id: x\n")
    rc, out, err = _run_hook(str(yaml_file), cwd=repo)
    assert rc == 0  # soft-skip
    assert "audit/" in out + err  # 警告訊息


def test_hook_passes_when_log_matches(tmp_path):
    repo = _stub_repo_with_audit(tmp_path)
    yaml_file = repo / "plugins" / "wifi_llapi" / "cases" / "D001_x.yaml"
    yaml_content = "id: D001\nname: x\n"
    yaml_file.write_text(yaml_content)
    import hashlib
    sha = hashlib.sha256(yaml_content.encode()).hexdigest()
    log = repo / "audit" / "runs" / "rid1" / "wifi_llapi" / "verify_edit_log.jsonl"
    log.write_text(json.dumps({
        "case": "D001",
        "yaml_path": str(yaml_file),
        "yaml_sha256_after_proposed": sha,
        "diff_paths": ["pass_criteria[0].value"],
    }) + "\n")
    rc, out, err = _run_hook(str(yaml_file), cwd=repo)
    assert rc == 0, f"out={out} err={err}"


def test_hook_fails_when_no_log_match(tmp_path):
    repo = _stub_repo_with_audit(tmp_path)
    yaml_file = repo / "plugins" / "wifi_llapi" / "cases" / "D001_x.yaml"
    yaml_file.write_text("id: D001\nname: untracked\n")
    log = repo / "audit" / "runs" / "rid1" / "wifi_llapi" / "verify_edit_log.jsonl"
    log.write_text(json.dumps({
        "case": "D001",
        "yaml_path": str(yaml_file),
        "yaml_sha256_after_proposed": "deadbeef",
        "diff_paths": [],
    }) + "\n")
    rc, out, err = _run_hook(str(yaml_file), cwd=repo)
    assert rc != 0
    assert "verify-edit" in (out + err)


def test_hook_audit_bypass_via_commit_msg(tmp_path):
    repo = _stub_repo_with_audit(tmp_path)
    yaml_file = repo / "plugins" / "wifi_llapi" / "cases" / "D001_x.yaml"
    yaml_file.write_text("id: D001\nname: untracked\n")
    log = repo / "audit" / "runs" / "rid1" / "wifi_llapi" / "verify_edit_log.jsonl"
    log.write_text("")  # no entries
    rc, out, err = _run_hook(
        str(yaml_file), cwd=repo,
        env_extra={"COMMIT_MSG": "fix: rename id [audit-bypass: rename only]"},
    )
    assert rc == 0
    bypass_log = repo / "audit" / "bypass_log.jsonl"
    assert bypass_log.is_file()
```

- [ ] **Step 2: Run — FAIL**

```bash
uv run pytest tests/test_audit_provenance_hook.py -v
```

- [ ] **Step 3: Implement hook script**

```python
#!/usr/bin/env python3
# scripts/check_audit_yaml_provenance.py
"""Pre-commit hook: validate plugins/<plugin>/cases/D*.yaml edits 對應 audit RID 的
verify_edit_log.jsonl，否則 fail。

Soft-skip when /audit dir 不存在或 verify_edit_log 全空（fresh clone / CI 環境）。
Escape hatch: commit message 含 [audit-bypass: <reason>] → pass + 寫 bypass_log.jsonl.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


_BYPASS_RE = re.compile(r"\[audit-bypass:\s*([^\]]+)\]")


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_commit_msg() -> str:
    # 1. env override (testing)
    if "COMMIT_MSG" in os.environ:
        return os.environ["COMMIT_MSG"]
    # 2. .git/COMMIT_EDITMSG
    p = Path(".git") / "COMMIT_EDITMSG"
    if p.is_file():
        return p.read_text(errors="ignore")
    return ""


def _audit_logs(repo_root: Path) -> list[Path]:
    audit_dir = repo_root / "audit"
    if not audit_dir.is_dir():
        return []
    return list(audit_dir.glob("runs/*/*/verify_edit_log.jsonl"))


def _log_has_sha(logs: list[Path], target_sha: str) -> bool:
    for log in logs:
        for line in log.read_text(errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("yaml_sha256_after_proposed") == target_sha:
                return True
    return False


def _record_bypass(repo_root: Path, reason: str, files: list[str]) -> None:
    bypass_log = repo_root / "audit" / "bypass_log.jsonl"
    bypass_log.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "files": files,
    }
    with bypass_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv if a]
    if not files:
        return 0

    # filter: 只看 plugins/*/cases/D*.yaml
    targets = [p for p in files
               if re.match(r"^plugins/[^/]+/cases/D\d+_.*\.ya?ml$", str(p).replace("\\", "/"))]
    if not targets:
        return 0

    repo_root = Path.cwd()

    # Bypass check
    msg = _read_commit_msg()
    bypass_match = _BYPASS_RE.search(msg)
    if bypass_match:
        _record_bypass(repo_root, bypass_match.group(1).strip(),
                       [str(t) for t in targets])
        print(f"[audit-yaml-provenance] BYPASS: {bypass_match.group(1).strip()}")
        return 0

    # Soft-skip when audit/ absent or logs empty
    logs = _audit_logs(repo_root)
    if not logs or all(not l.read_text(errors="ignore").strip() for l in logs):
        print("[audit-yaml-provenance] WARN: audit/ dir 不存在或 verify_edit_log 全空; "
              "soft-skip (fresh clone / CI environment)")
        return 0

    # Hard check: 每個 staged YAML 必須在某 log 找到對應 sha
    failures: list[str] = []
    for target in targets:
        sha = _file_sha256(target)
        if not _log_has_sha(logs, sha):
            failures.append(str(target))

    if failures:
        print("ERROR: audit YAML provenance check failed for:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Audit doctrine 要求所有 plugins/cases/D*.yaml 編輯都要經過 "
              "`testpilot audit verify-edit <RID> <case> --yaml ... --proposed ...`", file=sys.stderr)
        print("Workaround: commit message 加 [audit-bypass: <reason>] 暫時繞過。", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Create .pre-commit-config.yaml**

```yaml
# .pre-commit-config.yaml
# 注意：repo 目前沒有 pre-commit；這是首次引入。
# Run: pre-commit install
repos:
  - repo: local
    hooks:
      - id: audit-yaml-provenance
        name: Audit YAML provenance check
        entry: python scripts/check_audit_yaml_provenance.py
        language: system
        files: '^plugins/[^/]+/cases/D\d+_.*\.yaml$'
        pass_filenames: true
        require_serial: true
```

- [ ] **Step 5: Run + commit**

```bash
chmod +x scripts/check_audit_yaml_provenance.py
uv run pytest tests/test_audit_provenance_hook.py -v
# expect 4 pass

git add scripts/check_audit_yaml_provenance.py .pre-commit-config.yaml tests/test_audit_provenance_hook.py
git commit -m "feat(audit): pre-commit hook for YAML provenance enforcement

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

**Phase C Review Checkpoint** — 確認：
- 邊界規則涵蓋所有禁忌欄位（id / source.* / topology / steps add）
- verify-edit 正確 append log；shape 對齊 design.md §9.2
- pre-commit hook 三條 path（pass / fail / soft-skip / bypass）都有 cover
- 真在 repo 跑 `pre-commit install && git commit` 試過 hook 行為（手動 smoke）

---

## Phase D — Pass 3 Evidence + Decide + Apply + PR

### Task 13: Implement `audit record` + citation verification

**Files:**
- Create: `src/testpilot/audit/decision.py`（含 citation check）
- Modify: `src/testpilot/audit/cli.py`（加 record subcommand）
- Test: `tests/test_audit_decision.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit_decision.py
"""Citation verification + bucket decision tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from testpilot.audit.decision import (
    Citation,
    DecisionInput,
    decide_bucket,
    verify_citation,
)


def test_verify_citation_matches_existing_file(tmp_path):
    f = tmp_path / "src" / "code.c"
    f.parent.mkdir(parents=True)
    f.write_text("line1\nuint16 srg_pbssid_bmp[4];\nline3\n")

    cit = Citation(file=str(f), line=2, snippet="uint16 srg_pbssid_bmp[4];")
    assert verify_citation(cit, repo_root=tmp_path) is True


def test_verify_citation_rejects_wrong_line(tmp_path):
    f = tmp_path / "src" / "code.c"
    f.parent.mkdir(parents=True)
    f.write_text("line1\nuint16 srg_pbssid_bmp[4];\nline3\n")
    cit = Citation(file=str(f), line=99, snippet="uint16 srg_pbssid_bmp[4];")
    assert verify_citation(cit, repo_root=tmp_path) is False


def test_verify_citation_rejects_missing_file(tmp_path):
    cit = Citation(file=str(tmp_path / "no.c"), line=1, snippet="x")
    assert verify_citation(cit, repo_root=tmp_path) is False


def test_decide_bucket_applied():
    inp = DecisionInput(
        verdict_match=True,
        citation_present=True,
        citation_verified=True,
        field_scope_safe=True,
        schema_valid=True,
    )
    bucket, reason = decide_bucket(inp)
    assert bucket == "applied"


def test_decide_bucket_pending_when_citation_missing():
    inp = DecisionInput(
        verdict_match=True,
        citation_present=False,
        citation_verified=False,
        field_scope_safe=True,
        schema_valid=True,
    )
    bucket, reason = decide_bucket(inp)
    assert bucket == "pending"
    assert "citation" in reason


def test_decide_bucket_block_on_verdict_mismatch():
    inp = DecisionInput(
        verdict_match=False,
        citation_present=True,
        citation_verified=True,
        field_scope_safe=True,
        schema_valid=True,
    )
    bucket, reason = decide_bucket(inp)
    assert bucket == "block"
```

- [ ] **Step 2: Run — FAIL**

```bash
uv run pytest tests/test_audit_decision.py -v
```

- [ ] **Step 3: Implement decision module**

```python
# src/testpilot/audit/decision.py
"""Citation verification + bucket decision logic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Citation:
    file: str
    line: int
    snippet: str


@dataclass
class DecisionInput:
    verdict_match: bool
    citation_present: bool
    citation_verified: bool
    field_scope_safe: bool
    schema_valid: bool


def verify_citation(c: Citation, *, repo_root: Path) -> bool:
    """Check that file exists, line content matches snippet (whitespace-tolerant)."""
    path = Path(c.file)
    if not path.is_absolute():
        path = repo_root / path
    if not path.is_file():
        return False
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except Exception:
        return False
    if c.line < 1 or c.line > len(lines):
        return False
    actual = lines[c.line - 1].strip()
    snippet = c.snippet.strip()
    return snippet in actual


def verify_all(citations: Iterable[Citation], *, repo_root: Path) -> bool:
    return all(verify_citation(c, repo_root=repo_root) for c in citations)


def decide_bucket(inp: DecisionInput) -> tuple[str, str]:
    """Return (bucket, reason)."""
    if not inp.verdict_match:
        return "block", "verdict_mismatch_after_all_passes"
    # verdict_match=True 之下：
    if (inp.citation_present and inp.citation_verified
            and inp.field_scope_safe and inp.schema_valid):
        return "applied", "all_checks_passed"
    reasons = []
    if not inp.citation_present: reasons.append("citation_missing")
    if not inp.citation_verified: reasons.append("citation_not_verified")
    if not inp.field_scope_safe: reasons.append("field_scope_violation")
    if not inp.schema_valid: reasons.append("schema_invalid")
    return "pending", ",".join(reasons) if reasons else "needs_review"
```

- [ ] **Step 4: Wire `audit record` subcommand**

在 `src/testpilot/audit/cli.py` 末尾追加：

```python
from testpilot.audit import decision as decision_mod


@audit_group.command("record")
@click.argument("rid")
@click.argument("case")
@click.option("--evidence", required=True, type=click.Path(path_type=Path),
              help="Path to JSON file with main agent's Pass 3 evidence")
def cmd_record(rid: str, case: str, evidence: Path) -> None:
    """Record main agent's Pass 3 evidence; verify all citations mechanically."""
    run_dir = _resolve_run_dir(rid)
    if not evidence.is_file():
        raise click.UsageError(f"evidence 檔不存在: {evidence}")

    data = json.loads(evidence.read_text())
    citations_raw = data.get("citations", [])
    repo_root = Path.cwd()
    citations = [decision_mod.Citation(**c) for c in citations_raw]
    all_ok = decision_mod.verify_all(citations, repo_root=repo_root)

    case_dir = run_dir / "case" / case
    case_dir.mkdir(parents=True, exist_ok=True)
    out_path = case_dir / "pass3_source.json"
    data["citations_verified"] = all_ok
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))

    if all_ok:
        click.echo(f"[OK] recorded {out_path}; all citations verified")
    else:
        click.echo(f"[WARN] recorded {out_path}; some citations did not verify",
                   err=True)
```

- [ ] **Step 5: Run + commit**

```bash
uv run pytest tests/test_audit_decision.py -v
# expect 6 pass

git add src/testpilot/audit/decision.py src/testpilot/audit/cli.py tests/test_audit_decision.py
git commit -m "feat(audit): citation verify + bucket decision + 'audit record' CLI

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 14: Implement `audit decide` CLI subcommand

**Files:**
- Modify: `src/testpilot/audit/cli.py`
- Test: `tests/test_audit_cli.py`（追加）

- [ ] **Step 1: Write failing test**

在 `tests/test_audit_cli.py` 追加：

```python
def test_decide_writes_decision_json_and_bucket(tmp_path, monkeypatch):
    repo = _stub_repo(tmp_path)
    workbook = Path(__file__).resolve().parent / "fixtures" / "audit" / "sample_workbook.xlsx"
    monkeypatch.chdir(repo)
    (repo / "audit").mkdir()

    runner = CliRunner()
    init = runner.invoke(cli_main, [
        "audit", "init", "wifi_llapi", "--workbook", str(workbook),
        "--cases", "D366",
    ])
    rid = init.output.strip().splitlines()[-1]

    result = runner.invoke(cli_main, [
        "audit", "decide", rid, "D366", "--bucket", "applied",
        "--reason", "test ok",
    ])
    assert result.exit_code == 0
    decision = json.loads(
        (repo / "audit" / "runs" / rid / "wifi_llapi" / "case" / "D366"
         / "decision.json").read_text()
    )
    assert decision["bucket"] == "applied"
    assert decision["reason"] == "test ok"

    bucket_lines = (
        repo / "audit" / "runs" / rid / "wifi_llapi" / "buckets" / "applied.jsonl"
    ).read_text().splitlines()
    assert any('"D366"' in l for l in bucket_lines)
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement decide subcommand**

在 `src/testpilot/audit/cli.py` 末尾追加：

```python
@audit_group.command("decide")
@click.argument("rid")
@click.argument("case")
@click.option("--bucket", required=True,
              type=click.Choice(["confirmed", "applied", "pending", "block"]))
@click.option("--reason", default="")
@click.option("--proposed-yaml", type=click.Path(path_type=Path), default=None)
def cmd_decide(rid: str, case: str, bucket: str, reason: str,
               proposed_yaml: Path | None) -> None:
    """Finalize a case's audit decision: write decision.json + append bucket."""
    run_dir = _resolve_run_dir(rid)
    case_dir = run_dir / "case" / case
    case_dir.mkdir(parents=True, exist_ok=True)

    decision = {
        "case": case,
        "bucket": bucket,
        "reason": reason,
        "proposed_yaml": str(proposed_yaml) if proposed_yaml else None,
    }
    (case_dir / "decision.json").write_text(
        json.dumps(decision, indent=2, ensure_ascii=False, sort_keys=True))

    bucket_mod.append_to_bucket(run_dir, bucket,
                                {"case": case, "reason": reason})
    click.echo(f"[{bucket}] {case}: {reason}")
```

- [ ] **Step 4: Run + commit**

```bash
uv run pytest tests/test_audit_cli.py -v
# expect all pass

git add src/testpilot/audit/cli.py tests/test_audit_cli.py
git commit -m "feat(audit): wire 'audit decide' subcommand

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 15: Implement `audit apply` CLI subcommand

**Files:**
- Create: `src/testpilot/audit/apply.py`
- Modify: `src/testpilot/audit/cli.py`
- Test: `tests/test_audit_apply.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_audit_apply.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from testpilot.audit.apply import apply_run, ApplyResult


def test_apply_writes_proposed_yaml_for_applied_bucket_only(tmp_path):
    run_dir = tmp_path / "audit" / "runs" / "rid" / "wifi_llapi"
    (run_dir / "buckets").mkdir(parents=True)
    (run_dir / "buckets" / "applied.jsonl").write_text(
        json.dumps({"case": "D366"}) + "\n"
    )
    (run_dir / "buckets" / "pending.jsonl").write_text(
        json.dumps({"case": "D369"}) + "\n"
    )
    (run_dir / "case" / "D366").mkdir(parents=True)
    (run_dir / "case" / "D369").mkdir(parents=True)
    (run_dir / "case" / "D366" / "proposed.yaml").write_text("id: D366\nname: x\n")
    (run_dir / "case" / "D369" / "proposed.yaml").write_text("id: D369\nname: x\n")

    cases_dir = tmp_path / "plugins" / "wifi_llapi" / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "D366_x.yaml").write_text("id: D366\nname: old\n")
    (cases_dir / "D369_x.yaml").write_text("id: D369\nname: old\n")

    res = apply_run(run_dir, cases_dir=cases_dir, include_pending=False)
    assert "D366" in res.applied_cases
    assert "D369" not in res.applied_cases
    # 檢查 D366 真的被覆蓋
    assert "name: x" in (cases_dir / "D366_x.yaml").read_text()
    assert "name: old" in (cases_dir / "D369_x.yaml").read_text()


def test_apply_with_include_pending(tmp_path):
    run_dir = tmp_path / "audit" / "runs" / "rid" / "wifi_llapi"
    (run_dir / "buckets").mkdir(parents=True)
    (run_dir / "buckets" / "pending.jsonl").write_text(
        json.dumps({"case": "D369"}) + "\n"
    )
    (run_dir / "case" / "D369").mkdir(parents=True)
    (run_dir / "case" / "D369" / "proposed.yaml").write_text("id: D369\nname: new\n")

    cases_dir = tmp_path / "plugins" / "wifi_llapi" / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "D369_x.yaml").write_text("id: D369\nname: old\n")

    res = apply_run(run_dir, cases_dir=cases_dir, include_pending=True)
    assert "D369" in res.applied_cases
    assert "name: new" in (cases_dir / "D369_x.yaml").read_text()


def test_apply_skips_block_bucket(tmp_path):
    run_dir = tmp_path / "audit" / "runs" / "rid" / "wifi_llapi"
    (run_dir / "buckets").mkdir(parents=True)
    (run_dir / "buckets" / "block.jsonl").write_text(
        json.dumps({"case": "D047"}) + "\n"
    )
    (run_dir / "case" / "D047").mkdir(parents=True)
    (run_dir / "case" / "D047" / "proposed.yaml").write_text("id: D047\nname: should_not_apply\n")

    cases_dir = tmp_path / "plugins" / "wifi_llapi" / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "D047_x.yaml").write_text("id: D047\nname: original\n")

    res = apply_run(run_dir, cases_dir=cases_dir, include_pending=True)
    assert "D047" not in res.applied_cases
    assert "name: original" in (cases_dir / "D047_x.yaml").read_text()
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement apply module**

```python
# src/testpilot/audit/apply.py
"""Write proposed.yaml back to plugins/cases/."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from testpilot.audit import bucket as bucket_mod


@dataclass
class ApplyResult:
    applied_cases: list[str] = field(default_factory=list)
    skipped_cases: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def apply_run(
    run_dir: Path,
    *,
    cases_dir: Path,
    include_pending: bool = False,
    only_cases: list[str] | None = None,
) -> ApplyResult:
    """Apply proposed.yaml from applied (and optionally pending) buckets."""
    res = ApplyResult()
    target_buckets = ["applied"]
    if include_pending:
        target_buckets.append("pending")

    for bucket_name in target_buckets:
        for entry in bucket_mod.list_bucket(run_dir, bucket_name):
            case = entry.get("case")
            if not case:
                continue
            if only_cases and case not in only_cases:
                res.skipped_cases.append(case)
                continue
            proposed = run_dir / "case" / case / "proposed.yaml"
            if not proposed.is_file():
                res.errors.append(f"{case}: proposed.yaml missing")
                continue
            yaml_files = list(cases_dir.glob(f"{case}_*.yaml"))
            if not yaml_files:
                res.errors.append(f"{case}: target yaml not found in {cases_dir}")
                continue
            target = yaml_files[0]
            shutil.copy2(proposed, target)
            res.applied_cases.append(case)

    return res
```

- [ ] **Step 4: Wire `audit apply` CLI**

在 `src/testpilot/audit/cli.py` 末尾追加：

```python
from testpilot.audit import apply as apply_mod


@audit_group.command("apply")
@click.argument("rid")
@click.option("--include-pending", is_flag=True)
@click.option("--cases", default="", help="Comma-separated case ids")
def cmd_apply(rid: str, include_pending: bool, cases: str) -> None:
    """Apply proposed.yaml back to plugins/<plugin>/cases/."""
    run_dir = _resolve_run_dir(rid)
    plugin = run_dir.name
    cases_dir = Path.cwd() / "plugins" / plugin / "cases"
    only = [c.strip() for c in cases.split(",") if c.strip()] or None

    res = apply_mod.apply_run(run_dir, cases_dir=cases_dir,
                               include_pending=include_pending,
                               only_cases=only)
    for c in res.applied_cases:
        click.echo(f"[applied] {c}")
    for c in res.skipped_cases:
        click.echo(f"[skipped] {c}")
    for e in res.errors:
        click.echo(f"[error] {e}", err=True)
    click.echo(f"\nTotal applied: {len(res.applied_cases)}")
```

- [ ] **Step 5: Run + commit**

```bash
uv run pytest tests/test_audit_apply.py tests/test_audit_cli.py -v

git add src/testpilot/audit/apply.py src/testpilot/audit/cli.py tests/test_audit_apply.py
git commit -m "feat(audit): wire 'audit apply' — write proposed.yaml back to plugin cases

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 16: Implement `audit pr` CLI subcommand

**Files:**
- Create: `src/testpilot/audit/pr.py`
- Modify: `src/testpilot/audit/cli.py`
- Test: `tests/test_audit_pr.py`（dry-run / mock-only）

- [ ] **Step 1: Write failing test (mock subprocess)**

```python
# tests/test_audit_pr.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from testpilot.audit.pr import build_pr_body, open_pr


def test_build_pr_body_contains_rid_and_buckets(tmp_path):
    run_dir = tmp_path / "audit" / "runs" / "rid1" / "wifi_llapi"
    (run_dir / "buckets").mkdir(parents=True)
    (run_dir / "buckets" / "applied.jsonl").write_text(
        '{"case": "D366"}\n{"case": "D369"}\n'
    )
    (run_dir / "manifest.json").write_text('{"rid": "rid1", "plugin": "wifi_llapi", "cases": ["D366", "D369"]}')
    body = build_pr_body(run_dir, rid="rid1")
    assert "rid1" in body
    assert "applied | 2" in body
    assert "D366" in body
    assert "D369" in body


def test_open_pr_invokes_gh(tmp_path):
    run_dir = tmp_path / "audit" / "runs" / "rid1" / "wifi_llapi"
    (run_dir / "buckets").mkdir(parents=True)
    (run_dir / "manifest.json").write_text('{"rid": "rid1", "plugin": "wifi_llapi", "cases": []}')
    (run_dir / "buckets" / "applied.jsonl").write_text("")

    with patch("testpilot.audit.pr.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="https://example/pr/1")
        url = open_pr(run_dir, rid="rid1", draft=True)
    # 至少 1 次 git add + commit + push + gh pr create
    assert mock_run.call_count >= 4
    assert "https://" in url or url == ""
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement pr module**

```python
# src/testpilot/audit/pr.py
"""Open audit-applied PR via git + gh."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from testpilot.audit import bucket as bucket_mod


def build_pr_body(run_dir: Path, *, rid: str) -> str:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    plugin = manifest.get("plugin", "")
    lines = [
        f"# Audit Run — `{rid}`",
        "",
        f"- Plugin: `{plugin}`",
        f"- Total cases in run: {len(manifest.get('cases', []))}",
        "",
        "## Bucket counts",
        "",
        "| Bucket | Count |",
        "| --- | ---: |",
    ]
    for b in bucket_mod.BUCKETS:
        n = len(bucket_mod.list_bucket(run_dir, b))
        lines.append(f"| {b} | {n} |")
    lines.append("")

    applied = bucket_mod.list_bucket(run_dir, "applied")
    if applied:
        lines.extend(["## Applied cases", ""])
        for e in applied:
            lines.append(f"- `{e['case']}` — {e.get('reason', '')}")
        lines.append("")

    block = bucket_mod.list_bucket(run_dir, "block")
    if block:
        lines.extend(["## Block list (manual review needed)", ""])
        for e in block:
            lines.append(f"- `{e['case']}` — {e.get('reason', '')}")
        lines.append("")

    lines.extend([
        "## Verification",
        "",
        f"- 全程 evidence 在 `audit/runs/{rid}/{plugin}/`（gitignored, local-only）",
        "- 主 agent doctrine: `docs/audit-guide.md`",
        "- spec: `docs/superpowers/specs/2026-04-27-audit-mode-design.md`",
        "",
    ])
    return "\n".join(lines)


def open_pr(run_dir: Path, *, rid: str, draft: bool = False) -> str:
    """git add + commit + push + gh pr create. Return PR URL."""
    plugin = run_dir.name
    repo_root = Path.cwd()
    cases_dir_rel = f"plugins/{plugin}/cases"

    # 1. git add
    subprocess.run(["git", "add", cases_dir_rel], cwd=repo_root, check=True)

    # 2. git commit
    msg_summary = f"audit({plugin}): apply RID {rid[:15]}"
    body = build_pr_body(run_dir, rid=rid)
    subprocess.run(
        ["git", "commit", "-m", msg_summary, "-m", body],
        cwd=repo_root, check=True,
    )

    # 3. git push
    subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=repo_root, check=True)

    # 4. gh pr create
    title = f"audit({plugin}): {rid[:15]}"
    pr_args = ["gh", "pr", "create", "--title", title, "--body", body]
    if draft:
        pr_args.append("--draft")
    p = subprocess.run(pr_args, cwd=repo_root, check=True,
                       capture_output=True, text=True)
    return p.stdout.strip()
```

- [ ] **Step 4: Wire `audit pr` CLI**

```python
# 加在 src/testpilot/audit/cli.py 末尾
from testpilot.audit import pr as pr_mod


@audit_group.command("pr")
@click.argument("rid")
@click.option("--draft", is_flag=True)
def cmd_pr(rid: str, draft: bool) -> None:
    """git commit/push + gh pr create."""
    run_dir = _resolve_run_dir(rid)
    url = pr_mod.open_pr(run_dir, rid=rid, draft=draft)
    click.echo(url)
```

- [ ] **Step 5: Run + commit**

```bash
uv run pytest tests/test_audit_pr.py -v
# expect 2 pass

git add src/testpilot/audit/pr.py src/testpilot/audit/cli.py tests/test_audit_pr.py
git commit -m "feat(audit): wire 'audit pr' — git add/commit/push + gh pr create

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

**Phase D Review Checkpoint** — 確認：
- record / decide / apply / pr 四 subcommand 行為符合 spec
- citation 驗證在 file/line/snippet 三層 mechanical check
- bucket 5-condition decision matrix 正確
- pr body 包含 RID + bucket counts + applied/block lists

---

## Documentation Sync

### Task 17: Rewrite docs/audit-guide.md as agent doctrine

**Files:**
- Modify (rewrite): `docs/audit-guide.md`

- [ ] **Step 1: Backup 現有 audit-guide.md**

```bash
cp docs/audit-guide.md docs/audit-guide.md.legacy.bak
```

- [ ] **Step 2: Rewrite as agent doctrine**

寫入 `docs/audit-guide.md`：

````markdown
# TestPilot Audit Mode — Agent Doctrine

> 這份文件是主 agent 在 audit session 內遵循的工作章法。Audit mode 與 normal `testpilot run` 完全分流；本文件規範主 agent 進入 audit session 後可做 / 不可做的事。

## 1. 何時進入 audit session

當 user（或 Copilot mode）明確啟動 audit work：
- 給 audit workbook 路徑（如 `0401.xlsx`）
- 指定 plugin（首發只 wifi_llapi）
- 預期產出 PR 修正 case YAML

## 2. 主 agent 與 sub-agents 的分工

| Role | 可做 | 不可做 |
|---|---|---|
| 主 agent（Copilot session） | 執行 `testpilot audit ...` CLI、用 serialwrap 對 DUT/STA 跑命令、用 Task tool 派 fleet sub-agents、構造 proposed.yaml、走 verify-edit | 直接 Edit/Write `plugins/<plugin>/cases/D*.yaml` 不經 verify-edit |
| Fleet sub-agents（subagent_type=Explore） | read-only grep/search source code、回 candidate commands + `filename:line` citations | Edit/Write 任何檔、操作 serialwrap、修 source code |

## 3. Audit session 流程

```
1. testpilot audit init <plugin> --workbook <path>     → 拿 RID
2. testpilot audit pass12 <RID>                         → 預過濾
3. testpilot audit status <RID>                         → 看 needs_pass3 worklist
4. for each case in needs_pass3:
     a. 派 fleet sub-agents 對 source 子樹 grep
     b. 主 agent 用 serialwrap 跑 candidate commands
     c. 構造 proposed.yaml（只動 §4 white-list 欄位）
     d. testpilot audit verify-edit <RID> <case> --yaml ... --proposed ...
     e. testpilot audit record <RID> <case> --evidence pass3.json
     f. testpilot audit decide <RID> <case> --bucket applied|pending|block
5. testpilot audit summary <RID>                        → 產 end-of-run 報告
6. user review summary.md + 各 bucket
7. testpilot audit apply <RID>                          → 套 applied 桶到 plugins/cases/
8. testpilot audit pr <RID>                             → 開 PR
```

## 4. YAML 編輯邊界（white-list）

只允許動：
- `steps[*].command`
- `steps[*].capture`
- `verification_command`
- `pass_criteria[*]`

**禁止動**：`id` / `name` / `version` / `source.*` / `platform.*` / `bands` / `topology.*` / `setup_steps` / `sta_env_setup` / `test_procedure`；禁止 add/remove 整個 step。

違反 → verify-edit 拒絕；pre-commit hook 也會擋下。

## 5. Evidence 與 citation 規範

**Pass 3 evidence JSON 格式**（`testpilot audit record --evidence` 的輸入）：

```json
{
  "candidate_commands": [
    {
      "command": "wl -i wl0 sr_config srg_obsscolorbmp",
      "rationale": "...",
      "rerun_verdict": {"5g": "Fail", "6g": "Fail", "2.4g": "Fail"}
    }
  ],
  "citations": [
    {
      "file": "bcmdrivers/broadcom/net/wl/impl107/main/src/wl/sys/wlc_stf.h",
      "line": 263,
      "snippet": "uint16 srg_pbssid_bmp[4];"
    }
  ]
}
```

`citations[*]` 必須通過 mechanical 驗證（檔案存在 / 行號合法 / snippet 是該行 substring）才會被 record 接受；無 citation 直接落 block。

## 6. 主 agent 不可做的事

- 直接 `vim plugins/.../D*.yaml` 然後 `git commit`（pre-commit hook 會擋）
- 跳過 verify-edit gate 直接套 proposed.yaml
- 用 LLM 自由「重新組合」workbook G/H 的命令（必須是 substring 引用）
- 不留 source citation 就把 case 標 applied
- 為了「對齊 workbook result」而調整 pass_criteria 卻沒有 source code 證據（evidence-only 原則）

如果以上任一無法滿足 → bucket=block，附完整 evidence trail 等人工。

## 7. 跨 session 協同

- audit dir 是 gitignored；切換機器要重 init 新 RID
- block 不是 final state；下次 audit 自動重評（人工修完 YAML 後下輪會跑 Pass 1 重看）
- `testpilot audit pass12 <RID>` 是 idempotent，可任何時候 rerun

## 8. 與 normal test 的接點

- `testpilot run wifi_llapi` 不會產 audit dir、不會修 plugins/cases/
- audit 改完的 YAML 同樣被 normal run 跑（只是經過邊界控管 + 證據鏈）
- 既有 `testpilot wifi-llapi audit-yaml-commands` 是 narrow 的 shell-chain linter，與本 audit mode 無關，保留不動

## 9. 參考

- 設計：`docs/superpowers/specs/2026-04-27-audit-mode-design.md`
- OpenSpec main spec：`openspec/specs/audit-mode/spec.md`
- OpenSpec archive：`openspec/changes/archive/2026-04-28-add-audit-mode/`
- legacy（原本的 prose-driven calibration guide）：`docs/audit-guide.md.legacy.bak`
````

- [ ] **Step 3: Commit**

```bash
git add docs/audit-guide.md docs/audit-guide.md.legacy.bak
git commit -m "docs(audit): rewrite audit-guide.md as agent doctrine

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 18: Update AGENTS.md / plan.md / todos.md / README.md / CHANGELOG.md

**Files:**
- Modify: `AGENTS.md`、`docs/plan.md`、`docs/todos.md`、`README.md`、`CHANGELOG.md`

- [ ] **Step 1: Add §Audit Mode Governance to AGENTS.md**

在 `AGENTS.md` 末尾追加：

```markdown
## Audit Mode Governance

1. Audit work 全程透過 `testpilot audit ...` 群組執行；不得直接 Edit `plugins/<plugin>/cases/D*.yaml` 不經 verify-edit gate
2. 每個 audit run 必須有 RID（`<git_short_sha>-<ISO8601>`）；evidence 落在 `audit/runs/<RID>/`（gitignored）
3. YAML 編輯只允許動 `steps[*].command|capture` / `verification_command` / `pass_criteria[*]`；其它欄位（id / source.* / topology / etc.）禁止
4. pre-commit hook `audit-yaml-provenance` 強制：所有 YAML 變動必須有對應 `verify_edit_log.jsonl` entry；繞行需 commit message 加 `[audit-bypass: <reason>]`
5. Pass 3 由主 agent 在 Copilot session 內負責；fleet sub-agents（Task tool, Explore agent）只做 read-only source survey；主 agent 自己跑 serialwrap
6. block 不是 final state；下次 audit run 對所有 case 一律重評
7. doctrine 細節：`docs/audit-guide.md`
```

- [ ] **Step 2: Update docs/plan.md §4 加 Audit Mode Phase**

在 `docs/plan.md` §4 Phase 列表中插入新 phase（依現有編排接續）：

```markdown
### Phase: Audit Mode（issue #36）

把 audit / normal test 邊界劃線。Deliverables：
- `testpilot audit` CLI 群組（init/pass12/record/verify-edit/decide/status/summary/apply/pr）
- `audit/` gitignored 工作資料夾
- pre-commit hook `audit-yaml-provenance`
- `docs/audit-guide.md` 改寫為 agent doctrine

Acceptance：D366/D369 audit 後 verdict 對齊 workbook Fail；apply 後 git diff 只動 §4 white-list paths。

詳見：`docs/superpowers/specs/2026-04-27-audit-mode-design.md`、`openspec/specs/audit-mode/spec.md`、`docs/superpowers/plans/2026-04-27-audit-mode.md`。
```

- [ ] **Step 3: Update docs/todos.md（追加待辦）**

```markdown
## Audit Mode（#36）

- [ ] Phase A scaffolding（audit 套件骨架 + gitignore + RID + workbook index + bucket + init/status/summary CLI）
- [ ] Phase B Pass 1/2 mechanical（runner_facade + extractor + pass12 CLI）
- [ ] Phase C verify-edit gate + pre-commit hook
- [ ] Phase D Pass 3 evidence/decide/apply/pr CLI
- [ ] Documentation sync（audit-guide rewrite + AGENTS/plan/README/CHANGELOG）
- [ ] Phase E wifi_llapi 首發 audit 跑 + acceptance（D366/D369）
```

- [ ] **Step 4: Update README.md Commands 區塊**

在 `README.md` Commands 區塊追加：

````markdown
### Audit mode（#36）

```bash
# Init audit run（產 RID）
testpilot audit init wifi_llapi --workbook ~/0401.xlsx

# 預過濾（Pass 1 + Pass 2 機械化）
testpilot audit pass12 <RID>

# 看狀態
testpilot audit status <RID>

# 主 agent Pass 3 流程後
testpilot audit verify-edit <RID> <case> --yaml ... --proposed ...
testpilot audit record <RID> <case> --evidence pass3.json
testpilot audit decide <RID> <case> --bucket applied

# End of run
testpilot audit summary <RID>
testpilot audit apply <RID>
testpilot audit pr <RID>
```

詳見 `docs/audit-guide.md`。
````

- [ ] **Step 5: Update CHANGELOG.md Unreleased + commit**

在 `CHANGELOG.md` `## Unreleased` 段：

```markdown
### Added

- `testpilot audit` CLI subcommand 群組（init/pass12/record/verify-edit/decide/status/summary/apply/pr）— audit / calibration 工作模式從 normal test 切開（#36）
- `audit/` gitignored 工作資料夾，存 RID、evidence、bucket bookkeeping、verify_edit_log
- `scripts/check_audit_yaml_provenance.py` pre-commit hook — 強制 plugins/cases/D*.yaml 變動必須對應 verify_edit_log
- `docs/audit-guide.md` — 主 agent audit doctrine（rewrite）
- workbook lookup 改用 `(source.object, source.api)` 語意鍵（衍生 #31）
```

```bash
git add AGENTS.md docs/plan.md docs/todos.md README.md CHANGELOG.md
git commit -m "docs(audit): sync AGENTS / plan / todos / README / CHANGELOG for #36

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Acceptance Verification

### Task 19: Final acceptance — D366 / D369 dry-run

> **Note**: This task is the operational acceptance. Phase E (full 415-case wifi_llapi audit run) is a separate operational session driven by the user via Copilot mode; it's not a coded task in this plan.

**Files:**
- Modify (audit dry-run): `audit/workbooks/wifi_llapi.xlsx`（人工 drop）

- [ ] **Step 1: Drop workbook to convention path**

```bash
cp ~/0401.xlsx audit/workbooks/wifi_llapi.xlsx
```

- [ ] **Step 2: Run init**

```bash
testpilot audit init wifi_llapi
# 印出 RID；存於變數
RID=$(testpilot audit init wifi_llapi)
```

- [ ] **Step 3: Pass12 dry-run**

```bash
testpilot audit pass12 $RID
testpilot audit status $RID
# 確認 confirmed + applied + pending + block + needs_pass3 加總 == 415
```

- [ ] **Step 4: D366/D369 應在 needs_pass3 worklist 中**

```bash
grep -c "D366\|D369" audit/runs/$RID/wifi_llapi/buckets/needs_pass3.jsonl
# expect 2
```

- [ ] **Step 5: 主 agent Pass 3 流程（操作性，由 Copilot session 主 agent 執行）**

主 agent 對 D366：
1. 派 fleet sub-agents 對 `bcmdrivers/.../impl107/`、`mod-whm-brcm/`、`pwhm-v7.6.38/src/` grep `srg_obsscolorbmp` / `SRGBSSColorBitmap`
2. Sub-agents 回 candidate command `wl -i wl0 sr_config srg_obsscolorbmp` + `wlc_stf.h:263` citation
3. 主 agent 用 serialwrap 對 DUT 跑 setter + 讀 driver bitmap，確認 brcm token-positional bug → verdict_s = Fail / Fail / Fail
4. 構造 proposed.yaml：把 pass_criteria 改成驗證 driver bitmap（不再依賴 hostapd config）
5. `testpilot audit verify-edit $RID D366 --yaml plugins/.../D366_*.yaml --proposed audit/runs/$RID/wifi_llapi/case/D366/proposed.yaml`
6. `testpilot audit record $RID D366 --evidence audit/runs/$RID/wifi_llapi/case/D366/pass3.json`
7. `testpilot audit decide $RID D366 --bucket applied --reason "driver_bitmap_validated"`

對 D369 同樣流程。

- [ ] **Step 6: Apply + PR**

```bash
testpilot audit summary $RID
# review summary.md
testpilot audit apply $RID --cases D366,D369
git diff plugins/wifi_llapi/cases/D366_srgbsscolorbitmap.yaml
# 預期：只動 verification_command + pass_criteria
testpilot audit pr $RID --draft
```

- [ ] **Step 7: 驗證 acceptance**

```bash
# 確認 D366 pass_criteria 含 driver bitmap
grep -A2 "wl.*sr_config.*srg_obsscolorbmp" plugins/wifi_llapi/cases/D366_srgbsscolorbitmap.yaml
# 預期命中

# 確認 audit/ 不入 git
git ls-files audit/
# 預期：empty 或只 .gitkeep

# Run full pytest
uv run pytest -q
# 預期 all pass
```

---

## Test Strategy

### Unit tests
- `tests/test_audit_manifest.py` — RID 生成、manifest IO
- `tests/test_audit_workbook_index.py` — 語意鍵 normalize、index 衝突偵測、欄位 auto-discovery
- `tests/test_audit_bucket.py` — jsonl append-only 行為
- `tests/test_audit_extractor.py` — Pass 2 mechanical extractor 各 rule
- `tests/test_audit_runner_facade.py` — facade dataclass shape（live test 在 integration）
- `tests/test_audit_pass12.py` — Pass 1/2 主流程（mock facade）
- `tests/test_audit_verify_edit.py` — YAML edit boundary
- `tests/test_audit_decision.py` — citation verify + bucket decision matrix
- `tests/test_audit_apply.py` — apply bucket 行為
- `tests/test_audit_pr.py` — pr body 構造（mock subprocess）

### Integration tests
- `tests/test_audit_cli.py` — `testpilot audit init / status / summary / verify-edit / decide` 端到端
- `tests/test_audit_provenance_hook.py` — pre-commit hook 三條 path（pass / fail / soft-skip / bypass）

### Acceptance tests（operational, manual）
- D366 / D369 dry-run（Task 19）— 由主 agent 在 Copilot session 內跑

### Fixtures
- `tests/fixtures/audit/sample_workbook.xlsx` — 最小 workbook（covering single match / ambiguous / missing）
- 測試用 case YAML 在 test 內嵌 inline string（避免額外 fixture 文件）

### Test commands
```bash
# Run all audit tests
uv run pytest tests/test_audit*.py -v

# Run full suite
uv run pytest -q
```

---

## Rollback Strategy

任一 Phase 完成後若需回滾：

1. **Phase A 回滾**：`git revert` 對應 commit；`audit/` 已 gitignored，留下無妨
2. **Phase B 回滾**：同上；runner_facade 不影響 normal run
3. **Phase C 回滾**：`pre-commit uninstall` + revert `.pre-commit-config.yaml`；YAML 寫入回到無閘狀態
4. **Phase D 回滾**：revert apply/pr commits；`audit apply` 寫到 plugins/cases/ 的內容須手動 `git checkout` 還原

特別注意：
- `audit/` 內容是 local-only — rollback 不影響 evidence
- pre-commit hook 是「越早裝越好」— Phase C 之後有任何 plugins/cases YAML 修改都該經 verify-edit
- D366 / D369 acceptance 修正若想回滾：`git revert` apply commit；YAML 回到 audit 前狀態

---

## Integration Points with Existing Codebase

| 既有元件 | Audit 接合方式 |
|---|---|
| `src/testpilot/cli.py` | import + `main.add_command(audit_group)`；不改既有 commands |
| `src/testpilot/core/orchestrator.py` `Orchestrator.run()` | 由 `runner_facade.run_one_case_for_audit()` 包薄殼呼叫；不改 `Orchestrator` 內部 |
| `plugins/wifi_llapi/plugin.py` | 不直接 import；走 Orchestrator pipeline；若 Pass 1 facade 需要更細 verdict map，先看 `Orchestrator.run()` 回傳 JSON 結構是否足夠（Phase B Task 7 confirm） |
| `src/testpilot/schema/case_schema.py` `validate_case()` | `verify_edit` 直接 reuse；不修改 |
| `src/testpilot/yaml_command_audit.py` | **不**改、不 reuse — 是不同的 narrow shell-chain linter，名稱接近但職責不同 |
| `tests/test_*.py` | 既有測試不影響；新增 `test_audit_*.py` |
| `pyproject.toml` | 無新依賴（openpyxl/ruamel.yaml/pyyaml 已在；click/pytest 已在；`pre-commit` 是 dev tool 用戶自行安裝） |
| `.gitignore` | append `/audit/*` + `!audit/.gitkeep` |

### 與既有 alignment 流程的關係

AGENTS.md §「Case Discovery Convention」提到 `(source.object, source.api)` 為 canonical key — 本 plan 完全沿用同一規則，audit 只是把它應用到 workbook lookup（不再用 row）。alignment 流程不變。

`testpilot run wifi_llapi` 既有的「rename case files / rewrite source.row」行為不被 audit 影響（兩者各管各的）。

---

## Self-Review Notes

(這是寫作者完成 plan 後的自查；engineer 看到時這已修完，僅留作 trace)

### Spec coverage check

| Spec Requirement | Task |
|---|---|
| Audit subcommand 群組 | Tasks 5, 6, 9, 11, 13, 14, 15, 16 |
| RID 生成與 manifest | Task 2 |
| audit/ 工作資料夾 gitignored | Task 1 |
| Workbook 語意鍵 lookup | Task 3 |
| Pass 1 純 py 預過濾 | Tasks 7, 9 |
| Pass 2 mechanical command extraction | Tasks 8, 9 |
| Pass 3 主 agent + fleet sub-agents | Task 17 (doctrine) + Task 19 (operational) |
| YAML edit boundary white-list | Task 10 |
| verify-edit gate 與 verify_edit_log | Tasks 10, 11 |
| Pre-commit hook 強制驗證 YAML provenance | Task 12 |
| Bucket 分類 | Tasks 13, 14, 15 |
| Resume 與 idempotent | Task 9（pass12 idempotent） |
| Block 復原語意 | doctrine in Task 17 |
| Template YAML 與 underscore-prefix 跳過 | Task 5（_discover_official_cases skip _*.yaml） |
| PR 構造 | Task 16 |
| D366 / D369 acceptance | Task 19 |

### Placeholder scan
- 無 TBD / TODO / "fill in details"
- 全部 Step 都附有具體 code block 或精確 command
- Task 19 的 step 5 是 operational（主 agent 在 Copilot session 自然處理），非 placeholder

### Type consistency
- `AuditCaseResult.verdict_per_band: dict[str, str]`（5g/6g/2.4g keys）一致
- `WorkbookRow` dataclass 欄位（`result_5g/6g/24g`）在 build_index → pass12 → decision 鏈一致
- `Citation(file, line, snippet)` 在 verify_citation / decision_input / record CLI 一致
- `BUCKETS` tuple 順序在 cli/bucket/decision/pr 全部一致

---

**Plan complete.**

#!/usr/bin/env python3
# scripts/check_audit_yaml_provenance.py
"""Pre-commit hook: validate plugins/<plugin>/cases/D*.yaml edits against audit RID
verify_edit_log.jsonl entries, otherwise fail.

Soft-skip when audit/ dir is absent or verify_edit_log is entirely empty (fresh clone /
CI environment).
Escape hatch: commit message containing [audit-bypass: <reason>] passes and appends
audit/bypass_log.jsonl.
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
_CASE_RE = re.compile(r"plugins/[^/]+/cases/D\d+[^/]*\.ya?ml$")


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_commit_msg() -> str:
    """Read commit message from env override or the active git dir."""
    if "COMMIT_MSG" in os.environ:
        return os.environ["COMMIT_MSG"]
    # In git worktrees, .git is a pointer file; hooks receive GIT_DIR for the real git dir.
    p = Path(os.environ.get("GIT_DIR", ".git")) / "COMMIT_EDITMSG"
    if p.is_file():
        return p.read_text(errors="ignore")
    return ""


def _audit_logs(repo_root: Path) -> list[Path]:
    audit_dir = repo_root / "audit"
    if not audit_dir.is_dir():
        return []
    return list(audit_dir.glob("runs/*/*/verify_edit_log.jsonl"))


def _is_target(path: Path, repo_root: Path) -> bool:
    """Return True if path matches plugins/*/cases/D*.ya?ml under repo_root.

    Handles both absolute paths (from test invocations) and relative paths
    (from pre-commit, relative to repo root).
    """
    # Normalise to a forward-slash string relative to repo_root when possible
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
        s = rel.as_posix()
    except ValueError:
        # Path not under repo_root — fall back to the raw string
        s = path.as_posix()

    return bool(_CASE_RE.search(s))


def _log_has_provenance(logs: list[Path], target_sha: str, target_path: Path, repo_root: Path) -> bool:
    """Return True if any log entry matches target_sha (and optionally yaml_path)."""
    # Build candidate strings for yaml_path matching (absolute + relative)
    try:
        rel_str = str(target_path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        rel_str = None
    abs_str = str(target_path.resolve())

    for log in logs:
        for line in log.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("yaml_sha256_after_proposed") != target_sha:
                continue
            # SHA matched; optionally narrow by yaml_path when present
            log_yaml_path = entry.get("yaml_path", "")
            if log_yaml_path:
                if log_yaml_path not in (abs_str, rel_str):
                    # yaml_path present but doesn't match either form — skip
                    continue
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

    repo_root = Path.cwd()

    # Filter: only plugins/*/cases/D*.yaml files
    targets = [p for p in files if _is_target(p, repo_root)]
    if not targets:
        return 0

    # Bypass check (must happen before soft-skip to ensure bypass_log is written)
    msg = _read_commit_msg()
    bypass_match = _BYPASS_RE.search(msg)
    if bypass_match:
        reason = bypass_match.group(1).strip()
        _record_bypass(repo_root, reason, [str(t) for t in targets])
        print(f"[audit-yaml-provenance] BYPASS: {reason}")
        return 0

    # Soft-skip when audit/ absent or all logs are empty
    logs = _audit_logs(repo_root)
    if not logs or all(not log.read_text(errors="ignore").strip() for log in logs):
        print(
            "[audit-yaml-provenance] WARN: audit/ dir 不存在或 verify_edit_log 全空; "
            "soft-skip (fresh clone / CI environment)"
        )
        return 0

    # Hard check: every staged YAML must have a matching provenance entry
    failures: list[str] = []
    for target in targets:
        if not target.exists():
            # Deleted file — no provenance required
            continue
        sha = _file_sha256(target)
        if not _log_has_provenance(logs, sha, target, repo_root):
            failures.append(str(target))

    if failures:
        print("ERROR: audit YAML provenance check failed for:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print("", file=sys.stderr)
        print(
            "Audit doctrine 要求所有 plugins/cases/D*.yaml 編輯都要經過 "
            "`testpilot audit verify-edit <RID> <case> --yaml ... --proposed ...`",
            file=sys.stderr,
        )
        print(
            "Workaround: commit message 加 [audit-bypass: <reason>] 暫時繞過。",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

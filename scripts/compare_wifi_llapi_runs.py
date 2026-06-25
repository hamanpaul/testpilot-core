#!/usr/bin/env python3
"""Compare wifi_llapi agent_trace runs for deterministic full-run verification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from testpilot.reporting.wifi_llapi_artifacts import resolve_trace_run_dir


def _default_reports_root() -> Path:
    return Path(__file__).resolve().parents[1] / "plugins" / "wifi_llapi" / "reports"


def _normalize_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        "attempt": attempt.get("attempt"),
        "timeout_seconds": attempt.get("timeout_seconds"),
        "status": attempt.get("status"),
        "comment": attempt.get("comment"),
    }


def _load_run_snapshot(run_dir: Path, *, strict: bool) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for path in sorted(run_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        case_id = str(payload.get("case_id", "")).strip()
        if not case_id:
            continue

        final = payload.get("final", {})
        normalized = {
            "status": final.get("status"),
            "attempts_used": final.get("attempts_used"),
            "comment": final.get("comment", ""),
        }
        if strict:
            attempts = payload.get("attempts", [])
            if isinstance(attempts, list):
                normalized["attempts"] = [
                    _normalize_attempt(item) for item in attempts if isinstance(item, dict)
                ]
        snapshot[case_id] = normalized
    return snapshot


def _compare_snapshots(
    baseline_name: str,
    baseline: dict[str, dict[str, Any]],
    target_name: str,
    target: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    baseline_cases = set(baseline)
    target_cases = set(target)
    missing_in_target = sorted(baseline_cases - target_cases)
    extra_in_target = sorted(target_cases - baseline_cases)
    mismatches: list[dict[str, Any]] = []

    for case_id in sorted(baseline_cases & target_cases):
        if baseline[case_id] == target[case_id]:
            continue
        mismatches.append(
            {
                "case_id": case_id,
                "baseline": baseline[case_id],
                "target": target[case_id],
            }
        )

    return {
        "baseline": baseline_name,
        "target": target_name,
        "baseline_case_count": len(baseline_cases),
        "target_case_count": len(target_cases),
        "missing_in_target": missing_in_target,
        "extra_in_target": extra_in_target,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "identical": not missing_in_target and not extra_in_target and not mismatches,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare wifi_llapi agent_trace runs and report deterministic mismatches."
    )
    parser.add_argument(
        "runs",
        nargs="+",
        help=(
            "Artifact folder names under plugins/wifi_llapi/reports, "
            "legacy run IDs under reports/agent_trace, or explicit artifact/trace directories."
        ),
    )
    parser.add_argument(
        "--trace-root",
        default=str(_default_reports_root()),
        help="Reports root directory containing artifact folders and legacy trace runs.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also compare per-attempt status/comment/timeout, not only final results.",
    )
    parser.add_argument(
        "--show-matches",
        type=int,
        default=20,
        help="Maximum mismatch entries to print per comparison.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    reports_root = Path(args.trace_root)
    run_dirs = [resolve_trace_run_dir(item, reports_root) for item in args.runs]
    run_names = [path.name for path in run_dirs]
    snapshots = {
        path.name: _load_run_snapshot(path, strict=bool(args.strict))
        for path in run_dirs
    }

    baseline_name = run_names[0]
    baseline = snapshots[baseline_name]
    comparisons = []
    identical = True
    for name in run_names[1:]:
        result = _compare_snapshots(baseline_name, baseline, name, snapshots[name])
        if result["mismatch_count"] > args.show_matches:
            result["mismatches"] = result["mismatches"][: args.show_matches]
            result["mismatches_truncated"] = True
        comparisons.append(result)
        identical = identical and bool(result["identical"])

    payload = {
        "trace_root": str(reports_root),
        "runs": run_names,
        "strict": bool(args.strict),
        "all_identical": identical,
        "comparisons": comparisons,
    }
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())

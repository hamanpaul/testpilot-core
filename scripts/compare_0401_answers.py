#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from testpilot.reporting.wifi_llapi_compare_0401 import (
    compare_run_against_0401,
    render_compare_markdown,
)
from testpilot.reporting.wifi_llapi_artifacts import resolve_trace_run_dir


def _default_reports_root() -> Path:
    return Path(__file__).resolve().parents[1] / "plugins" / "wifi_llapi" / "reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare wifi_llapi run results against a local answer workbook."
    )
    parser.add_argument(
        "runs",
        nargs="+",
        help=(
            "One or more artifact folder names under plugins/wifi_llapi/reports, "
            "legacy run IDs under reports/agent_trace, or explicit artifact/trace directories. "
            "Later runs override earlier case results."
        ),
    )
    parser.add_argument(
        "--answers",
        required=True,
        help="Path to the local-only answer workbook (for example ~/testpilot-local/0401.xlsx).",
    )
    parser.add_argument(
        "--cases-dir",
        default="plugins/wifi_llapi/cases",
        help="Case YAML directory.",
    )
    parser.add_argument(
        "--trace-root",
        default=str(_default_reports_root()),
        help="Reports root directory for resolving artifact folders and legacy trace runs.",
    )
    parser.add_argument(
        "--output-md",
        default="compare-0401.md",
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--output-json",
        default="compare-0401.json",
        help="JSON report output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    reports_root = Path(args.trace_root)
    run_dirs = [resolve_trace_run_dir(value, reports_root) for value in args.runs]
    answers = Path(args.answers)
    if not answers.is_absolute():
        answers = repo_root / answers
    cases_dir = Path(args.cases_dir)
    if not cases_dir.is_absolute():
        cases_dir = repo_root / cases_dir
    output_md = Path(args.output_md)
    if not output_md.is_absolute():
        output_md = repo_root / output_md
    output_json = Path(args.output_json)
    if not output_json.is_absolute():
        output_json = repo_root / output_json

    payload = compare_run_against_0401(
        run_dirs,
        answers,
        cases_dir=cases_dir,
    )
    output_md.write_text(render_compare_markdown(payload), encoding="utf-8")
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(output_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

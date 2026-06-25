#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

PLUGINS_ROOT = PROJECT_ROOT / "plugins"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wifi_llapi.reporting.wifi_llapi_inventory import (
    apply_wifi_llapi_inventory_reconcile_plan,
    build_wifi_llapi_inventory_reconcile_plan,
)


def _project_root() -> Path:
    return PROJECT_ROOT


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconcile wifi_llapi inventory")
    parser.add_argument(
        "--template-xlsx",
        type=Path,
        default=_project_root() / "plugins" / "wifi_llapi" / "reports" / "templates" / "wifi_llapi_template.xlsx",
        help="Workbook used as the official inventory source.",
    )
    parser.add_argument(
        "--cases-dir",
        type=Path,
        default=_project_root() / "plugins" / "wifi_llapi" / "cases",
        help="Discoverable wifi_llapi case directory.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_project_root(),
        help="Repository root for git history lookups.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply the reconcile plan in place.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    plan = build_wifi_llapi_inventory_reconcile_plan(
        args.template_xlsx,
        args.cases_dir,
        repo_root=args.repo_root,
    )

    mode = "apply" if args.apply else "dry-run"
    print(f"{mode}: {len(plan.actions)} actions, {len(plan.blockers)} blockers")
    for line in plan.to_lines():
        print(line)

    if plan.blockers:
        return 1
    if args.apply:
        apply_wifi_llapi_inventory_reconcile_plan(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build wifi_llapi Excel template report from source workbook."""

from __future__ import annotations

import argparse
from pathlib import Path

from testpilot.reporting.wifi_llapi_excel import ensure_template_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Wifi_LLAPI sheet and clear result/test command columns."
    )
    parser.add_argument(
        "--source-xlsx",
        required=True,
        help="Source workbook path (contains Wifi_LLAPI sheet).",
    )
    parser.add_argument(
        "--sheet",
        default="Wifi_LLAPI",
        help="Sheet name to extract (default: Wifi_LLAPI).",
    )
    parser.add_argument(
        "--out",
        default="plugins/wifi_llapi/reports/templates/wifi_llapi_template.xlsx",
        help="Output template path.",
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    manifest_path = out_path.with_suffix(".manifest.json")
    result = ensure_template_report(
        source_xlsx=args.source_xlsx,
        template_path=out_path,
        manifest_path=manifest_path,
        sheet_name=args.sheet,
    )
    print(f"Template: {result.template_path}")
    print(f"Sheet: {result.sheet_name}")
    print(f"Rows: {result.total_case_rows}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


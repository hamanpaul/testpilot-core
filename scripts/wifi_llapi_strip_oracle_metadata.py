#!/usr/bin/env python3
"""Strip wifi_llapi oracle metadata migration script.

This script requires ruamel.yaml for round-trip YAML preservation.
"""
from __future__ import annotations
import argparse
from pathlib import Path

try:
    from ruamel.yaml import YAML
except Exception as exc:
    raise SystemExit("ruamel.yaml is required for this migration script; please install it") from exc


def process_file(path: Path, apply: bool, yaml: YAML):
    text = path.read_text(encoding="utf-8")
    data = yaml.load(text)
    if data is None:
        data = {}
    removed = []
    # top-level results_reference
    if isinstance(data, dict) and "results_reference" in data:
        removed.append("results_reference")
        data.pop("results_reference", None)
    # source-level if mapping
    src = data.get("source") if isinstance(data, dict) else None
    if isinstance(src, dict):
        for key in ("baseline", "report", "sheet"):
            if key in src:
                removed.append(f"source.{key}")
                src.pop(key, None)
    # write if apply and removed
    if removed and apply:
        # write preserving formatting and quotes
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
    return removed


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Strip wifi_llapi oracle metadata")
    parser.add_argument("--apply", action="store_true", help="Apply changes in-place")
    parser.add_argument("--cases-dir", default="plugins/wifi_llapi/cases", help="Directory with case YAMLs")
    args = parser.parse_args(argv)

    yaml = YAML(typ='rt')
    yaml.preserve_quotes = True
    yaml.default_flow_style = False

    cases_dir = Path(args.cases_dir)
    files = sorted(cases_dir.glob("*.yaml")) if cases_dir.exists() else []
    scanned = 0
    modified = 0
    clean = 0
    errors = 0
    for p in files:
        scanned += 1
        try:
            removed = process_file(p, args.apply, yaml)
        except Exception as exc:
            # Treat unreadable/invalid YAML as error, not as already clean
            print(f"{p}: error: {exc}")
            errors += 1
            continue
        if removed:
            print(f"{p}: removed [{', '.join(removed)}]")
            modified += 1
        else:
            clean += 1
    # Extend summary with errors count to avoid misclassifying failures
    print(f"{scanned} files scanned, {modified} modified, {clean} already clean, {errors} errors")
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())

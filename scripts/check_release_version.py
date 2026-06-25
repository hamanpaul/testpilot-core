#!/usr/bin/env python3
"""Validate TestPilot release tag and version mirrors."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _runtime_version() -> str:
    init_text = (ROOT / "src" / "testpilot" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    if match is None:
        raise ValueError("Could not read __version__ from src/testpilot/__init__.py")
    return match.group(1)


def _pyproject_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _version_file() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def validate(tag: str) -> str:
    version = _version_file()
    if not SEMVER_RE.fullmatch(version):
        raise ValueError(f"VERSION must use Semantic Versioning X.Y.Z, got {version!r}")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"Release tag must use vX.Y.Z, got {tag!r}")

    pyproject_version = _pyproject_version()
    runtime_version = _runtime_version()
    if pyproject_version != version:
        raise ValueError(f"Version mismatch: VERSION={version} pyproject={pyproject_version}")
    if runtime_version != version:
        raise ValueError(f"Version mismatch: VERSION={version} __init__={runtime_version}")

    expected_tag = f"v{version}"
    if tag != expected_tag:
        raise ValueError(f"Tag {tag} does not match expected {expected_tag}")
    return f"Validated release tag {tag}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="Release tag to validate, e.g. v0.2.0")
    args = parser.parse_args()
    try:
        print(validate(args.tag))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

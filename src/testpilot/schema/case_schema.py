"""case_schema — YAML test case schema validation."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# 必要的頂層欄位
REQUIRED_TOP_KEYS = {"id", "name", "topology", "steps", "pass_criteria"}

# topology 必要欄位
REQUIRED_TOPOLOGY_KEYS = {"devices"}

# step 必要欄位
REQUIRED_STEP_KEYS = {"id", "action", "target"}
class CaseValidationError(Exception):
    """Test case YAML 驗證失敗。"""


def _validate_step_command(step: dict[str, Any], *, source: Path | str, index: int) -> None:
    command = step.get("command")
    if command is None:
        return
    if isinstance(command, str):
        return
    if isinstance(command, list) and all(isinstance(item, str) and item.strip() for item in command):
        return
    raise CaseValidationError(
        f"{source}: step[{index}] command must be a string or non-empty list of strings"
    )


def require_non_empty_string(
    value: Any,
    *,
    source: Path | str,
    field: str,
) -> str:
    if not isinstance(value, str):
        raise CaseValidationError(f"{source}: {field} must be a non-empty string")
    text = value.strip()
    if not text:
        raise CaseValidationError(f"{source}: {field} must be a non-empty string")
    return text


def validate_string_list(
    value: Any,
    *,
    source: Path | str,
    field: str,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise CaseValidationError(f"{source}: {field} must be a list of non-empty strings")
    if not value and not allow_empty:
        raise CaseValidationError(f"{source}: {field} must be a non-empty list of strings")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise CaseValidationError(
                f"{source}: {field}[{index}] must be a non-empty string"
            )
        normalized.append(item.strip())
    return normalized


def require_mapping(
    value: Any,
    *,
    source: Path | str,
    field: str,
    allow_empty: bool = True,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CaseValidationError(f"{source}: {field} must be a mapping")
    if not value and not allow_empty:
        raise CaseValidationError(f"{source}: {field} must be a non-empty mapping")
    return dict(value)


def require_string_mapping(
    value: Any,
    *,
    source: Path | str,
    field: str,
) -> dict[str, str]:
    mapping = require_mapping(value, source=source, field=field)
    normalized: dict[str, str] = {}
    for key, item in mapping.items():
        if not isinstance(key, str) or not key.strip():
            raise CaseValidationError(f"{source}: {field} keys must be non-empty strings")
        normalized[key.strip()] = require_non_empty_string(
            item,
            source=source,
            field=f"{field}.{key}",
        )
    return normalized


def require_bool(value: Any, *, source: Path | str, field: str) -> bool:
    if not isinstance(value, bool):
        raise CaseValidationError(f"{source}: {field} must be a boolean")
    return value


def load_case(
    path: Path | str,
    *,
    validator: Callable[[dict[str, Any], Path | str], None] | None = None,
) -> dict[str, Any]:
    """載入並驗證單一 test case YAML 檔。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"case file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise CaseValidationError(f"case must be a YAML mapping: {path}")

    (validator or validate_case)(data, path)
    return data


def validate_case(case: dict[str, Any], source: Path | str = "<unknown>") -> None:
    """驗證 test case dict 結構。"""
    missing = REQUIRED_TOP_KEYS - set(case.keys())
    if missing:
        raise CaseValidationError(f"{source}: missing required keys: {missing}")

    # topology
    topo = case["topology"]
    if not isinstance(topo, dict):
        raise CaseValidationError(f"{source}: topology must be a mapping")
    topo_missing = REQUIRED_TOPOLOGY_KEYS - set(topo.keys())
    if topo_missing:
        raise CaseValidationError(f"{source}: topology missing keys: {topo_missing}")

    # devices
    devices = topo["devices"]
    if not isinstance(devices, dict) or not devices:
        raise CaseValidationError(f"{source}: topology.devices must be a non-empty mapping")

    # steps
    steps = case["steps"]
    if not isinstance(steps, list) or not steps:
        raise CaseValidationError(f"{source}: steps must be a non-empty list")
    step_ids: set[str] = set()
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise CaseValidationError(f"{source}: step[{i}] must be a mapping")
        step_missing = REQUIRED_STEP_KEYS - set(step.keys())
        if step_missing:
            raise CaseValidationError(f"{source}: step[{i}] missing keys: {step_missing}")
        _validate_step_command(step, source=source, index=i)
        sid = step["id"]
        if sid in step_ids:
            raise CaseValidationError(f"{source}: duplicate step id: {sid}")
        step_ids.add(sid)
        # depends_on 參照檢查
        dep = step.get("depends_on")
        if dep and dep not in step_ids:
            raise CaseValidationError(f"{source}: step[{i}] depends_on '{dep}' not found before it")

    # pass_criteria
    criteria = case["pass_criteria"]
    if not isinstance(criteria, list) or not criteria:
        raise CaseValidationError(f"{source}: pass_criteria must be a non-empty list")


def load_cases_dir(
    cases_dir: Path | str,
    *,
    validator: Callable[[dict[str, Any], Path | str], None] | None = None,
) -> list[dict[str, Any]]:
    """載入 cases/ 目錄下所有 .yaml/.yml 檔（排除 _template）。"""
    cases_dir = Path(cases_dir)
    cases: list[dict[str, Any]] = []
    if not cases_dir.is_dir():
        return cases
    for p in sorted(cases_dir.glob("*.y*ml")):
        if p.stem.startswith("_"):
            continue
        try:
            cases.append(load_case(p, validator=validator))
        except Exception:
            log.exception("failed to load case: %s", p)
    return cases

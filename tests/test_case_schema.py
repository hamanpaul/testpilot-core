"""Test YAML case schema validation."""

import pytest
from testpilot.schema.case_schema import (
    CaseValidationError,
    validate_case,
)


def _minimal_case(**overrides):
    base = {
        "id": "test-1",
        "name": "test case",
        "topology": {"devices": {"DUT": {"role": "ap"}}},
        "steps": [{"id": "s1", "action": "exec", "target": "DUT"}],
        "pass_criteria": [{"field": "x", "operator": "==", "value": "y"}],
    }
    base.update(overrides)
    return base


def test_valid_case():
    validate_case(_minimal_case())


def test_missing_top_key():
    case = _minimal_case()
    del case["steps"]
    with pytest.raises(CaseValidationError, match="missing required keys"):
        validate_case(case)


def test_empty_devices():
    case = _minimal_case(topology={"devices": {}})
    with pytest.raises(CaseValidationError, match="non-empty mapping"):
        validate_case(case)


def test_duplicate_step_id():
    case = _minimal_case(steps=[
        {"id": "s1", "action": "exec", "target": "DUT"},
        {"id": "s1", "action": "exec", "target": "DUT"},
    ])
    with pytest.raises(CaseValidationError, match="duplicate step id"):
        validate_case(case)


def test_depends_on_ordering():
    case = _minimal_case(steps=[
        {"id": "s1", "action": "exec", "target": "DUT", "depends_on": "s2"},
        {"id": "s2", "action": "exec", "target": "DUT"},
    ])
    with pytest.raises(CaseValidationError, match="not found before"):
        validate_case(case)


def test_step_command_accepts_non_empty_string_list():
    case = _minimal_case(steps=[
        {"id": "s1", "action": "exec", "target": "DUT", "command": ["echo one", "echo two"]},
    ])
    validate_case(case)


def test_step_command_rejects_non_string_list_items():
    case = _minimal_case(steps=[
        {"id": "s1", "action": "exec", "target": "DUT", "command": ["echo one", 2]},
    ])
    with pytest.raises(CaseValidationError, match="command must be a string or non-empty list of strings"):
        validate_case(case)


def test_step_command_rejects_empty_string_list_items():
    case = _minimal_case(steps=[
        {"id": "s1", "action": "exec", "target": "DUT", "command": ["echo one", "   "]},
    ])
    with pytest.raises(CaseValidationError, match="command must be a string or non-empty list of strings"):
        validate_case(case)

"""Tests that testpilot.api exposes the symbols required by the audit fold-out (P4 Task 1).

Guards:
- validate_case, CaseValidationError, case_d_number in __all__ and importable
- run_one_case in __all__ and importable as a ctx-free callable
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import testpilot.api as api


def test_validate_case_in_all():
    assert "validate_case" in api.__all__


def test_case_validation_error_in_all():
    assert "CaseValidationError" in api.__all__


def test_case_d_number_in_all():
    assert "case_d_number" in api.__all__


def test_case_d_number_importable():
    assert hasattr(api, "case_d_number")
    assert callable(api.case_d_number)


def test_case_d_number_basic():
    assert api.case_d_number("D042") == "D042"
    assert api.case_d_number("wifi_llapi-D001-foo") == "D001"
    assert api.case_d_number("no_number") == ""


def test_run_one_case_in_all():
    assert "run_one_case" in api.__all__


def test_run_one_case_importable():
    assert hasattr(api, "run_one_case")
    assert callable(api.run_one_case)


def test_run_one_case_signature():
    """run_one_case must accept (plugin, case_id, *, repo_root=None) without click ctx."""
    sig = inspect.signature(api.run_one_case)
    params = sig.parameters
    assert "plugin" in params
    assert "case_id" in params
    repo_root_param = params.get("repo_root")
    assert repo_root_param is not None
    assert repo_root_param.default is None


def test_run_one_case_delegates_to_orchestrator():
    """run_one_case should instantiate Orchestrator and call .run(plugin, case_ids=[case_id])."""
    fake_result = {"status": "ok", "cases": []}
    mock_orch = MagicMock()
    mock_orch.run.return_value = fake_result

    with patch("testpilot.core.api_entry.Orchestrator", return_value=mock_orch) as MockOrch:
        result = api.run_one_case("wifi_llapi", "D001", repo_root=Path("/fake/root"))

    MockOrch.assert_called_once_with(project_root=Path("/fake/root"))
    mock_orch.run.assert_called_once_with("wifi_llapi", case_ids=["D001"])
    assert result == fake_result

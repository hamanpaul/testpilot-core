"""Tests for verdict-only case utility behavior."""

from __future__ import annotations

import pytest

from testpilot.core.case_utils import case_band_results


def test_case_band_results_uses_verdict_only_status():
    case = {
        "bands": ["5g", "2.4g"],
        "results_reference": {
            "v4.0.3": {"5g": "Fail", "6g": "Skip", "2.4g": "Not Supported"},
        },
    }

    assert case_band_results(case, True) == ("Pass", "N/A", "Pass")
    assert case_band_results(case, False) == ("Fail", "N/A", "Fail")


def test_case_band_results_defaults_to_all_bands_when_unspecified():
    assert case_band_results({}, True) == ("Pass", "Pass", "Pass")


def test_case_utils_no_longer_exports_baseline_results_reference():
    with pytest.raises(ImportError):
        exec("from testpilot.core.case_utils import baseline_results_reference", {})

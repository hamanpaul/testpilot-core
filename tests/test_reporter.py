"""Tests for the MD / JSON report projectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from testpilot.reporting.reporter import (
    IReporter,
    JsonReporter,
    MarkdownReporter,
    generate_reports,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_META: dict[str, Any] = {
    "title": "WiFi LLAPI Run",
    "date": "2025-07-15",
    "tester": "bot",
    "testbed": "lab-01",
    "dut_model": "AX-9000",
    "firmware_version": "1.2.3",
    "plugin": "wifi_llapi",
    "timing": [
        {
            "metric": "suite run",
            "started_at": "2025-07-15T10:00:00+08:00",
            "finished_at": "2025-07-15T10:02:00+08:00",
            "duration_seconds": 120,
        },
        {
            "metric": "environment buildup",
            "started_at": "2025-07-15T10:00:00+08:00",
            "finished_at": "2025-07-15T10:00:15+08:00",
            "duration_seconds": 15,
        },
    ],
}

_CASES: list[dict[str, Any]] = [
    {
        "case_id": "D001",
        "source_row": 5,
        "executed_test_command": "wl -i wl0 status",
        "command_output": "Status: connected",
        "result_5g": "pass",
        "result_6g": "fail",
        "result_24g": "pass",
        "diagnostic_status": "FailEnv",
        "comment": "6G radio off",
        "tester": "bot",
        "case_started_at": "2025-07-15T10:00:15+08:00",
        "case_finished_at": "2025-07-15T10:01:00+08:00",
        "case_duration_seconds": 45,
    },
    {
        "case_id": "D002",
        "source_row": 6,
        "executed_test_command": "wl -i wl1 assoclist",
        "command_output": "AA:BB:CC:DD:EE:FF",
        "result_5g": "pass",
        "result_6g": "not_supported",
        "result_24g": "pass",
        "diagnostic_status": "PassAfterRemediation",
        "comment": "",
        "tester": "bot",
        "case_started_at": "2025-07-15T10:01:00+08:00",
        "case_finished_at": "2025-07-15T10:02:00+08:00",
        "case_duration_seconds": 60,
    },
]


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_markdown_reporter_satisfies_protocol() -> None:
    reporter: IReporter = MarkdownReporter()
    assert callable(getattr(reporter, "generate", None))


def test_json_reporter_satisfies_protocol() -> None:
    reporter: IReporter = JsonReporter()
    assert callable(getattr(reporter, "generate", None))


# ---------------------------------------------------------------------------
# MarkdownReporter
# ---------------------------------------------------------------------------


class TestMarkdownReporter:
    def test_generates_valid_markdown_with_summary_table(self, tmp_path: Path) -> None:
        out = tmp_path / "report.md"
        result = MarkdownReporter().generate(_CASES, _META, out)
        assert result == out
        text = out.read_text(encoding="utf-8")
        # Header
        assert "# WiFi LLAPI Run" in text
        assert "**Date**: 2025-07-15" in text
        assert "**Tester**: bot" in text
        # Summary table
        assert "| case_id |" in text
        assert "| D001 |" in text
        assert "| D002 |" in text
        assert "diagnostic_status" in text
        assert "## Timing" in text
        assert "## Suite summary" in text
        assert "## Per-case timing" in text
        assert "| pass_cases | failed_cases | other_cases | pass_rate |" in text
        assert "| 0 | 1 | 1 | `0.00%` |" in text
        assert "| D001 | `2025-07-15T10:01:00+08:00` | `00:00:45` |" in text

    def test_case_details_collapsible(self, tmp_path: Path) -> None:
        out = tmp_path / "report.md"
        MarkdownReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "<details><summary>D001</summary>" in text
        assert "wl -i wl0 status" in text

    def test_empty_cases(self, tmp_path: Path) -> None:
        out = tmp_path / "report.md"
        MarkdownReporter().generate([], _META, out)
        text = out.read_text(encoding="utf-8")
        assert "# WiFi LLAPI Run" in text
        # Table header present, but no data rows beyond header/sep
        assert "| case_id |" in text

    def test_missing_optional_fields(self, tmp_path: Path) -> None:
        minimal: list[dict[str, Any]] = [{"case_id": "D097", "source_row": 99}]
        out = tmp_path / "report.md"
        MarkdownReporter().generate(minimal, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "D097" in text

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "dir" / "report.md"
        MarkdownReporter().generate(_CASES, _META, out)
        assert out.exists()


# ---------------------------------------------------------------------------
# JsonReporter
# ---------------------------------------------------------------------------


class TestJsonReporter:
    def test_generates_valid_json_structure(self, tmp_path: Path) -> None:
        out = tmp_path / "report.json"
        result = JsonReporter().generate(_CASES, _META, out)
        assert result == out
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert "meta" in payload
        assert "cases" in payload
        assert "summary" in payload

    def test_summary_counts(self, tmp_path: Path) -> None:
        out = tmp_path / "report.json"
        JsonReporter().generate(_CASES, _META, out)
        summary = json.loads(out.read_text(encoding="utf-8"))["summary"]
        assert summary["total_cases"] == 2
        assert summary["pass"] == 4
        assert summary["fail"] == 1
        assert summary["not_supported"] == 1
        assert summary["error"] == 0
        assert summary["diagnostic_status"] == {
            "FailEnv": 1,
            "PassAfterRemediation": 1,
        }
        assert summary["pass_cases"] == 0
        assert summary["failed_cases"] == 1
        assert summary["other_cases"] == 1
        assert summary["pass_rate"] == 0.0

    def test_meta_preserved(self, tmp_path: Path) -> None:
        out = tmp_path / "report.json"
        JsonReporter().generate(_CASES, _META, out)
        meta = json.loads(out.read_text(encoding="utf-8"))["meta"]
        assert meta["tester"] == "bot"
        assert meta["dut_model"] == "AX-9000"

    def test_empty_cases(self, tmp_path: Path) -> None:
        out = tmp_path / "report.json"
        JsonReporter().generate([], _META, out)
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["cases"] == []
        assert payload["summary"]["total_cases"] == 0

    def test_missing_optional_fields(self, tmp_path: Path) -> None:
        minimal: list[dict[str, Any]] = [{"case_id": "D097"}]
        out = tmp_path / "report.json"
        JsonReporter().generate(minimal, _META, out)
        cases = json.loads(out.read_text(encoding="utf-8"))["cases"]
        assert cases[0]["case_id"] == "D097"


# ---------------------------------------------------------------------------
# generate_reports()
# ---------------------------------------------------------------------------


class TestGenerateReports:
    def test_creates_both_formats(self, tmp_path: Path) -> None:
        paths = generate_reports(_CASES, _META, tmp_path)
        assert len(paths) == 2
        suffixes = {p.suffix for p in paths}
        assert suffixes == {".md", ".json"}
        assert all(p.exists() for p in paths)

    def test_honors_explicit_output_stem(self, tmp_path: Path) -> None:
        meta = dict(_META)
        meta["output_stem"] = "20250715_FW-TEST_wifi_LLAPI_20250715T100000000000"
        paths = generate_reports(_CASES, meta, tmp_path)
        assert {p.name for p in paths} == {
            "20250715_FW-TEST_wifi_LLAPI_20250715T100000000000.md",
            "20250715_FW-TEST_wifi_LLAPI_20250715T100000000000.json",
        }

    def test_single_format(self, tmp_path: Path) -> None:
        paths = generate_reports(_CASES, _META, tmp_path, formats=("json",))
        assert len(paths) == 1
        assert paths[0].suffix == ".json"

    def test_unsupported_format_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unsupported report format"):
            generate_reports(_CASES, _META, tmp_path, formats=("pdf",))

    def test_empty_cases_both_formats(self, tmp_path: Path) -> None:
        paths = generate_reports([], _META, tmp_path)
        assert len(paths) == 2
        assert all(p.exists() for p in paths)


# ---------------------------------------------------------------------------
# Task 4 – precomputed wifi_llapi_summary
# ---------------------------------------------------------------------------

_PRECOMPUTED_SUMMARY: dict[str, Any] = {
    "policy_version": "wifi_llapi_summary_v1",
    "band_category": [
        {
            "band_key": "result_5g",
            "band_label": "5G",
            "category": "WiFi.AccessPoint",
            "total_items": 2,
            "tested_items": 2,
            "pass": 1,
            "fail": 1,
            "to_be_tested": 0,
            "not_supported": 0,
            "skip": 0,
            "pass_rate": 0.5,
            "progress": 1.0,
        },
        {
            "band_key": "result_5g",
            "band_label": "5G",
            "category": "WiFi.EndPoint",
            "total_items": 0,
            "tested_items": 0,
            "pass": 0,
            "fail": 0,
            "to_be_tested": 0,
            "not_supported": 0,
            "skip": 0,
            "pass_rate": None,
            "progress": None,
        },
    ],
    "bucket_totals": {
        "result_5g": {
            "band_key": "result_5g",
            "band_label": "5G",
            "total_items": 2,
            "tested_items": 2,
            "pass": 1,
            "fail": 1,
            "to_be_tested": 0,
            "not_supported": 0,
            "skip": 0,
            "pass_rate": 0.5,
            "progress": 1.0,
        },
    },
    "raw_totals": {"result_5g": {"Pass": 1, "Fail": 1}},
    "diagnostic_status": {},
    "per_case": [],
}


def test_json_reporter_uses_precomputed_wifi_llapi_summary(
    tmp_path: Path,
) -> None:
    meta_with_summary: dict[str, Any] = {
        **_META,
        "plugin_summary": _PRECOMPUTED_SUMMARY,
    }
    out = tmp_path / "report.json"
    JsonReporter().generate(_CASES, meta_with_summary, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    summary = payload["summary"]
    assert summary["policy_version"] == "wifi_llapi_summary_v1"
    # band_category row for 5G/WiFi.AccessPoint: pass=1, fail=1 → pass_rate=0.5
    bc_rows: list[dict[str, Any]] = summary["band_category"]
    ap_5g = next(
        (r for r in bc_rows if r["band_key"] == "result_5g" and r["category"] == "WiFi.AccessPoint"),
        None,
    )
    assert ap_5g is not None
    assert ap_5g["pass"] == 1
    assert ap_5g["fail"] == 1


def test_markdown_reporter_renders_hybrid_summary(tmp_path: Path) -> None:
    meta_with_summary: dict[str, Any] = {
        **_META,
        "plugin_summary": _PRECOMPUTED_SUMMARY,
    }
    out = tmp_path / "report.md"
    MarkdownReporter().generate(_CASES, meta_with_summary, out)
    text = out.read_text(encoding="utf-8")
    assert "## WiFi LLAPI Hybrid summary" in text
    # Table header contains band/category/count columns
    assert "Band" in text
    assert "Category" in text
    assert "Pass Rate" in text
    # Row for 5G/WiFi.AccessPoint with pass_rate 50.00%
    assert "50.00%" in text
    assert "WiFi.AccessPoint" in text

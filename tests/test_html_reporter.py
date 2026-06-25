"""Tests for the HTML report generator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from testpilot.reporting.html_reporter import HtmlReporter
from testpilot.reporting.reporter import IReporter, generate_reports

# ---------------------------------------------------------------------------
# Fixtures — reuse the same data shapes as test_reporter.py
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


def test_html_reporter_satisfies_protocol() -> None:
    reporter: IReporter = HtmlReporter()
    assert callable(getattr(reporter, "generate", None))


# ---------------------------------------------------------------------------
# Basic generation
# ---------------------------------------------------------------------------


class TestHtmlReporter:
    def test_generates_valid_html(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        result = HtmlReporter().generate(_CASES, _META, out)
        assert result == out
        text = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in text
        assert "<html" in text
        assert "</html>" in text
        assert "WiFi LLAPI Run" in text

    def test_contains_meta_fields(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "2025-07-15" in text
        assert "bot" in text
        assert "lab-01" in text
        assert "AX-9000" in text
        assert "1.2.3" in text

    def test_contains_kpi_strip(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "Total Cases" in text
        assert "Pass Cases" in text
        assert "Failed Cases" in text
        assert "Pass Rate" in text

    def test_kpi_strip_keeps_counts_with_precomputed_wifi_summary(self, tmp_path: Path) -> None:
        cases = [
            {"case_id": "D001", "result_5g": "Pass", "result_6g": "Pass", "result_24g": "Pass"},
            {"case_id": "D002", "result_5g": "Fail", "result_6g": "Pass", "result_24g": "Pass"},
            {"case_id": "D003", "result_5g": "Skip", "result_6g": "Skip", "result_24g": "Skip"},
        ]
        meta = {
            **_META,
            "plugin_summary": {
                "policy_version": "wifi_llapi_summary_v1",
                "band_category": [],
                "bucket_totals": {},
                "raw_totals": {},
            },
        }
        out = tmp_path / "report.html"

        HtmlReporter().generate(cases, meta, out)

        text = out.read_text(encoding="utf-8")
        assert '<div class="label">Total Cases</div><div class="value">3</div>' in text
        assert '<div class="label">Pass Cases</div><div class="value">1</div>' in text
        assert '<div class="label">Failed Cases</div><div class="value">1</div>' in text
        assert '<div class="label">Other Cases</div><div class="value">1</div>' in text
        assert '<div class="label">Pass Rate</div><div class="value">50.00%</div>' in text

    def test_contains_summary_table(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "D001" in text
        assert "D002" in text
        assert "FailEnv" in text

    def test_contains_timing_section(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "Timing" in text
        assert "suite run" in text
        assert "environment buildup" in text

    def test_contains_case_details(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "<details" in text
        assert "wl -i wl0 status" in text
        assert "Status: connected" in text

    def test_contains_per_case_timing(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "Per-case Timing" in text
        assert "00:00:45" in text
        assert "00:01:00" in text

    def test_verdict_chips(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "#1AB39F" in text  # success/pass color
        assert "#DC3545" in text  # error/fail color

    def test_overall_status_chips(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "Failed" in text

    def test_case_anchor_links(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        assert 'href="#D001"' in text
        assert 'id="D001"' in text

    def test_suite_summary_section(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "Suite Summary" in text
        assert "Diagnostic Status" in text

    def test_empty_cases(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate([], _META, out)
        text = out.read_text(encoding="utf-8")
        assert "WiFi LLAPI Run" in text
        assert "Total Cases" in text
        # Should not have case details section
        assert "Case Details" not in text

    def test_missing_optional_fields(self, tmp_path: Path) -> None:
        minimal: list[dict[str, Any]] = [{"case_id": "D097", "source_row": 99}]
        out = tmp_path / "report.html"
        HtmlReporter().generate(minimal, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "D097" in text

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "dir" / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        assert out.exists()


# ---------------------------------------------------------------------------
# HTML escaping / security
# ---------------------------------------------------------------------------


class TestHtmlEscaping:
    def test_escapes_script_tags_in_command(self, tmp_path: Path) -> None:
        cases: list[dict[str, Any]] = [
            {
                "case_id": "D999",
                "executed_test_command": '<script>alert("xss")</script>',
                "command_output": '<img onerror="alert(1)">',
                "result_5g": "pass",
                "comment": "test <b>bold</b>",
            },
        ]
        out = tmp_path / "report.html"
        HtmlReporter().generate(cases, {"title": "XSS Test"}, out)
        text = out.read_text(encoding="utf-8")
        assert "<script>" not in text
        assert "&lt;script&gt;" in text
        assert '<img onerror="alert(1)">' not in text
        assert "&lt;img onerror=" in text
        assert "<b>bold</b>" not in text
        assert "&lt;b&gt;bold&lt;/b&gt;" in text

    def test_escapes_special_chars_in_title(self, tmp_path: Path) -> None:
        out = tmp_path / "report.html"
        HtmlReporter().generate([], {"title": "Test <&> Report"}, out)
        text = out.read_text(encoding="utf-8")
        assert "Test &lt;&amp;&gt; Report" in text

    def test_escapes_ampersand_in_output(self, tmp_path: Path) -> None:
        cases: list[dict[str, Any]] = [
            {
                "case_id": "D100",
                "command_output": "foo && bar & baz",
                "result_5g": "pass",
            },
        ]
        out = tmp_path / "report.html"
        HtmlReporter().generate(cases, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "foo &amp;&amp; bar &amp; baz" in text

    def test_unicode_chinese_content(self, tmp_path: Path) -> None:
        cases: list[dict[str, Any]] = [
            {
                "case_id": "D888",
                "comment": "測試中文內容",
                "result_5g": "pass",
            },
        ]
        out = tmp_path / "report.html"
        HtmlReporter().generate(cases, {"title": "中文報告"}, out)
        text = out.read_text(encoding="utf-8")
        assert "測試中文內容" in text
        assert "中文報告" in text


# ---------------------------------------------------------------------------
# Integration with generate_reports()
# ---------------------------------------------------------------------------


class TestGenerateReportsHtml:
    def test_html_format_via_generate_reports(self, tmp_path: Path) -> None:
        paths = generate_reports(_CASES, _META, tmp_path, formats=("html",))
        assert len(paths) == 1
        assert paths[0].suffix == ".html"
        assert paths[0].exists()
        text = paths[0].read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in text

    def test_all_three_formats(self, tmp_path: Path) -> None:
        paths = generate_reports(
            _CASES, _META, tmp_path, formats=("md", "json", "html")
        )
        assert len(paths) == 3
        suffixes = {p.suffix for p in paths}
        assert suffixes == {".md", ".json", ".html"}

    def test_unsupported_format_still_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unsupported report format"):
            generate_reports(_CASES, _META, tmp_path, formats=("pdf",))

    def test_honors_explicit_output_stem(self, tmp_path: Path) -> None:
        meta = dict(_META)
        meta["output_stem"] = "test_report_stem"
        paths = generate_reports(_CASES, meta, tmp_path, formats=("html",))
        assert paths[0].name == "test_report_stem.html"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_timing_data(self, tmp_path: Path) -> None:
        meta = dict(_META)
        del meta["timing"]
        cases: list[dict[str, Any]] = [{"case_id": "D050", "result_5g": "pass"}]
        out = tmp_path / "report.html"
        HtmlReporter().generate(cases, meta, out)
        text = out.read_text(encoding="utf-8")
        assert "Timing data unavailable" in text or "Timing" in text

    def test_remediation_history(self, tmp_path: Path) -> None:
        cases: list[dict[str, Any]] = [
            {
                "case_id": "D050",
                "result_5g": "fail",
                "remediation_history": [
                    {
                        "attempt_index": 1,
                        "decision_source": "builtin-fallback",
                        "summary": "sta reconnect failed",
                        "applied": False,
                    },
                ],
            },
        ]
        out = tmp_path / "report.html"
        HtmlReporter().generate(cases, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "Remediation History" in text
        assert "sta reconnect failed" in text
        assert "builtin-fallback" in text

    def test_log_references(self, tmp_path: Path) -> None:
        cases: list[dict[str, Any]] = [
            {
                "case_id": "D070",
                "result_5g": "pass",
                "dut_log_lines": "L100-L200",
                "sta_log_lines": "L50-L80",
            },
        ]
        out = tmp_path / "report.html"
        HtmlReporter().generate(cases, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "L100-L200" in text
        assert "L50-L80" in text
        assert "Log Reference" in text

    def test_log_snippets_from_artifact_logs(self, tmp_path: Path) -> None:
        (tmp_path / "DUT.log").write_text(
            "dut line 1\ndut line 2\ndut line 3\ndut line 4\n",
            encoding="utf-8",
        )
        (tmp_path / "STA.log").write_text(
            "sta line 1\nsta line 2\nsta line 3\n",
            encoding="utf-8",
        )
        cases: list[dict[str, Any]] = [
            {
                "case_id": "D071",
                "result_5g": "fail",
                "dut_log_lines": "L2-L3",
                "sta_log_lines": "L1-L2",
            },
        ]
        out = tmp_path / "report.html"
        HtmlReporter().generate(cases, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "DUT Log Snippet" in text
        assert "STA Log Snippet" in text
        assert "L2: dut line 2" in text
        assert "L3: dut line 3" in text
        assert "L1: sta line 1" in text
        assert "L2: sta line 2" in text

    def test_log_snippets_truncate_large_ranges(self, tmp_path: Path) -> None:
        dut_lines = "\n".join(f"dut line {idx}" for idx in range(1, 201)) + "\n"
        (tmp_path / "DUT.log").write_text(dut_lines, encoding="utf-8")
        cases: list[dict[str, Any]] = [
            {
                "case_id": "D072",
                "result_5g": "fail",
                "dut_log_lines": "L1-L200",
            },
        ]
        out = tmp_path / "report.html"
        HtmlReporter().generate(cases, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "Snippet truncated for readability" in text
        assert "L1: dut line 1" in text
        assert "L60: dut line 60" in text
        assert "... (80 lines omitted) ..." in text
        assert "L141: dut line 141" in text
        assert "L200: dut line 200" in text

    def test_multiline_command_output(self, tmp_path: Path) -> None:
        cases: list[dict[str, Any]] = [
            {
                "case_id": "D055",
                "result_5g": "pass",
                "executed_test_command": "line1\nline2\nline3",
                "command_output": "out1\nout2\nout3",
            },
        ]
        out = tmp_path / "report.html"
        HtmlReporter().generate(cases, _META, out)
        text = out.read_text(encoding="utf-8")
        assert "line1\nline2\nline3" in text
        assert "out1\nout2\nout3" in text

    def test_design_system_css_colors(self, tmp_path: Path) -> None:
        """Verify DESIGN.md color tokens appear in the inline CSS."""
        out = tmp_path / "report.html"
        HtmlReporter().generate(_CASES, _META, out)
        text = out.read_text(encoding="utf-8")
        # Arcadyan green accent
        assert "#99CC00" in text
        # Graphite 800
        assert "#3C4043" in text
        # Gray surface
        assert "#F1F3F4" in text
        # Border
        assert "#DADCE0" in text
        # Dark canvas for code blocks
        assert "#3C3D41" in text


# ---------------------------------------------------------------------------
# Task 4 – hybrid summary in HTML
# ---------------------------------------------------------------------------

_PRECOMPUTED_SUMMARY: dict[str, Any] = {
    "policy_version": "wifi_llapi_summary_v1",
    "band_category": [
        {
            "band_key": "result_5g",
            "band_label": "5G",
            "category": "WiFi.AccessPoint",
            "total_items": 2,
            "tested_items": 1,
            "pass": 1,
            "fail": 0,
            "to_be_tested": 1,
            "not_supported": 0,
            "skip": 0,
            "pass_rate": 1.0,
            "progress": 0.5,
        },
    ],
    "bucket_totals": {},
    "raw_totals": {},
    "diagnostic_status": {},
    "per_case": [],
}


def test_html_reporter_renders_hybrid_summary(tmp_path: Path) -> None:
    meta_with_summary: dict[str, Any] = {
        **_META,
        "plugin_summary": _PRECOMPUTED_SUMMARY,
    }
    out = tmp_path / "report.html"
    HtmlReporter().generate(_CASES, meta_with_summary, out)
    text = out.read_text(encoding="utf-8")
    assert "WiFi LLAPI Hybrid Summary" in text
    assert "WiFi.AccessPoint" in text
    assert "To be confirmed" in text

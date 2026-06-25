"""Generic MD / JSON report projectors.

Provides :class:`IReporter` protocol plus concrete
:class:`MarkdownReporter` and :class:`JsonReporter` implementations.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

# ---------------------------------------------------------------------------
# Band / summary helpers
# ---------------------------------------------------------------------------

_BAND_KEYS: tuple[str, ...] = ("result_5g", "result_6g", "result_24g")
_BAND_LABELS: dict[str, str] = {
    "result_5g": "5G",
    "result_6g": "6G",
    "result_24g": "2.4G",
}
_NON_PASS_EXPECTED = {"not supported", "not_supported", "skip", "n/a"}


def _verdict(value: str) -> str:
    """Normalise a single band verdict to lower-case token."""
    return value.strip().lower() if value else ""


def _overall_status(case: Mapping[str, Any]) -> str:
    values = [str(case.get(key, "")).strip() for key in _BAND_KEYS]
    lowered = {_verdict(value) for value in values if value}
    if lowered == {"pass"}:
        return "Pass"
    if "fail" in lowered or "error" in lowered:
        return "Failed"
    if lowered and lowered <= _NON_PASS_EXPECTED:
        return "Non-pass expected"
    return "Mixed"


def _suite_case_counts(case_results: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"pass_cases": 0, "failed_cases": 0, "other_cases": 0}
    for case in case_results:
        status = _overall_status(case)
        if status == "Pass":
            counts["pass_cases"] += 1
        elif status == "Failed":
            counts["failed_cases"] += 1
        else:
            counts["other_cases"] += 1
    return counts


def _pass_rate(case_counts: Mapping[str, int]) -> float | None:
    denominator = int(case_counts.get("pass_cases", 0)) + int(case_counts.get("failed_cases", 0))
    if denominator <= 0:
        return None
    return int(case_counts.get("pass_cases", 0)) / denominator


def _precomputed_plugin_summary(
    meta: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the plugin-provided precomputed summary from *meta* when present."""
    val = meta.get("plugin_summary")
    if isinstance(val, dict):
        return dict(val)
    return None


def _summary_payload(
    case_results: Sequence[Mapping[str, Any]],
    meta: Mapping[str, Any],
) -> dict[str, Any]:
    """Return generic suite counts plus optional plugin-provided summary details."""
    precomputed = _precomputed_plugin_summary(meta)
    if precomputed is not None:
        return {**_summarise(case_results), **precomputed}
    return _summarise(case_results)


def _summarise(case_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate pass / fail / not_supported / error counts across bands."""
    counter: Counter[str] = Counter()
    diagnostic_counter: Counter[str] = Counter()
    for case in case_results:
        for key in _BAND_KEYS:
            v = _verdict(str(case.get(key, "")))
            if v:
                counter[v] += 1
        diagnostic = str(case.get("diagnostic_status", "")).strip()
        if diagnostic:
            diagnostic_counter[diagnostic] += 1
    suite_counts = _suite_case_counts(case_results)
    pass_rate = _pass_rate(suite_counts)
    return {
        "total_cases": len(case_results),
        "pass": counter.get("pass", 0),
        "fail": counter.get("fail", 0),
        "not_supported": counter.get("not_supported", 0)
        + counter.get("not supported", 0),
        "error": counter.get("error", 0),
        "diagnostic_status": dict(diagnostic_counter),
        **suite_counts,
        "pass_rate": pass_rate,
    }


def _format_duration(value: Any) -> str:
    try:
        total = max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return ""
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _suite_timing_rows(
    meta: Mapping[str, Any],
    case_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    raw_rows = meta.get("timing")
    rows: list[dict[str, str]] = []
    if isinstance(raw_rows, Sequence) and not isinstance(raw_rows, (str, bytes)):
        for item in raw_rows:
            if not isinstance(item, Mapping):
                continue
            metric = str(item.get("metric", item.get("label", ""))).strip()
            if not metric:
                continue
            started_at = str(item.get("started_at", "")).strip()
            finished_at = str(item.get("finished_at", "")).strip()
            duration = _format_duration(item.get("duration_seconds"))
            rows.append(
                {
                    "metric": metric,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration": duration,
                }
            )
    if rows:
        return rows

    started_values = [
        str(case.get("case_started_at", "")).strip()
        for case in case_results
        if str(case.get("case_started_at", "")).strip()
    ]
    finished_values = [
        str(case.get("case_finished_at", "")).strip()
        for case in case_results
        if str(case.get("case_finished_at", "")).strip()
    ]
    duration_total = 0.0
    for case in case_results:
        value = case.get("case_duration_seconds")
        if value is None:
            continue
        try:
            duration_total += float(value or 0.0)
        except (TypeError, ValueError):
            continue
    if started_values or finished_values or duration_total > 0:
        rows.append(
            {
                "metric": "suite run",
                "started_at": min(started_values) if started_values else "",
                "finished_at": max(finished_values) if finished_values else "",
                "duration": _format_duration(duration_total),
            }
        )
    return rows


def _case_timing_rows(case_results: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for case in case_results:
        finished_at = str(case.get("case_finished_at", "")).strip()
        duration = _format_duration(case.get("case_duration_seconds"))
        if not finished_at and not duration:
            continue
        rows.append(
            {
                "case_id": str(case.get("case_id", "")).strip(),
                "finished_at": finished_at,
                "duration": duration,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class IReporter(Protocol):
    """Minimal reporter contract."""

    def generate(
        self,
        case_results: Sequence[Mapping[str, Any]],
        meta: Mapping[str, Any],
        output_path: Path,
    ) -> Path: ...


# ---------------------------------------------------------------------------
# MarkdownReporter
# ---------------------------------------------------------------------------


class MarkdownReporter:
    """Render results to a human-readable Markdown file."""

    def generate(
        self,
        case_results: Sequence[Mapping[str, Any]],
        meta: Mapping[str, Any],
        output_path: Path,
    ) -> Path:
        lines: list[str] = []
        summary = _summary_payload(case_results, meta)
        self._write_header(lines, meta)
        self._write_timing(lines, meta, case_results)
        self._write_suite_summary(lines, summary)
        self._write_hybrid_summary(lines, summary)
        self._write_summary_table(lines, case_results)
        self._write_per_case_timing(lines, case_results)
        self._write_case_details(lines, case_results)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output_path

    # -- private helpers ----------------------------------------------------

    @staticmethod
    def _write_header(lines: list[str], meta: Mapping[str, Any]) -> None:
        title = meta.get("title", "Test Report")
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"- **Date**: {meta.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))}")
        for key in ("tester", "testbed", "dut_model", "firmware_version", "plugin"):
            if key in meta:
                label = key.replace("_", " ").title()
                lines.append(f"- **{label}**: {meta[key]}")
        lines.append("")

    @staticmethod
    def _write_hybrid_summary(
        lines: list[str],
        summary: Mapping[str, Any],
    ) -> None:
        """Render the WiFi LLAPI hybrid band/category summary table.

        No-ops gracefully when *summary* lacks a ``band_category`` sequence.
        """
        band_category = summary.get("band_category")
        if not band_category or not isinstance(band_category, (list, tuple)):
            return

        lines.append("## WiFi LLAPI Hybrid summary")
        lines.append("")
        lines.append(
            "| Band | Category | Total | Tested | Pass | Fail"
            " | To be confirmed | Not Supported | Skip | Pass Rate |"
        )
        lines.append(
            "|------|----------|-------|--------|------|------"
            "|--------------|---------------|------|-----------|"
        )
        for row in band_category:
            band = (
                row.get("band_label")
                or row.get("band")
                or row.get("band_key")
                or ""
            )
            category = row.get("category", "")
            total = row.get("total_items", 0)
            tested = row.get("tested_items", 0)
            pass_ = row.get("pass", 0)
            fail = row.get("fail", 0)
            tbt = row.get("to_be_tested", 0)
            ns = row.get("not_supported", 0)
            skip = row.get("skip", 0)
            pr = _format_percent(row.get("pass_rate"))
            lines.append(
                f"| {band} | {category} | {total} | {tested}"
                f" | {pass_} | {fail} | {tbt} | {ns} | {skip} | {pr} |"
            )
        lines.append("")

    @staticmethod
    def _write_summary_table(
        lines: list[str],
        case_results: Sequence[Mapping[str, Any]],
    ) -> None:
        lines.append("## Summary")
        lines.append("")
        header = "| case_id | source_row | result_5g | result_6g | result_24g | diagnostic_status | comment |"
        sep = "|---------|------------|-----------|-----------|------------|-------------------|---------|"
        lines.append(header)
        lines.append(sep)
        for case in case_results:
            cid = case.get("case_id", "")
            row = case.get("source_row", "")
            r5 = case.get("result_5g", "")
            r6 = case.get("result_6g", "")
            r24 = case.get("result_24g", "")
            diagnostic = case.get("diagnostic_status", "")
            comment = case.get("comment", "")
            lines.append(f"| {cid} | {row} | {r5} | {r6} | {r24} | {diagnostic} | {comment} |")
        lines.append("")

    @staticmethod
    def _write_timing(
        lines: list[str],
        meta: Mapping[str, Any],
        case_results: Sequence[Mapping[str, Any]],
    ) -> None:
        lines.append("## Timing")
        lines.append("")
        timing_rows = _suite_timing_rows(meta, case_results)
        if not timing_rows:
            lines.append("_Timing data unavailable._")
            lines.append("")
            return
        lines.append("| metric | started_at | finished_at | duration |")
        lines.append("| --- | --- | --- | --- |")
        for row in timing_rows:
            started_at = f"`{row['started_at']}`" if row["started_at"] else "-"
            finished_at = f"`{row['finished_at']}`" if row["finished_at"] else "-"
            duration = f"`{row['duration']}`" if row["duration"] else "-"
            lines.append(
                f"| {row['metric']} | {started_at} | {finished_at} | {duration} |"
            )
        lines.append("")

    @staticmethod
    def _write_suite_summary(lines: list[str], summary: Mapping[str, Any]) -> None:
        lines.append("## Suite summary")
        lines.append("")
        lines.append("| pass_cases | failed_cases | other_cases | pass_rate |")
        lines.append("| --- | --- | --- | --- |")
        lines.append(
            "| "
            f"{summary.get('pass_cases', 0)} | "
            f"{summary.get('failed_cases', 0)} | "
            f"{summary.get('other_cases', 0)} | "
            f"`{_format_percent(summary.get('pass_rate'))}` |"
        )
        lines.append("")
        lines.append("| total_cases | pass_bands | fail_bands | not_supported_bands | error_bands |")
        lines.append("| --- | --- | --- | --- | --- |")
        lines.append(
            "| "
            f"{summary.get('total_cases', 0)} | "
            f"{summary.get('pass', 0)} | "
            f"{summary.get('fail', 0)} | "
            f"{summary.get('not_supported', 0)} | "
            f"{summary.get('error', 0)} |"
        )
        lines.append("")

    @staticmethod
    def _write_per_case_timing(
        lines: list[str],
        case_results: Sequence[Mapping[str, Any]],
    ) -> None:
        lines.append("## Per-case timing")
        lines.append("")
        timing_rows = _case_timing_rows(case_results)
        if not timing_rows:
            lines.append("_No per-case timing data captured._")
            lines.append("")
            return
        lines.append("| case_id | finished_at | duration |")
        lines.append("| --- | --- | --- |")
        for row in timing_rows:
            finished_at = f"`{row['finished_at']}`" if row["finished_at"] else "-"
            duration = f"`{row['duration']}`" if row["duration"] else "-"
            lines.append(f"| {row['case_id']} | {finished_at} | {duration} |")
        lines.append("")

    @staticmethod
    def _write_case_details(
        lines: list[str],
        case_results: Sequence[Mapping[str, Any]],
    ) -> None:
        if not case_results:
            return
        lines.append("## Case Details")
        lines.append("")
        for case in case_results:
            cid = case.get("case_id", "unknown")
            lines.append(f"<details><summary>{cid}</summary>")
            lines.append("")
            cmd = case.get("executed_test_command", "")
            if cmd:
                lines.append("**Command**")
                lines.append("")
                lines.append("```")
                lines.append(cmd)
                lines.append("```")
                lines.append("")
            output = case.get("command_output", "")
            if output:
                lines.append("**Output**")
                lines.append("")
                lines.append("```")
                lines.append(output)
                lines.append("```")
                lines.append("")
            # Log references
            dut_lines = case.get("dut_log_lines", "")
            sta_lines = case.get("sta_log_lines", "")
            if dut_lines or sta_lines:
                lines.append("**Log Reference**")
                lines.append("")
                if dut_lines:
                    lines.append(f"- DUT: `{dut_lines}`")
                if sta_lines:
                    lines.append(f"- STA: `{sta_lines}`")
                lines.append("")
            # Emit any extra keys not yet rendered
            shown = {
                "case_id",
                "source_row",
                "executed_test_command",
                "command_output",
                "result_5g",
                "result_6g",
                "result_24g",
                "comment",
                "tester",
                "dut_log_lines",
                "sta_log_lines",
            }
            extras = {k: v for k, v in case.items() if k not in shown}
            if extras:
                for k, v in extras.items():
                    lines.append(f"- **{k}**: {v}")
                lines.append("")
            lines.append("</details>")
            lines.append("")


# ---------------------------------------------------------------------------
# JsonReporter
# ---------------------------------------------------------------------------


class JsonReporter:
    """Render results to a structured JSON file."""

    def generate(
        self,
        case_results: Sequence[Mapping[str, Any]],
        meta: Mapping[str, Any],
        output_path: Path,
    ) -> Path:
        payload: dict[str, Any] = {
            "meta": dict(meta),
            "cases": [dict(c) for c in case_results],
            "summary": _summary_payload(case_results, meta),
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        return output_path


# ---------------------------------------------------------------------------
# Convenience helper
# ---------------------------------------------------------------------------

def _html_reporter_class() -> type:
    """Lazy import to avoid circular dependency."""
    from testpilot.reporting.html_reporter import HtmlReporter
    return HtmlReporter


_FORMAT_REGISTRY: dict[str, type] = {
    "md": MarkdownReporter,
    "json": JsonReporter,
}


def _resolve_reporter(fmt: str) -> type:
    """Resolve format key to reporter class, supporting lazy-loaded entries."""
    if fmt == "html":
        return _html_reporter_class()
    cls = _FORMAT_REGISTRY.get(fmt)
    if cls is None:
        raise ValueError(f"Unsupported report format: {fmt!r}")
    return cls


def generate_reports(
    case_results: Sequence[Mapping[str, Any]],
    meta: Mapping[str, Any],
    output_dir: Path,
    formats: Sequence[str] = ("md", "json"),
) -> list[Path]:
    """Generate reports in the requested formats and return their paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    explicit_stem = str(meta.get("output_stem", "")).strip()
    stem = explicit_stem or str(meta.get("title", "report")).replace(" ", "_").lower()
    paths: list[Path] = []
    for fmt in formats:
        cls = _resolve_reporter(fmt)
        out = output_dir / f"{stem}.{fmt}"
        reporter = cls()
        reporter.generate(case_results, meta, out)
        paths.append(out)
    return paths

"""Self-contained HTML report generator following DESIGN.md Arcadyan styling.

Produces a single HTML file with inline CSS — no external dependencies
beyond optional Google Fonts for Montserrat / Noto Sans TC.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from testpilot.reporting.reporter import (
    _BAND_KEYS,
    _BAND_LABELS,
    _case_timing_rows,
    _format_duration,
    _format_percent,
    _overall_status,
    _suite_timing_rows,
    _summary_payload,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATUS_COLORS: dict[str, tuple[str, str]] = {
    # verdict → (background, text)
    "pass": ("#e8f8f5", "#1AB39F"),
    "fail": ("#fce4e6", "#DC3545"),
    "error": ("#fce4e6", "#DC3545"),
    "not_supported": ("#e8f4fd", "#00ADDC"),
    "not supported": ("#e8f4fd", "#00ADDC"),
    "skip": ("#e8f4fd", "#00ADDC"),
    "n/a": ("#f5f5f5", "#5F6368"),
}

_OVERALL_COLORS: dict[str, tuple[str, str]] = {
    "Pass": ("#e8f8f5", "#1AB39F"),
    "Failed": ("#fce4e6", "#DC3545"),
    "Mixed": ("#fff8e1", "#FEB80A"),
    "Non-pass expected": ("#e8f4fd", "#00ADDC"),
}

_LOG_RANGE_RE = re.compile(r"^L(?P<start>\d+)(?:-L(?P<end>\d+))?$")
_MAX_LOG_SNIPPET_LINES = 120
_TRUNCATED_HEAD_LINES = 60
_TRUNCATED_TAIL_LINES = 60


def _esc(value: Any) -> str:
    """HTML-escape a value, handling None gracefully."""
    return html.escape(str(value) if value is not None else "")


def _chip(text: str, bg: str, fg: str) -> str:
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:9999px;'
        f"font-size:12px;font-weight:600;letter-spacing:0.06em;"
        f'background:{bg};color:{fg};text-transform:uppercase">{_esc(text)}</span>'
    )


def _verdict_chip(raw: str) -> str:
    v = raw.strip().lower() if raw else ""
    if not v:
        return ""
    bg, fg = _STATUS_COLORS.get(v, ("#f5f5f5", "#5F6368"))
    return _chip(raw.strip(), bg, fg)


def _overall_chip(status: str) -> str:
    bg, fg = _OVERALL_COLORS.get(status, ("#f5f5f5", "#5F6368"))
    return _chip(status, bg, fg)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """\
:root {
  --green: #99CC00;
  --green-hover: #A8D426;
  --white: #FFFFFF;
  --gray-050: #F1F3F4;
  --gray-100: #DADCE0;
  --gray-500: #666666;
  --gray-600: #5F6368;
  --graphite-800: #3C4043;
  --graphite-900: #3C3D41;
  --success: #1AB39F;
  --error: #DC3545;
  --warning: #FEB80A;
  --info: #00ADDC;
  --radius: 6px;
}
*, *::before, *::after { box-sizing: border-box; }
html { font-size: 16px; }
body {
  margin: 0;
  font-family: 'Montserrat', 'Noto Sans TC', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
  background: var(--gray-050);
  color: var(--gray-500);
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
}
.container { max-width: 1300px; margin: 0 auto; padding: 24px 16px; }
/* Header bar */
.top-bar {
  background: var(--graphite-800);
  color: var(--white);
  padding: 12px 24px;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.top-bar .brand { color: var(--green); }
/* Page title */
h1 {
  font-size: 2rem; font-weight: 700; color: var(--graphite-800);
  margin: 0 0 8px; line-height: 1.2; letter-spacing: -0.01em;
}
.meta { color: var(--gray-600); font-size: 14px; margin-bottom: 24px; }
.meta span { margin-right: 16px; }
/* KPI strip */
.kpi-strip {
  display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px;
}
.kpi {
  flex: 1 1 150px;
  background: var(--white);
  border: 1px solid var(--gray-100);
  border-radius: var(--radius);
  padding: 16px;
  min-width: 140px;
}
.kpi .label { font-size: 13px; font-weight: 600; letter-spacing: 0.04em; color: var(--gray-600); text-transform: uppercase; }
.kpi .value { font-size: 20px; font-weight: 700; color: var(--graphite-800); margin-top: 4px; }
.kpi.accent .value { color: var(--success); }
.kpi.error .value { color: var(--error); }
/* Section headers with green keyline */
h2 {
  font-size: 1.5rem; font-weight: 600; color: var(--graphite-800);
  border-left: 4px solid var(--green); padding-left: 12px;
  margin: 32px 0 16px; line-height: 1.25;
}
/* Tables */
table {
  width: 100%; border-collapse: collapse;
  background: var(--white);
  border: 1px solid var(--gray-100);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 24px;
  font-size: 14px;
}
thead th {
  background: var(--gray-050);
  font-size: 13px; font-weight: 600;
  text-align: left; padding: 10px 12px;
  border-bottom: 2px solid var(--gray-100);
  color: var(--graphite-800);
  white-space: nowrap;
}
tbody td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--gray-100);
  vertical-align: top;
}
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover { background: #fafbfc; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
/* Collapsible case details */
details {
  background: var(--white);
  border: 1px solid var(--gray-100);
  border-radius: var(--radius);
  margin-bottom: 12px;
  overflow: hidden;
}
details summary {
  padding: 12px 16px;
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
  color: var(--graphite-800);
  background: var(--gray-050);
  list-style: none;
  display: flex; align-items: center; gap: 10px;
}
details summary::-webkit-details-marker { display: none; }
details summary::before {
  content: '▶'; font-size: 10px; color: var(--gray-600);
  transition: transform 0.15s;
}
details[open] summary::before { transform: rotate(90deg); }
details .detail-body { padding: 16px; }
/* Code / log blocks (dark) */
pre.code-block {
  background: var(--graphite-900);
  color: #DADCE0;
  font-family: 'SFMono-Regular', Menlo, Consolas, 'Liberation Mono', monospace;
  font-size: 13px;
  line-height: 1.54;
  padding: 12px 16px;
  border-radius: var(--radius);
  overflow-x: auto;
  margin: 8px 0 16px;
  white-space: pre-wrap;
  word-break: break-all;
}
.detail-meta { font-size: 13px; color: var(--gray-600); margin-bottom: 8px; }
.detail-meta strong { color: var(--graphite-800); }
/* Responsive */
@media (max-width: 600px) {
  .kpi-strip { flex-direction: column; }
  table { font-size: 12px; }
  h1 { font-size: 1.5rem; }
  h2 { font-size: 1.25rem; }
}
"""


# ---------------------------------------------------------------------------
# HtmlReporter
# ---------------------------------------------------------------------------


class HtmlReporter:
    """Render results to a self-contained HTML file following DESIGN.md."""

    def generate(
        self,
        case_results: Sequence[Mapping[str, Any]],
        meta: Mapping[str, Any],
        output_path: Path,
    ) -> Path:
        summary = _summary_payload(case_results, meta)
        artifact_dir = output_path.parent
        parts: list[str] = []
        parts.append(self._doc_open(meta))
        parts.append(self._kpi_strip(summary))
        parts.append(self._summary_table(case_results))
        parts.append(self._timing_section(meta, case_results))
        parts.append(self._suite_summary_section(summary))
        parts.append(self._hybrid_summary_section(summary))
        parts.append(self._per_case_timing(case_results))
        parts.append(self._case_details(case_results, artifact_dir))
        parts.append(self._doc_close())
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(parts), encoding="utf-8")
        return output_path

    @staticmethod
    def _parse_line_range(raw: str) -> tuple[int, int] | None:
        match = _LOG_RANGE_RE.match(raw.strip())
        if not match:
            return None
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        if start > end:
            start, end = end, start
        return start, end

    @classmethod
    def _log_excerpt(cls, log_path: Path, line_ref: str) -> tuple[str, bool] | None:
        parsed = cls._parse_line_range(line_ref)
        if parsed is None or not log_path.is_file():
            return None
        start, end = parsed
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not lines or start < 1:
            return None
        excerpt_lines = lines[start - 1:end]
        if not excerpt_lines:
            return None

        truncated = len(excerpt_lines) > _MAX_LOG_SNIPPET_LINES
        if truncated:
            head = excerpt_lines[:_TRUNCATED_HEAD_LINES]
            tail = excerpt_lines[-_TRUNCATED_TAIL_LINES:]
            numbered_lines = [
                f"L{start + idx}: {line}"
                for idx, line in enumerate(head)
            ]
            omitted = len(excerpt_lines) - (_TRUNCATED_HEAD_LINES + _TRUNCATED_TAIL_LINES)
            if omitted > 0:
                numbered_lines.append(f"... ({omitted} lines omitted) ...")
            tail_start = end - len(tail) + 1
            numbered_lines.extend(
                f"L{tail_start + idx}: {line}"
                for idx, line in enumerate(tail)
            )
        else:
            numbered_lines = [
                f"L{start + idx}: {line}"
                for idx, line in enumerate(excerpt_lines)
            ]
        return "\n".join(numbered_lines), truncated

    # -- document shell -----------------------------------------------------

    @staticmethod
    def _doc_open(meta: Mapping[str, Any]) -> str:
        title = _esc(meta.get("title", "Test Report"))
        lines = [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{title}</title>",
            '<link rel="preconnect" href="https://fonts.googleapis.com">',
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
            '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">',
            f"<style>{_CSS}</style>",
            "</head>",
            "<body>",
            '<div class="top-bar"><span class="brand">TestPilot</span> &mdash; WiFi LLAPI Report</div>',
            '<div class="container">',
            f"<h1>{title}</h1>",
            '<div class="meta">',
        ]
        for key in ("date", "tester", "testbed", "dut_model", "firmware_version", "plugin"):
            val = meta.get(key, "")
            if val:
                label = key.replace("_", " ").title()
                lines.append(f"<span><strong>{label}:</strong> {_esc(val)}</span>")
        lines.append("</div>")
        return "\n".join(lines)

    @staticmethod
    def _doc_close() -> str:
        return "</div>\n</body>\n</html>"

    # -- KPI strip ----------------------------------------------------------

    @staticmethod
    def _kpi_strip(summary: Mapping[str, Any]) -> str:
        tiles = [
            ("Total Cases", str(summary.get("total_cases", 0)), ""),
            ("Pass Cases", str(summary.get("pass_cases", 0)), "accent"),
            ("Failed Cases", str(summary.get("failed_cases", 0)), "error" if summary.get("failed_cases", 0) else ""),
            ("Other Cases", str(summary.get("other_cases", 0)), ""),
            ("Pass Rate", _format_percent(summary.get("pass_rate")), "accent"),
        ]
        parts = ['<div class="kpi-strip">']
        for label, value, cls in tiles:
            cls_attr = f' class="kpi {cls}"' if cls else ' class="kpi"'
            parts.append(
                f"<div{cls_attr}>"
                f'<div class="label">{label}</div>'
                f'<div class="value">{_esc(value)}</div>'
                f"</div>"
            )
        parts.append("</div>")
        return "\n".join(parts)

    # -- summary table ------------------------------------------------------

    @staticmethod
    def _summary_table(case_results: Sequence[Mapping[str, Any]]) -> str:
        lines = [
            "<h2>Summary</h2>",
            "<table>",
            "<thead><tr>",
            "<th>Case ID</th><th>Row</th>",
            "<th>5G</th><th>6G</th><th>2.4G</th>",
            "<th>Overall</th><th>Diagnostic</th><th>Comment</th>",
            "</tr></thead>",
            "<tbody>",
        ]
        for case in case_results:
            cid = _esc(case.get("case_id", ""))
            row = _esc(case.get("source_row", ""))
            r5 = _verdict_chip(str(case.get("result_5g", "")))
            r6 = _verdict_chip(str(case.get("result_6g", "")))
            r24 = _verdict_chip(str(case.get("result_24g", "")))
            overall = _overall_chip(_overall_status(case))
            diag = _esc(case.get("diagnostic_status", ""))
            comment = _esc(case.get("comment", ""))
            anchor = f'<a href="#{_esc(case.get("case_id", ""))}">{cid}</a>'
            lines.append(
                f"<tr><td>{anchor}</td><td class='num'>{row}</td>"
                f"<td>{r5}</td><td>{r6}</td><td>{r24}</td>"
                f"<td>{overall}</td><td>{diag}</td><td>{comment}</td></tr>"
            )
        lines.append("</tbody></table>")
        return "\n".join(lines)

    # -- timing section -----------------------------------------------------

    @staticmethod
    def _timing_section(
        meta: Mapping[str, Any],
        case_results: Sequence[Mapping[str, Any]],
    ) -> str:
        rows = _suite_timing_rows(meta, case_results)
        lines = ["<h2>Timing</h2>"]
        if not rows:
            lines.append("<p><em>Timing data unavailable.</em></p>")
            return "\n".join(lines)
        lines += [
            "<table><thead><tr>",
            "<th>Metric</th><th>Started At</th><th>Finished At</th><th>Duration</th>",
            "</tr></thead><tbody>",
        ]
        for r in rows:
            lines.append(
                f"<tr><td>{_esc(r['metric'])}</td>"
                f"<td><code>{_esc(r['started_at'])}</code></td>"
                f"<td><code>{_esc(r['finished_at'])}</code></td>"
                f"<td><code>{_esc(r['duration'])}</code></td></tr>"
            )
        lines.append("</tbody></table>")
        return "\n".join(lines)

    # -- suite summary ------------------------------------------------------

    @staticmethod
    def _suite_summary_section(summary: Mapping[str, Any]) -> str:
        lines = [
            "<h2>Suite Summary</h2>",
            "<table><thead><tr>",
            "<th>Total Cases</th><th>Pass (bands)</th><th>Fail (bands)</th>"
            "<th>Not Supported (bands)</th><th>Error (bands)</th>",
            "</tr></thead><tbody><tr>",
            f"<td class='num'>{summary.get('total_cases', 0)}</td>",
            f"<td class='num'>{summary.get('pass', 0)}</td>",
            f"<td class='num'>{summary.get('fail', 0)}</td>",
            f"<td class='num'>{summary.get('not_supported', 0)}</td>",
            f"<td class='num'>{summary.get('error', 0)}</td>",
            "</tr></tbody></table>",
        ]
        # Diagnostic breakdown if any
        diag: dict[str, int] = summary.get("diagnostic_status", {})
        if diag:
            lines += [
                "<table><thead><tr><th>Diagnostic Status</th><th>Count</th></tr></thead><tbody>",
            ]
            for k, v in sorted(diag.items()):
                lines.append(f"<tr><td>{_esc(k)}</td><td class='num'>{v}</td></tr>")
            lines.append("</tbody></table>")
        return "\n".join(lines)

    # -- wifi llapi hybrid summary ------------------------------------------

    @staticmethod
    def _hybrid_summary_section(summary: Mapping[str, Any]) -> str:
        """Render WiFi LLAPI hybrid band/category summary table.

        No-ops gracefully when *summary* lacks a ``band_category`` sequence.
        """
        band_category = summary.get("band_category")
        if not band_category or not isinstance(band_category, (list, tuple)):
            return ""

        lines = [
            "<h2>WiFi LLAPI Hybrid Summary</h2>",
            "<table><thead><tr>",
            "<th>Band</th><th>Category</th><th>Total</th><th>Tested</th>",
            "<th>Pass</th><th>Fail</th><th>To be confirmed</th>",
            "<th>Not Supported</th><th>Skip</th><th>Pass Rate</th>",
            "</tr></thead><tbody>",
        ]
        for row in band_category:
            band = _esc(
                row.get("band_label")
                or row.get("band")
                or row.get("band_key")
                or ""
            )
            category = _esc(row.get("category", ""))
            total = _esc(row.get("total_items", 0))
            tested = _esc(row.get("tested_items", 0))
            pass_ = _esc(row.get("pass", 0))
            fail = _esc(row.get("fail", 0))
            tbt = _esc(row.get("to_be_tested", 0))
            ns = _esc(row.get("not_supported", 0))
            skip = _esc(row.get("skip", 0))
            pr = _esc(_format_percent(row.get("pass_rate")))
            lines.append(
                f"<tr>"
                f"<td>{band}</td><td>{category}</td>"
                f"<td class='num'>{total}</td><td class='num'>{tested}</td>"
                f"<td class='num'>{pass_}</td><td class='num'>{fail}</td>"
                f"<td class='num'>{tbt}</td><td class='num'>{ns}</td>"
                f"<td class='num'>{skip}</td><td class='num'>{pr}</td>"
                f"</tr>"
            )
        lines.append("</tbody></table>")
        return "\n".join(lines)

    # -- per-case timing ----------------------------------------------------

    @staticmethod
    def _per_case_timing(case_results: Sequence[Mapping[str, Any]]) -> str:
        rows = _case_timing_rows(case_results)
        lines = ["<h2>Per-case Timing</h2>"]
        if not rows:
            lines.append("<p><em>No per-case timing data captured.</em></p>")
            return "\n".join(lines)
        lines += [
            "<table><thead><tr>",
            "<th>Case ID</th><th>Finished At</th><th>Duration</th>",
            "</tr></thead><tbody>",
        ]
        for r in rows:
            lines.append(
                f"<tr><td>{_esc(r['case_id'])}</td>"
                f"<td><code>{_esc(r['finished_at'])}</code></td>"
                f"<td><code>{_esc(r['duration'])}</code></td></tr>"
            )
        lines.append("</tbody></table>")
        return "\n".join(lines)

    # -- per-case collapsible details ---------------------------------------

    @staticmethod
    def _case_details(
        case_results: Sequence[Mapping[str, Any]],
        artifact_dir: Path,
    ) -> str:
        if not case_results:
            return ""
        lines = ["<h2>Case Details</h2>"]
        log_paths = {
            "DUT": artifact_dir / "DUT.log",
            "STA": artifact_dir / "STA.log",
        }
        for case in case_results:
            cid = case.get("case_id", "unknown")
            overall = _overall_status(case)
            chip = _overall_chip(overall)
            lines.append(f'<details id="{_esc(cid)}">')
            lines.append(f"<summary>{_esc(cid)} {chip}</summary>")
            lines.append('<div class="detail-body">')

            # Meta line
            row = case.get("source_row", "")
            diag = case.get("diagnostic_status", "")
            meta_parts = []
            if row:
                meta_parts.append(f"<strong>Row:</strong> {_esc(row)}")
            for bk in _BAND_KEYS:
                v = str(case.get(bk, "")).strip()
                if v:
                    meta_parts.append(f"<strong>{_BAND_LABELS.get(bk, bk)}:</strong> {_verdict_chip(v)}")
            if diag:
                meta_parts.append(f"<strong>Diagnostic:</strong> {_esc(diag)}")
            if meta_parts:
                lines.append(f'<div class="detail-meta">{" &nbsp;|&nbsp; ".join(meta_parts)}</div>')

            comment = str(case.get("comment", "")).strip()
            if comment:
                lines.append(f"<p><strong>Comment:</strong> {_esc(comment)}</p>")

            # Command
            cmd = str(case.get("executed_test_command", "")).strip()
            if cmd:
                lines.append("<p><strong>Command</strong></p>")
                lines.append(f'<pre class="code-block">{_esc(cmd)}</pre>')

            # Output
            output = str(case.get("command_output", "")).strip()
            if output:
                lines.append("<p><strong>Output</strong></p>")
                lines.append(f'<pre class="code-block">{_esc(output)}</pre>')

            # Log refs
            dut_lines = str(case.get("dut_log_lines", "")).strip()
            sta_lines = str(case.get("sta_log_lines", "")).strip()
            if dut_lines or sta_lines:
                lines.append("<p><strong>Log Reference</strong></p><ul>")
                if dut_lines:
                    lines.append(f"<li>DUT: <code>{_esc(dut_lines)}</code></li>")
                if sta_lines:
                    lines.append(f"<li>STA: <code>{_esc(sta_lines)}</code></li>")
                lines.append("</ul>")
                for device, line_ref in (("DUT", dut_lines), ("STA", sta_lines)):
                    if not line_ref:
                        continue
                    excerpt = HtmlReporter._log_excerpt(log_paths[device], line_ref)
                    if excerpt is None:
                        continue
                    excerpt_text, truncated = excerpt
                    lines.append(
                        f"<p><strong>{device} Log Snippet</strong> "
                        f"<code>{_esc(line_ref)}</code></p>"
                    )
                    if truncated:
                        lines.append(
                            "<div class='detail-meta'>"
                            "Snippet truncated for readability; showing head and tail of the referenced range."
                            "</div>"
                        )
                    lines.append(f'<pre class="code-block">{_esc(excerpt_text)}</pre>')

            # Duration
            dur = case.get("case_duration_seconds")
            if dur is not None:
                lines.append(f'<div class="detail-meta"><strong>Duration:</strong> <code>{_esc(_format_duration(dur))}</code></div>')

            # Remediation history
            remediation = case.get("remediation_history")
            if remediation and isinstance(remediation, list):
                lines.append("<p><strong>Remediation History</strong></p>")
                for entry in remediation:
                    if isinstance(entry, dict):
                        summary_text = entry.get("summary", "")
                        source = entry.get("decision_source", "")
                        applied = entry.get("applied", False)
                        lines.append(
                            f'<div class="detail-meta">'
                            f"Attempt {entry.get('attempt_index', '?')}: "
                            f"{_esc(summary_text)} "
                            f"(source: {_esc(source)}, applied: {applied})"
                            f"</div>"
                        )

            lines.append("</div></details>")
        return "\n".join(lines)

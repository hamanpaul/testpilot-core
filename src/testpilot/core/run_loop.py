"""Core-owned execution loop for plugin-managed runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
import logging
from pathlib import Path
import time
from typing import Any

from testpilot.api import (
    case_band_results as _case_band_results,
    overall_case_status as _overall_case_status,
    sanitize_case_id as _sanitize_case_id,
)
from testpilot.core.execution_engine import ExecutionEngine
from testpilot.core.orchestrator import build_case_session_plan
from testpilot.runtime.run_backend import RunHandle

log = logging.getLogger(__name__)


@dataclass
class CaseRunRecord:
    case: dict[str, Any]
    retry: Any
    source_row: int
    trace_path: str
    seq_start: int | None
    seq_end: int | None
    started_at: str
    finished_at: str
    duration_seconds: float
    drift: bool = False
    case_id: str = ""
    dut_log_lines: str = ""
    sta_log_lines: str = ""


@dataclass
class RunResult:
    cases: list[CaseRunRecord]
    run_id: str
    run_date: date
    plugin_name: str
    fw_ver: str
    fw_ver_source: str
    artifact_dir: Path
    agent_trace_dir: Path
    dut_log_path: str
    sta_log_path: str
    timing_rows: list[dict[str, Any]]
    execution_policy: dict[str, Any]
    plugin_version: str = ""
    agent_trace_count: int = 0
    cases_count: int = 0
    run_started_monotonic: float = 0.0
    run_started_at_iso: str = ""
    first_case_started_monotonic: float | None = None
    first_case_started_at_iso: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)
    version_manifest: dict[str, Any] = field(default_factory=dict)


def _capture_version_manifest(
    orchestrator: Any,
    *,
    plugin: Any,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    capture = getattr(plugin, "capture_dut_firmware_version", None)
    if not callable(capture):
        return {}
    try:
        captured = capture(getattr(orchestrator, "config", None), cases)
    except Exception:
        log.warning(
            "%s version manifest capture failed; continuing without manifest",
            getattr(plugin, "name", "plugin"),
            exc_info=True,
        )
        return {}
    if isinstance(captured, Mapping):
        return dict(captured)
    legacy_git = str(captured or "").strip()
    if legacy_git:
        return {"git": legacy_git}
    return {}


def _resolve_firmware_version(
    *,
    requested: str | None,
    version_manifest: Mapping[str, Any],
) -> tuple[str, str]:
    requested_value = (requested or "").strip()
    if requested_value and requested_value != "DUT-FW-VER":
        return requested_value, "cli"
    manifest_git = str(version_manifest.get("git", "") or "").strip()
    if manifest_git:
        return manifest_git, "dut_git_revision"
    return "DUT-FW-VER", "fallback_default"


def _apply_plugin_execution_policy(
    plugin: Any,
    execution_policy: dict[str, Any],
) -> dict[str, Any]:
    policy = dict(execution_policy)
    # NOTE: execution_policy is treated as run-level only here — the core loop
    # passes an empty case and applies just mode/max_concurrency. Per-case policy
    # and other fields (retry/timeout/failure) are intentionally not consumed yet;
    # revisit if a plugin needs case-specific execution constraints.
    constraint = plugin.execution_policy({})
    if not isinstance(constraint, dict):
        return policy
    if "mode" in constraint and policy.get("mode") != constraint["mode"]:
        log.warning(
            "%s execution.mode=%s is not supported, force to %s",
            getattr(plugin, "name", "plugin"),
            policy.get("mode"),
            constraint["mode"],
        )
        policy["mode"] = constraint["mode"]
    if (
        "max_concurrency" in constraint
        and policy.get("max_concurrency") != constraint["max_concurrency"]
    ):
        log.warning(
            "%s max_concurrency=%s is not supported, force to %s",
            getattr(plugin, "name", "plugin"),
            policy.get("max_concurrency"),
            constraint["max_concurrency"],
        )
        policy["max_concurrency"] = constraint["max_concurrency"]
    return policy


def _seq_tracking_handle(
    orchestrator: Any,
    *,
    run_id: str,
    capture_path: Path | str | None,
) -> RunHandle | None:
    run_handle = orchestrator.run_handle
    if run_handle is not None:
        if run_handle.run_id == "run":
            run_handle.run_id = run_id
        return run_handle
    normalized_capture_path = str(Path(capture_path)) if capture_path is not None else None
    return RunHandle(run_id=run_id, meta={"wal_path": normalized_capture_path})


def _mark_seq_position(
    orchestrator: Any,
    run_handle: RunHandle | None,
) -> int | None:
    if run_handle is None:
        return None
    return orchestrator.run_backend.mark_position(run_handle)


def _build_case_trace_payload(
    *,
    run_id: str,
    plugin_name: str,
    case: dict[str, Any],
    case_id: str,
    source_row: int,
    execution_policy: dict[str, Any],
    selection_trace: dict[str, Any],
    retry_result: Any,
) -> dict[str, Any]:
    verdict = retry_result.verdict
    attempts_trace = retry_result.attempts

    result_5g, result_6g, result_24g = _case_band_results(case, verdict)
    status = _overall_case_status(result_5g, result_6g, result_24g)

    for attempt in attempts_trace:
        att_verdict = attempt.get("verdict", False)
        a5, a6, a24 = _case_band_results(case, att_verdict)
        attempt["status"] = _overall_case_status(a5, a6, a24)

    return {
        "run_id": run_id,
        "plugin": plugin_name,
        "case_id": case_id,
        "source_row": source_row,
        "execution": execution_policy,
        "selection_trace": selection_trace,
        "attempts": attempts_trace,
        "final": {
            "status": status,
            "evaluation_verdict": "Pass" if verdict else "Fail",
            "attempts_used": retry_result.attempts_used,
            "comment": retry_result.comment,
            "diagnostic_status": retry_result.diagnostic_status,
        },
        "diagnostic_status": retry_result.diagnostic_status,
        "remediation_history": retry_result.remediation_history or [],
        "failure_snapshot": retry_result.failure_snapshot,
    }


def run(
    orchestrator: Any,
    plugin_name: str,
    case_ids: list[str] | None,
    dut_fw_ver: str | None,
    provider_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plugin = orchestrator.loader.load(plugin_name)
    prepared = plugin.prepare_run(case_ids)
    cases = list(prepared.cases)
    prepared_artifacts = dict(prepared.artifacts)

    reports_root = Path(orchestrator.plugins_dir) / plugin_name / "reports"
    run_date = date.today()
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    version_manifest = _capture_version_manifest(
        orchestrator,
        plugin=plugin,
        cases=cases,
    )

    capture_path = orchestrator._start_run_capture(run_id)
    run_handle = _seq_tracking_handle(
        orchestrator,
        run_id=run_id,
        capture_path=capture_path,
    )
    run_seq_start = _mark_seq_position(orchestrator, run_handle)

    fw_ver, fw_ver_source = _resolve_firmware_version(
        requested=dut_fw_ver,
        version_manifest=version_manifest,
    )
    artifact_dir = reports_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    agent_config = orchestrator.runner_selector.load_agent_config(plugin_name, plugin=plugin)
    execution_policy = orchestrator.runner_selector.build_execution_policy(agent_config)
    execution_policy = _apply_plugin_execution_policy(plugin, execution_policy)
    orchestrator._build_execution_engine(
        plugin_name=plugin_name,
        plugin=plugin,
        agent_config=agent_config,
    )
    agent_trace_dir = artifact_dir / "agent_trace"
    agent_trace_dir.mkdir(parents=True, exist_ok=True)

    case_records: list[CaseRunRecord] = []
    case_trace_files: list[str] = []
    run_started_monotonic = time.monotonic()
    run_started_at_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    first_case_started_monotonic: float | None = None
    first_case_started_at_iso = ""

    case_seq_ranges: dict[str, dict[str, int | None]] = {}

    for case in cases:
        case_id = str(case.get("id", "?"))
        source = case.get("source", {}) if isinstance(case.get("source"), dict) else {}
        try:
            source_row = int(source.get("row", 0))
        except (TypeError, ValueError):
            source_row = 0

        selected_runner, selection_trace = orchestrator.runner_selector.select_case_runner(
            plugin_name=plugin_name,
            case=case,
            agent_config=agent_config,
        )
        if callable(build_case_session_plan):
            session_plan = build_case_session_plan(
                run_id,
                case_id,
                selected_runner,
                provider_config=provider_config,
            )
            if session_plan is not None:
                selection_trace["session_plan"] = session_plan

        active_session_id: str | None = None
        session_plan_dict = selection_trace.get("session_plan")
        if session_plan_dict and isinstance(session_plan_dict, dict):
            session_handle = orchestrator._create_case_session(session_plan_dict)
            if session_handle:
                selection_trace["session_handle"] = session_handle
                if session_handle.get("status") == "created":
                    active_session_id = session_handle.get("session_id")

        seq_before = _mark_seq_position(orchestrator, run_handle)
        case_started_monotonic = time.monotonic()
        case_started_at_iso = datetime.now().astimezone().isoformat(timespec="seconds")
        if first_case_started_monotonic is None:
            first_case_started_monotonic = case_started_monotonic
            first_case_started_at_iso = case_started_at_iso
        try:
            retry_result = orchestrator.execution_engine.execute_with_retry(
                plugin=plugin,
                case=case,
                runner=selected_runner,
                execution_policy=execution_policy,
            )
        finally:
            orchestrator._cleanup_case_session(active_session_id)
        case_finished_monotonic = time.monotonic()
        case_finished_at_iso = datetime.now().astimezone().isoformat(timespec="seconds")
        seq_after = _mark_seq_position(orchestrator, run_handle)
        case_seq_ranges[case_id] = {
            "seq_start": seq_before,
            "seq_end": seq_after,
        }

        case_trace_path = agent_trace_dir / f"{_sanitize_case_id(case_id)}.json"
        ExecutionEngine.write_case_trace(
            case_trace_path,
            _build_case_trace_payload(
                run_id=run_id,
                plugin_name=plugin_name,
                case=case,
                case_id=case_id,
                source_row=source_row,
                execution_policy=execution_policy,
                selection_trace=selection_trace,
                retry_result=retry_result,
            ),
        )
        case_trace_files.append(str(case_trace_path))

        case_records.append(
            CaseRunRecord(
                case=case,
                retry=retry_result,
                source_row=source_row,
                trace_path=str(case_trace_path),
                seq_start=seq_before,
                seq_end=seq_after,
                started_at=case_started_at_iso,
                finished_at=case_finished_at_iso,
                duration_seconds=round(
                    case_finished_monotonic - case_started_monotonic,
                    3,
                ),
                drift=bool(case.get("drift", False)),
                case_id=case_id,
            )
        )

    dut_log_path = ""
    sta_log_path = ""
    try:
        run_seq_end = _mark_seq_position(orchestrator, run_handle)
        log_result = orchestrator._export_run_logs(
            run_id=run_id,
            artifact_dir=artifact_dir,
            case_seq_ranges=case_seq_ranges,
            case_results=case_records,
            run_seq_start=run_seq_start,
            run_seq_end=run_seq_end,
        )
        dut_log_path = log_result.get("dut_log_path", "")
        sta_log_path = log_result.get("sta_log_path", "")
    except Exception:
        log.warning("run log export failed", exc_info=True)
    finally:
        orchestrator._stop_run_capture()

    run_result = RunResult(
        cases=case_records,
        run_id=run_id,
        run_date=run_date,
        plugin_name=plugin_name,
        fw_ver=fw_ver,
        fw_ver_source=fw_ver_source,
        artifact_dir=artifact_dir,
        agent_trace_dir=agent_trace_dir,
        dut_log_path=dut_log_path,
        sta_log_path=sta_log_path,
        timing_rows=[],
        execution_policy=execution_policy,
        plugin_version=plugin.version,
        agent_trace_count=len(case_trace_files),
        cases_count=len(cases),
        run_started_monotonic=run_started_monotonic,
        run_started_at_iso=run_started_at_iso,
        first_case_started_monotonic=first_case_started_monotonic,
        first_case_started_at_iso=first_case_started_at_iso,
        artifacts=prepared_artifacts,
        version_manifest=version_manifest,
    )

    reporter = plugin.create_reporter()
    build_reports = getattr(reporter, "build_reports", None)
    if not callable(build_reports):
        raise RuntimeError(f"{plugin_name} reporter does not implement build_reports()")
    payload = build_reports(run_result)
    if isinstance(payload, dict):
        payload.setdefault(
            "agent_session_degraded",
            getattr(
                orchestrator,
                "agent_session_degraded",
                {"degraded": False, "reason": ""},
            ),
        )
    return payload


run_cases = run

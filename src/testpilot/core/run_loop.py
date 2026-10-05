"""Core-owned execution loop for plugin-managed runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
import inspect
import json
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
from testpilot.core.plugin_base import PluginBase
from testpilot.core.run_start_gate import (
    PrepareRunGateOutcome,
    RunCapabilityAdmissionOutcome,
    admit_run_capabilities,
    is_valid_capture_context,
    is_valid_gate_result,
    is_valid_sequence_marker,
    is_valid_strict_capture_provider_admission,
)
from testpilot.core.run_analysis import RunAnalysisResult
from testpilot.core.role_plan import (
    CaptureRolePlanRequest,
    EffectiveRolePlan,
    RolePlanError,
    project_capture_role_plan,
)
from testpilot.core.testbed_config import TestbedConfig
from testpilot.runtime.run_backend import RunHandle
from testpilot.runtime.strict_capture import (
    StrictCaptureError,
    StrictCaptureHarvest,
    StrictCaptureHarvestStatus,
    StrictCapturePosition,
)

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
    planning_result: Any,
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
        "case_planning": planning_result.to_trace_dict(),
        "attempts": attempts_trace,
        "final": {
            "status": status,
            "evaluation_verdict": "Pass" if verdict else "Fail",
            "attempts_used": retry_result.attempts_used,
            "comment": retry_result.comment,
            "diagnostic_status": retry_result.diagnostic_status,
            "abort_run": bool(getattr(retry_result, "abort_run", False)),
            "abort_reason": str(getattr(retry_result, "abort_reason", "")),
        },
        "diagnostic_status": retry_result.diagnostic_status,
        "remediation_history": retry_result.remediation_history or [],
        "failure_snapshot": retry_result.failure_snapshot,
        "tier2_audit": retry_result.tier2_audit or [],
        "agent_recovered": bool(retry_result.agent_recovered),
    }


def _stop_run_capture_once(orchestrator: Any, capture_state: dict[str, bool]) -> None:
    if not capture_state.get("capture_attempted") or capture_state.get("capture_stopped"):
        return
    orchestrator._stop_run_capture()
    capture_state["capture_stopped"] = True


def _safe_case_ids(cases: list[dict[str, Any]] | None, requested_ids: list[str] | None) -> list[str]:
    raw_ids = (
        [case.get("id", "?") for case in cases]
        if cases is not None
        else (requested_ids or [])
    )
    return [_sanitize_case_id(str(case_id))[:128] for case_id in raw_ids]


def _run_start_abort(
    *,
    plugin_name: str,
    reports_root: Path,
    run_id: str,
    reason_code: str,
    outcome: str,
    cases: list[dict[str, Any]] | None,
    requested_ids: list[str] | None,
    capture_attempted: bool,
    capture_status: str | None = None,
    run_seq_start: int | None = None,
    gate_result: Any = None,
) -> dict[str, Any]:
    """Write terminal run-start metadata without creating executed-case rows."""
    artifact_dir = reports_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    selected_ids = _safe_case_ids(cases, requested_ids)
    selection_known = cases is not None or requested_ids is not None
    summary: dict[str, Any] = {
        "stage": "run_start",
        "outcome": outcome,
        "reason_code": reason_code,
        "executed_case_count": 0,
        "selected_case_count": len(selected_ids) if selection_known else None,
        "selected_case_ids": selected_ids,
        "unexecuted_case_ids": selected_ids,
        "selection_status": (
            "prepared"
            if cases is not None
            else "request_only"
            if requested_ids is not None
            else "unresolved"
        ),
        "capture_status": capture_status
        or ("incomplete" if capture_attempted else "not_started"),
        "run_seq_start": run_seq_start,
    }
    if is_valid_gate_result(gate_result):
        summary["gate"] = gate_result.to_payload()
    artifact_path = artifact_dir / "run-abort.json"
    artifact_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "plugin": plugin_name,
        "status": "aborted",
        "cases_count": 0,
        "run_abort": summary,
        "run_abort_path": str(artifact_path),
    }


def abort_run_start_before_capture(
    orchestrator: Any,
    plugin_name: str,
    requested_ids: list[str] | None,
    reason_code: str,
) -> dict[str, Any]:
    """Create a sanitized terminal artifact for public-entry capability rejection."""
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    reports_root = Path(orchestrator.plugins_dir) / plugin_name / "reports"
    return _run_start_abort(
        plugin_name=plugin_name,
        reports_root=reports_root,
        run_id=run_id,
        reason_code=reason_code,
        outcome=PrepareRunGateOutcome.UNKNOWN.value,
        cases=None,
        requested_ids=requested_ids,
        capture_attempted=False,
    )


def _strict_capture_ranges_problem(
    *,
    run_seq_start: int,
    run_seq_end: Any,
    case_seq_ranges: dict[str, dict[str, int | None]],
) -> str | None:
    if not is_valid_sequence_marker(run_seq_end) or run_seq_end < run_seq_start:
        return "run_end_marker_invalid"
    for bounds in case_seq_ranges.values():
        case_start = bounds.get("seq_start")
        case_end = bounds.get("seq_end")
        if (
            not is_valid_sequence_marker(case_start)
            or not is_valid_sequence_marker(case_end)
            or case_start < run_seq_start
            or case_end < case_start
            or case_end > run_seq_end
        ):
            return "case_sequence_range_invalid"
    return None


def _finalize_strict_capture(
    orchestrator: Any,
    capture_state: dict[str, Any],
) -> StrictCaptureHarvest | None:
    handle = capture_state.get("strict_handle")
    if handle is None or capture_state.get("strict_harvested"):
        return None
    raw_artifact_dir = capture_state.get("strict_artifact_dir")
    if raw_artifact_dir:
        artifact_dir = Path(raw_artifact_dir)
    else:
        reports_root = Path(capture_state["strict_reports_root"])
        artifact_dir = reports_root / capture_state["strict_run_id"]
    try:
        harvest = orchestrator.run_backend.harvest_strict_for_handle(
            handle,
            artifact_dir,
            capture_state.get("strict_case_results", []),
            capture_state.get("strict_case_seq_ranges", {}),
        )
        if type(harvest) is not StrictCaptureHarvest:
            raise StrictCaptureError("capture_harvest_result_invalid")
    except Exception:
        harvest = StrictCaptureHarvest(
            StrictCaptureHarvestStatus.UNKNOWN,
            "capture_finalize_failed",
        )
    capture_state["strict_harvested"] = True
    capture_state["strict_harvest_payload"] = harvest.to_payload()
    return harvest


def _attach_strict_capture_result(
    result: Any,
    capture_state: dict[str, Any],
    harvest: StrictCaptureHarvest,
) -> None:
    payload = harvest.to_payload()
    if not isinstance(result, dict):
        return
    run_abort = result.get("run_abort")
    if isinstance(run_abort, dict):
        run_abort["core_run_capture"] = payload
        run_abort["capture_status"] = payload["status"]
        abort_path = result.get("run_abort_path")
        if isinstance(abort_path, str) and abort_path:
            try:
                Path(abort_path).write_text(
                    json.dumps(run_abort, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass
        return
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        artifacts["core_run_capture"] = payload


def run(
    orchestrator: Any,
    plugin_name: str,
    case_ids: list[str] | None,
    dut_fw_ver: str | None,
    provider_config: dict[str, Any] | None = None,
    *,
    preloaded_plugin: Any | None = None,
    prebound_plugin: Any | None = None,
) -> dict[str, Any]:
    capture_state: dict[str, Any] = {
        "capture_attempted": False,
        "capture_stopped": False,
        "capture_cleanup_suppressed": False,
        "strict_capture": False,
        "strict_preflight_active": False,
        "strict_handle": None,
        "strict_harvested": False,
    }
    try:
        result = _run_with_capture(
            orchestrator,
            plugin_name,
            case_ids,
            dut_fw_ver,
            provider_config,
            preloaded_plugin=preloaded_plugin,
            prebound_plugin=prebound_plugin,
            capture_state=capture_state,
        )
        if capture_state.get("strict_capture"):
            harvest = _finalize_strict_capture(orchestrator, capture_state)
            if harvest is not None:
                _attach_strict_capture_result(result, capture_state, harvest)
        return result
    finally:
        if capture_state.get("strict_capture"):
            handle = capture_state.get("strict_handle")
            try:
                if handle is not None:
                    _finalize_strict_capture(orchestrator, capture_state)
                    orchestrator.run_backend.release_strict_capture(handle)
                elif capture_state.get("strict_preflight_active"):
                    orchestrator.run_backend.cancel_strict_capture_preflight(
                        capture_state.get("strict_run_id", "")
                    )
            except Exception:
                log.warning("strict capture local release failed")
        elif (
            capture_state["capture_attempted"]
            and not capture_state["capture_stopped"]
            and not capture_state["capture_cleanup_suppressed"]
        ):
            try:
                _stop_run_capture_once(orchestrator, capture_state)
            except Exception:
                # Preserve a setup/run exception while making the failed cleanup
                # visible. The normal export-path cleanup still propagates errors.
                log.warning("run capture cleanup failed", exc_info=True)


def _run_with_capture(
    orchestrator: Any,
    plugin_name: str,
    case_ids: list[str] | None,
    dut_fw_ver: str | None,
    provider_config: dict[str, Any] | None,
    *,
    preloaded_plugin: Any | None,
    prebound_plugin: Any | None,
    capture_state: dict[str, bool],
) -> dict[str, Any]:
    plugin = (
        preloaded_plugin
        if preloaded_plugin is not None
        else orchestrator.loader.load(plugin_name)
    )
    admission = admit_run_capabilities(
        plugin,
        getattr(orchestrator, "run_backend", None),
        default_gate_hook=PluginBase.prepare_run_after_capture,
    )
    strict_capture_gate = admission.outcome is not RunCapabilityAdmissionOutcome.LEGACY
    capability_problem = (
        admission.reason_code
        if admission.outcome is RunCapabilityAdmissionOutcome.REJECTED
        else None
    )
    if capability_problem is not None:
        run_id = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        reports_root = Path(orchestrator.plugins_dir) / plugin_name / "reports"
        return _run_start_abort(
            plugin_name=plugin_name,
            reports_root=reports_root,
            run_id=run_id,
            reason_code=capability_problem,
            outcome=PrepareRunGateOutcome.UNKNOWN.value,
            cases=None,
            requested_ids=case_ids,
            capture_attempted=False,
        )

    strict_run_id: str | None = None
    strict_reports_root: Path | None = None
    strict_role_request: CaptureRolePlanRequest | None = None
    strict_role_plan: EffectiveRolePlan | None = None
    strict_config: Any = None
    if strict_capture_gate:
        capture_state["strict_capture"] = True
        strict_run_id = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        strict_reports_root = Path(orchestrator.plugins_dir) / plugin_name / "reports"
        capture_state["strict_run_id"] = strict_run_id
        capture_state["strict_reports_root"] = strict_reports_root
        strict_config = getattr(orchestrator, "config", None)
        raw_request = inspect.getattr_static(
            type(plugin), "capture_role_plan_request", None
        )
        if type(raw_request) is not CaptureRolePlanRequest:
            return _run_start_abort(
                plugin_name=plugin_name,
                reports_root=strict_reports_root,
                run_id=strict_run_id,
                reason_code="capture_role_plan_invalid",
                outcome=PrepareRunGateOutcome.UNKNOWN.value,
                cases=None,
                requested_ids=case_ids,
                capture_attempted=False,
            )
        strict_role_request = raw_request
        try:
            if not isinstance(strict_config, TestbedConfig):
                raise RolePlanError("strict capture requires the selected testbed config")
            strict_role_plan = project_capture_role_plan(
                strict_config,
                strict_role_request,
            )
        except (RolePlanError, TypeError, ValueError):
            return _run_start_abort(
                plugin_name=plugin_name,
                reports_root=strict_reports_root,
                run_id=strict_run_id,
                reason_code="capture_role_plan_invalid",
                outcome=PrepareRunGateOutcome.UNKNOWN.value,
                cases=None,
                requested_ids=case_ids,
                capture_attempted=False,
            )
        try:
            provider_admission = orchestrator.run_backend.strict_capture_preflight(
                strict_run_id,
                strict_config,
                strict_role_request,
                strict_role_plan,
            )
        except Exception:
            provider_admission = None
        if not is_valid_strict_capture_provider_admission(provider_admission):
            return _run_start_abort(
                plugin_name=plugin_name,
                reports_root=strict_reports_root,
                run_id=strict_run_id,
                reason_code="capture_provider_protocol_invalid",
                outcome=PrepareRunGateOutcome.UNKNOWN.value,
                cases=None,
                requested_ids=case_ids,
                capture_attempted=False,
            )
        if provider_admission.outcome.value != "supported":
            return _run_start_abort(
                plugin_name=plugin_name,
                reports_root=strict_reports_root,
                run_id=strict_run_id,
                reason_code=provider_admission.reason_code or "capture_provider_unavailable",
                outcome=PrepareRunGateOutcome.UNKNOWN.value,
                cases=None,
                requested_ids=case_ids,
                capture_attempted=False,
            )
        capture_state["strict_preflight_active"] = True
        capture_state["strict_config"] = strict_config
        capture_state["strict_role_request"] = strict_role_request
        capture_state["strict_role_plan"] = strict_role_plan

    if plugin is not prebound_plugin:
        bind_testbed_config = getattr(plugin, "bind_testbed_config", None)
        if callable(bind_testbed_config):
            try:
                bind_testbed_config(getattr(orchestrator, "config", None))
            except Exception:
                if strict_capture_gate:
                    return _run_start_abort(
                        plugin_name=plugin_name,
                        reports_root=strict_reports_root,
                        run_id=strict_run_id,
                        reason_code="testbed_config_binding_failed",
                        outcome=PrepareRunGateOutcome.UNKNOWN.value,
                        cases=None,
                        requested_ids=case_ids,
                        capture_attempted=False,
                    )
                return abort_run_start_before_capture(
                    orchestrator,
                    plugin_name,
                    case_ids,
                    "testbed_config_binding_failed",
                )

    bind_project_root = getattr(plugin, "bind_project_root", None)
    if callable(bind_project_root):
        bind_project_root(getattr(orchestrator, "root", None))
    prepared = plugin.prepare_run(case_ids)
    cases = list(prepared.cases)
    prepared_artifacts = dict(prepared.artifacts)

    reports_root = Path(orchestrator.plugins_dir) / plugin_name / "reports"
    run_date = date.today()
    run_id = strict_run_id or datetime.now().strftime("%Y%m%dT%H%M%S%f")
    if strict_capture_gate:
        assert strict_config is not None
        assert strict_role_request is not None
        assert strict_role_plan is not None
        try:
            projected_after_prepare = project_capture_role_plan(
                strict_config,
                strict_role_request,
            )
        except (RolePlanError, TypeError, ValueError):
            projected_after_prepare = None
        if (
            projected_after_prepare is None
            or projected_after_prepare.digest != strict_role_plan.digest
        ):
            return _run_start_abort(
                plugin_name=plugin_name,
                reports_root=reports_root,
                run_id=run_id,
                reason_code="capture_role_plan_changed",
                outcome=PrepareRunGateOutcome.UNKNOWN.value,
                cases=cases,
                requested_ids=case_ids,
                capture_attempted=False,
            )
        supplied_plan = getattr(prepared, "effective_role_plan", None)
        if supplied_plan is not None and supplied_plan is not strict_role_plan:
            return _run_start_abort(
                plugin_name=plugin_name,
                reports_root=reports_root,
                run_id=run_id,
                reason_code="capture_role_plan_changed",
                outcome=PrepareRunGateOutcome.UNKNOWN.value,
                cases=cases,
                requested_ids=case_ids,
                capture_attempted=False,
            )
        prepared.effective_role_plan = strict_role_plan
        capture_state["strict_artifact_dir"] = reports_root / run_id
        capture_state["strict_case_results"] = []
        capture_state["strict_case_seq_ranges"] = {}
    # Empty selections have no executable work to capture. Plugins can also
    # explicitly classify a non-empty selection as no-I/O (for example when
    # every prepared result is unsupported/N/A). Case planning, execution, and
    # reporting still run for the latter; only Core's environment probes stop.
    capture_enabled = bool(cases) and getattr(prepared, "no_io", False) is not True
    if strict_capture_gate and cases and not capture_enabled:
        return _run_start_abort(
            plugin_name=plugin_name,
            reports_root=reports_root,
            run_id=run_id,
            reason_code="required_capture_disabled",
            outcome=PrepareRunGateOutcome.UNKNOWN.value,
            cases=cases,
            requested_ids=case_ids,
            capture_attempted=False,
        )
    if capture_enabled:
        if strict_capture_gate:
            try:
                projected_before_begin = project_capture_role_plan(
                    strict_config,
                    strict_role_request,
                )
            except (RolePlanError, TypeError, ValueError):
                projected_before_begin = None
            if (
                projected_before_begin is None
                or projected_before_begin.digest != strict_role_plan.digest
            ):
                return _run_start_abort(
                    plugin_name=plugin_name,
                    reports_root=reports_root,
                    run_id=run_id,
                    reason_code="capture_role_plan_changed",
                    outcome=PrepareRunGateOutcome.UNKNOWN.value,
                    cases=cases,
                    requested_ids=case_ids,
                    capture_attempted=False,
                )
            try:
                run_handle = orchestrator.run_backend.begin_strict_capture(
                    run_id,
                    strict_config,
                    strict_role_request,
                    strict_role_plan,
                )
            except StrictCaptureError as exc:
                capture_state["capture_attempted"] = True
                return _run_start_abort(
                    plugin_name=plugin_name,
                    reports_root=reports_root,
                    run_id=run_id,
                    reason_code=exc.reason_code,
                    outcome=PrepareRunGateOutcome.UNKNOWN.value,
                    cases=cases,
                    requested_ids=case_ids,
                    capture_attempted=True,
                    capture_status=(
                        "unknown" if exc.operation_uncertain else "incomplete"
                    ),
                )
            except Exception:
                capture_state["capture_attempted"] = True
                return _run_start_abort(
                    plugin_name=plugin_name,
                    reports_root=reports_root,
                    run_id=run_id,
                    reason_code="capture_begin_unknown",
                    outcome=PrepareRunGateOutcome.UNKNOWN.value,
                    cases=cases,
                    requested_ids=case_ids,
                    capture_attempted=True,
                    capture_status="unknown",
                )
            capture_state["strict_preflight_active"] = False
            capture_state["strict_handle"] = run_handle
            capture_state["capture_attempted"] = True
            run_seq_start = run_handle.seq_start
            if not is_valid_sequence_marker(run_seq_start):
                return _run_start_abort(
                    plugin_name=plugin_name,
                    reports_root=reports_root,
                    run_id=run_id,
                    reason_code=(
                        "run_start_marker_unavailable"
                        if run_seq_start is None
                        else "run_start_marker_invalid"
                    ),
                    outcome=PrepareRunGateOutcome.UNKNOWN.value,
                    cases=cases,
                    requested_ids=case_ids,
                    capture_attempted=True,
                )
            try:
                capture_context = orchestrator.run_backend.get_strict_capture_context(
                    run_handle,
                    run_id=run_id,
                    run_seq_start=run_seq_start,
                )
            except Exception:
                capture_context = None
            if not is_valid_capture_context(
                capture_context,
                run_id=run_id,
                start_sequence=run_seq_start,
            ):
                capture_state["capture_cleanup_suppressed"] = True
                return _run_start_abort(
                    plugin_name=plugin_name,
                    reports_root=reports_root,
                    run_id=run_id,
                    reason_code="capture_context_invalid",
                    outcome=PrepareRunGateOutcome.UNKNOWN.value,
                    cases=cases,
                    requested_ids=case_ids,
                    capture_attempted=True,
                    run_seq_start=run_seq_start,
                )

            try:
                gate_result = plugin.prepare_run_after_capture(prepared, capture_context)
            except Exception:
                gate_result = None
                gate_exception = True
            else:
                gate_exception = False
            if not is_valid_gate_result(gate_result):
                gate_reason = (
                    "post_capture_gate_exception"
                    if gate_exception
                    else "post_capture_gate_result_missing"
                    if gate_result is None
                    else "post_capture_gate_result_invalid"
                )
                return _run_start_abort(
                    plugin_name=plugin_name,
                    reports_root=reports_root,
                    run_id=run_id,
                    reason_code=gate_reason,
                    outcome=PrepareRunGateOutcome.UNKNOWN.value,
                    cases=cases,
                    requested_ids=case_ids,
                    capture_attempted=True,
                    run_seq_start=run_seq_start,
                )
            if gate_result.outcome is not PrepareRunGateOutcome.ACCEPTED:
                return _run_start_abort(
                    plugin_name=plugin_name,
                    reports_root=reports_root,
                    run_id=run_id,
                    reason_code=gate_result.reason_code,
                    outcome=gate_result.outcome.value,
                    cases=cases,
                    requested_ids=case_ids,
                    capture_attempted=True,
                    run_seq_start=run_seq_start,
                    gate_result=gate_result,
                )
            try:
                projected_after_gate = project_capture_role_plan(
                    strict_config,
                    strict_role_request,
                )
            except (RolePlanError, TypeError, ValueError):
                projected_after_gate = None
            if (
                projected_after_gate is None
                or projected_after_gate.digest != strict_role_plan.digest
                or getattr(prepared, "effective_role_plan", None) is not strict_role_plan
            ):
                return _run_start_abort(
                    plugin_name=plugin_name,
                    reports_root=reports_root,
                    run_id=run_id,
                    reason_code="capture_role_plan_changed",
                    outcome=PrepareRunGateOutcome.UNKNOWN.value,
                    cases=cases,
                    requested_ids=case_ids,
                    capture_attempted=True,
                    run_seq_start=run_seq_start,
                )
            prepared.run_start_gate = gate_result
            prepared_artifacts["run_start_gate"] = gate_result.to_payload()
        else:
            # The legacy path deliberately retains setup/reset, sequence
            # markers, export and teardown behavior unchanged.
            capture_state["capture_attempted"] = True
            capture_path = orchestrator._start_run_capture(run_id)
            run_handle = _seq_tracking_handle(
                orchestrator,
                run_id=run_id,
                capture_path=capture_path,
            )
            run_seq_start = _mark_seq_position(orchestrator, run_handle)
        version_manifest = _capture_version_manifest(
            orchestrator,
            plugin=plugin,
            cases=cases,
        )
    else:
        run_handle = None
        run_seq_start = None
        version_manifest = {}

    fw_ver, fw_ver_source = _resolve_firmware_version(
        requested=dut_fw_ver,
        version_manifest=version_manifest,
    )
    artifact_dir = reports_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    agent_config = orchestrator.runner_selector.load_agent_config(plugin_name, plugin=plugin)
    execution_policy = orchestrator.runner_selector.build_execution_policy(agent_config)
    execution_policy = _apply_plugin_execution_policy(plugin, execution_policy)
    agent_trace_dir = artifact_dir / "agent_trace"
    agent_trace_dir.mkdir(parents=True, exist_ok=True)

    case_records: list[CaseRunRecord] = []
    planning_by_case: dict[str, Any] = {}
    case_trace_files: list[str] = []
    run_started_monotonic = time.monotonic()
    run_started_at_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    first_case_started_monotonic: float | None = None
    first_case_started_at_iso = ""

    case_seq_ranges: dict[str, dict[str, int | None]] = {}
    if strict_capture_gate:
        capture_state["strict_case_results"] = case_records
        capture_state["strict_case_seq_ranges"] = case_seq_ranges
    loop_error: Exception | None = None
    strict_abort: dict[str, Any] | None = None

    def _record_strict_abort(reason_code: str, next_case_ordinal: int) -> None:
        nonlocal strict_abort
        unexecuted = [
            str(item.get("id", "?")) for item in cases[next_case_ordinal:]
        ]
        strict_abort = {
            "stage": "case_execution",
            "outcome": PrepareRunGateOutcome.UNKNOWN.value,
            "reason_code": reason_code,
            "executed_case_count": len(case_records),
            "selected_case_count": len(cases),
            "unexecuted_case_ids": unexecuted,
        }
        prepared_artifacts["run_abort"] = strict_abort
        try:
            (artifact_dir / "run-abort.json").write_text(
                json.dumps(strict_abort, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
                pass

    case_ordinal = 1
    last_checkpoint_sequence = run_seq_start if strict_capture_gate else None
    try:
        for case_ordinal, case in enumerate(cases, start=1):
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
            planning_result = orchestrator._plan_case(
                run_id=run_id,
                plugin_name=plugin_name,
                case=case,
                case_ordinal=case_ordinal,
                case_count=len(cases),
                execution_policy=execution_policy,
            )
            planning_by_case[case_id] = planning_result
            orchestrator._build_execution_engine(
                plugin_name=plugin_name,
                plugin=plugin,
                agent_config=agent_config,
                run_id=run_id,
                case_id=case_id,
                runner=selected_runner,
                provider_config=None,
            )

            if strict_capture_gate:
                try:
                    position_before = orchestrator.run_backend.checkpoint_strict_capture(
                        run_handle
                    )
                    if (
                        type(position_before) is not StrictCapturePosition
                        or not is_valid_sequence_marker(position_before.sequence)
                        or (
                            last_checkpoint_sequence is not None
                            and position_before.sequence < last_checkpoint_sequence
                        )
                    ):
                        raise StrictCaptureError("capture_checkpoint_invalid")
                    seq_before = position_before.sequence
                except StrictCaptureError as exc:
                    _record_strict_abort(exc.reason_code, case_ordinal - 1)
                    break
                except Exception:
                    _record_strict_abort("capture_checkpoint_unknown", case_ordinal - 1)
                    break
            else:
                seq_before = _mark_seq_position(orchestrator, run_handle)
            case_started_monotonic = time.monotonic()
            case_started_at_iso = datetime.now().astimezone().isoformat(timespec="seconds")
            if first_case_started_monotonic is None:
                first_case_started_monotonic = case_started_monotonic
                first_case_started_at_iso = case_started_at_iso
            retry_result = orchestrator.execution_engine.execute_with_retry(
                plugin=plugin,
                case=case,
                runner=selected_runner,
                execution_policy=execution_policy,
            )
            case_finished_monotonic = time.monotonic()
            case_finished_at_iso = datetime.now().astimezone().isoformat(timespec="seconds")
            checkpoint_problem: str | None = None
            if strict_capture_gate:
                try:
                    position_after = orchestrator.run_backend.checkpoint_strict_capture(
                        run_handle
                    )
                    if (
                        type(position_after) is not StrictCapturePosition
                        or not is_valid_sequence_marker(position_after.sequence)
                        or position_after.sequence < seq_before
                    ):
                        raise StrictCaptureError("capture_checkpoint_invalid")
                    seq_after = position_after.sequence
                    last_checkpoint_sequence = seq_after
                except StrictCaptureError as exc:
                    seq_after = None
                    checkpoint_problem = exc.reason_code
                except Exception:
                    seq_after = None
                    checkpoint_problem = "capture_checkpoint_unknown"
            else:
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
                    planning_result=planning_result,
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
            if checkpoint_problem is not None:
                _record_strict_abort(checkpoint_problem, case_ordinal)
                break
            if getattr(retry_result, "abort_run", False) is True:
                # Later cases were never executed and must not acquire verdicts.
                abort_summary = {
                    "case_id": case_id,
                    "reason": retry_result.abort_reason,
                    "executed_case_count": len(case_records),
                    "requested_case_count": len(cases),
                    "unexecuted_case_ids": [str(item.get("id", "?")) for item in cases[case_ordinal:]],
                }
                prepared_artifacts["run_abort"] = abort_summary
                (artifact_dir / "run-abort.json").write_text(
                    json.dumps(abort_summary, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                break
    except Exception as exc:
        if strict_capture_gate:
            next_case_ordinal = max(0, case_ordinal - 1)
            _record_strict_abort("case_execution_unknown", next_case_ordinal)
        else:
            loop_error = exc

    dut_log_path = ""
    sta_log_path = ""
    if capture_enabled:
        if strict_capture_gate:
            try:
                harvest = orchestrator.run_backend.harvest_strict_for_handle(
                    run_handle,
                    artifact_dir,
                    case_records,
                    case_seq_ranges,
                )
                if type(harvest) is not StrictCaptureHarvest:
                    raise StrictCaptureError("capture_harvest_result_invalid")
            except Exception:
                harvest = StrictCaptureHarvest(
                    StrictCaptureHarvestStatus.UNKNOWN,
                    "capture_harvest_failed",
                )
            capture_state["strict_harvested"] = True
            capture_state["strict_harvest_payload"] = harvest.to_payload()
            prepared_artifacts["core_run_capture"] = harvest.to_payload()
            if harvest.status is StrictCaptureHarvestStatus.COMPLETE:
                dut_log_path = harvest.dut_log_path
                sta_log_path = harvest.sta_log_path
            if harvest.status is not StrictCaptureHarvestStatus.COMPLETE:
                if not isinstance(prepared_artifacts.get("run_abort"), dict):
                    _record_strict_abort(harvest.reason_code, len(cases))
                run_abort_payload = prepared_artifacts.get("run_abort")
                if isinstance(run_abort_payload, dict):
                    run_abort_payload["core_run_capture"] = harvest.to_payload()
                    try:
                        (artifact_dir / "run-abort.json").write_text(
                            json.dumps(run_abort_payload, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    except OSError:
                        pass
            elif isinstance(prepared_artifacts.get("run_abort"), dict):
                prepared_artifacts["run_abort"]["core_run_capture"] = harvest.to_payload()
                try:
                    (artifact_dir / "run-abort.json").write_text(
                        json.dumps(
                            prepared_artifacts["run_abort"],
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
        else:
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
                _stop_run_capture_once(orchestrator, capture_state)

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
        cases_count=len(case_records) if strict_capture_gate else len(cases),
        run_started_monotonic=run_started_monotonic,
        run_started_at_iso=run_started_at_iso,
        first_case_started_monotonic=first_case_started_monotonic,
        first_case_started_at_iso=first_case_started_at_iso,
        artifacts=prepared_artifacts,
        version_manifest=version_manifest,
    )

    def _write_core_cost_payload(
        *,
        analysis: Any,
        metrics: Mapping[str, Any],
    ) -> Any:
        from testpilot.reporting.usage_reporter import (
            CoreCostArtifacts,
            build_core_cost_report,
            write_core_cost_artifacts,
        )

        try:
            frozen_usage = orchestrator.usage_ledger.freeze()
            runtime = getattr(orchestrator, "agent_runtime", None)
            agent_state = (
                runtime.public_summary()
                if runtime is not None and hasattr(runtime, "public_summary")
                else {}
            )
            report = build_core_cost_report(
                run_result=run_result,
                planning_by_case=planning_by_case,
                agent_recovery_support=getattr(orchestrator, "agent_recovery_support", {}),
                usage=frozen_usage,
                metrics=metrics,
                analysis=analysis,
                agent_state=agent_state,
            )
            return write_core_cost_artifacts(
                artifact_dir=artifact_dir,
                report=report,
                usage=frozen_usage,
                analysis=analysis,
            )
        except Exception as exc:
            log.warning("core cost artifacts failed; continuing", exc_info=True)
            return CoreCostArtifacts(
                status="failed",
                analysis_status=getattr(analysis, "status", "unavailable"),
                error_type=type(exc).__name__,
            )

    from testpilot.core.assistance_metrics import compute_assistance_metrics

    assistance_metrics = compute_assistance_metrics(case_records)
    if loop_error is not None:
        aborted_analysis = RunAnalysisResult(status="skipped_aborted")
        core_artifacts = _write_core_cost_payload(
            analysis=aborted_analysis,
            metrics=assistance_metrics,
        )
        run_result.artifacts["core_agent_analysis"] = aborted_analysis.to_dict()
        run_result.artifacts["core_cost_report"] = core_artifacts.to_payload()
        setattr(loop_error, "core_agent_analysis", aborted_analysis.to_dict())
        setattr(loop_error, "core_cost_report", core_artifacts.to_payload())
        raise loop_error.with_traceback(loop_error.__traceback__)

    # Analysis is deliberately a run-end operation: all case retry records
    # above already contain their final verdicts, and this snapshot excludes
    # the analysis calls themselves from per-case direct usage.
    direct_usage = orchestrator.usage_ledger.snapshot()
    analysis_metrics = {
        **assistance_metrics,
        "cases": len(case_records),
        "pass_count": sum(bool(record.retry.verdict) for record in case_records),
        "fail_count": sum(not bool(record.retry.verdict) for record in case_records),
        "agent_tokens": direct_usage.model_tokens(),
        "duration_seconds": round(max(0.0, time.monotonic() - run_started_monotonic), 3),
    }
    run_analysis = orchestrator._analyze_run(
        run_result=run_result,
        metrics=analysis_metrics,
        direct_usage=direct_usage,
    )
    core_artifacts = _write_core_cost_payload(
        analysis=run_analysis,
        metrics=assistance_metrics,
    )
    reporter = plugin.create_reporter()
    build_reports = getattr(reporter, "build_reports", None)
    if not callable(build_reports):
        raise RuntimeError(f"{plugin_name} reporter does not implement build_reports()")
    payload = build_reports(run_result)
    # Keep the plugin contract unchanged: the reporter sees the RunResult
    # exactly as produced by the core run.  Core-owned analysis and cost
    # pointers are attached only after plugin reporting has completed.
    run_result.artifacts["core_agent_analysis"] = run_analysis.to_dict()
    if isinstance(payload, dict):
        if "run_abort" in run_result.artifacts:
            payload["status"] = "aborted"
            payload["run_abort"] = dict(run_result.artifacts["run_abort"])
        payload.setdefault(
            "agent_session_degraded",
            getattr(
                orchestrator,
                "agent_session_degraded",
                {"degraded": False, "reason": ""},
            ),
        )
        agent_recovered_case_ids: list[str] = []
        tier2_audit: list[dict[str, Any]] = []
        for record in case_records:
            if bool(record.retry.agent_recovered):
                agent_recovered_case_ids.append(record.case_id)
            raw_audit = record.retry.tier2_audit or []
            tier2_audit.extend(
                dict(item) for item in raw_audit if isinstance(item, dict)
            )
        payload["tier2_remediation"] = {
            "agent_recovered_case_ids": agent_recovered_case_ids,
            "audit": tier2_audit,
        }
        payload["core_agent_analysis"] = run_analysis.to_dict()
        payload["core_cost_report"] = core_artifacts.to_payload()
    return payload


run_cases = run

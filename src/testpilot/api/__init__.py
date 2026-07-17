"""testpilot.api — plugin 的唯一公開契約表面。

凡未經本模組匯出之符號,即為 core 私有,不對 plugin 承諾穩定。
本層以 re-export 既有符號為主(契約宣告與實作分離);唯一例外是本模組定義的 `API_VERSION` —— plugin SDK 契約版本常數。
"""
from __future__ import annotations

from testpilot.core.api_entry import run_one_case
from testpilot.core.case_utils import (
    case_band_results,
    case_d_number,
    case_matches_requested_ids,
    overall_case_status,
    sanitize_case_id,
    step_command_lines,
    stringify_step_command,
)
from testpilot.cli_support import (
    CliRegistrar,
    get_orchestrator,
    load_registered_plugin,
    run_plugin_cases,
)
from testpilot.core.plugin_base import IncompatiblePluginError, PluginBase
from testpilot.core.prepared_run import PreparedRun
from testpilot.core.testbed_config import TestbedConfig
from testpilot.reporting.html_reporter import HtmlReporter
from testpilot.reporting.reporter import (
    IReporter,
    JsonReporter,
    MarkdownReporter,
    generate_reports,
)
from testpilot.schema.case_schema import (
    CaseValidationError,
    load_case,
    load_cases_dir,
    require_bool,
    require_mapping,
    require_non_empty_string,
    require_string_mapping,
    validate_string_list,
    validate_case,
)
from testpilot.transport.base import StubTransport, TransportBase
from testpilot.transport.factory import create_transport
from testpilot.serialwrap_binary import resolve_serialwrap_binary

from testpilot.runtime.run_backend import (
    ExportRequest,
    ExportResult,
    RunBackend,
    RunHandle,
)
from testpilot.core.tier2_recovery import (
    Tier2Capability,
    Tier2PlanValidationError,
    Tier2RecoveryAudit,
    Tier2RecoveryContext,
)

from testpilot.api import excel_adapter  # noqa: F401  (公開子模組)

API_VERSION = "1.2"

__all__ = [
    "API_VERSION",
    "IncompatiblePluginError",
    "PluginBase",
    "PreparedRun",
    "IReporter",
    "MarkdownReporter",
    "JsonReporter",
    "HtmlReporter",
    "generate_reports",
    "TransportBase",
    "StubTransport",
    "create_transport",
    "resolve_serialwrap_binary",
    "load_case",
    "load_cases_dir",
    "CaseValidationError",
    "validate_case",
    "require_non_empty_string",
    "validate_string_list",
    "require_mapping",
    "require_string_mapping",
    "require_bool",
    "TestbedConfig",
    "stringify_step_command",
    "step_command_lines",
    "case_band_results",
    "case_matches_requested_ids",
    "overall_case_status",
    "sanitize_case_id",
    "case_d_number",
    "run_one_case",
    "CliRegistrar",
    "get_orchestrator",
    "load_registered_plugin",
    "run_plugin_cases",
    "RunBackend",
    "RunHandle",
    "ExportRequest",
    "ExportResult",
    "Tier2Capability",
    "Tier2PlanValidationError",
    "Tier2RecoveryAudit",
    "Tier2RecoveryContext",
    "excel_adapter",
]

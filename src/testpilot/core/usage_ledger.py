"""Append-only, secret-safe accounting for core SDK invocations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from typing import Any, Callable, Literal, get_args
from uuid import uuid4

UsagePurpose = Literal["case_planning", "agent_recovery", "run_analysis_batch", "run_analysis_reducer"]
UsageAllocation = Literal["direct", "shared"]
InvocationStatus = Literal["completed", "failed"]
UsageStatus = Literal["exact", "unavailable"]


class LedgerFrozenError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class UsageBinding:
    invocation_id: str
    run_id: str
    session_id: str
    case_id: str | None
    purpose: UsagePurpose
    model: str
    started_at: str

    @property
    def allocation(self) -> UsageAllocation:
        return "shared" if self.purpose.startswith("run_analysis_") else "direct"


@dataclass(frozen=True, slots=True)
class InvocationRecord:
    invocation_id: str
    run_id: str
    session_id: str
    case_id: str | None
    purpose: UsagePurpose
    allocation: UsageAllocation
    model: str
    started_at: str
    finished_at: str
    status: InvocationStatus
    error_type: str
    usage_status: UsageStatus


@dataclass(frozen=True, slots=True)
class UsageRecord:
    invocation_id: str
    session_id: str
    api_call_id: str | None
    event_id: str | None
    dedupe_basis: Literal["api_call_id", "event_id"]
    case_id: str | None
    purpose: UsagePurpose
    allocation: UsageAllocation
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    provider_cost_units: float | None
    duration_seconds: float | None
    timestamp: str

    @property
    def model_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    invocations: tuple[InvocationRecord, ...]
    usage: tuple[UsageRecord, ...]
    journal_lines: tuple[str, ...]
    duplicate_usage_events: int
    rejected_usage_events: int
    reconciliation_events: int

    def call_count(self, *, case_id: str | None = None, purpose: UsagePurpose | None = None) -> int:
        return sum(1 for row in self.invocations if (case_id is None or row.case_id == case_id) and (purpose is None or row.purpose == purpose))

    def model_tokens(self, *, case_id: str | None = None, purpose: UsagePurpose | None = None) -> int:
        return sum(row.model_tokens for row in self.usage if (case_id is None or row.case_id == case_id) and (purpose is None or row.purpose == purpose))

    def case_totals(self, case_id: str) -> dict[str, int]:
        rows = [row for row in self.usage if row.case_id == case_id]
        return {"input_tokens": sum(row.input_tokens for row in rows), "output_tokens": sum(row.output_tokens for row in rows), "model_tokens": sum(row.model_tokens for row in rows), "cache_read_tokens": sum(row.cache_read_tokens for row in rows), "cache_write_tokens": sum(row.cache_write_tokens for row in rows)}


class UsageLedger:
    def __init__(self) -> None:
        self._invocations: list[InvocationRecord] = []
        self._bindings: dict[str, UsageBinding] = {}
        self._usage: list[UsageRecord] = []
        self._journal: list[dict[str, Any]] = []
        self._seen_api_calls: set[tuple[str, str]] = set()
        self._seen_event_ids: set[tuple[str, str]] = set()
        self._duplicate_usage_events = 0
        self._rejected_usage_events = 0
        self._reconciliation_events = 0
        self._frozen = False

    def _check_mutable(self) -> None:
        if self._frozen:
            raise LedgerFrozenError("usage ledger is frozen")

    def start_invocation(self, *, run_id: str, session_id: str, case_id: str | None, purpose: UsagePurpose, model: str) -> UsageBinding:
        self._check_mutable()
        if purpose not in get_args(UsagePurpose):
            raise ValueError(f"unsupported usage purpose: {purpose}")
        binding = UsageBinding(str(uuid4()), run_id, session_id, case_id, purpose, model, _now())
        self._bindings[binding.invocation_id] = binding
        self._journal.append({"event": "invocation_started", "invocation_id": binding.invocation_id, "run_id": run_id, "session_id": session_id, "case_id": case_id, "purpose": purpose, "allocation": binding.allocation, "model": model, "started_at": binding.started_at})
        return binding

    def event_handler(self, binding: UsageBinding) -> Callable[[Any], None]:
        return lambda event: self.ingest_event(event, binding=binding)

    @staticmethod
    def _number(value: Any, *, integral: bool, default: int | float | None = None) -> int | float | None:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid usage number")
        if integral and int(value) != value:
            raise ValueError("token counts must be integral")
        return int(value) if integral else float(value)

    def ingest_event(self, event: Any, *, binding: UsageBinding) -> bool:
        if self._frozen:
            return False
        try:
            event_type = getattr(getattr(event, "type", None), "value", getattr(event, "type", None))
            if event_type == "session.usage_info":
                self._reconciliation_events += 1
                return False
            if event_type != "assistant.usage":
                return False
            data = event.data
            event_id = getattr(event, "id", None)
            api_call_id = getattr(data, "api_call_id", None)
            if not api_call_id and not event_id:
                raise ValueError("usage event has no identifier")
            dedupe_basis: Literal["api_call_id", "event_id"] = "api_call_id" if api_call_id else "event_id"
            api_key = (
                (binding.session_id, str(api_call_id))
                if api_call_id
                else None
            )
            event_key = (
                (binding.session_id, str(event_id))
                if event_id
                else None
            )
            if (
                (api_key is not None and api_key in self._seen_api_calls)
                or (event_key is not None and event_key in self._seen_event_ids)
            ):
                self._duplicate_usage_events += 1
                return False
            inputs = self._number(getattr(data, "input_tokens", None), integral=True)
            outputs = self._number(getattr(data, "output_tokens", None), integral=True)
            if inputs is None or outputs is None:
                raise ValueError("usage event missing token counts")
            cache_read = self._number(getattr(data, "cache_read_tokens", 0), integral=True, default=0)
            cache_write = self._number(getattr(data, "cache_write_tokens", 0), integral=True, default=0)
            cost = self._number(getattr(data, "cost", None), integral=False)
            duration = self._number(getattr(data, "duration", None), integral=False)
            if api_key is not None:
                self._seen_api_calls.add(api_key)
            if event_key is not None:
                self._seen_event_ids.add(event_key)
            timestamp = getattr(event, "timestamp", None)
            timestamp = timestamp.isoformat() if hasattr(timestamp, "isoformat") else _now()
            row = UsageRecord(binding.invocation_id, binding.session_id, str(api_call_id) if api_call_id else None, str(event_id) if event_id else None, dedupe_basis, binding.case_id, binding.purpose, binding.allocation, getattr(data, "model", binding.model), inputs, outputs, cache_read or 0, cache_write or 0, cost, duration, timestamp)
            self._usage.append(row)
            self._journal.append({"event": "assistant_usage", **asdict(row)})
            return True
        except Exception:
            self._rejected_usage_events += 1
            return False

    def finish_invocation(self, binding: UsageBinding, *, status: InvocationStatus, error_type: str = "") -> None:
        self._check_mutable()
        if status not in ("completed", "failed"):
            raise ValueError(f"unsupported invocation status: {status}")
        exact = any(row.invocation_id == binding.invocation_id for row in self._usage)
        record = InvocationRecord(binding.invocation_id, binding.run_id, binding.session_id, binding.case_id, binding.purpose, binding.allocation, binding.model, binding.started_at, _now(), status, error_type if status == "failed" else "", "exact" if exact else "unavailable")
        self._invocations.append(record)
        self._journal.append({"event": "invocation_finished", **asdict(record)})

    def snapshot(self) -> UsageSnapshot:
        lines = tuple(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) for row in self._journal)
        return UsageSnapshot(tuple(self._invocations), tuple(self._usage), lines, self._duplicate_usage_events, self._rejected_usage_events, self._reconciliation_events)

    def freeze(self) -> UsageSnapshot:
        self._frozen = True
        return self.snapshot()

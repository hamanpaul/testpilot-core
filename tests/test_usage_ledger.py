from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from testpilot.core.usage_ledger import LedgerFrozenError, UsageLedger


def _usage_event(*, event_id="event-1", api_call_id="call-1", input_tokens=100.0, output_tokens=20.0):
    return SimpleNamespace(
        id=event_id,
        timestamp=datetime(2026, 7, 17, tzinfo=timezone.utc),
        type=SimpleNamespace(value="assistant.usage"),
        data=SimpleNamespace(
            api_call_id=api_call_id,
            model="azure-deployment",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=40.0,
            cache_write_tokens=5.0,
            cost=1.25,
            duration=2.5,
        ),
    )


def _binding(ledger, *, purpose="case_planning", case_id="D001"):
    return ledger.start_invocation(
        run_id="run-1", session_id="session-1", case_id=case_id,
        purpose=purpose, model="azure-deployment",
    )


def _record_completed(ledger, *, purpose="case_planning", case_id="D001"):
    binding = ledger.start_invocation(
        run_id="run-1",
        session_id="session-analysis" if purpose == "run_analysis_batch" else "session-1",
        case_id=case_id,
        purpose=purpose,
        model="azure-deployment",
    )
    ledger.event_handler(binding)(_usage_event())
    ledger.finish_invocation(binding, status="completed")
    return ledger.snapshot().invocations[-1]


def _session_usage_info_event():
    return SimpleNamespace(
        id="session-event",
        type=SimpleNamespace(value="session.usage_info"),
        data=SimpleNamespace(input_tokens=999, output_tokens=999),
    )


def test_started_failed_invocation_counts_call_without_usage():
    ledger = UsageLedger()
    binding = _binding(ledger)
    ledger.finish_invocation(binding, status="failed", error_type="TimeoutError")
    snapshot = ledger.freeze()
    assert snapshot.call_count(case_id="D001", purpose="case_planning") == 1
    assert snapshot.model_tokens(case_id="D001") == 0
    assert snapshot.invocations[0].usage_status == "unavailable"


def test_usage_dedupes_by_api_call_then_event_id():
    ledger = UsageLedger()
    binding = _binding(ledger)
    handler = ledger.event_handler(binding)
    handler(_usage_event(event_id="event-1", api_call_id="call-1"))
    handler(_usage_event(event_id="event-2", api_call_id="call-1"))
    handler(_usage_event(event_id="event-1", api_call_id="call-2"))
    ledger.finish_invocation(binding, status="completed")
    snapshot = ledger.freeze()
    assert len(snapshot.usage) == 1
    assert snapshot.duplicate_usage_events == 2
    assert snapshot.usage[0].dedupe_basis == "api_call_id"
    assert snapshot.model_tokens(case_id="D001") == 120
    assert snapshot.usage[0].cache_read_tokens == 40
    assert snapshot.usage[0].provider_cost_units == 1.25
    assert snapshot.usage[0].duration_seconds == 2.5


def test_event_id_is_fallback_when_api_call_id_missing():
    ledger = UsageLedger()
    binding = _binding(ledger)
    handler = ledger.event_handler(binding)
    handler(_usage_event(event_id="event-1", api_call_id=None))
    handler(_usage_event(event_id="event-1", api_call_id=None))
    ledger.finish_invocation(binding, status="completed")
    snapshot = ledger.freeze()
    assert len(snapshot.usage) == 1
    assert snapshot.duplicate_usage_events == 1
    assert snapshot.usage[0].dedupe_basis == "event_id"


def test_event_id_is_also_reserved_when_api_call_id_exists():
    ledger = UsageLedger()
    binding = _binding(ledger)
    handler = ledger.event_handler(binding)
    handler(_usage_event(event_id="event-1", api_call_id="call-1"))
    handler(_usage_event(event_id="event-1", api_call_id=None))
    ledger.finish_invocation(binding, status="completed")
    snapshot = ledger.freeze()
    assert len(snapshot.usage) == 1
    assert snapshot.duplicate_usage_events == 1


def test_api_call_dedupe_applies_across_bindings_in_same_session():
    ledger = UsageLedger()
    binding_one = ledger.start_invocation(
        run_id="run-1",
        session_id="shared-session",
        case_id="D001",
        purpose="case_planning",
        model="azure-deployment",
    )
    binding_two = ledger.start_invocation(
        run_id="run-1",
        session_id="shared-session",
        case_id="D002",
        purpose="agent_recovery",
        model="azure-deployment",
    )

    ledger.event_handler(binding_one)(_usage_event(event_id="event-1", api_call_id="call-1"))
    ledger.event_handler(binding_two)(_usage_event(event_id="event-2", api_call_id="call-1"))
    ledger.finish_invocation(binding_one, status="completed")
    ledger.finish_invocation(binding_two, status="completed")

    snapshot = ledger.freeze()

    assert len(snapshot.usage) == 1
    assert snapshot.duplicate_usage_events == 1
    assert snapshot.usage[0].case_id == "D001"


@pytest.mark.parametrize("event_id,api_call_id,input_tokens", [
    (None, None, 1.0), ("event", "call", -1.0),
    ("event", "call", float("nan")), ("event", "call", 1.5),
])
def test_invalid_usage_is_rejected_without_raising(event_id, api_call_id, input_tokens):
    ledger = UsageLedger()
    binding = _binding(ledger)
    ledger.event_handler(binding)(_usage_event(event_id=event_id, api_call_id=api_call_id, input_tokens=input_tokens))
    assert ledger.snapshot().rejected_usage_events == 1


def test_shared_and_direct_allocation_are_not_mixed():
    ledger = UsageLedger()
    direct = _record_completed(ledger, purpose="agent_recovery")
    shared = _record_completed(ledger, purpose="run_analysis_batch", case_id=None)
    snapshot = ledger.freeze()
    assert direct.allocation == "direct"
    assert shared.allocation == "shared"
    assert snapshot.model_tokens(purpose="agent_recovery") == 120
    assert snapshot.model_tokens(purpose="run_analysis_batch") == 120


def test_session_usage_info_is_reconciliation_only():
    ledger = UsageLedger()
    binding = _binding(ledger)
    ledger.event_handler(binding)(_session_usage_info_event())
    snapshot = ledger.freeze()
    assert snapshot.model_tokens() == 0
    assert snapshot.reconciliation_events == 1


def test_freeze_rejects_later_mutation():
    ledger = UsageLedger()
    ledger.freeze()
    with pytest.raises(LedgerFrozenError):
        _binding(ledger)

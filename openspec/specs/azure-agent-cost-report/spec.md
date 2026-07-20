## ADDED Requirements

### Requirement: Azure readiness automatically controls core agent support
TestPilot core SHALL resolve `COPILOT_PROVIDER_API_KEY`, `COPILOT_PROVIDER_BASE_URL`, and `COPILOT_MODEL` into `disabled_no_key`, `misconfigured`, `azure_ready`, or `degraded` state. Core MUST create only an Azure provider mapping, MUST ignore `COPILOT_PROVIDER_TYPE` as an enable switch, and MUST NOT fall back to OAuth or another provider.

#### Scenario: No API key
- **WHEN** the API key is absent, including when endpoint or deployment values exist
- **THEN** core runs deterministic execution, creates no agent session, emits no warning, and reports zero core model tokens

#### Scenario: Partial Azure configuration
- **WHEN** an API key exists but endpoint or deployment is missing
- **THEN** core reports a redacted misconfigured reason, continues deterministic execution, and creates no agent session

#### Scenario: Complete Azure configuration
- **WHEN** endpoint, API key, and deployment are present
- **THEN** core marks the runtime Azure-ready and every core SDK request uses that Azure deployment and private Azure provider mapping

#### Scenario: Provider or SDK failure
- **WHEN** an Azure SDK/provider/auth/session failure occurs during a run
- **THEN** core marks the runtime degraded, opens the run-scoped agent breaker, records only a stable error type, and continues deterministic execution without fallback

### Requirement: Core-owned agent phases are bounded and tool-denied
The core run loop SHALL perform one advisory, tool-denied planning attempt per case before deterministic execution when Azure is ready and the breaker is closed. Tier-2 recovery SHALL require effective policy and both plugin capability/executor overrides. Run-end analysis SHALL begin only after all final verdicts and SHALL use bounded redacted capsules.

#### Scenario: Per-case planning
- **WHEN** a case is selected on an Azure-ready run
- **THEN** core sends one bounded planning prompt using the Azure deployment, records advisory output only, and cannot change case semantics, runner identity, commands, criteria, retry policy, or verdict

#### Scenario: Breaker-open planning
- **WHEN** a prior core agent invocation has opened the run breaker
- **THEN** later cases record `skipped_circuit_breaker` with zero calls/tokens and still execute deterministically

#### Scenario: Unsupported tier-2 plugin
- **WHEN** effective tier-2 policy is enabled but the plugin has not overridden both capability/context and executor methods
- **THEN** core creates no recovery requester, reports unsupported/zero recovery usage, and leaves deterministic tier-1 remediation unchanged

#### Scenario: Run-end analysis ordering
- **WHEN** all cases have final verdicts
- **THEN** core builds capsules, performs one bounded batch or batch-plus-single-reducer analysis, and does not recursively analyze analysis usage

### Requirement: Usage and cost artifacts are exact and additive
Core SHALL count only accepted `assistant.usage` events, deduplicate authoritative API call IDs with event-ID fallback, preserve invocation calls independently from token availability, and write core-owned artifacts before attaching an additive pointer after the unchanged plugin reporter returns. Shared analysis tokens SHALL remain shared and all benefit metrics SHALL be observational.

#### Scenario: Duplicate usage
- **WHEN** the same `(session_id, api_call_id)` usage event is delivered more than once
- **THEN** the ledger counts it once; cache fields remain separate and provider cost is reported as `provider_cost_units`

#### Scenario: Failed model call
- **WHEN** a started invocation fails before authoritative usage is received
- **THEN** calls equals one, usage status is unavailable, and deterministic verdicts remain unchanged

#### Scenario: Core report integration
- **WHEN** the core run-loop report phase completes
- **THEN** JSON/Markdown artifacts contain per-case direct usage, deterministic/recovery outcomes, shared analysis usage, run totals, coverage, analysis status, and observational metrics; plugin `RunResult` and reporter contract remain unchanged

#### Scenario: Non-core execution path
- **WHEN** a custom-runner or skeleton path owns the full run loop
- **THEN** core makes no agent call and returns `unsupported_execution_path` with `core_sdk_calls_only` coverage

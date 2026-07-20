## Why

TestPilot core currently exposes provider/runner-driven agent setup, an interactive Azure path, and no core-owned accounting for per-case agent usage or remediation benefit. The approved core-only design needs a deterministic fallback when Azure credentials are absent, one Azure provider boundary when they are present, and an auditable cost/benefit report without changing plugin contracts.

## What Changes

- **BREAKING**: remove the interactive `--azure` enable flow and all GitHub OAuth/non-Azure fallback from core CLI behavior.
- Resolve Azure readiness automatically from endpoint, API key, and deployment environment variables; absent key means deterministic/no-agent mode.
- Add mandatory, pinned `github-copilot-sdk` runtime packaging and an Azure-only, tool-denied one-shot adapter.
- Execute advisory per-case planning before deterministic execution, capability-gated tier-2 recovery during retries, and bounded run-end analysis after all final verdicts.
- Record authoritative `assistant.usage` events in a run-scoped deduplicating ledger and produce per-case direct, shared, deterministic, recovery, total-token, and observational benefit metrics.
- Keep plugin APIs, selected runner identity, deterministic remediation ownership, plugin reporters, and custom-runner behavior compatible; mark non-core execution paths unsupported for this report.

## Capabilities

### New Capabilities

- `azure-agent-cost-report`: Azure-only runtime readiness, core agent invocation accounting, bounded analysis, and core-owned cost/benefit artifacts.

### Modified Capabilities

- `core-owned-execution-loop`: add the approved per-case planning, capability-gated recovery, run-end analysis ordering, and fail-soft core reporting requirements.

## Impact

- Core CLI/auth/session/orchestrator/run-loop and reporting modules, plus tests and offline packaging metadata.
- New core usage-ledger, planning, assistance-metrics, run-analysis, and usage-reporting modules.
- No wifi_llapi source, plugin configuration, case YAML, plugin reporter, `PluginBase` signature, or plugin API version changes.

## Context

The approved design is scoped to `testpilot-core`. The current core run loop selects a plugin runner, optionally creates an ordinary Copilot session, executes deterministic cases with plugin-owned remediation, and invokes the plugin reporter. Azure authentication still has interactive/OAuth paths, while usage and benefit accounting are not core-owned. The change crosses CLI, auth, SDK session, orchestration, run-loop, reporting, packaging, and governance boundaries.

Constraints are strict: no wifi_llapi or other plugin source/config/reporter changes; no new PluginBase/API_VERSION surface; no live DUT/STA/serialwrap actions; deterministic verdicts remain authoritative; and no secret may enter plugin-visible context or artifacts.

## Goals / Non-Goals

**Goals:**

- Make complete Azure endpoint/key/deployment environment configuration the only core agent enablement condition.
- Make no-key and incomplete configuration deterministic/no-agent modes without OAuth or other-provider fallback.
- Execute bounded, tool-denied per-case planning, capability-gated tier-2 recovery, and run-end analysis with exact SDK usage accounting.
- Produce additive core-owned JSON/Markdown cost artifacts with direct per-case, shared run-analysis, deterministic outcome, recovery outcome, total tokens, and observational metrics.
- Preserve selected runner identity, plugin reporter contract, deterministic remediation ownership, and unsupported custom/skeleton paths.

**Non-Goals:**

- Changing plugin source, plugin configuration, case YAML, plugin reporters, PluginBase signatures, or API versions.
- Naming, interpreting, or executing wifi/serialwrap/DUT/STA safe actions in core agent prompts or tools.
- Treating observed rates as causal uplift/regression or assigning shared analysis tokens to individual cases.
- Supporting model calls made outside the core SDK adapter on custom-runner paths.

## Decisions

1. **Private Azure runtime, public status only.** Resolve the environment into a secret-safe status object. The private provider mapping remains inside core-owned orchestration; Click context exposes only public state, notice, and a `None` compatibility provider key. This prevents plugin commands from retrieving endpoint/key through a runtime accessor.
2. **Azure is the only provider boundary.** Remove interactive `--azure`, OAuth fallback, and `COPILOT_PROVIDER_TYPE` enable semantics. The SDK deployment comes from `COPILOT_MODEL`; plugin runner model labels remain execution metadata.
3. **One generic one-shot controller.** Planning, recovery, and analysis use one tool-denied adapter with purpose/session binding, event subscription before send, run circuit breaker, fail-soft schema validation, and terminal ledger records for every started invocation.
4. **Authoritative append-only usage ledger.** Count only accepted `assistant.usage`; deduplicate by `(session_id, api_call_id)` with event-id fallback, reconcile `session.usage_info` without adding it, and keep cache/provider cost fields separate from model tokens.
5. **Run-end bounded analysis.** Build redacted capsules only after final verdicts. Pack at a 48,000-character target, use at most one reducer for multiple batches, compact reducer input to 40,000 characters, and enforce the SDK's 64,000-character prompt ceiling.
6. **Capability ownership remains with plugins.** Tier-2 is supported only when effective policy is enabled and both versioned PluginBase methods are overridden. Core never converts tier-1 action names into agent capabilities.
7. **Additive report integration.** Freeze and write core artifacts before calling the unchanged plugin reporter, then attach only an additive `core_cost_report` pointer. Custom/skeleton paths return `unsupported_execution_path` without core calls.

Alternatives considered: retaining OAuth as a fallback was rejected because it violates the Azure-only boundary; putting provider config in Click context was rejected because plugins inherit that context; per-case run analysis was rejected because it duplicates shared prompt overhead and cannot represent run-level totals efficiently; and changing PluginBase was rejected because the capability contract already exists.

## Risks / Trade-offs

- **[SDK/provider failure]** A provider or session failure can affect later agent calls → open a run-scoped breaker, mark degraded with only a stable error type, and continue deterministic execution.
- **[Malformed advisory]** A model can return invalid JSON → reject only that invocation without opening the provider breaker or changing verdicts.
- **[Payload growth]** Case evidence can exceed SDK limits → redact, bound, pack on capsule boundaries, compact reducer input, and fail analysis locally without changing verdicts.
- **[Metric bias]** Tier-2 applies after deterministic failures → label all ratios observational and set causal uplift unavailable.
- **[Secret exposure]** Provider mappings can leak through traces or plugin context → keep them private, use public status projections, and add context/artifact redaction tests.
- **[Intermediate commits]** Legacy empty-session or tier-2 paths could bypass Azure gates → land minimum no-agent/Azure-provider/capability gates in the first implementation task before later one-shot replacement.

## Migration Plan

1. Add RED tests and implement the Azure resolver/CLI/provider dependency with the minimum legacy-path gates.
2. Add the usage ledger and generic one-shot controller, then replace empty sessions with per-case planning.
3. Add capability-gated recovery, observational metrics, bounded run analysis, and core artifacts in separate commits.
4. Synchronize docs/convention files and run the full pytest, policy, diff, and packaging/offline gates.
5. Rollback is a branch-level revert of the task commits; no plugin data migration or case-file rewrite is required.

## Open Questions

- None for the approved scope. Provider pricing units remain intentionally opaque and are reported as `provider_cost_units`, not USD.

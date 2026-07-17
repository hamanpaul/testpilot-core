## 1. Azure runtime and packaging

- [ ] 1.1 Add RED tests for automatic Azure readiness, secret-safe public status, CLI removal of interactive auth, private runtime injection, and plugin-visible context redaction.
- [ ] 1.2 Add pinned `github-copilot-sdk>=0.1.23,<0.2` dependency, lock metadata, wheel assertion, installed SDK surface probe, and offline bundle smoke.
- [ ] 1.3 Implement Azure-only resolver/CLI wiring and minimum legacy-path gates: no-key creates no session/requester, ready paths force Azure deployment/provider, and tier-2 requires concrete plugin overrides.
- [ ] 1.4 Run focused RED/GREEN and commit `feat(agent): 收斂 Azure-only 自動啟用與 SDK runtime`.

## 2. Authoritative usage ledger

- [ ] 2.1 Write RED SDK-shaped event tests for lifecycle, validation, cache/cost fields, reconciliation-only usage info, immutable journal rows, and call/token separation.
- [ ] 2.2 Implement run-scoped append-only `UsageLedger` with `assistant.usage` authority, API-call dedupe and event-id fallback.
- [ ] 2.3 Verify invalid/duplicate events do not inflate totals and commit `feat(reporting): 新增 core SDK usage ledger`.

## 3. Generic one-shot controller and breaker

- [ ] 3.1 Write RED tests for event subscription ordering, tool denial, disabled/no-agent skips, post-start setup terminal records, provider failure breaker, and malformed-response non-breaker behavior.
- [ ] 3.2 Implement purpose-neutral one-shot invocation through Azure deployment/provider, typed failures, run reset, degraded state, and first-provider-failure circuit breaker.
- [ ] 3.3 Run focused GREEN and commit `feat(agent): 統一 one-shot 計量與 run circuit breaker`.

## 4. Actual per-case planning

- [ ] 4.1 Write RED prompt/parser tests for bounded redaction, fixed advisory schema, and rejection of authoritative/secret-like output.
- [ ] 4.2 Implement `case_planning` prompt/parser and fail-soft local validation.
- [ ] 4.3 Replace the empty-session run-loop path with one planning call before deterministic execution, preserve selected runner identity, and record planning status in case trace.
- [ ] 4.4 Run focused GREEN and commit `feat(agent): 新增每案唯讀 Azure planning`.

## 5. Capability-gated tier-2 recovery

- [ ] 5.1 Write RED tests proving effective policy plus both PluginBase overrides are required and tier-1 action names never become tools/capabilities.
- [ ] 5.2 Implement typed tier-2 support, Azure-only `agent_recovery` invocation binding, fail-soft pre-executor skips, and fail-closed executor/verify-gate behavior.
- [ ] 5.3 Verify recovery uses Azure deployment while plugin runner identity remains unchanged, then commit `feat(remediation): 以 Azure 與 plugin capability gate tier-2`.

## 6. Observational assistance metrics

- [ ] 6.1 Write RED fixtures for initial/final rates, deterministic and recovery outcomes, empty denominators, post-gate failures, and no-op tier-1 miss attribution.
- [ ] 6.2 Implement pure arithmetic summaries with separate plugin/core verification accounting, observational evidence labels, and no causal claims.
- [ ] 6.3 Run focused GREEN and commit `feat(reporting): 新增 observational assistance metrics`.

## 7. Bounded run-end analysis

- [ ] 7.1 Write RED capsule redaction/packing/parser tests, including assessment bounds, 48k batch packing, 40k reducer projection, and 64k prompt ceiling.
- [ ] 7.2 Implement bounded capsules, fixed batch response schema, compact reducer, and fail-soft `_analyze_run()` after all final verdicts.
- [ ] 7.3 Verify one batch uses one shared call, multiple batches use one reducer, failures preserve verdicts, and commit `feat(reporting): 新增 run-end bounded Azure analysis`.

## 8. Core cost artifacts and path integration

- [ ] 8.1 Write RED pure reporter tests for per-case direct totals, deterministic zero tokens, recovery support, shared analysis, cache/cost units, and total usage status.
- [ ] 8.2 Implement JSON/Markdown/events artifacts, additive post-reporter pointer, partial analysis handling, and custom/skeleton unsupported paths.
- [ ] 8.3 Verify plugin RunResult/reporter contracts remain unchanged and commit `feat(reporting): 產生 core-only agent cost report`.

## 9. Documentation, review, and full verification

- [ ] 9.1 Synchronize README, docs/spec, docs/plan, CHANGELOG, and all four convention files with Azure-only/core-only behavior; do not modify plugin docs/source.
- [ ] 9.2 Run focused documentation/governance checks, request code review, and resolve all Critical/Important findings with re-review.
- [ ] 9.3 Run `uv run pytest -q`, offline/package smoke where available, `python3 -m policy_check --repo .`, and `git diff --check`; fix failures before completion.
- [ ] 9.4 Archive this OpenSpec change, run final adversarial review, commit with Conventional Commits, and leave push/PR untouched unless explicitly requested.

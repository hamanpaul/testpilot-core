# Core SDK API 1.5: teardown cleanup results

## Purpose and base

Core SDK API 1.5 work is tracked in [issue #61](https://github.com/hamanpaul/testpilot-core/issues/61).

Add a Core-owned result contract for plugin cleanup so that a failed or unverified restore cannot be hidden by `ExecutionEngine.execute_case_once()`'s `finally` block or followed by a retry. Work starts from merged `main` commit `ea442ec94166fc68b5fb0a2180f2d9982fd9d403` in `feature/cleanup-result-api15-20261004`. The current D036 plugin and installed API 1.4 pair remain unchanged.

Source review is pinned to Core `7d5fcef884d2ba8a08ef31b05ea78c5383034919` and the D036 plan at plugin commit `847cb17120176b739c77f6095431df21088f1bad`. At the pinned Core, `execute_case_once()` ignores teardown returns and logs teardown exceptions; `execute_with_retry()` already stops on the attempt's `abort_run`; the run loop stops later cases on `RetryResult.abort_run`. `PluginBase.run_pipeline()` has early setup/verify returns whose values cannot be changed by its `finally` cleanup.

## API contract

- `teardown()` may return `None` for successful or legacy cleanup.
- A cleanup failure returns a mapping with `status` exactly `failed` or `unknown`, a stable bounded `reason_code`, bounded safe `comment`, and optional structured `transport_result`.
- Core validates the mapping, stamps the current case ID and attempt index, and builds its own `failure_snapshot` with category `environment`. The plugin cannot supply the final verdict, category, abort bit, identity, or snapshot. Both failure statuses set verdict false and terminal `abort_run=true`; unknown transport evidence takes precedence over a claimed known failure.
- A malformed non-`None` result or ordinary teardown exception fails closed as unknown cleanup failure. Existing transport-unknown behavior remains: if an earlier step outcome is unknown, Core skips teardown I/O. Cancellation exceptions continue to propagate and are never retried as ordinary case failures.
- Cleanup failure overrides an already computed pass. Successful cleanup leaves the prior case verdict and normal retry policy unchanged. A failure/unknown cleanup cannot be retried and stops later cases.
- `PluginBase.run_pipeline()` must apply the same result contract, including setup and verification failures; its early returns must converge through post-finally result assembly.

Any plugin that relies on Core consuming a cleanup-result mapping declares `api_version = "1.5"`. Core advances `API_VERSION` to `1.5`; an API 1.4 Core must reject such a plugin before execution. Existing plugins returning `None` remain compatible. This SDK feature does not require a new hook or exported result class.

## Implementation sequence

1. Add this plan as a docs-only commit before source changes.
2. Add focused tests first for the execution-engine and direct pipeline result contract. Run them red against the unchanged implementation.
3. Implement the smallest shared cleanup-result normalizer and wire it into `ExecutionEngine.execute_case_once()` and `PluginBase.run_pipeline()`.
4. Update `API_VERSION`, versioned-plugin compatibility tests, and the plugin development guide. Add a changelog fragment; keep package `VERSION` at its current unreleased baseline.
5. Run focused lifecycle tests, full Core `uv run pytest -q`, policy checks, lint, and diff checks. Preserve source and test pins in the task report; do not merge, push, or claim live D036 acceptance.

## Required tests

- `None` cleanup preserves successful and failed legacy cases.
- Pass plus known cleanup failure becomes `FailEnv`, aborts after one attempt, and leaves later cases unexecuted.
- A known step failure followed by cleanup failure also aborts before retry; successful cleanup preserves ordinary retry behavior.
- A pre-step halt after mutation reaches restore; a halt before mutation performs no restore.
- An earlier unknown step receipt suppresses teardown; an unknown cleanup receipt prevents subsequent cleanup commands, retries, and later cases.
- Invalid status, malformed mapping, and ordinary teardown exception fail closed; Core-authored case/attempt identity prevents stale snapshot reuse.
- Direct `run_pipeline()` handles pass, setup failure, verify failure, step failure, and exceptions without early returns hiding cleanup failure.
- Cancellation propagates without retry; a fake D036 finalizer performs no I/O when a state-changing command is in flight or its outcome is uncertain.
- The loader rejects API 1.5 plugins on API 1.4 and accepts them on API 1.5; API 1.4 plugins remain loadable on API 1.5.

## Boundaries

Do not change the serialwrap protocol, command replay/recovery, official D036 YAML, the existing API 1.4 plugin pair, or any live DUT path. The Core result is not proof that hardware was restored. The plugin must mark a possible mutation before command dispatch, stop its own cleanup sequence at uncertainty, and preserve bounded transport evidence. The read-then-submit race remains outside this change.

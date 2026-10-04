# Issue153 P1 Core Task1: SDK run-start gate

> Date: 2026-10-04
> Status: Core lifecycle contract prototype; independent review required
> Scope: `testpilot-core` only, based on `ee4743305d8b0a6c82ded2e8acbb2cf977428dc0`

## Goal

Add an additive SDK lifecycle contract that lets a plugin require host-verified
capture binding before firmware-version probes and case execution. The host must
reject an unsupported strict-capture requirement before plugin preparation. A
strict run with missing or uncertain evidence must end with a terminal run-start
artifact that lists selected cases as unexecuted and creates no case verdict rows.

This task defines the public API and host lifecycle. A production strict capture
provider and dual-channel transport binding belong to a separate Core task.

## Public contract

- Increment `testpilot.api.API_VERSION` from `1.5` to `1.6`.
- Export frozen, bounded types: `PrepareRunAfterCaptureContext`,
  `PrepareRunGateEvidence`, `PrepareRunGateOutcome`, `PrepareRunGateResult`, and
  `RunCapability`.
- Add `PluginBase.required_run_capabilities`, defaulting to an empty frozen set,
  and an optional `prepare_run_after_capture(prepared, context)` hook whose
  default returns `None`.
- Add `PreparedRun.run_start_gate`, defaulting to `None`, to retain the accepted
  typed result with the prepared selection.
- Strict capability declarations use typed enum members. The public
  `Orchestrator.run()` entry point performs shared admission after API-checked
  plugin loading and before `bind_project_root()` or runner construction.
  Unknown, malformed, unsupported, or API-incompatible declarations fail
  closed before either callback.
- The active `RunBackend` must supply the context from the actual run capture
  handle. Configuration values cannot prove capture binding.

An admitted strict plugin runs through the Core-owned context-bearing loop.
Until Core defines an equivalent context-bearing runner contract, strict
plugins with a custom `create_runner()` are rejected before the factory runs.
The inherited `PluginBase.run_pipeline()` has no capture-context parameter and
raises before setup, steps, cleanup, or verdict evaluation when called directly
by a strict plugin. Legacy plugins with no required capability keep their
existing custom-runner and direct-pipeline behavior.

The context contains the run ID, an actual non-negative start sequence (zero is
valid), and an opaque safe-token binding ID. Gate results contain finite
`accepted`, `failed`, or `unknown` outcomes, sanitized reason codes, and at most
16 sanitized evidence items. An accepted result is invalid if any supplied
evidence item is not accepted.

## Strict lifecycle

```text
host capability preflight
  -> Core-owned loop
  -> bind project root
  -> pure prepare selection
  -> strict capture setup and handle binding
  -> validate run-start marker
  -> build context from active capture handle
  -> prepare_run_after_capture
  -> firmware-version capture
  -> case runner and execution
  -> validate end marker and case ranges before bounded export
```

The strict capability check occurs before plugin preparation. During a run,
capture setup and run-start marker errors are sanitized into terminal aborts.
`None`, booleans, negative values, and malformed markers are invalid. Gate
exceptions, missing or malformed results, and failed/unknown results also produce
terminal aborts. These artifacts record the reason, finite outcome, capture
status, selected case IDs, and unexecuted case IDs; they report zero executed
cases and never synthesize Pass/Fail rows.

After strict startup uncertainty, Core does not continue to firmware-version
capture, case runners, run-capture export, or capture teardown. This
Task1 implementation has no strict production provider or bounded WAL harvest;
unsupported backends abort before preparation. A separate capture task must
provide the actual provider and bounded read-only harvest behavior before a
strict production plugin can run.

After accepted gate evidence, strict end-marker and per-case sequence ranges are
validated before export. Invalid or reversed ranges mark `core_run_capture` as
incomplete and suppress export; they never fall back to sequence zero or broaden
the requested range. Legacy plugins with no required capability retain their
prior lifecycle and best-effort behavior.

## Compatibility

- API 1.4 and 1.5 plugins remain loadable on an API 1.6 host and take the legacy
  path unless they opt in to a strict capability.
- API 1.5 hosts reject API 1.6 plugins during loading before plugin instantiation
  or `prepare_run()`.
- No package version, `VERSION`, dependency, plugin repository, configuration,
  official case YAML, transport, logger, or production backend changes are part
  of this task.

## Offline verification

Fake run-loop tests exercise the actual Core run entry point and ledger events.
They cover pre-prepare capability rejection, missing backend provider, setup and
marker exceptions, malformed contexts and results, accepted/failed/unknown gate
outcomes, legacy opt-out, old-host rejection, zero start markers, and invalid end
markers/case ranges. Tests use only fake plugin, backend, runner, and reporter
objects; they do not invoke subprocesses, networks, SSH, serialwrap, hardware,
or real capture.

Public-entry tests call the actual `Orchestrator.run()` and inherited
`PluginBase.run_pipeline()` methods. They cover missing-provider and malformed
capability rejection before bind/factory, strict custom-runner rejection with a
fake supported provider, the accepted Core-owned path, and legacy custom/direct
controls.

This specification and its tests establish only the SDK/Core lifecycle
prototype. They do not establish production capture binding, plugin-side hybrid
routing or identity verification, live hardware behavior, EIT results, or issue
closure.

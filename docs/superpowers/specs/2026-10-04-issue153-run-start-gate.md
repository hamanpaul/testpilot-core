# Issue153 P1 Core Task1: SDK run-start gate

> Date: 2026-10-04
> Status: SDK lifecycle and opt-in API 1.1 Core consumer; live deployment remains unqualified
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
  plugin loading and before testbed configuration binding,
  `bind_project_root()`, or runner construction. Unknown, malformed, unsupported,
  or API-incompatible declarations fail closed before those steps.
- After admission, Core calls the optional `PluginBase.bind_testbed_config()` hook
  when available, with the exact already-loaded `Orchestrator.config` object before custom
  runner construction or plugin preparation. Its default is a no-op. A hook
  exception stops startup with the finite sanitized
  `testbed_config_binding_failed` reason. This delivers configuration only; it
  is not capture or physical-identity evidence.
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
  -> explicit API 1.1 provider capability preflight
  -> bind selected testbed config and project root
  -> pure prepare selection and freeze requested role plan
  -> begin the capture binding on the explicit provider
  -> build context from the same active handle
  -> prepare_run_after_capture and recheck role-plan identity
  -> firmware-version capture
  -> per-case checkpoint, execution, and checkpoint
  -> one end mark, fixed-range validation, finish, complete-only export
```

Public `Orchestrator.run()` performs static SDK admission before plugin
configuration binding, custom runner construction, or preparation. The
Core-owned loop makes a single read-only provider capability request before
plugin binding or preparation. It requires API 1.1 and the checkpoint feature;
unsupported or malformed providers produce a sanitized terminal abort before
preparation. The loop re-projects the same requested plan around plugin
callbacks and refuses any drift. Begin/context/gate failure stops before
firmware-version capture and case work. Abort artifacts identify selected and
unexecuted cases without inventing Pass/Fail rows.

After an accepted gate, every case is bracketed by read-only append-position
checkpoints. A checkpoint uncertainty stops the run before a not-yet-started
case or any later case. Core freezes one end mark, reads only the anchored
start-to-end interval, verifies full global sequence coverage and every row,
then finishes that same provider handle. It publishes logs and case line ranges
only when the complete fixed interval and finish receipt validate; partial or
unknown results carry bounded status metadata without case log attribution.
Unknown one-shot completion permits status lookup for that exact operation ID
only. Legacy plugins with no strict capability retain the prior setup, marker,
export, teardown, and custom-runner behavior.

## Neutral role-plan projection

The API 1.6 candidate also exposes frozen `CaptureRolePlanRequest`,
`RolePlanOptionRequest`, `RolePlanIdentity`, `RolePlanProviderOption`, and
`EffectiveRolePlan` types. `PluginBase.capture_role_plan_request` defaults to
`None` and is independent of `required_run_capabilities`; a generic strict
capture capability does not imply any DUT, STA, or other role. `PreparedRun`
has an optional `effective_role_plan` field at the end of its constructor so
existing positional calls continue to work.

The Core-internal `project_capture_role_plan()` helper consumes the exact
already-loaded `TestbedConfig` object and projects only explicitly requested
fields; it is deliberately not re-exported from `testpilot.api`. A
requested role requires a configured selector, expected device-by-id, and one
unambiguous profile value; an optional configured serial port is copied only
when present. Provider options are separate namespaced fields and are
projected only when the host supplies a matching allowlist. The projection
does not reload a file, read the current working directory, infer defaults,
or query a broker. Nested option values are copied into immutable values, and
credential-like mapping keys are rejected at any nesting depth.
Physical-identity and provider-option digests are computed separately, and the
overall digest binds both. Type representations do not display configured
identity or option values.

This additive type surface does not wire the request into the run lifecycle,
create a provider contract, or establish physical capture binding or broker
ownership. `EffectiveRolePlan` construction verifies canonical ordering,
uniqueness, role relationships, and that every digest matches its contents;
those checks establish internal consistency only, not host provenance.
`PrepareRunAfterCaptureContext` remains exactly its existing three fields.
Runtime freezing, drift checks, and backend proof require a later
jointly reviewed task; until then these types are configuration projection
only and do not make strict capture usable.

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

This specification's synthetic provider tests establish the Core contract and
consumer behavior. They do not establish the deployed EIT broker version,
plugin-side hybrid routing or identity verification, live hardware behavior,
EIT results, or issue closure.

## API 1.1 strict capture consumer

The Core now has a production consumer for the additive serialwrap capture
binding API 1.1. It is opt-in through the existing SDK declaration: a plugin
class must require `RunCapability.STRICT_CAPTURE_BINDING` and declare a static
`CaptureRolePlanRequest`. A generic strict capability does not imply DUT, STA,
or any other role. Core projects only the requested roles from the already
loaded `TestbedConfig`, checks the same frozen plan before and after plugin
callbacks, and passes that same plan and configuration object to the backend.
The three-field `PrepareRunAfterCaptureContext` remains unchanged.

At the public `Orchestrator.run()` entry point, static capability admission
still occurs before configuration binding, runner construction, or preparation.
For an admitted strict plugin, the backend then resolves one explicit
serialwrap endpoint and makes one read-only API 1.1 capability request before
plugin binding or preparation. Unsupported, absent, malformed, or API 1.0-only
providers stop the run before plugin preparation. There is no fallback to
API 1.0 capture routes. The provider query does not start or attach a daemon,
reset the WAL, probe target readiness, or issue target commands. Begin, each
per-case position checkpoint, the single end mark, fixed-range pages, and finish
all stay bound to that accepted plan and handle. Raw WAL rows and opaque
provider tokens remain private to the backend.

Case log intervals and DUT/STA log files are published only after every page,
sequence, row envelope, payload length, CRC, epoch, binding token, terminal
coverage assertion, and finish receipt validates. Incomplete or unknown
harvests produce bounded status metadata and no case log-line attribution. A
single metadata-only finish is allowed only after a well-formed, correctly
anchored terminal range page explicitly reports an incomplete capture with
`ok: true`, `complete: false`, `capture_status: incomplete`, no more page, and
no next cursor. A malformed, nonterminal, wrong-anchor, capped, or timed-out
range stops provider I/O without finish or status lookup; the range method is
read-only and has no operation ID to reconcile. When a begin, checkpoint, mark,
or finish result may have been applied but its completion is unknown, Core
queries status only for that operation ID. It does not repeat the mutation or
send later provider or target commands. Core always releases its local
lease/maps in a `finally` path. These guarantees cover the broker's
append-order evidence, not continuous physical identity or exclusive ownership
of the UART.

The API 1.1 consumer does not change normal-run defaults or the installed EIT
broker. A plugin that does not opt into the strict capability continues on the
legacy run path. The currently installed EIT broker is API 1.0-only, so a
plugin that opts into strict capture against that broker will abort before
plugin preparation with `capture_provider_unsupported`; it will not silently
use the API 1.0 exporter. Passing synthetic provider tests is not live EIT or
hardware qualification.

## Effective configuration delivery (#152 Core dependency)

The separate effective-testbed binding task adds the optional
`PluginBase.bind_testbed_config(topology)` lifecycle hook. The public Core entry
passes its already-selected `Orchestrator.config` object after capability
admission and before custom runner construction or plugin preparation. Direct
Core-loop entry applies the same order. A Core-owned run-local identity reference
prevents calling the hook twice for the same plugin instance when public dispatch
falls back into the Core loop; if the loader returns a different plugin instance,
Core binds that instance separately. Unsupported strict capabilities are still
rejected before this hook. Binding failure produces a sanitized terminal
run-start abort before capture or preparation.

This is configuration delivery only. It does not reload or reconstruct the
configuration, prove a DUT/STA identity, provide capture evidence, or make strict
capture usable. The hook does not alter the three-field capture context, API
version metadata, role-plan request default, or transport semantics.

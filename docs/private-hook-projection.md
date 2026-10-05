# Private hook payload projection

SDK API 1.7 lets a plugin choose what Core lifecycle hooks and Engine result
surfaces may observe. The evaluator continues to use the original in-process
case and step results, including private captures.

## Projector contract

Override the optional method on `PluginBase`:

```python
def project_hook_payload(self, hook_name: str, payload: dict) -> dict:
    ...
```

The input and return value have the same two-part shape:

```python
{
    "data": {"step": {"command": "..."}, "result": {"output": "..."}},
    "context": {
        "hook_name": "post_step",
        "case_id": "D001",
        "plugin_name": "example",
        "attempt_index": 1,
        "step_id": "probe",
        "runner": {},
        "extra": {},
    },
}
```

`data` is the lifecycle-specific hook payload. `context` contains plain fields
corresponding to `HookContext`. Return a mapping with exactly `data` and
`context`; both values must be dictionaries, and the context fields must retain
their expected types and the current `hook_name`.

Core deep-copies the envelope before projection, validates and copies the
projected value, then constructs the `HookContext` passed to the callback from
the projected context. The callback never receives the original runner or
`extra` through a second argument. After dispatch, Core projects the mutated
copy again before reading supported controls. Observer changes to `case`,
`step`, `result`, command/output fields, captures, or prior attempts are not
merged into evaluator state or retained attempt evidence.

For each hook return projection, Core adds the reserved top-level data field
`__testpilot_hook_result__` to carry `HookResult` controls back from the hook
dispatcher. It contains exactly `proceed` (a bool) and `advice` (a string);
Core validates their types, then removes the carrier before merging supported
controls. The field is visible only to the projector during this return
projection, not to the lifecycle callback or public result surfaces. A
projector using a strict allowlist must preserve this field and its exact
two-key shape on every return projection. It may redact `advice` while keeping
it a string. If the field is missing or malformed, Core fails closed with
`hook_payload_projection_failed`. Do not publish the reserved field or
unredacted private values from it.

The default implementation returns the envelope unchanged for compatibility.
Plugins that need to keep private values out of hook and Engine result surfaces
should declare `api_version = "1.7"` and override the method to remove or
replace sensitive values in both `data` and `context`. The projector should be
deterministic and should not perform I/O.

Core merges only its supported controls from the projected return: the
case-local `max_attempts` adjustment, `HookResult.proceed` / `advice`, and the
existing remediation history, tier-2 audit, recovery marker, failure snapshot,
remediation decision, transport evidence, and abort controls. Observer edits
to step results, commands, outputs, the case, or earlier attempts cannot change
the verdict or overwrite the retained evidence.

## Failure and unknown-outcome behavior

The runtime remediation coordinator consumes the projected `failure_snapshot`
from `on_failure`. It must match the current case ID and integer attempt index;
its category and reason remain available even if the projector removes
`case._last_failure`. Only an absent `failure_snapshot` field uses the legacy
case fallback. A present but invalid or mismatched snapshot uses Core's normal
phase defaults without reading private case evidence.

If deep-copying fails, the projector raises, or the returned envelope is
malformed, Core stops the case with the finite reason
`hook_payload_projection_failed`. It does not retry with the raw payload or
format the projector exception. If safe transport evidence already says the
command outcome is unknown, that classification and its validated receipt
fields take precedence.

Core classifies unknown transport evidence before dispatching the next
action-capable lifecycle hook. An unknown step result skips `post_step` and
`on_failure`; unknown evidence from setup, verification, an exception, or the
current failure snapshot also skips `on_failure`. Unknown teardown results and
unknown controls returned by `on_retry` suppress `post_case` and stop another
attempt. Core does not replay a later step or retry the case, and it skips
teardown when uncertainty exists before cleanup begins. A completed nonzero
command result remains a known failure and follows the configured hook and
retry path.

## Boundary

Projection covers Core lifecycle hook copies and Engine attempt, failure
snapshot, and trace values derived from those results. It does not redact raw
UART/WAL capture files and does not guarantee that a plugin-generated report
sanitizes the plugin's private evidence. Plugins remain responsible for their
own report and transport-retention boundaries.

Hook halt and handler-failure outcome logs use fixed status messages and do not
include `HookResult.advice` or handler exception text; those values remain
available to the Engine's normal projected control path. Registering an
unknown hook name also emits a warning containing the supplied name and the
valid hook names.

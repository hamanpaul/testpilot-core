## Why

`wifi_llapi` official case inventory has drifted away from the current checked-in template workbook. The repo can now claim that some rows are aligned even when the canonical discoverable YAML is missing, and runtime reruns can still be blocked on ambiguous `(source.object, source.api)` families even when the case already carries the correct `source.row`.

This needs to be fixed now because the current state makes reruns unreliable, hides missing official rows behind historical leftovers, and lets documentation drift away from the actual repo inventory.

## What Changes

- Introduce a workbook-authoritative official inventory rule for `wifi_llapi`: every official workbook row must map to exactly one discoverable YAML.
- Add inventory audit and reconcile behavior to detect missing, drifted, duplicate, and extra discoverable official cases.
- Restore missing official case YAML rows from repo history or explicit repair flows, and demote non-canonical historical leftovers out of discoverable inventory.
- **BREAKING**: change runtime ambiguous-family handling so `(source.object, source.api)` collisions first use `source.row` to select the canonical row; only unresolved collisions remain blocked as `ambiguous_object_api_family`.
- Sync runtime artifacts and repo handoff docs so they describe the repaired canonical inventory instead of stale historical state.

## Capabilities

### New Capabilities
- `wifi-llapi-official-inventory`: Define workbook-authoritative official inventory, including one discoverable YAML per official workbook row plus explicit handling for missing, drifted, duplicate, and extra cases.

### Modified Capabilities
- `wifi-llapi-alignment-guardrails`: Change ambiguous-family alignment behavior so runtime uses `source.row` to disambiguate before emitting `ambiguous_object_api_family`.

## Impact

- Affected code: `src/testpilot/reporting/wifi_llapi_align.py`, new inventory audit/reconcile helpers, reconcile script, `plugins/wifi_llapi/cases/*.yaml`, orchestrator integration tests, and repo handoff docs.
- Affected runtime behavior: row-correct ambiguous-family cases become runnable instead of being blocked immediately.
- Affected artifacts: alignment summaries, blocked-case reports, and repo documentation must match the repaired canonical official inventory.

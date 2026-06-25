## 1. Runtime alignment repair

- [x] 1.1 Add regression tests proving `align_case()` uses `source.row` to resolve ambiguous `(source.object, source.api)` families when the row is one of the template candidates
- [x] 1.2 Keep `ambiguous_object_api_family` blocking behavior for families that still cannot be resolved by `source.row`
- [x] 1.3 Update `src/testpilot/reporting/wifi_llapi_align.py` to select the canonical row from `candidate_rows` when `source.row` is present and valid
- [x] 1.4 Re-run targeted alignment tests and confirm the new row-disambiguation behavior stays green

## 2. Official inventory audit

- [x] 2.1 Create workbook-driven inventory audit helpers that classify discoverable `wifi_llapi` YAML as canonical, missing, drifted, duplicate, or extra
- [x] 2.2 Add unit tests covering missing rows, stale row-bearing metadata, and duplicate/extra discoverable cases
- [x] 2.3 Expose a machine-checkable audit result that can be used by repo-scale tests and reconcile tooling

## 3. Inventory reconcile flow

- [x] 3.1 Create a reconcile script that prints restore/rewrite/demote actions in dry-run mode
- [x] 3.2 Restore missing canonical rows from repo history when a historical `D###_*.yaml` exists
- [x] 3.3 Rewrite drifted cases to canonical row-bearing metadata and demote non-canonical leftovers out of discoverable inventory
- [x] 3.4 Add repo-scale inventory tests asserting one discoverable YAML per official workbook row with no silent omissions

## 4. Integration verification and docs sync

- [x] 4.1 Add orchestrator/runtime regression coverage proving row-correct ambiguous-family cases are runnable instead of blocked
- [ ] 4.2 Apply the reconcile flow to `plugins/wifi_llapi/cases/` and review the resulting canonical inventory diff
  Blocked on the current real-repo reconcile dry-run: `376 actions / 344 blockers`
  (`missing_history_candidate`: 280, `ambiguous_history_candidate`: 57, `unresolved_object_api_family`: 7).
  The accepted Task 3 planner must stop on those blockers instead of guessing restore/apply behavior.
- [ ] 4.3 Re-run the problematic case set to confirm rows are executed or explicitly blocked, never silently skipped
  Current target-row accounting on the real repo is explicit, not silent:
  `D034/D095/D096/D100` are canonical discoverable rows;
  `D308/D313/D316/D327/D329/D337/D406/D495` are discoverable drifted rows scheduled for
  `rewrite:canonical_row_bearing_metadata`;
  `D407` remains missing behind `ambiguous_history_candidate`.
  Repo-scale invariants currently hold (`missing_uncovered = 0`, `unresolved_uncovered = 0`),
  but a full rerun of the repaired target set remains blocked until 4.2 can safely apply the
  canonical inventory changes.
- [ ] 4.4 Sync `README.md`, `docs/plan.md`, and `docs/todos.md` to the repaired canonical inventory
  Blocked until 4.2 produces a safe canonical inventory diff to document.
- [ ] 4.5 Run full repo regression and archive any remaining blockers explicitly before claiming completion
  Partial verification is done (`mixed_alignment` runtime regression plus targeted wifi_llapi suites).
  Full repo regression currently stops at the unrelated baseline failure
  `tests/test_topology.py::test_variable_resolve`
  (`SSID_5G` expected `testpilot5G`, got `TestPilot_5G`), so Task 4 cannot be closed yet.

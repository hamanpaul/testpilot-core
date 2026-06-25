# wifi_llapi missing-row alignment (2026-04-24, one-shot)

A single-use script that runs 17 hard-coded actions against
`plugins/wifi_llapi/cases/` so its inventory matches the official
`wifi_llapi_template.xlsx` Support set (415 rows).

## Why this exists

`scripts/wifi_llapi_reconcile_inventory.py` (Stream 1) handles ongoing
alignment, but currently has 344 blockers. This batch performs the subset
that is unambiguous and safe (Stream 2): missing-row fills + stale deletes.

See `docs/superpowers/specs/2026-04-24-wifi-llapi-align-missing-rows-design.md`.

## Usage

Dry-run (default — prints plan, writes reports, makes no changes):

    uv run python tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py

Apply (mutates working tree via `git mv`/`git rm`/`git add`):

    uv run python tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py --apply

Working tree must be clean before `--apply`.

Post-state verification is plan-derived, not an unconditional `415/415` canonical
assertion. This one-shot batch is only responsible for eliminating the known
missing Support rows from the current snapshot; unrelated pre-existing
filename/source-row drift is reported via `canonical_coverage` but does not fail
apply if the generated post-state matches the plan expectation and
`liberal_missing_rows` is empty.

## After this runs

Do not delete this directory. The script + reports stay for audit. Future
inventory work should go through `scripts/wifi_llapi_reconcile_inventory.py`.

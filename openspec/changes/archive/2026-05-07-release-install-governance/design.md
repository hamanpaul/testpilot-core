## Context

TestPilot currently operates like a developer checkout: installation guidance points to editable installs, the normal wifi_llapi run is usually shown through `python -m testpilot.cli` or `testpilot run wifi_llapi`, and release policy is split across README, AGENTS, changelog, workflows, and local convention. QC/TEST users need an installed `testpilot` command that hides repository and virtualenv details, while maintainers still need the managed git checkout so YAML edits and release-policy changes remain reviewable.

The approved design source is `docs/superpowers/specs/2026-05-06-release-install-governance-design.md`. This OpenSpec change translates that design into implementable contracts for managed installation, release governance, and the wifi_llapi operational CLI.

## Goals / Non-Goals

**Goals:**

- Provide a managed installation layout under `~/.local/share/testpilot` with a wrapper at `~/.local/bin/testpilot`.
- Support installer defaults for `paulc-arc/testpilot`, local/fork overrides, latest stable release resolution, skill sync, and serialwrap install/update.
- Add top-level `testpilot --update [REF]`, `testpilot --verify-install`, and source-ref-aware `testpilot --version`.
- Promote `testpilot wifi_llapi` as the documented primary normal-run path while preserving `testpilot run wifi_llapi`.
- Make `VERSION` canonical and enforce version, release, help-sync, PR, and policy alignment through docs and workflow gates.

**Non-Goals:**

- Do not remove `testpilot run wifi_llapi` compatibility.
- Do not alias helper commands currently grouped under `testpilot wifi-llapi ...`.
- Do not publish wheels, sdists, or binary release assets as part of this migration.
- Do not change serialwrap internals that still install into legacy locations; track that in serialwrap separately.

## Decisions

1. **Managed checkout over wheel-only package data.** A checkout preserves maintainers' ability to inspect diffs, recover QC YAML edits, and submit PRs. A wheel-only install would make plugin assets easier to package but would hide the repository state that this project intentionally keeps reviewable.
2. **Pre-dispatch top-level options.** `--update [REF]` and `--verify-install` are handled before Click command routing so the desired UX can remain a top-level option with an optional ref. Modeling update as a subcommand was rejected because the approved user surface is `testpilot --update [REF]`.
3. **Common wifi_llapi run helper.** `testpilot wifi_llapi` and `testpilot run wifi_llapi` share the same internal execution helper to avoid drift in reports, alignment behavior, and accepted flags. Removing the old command was rejected because existing scripts still depend on it.
4. **`VERSION` is canonical.** Release checks read `VERSION` first and treat `pyproject.toml` plus `src/testpilot/__init__.py` as mirrors. Keeping `pyproject.toml` canonical was rejected because release workflow and shell scripts need a single plain-text source.
5. **Project-neutral policy config.** Governance uses `.project-policy.yml`, not `.paul-project.yml`, and pins policy workflow references by full commit SHA. This keeps policy adoption portable while retaining deterministic supply-chain behavior.

## Risks / Trade-offs

- **Installer touches user home directories** -> tests must exercise override paths in temporary directories and avoid modifying real user state.
- **Top-level option parsing can conflict with Click** -> keep pre-dispatch handling narrow and cover `--update`, `--verify-install`, and `--version` with CLI tests.
- **Managed checkout updates can overwrite local edits** -> update must detect dirty checkouts and fail with a clear message unless an explicit future force option is introduced.
- **Policy full blocking may fail until external repos are ready** -> TestPilot pins only after policy substrate is de-personalized and the selected full SHA is known.
- **Docs/help sync can drift** -> README marker blocks and `.project-policy.yml` declare the commands that must be regenerated and checked.

## Migration Plan

1. Add release/install specs and tests before implementation.
2. Add `VERSION`, align mirrors to `0.2.0`, and update source-ref version display.
3. Add installer, update, verify-install, wrapper, skill sync, and serialwrap integration.
4. Add `testpilot wifi_llapi` runtime command using the existing run helper.
5. Add policy config, workflow gates, PR template updates, README/help markers, release docs, skill docs, and changelog entry.
6. Validate with targeted installer/CLI/workflow tests and the full repository test suite.

Rollback is a normal git revert: the existing editable-install and `testpilot run wifi_llapi` paths remain available throughout the migration.

## Why

TestPilot needs a fixed release and installation surface for QC/TEST users, while preserving a managed git checkout for maintainers who need reviewable YAML and policy changes. The current developer-checkout workflow makes normal runs, updates, skill installation, version reporting, and release governance too easy to drift.

## What Changes

- Add a managed installer that places TestPilot under `~/.local/share/testpilot`, exposes `~/.local/bin/testpilot`, syncs repository skills, and installs or updates `serialwrap` from the `paulc-arc` fork.
- Add top-level `testpilot --update [REF]`, `testpilot --verify-install`, and source-ref-aware `testpilot --version` handling before normal Click dispatch.
- Promote `testpilot wifi_llapi` as the primary normal-run command while keeping `testpilot run wifi_llapi` compatible.
- Make `VERSION` the canonical project version and keep `pyproject.toml` plus `src/testpilot/__init__.py` as mirrors.
- Add blocking release/policy governance through `.project-policy.yml`, release workflow checks, PR template guidance, README help sync markers, and updated release documentation.
- Update repository skill documentation to prefer the installed `testpilot wifi_llapi` UX for QC/TEST operation.

## Capabilities

### New Capabilities

- `managed-installation`: Installer, update, verification, wrapper, skill sync, and serialwrap integration behavior for managed TestPilot deployments.
- `release-governance`: Version mirror alignment, release/tag validation, policy config, blocking workflow, and PR/release documentation requirements.
- `wifi-llapi-operational-cli`: User-facing `testpilot wifi_llapi` runtime command, compatibility behavior, and help/documentation synchronization.

### Modified Capabilities

- None.

## Impact

- Affected user commands: `testpilot --version`, `testpilot --update [REF]`, `testpilot --verify-install`, `testpilot wifi_llapi`, and `testpilot run wifi_llapi`.
- Affected files include `scripts/install.sh`, `src/testpilot/cli.py`, `VERSION`, `pyproject.toml`, `src/testpilot/__init__.py`, `.project-policy.yml`, GitHub workflow/template files, README/release docs, `AGENTS.md`, `CHANGELOG.md`, and `skills/testpilot-normal-test/SKILL.md`.
- Adds installer/update interactions with git, Python virtualenv setup, local wrapper generation, skill synchronization to `~/.agents/skills`, and serialwrap installation/update from `https://github.com/paulc-arc/serialwrap.git`.

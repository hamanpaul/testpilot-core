## ADDED Requirements

### Requirement: Managed installer creates checkout, venv, wrapper, skills, and serialwrap
The installer SHALL create or update a managed TestPilot checkout under `~/.local/share/testpilot/src`, create a runtime virtualenv under `~/.local/share/testpilot/.venv`, install TestPilot into that virtualenv, expose `~/.local/bin/testpilot`, sync `skills/testpilot-normal-test` into `~/.agents/skills/testpilot-normal-test`, and install or update serialwrap from `https://github.com/paulc-arc/serialwrap.git`.

The installer SHALL default `TESTPILOT_REPO_URL` to `https://github.com/paulc-arc/testpilot.git`, `TESTPILOT_REF` to `latest-release`, and `SERIALWRAP_REPO_URL` to `https://github.com/paulc-arc/serialwrap.git`. Environment variables SHALL allow local, fork, branch, tag, and commit overrides.

#### Scenario: Local override install
- **WHEN** the installer runs with `TESTPILOT_REPO_URL=file:///tmp/testpilot` and a temporary home/bin root
- **THEN** it creates the managed checkout from that local repository, installs the wrapper, syncs `testpilot-normal-test`, and does not require the user to activate a virtualenv

#### Scenario: Default latest release install
- **WHEN** the installer runs without `TESTPILOT_REPO_URL` or `TESTPILOT_REF`
- **THEN** it uses `https://github.com/paulc-arc/testpilot.git` and resolves `latest-release` to the latest stable `vX.Y.Z` tag before checkout

### Requirement: Top-level update refreshes the managed checkout
`testpilot --update [REF]` SHALL run before normal Click dispatch, update the managed checkout, reinstall TestPilot into the managed virtualenv, resync repository skills, and update or check serialwrap. When no ref is provided, it SHALL update to `main`. When a ref is provided, it SHALL fetch and checkout that branch, tag, or commit.

If the managed checkout has uncommitted changes, update SHALL fail with a clear message and SHALL NOT overwrite local edits.

#### Scenario: Default update selects main
- **WHEN** user runs `testpilot --update`
- **THEN** TestPilot fetches the managed checkout, checks out `main`, reinstalls the managed virtualenv, syncs skills, and updates or checks serialwrap

#### Scenario: Ref update selects requested ref
- **WHEN** user runs `testpilot --update v0.2.0`
- **THEN** TestPilot fetches the managed checkout, checks out `v0.2.0`, reinstalls the managed virtualenv, syncs skills, and updates or checks serialwrap

#### Scenario: Dirty checkout blocks update
- **WHEN** user runs `testpilot --update` and the managed checkout has uncommitted changes
- **THEN** the command exits non-zero and explains that local edits must be committed, stashed, or resolved before updating

### Requirement: Verify install reports deployment health
`testpilot --verify-install` SHALL run before normal Click dispatch and report whether the managed checkout exists, the wrapper points at the managed virtualenv, the console script works, serialwrap is available, `~/.agents/skills/testpilot-normal-test` exists, current git remote/ref/short SHA are readable, `VERSION`, `pyproject.toml`, and `src/testpilot/__init__.py` align, and plugin assets plus wifi_llapi cases are discoverable.

#### Scenario: Healthy install passes verification
- **WHEN** all managed install components are present and version mirrors align
- **THEN** `testpilot --verify-install` exits 0 and prints each checked item as passing

#### Scenario: Missing skill fails verification
- **WHEN** `~/.agents/skills/testpilot-normal-test` is missing
- **THEN** `testpilot --verify-install` exits non-zero and reports the missing skill path

### Requirement: Wrapper requires no source environment activation
The installed `~/.local/bin/testpilot` wrapper SHALL execute the managed virtualenv's TestPilot console script directly and SHALL NOT require users to source an activation script or set `PYTHONPATH`.

#### Scenario: Wrapper invokes managed console script
- **WHEN** user runs `~/.local/bin/testpilot --version`
- **THEN** the wrapper executes the console script from `~/.local/share/testpilot/.venv` and prints TestPilot version information

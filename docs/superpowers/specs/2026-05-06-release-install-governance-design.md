# Release Install and Governance Design

Date: 2026-05-06
Status: approved design draft

## Problem Statement

TestPilot is ready for a fixed release workflow, but current operation still feels like a developer checkout:

- install guidance relies on `uv pip install -e .` or `python -m testpilot.cli`
- runtime paths assume a cloned repository
- users may need to activate a venv or set environment variables
- `wifi_llapi` execution is documented through mixed command forms
- policy, release, help, README, skill, and changelog alignment are not enforced as a single gate

QC/TEST users need a simple operational surface:

```bash
testpilot wifi_llapi --dut-fw-ver BGW720-B0-403
```

They should not need to know where the repo is cloned, source a virtualenv, or manually install skills. Maintainers still need a real git checkout underneath because QC may modify test YAML and those changes must be reviewable and mergeable back into the repository.

## Decisions

1. Use a managed checkout, not wheel-only package data, for the first fixed deployment.
2. Install TestPilot under `~/.local/share/testpilot` and expose `~/.local/bin/testpilot`.
3. Install repository skills into `~/.agents/skills`, specifically `testpilot-normal-test`.
4. Install or update `serialwrap` from the `paulc-arc` fork as part of TestPilot install/update.
5. Official runtime entrypoint is `testpilot wifi_llapi`; `testpilot run wifi_llapi` remains compatible but is no longer the primary documentation path.
6. Updates use `testpilot --update [REF]`, not `self-update` and not `--channel`.
7. Default installer source is `paulc-arc/testpilot`, but test/local/fork usage can override the repository URL and ref through environment variables.
8. Full blocking policy is adopted, but the policy substrate is first de-personalized and moved to `paulc-arc`.
9. Policy config is `.project-policy.yml`, not `.paul-project.yml`.
10. TestPilot version canonical source becomes `VERSION`; `pyproject.toml` and `src/testpilot/__init__.py` are mirrors.
11. `testpilot --version` shows both semantic version and source ref, for example `TestPilot 0.2.0 (main@abc1234)`.
12. Current release alignment returns to the already tagged release `v0.2.0`; unreleased changes stay in `CHANGELOG.md [Unreleased]`.

## Target Install Layout

```text
~/.local/share/testpilot/
  src/          # managed git checkout
  .venv/        # TestPilot runtime virtualenv

~/.local/bin/
  testpilot     # wrapper; no source env needed

~/.agents/skills/
  testpilot-normal-test/
```

The managed checkout remains available for maintainers who need to inspect diffs, recover QC YAML edits, create branches, or submit PRs. QC/TEST users operate through the wrapper only.

## Installer UX

Official install command:

```bash
curl -fsSL https://raw.githubusercontent.com/paulc-arc/testpilot/main/scripts/install.sh | bash
```

Local or fork test override:

```bash
TESTPILOT_REPO_URL=file:///home/paul_chen/prj_arc/testpilot \
  bash scripts/install.sh
```

```bash
TESTPILOT_REPO_URL=https://github.com/hamanpaul/testpilot.git \
TESTPILOT_REF=main \
  bash scripts/install.sh
```

Installer defaults:

```bash
TESTPILOT_REPO_URL=${TESTPILOT_REPO_URL:-https://github.com/paulc-arc/testpilot.git}
TESTPILOT_REF=${TESTPILOT_REF:-latest-release}
SERIALWRAP_REPO_URL=${SERIALWRAP_REPO_URL:-https://github.com/paulc-arc/serialwrap.git}
```

`latest-release` means the installer resolves the latest stable `vX.Y.Z` tag and checks it out. A specific branch, tag, or commit can be selected by `TESTPILOT_REF`.

The same `install.sh` can live in both `hamanpaul` and `paulc-arc` repositories because the default production target is encoded as `paulc-arc`, while tests can override the source. Release work should not require a late URL rewrite.

## Update UX

```bash
testpilot --update
```

Updates the managed checkout to latest `main`, reinstalls TestPilot into its managed venv, syncs skills, and updates/checks serialwrap.

```bash
testpilot --update v0.2.0
```

Checks out or fetches the requested ref, reinstalls TestPilot, syncs skills, and updates/checks serialwrap.

`--update` needs pre-dispatch handling before normal Click command routing because the desired UX is an option with an optional positional value.

## Runtime CLI UX

Primary command:

```bash
testpilot wifi_llapi --dut-fw-ver BGW720-B0-403
testpilot wifi_llapi --case wifi-llapi-D004-kickstation
```

Compatibility command:

```bash
testpilot run wifi_llapi --dut-fw-ver BGW720-B0-403
```

The compatibility command remains valid for old workflows and scripts, but docs and skills should prefer `testpilot wifi_llapi`.

`testpilot wifi_llapi --help` must clearly state the format:

```text
Usage:
  testpilot wifi_llapi [--case CASE_ID] [--dut-fw-ver FW_VER]
```

Helper commands remain grouped under `testpilot wifi-llapi ...` unless implementation decides to alias them later. The fixed user-facing normal-run path is `testpilot wifi_llapi`.

## Verify Install UX

Add a verification command or top-level option, named in docs as:

```bash
testpilot --verify-install
```

It checks:

- managed checkout exists
- wrapper points at the managed venv
- console script works
- `serialwrap` is available
- skill exists at `~/.agents/skills/testpilot-normal-test`
- current git remote/ref/short SHA
- `VERSION`, `pyproject.toml`, and `src/testpilot/__init__.py` align
- plugin assets and `wifi_llapi` cases are discoverable

## Version Governance

Current repo state before implementation:

```text
latest tag: v0.2.0
pyproject.toml: 0.2.2
src/testpilot/__init__.py: 0.2.2
```

Target state for this release-governance migration:

```text
VERSION: 0.2.0
pyproject.toml: 0.2.0
src/testpilot/__init__.py: 0.2.0
latest published tag: v0.2.0
```

`CHANGELOG.md [0.2.0]` becomes the curated release note section for the existing tag. Work after `v0.2.0` remains in `[Unreleased]` until the next release PR.

`testpilot --version` should include source ref:

```text
TestPilot 0.2.0 (main@abc1234)
```

or:

```text
TestPilot 0.2.0 (v0.2.0@2f7caf8)
```

This keeps semantic version stable while still making main-branch updates traceable.

The release workflow reads `VERSION` as canonical, verifies `pyproject.toml` and `src/testpilot/__init__.py` as mirrors, and verifies the tag is `v$(cat VERSION)`.

## Policy Governance

The `paulc-arc` forks exist and should be adjusted before TestPilot pins them:

- `paulc-arc/paulsha-conventions`
- `paulc-arc/.github`
- `paulc-arc/new-project-template`

Required de-personalization:

- remove `hamanpaul`-specific references or replace with `paulc-arc` where owner-specific behavior is needed
- remove `paul` personal naming from config names, docs, scripts, rule messages, and generated templates
- rename `.paul-project.yml` to `.project-policy.yml`
- update rule loader, README, workflow examples, template files, and CLI help sync scripts to use `.project-policy.yml`
- update reusable workflow repository references to `paulc-arc/paulsha-conventions`
- retain full SHA pinning; do not use branch or tag refs for policy-check workflow pinning

TestPilot should then add blocking policy-check pinned to the selected full commit SHA in `paulc-arc/paulsha-conventions`.

Full policy adoption means satisfying R-01 through R-16. Expected TestPilot changes include:

- add `.project-policy.yml`
- add `VERSION`
- align version mirrors
- add or synchronize `CLAUDE.md`, `GEMINI.md`, and `.github/copilot-instructions.md`
- preserve existing `AGENTS.md` project-specific rules while adding required policy metadata
- update PR template and workflows
- add README CLI help marker sections

## CLI Help Synchronization

`.project-policy.yml` should declare help sync for at least:

```yaml
cli:
  - command: "testpilot"
    help_args: ["--help"]
    reflected_in: "README.md"
    marker: "testpilot-help"
  - command: "testpilot"
    help_args: ["wifi_llapi", "--help"]
    reflected_in: "README.md"
    marker: "testpilot-wifi-llapi-help"
  - command: "testpilot"
    help_args: ["--update", "--help"]
    reflected_in: "README.md"
    marker: "testpilot-update-help"
```

The policy check runs the actual commands and compares their output to README marker blocks. Developers update the marker blocks with the policy helper script before opening PRs.

## Skill Synchronization

Installer and update flows sync:

```text
skills/testpilot-normal-test -> ~/.agents/skills/testpilot-normal-test
```

The skill must be updated to prefer:

```bash
testpilot wifi_llapi
testpilot wifi_llapi --case <CASE_ID>
```

It should stop presenting `uv run python -m testpilot.cli run wifi_llapi` as the preferred repository-normal-test path for QC/TEST operation. Compatibility notes can mention the old form only when useful for developers.

## Serialwrap Scope

TestPilot install/update should install or update serialwrap from:

```text
https://github.com/paulc-arc/serialwrap.git
```

However, any remaining serialwrap behavior that installs into `.paul_tools` is out of scope for this TestPilot release migration. Open a serialwrap issue before implementation to track neutralizing the serialwrap install root, for example to `~/.local/share/serialwrap`, with compatibility guidance.

## Documentation Scope

Files expected to change during implementation:

```text
README.md
docs/release-flow.md
AGENTS.md
CHANGELOG.md
skills/testpilot-normal-test/SKILL.md
.github/PULL_REQUEST_TEMPLATE.md
.github/workflows/*.yml
.project-policy.yml
VERSION
pyproject.toml
src/testpilot/__init__.py
scripts/install.sh
src/testpilot/cli.py
```

`docs/todos.md` is governed by project rules. Outside Plan Mode, do not add, remove, reorder, or renumber todo items. Only status/necessary note updates are allowed.

## Validation Plan

Implementation must include verification for:

- installer local override path
- installer default repo/ref logic
- `testpilot --update` default main behavior
- `testpilot --update v0.2.0` ref behavior
- `testpilot --version` source ref display
- `testpilot wifi_llapi --help` format clarity
- `testpilot --verify-install` checks
- skill sync path
- version mirror alignment
- release workflow tag/version validation
- policy-check full blocking pass
- existing `uv run pytest -q`

## Implementation Notes

1. `testpilot --verify-install` is a documented top-level option. Internally it may share implementation with a helper function, but no separate user-facing command is required.
2. `testpilot wifi_llapi` should share the same run path as `testpilot run wifi_llapi` through a common internal helper, so behavior and reporting stay identical.
3. Helper commands stay under the existing hyphenated `testpilot wifi-llapi ...` group for this release. This design does not add helper aliases.

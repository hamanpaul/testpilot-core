# release-governance Specification

## Purpose
Define version canonicality, release validation, project policy gates, and documentation synchronization requirements for TestPilot releases.

## Requirements
### Requirement: VERSION is canonical and mirrors must align
The repository SHALL contain a `VERSION` file that is the canonical semantic version source. `pyproject.toml` and `src/testpilot/__init__.py` SHALL mirror the exact `VERSION` value. For this migration, all three SHALL be `0.2.0`.

#### Scenario: Version mirrors align
- **WHEN** release validation reads `VERSION`, `pyproject.toml`, and `src/testpilot/__init__.py`
- **THEN** all three values are equal to `0.2.0`

#### Scenario: Mirror mismatch fails validation
- **WHEN** either `pyproject.toml` or `src/testpilot/__init__.py` differs from `VERSION`
- **THEN** release validation exits non-zero and identifies the mismatched file

### Requirement: Version output includes source ref
`testpilot --version` SHALL print the semantic version and source ref in the format `TestPilot X.Y.Z (<ref>@<short-sha>)`. The ref SHALL prefer the current branch or tag name when available and SHALL fall back to a detached-head commit label when no symbolic ref exists.

#### Scenario: Branch version output
- **WHEN** TestPilot runs from a checkout on `main` at commit `abcdef123`
- **THEN** `testpilot --version` prints `TestPilot 0.2.0 (main@abcdef1)`

#### Scenario: Tag version output
- **WHEN** TestPilot runs from a checkout at tag `v0.2.0` with commit `2f7caf8`
- **THEN** `testpilot --version` prints `TestPilot 0.2.0 (v0.2.0@2f7caf8)`

### Requirement: Release workflow validates tag, version, and policy gates
The release workflow SHALL run on release tags `vX.Y.Z`, verify that the tag name equals `v$(cat VERSION)`, verify mirror alignment, run the full test suite, and run the blocking project policy check pinned to the selected full commit SHA from `paulc-arc/paulsha-conventions`.

#### Scenario: Matching release tag passes version gate
- **WHEN** a workflow runs for tag `v0.2.0` and `VERSION` is `0.2.0`
- **THEN** the tag/version validation passes and the workflow proceeds to tests and policy checks

#### Scenario: Mismatched release tag fails version gate
- **WHEN** a workflow runs for tag `v0.2.1` and `VERSION` is `0.2.0`
- **THEN** the workflow exits non-zero before publishing release output

### Requirement: Project policy config declares docs and help sync gates
The repository SHALL use `.project-policy.yml` as the project-neutral policy config. It SHALL declare README help sync checks for `testpilot --help`, `testpilot wifi_llapi --help`, and `testpilot --update --help`, and it SHALL avoid `.paul-project.yml` naming.

#### Scenario: Help sync commands are declared
- **WHEN** policy validation reads `.project-policy.yml`
- **THEN** it finds help sync entries for markers `testpilot-help`, `testpilot-wifi-llapi-help`, and `testpilot-update-help`

#### Scenario: Personal policy config is absent
- **WHEN** policy validation checks repository root
- **THEN** `.project-policy.yml` exists and `.paul-project.yml` is absent

### Requirement: User-facing release changes update governance documentation
User-facing release/install changes SHALL update `CHANGELOG.md` under `[Unreleased]` or the curated `0.2.0` release section, `README.md`, `docs/release-flow.md`, `AGENTS.md`, `.github/PULL_REQUEST_TEMPLATE.md`, and workflow files so installation, update, verification, policy, and release guidance stay aligned.

#### Scenario: PR checklist includes release governance
- **WHEN** a maintainer opens a PR
- **THEN** the PR template prompts for version mirror, changelog, README/help sync, policy, and release workflow consideration

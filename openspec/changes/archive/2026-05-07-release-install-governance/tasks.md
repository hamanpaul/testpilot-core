## 1. Version and CLI foundations

- [x] 1.1 Add tests for canonical `VERSION` mirror alignment and source-ref-aware `testpilot --version`.
- [x] 1.2 Add `VERSION`, align `pyproject.toml` and `src/testpilot/__init__.py` to `0.2.0`, and implement source ref version formatting.
- [x] 1.3 Add tests for pre-dispatch `--update [REF]` and `--verify-install` handling before normal Click routing.
- [x] 1.4 Implement narrow pre-dispatch handling for `--update [REF]`, `--verify-install`, and update help.

## 2. Managed installer and verification

- [x] 2.1 Add installer tests for local repository override, default latest-release resolution, wrapper creation, skill sync, and serialwrap command selection using temporary home/bin paths.
- [x] 2.2 Implement `scripts/install.sh` managed checkout, managed venv install, wrapper generation, skill sync, configurable repo/ref defaults, and serialwrap install/update.
- [x] 2.3 Add tests for install verification checks, including missing skill failure and version mirror mismatch failure.
- [x] 2.4 Implement install verification helpers for checkout, wrapper, console script, serialwrap, skill path, git source, version mirrors, plugin assets, and wifi_llapi case discovery.

## 3. wifi_llapi operational command

- [x] 3.1 Add CLI tests proving `testpilot wifi_llapi` uses the same normal-run path and options as `testpilot run wifi_llapi`.
- [x] 3.2 Implement the `testpilot wifi_llapi` primary command through a shared internal run helper without changing helper commands under `testpilot wifi-llapi`.
- [x] 3.3 Add tests for `testpilot wifi_llapi --help` showing the fixed operational usage.

## 4. Release and policy governance

- [x] 4.1 Add tests or static checks for `.project-policy.yml` help sync declarations, absence of `.paul-project.yml`, and release tag/version validation.
- [x] 4.2 Add `.project-policy.yml`, release validation script or workflow steps, blocking policy-check workflow, and PR template release-governance checklist.
- [x] 4.3 Update `README.md`, `docs/release-flow.md`, `AGENTS.md`, `CHANGELOG.md`, and `skills/testpilot-normal-test/SKILL.md` to reflect install, update, verify, primary wifi_llapi command, version, and policy guidance.
- [x] 4.4 Refresh README help marker blocks for `testpilot --help`, `testpilot wifi_llapi --help`, and `testpilot --update --help`.

## 5. Validation and archive

- [x] 5.1 Run targeted tests for installer, CLI, version, and release governance.
- [x] 5.2 Run the full repository test suite.
- [x] 5.3 Request code review and resolve findings.
- [x] 5.4 Archive the OpenSpec change into canonical specs and update documentation.

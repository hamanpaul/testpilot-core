## 1. Manifest schema (optional version for core/plugins, pinned serialwrap)

- [x] 1.1 RED: add `tests/test_install_manifest.py` cases — `load_manifest` accepts core/plugin with no `version:` (→ `None`); serialwrap missing `version:` raises; `selected("wifi_llapi@0.3.1")` still pins
- [x] 1.2 Make `version` optional on `Core`/`Plugin` (`str | None = None`) and required on `Serialwrap` in `src/testpilot/install/manifest.py`; keep `selected()` override behavior
- [x] 1.3 Edit `install-manifest.yaml`: drop `version:` for core + plugins, keep `repo` + plugin `api_version`, keep serialwrap `version:` pinned
- [x] 1.4 GREEN: `tests/test_install_manifest.py` passes

## 2. Latest-compatible transactional resolution (installer)

- [x] 2.1 RED: installer test — resolution picks the newest API-compatible release over a newer-but-incompatible one; rewinds; no compatible release → abort WITHOUT mutating an existing install (stub `gh release list/view` + `api-version.txt`)
- [x] 2.2 Implement resolution in `scripts/install.sh`: resolve+install core (latest) first, read installed `API_VERSION`, then per plugin resolve newest-compatible via release metadata with a fallback; serialwrap uses the manifest pin; `--plugins name@ver` bypasses resolution
- [x] 2.3 Abort path: no compatible release → clear message (component, candidate api_versions, core API_VERSION), leave prior install intact
- [x] 2.4 GREEN: resolution tests pass

## 3. Shared post-install verify gate (online + offline)

- [x] 3.1 RED: installer test proving the ONLINE path invokes `testpilot --verify-install` and exits non-zero when a plugin is API-incompatible
- [x] 3.2 Factor the offline gate into a `_post_install_gate` helper in `scripts/install.sh`; call it at the end of BOTH branches
- [x] 3.3 Confirm/harden `--verify-install` reports `IncompatiblePluginError` as an actionable FAIL (pre-existing `managed-installation` requirement + scenario already cover it; online path now invokes it)
- [x] 3.4 GREEN: online-gate + verify-install tests pass

## 4. `--update` newest-compatible without bricking

- [x] 4.1 RED: update test — installer abort mid-update rolls back from snapshot and leaves the working install unchanged (`test_installer_failure_triggers_rollback`)
- [x] 4.2 Extract `_rollback_from_snapshot`; call it on BOTH installer-nonzero and verify-failure (reuses existing snapshot + `--no-index` rollback); `--update` inherits install.sh resolution
- [x] 4.3 GREEN: update tests pass

## 5. Offline bundle build-time resolution

- [~] 5.1 RED: build resolves latest core/plugins, keeps serialwrap pinned, writes `resolved-manifest.yaml` — NO automated test: `build-bundle.sh` has no test harness in-repo (offline tests fabricate tarballs directly; the dry-run uses a real `python3 -m venv`+pip that resists stubbing). Covered by `bash -n` + logic parity with the tested `install.sh` resolution. Pre-existing gap, flagged in the PR.
- [x] 5.2 Apply resolution in `scripts/build-bundle.sh` at build time (latest for unpinned core/plugins; serialwrap pinned); emit `resolved-manifest.yaml` into the staged bundle
- [x] 5.3 Verify via `bash -n scripts/build-bundle.sh` (see 5.1 note)

## 6. Sweep exact-version test assertions

- [x] 6.1 Updated `tests/test_installer.py` (stubs + new tests), `tests/test_install_sh_token_hygiene.py` (`$pver`→`$USE_VER`); `test_predispatch.py`/`test_wheel_contents.py` unaffected (keyword construction / no manifest-version assert)
- [x] 6.2 `tests/test_install_compat.py` unaffected (api_version only); `test_release_governance.py` / `test_version_metadata.py` do not assert manifest `core.version` — full suite green

## 7. Docs + changelog

- [x] 7.1 `README.md` install section: online = latest-compatible, offline = pinned snapshot, serialwrap pinned
- [x] 7.2 `docs/release-flow.md`: no explicit core/plugin "re-pin manifest" step existed to remove; CHANGELOG documents core no longer re-pins for plugin bumps
- [x] 7.3 `CHANGELOG.md [Unreleased]`: flow-latest-compatible entry added

## 8. Gate + finish

- [x] 8.1 Suite green: `.venv/bin/python -m pytest -q` → 548 passed, 1 pre-existing failure unrelated to this change (`test_offline_creates_wrapper`: bundle name `cp311` vs system python `3.12`; fails identically on `main`)
- [x] 8.2 `python3 -m policy_check --repo .` → pass 25 / fail 0 / warn 1 (R-22 advisory, no new dangling refs)
- [ ] 8.3 PR checklist / CHANGELOG / branch-name compliant; open PR (zh-tw)

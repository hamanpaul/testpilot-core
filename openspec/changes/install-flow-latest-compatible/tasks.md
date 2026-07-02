## 1. Manifest schema (optional version for core/plugins, pinned serialwrap)

- [ ] 1.1 RED: add `tests/test_install_manifest.py` cases — `load_manifest` accepts core/plugin with no `version:` (→ `None`); serialwrap missing `version:` raises; `selected("wifi_llapi@0.3.1")` still pins
- [ ] 1.2 Make `version` optional on `Core`/`Plugin` (`str | None = None`) and required on `Serialwrap` in `src/testpilot/install/manifest.py`; keep `selected()` override behavior
- [ ] 1.3 Edit `install-manifest.yaml`: drop `version:` for core + plugins, keep `repo` + plugin `api_version`, keep serialwrap `version:` pinned
- [ ] 1.4 GREEN: `tests/test_install_manifest.py` passes

## 2. Latest-compatible transactional resolution (installer)

- [ ] 2.1 RED: installer test — resolution picks the newest API-compatible release over a newer-but-incompatible one; rewinds to the previous compatible release; no compatible release → abort WITHOUT mutating an existing install (mock `gh release list`/metadata + `_check_api_compat`)
- [ ] 2.2 Implement resolution in `scripts/install.sh`: resolve+install core (latest) first, read installed `API_VERSION`, then per plugin resolve newest-compatible via release metadata with a transactional probe fallback; serialwrap uses the manifest pin; `--plugins name@ver` bypasses resolution
- [ ] 2.3 Abort path: no compatible release → clear message (component, candidate api_versions, core API_VERSION), leave prior install intact
- [ ] 2.4 GREEN: resolution tests pass

## 3. Shared post-install verify gate (online + offline)

- [ ] 3.1 RED: installer test proving the ONLINE path invokes `testpilot --verify-install` and exits non-zero when a plugin is API-incompatible
- [ ] 3.2 Factor the offline gate into a `_post_install_gate` helper in `scripts/install.sh`; call it at the end of BOTH branches
- [ ] 3.3 Confirm/harden `--verify-install` (`src/testpilot/cli.py`) reports `IncompatiblePluginError` as an actionable FAIL (plugin name, requested vs provided API version), never a crash/silent skip; add/extend a unit test
- [ ] 3.4 GREEN: online-gate + verify-install tests pass

## 4. `--update` newest-compatible without bricking

- [ ] 4.1 RED: update test — `--update` reinstalls newest-compatible; no compatible release → exit non-zero and leave working install unchanged (extend `tests/test_update_reconcile.py` / `test_update_installer_seam.py`)
- [ ] 4.2 Wire `--update` to the resolution path (reuse §2); preserve snapshot + restore-on-verify-fail and the unresolved-manifest guard
- [ ] 4.3 GREEN: update tests pass

## 5. Offline bundle build-time resolution

- [ ] 5.1 RED: bundle test — build resolves newest-compatible core/plugins, keeps serialwrap pinned, and writes `resolved-manifest.yaml` (mock release resolution)
- [ ] 5.2 Apply the same resolution in `scripts/build-bundle.sh` at build time; serialwrap pinned; emit `resolved-manifest.yaml` into the staged bundle
- [ ] 5.3 GREEN: bundle test passes

## 6. Sweep exact-version test assertions

- [ ] 6.1 Update `tests/test_installer.py`, `test_predispatch.py`, `test_wheel_contents.py` to drop exact manifest-version assertions and cover the resolution path
- [ ] 6.2 Confirm `tests/test_install_compat.py` unaffected (api_version only); confirm `test_release_governance.py` / `test_version_metadata.py` don't assert manifest `core.version`

## 7. Docs + changelog

- [ ] 7.1 `README.md` install section: online = latest-compatible, offline = pinned snapshot, serialwrap pinned
- [ ] 7.2 `docs/release-flow.md`: remove the core/plugin "re-pin manifest" step; keep a deliberate serialwrap-pin bump step
- [ ] 7.3 `CHANGELOG.md [Unreleased]`: add the flow-latest-compatible entry

## 8. Gate + finish

- [ ] 8.1 Full suite green: `.venv/bin/python -m pytest -q`
- [ ] 8.2 `python3 -m policy_check --repo .` clean; `install-doctor` CI gate still passes locally
- [ ] 8.3 PR checklist / CHANGELOG / branch-name compliant; open PR (zh-tw)

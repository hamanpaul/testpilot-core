## 1. Foundation: packaging hygiene

- [ ] 1.1 Rename core distribution `testpilot` → `testpilot-core` in `pyproject.toml` (`[project].name`); keep import package `testpilot` and `[project.scripts] testpilot = "testpilot.cli:main"`
- [ ] 1.2 Drive version from `VERSION` via hatch dynamic version (`[tool.hatch.version]`); remove any hardcoded version mirror drift
- [ ] 1.3 Remove the dead `.gitignore` line `plugins/wifi_llapi/reports/*` (core ships no wifi_llapi)
- [ ] 1.4 Ship `skills/testpilot-normal-test` as core wheel package data; add a hatch include/allowlist so wheel contents don't depend on `.gitignore`
- [ ] 1.5 RED: add a test asserting `uv build` wheel contains `entry_points`-less core modules + the packaged skill and the dist metadata name is `testpilot-core`; watch it fail, then make it pass

## 2. Install manifest + API-compat gate

- [ ] 2.1 RED: add a test for an `install-manifest.yaml` parser (schema: core/plugins[name,repo,version,api_version]/serialwrap, public/private+auth) — failing for the right reason first
- [ ] 2.2 Implement the manifest parser/loader in `src/testpilot/` and make 2.1 pass
- [ ] 2.3 RED+impl: API-compat gate that, for each pinned `(core, plugin)`, checks plugin `api_version` vs core `API_VERSION` under the `PluginLoader` rule; fails on incompatible pin
- [ ] 2.4 Add a starter `install-manifest.yaml` (core pinned; plugin/serialwrap entries scaffolded, marked private/public + auth)

## 3. Online installer rewrite (scripts/install.sh)

- [ ] 3.1 Remove the broken editable `-e $MANAGED_SRC/plugins/...` step; stop creating/depending on `~/.local/share/testpilot/src`
- [ ] 3.2 Authed manifest pre-fetch at REF (`gh api`), then create/refresh managed venv
- [ ] 3.3 Fetch private wheels via `gh release download` using `GH_TOKEN`/`TESTPILOT_INSTALL_TOKEN` env only (never token-in-URL, never logged); install core wheel first, plugins `--no-deps`, then serialwrap
- [ ] 3.4 `--plugins <subset>` selection; default = full manifest set; write wrapper; sync packaged skill from `importlib.resources`
- [ ] 3.5 Fallback to `pip install git+https://...@$VER` (source build) when a pinned tag has no wheel asset (transition)
- [ ] 3.6 Test: token never appears in process args/stdout/stderr/wrapper (assert log-scrub); `set -x` never covers token-bearing sections

## 4. Update + verify-install + migration (src/testpilot/cli.py)

- [ ] 4.1 Rewrite `_handle_update`: drop the `managed_src/.git` gate; re-resolve manifest, reinstall pinned wheels into the venv, reconcile (uninstall non-manifest `testpilot.plugins` dists), capture pre-update `pip freeze` snapshot
- [ ] 4.2 RED: test that re-running install/update does NOT produce a duplicate `testpilot.plugins` entry point (no `_normalize_entry_points` ValueError); reconcile removes dropped plugins
- [ ] 4.3 Rewrite `--verify-install` wheel-mode: real `importlib.metadata.entry_points`/versions, attempt `PluginLoader.load` per plugin (FAIL on `IncompatiblePluginError`), wrapper→managed venv, serialwrap binary, skill from packaged data; warn on `testpilot` importable outside managed venv
- [ ] 4.4 Migration: detect+reconcile prior install shapes (`pip --user testpilot`, pipx, legacy `src` checkout); repoint wrapper; warn on hybrid
- [ ] 4.5 Tests for 4.1/4.3/4.4 scenarios green

## 5. Offline bundle (scripts/build-bundle.sh + install.sh --offline)

- [ ] 5.1 `build-bundle.sh`: download exact pinned release wheels (no rebuild) + `pip download` third-party closure (same Linux platform + py-minor); emit `wheelhouse/` + pinned `requirements.txt` + packaged skill + `testbed.yaml.example`
- [ ] 5.2 Hard-exclude `configs/testbed.yaml`, root `*.xlsx`, `compare-*`; bundle name encodes `linux-<arch>-cp<XY>`; emit detached `SHA256SUMS`
- [ ] 5.3 Build-box dry-run gate: `pip install --no-index --find-links=wheelhouse -r requirements.txt` into throwaway venv; fail build if unresolved
- [ ] 5.4 `install.sh --offline <bundle>`: verify `SHA256SUMS` (abort on mismatch), assert py-minor/platform, create venv, `pip install --no-index --find-links=wheelhouse -r requirements.txt`, wrapper + skill, run `--verify-install` gate; zero network/credentials
- [ ] 5.5 Test: build a tiny bundle and install it in a network-disabled clean venv; `testpilot list-plugins`/`list-cases` work; checksum-mismatch and platform-mismatch abort paths covered

## 6. CI + release artifacts

- [ ] 6.1 Add `uv build` + `gh release upload $TAG dist/*.whl` to `.github/workflows/release.yml`
- [ ] 6.2 CI assertion: built wheel includes packaged skill + no `reports/<timestamp>` bundle; dist name is `testpilot-core`
- [ ] 6.3 Wire the manifest API-compat gate (2.3) and the new tests into CI (R-19)

## 7. Docs + governance

- [ ] 7.1 Rewrite `README.md` install section to the wheel + dual-entry model (online one-click + `--offline` bundle); make core README the canonical install reference; align sources to `hamanpaul/*`
- [ ] 7.2 Regenerate CLI help markers for `--update`/`--verify-install` (R-16)
- [ ] 7.3 Update `CHANGELOG.md [Unreleased]` (note BREAKING: dist rename + src-checkout removal)
- [ ] 7.4 Cross-reference the coordination issue (Closes #N) for the release DAG; note plugin/serialwrap wheels are prerequisites (Phase B) before core manifest pins them

## 8. Verify + policy gate

- [ ] 8.1 `uv run pytest -q` green
- [ ] 8.2 `python3 -m policy_check --repo .` no failure
- [ ] 8.3 Manual smoke: online install via `TESTPILOT_REPO_URL=file://…`/stub and offline `--offline` bundle each reach a passing `--verify-install`

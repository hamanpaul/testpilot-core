## Why

The one-click installer pins every component to an exact version in
`install-manifest.yaml`, so every downstream plugin patch forces `core` to open a
re-pin PR and cut its own release (e.g. `core v0.3.2` was purely a re-pin of
`serialwrap 0.2.0 → 0.2.1`). The runtime already gates plugins by SDK API
version, not release version — so as long as the API is compatible, `core` should
support the latest plugin without a re-pin release.

## What Changes

- Online install resolves **core and all plugins** to each repo's **newest
  release that is API-compatible with the installed core**, instead of the
  manifest pin. **BREAKING** for `install-manifest.yaml` schema: `version:` is
  dropped for core/plugins.
- Resolution is **transactional**: a candidate's `api_version` is determined
  before it is committed to the managed venv; if no compatible release exists the
  installer aborts loudly and leaves any pre-existing working install intact.
- A single **post-install verify gate** (`testpilot --verify-install || fail`)
  runs on **both** online and offline paths (today it runs only offline).
- **serialwrap stays pinned** in the manifest — it has no API/protocol contract
  to make latest safe.
- The offline bundle resolves latest-compatible for core/plugins at **build
  time**, stays an exact SHA256-verified snapshot, and records a
  `resolved-manifest.yaml` for provenance.
- Escape hatch preserved: `--plugins name@ver` and an optional manifest
  `version:` still pin.
- `core` release-flow drops the "re-pin manifest for plugins" step.

## Capabilities

### New Capabilities

- (none — this modifies existing installation capabilities)

### Modified Capabilities

- `managed-installation`: online install switches from exact-pin to
  latest-API-compatible transactional resolution for core/plugins; serialwrap
  stays pinned; the post-install verify gate now runs on the online path too;
  `--update` reinstalls newest-compatible without bricking a working install.
- `offline-install-bundle`: bundle build resolves latest-compatible for
  core/plugins at build time (serialwrap pinned) and records a resolved version
  manifest for provenance while keeping the exact-snapshot guarantee.

## Impact

- Code: `scripts/install.sh`, `scripts/build-bundle.sh`,
  `src/testpilot/install/manifest.py`, `install-manifest.yaml`,
  `src/testpilot/cli.py` (`--verify-install` hardening).
- Tests: `tests/test_install_manifest.py`, `test_installer.py`,
  `test_update_reconcile.py`, `test_update_installer_seam.py`,
  `test_predispatch.py`, `test_wheel_contents.py` (drop exact-version asserts,
  add resolution + online-gate coverage).
- Docs: `README.md`, `docs/release-flow.md`, `CHANGELOG.md`.
- Cross-repo (rollout dependency, non-blocking): plugin release workflows may
  publish per-release API metadata to enable metadata-based resolution; until
  then the transactional download-probe fallback applies.
- Unchanged: runtime `_check_api_compat` semantics; `install-doctor` CI gate
  (reads `api_version` only); serialwrap is not a pip dependency.

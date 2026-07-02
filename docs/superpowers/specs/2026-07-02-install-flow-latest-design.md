# Install Flow: Flow-Latest for core / plugins / serialwrap

- Date: 2026-07-02
- Status: Draft (design approved, pre-implementation)
- Scope: `testpilot-core` install flow only
- Related: [`2026-06-27-install-flow-dual-entry-design.md`](2026-06-27-install-flow-dual-entry-design.md), [`2026-06-18-versioned-plugin-contract-design.md`](2026-06-18-versioned-plugin-contract-design.md)

## Problem

The one-click install path pins every component to an exact release version in
`install-manifest.yaml`:

```yaml
core:       { distribution: testpilot-core, version: "0.3.2" }
plugins:
  - { name: wifi_llapi,       version: "0.3.1", api_version: "1.1" }
  - { name: brcm_fw_upgrade,  version: "0.1.0", api_version: "1.1" }
serialwrap: { version: "0.2.1" }
```

Every time a plugin or serialwrap cuts a patch release, `core` must open a
re-pin PR **and cut its own release** just to advance the pin — e.g. `core
v0.3.2` was purely a re-pin of `serialwrap 0.2.0 → 0.2.1`. This is a recurring
tax that couples `core`'s release cadence to unrelated downstream bumps, even
when nothing in `core` changed and the SDK API contract is unchanged.

The intent: **as long as the SDK API version is compatible, `core` should
support the latest plugin / serialwrap without a re-pin release.**

## Current architecture (what actually binds versions today)

Three independent mechanisms — only one of them binds release versions:

1. **Runtime plugin load — already API-based, no release-version binding.**
   `src/testpilot/core/plugin_loader.py:_check_api_compat` (L36) enforces
   `plugin.major == core.major and core.minor >= plugin.minor` against
   `testpilot.api.API_VERSION` (`= "1.1"`, `src/testpilot/api/__init__.py:58`).
   The plugin's release version (0.3.1 …) is never consulted at load time.

2. **serialwrap is not a pip dependency.** `pyproject.toml` deps are only
   `pyyaml / click / rich / openpyxl / ruamel.yaml`. `core` invokes serialwrap
   as an external binary via `resolve_serialwrap_binary`
   (`src/testpilot/serialwrap_binary.py`), so runtime never version-checks it.

3. **`install-manifest.yaml` exact-pin — install-time only.** Consumed by:
   - `scripts/install.sh` (online): parses the manifest, then per component runs
     `gh release download "v${version}"` (L411) into a temp dir, `pip install`s
     it, and copies the wheel into `WHEEL_CACHE` for `--update` rollback.
     git+https `@v${version}` fallback (L430-446) when no wheel asset exists.
   - `scripts/build-bundle.sh` (offline): same `gh release download "v${version}"`
     (L183) to stage a wheelhouse + `SHA256SUMS` tarball.
   - `testpilot install-doctor` (`src/testpilot/cli.py:1327`, wired in CI
     `.github/workflows/ci.yml:80`): reads only the manifest's `api_version`
     fields and checks them against `core` `API_VERSION` — does **not** read
     release `version`.

**Conclusion:** runtime is already flow-latest-compatible. The only thing that
forces re-pin releases is the exact `version:` in the manifest, consumed by the
two install scripts.

## Goals

- Online install resolves **core, all plugins, and serialwrap** to each repo's
  **latest GitHub release** at install time, instead of a manifest pin.
- `core` releases only for its own code changes — never to advance a downstream
  pin.
- Preserve the escape hatch: an explicit pin (`--plugins name@ver`, or an
  optional `version:` left in the manifest) still works.
- Preserve offline reproducibility: the offline bundle remains an exact,
  SHA256-verified snapshot.
- Keep the SDK API contract as the safety boundary (runtime gate + loud verify).

## Non-goals

- **Latest-*compatible* auto-fallback** (former "Approach A": pick the newest
  release whose declared `api_version` is compatible, skip/rewind otherwise).
  Deferred as YAGNI — the plugin's `api_version` is a Python class attribute not
  present in wheel metadata, so pre-download gating would require download →
  import → rewind machinery. The runtime gate + loud post-install verify cover
  the failure mode; revisit if a bad plugin release actually bites.
- Changing the runtime `_check_api_compat` semantics.
- Changing serialwrap to a pip dependency.
- Any signing / platform-matrix / prerelease-channel work.

## Design

### 1. Manifest becomes a repo registry + API contract

`install-manifest.yaml`: drop the checked-in `version:` pins. Keep `repo`
(required) and, per plugin, `api_version` (the contract `core` requires; still
read by `install-doctor`).

```yaml
core:
  distribution: testpilot-core
  repo: hamanpaul/testpilot-core
  private: true
plugins:
  - { name: wifi_llapi,      repo: hamanpaul/wifi_llapi,      api_version: "1.1", private: true }
  - { name: brcm_fw_upgrade, repo: hamanpaul/brcm_fw_upgrade, api_version: "1.1", private: true }
serialwrap:
  repo: hamanpaul/serialwrap
  private: false
```

`src/testpilot/install/manifest.py`: make `version` optional on `Core`,
`Plugin`, `Serialwrap` (`version: str | None = None`). `load_manifest` tolerates
a missing `version:` key. `InstallManifest.selected` keeps honoring
`name@ver` overrides — when a version is supplied it pins, otherwise it stays
`None` (= resolve latest downstream). No key removed from the parser, so the
optional-pin escape hatch survives.

### 2. `scripts/install.sh` — online path

- New helper `_resolve_latest_version(repo)`:
  `gh release view --repo "$repo" --json tagName --jq .tagName`, strip a leading
  `v`. No release found → `fail` with an actionable message naming the repo.
- Per component: if the manifest (or `--plugins name@ver`) provided a version,
  use it; otherwise resolve latest. Feed the resolved version string into the
  **unchanged** `_install_pkg_online` (download / cache / git+https fallback
  logic is untouched — it just receives a resolved version instead of a pinned
  one).
- `core` is resolved the same way (its latest **release**, independent of which
  ref the manifest was fetched from).
- Emit `info` lines showing each resolved version so the operator sees exactly
  what was selected.

### 3. `scripts/build-bundle.sh` — offline path

- Same "version absent → resolve latest **at build time**" logic.
- The bundle still stages concrete wheels + `SHA256SUMS`, so the offline tarball
  remains an exact snapshot: **offline reproducibility is unchanged.**
- Additionally write a `resolved-manifest.yaml` into the bundle recording the
  exact versions the snapshot was built from (provenance; lets an operator see /
  reproduce the pinned set).

### 4. Safety net — loud post-install verify

The online path already ends with `testpilot --verify-install || fail`
(`scripts/install.sh:229`). Requirement: `--verify-install` (wheel mode,
`src/testpilot/cli.py:_verify_install_wheel_mode` / `_handle_verify_install`)
must surface an `IncompatiblePluginError` from `plugin_loader.load` as a clear,
actionable **FAIL** (naming the plugin, its requested API version, and core's
provided API version) — never a crash, never a silent skip. There is existing
handling keyed on `error == "IncompatiblePluginError"` (cli.py:426); this design
confirms and, if needed, hardens it so a latest plugin that outran core's API is
caught at install time rather than first run.

### 5. Untouched / minor

- **`install-doctor` CI gate** (`ci.yml:80`): reads only `api_version`, so it
  keeps working unchanged as the declared-contract check.
- **`testpilot --update`**: naturally becomes "reinstall latest" (re-runs
  resolve-latest) instead of reinstalling a pinned set. Accepted as a feature;
  verify it does not assume a pinned version and that rollback via `WHEEL_CACHE`
  (`--no-index`) still functions.

### 6. Tests

- `tests/test_install_manifest.py`: `version` optional; missing-version loads;
  `name@ver` override still pins.
- `tests/test_installer.py`, `tests/test_update_reconcile.py`,
  `tests/test_update_installer_seam.py`, `tests/test_predispatch.py`,
  `tests/test_wheel_contents.py`: drop assertions on exact manifest versions;
  add coverage for the latest-resolution path (mock `gh release view`).
- New: latest-resolution unit(s) — resolve strips `v`; no-release → fail;
  explicit pin bypasses resolution.
- New: verify-install returns a FAIL entry when a loaded plugin raises
  `IncompatiblePluginError`.
- `tests/test_install_compat.py`: unaffected (api_version only).
- `tests/test_release_governance.py` / `tests/test_version_metadata.py`:
  `core`'s own version mirrors — unaffected unless they assert the manifest's
  `core.version` (relax if so).

### 7. Docs

- `README.md` install section: online = latest, offline = pinned snapshot.
- `docs/release-flow.md`: **remove the "re-pin manifest" step**; state that
  `core` releases only for its own changes.
- `CHANGELOG.md [Unreleased]`: entry for the flow-latest change.

## Reproducibility model (explicit)

| Path | Version selection | Reproducible? |
|------|-------------------|---------------|
| Online one-click | latest release per repo, resolved at install time | No (by intent) |
| Explicit pin (`--plugins name@ver` / manifest `version:`) | pinned | Yes |
| Offline bundle | snapshot of latest at **build** time, `SHA256SUMS` + `resolved-manifest.yaml` | Yes |

## Release-process impact (the payoff)

`core` no longer opens a re-pin PR + release when `wifi_llapi` / `brcm_fw_upgrade`
/ `serialwrap` bump. Downstream repos release independently; the next online
install (or `--update`, or a freshly built bundle) picks them up automatically,
gated by the SDK API contract.

## Risks & mitigations

- **A downstream release outruns core's API** (declares a newer `api_version`).
  → runtime gate rejects it; the loud `--verify-install` FAIL (§4) makes it
  visible at install time. Mitigation for the future is the deferred
  latest-compatible auto-fallback (non-goal here).
- **serialwrap has no API contract** — flow-latest fully trusts its CLI/protocol
  stability. Accepted per decision; serialwrap is invoked over a stable transport
  seam and can be pinned via the escape hatch if a bad release appears.
- **Non-determinism between two online installs.** Accepted for the online path;
  the offline bundle + explicit pin cover the reproducible use cases.
- **`gh release view` requires auth / a published release.** The no-release path
  fails loudly; token handling is unchanged from the existing download flow.

## Rollout

1. Land manifest schema + `manifest.py` optional-version.
2. `install.sh` + `build-bundle.sh` resolve-latest; verify-install hardening.
3. Tests + docs + CHANGELOG.
4. Single PR on `feature/install-flow-latest` (zh-tw, policy-governed repo).

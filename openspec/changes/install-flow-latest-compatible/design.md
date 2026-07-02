## Context

The one-click installer exact-pins every component in `install-manifest.yaml`,
forcing a `core` re-pin PR + release on every downstream bump. The runtime
already gates plugins by SDK `api_version` (`plugin_loader._check_api_compat`),
not release version, so latest-compatible install is safe by construction. A
Codex adversarial review of the initial design surfaced two must-fix issues,
both incorporated here:

1. The online install path today has **no** post-install verify step — the gate
   (`install.sh:227-231`) runs only inside the offline branch. A naive
   flow-latest would install an incompatible plugin and print success.
2. "Latest, trust runtime gate" detects a bad release only **after** mutating the
   managed venv; one bad plugin release could brick unpinned install / `--update`.

The full design record lives at
`docs/superpowers/specs/2026-07-02-install-flow-latest-design.md` (Rev 2).

## Goals / Non-Goals

**Goals:**
- Online install resolves core + plugins to the newest release API-compatible
  with the installed core; `core` releases only for its own changes.
- Resolution is transactional — never leaves the managed venv broken; aborts
  loudly and preserves a prior working install when no compatible release exists.
- One post-install verify gate on both online and offline paths.
- serialwrap stays manifest-pinned.
- Offline bundle stays an exact, SHA256-verified snapshot; escape-hatch pins
  preserved.

**Non-Goals:**
- serialwrap flow-latest (no contract to gate on).
- Changing `_check_api_compat` semantics or making serialwrap a pip dependency.
- Signing / platform-matrix / prerelease channels.

## Decisions

- **Resolve core first, then plugins against the installed core.** Core is the
  API provider (self-consistent); reading `testpilot.api.API_VERSION` from the
  managed venv after core install gives the authority to resolve plugins.
  Alternative (resolve all from static manifest metadata) rejected: the manifest
  no longer carries plugin release versions, and declared `api_version` may lag
  the actual release.

- **Compatibility is part of selection (not post-hoc).** Enumerate a plugin's
  releases newest→oldest and pick the newest whose `api_version` is compatible.
  Primary mechanism: plugins publish per-release API metadata (wheel metadata
  field and/or a small `<plugin>-api.json` release asset) so the installer reads
  it without a full install. Fallback when metadata is absent: transactional
  probe — download candidate → check in a throwaway probe venv that has core →
  install winner into the managed venv, rewinding on failure. Alternative
  (install-then-verify-then-rollback in the real venv) rejected: it mutates the
  managed venv before knowing compatibility (violates "no broken mutation").

- **Shared post-install gate.** Factor the offline branch's
  `testpilot --verify-install || fail` into a helper called at the end of both
  branches. The gate is the backstop; resolution is the primary defense, so it
  should essentially never trip.

- **serialwrap pinned.** `version:` stays required for serialwrap in the manifest
  and in resolution; only core/plugins flow latest. Revisiting requires a real
  serialwrap contract (separate future change).

- **Manifest `version:` optional for core/plugins.** Absent ⇒ resolve latest
  compatible; present ⇒ pin (escape hatch, alongside `--plugins name@ver`).

## Risks / Trade-offs

- [A plugin release outruns core's API] → resolution skips it, installs newest
  compatible; never bricks (transactional); verify gate is the backstop.
- [Primary metadata mechanism needs downstream buy-in] → until plugins publish
  per-release API metadata, the transactional-probe fallback applies
  (self-contained, pays a download+probe per rewind). Rollout dependency, not a
  blocker.
- [serialwrap latest could break live tests] → avoided: serialwrap stays pinned.
- [Non-determinism between two online installs] → accepted for online; offline
  bundle + explicit pin cover reproducible use cases.
- [`gh release list/view` needs auth / a published release] → no-release path
  fails loudly; token handling unchanged.

## Migration Plan

1. Land manifest schema + `manifest.py` optional-version (core/plugin) / required
   serialwrap.
2. `install.sh`: shared post-install gate + latest-compatible transactional
   resolution; `build-bundle.sh`: build-time resolution + `resolved-manifest.yaml`;
   serialwrap pinned throughout.
3. Tests + docs (`README.md`, `docs/release-flow.md`) + `CHANGELOG.md`.
4. (Cross-repo, parallel, non-blocking) plugin release workflows publish
   per-release API metadata to enable the primary resolution mechanism.

Rollback: revert the PR; the manifest can be re-pinned with explicit `version:`
values to restore exact-pin behavior without further code changes.

## Open Questions

- None blocking. The primary vs fallback resolution mechanism is settled
  (fallback ships in this change; metadata is an incremental cross-repo rollout).

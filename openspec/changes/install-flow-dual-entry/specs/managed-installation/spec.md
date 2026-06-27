## MODIFIED Requirements

### Requirement: Verify install reports deployment health
`testpilot --verify-install` SHALL run before normal Click dispatch and, in the wheel deployment model, report health using the live runtime metadata rather than a source checkout. It SHALL report whether: the managed virtualenv and `~/.local/bin/testpilot` wrapper exist and the wrapper resolves to the managed virtualenv's console script; the installed core distribution `testpilot-core` and its version are importable; each plugin declared by `importlib.metadata.entry_points(group="testpilot.plugins")` loads via `PluginLoader.load` (SDK `api_version` compatible with the installed core `API_VERSION`); `serialwrap` is resolvable on the operator's PATH; and the bundled `testpilot-normal-test` skill is present from packaged data. It SHALL fail when any plugin entry point is API-incompatible, and SHALL warn when a `testpilot` distribution is importable from outside the managed virtualenv.

#### Scenario: Healthy wheel install passes verification
- **WHEN** core + manifest plugins + serialwrap are installed into the managed venv and the wrapper resolves to it
- **THEN** `testpilot --verify-install` exits 0 and prints each checked item (venv, wrapper, core version, per-plugin load + version, serialwrap, skill) as passing

#### Scenario: API-incompatible plugin fails verification
- **WHEN** an installed plugin's declared `api_version` is incompatible with the installed core `API_VERSION`
- **THEN** `testpilot --verify-install` exits non-zero and reports the offending plugin and the version mismatch, rather than listing it as healthy

#### Scenario: Stray non-managed install warns
- **WHEN** a `testpilot`/`testpilot-core` distribution is importable from outside the managed virtualenv (e.g. a leftover `pip --user` install)
- **THEN** `testpilot --verify-install` warns about the out-of-managed-venv import so the operator can reconcile it

## ADDED Requirements

### Requirement: Managed installer installs pinned wheels into a managed venv
The installer SHALL create or update a runtime virtualenv under `~/.local/share/testpilot/.venv`, install the manifest-pinned `testpilot-core` wheel plus each selected plugin wheel and the `serialwrap` wheel into that virtualenv, expose `~/.local/bin/testpilot` as a wrapper that executes the managed virtualenv's console script with no activation, and sync the packaged `testpilot-normal-test` skill into `~/.agents/skills/testpilot-normal-test`. It SHALL NOT create or depend on a `~/.local/share/testpilot/src` source checkout. Private wheels SHALL be fetched with `gh release download` using a token provided only via the `GH_TOKEN`/`TESTPILOT_INSTALL_TOKEN` environment, never embedded in a URL or printed. `--plugins <name[,name...]>` SHALL select a subset; the default SHALL install the manifest's full plugin set.

#### Scenario: Online install of the manifest set
- **WHEN** the installer runs on a networked machine with a valid `TESTPILOT_INSTALL_TOKEN` and no `--plugins`
- **THEN** it creates the managed venv, installs the manifest-pinned core + all plugins + serialwrap as wheels, writes the wrapper, syncs the skill, and `testpilot --verify-install` passes

#### Scenario: Subset install
- **WHEN** the installer runs with `--plugins wifi_llapi`
- **THEN** only core, the `wifi_llapi` plugin, and serialwrap are installed, and `testpilot list-plugins` shows exactly `wifi_llapi`

#### Scenario: Token never leaks
- **WHEN** the installer fetches private wheels
- **THEN** the token is passed only via environment to `gh`, and never appears in process arguments, the wrapper, stdout/stderr, or any log

### Requirement: Top-level update reinstalls pinned wheels and reconciles the plugin set
`testpilot --update [REF]` SHALL run before normal Click dispatch, resolve the install manifest shipped with the installed core, reinstall the pinned core/plugin/serialwrap wheels into the managed virtualenv (delegating to the packaged installer, never resolving private components from public PyPI), and reconcile the virtualenv to exactly the manifest's component set by uninstalling any installed `testpilot.plugins` distribution not in the manifest. If the manifest cannot be resolved it SHALL exit non-zero WITHOUT modifying the installation (never treat an unresolved manifest as "uninstall everything"). It SHALL capture a pre-update snapshot (e.g. `pip freeze`) before changing the environment, and on post-update `--verify-install` failure SHALL restore the previous pinned set. `REF` is accepted and forwarded for forward-compatibility; fetching a different ref's manifest for cross-version update is a tracked follow-up (a runtime notice is emitted for a non-default `REF`).

#### Scenario: Update reinstalls pinned wheels
- **WHEN** user runs `testpilot --update` after a new manifest release
- **THEN** the managed venv is reinstalled to the new manifest's pinned wheels and `testpilot --verify-install` passes

#### Scenario: Dropped plugin is reconciled away
- **WHEN** a plugin present in the venv is no longer in the resolved manifest and user runs `testpilot --update`
- **THEN** that plugin distribution is uninstalled so no orphaned `testpilot.plugins` entry point remains, and the CLI does not raise a duplicate/incompatible-entry-point error

### Requirement: Install manifest pins the compatible component set
An `install-manifest.yaml` in core SHALL be the single source of truth for the managed install, exact-pinning the core version, each plugin (name, source repo, version, required `api_version`), and serialwrap, and marking each component public/private with its auth requirement. CI SHALL validate, for each pinned `(core, plugin)` pair, that the plugin's declared `api_version` is compatible with the core's `API_VERSION` under the `PluginLoader` rule, and SHALL fail the manifest change when any pinned pair is incompatible. Operators MAY override a single component with `--plugins <name>@<version>`.

#### Scenario: Manifest drives install-all
- **WHEN** the installer runs with no `--plugins`
- **THEN** it installs exactly the core, plugins, and serialwrap versions pinned in `install-manifest.yaml`

#### Scenario: Incompatible pin fails CI
- **WHEN** a manifest change pins a plugin whose `api_version` is incompatible with the pinned core `API_VERSION`
- **THEN** the manifest compatibility gate fails the change before it can be released

### Requirement: Core distribution is testpilot-core and is never resolved from public PyPI
The core distribution SHALL be named `testpilot-core` (its import package remains `testpilot`), and plugins SHALL declare their dependency on `testpilot-core`. Every install path SHALL avoid resolving the core from a public index: the online path SHALL install the core wheel first and then plugin wheels with `--no-deps`, and the offline path SHALL use `--no-index`. No install path SHALL satisfy `testpilot`/`testpilot-core` from public PyPI.

#### Scenario: Online plugin install does not touch PyPI for core
- **WHEN** the online installer installs a plugin wheel after the core wheel
- **THEN** it uses `--no-deps` so pip does not query PyPI to satisfy `testpilot-core`, and the install succeeds without network access to any public index for the core

### Requirement: Installer migrates pre-existing install shapes
On a machine with a prior TestPilot install, the installer SHALL detect and reconcile legacy shapes — a `pip install --user testpilot`, a pipx install, and a legacy `~/.local/share/testpilot/src` checkout — by uninstalling/repointing them so the managed virtualenv wrapper is authoritative, and SHALL warn when a `testpilot` import resolves outside the managed virtualenv after migration.

#### Scenario: Migrate a user-site install
- **WHEN** the installer runs on a machine where `testpilot` was previously installed via `pip install --user`
- **THEN** it reconciles the user-site install (uninstall/repoint), installs the managed wheel model, and `--verify-install` does not report a competing out-of-venv `testpilot`

## REMOVED Requirements

### Requirement: Managed installer creates checkout, venv, wrapper, skills, and serialwrap
**Reason**: P4 物理拆分後 plugin 不再內嵌於 core checkout；安裝模型改為 manifest-pinned 的 managed-venv + wheel，不再維護 `~/.local/share/testpilot/src` 原始碼 checkout，也不再 editable-install `plugins/<name>`（這正是壞掉的步驟）。
**Migration**: 由「Managed installer installs pinned wheels into a managed venv」取代——venv/wrapper/skill/serialwrap 仍建立，但 core/plugin/serialwrap 改以 wheel 安裝、來源由 `install-manifest.yaml` pin，private wheel 經 `gh release download` 取得。

### Requirement: Top-level update refreshes the managed checkout
**Reason**: `--update` 原本要求 `~/.local/share/testpilot/src/.git` 存在並 git fetch/checkout；wheel 模型沒有 src checkout，原需求在新模型下恆為失敗。
**Migration**: 由「Top-level update reinstalls pinned wheels and reconciles the plugin set」取代——`--update` 改為 re-resolve manifest、重裝 pinned wheel、reconcile 掉非 manifest 的 plugin，並保留更新前快照供回復。

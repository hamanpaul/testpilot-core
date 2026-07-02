## MODIFIED Requirements

### Requirement: Managed installer installs pinned wheels into a managed venv
The installer SHALL create or update a runtime virtualenv under `~/.local/share/testpilot/.venv`. For the core and each selected plugin it SHALL install the **newest release that is API-compatible with the installed core** `API_VERSION` under the `PluginLoader` rule — resolving and installing the core first, then resolving each plugin against the installed core — and it SHALL determine a candidate release's `api_version` **before** committing that release to the managed virtualenv (staging / release metadata probe), so a resolution never mutates the managed venv into a broken state. It SHALL install the **serialwrap version pinned in `install-manifest.yaml`** (serialwrap is not flow-latest). If no API-compatible release exists for a required component, the installer SHALL abort with a clear message naming the component, the candidate `api_version`(s), and the core `API_VERSION`, and SHALL leave any pre-existing working install intact. It SHALL expose `~/.local/bin/testpilot` as a wrapper that executes the managed virtualenv's console script with no activation, and sync the packaged `testpilot-normal-test` skill into `~/.agents/skills/testpilot-normal-test`. It SHALL NOT create or depend on a `~/.local/share/testpilot/src` source checkout. Private wheels SHALL be fetched with `gh release download` using a token provided only via the `GH_TOKEN`/`TESTPILOT_INSTALL_TOKEN` environment, never embedded in a URL or printed. `--plugins <name[,name...]>` SHALL select a subset; `--plugins <name>@<version>` SHALL pin a component to an exact version (bypassing latest-compatible resolution); the default SHALL install the manifest's full component set. The installer SHALL run `testpilot --verify-install` as a post-install gate on **both** the online and offline paths and SHALL fail the install when the gate fails.

#### Scenario: Online install of the latest-compatible set
- **WHEN** the installer runs on a networked machine with a valid `TESTPILOT_INSTALL_TOKEN` and no `--plugins`
- **THEN** it creates the managed venv, installs the newest API-compatible core + all plugins plus the manifest-pinned serialwrap as wheels, writes the wrapper, syncs the skill, and `testpilot --verify-install` passes

#### Scenario: Online path runs the post-install verify gate
- **WHEN** the online install path finishes installing all components
- **THEN** it runs `testpilot --verify-install` before reporting success and exits non-zero if the gate fails, exactly as the offline path does

#### Scenario: No compatible release aborts without mutating a working install
- **WHEN** a required plugin has no release whose declared `api_version` is compatible with the installed core `API_VERSION`
- **THEN** the installer aborts with a clear message and does not partially install or remove components from a pre-existing working managed venv

#### Scenario: Subset install
- **WHEN** the installer runs with `--plugins wifi_llapi`
- **THEN** only core, the `wifi_llapi` plugin, and serialwrap are installed, and `testpilot list-plugins` shows exactly `wifi_llapi`

#### Scenario: Explicit version pin bypasses resolution
- **WHEN** the installer runs with `--plugins wifi_llapi@0.3.1`
- **THEN** it installs exactly `wifi_llapi` `0.3.1` instead of resolving the newest compatible release

#### Scenario: Token never leaks
- **WHEN** the installer fetches private wheels
- **THEN** the token is passed only via environment to `gh`, and never appears in process arguments, the wrapper, stdout/stderr, or any log

### Requirement: Top-level update reinstalls pinned wheels and reconciles the plugin set
`testpilot --update [REF]` SHALL run before normal Click dispatch, resolve the install manifest shipped with the installed core, reinstall core and plugins to their **newest API-compatible releases** and serialwrap to its **manifest-pinned version** into the managed virtualenv (delegating to the packaged installer, never resolving private components from public PyPI), and reconcile the virtualenv to exactly the manifest's component set by uninstalling any installed `testpilot.plugins` distribution not in the manifest. If the manifest cannot be resolved, or if a required component has no API-compatible release, it SHALL exit non-zero WITHOUT modifying the installation (never treat an unresolved manifest as "uninstall everything", and never brick a working install to chase latest). It SHALL capture a pre-update snapshot (e.g. `pip freeze`) before changing the environment, and on post-update `--verify-install` failure SHALL restore the previous set. `REF` is accepted and forwarded for forward-compatibility; fetching a different ref's manifest for cross-version update is a tracked follow-up (a runtime notice is emitted for a non-default `REF`).

#### Scenario: Update reinstalls newest-compatible wheels
- **WHEN** user runs `testpilot --update` after a new plugin release
- **THEN** the managed venv is reinstalled to the newest API-compatible core + plugins and the pinned serialwrap, and `testpilot --verify-install` passes

#### Scenario: Dropped plugin is reconciled away
- **WHEN** a plugin present in the venv is no longer in the resolved manifest and user runs `testpilot --update`
- **THEN** that plugin distribution is uninstalled so no orphaned `testpilot.plugins` entry point remains, and the CLI does not raise a duplicate/incompatible-entry-point error

#### Scenario: No compatible release leaves the working install intact
- **WHEN** `testpilot --update` runs but a required component has no API-compatible release
- **THEN** it exits non-zero and leaves the previously working managed venv unchanged

### Requirement: Install manifest pins the compatible component set
An `install-manifest.yaml` in core SHALL be the single source of truth for the managed install, declaring the core and each plugin (name, source repo, required `api_version`) and serialwrap, and marking each component public/private with its auth requirement. The `version:` field SHALL be **optional for core and plugins** — when absent, the installer and bundle builder resolve the newest API-compatible release; when present, it pins that component — and SHALL be **required for serialwrap** (serialwrap is always pinned). CI SHALL validate, for each plugin, that the declared `api_version` is compatible with the core's `API_VERSION` under the `PluginLoader` rule, and SHALL fail the manifest change when any declared pair is incompatible. Operators MAY override a single component with `--plugins <name>@<version>`.

#### Scenario: Manifest with no core/plugin version drives latest-compatible install
- **WHEN** the installer runs with no `--plugins` and the manifest declares no `version:` for core or plugins
- **THEN** it installs the newest API-compatible core and plugins, plus the manifest-pinned serialwrap version

#### Scenario: Serialwrap pin is honored
- **WHEN** the installer resolves components
- **THEN** serialwrap is installed at exactly the manifest-pinned `version:` and is never resolved to latest

#### Scenario: Incompatible declared api_version fails CI
- **WHEN** a manifest change declares a plugin whose `api_version` is incompatible with the core `API_VERSION`
- **THEN** the manifest compatibility gate fails the change before it can be released

#### Scenario: Explicit override pins a single component
- **WHEN** the installer runs with `--plugins wifi_llapi@0.3.1`
- **THEN** `wifi_llapi` is installed at `0.3.1` regardless of the newest compatible release

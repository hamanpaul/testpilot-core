# Changelog

All notable changes to this project are documented in this file.

TestPilot follows Semantic Versioning (`vX.Y.Z`). GitHub Releases publish the
auto-generated release notes for each tag, while this file keeps the curated
repo changelog and the `Unreleased` queue that must be finalized during release
preparation.

## [Unreleased]

### Added

- `install-manifest.yaml` with pinned core, plugin, and serialwrap versions for manifest-driven managed installs.
- `testpilot install-doctor` CLI command: checks manifest plugin API-compat against the installed core SDK version (`testpilot.api.API_VERSION`); exits non-zero on incompatibility.
- Online one-click managed-venv wheel install via `scripts/install.sh` with `TESTPILOT_INSTALL_TOKEN` (downloads pinned wheels via `gh release download`); subset install via `--plugins`.
- Offline bundle install via `scripts/install.sh --offline <bundle.tar.gz>`; bundle built by `scripts/build-bundle.sh` on a networked Linux box; verifies `SHA256SUMS`, installs with `--no-index`.
- Wheel-mode `--verify-install`: reports managed venv health and wheel-installed package versions.
- Wheel-world `--update`: re-resolves manifest, reinstalls pinned wheels, reconciles plugins.
- Legacy-install migration detection: warns when a `~/.local/share/testpilot/src` git-checkout install is detected and guides migration to the wheel model.
- Skill `testpilot-normal-test` shipped as wheel data under `testpilot/_skills/testpilot-normal-test` (via `pyproject.toml` `force-include`).
- CI: wheel build (`uv build --wheel`) and upload to GitHub Release asset after tag-triggered release creation.
- CI: manifest API-compatibility gate (`testpilot install-doctor --manifest install-manifest.yaml`) and offline bundle smoke test in the PR/push workflow.
- `tests/test_wheel_contents.py`: wheel-content assertion locking that the skill is present and no runtime report bundle dirs leak into the wheel.

### Fixed

- **`--verify-install` version-mirror check now understands dynamic versions.**
  `pyproject.toml` uses `dynamic = ["version"]` (sourced from the `VERSION`
  file via `[tool.hatch.version]`), but `_check_version_mirrors()` still read
  `data["project"]["version"]` and surfaced a spurious
  `pyproject.toml unreadable: 'version'` FAIL in checkout-mode verify-install.
  It now reads the hatch version path (mirroring
  `tests/test_version_metadata.py` / `scripts/check_release_version.py`) when
  the version is dynamic.
- **CRITICAL: `testpilot --update` no longer destroys a real wheel install.** The
  authoritative `install-manifest.yaml` and `install.sh` now ship inside the
  wheel (`testpilot/_install/`), so `_resolve_manifest()` resolves them in a
  real install instead of returning an empty set that made the reconcile loop
  `pip uninstall` every plugin. An unresolvable manifest now exits nonzero
  WITHOUT touching the installation.
- **`--update` reinstall no longer hits public PyPI for private plugins.** The
  pinned set is reinstalled by delegating to the packaged `install.sh` (via an
  injectable seam, passing `TESTPILOT_REF` and `TESTPILOT_MANIFEST`) instead of
  `pip install --upgrade <bare-name>` (dependency-confusion risk). Dropped
  plugins are still reconciled via the pip runner.
- `--update` snapshots the environment (`.last-good.txt`) and gates on
  wheel-mode `--verify-install`; on verify failure it restores from the
  snapshot and exits nonzero. `REF` is accepted and forwarded as
  `TESTPILOT_REF`, but cross-version update is not yet implemented — the
  currently-pinned manifest set is reinstalled regardless of `REF` (a runtime
  notice is printed for a non-default `REF`). Fetching a new ref's manifest is
  a tracked follow-up.
- Legacy-install migration is now wired in (previously dead code): a hidden
  `testpilot install-migrate` command runs the detect/probe pair and removes
  legacy user-site / pipx / `~/.local/share/testpilot/src` checkouts via an
  injectable runner; `scripts/install.sh` invokes it (best-effort) after the
  managed venv is populated, in both online and offline modes.
- Wheel-mode stray-import detection now uses a non-managed interpreter
  (`_system_python_outside`) instead of the managed venv python, so it can
  actually detect a `testpilot` importable outside the managed venv.
- `scripts/install.sh` online mode now installs serialwrap WITH its dependency
  closure (it is public and does not depend on testpilot-core); only core and
  plugins keep the `--no-deps` path. The install helper's flag is renamed
  `is_core` → `with_deps` for clarity and the git+https fallback honors it too.
- `scripts/install.sh` GIT_ASKPASS hardening: the askpass helper now reads the
  token from the exported env at call time (`exec printf '%s\n' "$GH_TOKEN"`)
  instead of embedding the literal secret, and its cleanup is registered in the
  EXIT trap so it is removed even when `pip` fails under `set -euo pipefail`
  (a function-scoped RETURN trap does not fire on a `set -e` abort).

### Changed

- `--update` help text updated to describe the wheel-model reconcile (was stale
  "managed checkout" wording); README CLI-help marker blocks regenerated to
  match.
- Wheel-mode `--verify-install` now reports a failing plugin with its captured
  error TYPE (e.g. `failed to load (ImportError)`); only an actual
  `IncompatiblePluginError` is reported as `api-incompatible`.

### Changed — BREAKING

- **Distribution renamed `testpilot` → `testpilot-core`** (`pip install testpilot-core`); the import package `testpilot` is unchanged.
- Managed install model changed from git-checkout + editable source to wheel-based venv; `~/.local/share/testpilot/src` is no longer created or used.

## [0.3.0]

- **CI 可重現性 + 鎖定 click 渲染**: `uv.lock` 改為版控（移出 `.gitignore`），CI
  `test` job 改用 `uv sync --extra dev --locked` 從 lock 安裝（plugin 以
  `--no-deps` editable 疊加），消除 fresh-resolve 的相依漂移；並把 `click` 釘為
  `>=8.1,<8.4`。修正 click 8.4 對 `invoke_without_command` group 的
  `Usage: ... [COMMAND] ...` 渲染變更，使 README CLI-help marker（R-16）在 CI
  漂移失敗（`scripts/policy_cli_help.sh` 走獨立 pip 安裝、無法吃 lock，故需
  pyproject 釘版才能涵蓋 external-policy 路徑）。
- **wifi_llapi SAE baseline workaround（BGW720-0410 image / driver commit `00c7a198e8`）**:
  該 image 上 5G/2.4G 的 WPA2-PSK 4-way handshake 已壞（AP 在 association 後
  deauth STA `reason=1`），且 pwhm runtime reconfig 不會把 security apply 進
  driver（手動繞過 pwhm 直接改 hapd.conf + restart hostapd 才生效）。6G 因走
  SAE + 6GHz 強制 H2E 不受影響。將 `band-baselines.yaml` 的 5g/2.4g profile 從
  WPA2-Personal 改為 WPA3-Personal/SAE：`dut_runtime_config` 改 sed hapd.conf 成
  `wpa_key_mgmt=SAE` / `ieee80211w=2` / `sae_pwe=2`（必填，避免 DUT H2E-only 與
  STA hunting-and-pecking 撞牆）/ `ieee80211be=0`、移除第二 BSS；`sta_network_config`
  改 SAE + `sae_pwe=2`；移除 5g 的 `sta_driver_join_command`（WPA2 專屬 fallback）。
  經 `baseline-qualify` live 驗證三頻 COMPLETED+stable。**此為 image-specific
  workaround，image 修復（revert `00c7a198e8`）後應回退 5G/2.4G 為 WPA2-Personal**
  （見 Default Lab Baseline Policy）。
- **Sync policy 1.0.5**: bump `policy_version` 1.0.4 → 1.0.5 across `.project-policy.yml` and the four synchronized agent instruction files; repin the external policy engine SHA to `hamanpaul/paulsha-conventions@484f963adddf384d30fa0dd85aef35dddf822ee7` across `.project-policy.yml` `workflow_ref`, `.github/workflows/policy-check.yml`, and `.github/workflows/release.yml`; replace the old pointer-mode agent files with the 1.0.5 four-file synchronized payload (managed checklist + TestPilot project-specific content, all four byte-identical); update `tests/test_release_governance.py` for the new synchronized-mode assertions.
- **Tier B brcm core 解耦 (#89)**: 將 schema validation primitive 公開化並
  re-export 到 `testpilot.api`，讓 `wifi_llapi` 清掉 schema helper allow-list；
  `brcm_fw_upgrade` 的 profile/topology/case validation 搬入 plugin 專屬模組，
  production 匯入改為 only-api，並把 plugin boundary 守門擴大到所有 production
  plugins。code review 後續修正：因新增公開驗證面，SDK 契約 `API_VERSION`
  1.0→1.1、`wifi_llapi`/`brcm_fw_upgrade` 的 `api_version` 同步 1.1（讓「需要新
  helper 的 plugin 對只提供 1.0 的舊 core」得到受控 `IncompatiblePluginError`
  而非 runtime `ImportError`）；邊界守門強化動態 import 偵測（解析常數變數 /
  `import_module as X` alias / 常數串接，堵掉繞過字面字串檢查的 evasion）。
- **P4 物理切分 prep（in-monorepo, Task 1–5）**: 把 `audit` 折入 `wifi_llapi`
  plugin、wifi production 收斂為只依賴 `testpilot.api`（公開面新增
  `run_one_case` / `case_d_number` / `create_transport` / `RunBackend` /
  `RunHandle` / `ExportRequest` / `ExportResult`）、root `pyproject.toml`
  收斂 core-only、`wifi_llapi` 與 `brcm_fw_upgrade` 改為獨立 dist 經
  `entry_points` 發現，並以 replay `RunBackend` 接回
  `test_audit_runner_facade`（合成 fixture，待真 testbed 重錄）。code review
  後續修正：wifi transport 改走 `testpilot.api.create_transport`（移除動態
  import `testpilot.transport.factory` 破口、邊界守門擴及動態 import）、受管
  installer 與 CI 同步安裝/測試獨立 plugin dist、`run_one_case` 加 `run_backend`
  注入 hook 讓 audit 單-case 可 replay。依 governance(R-07),feature PR 維持
  `VERSION` = 最新 tag `0.2.1`、變更累積於 `[Unreleased]`;**下一個 release 目標
  為 0.3.0**(minor——0.x 慣例下 minor 即「破壞性/重大」:新增公開 api 面 +
  `testpilot.audit`→`wifi_llapi.audit`、plugin import 名與安裝語意變更;patch 會
  誤導 caret 範圍消費者),於 release 步驟落地。物理 repo 切分(Task 6–9)另案處理。
- **Versioned plugin contract**: add `testpilot.api.API_VERSION` as the plugin
  SDK contract version, require plugin `api_version` declarations, and make
  `PluginLoader.load()` reject undeclared or incompatible plugins with
  `IncompatiblePluginError` before plugin instantiation; `load_all()` now
  propagates incompatible-plugin failures instead of hiding them.
- **CLI register_cli 解耦**: 新增中性 `cli_support` / `CliRegistrar`，讓
  plugin 透過 `register_cli(registrar)` 掛載自己的 Click 命令與群組；
  `src/testpilot/cli.py` 對 `wifi_llapi` / `wifi-llapi` / `brcm` 零具名，
  並保留 `testpilot wifi_llapi`、`testpilot wifi-llapi <sub>`、
  `testpilot brcm-fw-upgrade run` 與 `testpilot run` help UX。
- **core ⊥ wifi_llapi 解耦**: report / validate / execution 改走 `PluginBase`
  hook——`create_reporter()`（報表）、`validate_case()`（驗證）、
  `execution_policy()`（執行約束）。`yaml_command_audit`、case 驗證
  (`validate_wifi_llapi_case`)、band baseline 與 official/D### case helper 全部
  搬入 `plugins/wifi_llapi/`，`src/testpilot/{core,schema,reporting}` 對 plugin
  零具名（`wifi_llapi` grep 為空），由新增的
  `tests/test_core_has_no_plugin_names.py` 守門。
- **Sync policy 1.0.4**: bump `policy_version` 1.0.3 → 1.0.4 (`.project-policy.yml` + four agent instruction files); repin the external policy engine SHA to `hamanpaul/paulsha-conventions@77a3e8381eeced9dbba623e450ed6a5c1fcc7b18` (v1.0.4 packages the R-21 secret-scan baseline data into the install, fixing the empty `exit 1` external-policy failure where v1.0.3 could not load its baseline) across `.project-policy.yml` `workflow_ref`, `policy-check.yml`, and `release.yml`; update `tests/test_release_governance.py` expected `policy_version` accordingly.
- **Sync policy 1.0.3**: bump `policy_version` 1.0.1 → 1.0.3 (`.project-policy.yml` + four agent instruction files) and add `tier: work`; repin the external policy engine SHA to `hamanpaul/paulsha-conventions@614caf23f6514d865cb43e77b53837a273b0b07f` (includes R-19 / R-20 / R-21) across `.project-policy.yml` `workflow_ref`, `policy-check.yml`, and `release.yml`; update `tests/test_release_governance.py` expected `policy_version` accordingly.
- **Sync policy 1.0.1**: bump `policy_version` 1.0.0 → 1.0.1 (`.project-policy.yml` + four agent instruction files); repin the external policy engine SHA to `hamanpaul/paulsha-conventions@4ff59b6c35a46a87af3c3e641975743ee8fa0858` (includes R-17 / R-18) across `.project-policy.yml` `workflow_ref`, `policy-check.yml`, and `release.yml`; update `tests/test_release_governance.py` expected `policy_version` accordingly.
- `wifi_llapi` env recovery now reloads custom DUT AP profiles before STA link
  checks, retries safe STA reconnect paths, and prefers `wld_gen` stack reload
  before AP bounce so env-fail cases can reach the test body instead of stalling
  in `setup_env` / `verify_env`.
- `wifi_llapi` custom AP-only setup now recovers transient DUT `wl bss` down
  checks by reloading the affected AP profile before failing `sta_env_setup`.
- `wifi_llapi` normal runtime now preserves a template-owned Excel `Summary`
  sheet and only synthesizes a fallback Summary when the workbook lacks one,
  so existing styles, merged cells, formulas, and number formats are retained.
- **release-flow 對齊強制政策**: `docs/release-flow.md` 的 release PR 分支由
  `release/vX.Y.Z` 改為 `feature/<slug>`（對齊 R-12），PR 標題範例改為
  `chore(release): prepare vX.Y.Z`（對齊 R-10），並註明 release PR 需掛
  `release:vX.Y.Z` 標籤讓 VERSION 領先 tag 通過 R-07。

## [0.2.1]

### Changed

- The canonical project version is now `VERSION`; `pyproject.toml` and
  `src/testpilot/__init__.py` are mirrors validated by tests and release CI.
- Wave 3 `wifi_llapi` getRadioStats traffic cases `D263-D266` and `D271-D276`
  now use multiband delta contracts backed by source-aligned radio driver
  formulas, including deterministic broadcast/multicast triggers and the
  D336-aligned `D276` unicast-sent extractor.
- `wifi-llapi reproject-summary` now preserves the styled template `Summary`
  sheet and relies on its formulas to calculate from `Wifi_LLAPI` report data.
- The `wifi_llapi` Excel `Summary` sheet now counts `Fail` from hidden
  projected summary buckets, so environment/setup/counter-zero failures remain
  outside the pass-criteria failure count.
- The `wifi_llapi` Excel `Summary` bucket formerly shown as `To be tested` is
  now shown as `To be confirmed`, and Summary Pass Rate formulas divide by
  `Pass + Fail` only.
- Reprojected wifi_llapi HTML and Markdown reports now retain the top-level
  suite KPI counts while also using the template-aligned Summary bucket data.
- Reprojected wifi_llapi reports now align text-report KPI totals to the current
  official `plugins/wifi_llapi/cases/D*.yaml` inventory, excluding stale cases
  that only exist in older source JSON bundles.

### Added

- Managed installer, `testpilot --update`, and `testpilot --verify-install`
  support for QC/TEST deployments with managed TestPilot, skill, and
  serialwrap assets.
- `testpilot wifi_llapi` primary run command for normal wifi_llapi operation,
  while preserving `testpilot run wifi_llapi` compatibility.
- Release governance checks for `VERSION` canonicality, README CLI help sync
  markers, `.project-policy.yml`, and release workflow validation.
- `testpilot audit` CLI subcommand group (`init`, `pass12`, `record`,
  `verify-edit`, `decide`, `status`, `summary`, `apply`, `pr`) that separates
  workbook-driven audit work from normal `testpilot run` execution.
- Gitignored `audit/` workspace for RID-scoped workbook snapshots, buckets,
  verify-edit logs, and case-level evidence artifacts.
- `scripts/check_audit_yaml_provenance.py` plus `.pre-commit-config.yaml` to
  enforce that `plugins/<plugin>/cases/D*.yaml` changes map back to a
  `verify_edit_log.jsonl` entry unless `[audit-bypass: <reason>]` is used.
- `docs/audit-guide.md` rewritten as the audit-mode agent doctrine.
- `testpilot run wifi_llapi` now performs a runtime alignment phase that
  auto-corrects case filename `D###`, `source.row`, and compatible `id` values
  against the checked-in template workbook before execution.
- wifi_llapi artifact bundles may now include `blocked_cases.md` and
  `skipped_cases.md` when metadata drift cannot be safely auto-aligned.
- Ambiguous `(source.object, source.api)` template families are now blocked
  instead of auto-aligned, and both `blocked_cases.md` plus
  `meta.alignment_summary.blocked_details` expose the candidate template rows to
  clean up later.

### Changed - BREAKING

- `testpilot run wifi_llapi` no longer accepts `--report-source-xlsx`; rebuild the checked-in template with `testpilot wifi-llapi build-template-report --source-xlsx <path>` before running if the template needs refreshing.

### Removed - BREAKING

- `plugins/wifi_llapi/cases/` no longer carries `results_reference`, `source.baseline`,
  `source.report`, or `source.sheet`; wifi_llapi report values now reflect runtime
  verdicts instead of workbook-derived oracle metadata.
- `testpilot.core.case_utils.baseline_results_reference()` has been removed;
  `case_band_results()` now projects per-band results from runtime verdict plus
  `case.bands` only.

## [0.2.0]

### Added

- Per-run wifi_llapi artifact bundles under `plugins/wifi_llapi/reports/<artifact_name>/`
  that keep xlsx, markdown, json, UART logs, trace output, and optional
  alignment warnings together.
- Local HTML diagnostic report generation from existing JSON run artifacts,
  including Arcadyan-styled case details.
- GitHub-native release management scaffolding: PR template checklist, CI
  workflow, tag-triggered release publishing, and release process
  documentation.

### Changed

- Report and template handling now use portable manifest paths and aligned repo
  documentation for the current autopilot / reporting architecture.
- Local workbook / compare outputs and one-off campaign notes are now treated as
  local-only artifacts instead of versioned repo content.
- Version metadata is now promoted from the historical `v0.1.5` baseline to the
  release target `v0.2.0`.

### Fixed

- Markdown reports now include the full statistics block expected by downstream
  review flows.
- HTML case details now render referenced DUT / STA log snippets with readable
  truncation for large ranges.
- 6G DUT runtime cleanup now preserves non-ASCII output safely during case
  execution.

## [0.1.5]

### Note

- Historical baseline release that predates formal changelog maintenance in
  this repository. Future curated changelog entries build forward from this
  tag.

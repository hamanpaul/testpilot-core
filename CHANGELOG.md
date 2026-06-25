# Changelog

All notable changes to this project are documented in this file.

TestPilot follows Semantic Versioning (`vX.Y.Z`). GitHub Releases publish the
auto-generated release notes for each tag, while this file keeps the curated
repo changelog and the `Unreleased` queue that must be finalized during release
preparation.

## [Unreleased]

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

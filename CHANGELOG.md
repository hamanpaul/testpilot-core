# Changelog

All notable changes to this project are documented in this file.

TestPilot follows Semantic Versioning (`vX.Y.Z`). GitHub Releases publish the
auto-generated release notes for each tag, while this file keeps the curated
repo changelog and the `Unreleased` queue that must be finalized during release
preparation.

## [Unreleased]

## [0.3.6] - 2026-08-07

### Added
- `testpilot <PLUGIN_PATH>` 可直接執行磁碟上的 plugin 專案，不需先安裝進 registry（#30）。
  
  ## 兩種 invocation 形式
  
  | 形式 | 解析方式 |
  |---|---|
  | `testpilot <PLUGIN_NAME> [ARGS]...` | registry mode——已安裝的 `testpilot.plugins` entry point（既有行為，未變） |
  | `testpilot <PLUGIN_PATH> [ARGS]...` | path mode——磁碟上的 plugin 專案根目錄（新增） |
  
  `PLUGIN_PATH` 指專案根目錄（含 `pyproject.toml` 那層）。專案自己的
  `[project.entry-points."testpilot.plugins"]` 表是 plugin 名稱與 import 目標的唯一真實來源，
  因此兩種模式對 plugin 身分的認定一致，只有解析路徑不同。
  
  ## 完整 parity，而非另一條簡化路徑
  
  path mode 跑的是 plugin **自己** 透過 `register_cli` 註冊的 command，因此
  `testpilot /path/to/p --flag` 與 `testpilot p --flag` 行為完全一致，plugin 專屬選項照常可用。
  plugin 未註冊同名 command 時才退回核心 run 路徑。
  
  這需要一個 loader 層的名稱 override：plugin 自有 command 內部會以**名稱**重新解析自己
  （`get_orchestrator(ctx, name)` → `load_registered_plugin(name)`，且 `Orchestrator` 自建
  一個新的 `PluginLoader`）。沒有 override 的話，path mode 會在乾淨環境直接找不到 plugin，
  或在有安裝的環境**靜默跑到已安裝的那份**——後者比不支援還糟。`PluginLoader.register_override`
  讓所有 loader 實例對「這個名字是誰」取得一致答案。
  
  ## 「跑到路徑那份」的保證
  
  僅把專案路徑前插 `sys.path` 並不夠：同名發行版若已被 import，其 top-level package 已在
  `sys.modules`，`import_module` 會直接回快取的那份。因此 path mode 會先驅逐不屬於本專案的
  同名 top-level module，再 import，並**驗證載入結果確實位於專案根目錄之下**；驗證不過就
  拒絕執行，而不是靜默測到錯的樹。
  
  ## Fail-closed 行為
  
  - 路徑不存在 / 不是目錄 / 缺 `pyproject.toml` / 沒有 `testpilot.plugins` entry point：各自給出明確訊息。
  - 專案宣告多個 plugin：**拒絕而不猜測**，並列出候選名稱，建議改為安裝後以名稱選取。
  - entry point 值格式錯誤、屬性不存在、不是 `PluginBase` 子類：明確拒絕。
  - path mode **不繞過** SDK API 版本閘，與 registry mode 共用同一個 `_check_api_compat`。
  - 已註冊的 plugin 名稱永遠優先於同名資料夾，path mode 不可能遮蔽已安裝的 plugin。
  
  ## 實作
  
  - 新增 `testpilot/core/plugin_project.py`：路徑解析、pyproject entry-point 讀取、
    專案優先 import 與位置驗證、plugin 實例化。
  - `testpilot/core/plugin_loader.py`：新增 class 層級的名稱 override（`register_override` /
    `clear_overrides`），`load()` 優先查詢。
  - `testpilot/cli.py`：`main` 改用 `PluginPathGroup`，`resolve_command` 在第一個 token 不是
    已註冊命令、且看起來像路徑時走 path mode。判定條件保守：含路徑分隔符、以 `.`／`~` 開頭、
    或該名稱確實是既有目錄。實作維持 plugin 零具名（`tests/test_cli_plugin_registration.py` 守門）。
    override 以 `ctx.call_on_close` 綁在 click context 生命週期上，指令結束（成功或失敗）即清除——
    process-wide 的 override 若殘留，之後對同名的解析會拿到上一輪的過期實例。
  
  ## 測試與文件
  
  新增 `tests/test_cli_plugin_path_mode.py`（14 個測試），含「同 package 名、已安裝那份已進
  `sys.modules`」的碰撞情境——這正是不做 module 驅逐就會靜默跑錯樹的那一條。另有 registry mode
  未回歸、相對路徑、四種 fail-closed 錯誤與 help 內容的覆蓋。
  
  README（en/zh 兩段）新增兩種形式的對照表與 path mode 細節；`docs/plugin-dev-guide.md` 補上
  「開發期免安裝跑法」；R-16 的 `testpilot-help` / `testpilot-update-help` marker 區塊已重生。

### Changed
- 升級 hamanpaul project policy 至 v1.0.15，並完成 R-21 減敏。
  
  ## 版本升級
  
  - `policy_version` 1.0.12 → 1.0.15（`.project-policy.yml` 與四份 agent convention 檔）。
  - `workflow_ref` / `policy_engine_ref` 雙 pin 換為 v1.0.15 的
    `a764806046c410eb4f254ac0b6a8aec8b7559dab`（`policy-check.yml` 與 `release.yml` 兩支）。
  - 新增 `.project-policy.yml` 的 `preflight.steps`（v1.0.13 的 canonical `preflight-ci`
    skill 需要）。
  - `tests/test_release_governance.py` 中寫死的 policy_version 斷言同步更新。
  
  ## R-21 減敏（本 repo 為 public，v1.0.13 起依 visibility + tier 判定命中等級）
  
  升級後 R-21 由「不適用」變為實際生效並命中 `structural:23 / marker:110`
  （marker baseline 為少數雇主／內部代號 token；常見 vendor 名稱屬 `public_names` 不列入）。
  分三類處理：
  
  **刪除拆分殘留**
  - `docs/COMPREHENSIVE_AUDIT_GUIDE.md`、`docs/AUDIT_GUIDE_INDEX.md`、
    `docs/audit-guide.md.legacy.bak`：pre-audit-mode 舊流程文件，audit doctrine 已由
    `wifi_llapi` 承接。
  - `docs/audit-todo.md`、`docs/wifi-baseline-exp.md`：core/plugin 拆分前的舊快照，
    現行版本由 `wifi_llapi` 維護。
  - `full_diff.patch`：293KB，於 `60d10c0` 誤 commit 的殘留產物。
  - 四份 agent 檔的 `Calibration Continuation Policy` 與 `Default Lab Baseline Policy`
    兩節：屬 plugin 的操作規範（逐案校正流程、實驗室 baseline 與 image-specific
    workaround），拆分後由 plugin repo 維護；已替換為指向說明。
  
  **live code 減敏**
  - `src/testpilot/cli_support.py`：`run` 子指令的 help 範例中 `--dut-fw-ver` 的裝置型號
    改為通用佔位值（README 的 cli-help 區塊為頂層 `--help`，不含此行，R-16 不受影響）。
  - `tests/test_serialwrap_binary.py` / `tests/test_verify_install_wheel_mode.py`：
    fixture 中的 `/home/<user>/...` 個人路徑改為 `/opt/...`（structural 偵測針對
    `/home/*/`，換成其他使用者名仍會命中，故改用非 `/home` 路徑）。
  
  **歷史紀錄以 allow-list 標示**
  - `secret_scan.allow` 納入 `docs/superpowers/**`、`openspec/changes/archive/**`、
    `CHANGELOG.md`。這些是當時決策的歷史紀錄，改寫等同竄改；allow-list 為 policy
    對「合法引用」設計的機制。live code 與現行 docs 皆已實際減敏，不在此清單內。
  
  減敏後 `policy_check`（1.0.15 engine + PR context + `--repo-visibility public`）
  為 pass 24 / fail 0，**未使用任何 `policy-exempt:*` 豁免 label**。
  
  ## 未納入的 gate 與已知既有問題（揭露，非本 PR 造成）
  
  - `preflight.steps` 只宣告 `tests`，**暫不宣告 openspec gate**：本 repo 現有 4 個 spec
    （`audit-mode`、`plugin-entry-points-discovery`、`plugin-runner-reporter-separation`、
    `wifi-llapi-alignment-guardrails`）缺 `#### Scenario:` 區塊而驗證失敗，於未修改的
    `main` 上結果相同（17 passed / 4 failed）。補齊後再加回。
  - `tests/test_installer.py::TestOfflineInstall::test_offline_creates_wrapper` 在本機失敗，
    同樣早於本 PR（未修改 main 上一致失敗、`main` CI 為綠）。根因為安裝腳本比對 bundle
    的 `cp311` 標籤與執行中 python 版本標籤，本機為 Python 3.12 且無 `python3.11`。
  - `.gitignore` 的 `.venv/` 改為 `.venv`：帶斜線的 pattern 只匹配目錄，把 `.venv` 做成
    共用 venv 的 symlink 時不會被忽略，會污染 `git status` 並使 policy gate 打包時拋
    `AbsoluteLinkError`。
  
  ## changelog fragment 修正（含一項既有缺陷）
  
  `docs/release-flow.md` 明定 `chore` **不是**合法 fragment type（合法值：`change` /
  `deprecate` / `feat` / `fix` / `perf` / `refactor` / `remove` / `security`），
  `policy_check.changelog collate` 會直接拋 `FragmentError` 拒絕執行、擋住整個 release：
  
  - 本 fragment 原用 `type: chore`，已改為 `change`（本 PR 引入，已修正）。
  - `changelog.d/serialwrap-pin-0-2-4.md` **完全沒有 YAML frontmatter**（直接以
    `### Changed` 開頭），為**早於本 PR 的既有缺陷**——代表 collate 在本 PR 之前就已經
    失敗、release 路徑已被擋住。已補上 `type: change` / `scope: install` frontmatter，
    內容維持原樣。修正後實測 `collate` 通過。
  
  另本 fragment 原文為說明減敏而直接寫出 marker token 與被替換掉的裝置型號字串，而
  `changelog.d/**` 不在 `secret_scan.allow` 內；fragment 於 release 時會被 collate 進
  `CHANGELOG.md`，等同在 release notes 重新命中。已改為不揭露具體 token 的描述。
- - managed-install serialwrap pin 由 `0.2.1` 提升至 `0.2.4`（`install-manifest.yaml`）。0.2.1→0.2.4 涵蓋 serialwrap `v0.2.2`~`v0.2.4`（174 commits）：daemon 暴露命令長度上限 `limits`（serialwrap#129）、arbiter recovery 佇列 flush（#128）、autoboot 倒數窗 recovery lease（#114/#140）、realhw 穩定性測試套件、Windows 原生 daemon 與 ssh 反向隧道 CLI。serialwrap 無 SDK API 契約，故維持顯式 `version:` pin，本次為刻意 bump（`main` HEAD 即 `v0.2.4`）。
- managed-install 的 serialwrap pin 由 `0.2.4` 提升至 `0.3.0`，並補上防止再次腐爛的守門測試。
  
  ## 為什麼
  
  serialwrap 的 daemon 早已在現場升到 `0.3.0`（v0.3.0 tag 於 2026-07-31 併入 #158），但兩條安裝路徑的 client pin 都還停在 `0.2.4`：
  
  | 路徑 | 位置 | 原值 |
  |---|---|---|
  | 線上安裝 | 本檔 `install-manifest.yaml` 的 `serialwrap.version` | `0.2.4` |
  | 離線 bundle | `wifi_llapi` 的 `scripts/make-bundle.sh` 的 `SERIALWRAP_REF`（`release.yml` 不覆寫，預設即出貨值） | `v0.2.4` |
  
  **沒有任何檢查看著這兩個 pin**，所以它們就這樣默默落後了一個 minor 版。
  
  這件事的諷刺之處在於：wifi_llapi #234 剛替 `--verify-install` 加上 client/daemon 版本漂移檢查，而 pin 若維持不動，**任何一次全新安裝都會在第一天就觸發那個新加的警告**——工具正確地指出了自己出貨的東西是舊的。
  
  ## 修法
  
  - `install-manifest.yaml` 的 `serialwrap.version` → `0.3.0`，並在註解明載「這是兩個獨立 pin 之一，必須與 wifi_llapi 的 `SERIALWRAP_REF` 一起 bump」。
  - 新增 `test_serialwrap_pin_is_the_deliberately_shipped_version`：把值鎖住，讓 bump 成為一次有意識的編輯；失敗訊息直接指向另一個 pin，避免只改一邊。
  
  wifi_llapi 側的對應修正與同型守門測試在該 repo 的 v0.3.9 release 一併落地。
  
  ## 未變更
  
  `core` 與 plugins 在本 manifest **刻意不釘版本**（由 installer 解析最新 API 相容版），因此 wifi_llapi 的新 release 不需要在此 re-pin；只有無 API 契約的 serialwrap 是釘死的。

### Fixed
- run-backend 裝置清單的 serialwrap session profile 不再硬編 `prpl-template`：優先讀 testbed 裝置的 `console_profile`（station-layer 選型鍵）、次之 `profile`，空值/缺席一律回退預設（truthy fallback，避免空 profile 產生畸形 session_id）。

## [0.3.5] - 2026-07-20

### Added
- 新增可運行的最小 sample plugin `examples/sample_echo`(獨立 dist `testpilot-sample-echo`,經 `testpilot.plugins` entry-point 被發現、只依賴 `testpilot.api`、走 `create_runner`→`run_pipeline` 產出 Pass verdict,含 `register_cli` demo 與 API 邊界測試);CI 補真實安裝發現 smoke;修 `docs/plugin-dev-guide.md` 死連結並加 Runnable sample 章節、清 `plugins/wifi_llapi/reports/` 殘骸並加 `.gitignore` 規則(ignore `plugins/*/reports/` run bundle、保留 `templates/`,防 run_loop 產生的 lab 產物再被追蹤 / R-21)。對照 issue #3。
- `run_loop` 無條件呼叫 plugin 的 DUT 版本 capture（fail-soft：擷取失敗記 warning 並以 `{}` 續行、不中止 run），naming 仍以 `--dut-fw-ver` 優先、fallback 取 `manifest["git"]`，整份 manifest 存進 `meta["version_manifest"]`。html/md reporter 於報表頂部渲染收折的 Environment/Versions 區塊（缺資料 no-op、不具名 plugin）。
- 新增 Azure-only core agent runtime 與成本報表契約：CLI 依環境自動判定 disabled/misconfigured/ready/degraded，misconfigured 會輸出去敏 notice；core run-loop 於每案 advisory planning、opt-in tier-2 recovery 與 run-end analysis 後寫出 `artifact_dir/agent_usage` JSON/Markdown artifacts，並以 additive pointer 回傳 `core_cost_report`/`core_agent_analysis`。
- HTML report 的 WiFi LLAPI Hybrid (tri-band) Summary 版面對齊 xlsx Summary sheet：section 位置移到 KPI/total-case 之下、per-case Summary 表之上；每 band 依 `5G`/`6G`/`2.4G` 分色（列底色 + 左側色條）以利區分；每 band 尾端新增粗體 **TOTAL** 小計列（取自 `bucket_totals`）；隱藏空的 `WiFi.Other` catch-all 列（真實 wifi_llapi 物件恆對到具體分類、Other 恆 0 且 xlsx 無此欄；Other 非零時仍顯示並計入 TOTAL）。
- `testpilot --version` 除 core 版本與 source ref 外，新增穩定排序的 installed plugin inventory，顯示各 `testpilot.plugins` entry point 的 distribution version 與 `api_version`；單一 plugin metadata 或 import 失敗時以 `unknown` fail-soft 顯示，不影響其餘 inventory 或 core 版本輸出。（#18）
- 新增 domain-agnostic tier-2 environment recovery：deterministic tier-1 連續失敗達門檻後，core 才於 retry gap 使用 tool-denied one-shot planner 選擇 plugin-advertised、schema/budget 驗證過的 environment action；plugin 執行後仍強制 deterministic `verify_env`，並輸出 bounded/redacted case/run audit 與 `agent_recovered` marker。provider、SDK 與 plugin callback 例外只保存 phase 及 exception type，不保存 raw exception text。（#4）
- 安裝流程改 flow latest-compatible：core/plugins 安裝當下解析 newest API-compatible（serialwrap 維持 manifest pin）。install.sh 交易式 resolve-before-mutate（先讀 core wheel API 再解析完整 plan 才動 venv）、任何動土後失敗以 ERR trap rollback、線上路徑也跑 `--verify-install` gate；`--update` installer/verify 失敗皆 rollback 不 brick；build-bundle build 期解析 newest-compatible + build-time API-compat gate + 寫 resolved-manifest.yaml。manifest core/plugins version 改 optional（serialwrap 必填），`--plugins name@ver` 保留釘版逃生口。

### Changed
- policy engine 升版 v1.0.5 → v1.0.10：`.project-policy.yml` / 四份 agent 檔 / 兩支 workflow 的 `uses:` 改 tag pin `@v1.0.10`、`policy_version` 對齊 1.0.10；採用 changelog.d fragment 模型（#24）。
- policy engine 升版 v1.0.10 → v1.0.12：`.project-policy.yml` / 四份 agent 檔 / 兩支 workflow 的 `uses:` 與 `policy_engine_ref` 改 pin `@25d31e02`（v1.0.12 release commit）、`policy_version` 對齊 1.0.12，並於 `uses:` 補 R-23 `# v1.0.12` 尾註。

### Fixed
- build-bundle.sh 的 third-party 依賴改為依已下載的 first-party wheel（core + 選定 plugins + serialwrap）metadata 解析閉包，取代原本手列套件名裸抓最新版——後者會抓到違反 core `click>=8.1,<8.4` pin 的 click 8.4.x，使 dry-run gate 以 ResolutionImpossible 失敗、產不出 bundle。新增 regression 測試鎖定此契約。
- copilot session foundation 對齊 `github-copilot-sdk` 0.1.x：實裝的 0.1.23 `PermissionHandler` 是 typing alias（非帶 `approve_all` 的 class），使每次 session 建立必然 raise → remediation silent 降級 builtin-fallback。改為 feature-detect `PermissionRequestResult` 自組 approve-all handler（wire shape `{"kind": "approved"}`，測試鎖形狀防 false-green），移除舊 `approve_all` 雙軌；session 建立失敗改一次性 loud warning + `run_loop` payload `agent_session_degraded` key（run-scoped，`run()` 入口重置）。(#16)
- install-manifest.yaml 的 `core.private` 由 `true` 更正為 `false`，對齊 `hamanpaul/testpilot-core` 實際為 public repo（serialwrap 亦 public 且標記正確；wifi_llapi/brcm_fw_upgrade 維持 private）。此欄位為 registry 標記、install.sh/build-bundle.sh 皆未讀取，故無行為變更，僅修正誤導的 metadata。
- Markdown 報表的 WiFi LLAPI Hybrid summary 表對齊 HTML 報表：空的 `WiFi.Other` catch-all 列（無 xlsx Summary 對應）改以該 band 的 **TOTAL 匯總列**呈現（取自 `bucket_totals`，統計該 band 全 category 總數），非只顯示 WiFi.Other 的 0。先前只修了 `html_reporter`（見 `feat-html-report-hybrid-summary-layout`），`reporter`(md) 未同步，本次補齊使兩者逐列一致。
- test_topology.py 改用 pytest fixture 於 tmp_path 寫入最小 testbed.yaml，不再依賴 git-ignored 的 configs/testbed.yaml（原本僅 CI bootstrap step 會產生），fresh clone 直接 pytest 不再有 2 個 failure。四項斷言不變（name=lab-bench-1、DUT 裝置、SSID_5G→testpilot5G、未知變數原樣保留）；inline testbed 僅含 name/DUT/SSID 不含任何 KEY 憑證，維持 R-21 機密掃描潔淨。

## [0.3.4] - 2026-07-08

### Added
- 可運行的最小 sample plugin `examples/sample_echo`(獨立 dist `testpilot-sample-echo`,經 `testpilot.plugins` entry-point 被發現、僅依賴 `testpilot.api`、`create_runner`→`run_pipeline` 產出 Pass verdict,含 `register_cli` demo);CI 加真實安裝發現 smoke;dev-guide/README 指向 sample 並修死連結、清 `plugins/wifi_llapi/reports/` 並加 `.gitignore` 防 `plugins/*/reports/` run bundle 再被追蹤(保留 `templates/`;R-21)。對照 #3。

### Changed
- Azure activation is environment-driven and core-only: no interactive enable
  flag or OAuth/provider fallback. Plugin API and `RunResult` remain unchanged;
  custom/skeleton paths report `unsupported_execution_path`. Benefit metrics are
  observational and do not claim USD pricing or causal uplift/regression.
- HTML report 的 WiFi LLAPI Hybrid (tri-band) Summary 版面對齊 xlsx `Summary` sheet:section 移到 KPI/total-case 之下、per-case Summary 表之上;per-band 依 `5G`/`6G`/`2.4G` 分色(列底色 + 左側 3px 色條);每 band 尾端補粗體 **TOTAL** 小計列(取自 `bucket_totals`);隱藏空的 `WiFi.Other` catch-all 列(xlsx 無此欄、真實物件恆對到具體分類;非零時仍顯示並計入 TOTAL)。純 `html_reporter` presentation 層改動,不動 `band_category` 計數邏輯。
- run_loop 啟動時一律擷取 plugin 的 DUT version manifest 並透過 `RunResult.version_manifest` 傳給 downstream reporters；capture hook 若失敗則 warning 後 fail-soft 續跑、沿用空 manifest fallback。report naming 仍維持 CLI `--dut-fw-ver` 優先、否則取 manifest `git`、再 fallback `DUT-FW-VER`；generic Markdown/HTML reporters 於報告頂部新增預設收合的 `Environment / Versions` 區塊。

### Fixed
- copilot session foundation 對齊 github-copilot-sdk 0.1.x（`PermissionHandler.approve_all` 已不存在）：自組 approve-all permission handler（wire shape `{"kind": "approved"}`）；session 建立失敗改為一次性 loud warning + run payload `agent_session_degraded` key，終結 silent builtin-fallback（#16）

## [0.3.3] - 2026-07-04

### Added
- 安裝流程改 flow latest-compatible：core/plugins 於安裝當下解析 newest API-compatible（serialwrap 維持 manifest pin），`install.sh` 交易式 resolve-before-mutate、動土後失敗 `ERR` trap rollback、線上路徑亦跑 `--verify-install` gate；manifest core/plugins version 改 optional。

### Changed
- policy engine 升版至 `v1.0.12`：`.project-policy.yml` / 四份 agent 檔 / 兩支 workflow 的 `uses:`+`policy_engine_ref` pin `@25d31e02`、`policy_version` 對齊 1.0.12，並於 `uses:` 補 R-23 `# v1.0.12` 尾註。

### Fixed
- `build-bundle.sh` third-party 依賴改依已下載 first-party wheel 的 metadata 解析閉包，取代裸抓最新版（後者會抓到違反 core `click>=8.1,<8.4` pin 的版本使 dry-run gate 失敗）。
- `test_topology.py` 改用 `tmp_path` fixture 寫最小 `testbed.yaml`，不再依賴 git-ignored 的 `configs/testbed.yaml`，fresh clone 直接 `pytest` 不再有 failure。

## [0.3.2]

### Changed

- `install-manifest.yaml`: bump `serialwrap` pin `0.2.0` → `0.2.1` to match the
  published `serialwrap-0.2.1-py3-none-any.whl` release asset (serialwrap Phase A
  added its tag-triggered wheel release; the offline-bundle path now resolves a
  serialwrap wheel instead of relying on the `install.sh` git+https fallback).

## [0.3.1]

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
- **Rollback snapshot path now honors `TESTPILOT_HOME`.** `_last_good_path()`
  hardcoded `~/.local/share/testpilot/.last-good.txt` while `_get_managed_venv()`
  respects `TESTPILOT_HOME`; the snapshot is now derived from the same base so it
  always sits next to the venv it describes.
- **Legacy-checkout probe now honors `TESTPILOT_HOME`.** `_probe_legacy_installs()`
  checked the hardcoded default `~/.local/share/testpilot/src` while removal uses
  `_get_managed_src()` (TESTPILOT_HOME-aware); the probe now uses
  `_get_managed_src()` so detection and removal target the same path.
- **CRITICAL: `--update` rollback can no longer reach a public index.** The
  rollback path ran `pip install -r <pip-freeze-snapshot>`, which resolves the
  private `testpilot-core`/plugins against public PyPI (dependency-confusion /
  install failure) — the same hazard the main install path avoids. Rollback now
  forces `pip install --no-index --find-links <wheel-cache> -r <snapshot>`
  against the local wheel cache the installer preserves under
  `${TESTPILOT_HOME}/.wheel-cache`, checks the runner return code, and on
  failure (or a missing snapshot) prints a manual-recovery message
  (`install.sh --offline <bundle>`) and exits nonzero instead of silently
  retrying online. `scripts/install.sh` online mode now copies each used wheel
  into `${TESTPILOT_HOME}/.wheel-cache` after a successful install.
- `scripts/install.sh` robustness: offline mode now validates the bundle's
  `linux-<arch>` tag against `uname -m` BEFORE extraction (fail fast on
  wrong-arch); the online per-package wheel download dir is tracked and cleaned
  by the EXIT trap so it no longer leaks when `pip` aborts under
  `set -euo pipefail`; and venv creation no longer hides a broken interpreter
  behind `|| true` — it fails if `${VENV}/bin/python` is missing or not
  executable.
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

- **CI offline smoke is now a real installer gate.**
  `tests/test_offline_install_integration.sh` previously `pip install`ed a
  wheelhouse directly and `exit 0`'d on any network/download failure, so the
  actual offline-installer paths (checksum, python+arch tag checks, extraction,
  wrapper, skill sync, post-install verify) were never exercised. It now stages
  a real bundle (`wheelhouse/` + `requirements.txt` + `SHA256SUMS`, in
  `build-bundle.sh`'s shape) and runs `bash scripts/install.sh --offline
  <bundle>` into an isolated `TESTPILOT_HOME`, asserting `testpilot --version`
  and `testpilot --verify-install` pass. In CI (`CI=true`) a
  dependency-prep/network failure is a HARD FAIL; locally with no network it
  prints an explicit SKIP. The CI step pins `CI: "true"`.
- `--update` help text updated to describe the wheel-model reconcile (was stale
  "managed checkout" wording); README CLI-help marker blocks regenerated to
  match.
- Wheel-mode `--verify-install` now reports a failing plugin with its captured
  error TYPE (e.g. `failed to load (ImportError)`); only an actual
  `IncompatiblePluginError` is reported as `api-incompatible`.
- `install-manifest.yaml`: `wifi_llapi` pin bumped `0.3.0` → `0.3.1` to match the
  published `wifi_llapi-0.3.1-py3-none-any.whl` release asset (`api_version`
  unchanged at `1.1`; `install-doctor` manifest-compat gate stays green).

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

<!-- managed-by: hamanpaul/paulsha-conventions@v1.0.12 -->
<!-- 若修改此檔，同步更新 CLAUDE.md / AGENTS.md / GEMINI.md / .github/copilot-instructions.md 四份 -->
policy_version: 1.0.12

# Agent Policy Checklist

本 repo 受 hamanpaul project policy v1.0.12 管轄。
所有 agent 進入 session 時，必須依下列 checklist 行動。

## 本 repo 的 profile
- policy_profile: `flat` （見 `.project-policy.yml`）
- policy_version: `1.0.12`

## 動工前
- [ ] 確認當前分支不是 `main`
  - 若在 `main`，先開 `feature/<slug>` 分支
  - 若在 `feature/*`，可直接工作，或再開 `wt/<feature>/<subtask>`
- [ ] 若本任務跨多個子項，先建議用 `git worktree` 拆開
- [ ] 若本任務對應某 issue（軟性建議，不打斷流程）：用 `gh issue view <N>` 核對該 issue 與本任務相關，分支可命名為 `feature/<N>-<slug>`，開 PR 時於 body 寫 `Closes #N`
  - 查無對應 issue：照常往下做，不需另開 issue、不需停下

## 改 code 時
- [ ] 同一 PR 必須同步更新 `CHANGELOG.md [Unreleased]`
- [ ] 除非可明確標示為 docs-only / test-only / chore，否則不得省略 CHANGELOG
- [ ] code_paths 涵蓋的檔案變動皆視為 code change
- [ ] 評估 `README.md` / `docs/**` 是否需隨本 PR 同步（R-18；行為或介面有變動務必更新，純內部變動可上 `policy-exempt:docs-sync`）
- [ ] R-22：搬移／改名／刪除 code 產物（檔案、`def`/`class`）時，同步更新 `README.md` / `docs/**` 中引用它的段落；無法即時處理上 `policy-exempt:doc-reference` 並附理由

## 改版號時（release 觸發時）
- [ ] 嚴格遵循 `<MAJOR>.<MINOR>.<PATCH>[-fix.N]`
- [ ] PATCH bump 對應 profile：
  - `stage-driven`: 一個 stage 落地
  - `flat`: 一個 feature batch 完成
- [ ] MINOR bump 需滿足：feature 群組全 landed + 7 天無 hotfix
- [ ] MAJOR bump 需使用者明確核可
- [ ] 若本 PR 將版本 bump 延後（feature 先進 `[Unreleased]`），merge 當下必須**立即**補做對應 release bump（`VERSION` / `policy_version` / 四份 agent 檔 / `managed-by` 標記 / tag / `docs/release-flow.md`），不得留置

## 完成任務（claim done）前
- [ ] `CHANGELOG.md [Unreleased]` 有對應 entry（或 PR 標 `skip-changelog` + 理由）
- [ ] `VERSION` 內容與意圖一致（release label PR 才可偏離 latest tag）
- [ ] `.github/PULL_REQUEST_TEMPLATE.md` checklist 全勾
- [ ] 測試全綠（本 repo: `uv run pytest -q`）
- [ ] `python3 -m policy_check --repo .` 無任何 failure
- [ ] R-17：PR body 若引用 issue（`#N`），必須是 closing-keyword 形式（`Closes/Fixes/Resolves #N`）；只引用不關閉時上 `policy-exempt:issue-link`
- [ ] R-18：code 有變動時已評估並（如需要）同步 `README.md` / `docs/**`，或上 `policy-exempt:docs-sync`
- [ ] R-19：repo 有 `tests/` 時，CI workflow 有實際執行測試（pytest 等）；新增測試套件而 CI 未涵蓋時同步補上
- [ ] R-21：宣告 `tier: shareable` 的 repo 不得含雇主機敏標記（內部代號、裝置型號等）、個人絕對路徑或憑證模式；合法引用上 `secret_scan.allow` 或命中時上 `policy-exempt:secret-scan` 並附理由
- [ ] R-22：docs 對本次刪改 code 產物的引用無懸空（CI 報「本次新破壞」FAIL、陳年 WARN），或上 `policy-exempt:doc-reference`
- [ ] 語言：PR 標題／內文與所有 comment 的語言符合本 repo 規範（見「語言規範」段）
- [ ] 若跳過任何檢查，PR 必須帶對應豁免 label + 理由

## 語言規範（PR / comment）
依 repo 來源決定撰寫語言（用 `git remote -v` 判斷）：
- `github.com/hamanpaul/*`、`github.com/paulc-arc/*` → 一律 **zh-tw**
- arcadyan GitLab → 一律 **en_US**

涵蓋範圍：PR 標題、PR 內文、code review 與 issue 的所有 comment。本 repo 屬 `hamanpaul` → zh-tw。

## 禁止
- 直接 commit 到 `main`
- 建立不符合命名規則的分支（必須 `feature/<slug>` 或 `wt/<feature>/<subtask>`）
- 發明新 `policy-exempt:*` label（**只能用 policy 列舉的白名單**）
- 修改本檔而不同步其他三份 agent convention 檔

## Exemption Labels 白名單
僅允許使用以下 labels 豁免對應規則（其他一律視同未豁免）：
- `policy-exempt:readme-sections` — R-02 README 必備段落
- `policy-exempt:changelog-format` — R-04 CHANGELOG 格式
- `policy-exempt:pr-title` — R-10 PR title conventional-commit 格式
- `policy-exempt:branch-name` — R-12 分支來源規則
- `policy-exempt:agent-files` — R-13 agent convention files 存在
- `policy-exempt:cli-help` — R-16 CLI help 同步
- `policy-exempt:issue-link` — R-17 PR body issue 參照需 closing-keyword 形式
- `policy-exempt:docs-sync` — R-18 code 變動需同步 README/docs
- `policy-exempt:ci-tests` — R-19 repo 有測試則 CI 必須執行
- `policy-exempt:secret-scan` — R-21 機密掃描（tier=shareable 命中雇主標記）
- `policy-exempt:doc-reference` — R-22 文件懸空引用（doc dangling reference）
- `skip-changelog` — R-09 code 變動要求 CHANGELOG entry（特殊用途，需附理由）
- `wip` — R-11 自動通過 PR body checkbox 未全勾（work in progress）

## Doc-alignment review（PR review 時）
review 變更時，除了 R-22 抓得到的懸空引用，另留意**語意陳舊**：引用都還在、但 docs 描述了已被這次變更改掉的架構／行為；發現時於 PR 留言指出、建議作者更新。Advisory，不擋 merge。建議將 GitHub Copilot 設為 PR reviewer 以啟用此層。

## TestPilot 專案專屬

# TestPilot Development Guidelines

policy_version: 1.0.12

## Scope

本檔定義本專案在開發/維護時的固定規範，重點是：

1. 文件與進度一致性
2. `docs/todos.md` 治理規則
3. plugin 級 agent/model 配置慣例

## Project Structure

```text
src/testpilot/
  core/       # orchestrator, plugin_base, plugin_loader, testbed_config
  reporting/  # wifi_llapi_excel and related report helpers
  transport/  # transport abstractions
  env/        # env modules (roadmap)
  schema/     # YAML case schema validation
plugins/      # each plugin in its own directory; ships testbed.yaml.example
configs/      # operator-local effective testbed.yaml (auto-staged by CLI; git-ignored)
docs/         # plan, todos, phase docs
scripts/      # utility scripts (gen_cases, build_template_report)
skills/       # repository agent skills, including testpilot-normal-test
```

## Case Discovery Convention

1. `plugins/wifi_llapi/cases/` 中，官方 discoverable cases 以 workbook row-indexed `D###` YAML 為主。
2. 檔名 stem 以 `_` 開頭的 YAML 視為 explicit fixtures / legacy compatibility artifacts；`load_cases_dir()` 會排除這類檔案，不得計入 discoverable case inventory。
3. 若需保留 legacy YAML 供 schema / backward-compat 測試，優先使用 underscore-prefixed fixture 命名，不要沿用會被誤認成正式 case 的 `D###` 命名。
4. `wifi_llapi` discoverable case 已移除 `results_reference` 與 `source.baseline` / `source.report` / `source.sheet`；runtime 報表值只反映實際 verdict 與 `bands` 投影，不再接受 workbook oracle metadata 回寫。

## Commands

```bash
uv pip install -e ".[dev]"
# configs/testbed.yaml is auto-staged from plugins/<plugin>/testbed.yaml.example
# whenever a plugin-aware command runs; no manual cp needed.
testpilot --version
testpilot list-plugins
testpilot list-cases wifi_llapi
python -m testpilot.cli wifi-llapi baseline-qualify --repeat-count 5 --soak-minutes 15
testpilot wifi_llapi
python -m testpilot.cli wifi-llapi build-template-report --source-xlsx <path>
uv run pytest -q
```

Wifi_llapi reporting guidance:

3. `testpilot wifi-llapi build-template-report --source-xlsx <path>` is a build/audit path. `testpilot wifi_llapi` must not depend on raw source workbooks.
4. `wifi_llapi` runtime alignment treats `(source.object, source.api)` as the canonical lookup key into the checked-in template workbook; `D###`, `source.row`, and matching `id` fragments are derived metadata and may be auto-corrected **in memory** during `testpilot wifi_llapi`.
5. If one `(source.object, source.api)` pair maps to multiple template rows, runtime alignment must block that family instead of guessing a row; follow-up cleanup uses the surfaced candidate template rows.
6. `testpilot wifi_llapi` MUST NOT rename case files or rewrite `source.row` / `id` during the normal run path. Runtime drift is surfaced in reports/artifacts only; persistent case-file alignment belongs to audit/apply workflows.
7. Runtime artifact bundles and JSON `alignment_summary.blocked_details` must expose blocked ambiguous families with their candidate template rows so maintainers can reconcile template duplicates offline.
8. Alignment and audit are separate responsibilities: runtime alignment is read-only and only projects metadata drift into run artifacts/reports; audit mode remains the place to change `name`, `steps`, `pass_criteria`, `source.object`, `source.api`, or `aliases`.

## Local Artifact Version Control Policy

1. repo root workbook inputs (`/*.xlsx`, `/*.xls`, `/*.xlsm`) and compare outputs (`compare-*.md`, `compare-*.json`) are local-only artifacts; do not commit them.
2. one-off campaign notes such as `*-full-run-static.md` and root-level STA experiment scratch notes are local-only unless explicitly promoted into `docs/`.
3. reusable report assets that stay versioned belong under `plugins/wifi_llapi/reports/templates/`; runtime output bundles under `plugins/wifi_llapi/reports/<artifact_name>/` remain untracked.

## Versioning and Release Policy

1. Repository release tags use Semantic Versioning in the form `vX.Y.Z`; the managed baseline for this workflow starts at `v0.2.0`.
2. Canonical project version lives in `VERSION`; `pyproject.toml` and `src/testpilot/__init__.py` are packaging/runtime mirrors and must stay identical.
3. User-facing pull requests should update `CHANGELOG.md` under `Unreleased`, or explicitly record why no changelog entry is needed.
4. Release preparation happens in a dedicated `release/vX.Y.Z` PR that updates version metadata, finalizes `CHANGELOG.md`, and syncs `README.md`, `docs/release-flow.md`, `.project-policy.yml`, and this `AGENTS.md` when process guidance changes.
5. Only tag merged `main` commits; release tags must be `vX.Y.Z` and match the in-repo version. Tag push is responsible for publishing the GitHub Release.
6. Prefer GitHub-native controls first: PR template checklist, Actions CI, and tag-triggered Releases. Add extra local rules only where GitHub cannot enforce behavior directly.
7. Current publication scope is GitHub tag + GitHub Release notes only; do not assume wheel / sdist / binary assets are produced. Installation guidance should point to tagged-source installs until package publication is added.

## Todo Governance（嚴格）

1. `docs/todos.md` 是唯一待辦看板。
2. 非 Plan Mode：不得增減項次、不得調整 ID。
3. 非 Plan Mode：只允許更新狀態與必要註記。
4. Plan Mode：才可新增/刪除/重排項次。

## Documentation Sync Rule

當更新規劃或進度時，必須同步檢查以下文件一致性：

1. `docs/plan.md`
2. `docs/todos.md`
3. `README.md`
4. 本檔 `AGENTS.md`

## Audit Report Format Policy

1. `wifi_llapi` 的人工校正 audit report 必須使用 collapsible markdown sections。
2. 一旦某批 case 被判定為「已 live 對齊」，report 中必須新增或更新 `Per-case 摘要表（zh-tw）` 區塊。
3. `Per-case 摘要表（zh-tw）` 至少要包含：
   - case id
   - workbook row
   - API 名稱
   - verdict
   - DUT log interval
   - STA log interval
4. 每個已對齊 case 都必須附上 markdown fenced code blocks，分別記錄：
   - STA 指令
   - DUT 指令
   - 判定 pass 的 log 摘錄 / log 區間
5. 不可只寫 prose summary 而省略指令與 log block；有標記 aligned 的 case，command/log evidence 是必填。
6. 若同一批 case 共用 STA baseline，可重複列出，或在每個 case 內明確引用同一組 baseline 指令，但不可省略。
7. 若已知 log 行號區間，沿用 `Lxxx-Lyyy` 表示法，避免後續批次漂移成不同風格。
8. `wifi_llapi` aligned YAML 的 workbook row reference 只保留在 `source.row`；舊的 `wifi-llapi-rXXX-*` alias 視為 stale metadata，live 對齊時應移除，不再作為 row 來源。

## Calibration Continuation Policy

1. 目前 `wifi_llapi` workbook 校正工作必須嚴格採 **single-case mode**：一次只處理一個 official case。
2. 不可把未解案例再拆成 batch 並行處理，也不可自行建立加速工具／腳本來跳過逐案 evidence 驗證。
3. sub-agent 只可協助 offline survey、source tracing、code review；最終 live serialwrap 操作與 verdict 仍由主操作者手動收斂。
4. repo-only handoff 必須落在已提交的文件，而不是 session-local SQL / plan scratchpad。最少要同步：
   - `docs/audit-todo.md`
   - `plugins/wifi_llapi/reports/audit-report-*.md` 的最新 checkpoint 區塊
   - `README.md`
   - `docs/plan.md`
5. 每次完成單案校正或確認 blocker 後，repo handoff 文件至少要同步：
   - 目前 calibrated / remaining counts
   - active blockers
   - 最新已提交 case 與 verdict 形狀
   - 下一個 ready case
   - 最新驗證指令與結果
6. **commit / brief status update / targeted tests pass 都不是停點**；只要沒有明確 blocker、lab 失真、或使用者要求暫停，就必須在同一輪直接推進到下一個 ready single case。
7. 每個 single-case loop 的預設完成定義固定為：offline survey → live 三個 band 驗證/切換 → YAML 重寫 → runtime targeted tests → runtime file / full suite → docs sync → precise stage/commit → 立刻把下一個 ready case 標成 `in_progress`。
8. 若因 context 壓縮、tool/runtime crash、或 session 中斷而被迫停下，必須先把「最新已提交 case、目前 counts、next ready case、active blocker、最新驗證結果」落回 repo handoff 文件，再視為可接受中斷。
9. 對使用者的進度回覆應以「不中斷主流程」為原則：除非需要請求決策或回報 blocker，說明完當前 checkpoint 後就要繼續執行下一筆，不得把單次回答本身當成停工理由。

## Default Lab Baseline Policy

1. 預設 baseline 不可使用 open security SSID。
2. 若 testcase 沒有明確要求特殊安全模式，預設使用：
   - 5G：`testpilot5G` / `WPA2-Personal` / password `00000000`
   - 2.4G：`testpilot2G` / `WPA2-Personal` / password `00000000`
   - 6G：`testpilot6G` / `WPA3-Personal` / `key_mgmt=SAE` / password `00000000`
3. baseline 因 reboot / session recover 重建後，必須先把最新 SSID / security readback 與已驗證 band link 狀態同步回 repo handoff 文件，再繼續逐案校正。
4. **BGW720-0410 image 暫時 workaround**：該 image 因 driver commit `00c7a198e8` 使 5G/2.4G 的 WPA2-PSK 4-way handshake 失敗（AP deauth `reason=1`，且 pwhm runtime reconfig 不會把 security apply 進 driver）。`band-baselines.yaml` 的 5g/2.4g profile 暫改為 `WPA3-Personal` / SAE（`sae_pwe=2` 必填，避免 DUT H2E-only 與 STA hunting-and-pecking 撞牆）以建立穩定 baseline；6G 不受影響。此為 image-specific override，image 修復（revert `00c7a198e8`）後須回退第 2 點的 5G/2.4G `WPA2-Personal` 預設（見 CHANGELOG）。

## Plugin Agent Config Policy

1. plugin 若需宣告 agent/model policy，使用 `plugins/<plugin>/agent-config.yaml`。
2. `wifi_llapi` 第三次重構目標優先序固定為：
   - Priority 1: `copilot + gpt-5.4 + high`
   - Priority 2: `copilot + sonnet-4.6 + high`
   - Priority 3: `copilot + gpt-5-mini + high`
3. 不再以 `codex CLI` 為相容目標，不為舊 runner policy 增加 workaround code。
4. 第一優先不可用時允許自動降級，且需留 `selection trace`。
5. `wifi_llapi` 執行策略以 case-level 為主（每個 test case 各自呼叫 agent）。
6. `wifi_llapi` 排程策略預設為 `sequential`（`max_concurrency=1`）。
7. case 失敗策略為 `retry_then_fail_and_continue`，且 timeout 需隨 retry attempt 調整。
8. `wifi_llapi` 目前允許的 live remediation 只限 safe environment repair：`serial_session_recover`、`sta_band_reconnect`、`sta_band_rebaseline`、`dut_band_rebaseline`、`case_env_reverify`。
9. live remediation 僅允許發生在 retry attempts 之間；不得 mid-step takeover，也不得修改 YAML semantics、step 指令、pass criteria 或 xlsx final verdict。
10. 若 agent remediation decision 無法取得、格式不合法、或超出 whitelist，必須 fallback 到 deterministic builtin classifier，或直接不套 remediation。

## Plugin API Contract Policy

1. `testpilot.api.API_VERSION` 是 plugin SDK 契約版本，採 `major.minor`，且獨立於 `VERSION` / package release 版本。
2. plugin class 必須顯式宣告 `api_version = "<major>.<minor>"`；`PluginBase.api_version = None` 代表未宣告，載入時必須報錯。
3. `PluginLoader.load()` 的相容條件固定為 `plugin.major == API.major` 且 `API.minor >= plugin.minor`。
4. 未宣告、格式錯誤、major 不同或 SDK minor 太舊時，必須 raise `IncompatiblePluginError`，並由 `testpilot.api` re-export 供 host/CLI 捕捉。

## Azure OpenAI BYOK Policy

1. CLI 提供 `--azure` flag，啟動時互動式詢問 endpoint / api_key / model 三個參數。
2. 認證順序：`--azure` 互動 → `COPILOT_PROVIDER_*` 環境變數 → GitHub OAuth → 全部失敗則結束程式。
3. 環境變數命名遵循 Copilot CLI 官方慣例：
   - `COPILOT_PROVIDER_TYPE=azure`
   - `COPILOT_PROVIDER_BASE_URL=<endpoint>`
   - `COPILOT_PROVIDER_API_KEY=<key>`
   - `COPILOT_MODEL=<deployment-name>`
   - `COPILOT_PROVIDER_AZURE_API_VERSION=<version>` (預設 `2024-10-21`)
4. API key 與 endpoint 不得提交至版本控制；secrets 一律透過環境變數或 shell profile 注入。
5. `agent-config.yaml` 只放執行策略（model priority / timeout / retry），不放 secrets。

## Code Style

1. Python 3.11+，型別標註優先。
2. 維持最小必要變更，避免無關重構。
3. plugin 需繼承 `PluginBase` 並匯出 `Plugin` 類別。

## Audit Mode Governance

1. Audit work 全程透過 `testpilot audit ...` 執行；不得直接編輯 `plugins/<plugin>/cases/D*.yaml` 而繞過 `verify-edit`
2. 每個 audit run 必須有 RID，evidence 與 buckets 落在 gitignored `audit/runs/<RID>/`
3. YAML 修改只允許動 `steps[*].command`、`steps[*].capture`、`verification_command`、`pass_criteria[*]`
4. pre-commit hook `audit-yaml-provenance` 強制 case YAML 變動必須對應某個 `verify_edit_log.jsonl`；繞行需用 commit message `[audit-bypass: <reason>]`
5. Pass 3 由主 agent 負責 evidence 收斂；fleet sub-agents 只做 read-only source survey
6. `block` 不是 final state；下次 audit run 對同 case 仍可重新評估
7. doctrine 與操作流程以 `docs/audit-guide.md` 為準

## ADDED Requirements

### Requirement: Audit subcommand 群組

`testpilot` CLI SHALL 提供一個獨立 `audit` subcommand 群組，與 `testpilot run` 完全分流。`audit` 群組必須包含下列 subcommand：`init`、`pass12`、`record`、`verify-edit`、`decide`、`status`、`summary`、`apply`、`pr`。

`audit` 群組的任何 subcommand SHALL NOT 呼叫任何 LLM SDK；audit Python 套件（`src/testpilot/audit/`）必須是 deterministic、可 reproduce。

`testpilot run` 路徑 SHALL NOT 觸發 audit YAML rewrite；反向亦然 — `testpilot audit ...` 群組除了 `apply` step 之外，SHALL NOT 修改 `plugins/<plugin>/cases/D*.yaml`。

#### Scenario: CLI 群組存在性與分流

- **WHEN** user 執行 `testpilot audit --help`
- **THEN** CLI 列出 `init` / `pass12` / `record` / `verify-edit` / `decide` / `status` / `summary` / `apply` / `pr` 九個 subcommand

#### Scenario: audit subcommand 不會被 normal run 誤觸

- **WHEN** user 執行 `testpilot run wifi_llapi`（任何 flag）
- **THEN** 該指令 SHALL NOT 產生 `audit/runs/<RID>/` 目錄、SHALL NOT 修改 plugin/cases/、SHALL NOT 觸發任何 audit bucket 落點

### Requirement: RID 生成與 manifest

`testpilot audit init <plugin> --workbook <path>` SHALL 產生 RID，格式 `<git_short_sha>-<ISO8601>` (e.g. `c2db948-2026-04-27T143000`)，並建立 `audit/runs/<RID>/<plugin>/manifest.json`，內容包含：plugin name、scope cases、CLI args、workbook 路徑、workbook sha256 hash、git commit SHA、init timestamp、欄位 mapping（auto-discovered 或從 `--col-*` 取）。

當 `--workbook` 未給時，CLI SHALL fallback 到 `audit/workbooks/<plugin>.xlsx`；兩者皆無 → init 失敗並印 error。

#### Scenario: init 產出 RID

- **WHEN** user 執行 `testpilot audit init wifi_llapi --workbook /path/to/0401.xlsx`
- **THEN** stdout 印出 RID 字串；`audit/runs/<RID>/wifi_llapi/manifest.json` 存在；workbook 副本寫到 `audit/runs/<RID>/wifi_llapi/workbook_snapshot.xlsx`

#### Scenario: init fallback 到約定路徑

- **WHEN** user 執行 `testpilot audit init wifi_llapi`（無 `--workbook`）且 `audit/workbooks/wifi_llapi.xlsx` 存在
- **THEN** init 採用 fallback 路徑成功

#### Scenario: init 在 workbook 缺失時失敗

- **WHEN** user 執行 `testpilot audit init wifi_llapi`（無 `--workbook`）且 `audit/workbooks/wifi_llapi.xlsx` 不存在
- **THEN** init exit 非 0；stderr 提示 `--workbook` 必須給或約定路徑必須存在

### Requirement: audit/ 工作資料夾 gitignored

repo 根目錄的 `.gitignore` SHALL 包含 `/audit/` entry；audit-runner 寫入的所有 evidence、buckets、manifests、verify_edit_log 都僅限 local。

repo 中 SHALL NOT 存在被 commit 的 `audit/runs/*/` 內容。

#### Scenario: audit/ 不入 git

- **WHEN** audit run 結束後 `audit/runs/<RID>/wifi_llapi/case/D366/decision.json` 存在
- **THEN** `git status` 不顯示 audit/ 為 untracked；`git ls-files audit/` 為空

### Requirement: Workbook 語意鍵 lookup

audit 載入 workbook 後 SHALL 建立 `(normalize(source.object), normalize(source.api))` → WorkbookRow 的 index。`normalize` 規則：去 trailing dot、collapse `{i}` placeholder、strip whitespace；保留大小寫（TR-181 名稱 case-significant）。

audit 對 case YAML 的對應 row 查找 SHALL NOT 使用 `source.row` 欄位作為比對來源；`source.row` 僅作為 evidence 中的 cross-check meta。

當同一 semantic key 對應多筆 workbook row 時 SHALL 標 `block` 並記錄 `reason="workbook_row_ambiguous"`，附 candidate raw_rows 清單。

當 case YAML 的 semantic key 無對應 workbook row 時 SHALL 標 `block` 並記錄 `reason="workbook_row_missing"`。

#### Scenario: 一對一 semantic key 找到對應 row

- **WHEN** case YAML 的 `source.object="WiFi.Radio.{i}.IEEE80211ax."` 與 `source.api="SRGBSSColorBitmap"`，且 workbook 有唯一 row 對應該 (object, api)
- **THEN** audit 用該 row 的 R/S/T 作為 verdict authority、G/H 作為 procedure authority

#### Scenario: row drift 不影響語意對齊

- **WHEN** workbook 對應 row 從 row 366 移到 row 412（手動編輯造成漂移）
- **THEN** audit 仍能透過 (object, api) 找到該 row，不依賴 source.row 是否更新

#### Scenario: ambiguous workbook 被 block

- **WHEN** workbook 兩 row 都記錄相同 (object, api)（資料重複）
- **THEN** audit 對該 case 標 bucket=block、reason=workbook_row_ambiguous、附 raw_rows=[r1, r2]

### Requirement: Pass 1 純 py 預過濾

`testpilot audit pass12 <RID>` SHALL 對 manifest 中每筆 official case：

1. 透過 thin facade（`src/testpilot/audit/runner_facade.run_one_case_for_audit`）跑 case YAML 原樣
2. 比對 verdict_y vs workbook R/S/T
3. 一致 → bucket=`confirmed`（diff 為空）
4. 不一致 → 進 Pass 2

Pass 1 行為 SHALL 是 idempotent — 重 run 不影響語意（同 RID + 同 workbook + 同 case YAML → 同 verdict）。

`pass12` SHALL NOT 修改 `plugins/<plugin>/cases/D*.yaml`。

#### Scenario: Pass 1 match 落 confirmed

- **WHEN** case YAML 跑完得 verdict=`Pass / Pass / Pass`，workbook R/S/T = `Pass / Pass / Pass`
- **THEN** audit 把該 case 落 bucket=confirmed，diff 為空

#### Scenario: Pass 1 mismatch 進 Pass 2

- **WHEN** case YAML 跑完得 verdict=`Pass / Pass / Pass`，workbook R/S/T = `Fail / Fail / Fail`
- **THEN** audit 對該 case 進 Pass 2 流程

### Requirement: Pass 2 mechanical command extraction

Pass 2 SHALL 從 workbook 該 row 的 G（Test Steps）/ H（Command Output）prose 用 regex + token allowlist 機械化抽 candidate command list。

Token allowlist：`{"ubus-cli", "wl", "hostapd_cli", "grep", "cat", "sed", "awk", "ip", "iw", "hostapd", "wpa_cli"}`。

支援的抽取規則：行首 token 命中 allowlist；fenced code block (` ``` ... ``` ` 或 `` `...` ``)；行內 single-line 命令引用。

Pass 2 抽出的命令 SHALL 是 G/H 文字 substring（不允許重新組合 / 改寫）。每筆 candidate command 必須帶有對應的 G/H substring 引用作為 citation。

當：
- 抽到 unambiguous command list 且 rerun verdict_w == workbook R/S/T 且所有 citation 通過 substring 驗證
  → bucket 候選 `applied`（再加 §Bucket classification 其他條件）
- 抽不到 / ambiguous / verdict_w 仍 mismatch
  → 標 `needs_pass3`

`needs_pass3` SHALL 寫進 `audit/runs/<RID>/<plugin>/buckets/needs_pass3.jsonl`，列入主 agent worklist。

#### Scenario: Pass 2 抽取 unambiguous 命令並對齊 workbook

- **WHEN** workbook G 含 fenced block `` `ubus-cli "WiFi.Radio.1.Noise?"` ``，rerun 後 verdict_w 對齊 workbook R/S/T
- **THEN** 該 case 候選進 applied 桶，evidence pass2_workbook.json 含 extracted_commands + citations

#### Scenario: Pass 2 抽不到命令進 needs_pass3

- **WHEN** workbook G 為純中文敘述「設定 SRG bitmap 並驗證 driver 是否拉起」，無 token-allowlist 命中
- **THEN** 該 case 標 needs_pass3，不進任何 bucket，列入主 agent worklist

### Requirement: Pass 3 主 agent + fleet sub-agents

主 agent 在 Copilot session 內 SHALL 對 `needs_pass3` worklist 中每筆 case：

1. 透過 Claude Code 內建 `Task` tool 派 read-only fleet sub-agents（`subagent_type=Explore`）對下列 source 子樹平行 grep：`bcmdrivers/.../impl107/`、`userspace/.../prpl_brcm/mods/mod-whm-brcm/`、`altsdk/.../pwhm-v7.6.38/src/`
2. 收集 candidate commands + filename:line citations
3. 用 serialwrap 在 DUT/STA 跑 candidate commands
4. 比 verdict_s vs workbook R/S/T

主 agent SHALL 把 sub-agent raw I/O 與自己的 reasoning 落到 `audit/runs/<RID>/<plugin>/case/D###/agent/`。

fleet sub-agents SHALL NOT 寫 source code、SHALL NOT 操作 serialwrap、SHALL NOT 修改 YAML；違反 → audit 視為 doctrine 違反，須在 evidence 標記 `doctrine_violation`。

#### Scenario: Pass 3 找到證據並 verdict 對齊

- **WHEN** 主 agent 對 D366 派 fleet sub-agents，sub-agent 回傳 `wl -i wlX sr_config srg_obsscolorbmp` + `bcmdrivers/.../wlc_stf.h:263` citation；主 agent 跑 serialwrap 得 verdict_s=`Fail`，workbook R/S/T=`Fail`
- **THEN** 主 agent 構造 proposed.yaml 把 pass_criteria 改成驗證 driver bitmap、跑 verify-edit、decide --bucket=applied

#### Scenario: Pass 3 無證據進 block

- **WHEN** 主 agent 對某 case 派 fleet sub-agents，所有 sub-agent 回 `no_evidence` 或 candidate 命令跑出來都 mismatch workbook
- **THEN** 主 agent 用 `testpilot audit decide --bucket=block` 落桶，evidence 含完整 pass3 trace

### Requirement: YAML edit boundary white-list

audit 對 case YAML 的修改 SHALL 限定在下列 key path：

- `steps[*].command`
- `steps[*].capture`
- `verification_command`（list 內容）
- `pass_criteria[*]`（增 / 刪 / 改任一條）

audit SHALL NOT 修改：

- `id`、`name`、`version`
- `source.*`（含 row, object, api）
- `platform.*`、`bands`、`topology.*`、`test_environment`、`hlapi_command`、`llapi_support`、`implemented_by`
- `setup_steps`、`sta_env_setup`、`test_procedure`
- `steps` 整個 list 的增/刪（只能改既有 step 的 command/capture）

#### Scenario: 允許動 pass_criteria

- **WHEN** audit proposed.yaml 對 D366 增加 `pass_criteria` entry 驗證 driver bitmap
- **THEN** verify-edit 通過

#### Scenario: 禁止動 source.row

- **WHEN** audit proposed.yaml 把 D366 的 `source.row` 從 366 改成 412
- **THEN** verify-edit 拒絕，exit 非 0、stderr 標 `field_scope_violation: source.row`

#### Scenario: 禁止 add 新 step

- **WHEN** audit proposed.yaml 在 D366 的 `steps` list 末尾加一個 `step16_extra_check`
- **THEN** verify-edit 拒絕，stderr 標 `field_scope_violation: steps[].add`

### Requirement: verify-edit gate 與 verify_edit_log

`testpilot audit verify-edit <RID> <case> --yaml <case_yaml_path> --proposed <proposed_yaml_path>` SHALL：

1. 讀取目前 working tree 的 `--yaml <case_yaml_path>` 與 audit `--proposed <proposed_yaml_path>`，做 path-aware diff
2. 驗證 diff 只動 §YAML edit boundary 中的 allowed paths（用 ruamel.yaml + json-pointer 比對 path 集合）
3. 載入 proposed.yaml 跑 `case_schema.validate()`；不過 → fail
4. 驗證 RID 在 active 狀態（manifest.json 存在）
5. 全過 → append 一行到 `audit/runs/<RID>/<plugin>/verify_edit_log.jsonl`：
   ```json
   {"ts": "<ISO8601>", "case": "<D###>", "yaml_path": "<path>",
    "yaml_sha256_before": "...", "yaml_sha256_after_proposed": "...",
    "diff_paths": [...]}
   ```
6. exit 0；fail 時 exit 非 0 + structured stderr

verify_edit_log.jsonl SHALL 是 append-only。

#### Scenario: verify-edit pass 並寫 log

- **WHEN** 主 agent 對 D366 跑 verify-edit，proposed.yaml 通過 schema 與 boundary
- **THEN** verify_edit_log.jsonl 增加一行包含 yaml_sha256_after_proposed；exit 0

#### Scenario: verify-edit fail 不寫 log

- **WHEN** 主 agent 對 D366 跑 verify-edit，proposed.yaml 動到 source.row
- **THEN** verify-edit exit 非 0；verify_edit_log.jsonl 行數不變

### Requirement: Pre-commit hook 強制驗證 YAML provenance

repo SHALL 提供 `scripts/check_audit_yaml_provenance.py` 並掛入 `.pre-commit-config.yaml`：

- 對 staged `plugins/<plugin>/cases/D*.yaml` 文件
- 算當前 sha256
- 掃 `audit/runs/*/<plugin>/verify_edit_log.jsonl`
- 比對：是否有任一 entry 的 `yaml_sha256_after_proposed == 當前 sha256`
- 命中 → pass
- 無命中 → fail with structured message
- escape hatch：commit message 含 `[audit-bypass: <reason>]` → hook pass 但記入 `audit/bypass_log.jsonl`
- soft-skip：當 `audit/` 不存在或 `verify_edit_log.jsonl` 找不到任何檔 → soft warn + skip（fresh clone / CI 環境）

#### Scenario: hook 對齊 verify_edit_log 命中

- **WHEN** PR 把 D366 改成 audit applied 桶的 proposed.yaml 內容；對應 verify_edit_log entry 已存在
- **THEN** pre-commit hook 通過

#### Scenario: hook 對未經 audit 的修改 fail

- **WHEN** developer 直接 vim 改 D366 然後 commit，沒跑 verify-edit
- **THEN** pre-commit hook fail，提示「audit doctrine 要求所有 YAML 編輯經 verify-edit」

#### Scenario: audit-bypass escape hatch

- **WHEN** commit message 含 `[audit-bypass: rename id only]`
- **THEN** hook pass；audit/bypass_log.jsonl 記一行

#### Scenario: fresh clone soft-skip

- **WHEN** repo 剛 clone（`audit/` 不存在），developer 改 YAML 並 commit
- **THEN** hook print soft warn 但 exit 0；commit 通過

### Requirement: Bucket 分類

每筆 case audit 結束時 SHALL 分為下列桶之一：

- `confirmed`：Pass 1 verdict_match，diff 為空
- `applied`：verdict_match ∧ citation_present ∧ citation_verified ∧ field_scope_safe ∧ schema_valid
- `pending`：verdict_match 但有任一 check 不過
- `block`：所有 Pass 都失敗 / workbook missing / workbook ambiguous / verify-edit 失敗 / Pass 3 無 citation

`audit apply <RID>` 預設 SHALL 只套 `applied` 桶；要套 `pending` 必須 `--include-pending` 或 `--cases ...` 明確列出；`block` 桶 SHALL NEVER auto-apply。

#### Scenario: applied 桶自動 apply

- **WHEN** user 執行 `testpilot audit apply <RID>`
- **THEN** 所有 applied 桶內 case 的 proposed.yaml 寫回 plugins/<plugin>/cases/

#### Scenario: pending 桶不自動 apply

- **WHEN** user 執行 `testpilot audit apply <RID>`（無 `--include-pending`）
- **THEN** pending 桶內 case 的 proposed.yaml 不被寫回；user review 後可用 `--include-pending` 或 `--cases` 套用

#### Scenario: block 桶絕不 auto-apply

- **WHEN** user 執行 `testpilot audit apply <RID> --include-pending`
- **THEN** block 桶內 case 仍不被寫回；只能人工修完後重 audit

### Requirement: Resume 與 idempotent

`testpilot audit pass12 <RID>` 與 `testpilot audit init <plugin> --resume <RID>` SHALL 支援續跑：

- 已存在 `case/D###/decision.json` 且 manifest workbook hash 未變 → skip
- 中斷時部分寫的 case 標 `dirty: true` → re-run
- pass12 任何時候可 rerun，行為等價

主 agent 重啟 audit session 時 SHALL 先用 `testpilot audit status <RID>` 拿目前 worklist。

#### Scenario: 中斷後續跑

- **WHEN** audit pass12 跑到第 200 筆中斷；user 再下 `testpilot audit pass12 <RID>`
- **THEN** 已跑完的前 199 筆 skip，從第 200 筆繼續

### Requirement: Block 復原語意

audit `block` SHALL NOT 視為 final state。每次 audit run（pass12 + 主 agent Pass 3）對所有 case 一律重新跑 waterfall，包括上次 block 的。

人工修完 case YAML 後（例如手寫 D366 的 driver bitmap pass_criteria），下一輪 audit run：
- 以新 YAML 拿 verdict_y'
- 若 verdict_y' == workbook → bucket=confirmed
- 若仍 mismatch → 重走 Pass 2 → Pass 3 → 可能再進 block

#### Scenario: 人工修完後重評

- **WHEN** D366 上輪 audit 落 block；user 手寫修 pass_criteria 並 commit；下輪 audit pass12 執行
- **THEN** D366 重跑 Pass 1，若 verdict 對齊 workbook 則進 confirmed；否則繼續走 Pass 2/3

### Requirement: Template YAML 與 underscore-prefix 跳過

audit init SHALL 跳過 `_template.yaml` 與其他 underscore-prefix YAML files，沿用 `load_cases_dir()` 排除規則。這些 fixture 不進 manifest、不產 case 資料夾、不被任何 audit pass 處理。

wifi_llapi 首發 scope = 415 official cases（`plugins/wifi_llapi/cases/D*.yaml`）。

#### Scenario: _template.yaml 不在 manifest

- **WHEN** `testpilot audit init wifi_llapi --workbook ...` 跑完
- **THEN** manifest.json 的 `cases` 列表不含 `_template.yaml` 與其他 underscore-prefix yaml

### Requirement: PR 構造

`testpilot audit pr <RID> [--draft]` SHALL：

1. `git add` audit applied case YAML
2. `git commit` with audit-mode commit message（含 RID + bucket 摘要）
3. `git push`
4. `gh pr create` 開 PR，body 自動帶：RID / bucket counts / acceptance evidence link / 驗證指引

PR 標題 SHALL 包含 RID 後 8 字元；PR body SHALL 引用 `audit/runs/<RID>/<plugin>/summary.md`（可貼 markdown 摘要進 body）。

#### Scenario: pr 開出含 RID 的 PR

- **WHEN** user 執行 `testpilot audit pr <RID>`
- **THEN** GitHub 上出現新 PR，標題含 RID 短碼，body 含 bucket 摘要表

### Requirement: D366 / D369 acceptance

audit 流程 SHALL 把 D366 SRGBSSColorBitmap 與 D369 SRGPartialBSSIDBitmap 的 pass_criteria 校正為驗證 driver bitmap 是否真的被拉起，而非以「副作用缺席」當 success。具體上：

- 主 agent Pass 3 後，proposed.yaml 的 pass_criteria MUST 含 driver bitmap 驗證（透過 `wl -i wl<x> sr_config srg_obsscolorbmp` 或 `srg_pbssidbmp` 取得 bitmap，再以 bit-mask 方式比對）
- rerun 後的 verdict MUST 對齊 workbook R/S/T 標示
- 該兩 case 的 audit 結局 bucket SHALL 為 `applied`
- apply 後 `git diff plugins/wifi_llapi/cases/D366_srgbsscolorbitmap.yaml` 與 `D369_srgpartialbssidbitmap.yaml` SHALL 只動 verification_command 與 pass_criteria；其他欄位（id / name / source / topology / bands / platform 等）MUST 保持不變

#### Scenario: D366 audit 結果

- **WHEN** wifi_llapi 首發 audit run 處理 D366
- **THEN** D366 落 applied 桶；proposed.yaml 的 pass_criteria 含 `wl -i wlX sr_config srg_obsscolorbmp` 對應的 bit-mask 驗證；verdict 對齊 workbook Fail

#### Scenario: D369 audit 結果

- **WHEN** wifi_llapi 首發 audit run 處理 D369
- **THEN** D369 落 applied 桶；proposed.yaml 的 pass_criteria 含 `wl -i wlX sr_config srg_pbssidbmp` 對應的 bit-mask 驗證；verdict 對齊 workbook Fail（混合 band：5G/6G Fail、2.4G Not Supported）

# Audit Mode — Design

- **Spec date:** 2026-04-27
- **Issues:** #36 (Add audit mode, should split with normal test mode) · 衍生自 #31 (workbook ↔ case identity authority)
- **Scope owner:** testpilot core + wifi_llapi plugin（首發）
- **Status:** Draft — awaiting user review

---

## 1. Background & Motivation

TestPilot 同時承載兩種完全不同的工作模式：

1. **Normal test**：依 case YAML 在 DUT/STA 上執行、判 verdict、產 xlsx report。Authoritative source 是 case YAML 本身。
2. **Audit / calibration**：以外部 workbook 為 result authority，回頭比對 case YAML 的 `steps` / `verification_command` / `pass_criteria` 是否合理；不合理就修。Authoritative source 是 workbook + source code。

過去這兩條 path 共用一條 runner，agent 在做 audit work 時可以無差別地：
- 直接 Edit 任意 case YAML（沒有寫入閘）
- 把 audit-only 的 trial-and-error 痕跡（trace、temp capture、為了「對齊 workbook」硬寫的 setter / pass_criteria）寫進 plugins/cases/D*.yaml
- 寫進去後 normal test 會把這份「被汙染的」case 當權威執行，產出 false-positive Pass

`#31` 是這個結構性問題的具體爆點之一（workbook ↔ case identity 漂移），但根因更深：**audit 與 normal test 的 YAML 寫入權限沒有劃線**。

具體例：`D366 SRGBSSColorBitmap` / `D369 SRGPartialBSSIDBitmap`。兩筆 case 的 `pass_criteria` 把「`grep -c ^he_spr_srg_bss_colors= /tmp/wl0_hapd.conf == 0`」當 pass 標的，因為當時 audit operator 觀察到 brcm hostapd 確實沒收到那行 — 所以「沒收到」變成 success criterion。但 IEEE 802.11ax SR Parameter Set 的正確驗證點是「driver SRG bitmap 是否真的有對應 bit set」（`wl -i wlX sr_config srg_obsscolorbmp`）。實測 brcm vendor binding 把字串 `"5,9,13"` 直接 token-positional 塞進 4 個 uint16，根本不是 bit-OR — 這條 case 應該 Fail。但因為 pass_criteria 反向了，目前回 Pass。

**本 spec 的核心命題**：把 audit work 做成有清楚邊界的工作模式，所有 audit 對 YAML 的修改必須走 verify-edit gate + 留 evidence，且 normal test path 不得繞過 audit doctrine 修 YAML。

---

## 2. Scope

### In scope

- 新增 `testpilot audit ...` subcommand 群組（init / pass12 / record / verify-edit / decide / status / summary / apply / pr）
- 新增 `audit/` 工作資料夾（gitignored）作為 audit run 的 evidence 與 bucket 簿記載體
- 新增 `src/testpilot/audit/` Python 套件 — 純機械助手，不呼叫 LLM
- 新增 pre-commit hook：plugins/cases/D*.yaml 的修改必須對應 audit RID 的 verify-edit log
- 改寫 `docs/audit-guide.md` 為主 agent 在 audit session 內遵循的 doctrine
- 同步更新 `AGENTS.md` / `docs/plan.md` / `docs/todos.md` / `README.md` / `CHANGELOG.md`
- 首發落地對象：`wifi_llapi` plugin 的 415 official cases（不含 `_template.yaml`）

### Out of scope

- 修改 `src/testpilot/core/agent_runtime.py` 或 `core/copilot_session.py`（audit CLI 不直呼 LLM SDK）
- 修改 `case_schema.py` 既有欄位定義（**只能修改或刪減 YAML 欄位內容，不得新增 top-level key**）
- 自動化 batch 跑 415 筆 case 的 LLM 抽取邏輯（Pass 3 由主 agent 在 Copilot session 內負責）
- workbook xlsx 的產生 / round-trip
- 跨 plugin audit dispatch（首發只支援 wifi_llapi；helper API 預留 plugin 參數）
- 修改任何 source code（driver / pwhm / hostapd / mod-whm-brcm 等）— 違反 #36 期望 #8

---

## 3. Roles & Boundaries

| 元件 | 角色 | 可寫範圍 |
|---|---|---|
| **Copilot agent mode** | Audit session 入口；起 unattended LLM agent | n/a |
| **主 agent**（在 Copilot session 內） | 統籌 RID lifecycle、決策 bucket、做 live serialwrap probe、寫 YAML | `audit/` + 經 verify-edit gate 後寫 `plugins/<plugin>/cases/D*.yaml` |
| **fleet sub-agents**（主 agent 透過 Task tool 派出） | read-only source code survey | nothing（只回傳 JSON） |
| **`testpilot audit ...` CLI** | 機械助手：workbook lookup、Pass 1/2 預過濾、verify-edit gate、bucket 簿記、PR 構造 | 只寫 `audit/`；apply/pr step 才會碰 plugins/cases/ |
| **doctrine docs** | `docs/audit-guide.md`（rewrite）為主 agent 的操作章法 | n/a |
| **pre-commit hook** | 強制執行：YAML diff 必須對應 verify-edit log | n/a（read-only check） |

**關鍵不變式**：

1. 只有主 agent 在 active audit RID 內、透過 verify-edit gate 才能修改 `plugins/<plugin>/cases/D*.yaml`
2. fleet sub-agent 只能 read source；不得 spawn serialwrap、不得 Edit 任何檔
3. audit CLI 不呼叫任何 LLM SDK；所有 LLM 互動屬於主 agent 內部行為，不從 audit Python 模組發起
4. normal `testpilot run` 路徑不會觸發 audit YAML rewrite；反向亦然（normal run 改 YAML 要走 alignment 路徑，不走 audit）

---

## 4. CLI Surface

```bash
# RID lifecycle
testpilot audit init <plugin> --workbook <path>
                              [--cases D###[,D###]]
                              [--sheet <name>]
                              [--col-object F --col-api E
                               --col-steps G --col-output H
                               --col-result R,S,T]
                              # 印出 RID

testpilot audit status <RID>          # bucket 計數 + needs_pass3 worklist
testpilot audit summary <RID>         # render audit/runs/<RID>/<plugin>/summary.md

# 純 py 預過濾（idempotent，主 agent 任何時間可 rerun）
testpilot audit pass12 <RID>          # 跑 Pass 1+2，更新 bucket，標 needs_pass3

# 主 agent Pass 3 落筆
testpilot audit record <RID> <case> --evidence <json>          # 落 pass3_source.json
testpilot audit verify-edit <RID> <case_yaml_path>             # 驗 diff scope + schema + RID active
testpilot audit decide <RID> <case> --bucket <applied|pending|block>
                                    [--proposed-yaml <path>]
                                    [--reason <text>]

# 終局
testpilot audit apply <RID> [--bucket applied[,pending]] [--cases ...]
testpilot audit pr <RID> [--draft]    # git add/commit/push + gh pr create
```

**RID 格式**：`<git_short_sha>-<ISO8601>`（e.g. `c2db948-2026-04-27T143000`）。包含 commit 短 SHA 確保可追溯到觸發時 repo 狀態。

**Workbook 路徑解析**：CLI `--workbook` 優先；未給則 fallback `audit/workbooks/<plugin>.xlsx`；皆無 → init 失敗。

**欄位 auto-discovery**：init 時掃 sheet header row 找 `Test Steps` / `Command Output` / 三 band result 欄；找不到才用 `--col-*` 強制覆蓋。snapshot 寫進 `audit/runs/<RID>/<plugin>/manifest.json`。

---

## 5. Decision Waterfall

```
┌────────────── 純 py 預過濾（pass12 CLI，可 idempotent rerun）──────────────┐
│                                                                            │
│ Pass 1 (mechanical):                                                       │
│   讀 YAML → 跑既有 plugin runner facade run_one_case(yaml_path)            │
│   → verdict_y vs workbook R/S/T                                            │
│   match → bucket=confirmed (no diff)                                       │
│   mismatch → 進 Pass 2                                                     │
│                                                                            │
│ Pass 2 (mechanical extract):                                               │
│   regex/heuristic 從 workbook G/H prose 抽 candidate commands:             │
│     - 行首 token: ubus-cli|wl|hostapd_cli|grep|cat|sed|awk|ip|iw|hostapd   │
│     - fenced code block (```...```)                                        │
│     - 內嵌 single-line command（行內 `...` quote）                         │
│   抽到 unambiguous list → 走 plugin runner rerun                           │
│   verdict_w == workbook + 抽出來的命令逐字回查 G/H 為 substring → 候選     │
│   抽不到 / ambiguous / verdict 仍 mismatch → 標 needs_pass3                │
│                                                                            │
└────────────────── 主 agent + fleet sub-agents（Pass 3）────────────────────┘

主 agent 拿 needs_pass3 worklist，逐 case 做：

  1. 透過 Task tool 派 fleet sub-agents 平行 grep:
       bcmdrivers/.../impl107/
       userspace/.../prpl_brcm/mods/mod-whm-brcm/
       altsdk/.../pwhm-v7.6.38/src/
     → 拿回 candidate commands + filename:line citations

  2. 主 agent 用 serialwrap 在 DUT/STA 跑 candidate commands
  3. 主 agent 比 verdict_s vs workbook R/S/T:
       match → 構造 proposed YAML（只動 allowed fields），跑
                 testpilot audit verify-edit <RID> <yaml>
                 testpilot audit record   <RID> <case> --evidence pass3.json
                 testpilot audit decide   <RID> <case> --bucket applied|pending
       mismatch / 無 source citation / verify-edit 不過 → 
                 testpilot audit decide   <RID> <case> --bucket block

  4. fleet sub-agent 與主 agent 的 raw I/O 全落
       audit/runs/<RID>/<plugin>/case/D###/agent/
         fleet_<sa_id>.json
         main_<turn>.json
```

**關鍵 invariants**：

- Pass 1/2 是 deterministic Python；可 rerun 不影響語意
- Pass 2 抽到的命令必須是 G/H 文字 substring（regex 級驗證），不得「重新組合改寫」
- Pass 3 由主 agent 負責；audit CLI 不做命令抽取
- Pass 3 的 YAML 修改必須有 source citation（filename + line + snippet hash），且 audit-runner mechanical 驗證該檔該行存在 — 沒有 citation 一律進 block

**Pass 2 抽取規則細節**（mechanical extractor）：

| 規則 | 範例 | 觸發 |
|---|---|---|
| 行首 shell token | `ubus-cli "WiFi.Radio.1.IEEE80211ax.SRGBSSColorBitmap?"` | 命中 ALLOWED_TOKENS 集合 |
| Fenced block | `` `wl -i wl0 sr_config srg_obsscolorbmp` `` | regex `\`([^`]+)\`` |
| Triple-fenced | `\`\`\`bash\nwl -i wl0 sr_config srg_obsscolorbmp\n\`\`\`` | 多行 code block |
| 否決 | 中文敘述 / 沒對應 token / 包含 `<placeholder>` | skip，需要 Pass 3 |

`ALLOWED_TOKENS = {"ubus-cli", "wl", "hostapd_cli", "grep", "cat", "sed", "awk", "ip", "iw", "hostapd", "wpa_cli"}`。

---

## 6. Workbook Lookup（語意鍵，不靠 row）

每筆 workbook row 載入後建立 index：

```python
key = (normalize(source.object), normalize(source.api))
# normalize: strip trailing dot; collapse {i} placeholder; strip whitespace
# (preserve case — TR-181 names are case-significant)
value = WorkbookRow(R, S, T, G, H, raw_row_index, raw_sheet_row_number)
```

YAML loop：

```python
for yaml_path in iter_official_cases(plugin):  # 跳過 _*.yaml
    case = load_case(yaml_path)
    key = (normalize(case.source.object), normalize(case.source.api))
    if key not in workbook_index:
        bucket = "block"; reason = "workbook_row_missing"
        continue
    if len(workbook_index[key]) > 1:
        bucket = "block"; reason = "workbook_row_ambiguous"
        candidates = [...]
        continue
    workbook_row = workbook_index[key][0]
    # waterfall 開始
```

**raw_row_index** 仍寫進 `case/D###/manifest.json` 供人對照（解 #31 漂移時 cross-check 用），但不是比對來源。

---

## 7. Audit Work Directory Layout

```
/audit/                                       (gitignored)
├── workbooks/
│   └── <plugin>.xlsx                         人工放；CLI --workbook 優先
├── runs/
│   └── <git_short_sha>-<ISO8601>/            RID
│       └── <plugin>/
│           ├── manifest.json                 scope, cli_args, runner_meta
│           ├── workbook_snapshot.xlsx        本次跑時的 workbook 副本（雜湊鎖定）
│           ├── workbook_index.json           semantic key → row
│           ├── verify_edit_log.jsonl         append-only；每筆 verify-edit 一行
│           ├── case/
│           │   └── D###/
│           │       ├── manifest.json         (yaml_path, workbook_row_meta, scope)
│           │       ├── pass1_baseline.json   {verdict, capture, log_paths}
│           │       ├── pass2_workbook.json   {extracted_cmds, verdict_w, capture_w}
│           │       ├── pass3_source.json     主 agent 落 evidence（記錄 sub-agent citations + verdict_s）
│           │       ├── proposed.diff         unified diff against current YAML
│           │       ├── proposed.yaml         full new YAML，schema-validated
│           │       ├── decision.json         {bucket, reason, confidence_checks}
│           │       └── agent/
│           │           ├── fleet_<sa_id>.json     sub-agent raw I/O
│           │           └── main_<turn>.json       主 agent 自身 reasoning trace（optional）
│           ├── buckets/
│           │   ├── confirmed.jsonl
│           │   ├── applied.jsonl
│           │   ├── pending.jsonl
│           │   └── block.jsonl
│           └── summary.md                    給人讀的 end-of-run 報告
└── history/
    └── <RID>.summary.md → ../runs/<RID>/<plugin>/summary.md
```

`.gitignore` 增加：
```
# Audit working directory（local-only evidence）
/audit/
```

---

## 8. Bucket Classification

每個 case 結束時計算下列 boolean：

| Check | 描述 |
|---|---|
| `verdict_match` | rerun verdict == workbook R/S/T |
| `citation_present` | Pass 2 抽出的命令有對應 G/H substring，或 Pass 3 有 filename:line |
| `citation_verified` | substring / filename:line 真的存在（mechanical check by audit CLI） |
| `field_scope_safe` | YAML diff 只動 `steps[*].command`、`steps[*].capture`、`verification_command`、`pass_criteria[*]` |
| `schema_valid` | 改寫後的 YAML 通過 `case_schema.py` 驗證 |

| Bucket | 條件 | 由誰寫入 |
|---|---|---|
| `confirmed` | Pass 1 verdict_match（diff 為空） | pass12 CLI |
| `applied` | verdict_match ∧ citation_present ∧ citation_verified ∧ field_scope_safe ∧ schema_valid | pass12 CLI（Pass 2 命中時）或主 agent decide CLI |
| `pending` | verdict_match 但有任一其他 check 不過 | 同上 |
| `block` | ¬verdict_match（所有 Pass 都失敗）/ workbook 行 missing/ambiguous / verify-edit 失敗 / Pass 3 無 citation | 同上 |

`apply` step 預設套 `applied`；`pending` 必須 `--include-pending` 或 `--cases` 明確列出；`block` 永不 auto-apply。

---

## 9. Edit Boundary（YAML 寫入閘）

### 9.1 允許修改的 YAML 範圍

只允許動下列 key path：

- `steps[*].command`
- `steps[*].capture`
- `verification_command`（list）
- `pass_criteria[*]`（增 / 刪 / 改任一條）

**禁止動**：

- `id`、`name`、`version`
- `source.*`（含 row, object, api）
- `platform.*`、`bands`、`topology.*`、`test_environment`、`hlapi_command`、`llapi_support`、`implemented_by`
- `setup_steps`、`sta_env_setup`、`test_procedure`（這些是 audit 上下文敘述，不是執行語意）
- `steps[*]` 增加 / 刪除整個 step（只能改既有 step 的 command/capture）

> **設計理由**：audit 修的是「驗證行為」，不是「測項身分 / topology / 元資料」。後者一旦動了，就跨入 alignment / refactor 範疇 — 那是另一條工作流（runtime alignment 已在 AGENTS.md §Case Discovery Convention 規範）。

### 9.2 verify-edit gate 的工作流

主 agent 在 audit session 內**任何**對 plugins/cases/D*.yaml 的 Edit/Write 之前，必須先：

```bash
testpilot audit verify-edit <RID> <case_yaml_path>
```

CLI 行為：

1. 讀目前 working tree 的 `<case_yaml_path>` 與 audit 對應 `proposed.yaml`，做 unified diff
2. 驗證 diff 只動 §9.1 allowed paths（用 ruamel.yaml + json-pointer 比對 path 集合）
3. 載入 proposed.yaml 跑 `case_schema.validate()`；不過 → fail
4. 驗證 RID 在 active 狀態（manifest.json 存在 + `.lock` 存在或最近 24h heartbeat）
5. 全過 → append 一行到 `audit/runs/<RID>/<plugin>/verify_edit_log.jsonl`：
   ```json
   {"ts": "2026-04-27T14:32:11Z", "case": "D366",
    "yaml_path": "plugins/wifi_llapi/cases/D366_srgbsscolorbitmap.yaml",
    "yaml_sha256_before": "...", "yaml_sha256_after_proposed": "...",
    "diff_paths": ["pass_criteria[8]", "pass_criteria[9]", "verification_command"]}
   ```
6. exit 0；fail 時 exit 非 0 + structured stderr

**主 agent 不得**直接 Edit/Write YAML 而不經 verify-edit；違反 → 主 agent 自律失敗 + pre-commit hook 第二道防線擋下。

---

## 10. Pre-commit Hook（強制層）

新增 `scripts/check_audit_yaml_provenance.py`，掛進 repo `.pre-commit-config.yaml`（既有則 append）：

```yaml
- repo: local
  hooks:
    - id: audit-yaml-provenance
      name: Audit YAML provenance check
      entry: python scripts/check_audit_yaml_provenance.py
      language: system
      files: '^plugins/[^/]+/cases/D\d+_.*\.yaml$'
      pass_filenames: true
```

Hook 邏輯：

1. 收 staged files（限 `plugins/*/cases/D*.yaml`）
2. 對每個 file：
   - 算當前 sha256
   - 掃 `audit/runs/*/<plugin>/verify_edit_log.jsonl`
   - 比對：是否有任一 entry 的 `yaml_sha256_after_proposed == 當前 sha256`
   - 命中 → pass；無 → fail with structured message:
     ```
     ERROR: plugins/wifi_llapi/cases/D366_xxx.yaml has changes not registered with any audit RID.
     Audit doctrine requires all YAML edits go through `testpilot audit verify-edit <RID>`.
     If this is intentional metadata fix outside audit (e.g. id rename), use `--allow-no-audit-rid` 
     and document in commit message.
     ```
3. 額外允許 escape hatch：commit message 含 `[audit-bypass: <reason>]` → hook pass 但記入 `.audit/bypass_log.jsonl`（`/audit/` 是 gitignored；bypass log 同 dir）

> **註**：`audit/` 是 gitignored 所以 `verify_edit_log.jsonl` 在別人 clone 後不存在。CI hook 只在「同一個 RID 還在當前 dev 的 worktree」時可驗。對 PR 的 review，會由 audit summary md（手動貼 PR body）+ verify_edit_log 摘要承擔可追溯性。如果未來要 CI-side enforcement，需把 verify_edit_log 改成 commit attestation（簽到 commit trailer）— 列為 future work。

---

## 11. Resume / Block Re-evaluation / Template

### 11.1 Resume

`testpilot audit pass12 <RID>` 與主 agent Pass 3 流程都是 idempotent：

- 已存在 `case/D###/decision.json` 且未過期（manifest 中的 workbook hash 未變）→ skip
- 中斷時部分寫的 case 標記 `dirty: true` → re-run 該 case
- `pass12` 可任何時候 rerun，行為等價

主 agent 重啟 audit session 時，先 `testpilot audit status <RID>` 拿目前 worklist。

### 11.2 Block 復原

人工修完 YAML 後（例如手寫 D366 的 bitmap pass_criteria），下一輪 audit run（同 RID 或新 RID）：

- pass12 重跑 Pass 1：以新 YAML 拿 verdict_y'
- 如果 verdict_y' == workbook → bucket=confirmed
- 如果仍 mismatch → 重走 Pass 2 → Pass 3 → 可能再進 block

> **語意**：block 不是 final state；每次 audit run 對所有 case 一律重新跑 waterfall。block 只是「上一輪到此為止的暫時結果」。

### 11.3 Template skip

`_template.yaml` 與其他 underscore-prefix fixtures（沿用 `load_cases_dir()` 排除規則）：

- audit init 不收進 manifest
- 不產 case 資料夾
- schema validation 由現有 pytest（`test_<plugin>_plugin_runtime.py`）把關，audit 不重做

明確 scope = 415 official cases。

---

## 12. LLM Integration（修訂後：只在 Pass 3 主 agent 內部）

audit Python 套件 (`src/testpilot/audit/`) **完全不呼叫**任何 LLM SDK。

Pass 3 的 LLM 互動由主 agent 在 Copilot session 內透過 Task tool 派 fleet sub-agents 完成：

- 主 agent prompt: 「對 case D###，object=X、api=Y，請 fleet sub-agents grep 下列 path 找對應 set/get/iovar 命令與 filename:line citations」
- Sub-agents 限制：read-only（不呼叫 serialwrap、不 Edit、不 Write source）
- Sub-agent 回傳格式（建議，agent 自律）：
  ```json
  {
    "candidate_commands": [
      {
        "command": "wl -i wl0 sr_config srg_obsscolorbmp",
        "citations": [
          {"file": "bcmdrivers/.../wlc_stf.h", "line": 263,
           "snippet": "uint16 srg_pbssid_bmp[4];"}
        ],
        "rationale": "..."
      }
    ],
    "no_evidence": false
  }
  ```
- 主 agent 收到後落到 `case/D###/agent/fleet_<sa_id>.json`，用 serialwrap 跑 commands，比 verdict_s
- 採納哪一條由主 agent 決策；audit CLI 只在 record / verify-edit / decide 時 mechanical 驗 citation 是否存在於 source（grep 該 file 該 line）

`core/agent_runtime.py` 與 `core/copilot_session.py` 不被 audit 模組使用，保留給 normal `run` 路徑。

---

## 13. Documentation Updates

audit mode 上線需同步更新：

| 檔 | 修改內容 |
|---|---|
| `docs/audit-guide.md` | 重寫為主 agent doctrine：session 進入條件、角色分工、verify-edit 必經流程、Pass 1/2/3 操作步驟、bucket 結局表 |
| `AGENTS.md` | 新增 §Audit Mode Governance — RID 強制 / verify-edit 必經 / pre-commit hook / `audit/` gitignored |
| `docs/plan.md` | §4 Phase 列表加「Audit Mode Phase」 |
| `docs/todos.md` | 新增 audit doctrine 落地待辦 |
| `README.md` | Commands 區塊加 audit 群組 |
| `CHANGELOG.md` | Unreleased 段加 feat(audit-mode) entry |
| `.gitignore` | 加 `/audit/` |
| `.pre-commit-config.yaml` | 加 `audit-yaml-provenance` hook |

---

## 14. Footgun Prevention Summary

| 防護 | 機制 |
|---|---|
| CLI 路徑分離 | `audit` ≠ `run`，不共用 entry |
| pass12 全程 read-only 對 plugins/ | 只寫 `audit/` |
| YAML edit allowlist | §9.1 white-list；verify-edit 用 json-pointer 級檢查 |
| 主 agent 自律層 | doctrine 規定 verify-edit 必經 |
| 強制層 | pre-commit hook：YAML 變動沒對應 verify_edit_log → fail |
| LLM 證據驗證 | citation mechanical check（grep file/line）；無 citation → block |
| RID 隔離 | 所有 evidence 在 `/audit/runs/<RID>/`；不跨 run 污染 |
| Resume 安全性 | workbook hash + manifest snapshot；workbook 換版本則新 RID |
| `audit/` gitignored | 不會誤 commit evidence；audit-only data 永遠不入 main |

---

## 15. Implementation Phases（給後續 writing-plans 收口用）

**Phase A — Core scaffolding（無 hardware 互動）**

1. `src/testpilot/audit/` 套件骨架（init/manifest/workbook_index/bucket）
2. CLI subcommand 群組（init/status/summary，pure file/state operation）
3. `audit/` 目錄與 .gitignore
4. workbook semantic-key index + auto-discovery
5. 單元測試：semantic key normalize、index 衝突偵測、resume 行為

**Phase B — Pass 1/2 mechanical**

1. `run_one_case_for_audit()` thin facade — 放 `src/testpilot/audit/runner_facade.py`，呼叫既有 `plugins/<plugin>/plugin.Plugin.execute_case()` 等 public 介面，不改 plugin.py 內部實作；若 plugin 缺乏 stable public hook，補一個薄 method 不視為 "改 source code"，因為它只暴露既有行為，不變更 normal run 結果
2. Pass 1 implementation
3. Pass 2 mechanical extractor + token allowlist
4. `pass12` CLI
5. 整合測試：對 ~10 筆已知 confirmed case 跑通

**Phase C — verify-edit + pre-commit**

1. `verify-edit` CLI + verify_edit_log
2. allowlist json-pointer 檢查
3. `scripts/check_audit_yaml_provenance.py`
4. `.pre-commit-config.yaml` 接入
5. 測試：故意違規 commit 應被擋；audit-bypass escape hatch 應通

**Phase D — Pass 3 / record / decide / apply / pr**

1. `record` / `decide` CLI
2. `apply` CLI（套 bucket → 寫 plugins/cases/）
3. `pr` CLI（git + gh）
4. 文件同步（§13 全部）
5. 主 agent doctrine（`docs/audit-guide.md` rewrite）

**Phase E — wifi_llapi 首發**

1. 起 unattended Copilot audit session
2. `testpilot audit init wifi_llapi --workbook 0401.xlsx`
3. `pass12`
4. 主 agent 跑 Pass 3 worklist
5. End-of-run review → apply → pr
6. PR review + merge

---

## 16. Risks & Mitigations

| 風險 | 緩解 |
|---|---|
| Pass 2 mechanical extraction 命中率低，所有 case 都掉到 Pass 3 → 主 agent 工作量沒被預過濾減少 | 設計上仍可運作；token allowlist 可逐步擴；最壞情況下 Pass 1 仍有效預過濾 confirmed 桶 |
| pre-commit hook 在 fresh clone 上沒有 `audit/runs/*/verify_edit_log.jsonl` → 永遠 fail | hook 邏輯：當 audit/ 不存在或 verify_edit_log 不存在時 → soft warn + auto-skip（與 audit-bypass 同處理）；只有當 audit/ 存在但 log 找不到對應 sha256 時才 hard fail |
| 主 agent 違反 doctrine 直接 Edit YAML 不過 verify-edit | pre-commit hook 第二道防線；commit 時擋下；user review PR 時也看得到 |
| workbook 與 case YAML 都動，造成 RID 期間 workbook 變化 | manifest snapshot workbook hash；rerun 時若 hash 不符 → 強制起新 RID |
| 主 agent 在 Pass 3 拿到 sub-agent 不可信的 citation（filename 假、line 不對） | audit CLI mechanical check：grep file 並比對 snippet hash；不過則 block |
| audit RID 累積過多 → /audit/ 膨脹 | history/ 只 symlink summary；evidence 老化由 user 手動清；可加 `testpilot audit gc` future feature |

---

## 17. Open Questions（spec 完成後 writing-plans 階段再決）

- pre-commit hook 的「audit/ 不存在 → soft skip」邏輯細節（是否分 dev / CI 兩種行為）
- `testpilot audit pr` 對既有 `gh pr create` 的 PR template 整合方式
- Pass 2 token allowlist 是否要可配置（plugin-level allowlist override）
- RID lock 機制（`.lock` 文件 + heartbeat）的具體 timeout 與 stale recovery
- bucket jsonl 的版本演進策略（schema 加欄位時的 backward compat）

以上不影響本 spec 的整體架構，留待 writing-plans 細化。

---

## 18. Acceptance Criteria

本 spec 完成 implementation 後驗收：

1. `testpilot audit init wifi_llapi --workbook <path>` 成功產出 RID 與 manifest，415 official cases 進 worklist，`_template.yaml` 不在內
2. `testpilot audit pass12 <RID>` 跑完，confirmed + applied + pending + block bucket 與 needs_pass3 worklist 加總 == 415，confirmed 桶非空
3. 主 agent 在 Copilot session 內跑 Pass 3 worklist，每筆 needs_pass3 case 落 decision.json
4. `testpilot audit verify-edit` 對違反 §9.1 的 diff 一律拒絕（含手寫測試 case）
5. pre-commit hook 對未經 verify-edit 的 YAML 變動擋下；audit-bypass escape hatch 可繞但記 log
6. `testpilot audit apply <RID>` 套 applied 桶後，`git diff plugins/<plugin>/cases/` 只動 §9.1 allowed paths
7. `testpilot audit pr <RID>` 開出 PR，body 含 RID + bucket 摘要 + 驗證指引
8. D366 / D369 在主 agent Pass 3 後，pass_criteria 含 driver bitmap 驗證（`wl sr_config srg_*bmp`），rerun verdict 對齊 workbook 的 Fail
9. `_template.yaml` 與其他 `_*.yaml` 在 audit run 期間保持原樣不被觸碰
10. `audit/` 不被 commit；`docs/audit-guide.md` 與 AGENTS.md 同步更新

---

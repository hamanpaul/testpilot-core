## 1. Phase A — Core scaffolding（無 hardware 互動）

- [ ] 1.1 建立 `src/testpilot/audit/` 套件骨架，新增 `__init__.py` 與 module skeleton (`manifest.py` / `workbook_index.py` / `bucket.py` / `verify_edit.py` / `pass12.py` / `runner_facade.py` / `pr.py`)
- [ ] 1.2 新增 `audit/` 目錄結構（含 `workbooks/` / `runs/` / `history/`）並把 `/audit/` 加進 repo 根 `.gitignore`
- [ ] 1.3 實作 RID 生成（`<git_short_sha>-<ISO8601>` 格式）與 manifest.json schema、`.lock` 機制（簡單 file lock）
- [ ] 1.4 實作 workbook semantic-key index：`(normalize(object), normalize(api))` → WorkbookRow；含 normalize 函式（去 trailing dot、collapse `{i}`、strip whitespace、保留 case）
- [ ] 1.5 實作 workbook 欄位 auto-discovery（掃 header row 找 Test Steps / Command Output / 三 band result column）
- [ ] 1.6 實作 bucket 簿記模組（`confirmed.jsonl` / `applied.jsonl` / `pending.jsonl` / `block.jsonl` / `needs_pass3.jsonl` 的 append-only 寫入）
- [ ] 1.7 在 `src/testpilot/cli.py` 追加 `audit` subcommand 群組，先實作 `init` / `status` / `summary` 三個 subcommand（不含 pass12 / Pass 3 / apply / pr）
- [ ] 1.8 unit tests：semantic key normalize（含 `{i}` collapse、去 trailing dot）
- [ ] 1.9 unit tests：workbook index 衝突偵測（ambiguous → 多 row 對同 key）
- [ ] 1.10 unit tests：missing row 偵測（YAML key 在 workbook 找不到對應 row）
- [ ] 1.11 unit tests：RID 生成可重現性 + .lock 取得/釋放
- [ ] 1.12 integration test：`testpilot audit init wifi_llapi --workbook fixtures/sample.xlsx` 產出 RID + manifest，415 cases 進 worklist，`_template.yaml` 不在內

## 2. Phase B — Pass 1/2 mechanical

- [ ] 2.1 實作 `runner_facade.run_one_case_for_audit(plugin, yaml_path)` thin facade — 呼叫既有 `plugins/<plugin>/plugin.Plugin.execute_case()` 等 public 介面；不改 plugin.py 內部實作
- [ ] 2.2 若 `wifi_llapi/plugin.py` 缺 stable public hook，補一個薄方法暴露既有行為（不變更 normal run 結果）
- [ ] 2.3 實作 Pass 1：跑 case YAML 原樣 → 比 verdict_y vs workbook R/S/T → 一致落 confirmed / 不一致進 Pass 2
- [ ] 2.4 實作 Pass 2 mechanical extractor：行首 token allowlist（`ubus-cli|wl|hostapd_cli|grep|cat|sed|awk|ip|iw|hostapd|wpa_cli`）、fenced code block (` ``` ` 與 `` ` ``)、行內 single-line 命令引用
- [ ] 2.5 實作 Pass 2 citation 驗證：抽出來的命令必須是 G/H 文字 substring（regex 級驗證）
- [ ] 2.6 實作 Pass 2 rerun：抽到 unambiguous list → 透過 facade rerun → 比 verdict_w
- [ ] 2.7 實作 Pass 2 落桶邏輯：verdict_w 對齊 + citation 通過 → 候選 applied；抽不到 / ambiguous / verdict 不齊 → needs_pass3
- [ ] 2.8 實作 `testpilot audit pass12 <RID>` CLI subcommand，遍歷 manifest 跑 Pass 1+2
- [ ] 2.9 實作 pass1_baseline.json / pass2_workbook.json evidence schema 與寫入
- [ ] 2.10 實作 `--resume` 邏輯：已存在 decision.json 且 manifest workbook hash 未變 → skip
- [ ] 2.11 unit tests：Pass 2 mechanical extractor 對各種 G/H format（fenced / 行首 / 行內 / 中文 prose / placeholder）
- [ ] 2.12 unit tests：citation substring 驗證（命中 / 不命中 / 部分命中）
- [ ] 2.13 integration test：對 ~10 筆已知 confirmed case 跑通 pass12，全落 confirmed 桶
- [ ] 2.14 integration test：對 D366 跑 pass12，預期 Pass 1 mismatch（YAML 回 Pass、workbook 期待 Fail）→ Pass 2 抽不到 driver-level command（workbook G 沒明寫 wl sr_config）→ needs_pass3

## 3. Phase C — verify-edit gate + pre-commit hook

- [ ] 3.1 實作 YAML edit boundary white-list 檢查：用 ruamel.yaml 載入、json-pointer 比對 diff path 集合，限定 `steps[*].command`、`steps[*].capture`、`verification_command`、`pass_criteria[*]`
- [ ] 3.2 實作 schema validation hook：proposed.yaml 跑 `case_schema.validate()` 才放行
- [ ] 3.3 實作 `testpilot audit verify-edit <RID> <case_yaml_path>` CLI：boundary check + schema check + RID active check + append `verify_edit_log.jsonl`
- [ ] 3.4 實作 verify_edit_log.jsonl 為 append-only，每行包含 `{ts, case, yaml_path, yaml_sha256_before, yaml_sha256_after_proposed, diff_paths}`
- [ ] 3.5 實作 `scripts/check_audit_yaml_provenance.py` pre-commit hook：對 staged plugins/cases/D*.yaml 算 sha256、掃 verify_edit_log.jsonl 找命中
- [ ] 3.6 實作 hook escape hatch：commit message 含 `[audit-bypass: <reason>]` → pass + 記 `audit/bypass_log.jsonl`
- [ ] 3.7 實作 hook soft-skip：`audit/` 不存在或 verify_edit_log 全空 → soft warn + exit 0
- [ ] 3.8 把 hook 接入 `.pre-commit-config.yaml`
- [ ] 3.9 unit tests：boundary 違反偵測（動 source.row / steps add / pass_criteria 改）
- [ ] 3.10 unit tests：schema invalid YAML 拒絕
- [ ] 3.11 unit tests：verify_edit_log append-only 不被覆寫
- [ ] 3.12 integration test：故意違規 commit（手寫改 D366）→ pre-commit hook 擋下
- [ ] 3.13 integration test：經 verify-edit 後 commit → hook 通過
- [ ] 3.14 integration test：commit message 含 `[audit-bypass: rename id]` → hook pass + bypass_log 新增一行
- [ ] 3.15 integration test：fresh clone（無 audit/ 目錄）對 plugins/cases/D*.yaml 任意修改 commit → hook soft-skip 通過

## 4. Phase D — Pass 3 evidence / decide / apply / pr

- [ ] 4.1 實作 `testpilot audit record <RID> <case> --evidence <json>` CLI：把主 agent Pass 3 evidence 落 `case/D###/pass3_source.json`
- [ ] 4.2 實作 record CLI 的 citation mechanical 驗證：grep filename 並比對 line snippet hash；不過則錯回 stderr
- [ ] 4.3 實作 `testpilot audit decide <RID> <case> --bucket <applied|pending|block> [--proposed-yaml <path>] [--reason <text>]` CLI
- [ ] 4.4 實作 decide CLI 的 confidence checks（verdict_match / citation_present / citation_verified / field_scope_safe / schema_valid）並寫 decision.json
- [ ] 4.5 實作 `testpilot audit apply <RID> [--bucket applied[,pending]] [--cases ...] [--include-pending]` CLI：套 proposed.yaml 寫回 plugins/<plugin>/cases/
- [ ] 4.6 實作 apply 邏輯：default 只套 applied 桶；pending 需 `--include-pending` 或 `--cases` 顯式列；block 永不 auto-apply
- [ ] 4.7 實作 apply 後二次 schema validate（防 race condition）
- [ ] 4.8 實作 `testpilot audit pr <RID> [--draft]` CLI：git add / commit（audit-mode message 含 RID + bucket 摘要）/ push / `gh pr create`
- [ ] 4.9 實作 PR body 模板：RID、bucket counts table、summary.md 引用、acceptance evidence 連結
- [ ] 4.10 實作 `testpilot audit summary <RID>` 產出 markdown summary：bucket table、per-bucket case list、pending review checklist、blocker reasons
- [ ] 4.11 unit tests：decide bucket 條件矩陣（5 boolean checks → bucket 對應）
- [ ] 4.12 unit tests：apply 對 block 桶不動 plugins/cases/
- [ ] 4.13 integration test：apply 套 applied 桶 → `git diff plugins/wifi_llapi/cases/` 只動 allowed paths
- [ ] 4.14 integration test：pr CLI 模擬 dry-run（用 `gh pr create --dry-run` 或環境變數隔離）

## 5. Phase E — wifi_llapi 首發 audit

- [ ] 5.1 預備 0401.xlsx workbook 副本到 `audit/workbooks/wifi_llapi.xlsx`
- [ ] 5.2 起 unattended Copilot audit session，讀新 `docs/audit-guide.md` doctrine
- [ ] 5.3 主 agent 跑 `testpilot audit init wifi_llapi --workbook audit/workbooks/wifi_llapi.xlsx`，記下 RID
- [ ] 5.4 主 agent 跑 `testpilot audit pass12 <RID>`，等待全 415 case 預過濾完成
- [ ] 5.5 主 agent 用 `testpilot audit status <RID>` 拿 needs_pass3 worklist
- [ ] 5.6 主 agent 對 D366 派 fleet sub-agents 做 source survey（impl107 + mod-whm-brcm + pwhm）→ 跑 serialwrap → record → verify-edit → decide
- [ ] 5.7 主 agent 對 D369 同樣流程
- [ ] 5.8 主 agent 對 needs_pass3 worklist 內其餘 case 逐筆推理（保持 single-case discipline）
- [ ] 5.9 主 agent 跑 `testpilot audit summary <RID>` 產出 end-of-run 報告
- [ ] 5.10 user review summary.md + 各 bucket jsonl
- [ ] 5.11 user 跑 `testpilot audit apply <RID>` 套 applied 桶（含 D366/D369）
- [ ] 5.12 user review pending 桶內 case，逐筆 `--cases` apply 或留 pending
- [ ] 5.13 跑 `uv run pytest -q` 確認無 regression
- [ ] 5.14 跑 `testpilot audit pr <RID>` 開 PR
- [ ] 5.15 PR review + merge

## 6. Documentation 同步

- [ ] 6.1 改寫 `docs/audit-guide.md` 為主 agent doctrine（取代現有 prose-driven 流程）
- [ ] 6.2 在 `AGENTS.md` 加 §Audit Mode Governance 段（RID 強制 / verify-edit 必經 / pre-commit hook / `audit/` gitignored）
- [ ] 6.3 在 `docs/plan.md` §4 Phase 列表加「Audit Mode Phase」並對應本 change
- [ ] 6.4 在 `docs/todos.md` 新增 audit doctrine 落地待辦（per Phase）
- [ ] 6.5 在 `README.md` Commands 區塊加 audit 群組範例
- [ ] 6.6 在 `CHANGELOG.md` Unreleased 段加 `feat(audit-mode)` entry，列出主要新功能
- [ ] 6.7 確認 `docs/superpowers/specs/2026-04-27-audit-mode-design.md` 與本 change 內容一致；若有 drift 補 commit 同步

## 7. Acceptance verification

- [ ] 7.1 確認 `testpilot audit init wifi_llapi --workbook <path>` 產出 RID 與 manifest，415 cases 進 worklist，`_template.yaml` 不在內
- [ ] 7.2 確認 `testpilot audit pass12 <RID>` 跑完後 confirmed + applied + pending + block + needs_pass3 加總 == 415，confirmed 桶非空
- [ ] 7.3 確認主 agent Pass 3 對每筆 needs_pass3 case 落 decision.json（含 evidence trail）
- [ ] 7.4 確認 verify-edit 對違反 §9.1 的 diff 一律拒絕
- [ ] 7.5 確認 pre-commit hook 對未經 verify-edit 的 YAML 變動擋下；audit-bypass escape hatch 可繞但記 log
- [ ] 7.6 確認 apply 後 `git diff plugins/wifi_llapi/cases/` 只動 allowed paths
- [ ] 7.7 確認 audit pr 開出的 PR body 含 RID + bucket 摘要 + 驗證指引
- [ ] 7.8 確認 D366 audit 後 pass_criteria 含 `wl sr_config srg_obsscolorbmp` driver bitmap 驗證；rerun verdict 對齊 workbook Fail
- [ ] 7.9 確認 D369 audit 後 pass_criteria 含 `wl sr_config srg_pbssidbmp` driver bitmap 驗證；rerun verdict 對齊 workbook 混合（5G/6G Fail、2.4G Not Supported）
- [ ] 7.10 確認 `_template.yaml` 與其他 `_*.yaml` 在 audit run 期間原樣不動
- [ ] 7.11 確認 `audit/` 目錄完全不入 git（`git ls-files audit/` 為空）
- [ ] 7.12 確認 `docs/audit-guide.md` 與 AGENTS.md 同步更新並通過 review

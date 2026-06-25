## Context

TestPilot 由 plugin-driven runner 與 case YAML 文件組成。`testpilot run <plugin>` 執行 case YAML、產 verdict、寫 xlsx report。Audit / calibration 工作的目的是用外部 workbook（authoritative result source）反過來校正 case YAML 的 `steps` / `verification_command` / `pass_criteria`。

過去 audit work 沿用同一條 runner、agent 對 plugins/cases/D*.yaml 的 Edit/Write 沒有閘門。實務上 audit operator 常把 trial-and-error 痕跡寫入 case YAML（例如把 driver 漏掉一條 hostapd config 的副作用反過來當 pass criterion），結果 normal `testpilot run` 跑這份被汙染的 case 時回 false-positive Pass。

issue **#36** 標題只寫「拆 audit mode」，但根因是缺寫入閘 + 缺證據鏈。本 change 以兩個強制機制處理：

1. **doctrine 層（自律）**：主 agent 在 audit session 內必經 `testpilot audit verify-edit <RID>` 才能寫 YAML
2. **CI 層（強制）**：pre-commit hook 驗證 PR 中所有 YAML 變動都對應某個 RID 的 verify_edit_log；對不上 → fail

附帶解掉 issue **#31** 的 row 漂移問題：workbook lookup 改用 `(source.object, source.api)` 語意鍵，不靠 `source.row`。

完整背景與實作細節見 `docs/superpowers/specs/2026-04-27-audit-mode-design.md`（commit `8427848`）。

## Goals / Non-Goals

**Goals:**

- 把 audit / normal test 的 YAML 寫入權限劃線；audit-only data 不再可能進 plugins/cases/D*.yaml
- 提供可重 run、可 resume、idempotent 的 audit pass1+2 預過濾；只把真的需要推理的 case 丟到主 agent
- 主 agent + fleet sub-agents 的 Pass 3 工作流有明確 evidence trail，每筆改動都可追溯到 source citation
- D366 / D369 在 audit 完成後，pass_criteria 改成驗證 driver bitmap 真的被拉起來，verdict 對齊 workbook Fail
- 解 #31 的 workbook ↔ case identity 漂移，用語意鍵取代 row number
- audit 工作目錄完全 local-only，evidence 不入 main repo

**Non-Goals:**

- 不寫 batch headless automation 自動跑 415 筆 LLM 推理（Pass 3 是主 agent 在 Copilot session 內負責）
- audit CLI 不直接呼叫任何 LLM SDK；`core/agent_runtime.py` 與 `core/copilot_session.py` 沿用給 normal run
- 不修改 `case_schema.py` 既有欄位定義（不新增 top-level key；只修改或刪減 YAML 內容）
- 不修改任何 source code（driver / pwhm / hostapd / mod-whm-brcm）— 違反 #36 期望 #8
- 跨 plugin audit dispatch 暫不支援；首發只 wifi_llapi（helper API 預留 plugin 參數）
- 不做 workbook xlsx 的 round-trip / 自動產生
- 不做 alignment 規範變更（既有 `wifi-llapi-alignment-guardrails` 不動）

## Decisions

### D1：CLI 分流（不在 `run` 加 flag）

- **Decision**: 新獨立 subcommand `testpilot audit ...`，內部 reuse runner（透過 thin facade 暴露既有 case execution 入口）
- **Rationale**: normal `run` 與 audit 完全分流可避免「flag 誤觸」；reuse runner 確保 normal/audit 跑同樣的 plugin 行為，不會漂移
- **Alternatives considered**: 
  - 在 `run` 加 `--audit` flag — 否決：normal/audit 行為混在一起，未來容易誤觸（這正是現況問題）
  - 完全獨立 audit-runner（不 reuse） — 否決：兩條 path 會漂移，需要兩條測試覆蓋

### D2：Pass 1/2 純 py、Pass 3 主 agent

- **Decision**: Pass 1（YAML 原樣）與 Pass 2（從 workbook G/H 機械抽 candidate commands）由 `testpilot audit pass12 <RID>` 純 py 跑；Pass 3 由主 agent 在 Copilot session 內透過 Task tool 派 fleet sub-agents 對 source 做 read-only survey、自己用 serialwrap 跑驗證
- **Rationale**: 預過濾把 trivial 對齊（confirmed 桶）和明顯 mismatch 過濾出來，減少主 agent 工作量；Pass 3 才需要推理，由 LLM 主 agent 負責；audit CLI 不直呼 LLM SDK，行為 deterministic、可 reproduce
- **Alternatives considered**:
  - 全 py 自動化（含 Pass 3 LLM 抽取） — 否決：用戶明確要求 unattended via Copilot mode，不從 py 端自驅 LLM
  - 全 agent（連 Pass 1/2 也由 agent 跑） — 否決：浪費主 agent 在 trivial confirmed case 上的 token budget

### D3：Workbook lookup 用 `(source.object, source.api)` 語意鍵

- **Decision**: 不用 `source.row` 對齊；用 `(normalize(object), normalize(api))` 建 index；多 row 對到同 key → block（reason="workbook_row_ambiguous"）；無 row 對到 → block（reason="workbook_row_missing"）
- **Rationale**: 解 #31 — workbook.xlsx 與 template.xlsx 行序可能不同；row drift 不影響語意；AGENTS.md 已確立 `(source.object, source.api)` 為 canonical key
- **Alternatives considered**:
  - 用 `source.row` 直接對齊 — 否決：#31 問題本身
  - 用 `id` / `name` 字串 — 否決：多筆 case 可能共用相近 name；id 是 metadata 層級

### D4：YAML edit boundary white-list

- **Decision**: 只允許動 `steps[*].command`、`steps[*].capture`、`verification_command`、`pass_criteria[*]`；禁止動 `id` / `name` / `version` / `source.*` / `platform.*` / `bands` / `topology.*` / `setup_steps` / `sta_env_setup` / `test_procedure`；禁止 add/remove 整個 step
- **Rationale**: audit 修的是「驗證行為」，不是「測項身分 / topology / 元資料」；後者一旦動了，跨入 alignment / refactor 範疇（另一條工作流）
- **Alternatives considered**:
  - 寬鬆邊界（也允許動 source.row） — 否決：與 #31 反向；alignment 已是另一條獨立 path
  - 更嚴邊界（只允許 pass_criteria） — 否決：D366/D369 的修正需要同時動 verification_command + pass_criteria，過嚴會逼很多正確 case 落進 manual

### D5：兩道防線（doctrine + pre-commit hook）

- **Decision**: 自律層 = `testpilot audit verify-edit` CLI；強制層 = `scripts/check_audit_yaml_provenance.py` pre-commit hook 比對 YAML sha256 vs `verify_edit_log.jsonl`
- **Rationale**: 主 agent 仍可技術上繞過 verify-edit 直接 Edit 檔（hook 是寫 YAML 之後才跑），但 commit 階段擋下；提供 `[audit-bypass: <reason>]` escape hatch 處理真實的 metadata-only edit
- **Alternatives considered**:
  - 只有自律層 — 否決：歷史已證明自律靠不住（#31 就是這樣發生的）
  - 只有強制層（hook） — 否決：缺 evidence trail；無法區分「是 audit 跑出來的」vs「手寫的」
  - 用 settings.json PreToolUse hook 在 Edit 前擋 — 否決：與 Copilot CLI 互動複雜；platform-specific；session lock 可靠性低

### D6：Bucket 三桶 + 信心分層

- **Decision**: `confirmed`（Pass 1 match，無 diff）/ `applied`（verdict_match ∧ citation_present ∧ citation_verified ∧ field_scope_safe ∧ schema_valid）/ `pending`（verdict_match 但有 check 不過）/ `block`（verdict_mismatch 或 workbook missing/ambiguous）；`apply` step 預設只套 applied
- **Rationale**: evidence-only 原則靠 mechanical check 落實；自動 apply 的條件全 deterministic，不靠 heuristic；pending 桶讓 borderline case 落到人工 review
- **Alternatives considered**:
  - 嚴格雙桶（applied = no-diff, pending = 任何改寫） — 否決：Pass 2 純 G/H substring 命中且 verdict 對齊的也要進 pending，量會很大
  - 四桶（再加 manual-only） — 否決：實務上 pending 已涵蓋；過度切分

### D7：RID 用 `<git_short_sha>-<ISO8601>`

- **Decision**: RID 由 audit init 產生，格式 `<commit短SHA>-<ISO8601 UTC>`；workbook hash 寫進 manifest，workbook 換版本則新 RID
- **Rationale**: commit 短 SHA 確保可追溯到觸發時 repo 狀態；timestamp 確保唯一；workbook hash 鎖 evidence 與 workbook 一致
- **Alternatives considered**:
  - 純 ISO timestamp — 否決：repo 狀態不可追溯
  - 純 sequence (`run-001`) — 否決：跨機器易撞號

### D8：Pass 3 走 Task tool（不用 coordinator / dispatching-parallel-agents skill）

- **Decision**: 主 agent 派 fleet sub-agents 用 Claude Code 內建 `Task` tool；`subagent_type=Explore`（read-only 偏好）；不引入 `coordinator` / `superpowers:dispatching-parallel-agents` 等額外 layer
- **Rationale**: `Task` 是內建工具、無需額外 setup；`Explore` agent 預設 read-only（沒有 Edit/Write）；user 確認 Q9-α（survey-only）
- **Alternatives considered**:
  - `coordinator` skill — 否決：multi-agent broker 對 audit 一筆一筆推理過於重；coordinator 有 short-lived job lifecycle 不必要
  - `dispatching-parallel-agents` skill — 否決：適合 2+ 完全獨立 task；audit 每筆 case 內的 fleet sub-agents 都對同一 (object, api) survey，本質是 query fanout 不是獨立 task

### D9：doctrine 放 `docs/audit-guide.md`，不做獨立 skill

- **Decision**: 主 agent doctrine rewrite `docs/audit-guide.md`；不建獨立 `superpowers:audit-mode` skill
- **Rationale**: doctrine 內容專屬 testpilot 專案；放 docs 跟其它專案文件同處，agent 在 session 開始讀 docs 即可；沒必要做成跨專案 skill
- **Alternatives considered**:
  - 做 skill — 否決：跨專案 reuse 價值低；維護兩處同步麻煩

## Risks / Trade-offs

- **Risk**: Pass 2 mechanical extraction 命中率低，所有 case 都掉到 Pass 3 → 主 agent 工作量沒被預過濾減少
  → **Mitigation**: 設計上仍可運作；token allowlist 可逐步擴；最壞情況下 Pass 1 仍有效預過濾 confirmed 桶；Pass 2 命中率列入 acceptance metric

- **Risk**: pre-commit hook 在 fresh clone 上沒有 `audit/runs/*/verify_edit_log.jsonl` → 永遠 fail
  → **Mitigation**: hook 邏輯：`audit/` 不存在或 verify_edit_log 不存在時 → soft warn + auto-skip（與 audit-bypass 同處理）；只有當 audit/ 存在但 log 找不到對應 sha256 時才 hard fail

- **Risk**: 主 agent 違反 doctrine 直接 Edit YAML 不過 verify-edit
  → **Mitigation**: pre-commit hook 第二道防線；commit 時擋下；user review PR 也看得到 YAML diff 沒對應 RID

- **Risk**: workbook 與 case YAML 都動，造成 RID 期間 workbook 變化
  → **Mitigation**: manifest snapshot workbook hash；rerun 時若 hash 不符 → 強制起新 RID

- **Risk**: 主 agent 在 Pass 3 拿到 sub-agent 不可信的 citation（filename 假、line 不對）
  → **Mitigation**: audit CLI mechanical check：grep file 並比對 snippet hash；不過則 block

- **Risk**: audit RID 累積過多 → /audit/ 膨脹
  → **Mitigation**: history/ 只 symlink summary；evidence 老化由 user 手動清；可加 `testpilot audit gc` future feature

- **Risk**: 主 agent doctrine drift（agent 沒讀 docs/audit-guide.md 就開工）
  → **Mitigation**: Copilot mode 啟動時系統 prompt 要求先讀 doctrine；audit init 步驟在輸出中明示

- **Trade-off**: thin facade `run_one_case_for_audit()` 是 audit-required infra（妥協 Out-of-scope 中「不改 src/testpilot/core」），但放 `src/testpilot/audit/runner_facade.py` 並只呼叫既有 plugin public API；若 plugin 缺 stable hook 才補薄方法（不變更 normal run 行為）。理由與用戶 Q2 對話一致

## Migration Plan

無 breaking change。`testpilot run` 行為與 case YAML schema 不變；audit 是新 path。

導入順序見 tasks.md 的五階段切分（Phase A → E）。

## Open Questions

- pre-commit hook 的「audit/ 不存在 → soft skip」邏輯細節（是否分 dev / CI 兩種行為，CI 環境 audit/ 一定不存在的合理 default）
- `testpilot audit pr` 對既有 `gh pr create` 的 PR template 整合方式（PR body 模板）
- Pass 2 token allowlist 是否要可配置（plugin-level allowlist override；首發寫死）
- RID lock 機制（`.lock` 文件 + heartbeat）的具體 timeout（24h？1h？）與 stale recovery 策略
- bucket jsonl 的版本演進策略（schema 加欄位時的 backward compat）

以上不影響整體架構，留待 implementation 過程中按需細化。

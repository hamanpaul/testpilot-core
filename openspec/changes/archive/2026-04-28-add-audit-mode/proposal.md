## Why

TestPilot 目前讓 audit / calibration 工作與 normal test 共用同一條 runner 與 YAML 寫入權限。issue **#36** 要求把 audit mode 從 normal test 切開；根因比 #36 標題所述更深 — agent 在做 audit 時可以無差別地 Edit 任何 case YAML，把 audit-only 的 trial-and-error 痕跡（trace、temp capture、為了「對齊 workbook」硬寫的 setter / pass_criteria）寫進 plugins/cases/D*.yaml，造成 normal test path 跑這份被汙染的 case 時回 false-positive Pass。issue **#31** 是這條結構性問題的具體爆點之一（workbook ↔ case identity 漂移）。具體例：D366 SRGBSSColorBitmap / D369 SRGPartialBSSIDBitmap 的 pass_criteria 把「`grep -c ^he_spr_srg_bss_colors= /tmp/wl0_hapd.conf == 0`」當 pass 標的（即 brcm hostapd 沒收到那行就算過），但正確驗證點是「driver SRG bitmap 是否真的有 bit set」— 這條 case 應該 Fail。本 change 把 audit work 做成有清楚邊界的工作模式，所有 audit 對 YAML 的修改必須走 verify-edit gate + 留 evidence；normal test path 不得繞過 audit doctrine 修 YAML。

## What Changes

- **新增** `testpilot audit ...` subcommand 群組：`init` / `pass12` / `record` / `verify-edit` / `decide` / `status` / `summary` / `apply` / `pr`
- **新增** `audit/` 工作資料夾（gitignored），存放 RID（`<git_short_sha>-<ISO8601>`）、workbook snapshot、case-level evidence（pass1/2/3 JSON、proposed.yaml/diff、decision）、buckets jsonl、verify_edit_log
- **新增** `src/testpilot/audit/` Python 套件 — 純機械助手（workbook semantic-key index / Pass 1+2 mechanical extractor / verify-edit gate / bucket 簿記 / PR 構造）；不呼叫任何 LLM SDK
- **新增** workbook lookup 改用 `(source.object, source.api)` 語意鍵（避免 #31 的 row 漂移）
- **新增** Pass 1+2 純 py 預過濾：Pass 1 跑 YAML 原樣比 verdict；Pass 2 從 workbook G/H prose mechanical 抽 candidate commands（regex + 行首 token allowlist `ubus-cli|wl|hostapd_cli|grep|cat|sed|awk|ip|iw|hostapd|wpa_cli` + fenced block）
- **新增** Pass 3 doctrine（主 agent + fleet sub-agents）：主 agent 透過 Task tool 派 read-only fleet sub-agents 對 `bcmdrivers/.../impl107/`、`mod-whm-brcm/`、`pwhm-v7.6.38/src/` 三個子樹 grep；主 agent 自己用 serialwrap 在 DUT/STA 跑 candidate commands；citation 必須 mechanical 驗證才採納
- **新增** YAML edit boundary white-list：只允許 `steps[*].command`、`steps[*].capture`、`verification_command`、`pass_criteria[*]`；禁止動 `id` / `name` / `version` / `source.*` / `platform.*` / `bands` / `topology.*` / `setup_steps` / `sta_env_setup` / `test_procedure` 等
- **新增** verify-edit gate（`testpilot audit verify-edit`）— 主 agent 寫 YAML 前必經，append `verify_edit_log.jsonl`
- **新增** pre-commit hook `scripts/check_audit_yaml_provenance.py`：plugins/cases/D*.yaml 的 sha256 必須在某個 RID 的 verify_edit_log 找到對應 entry，否則 fail；提供 `[audit-bypass: <reason>]` commit message escape hatch
- **新增** bucket 分類（`confirmed` / `applied` / `pending` / `block`）+ apply step 的 default 套用規則
- **新增** Resume 支援（`--resume <RID>`、idempotent `pass12`）；block 不視為 final state，下次 audit 自動重評
- **改寫** `docs/audit-guide.md` 為主 agent 在 audit session 內遵循的 doctrine
- **同步更新** `AGENTS.md`（Audit Mode Governance 章）、`docs/plan.md`、`docs/todos.md`、`README.md`、`CHANGELOG.md`
- **跳過** `_template.yaml` 與其他 underscore-prefix fixtures；首發 scope = wifi_llapi 415 official cases
- **不改** `src/testpilot/core/agent_runtime.py` 與 `core/copilot_session.py`（audit CLI 不直呼 LLM SDK）
- **不改** `case_schema.py` 既有欄位定義（不新增 top-level key）
- **不改** 任何 source code（driver / pwhm / hostapd / mod-whm-brcm 等）

## Capabilities

### New Capabilities

- `audit-mode`: TestPilot audit / calibration 工作模式 — RID lifecycle、`testpilot audit ...` CLI 群組、`audit/` gitignored 工作資料夾、三段 waterfall（Pass 1/2 純 py、Pass 3 主 agent + fleet sub-agents）、workbook semantic-key lookup、bucket 分類、YAML edit boundary、verify-edit gate、pre-commit hook 強制層、Resume / Block / Template 規則、首發 wifi_llapi 415 cases 的 acceptance

### Modified Capabilities

（無 — 既有 `wifi-llapi-alignment-guardrails` capability 不變；本 change 不調整 alignment 規範，只在 audit 路徑加新的工作模式）

## Impact

- **Affected code:**
  - `src/testpilot/audit/`（新套件 — `runner_facade.py` / `workbook_index.py` / `bucket.py` / `manifest.py` / `verify_edit.py` / `pass12.py` / `pr.py` 等）
  - `src/testpilot/cli.py`（追加 `audit` subcommand 群組）
  - `plugins/<plugin>/plugin.py` 視需要暴露 thin public method（不改 normal run 行為）
  - `scripts/check_audit_yaml_provenance.py`（新增 pre-commit hook）
  - `.pre-commit-config.yaml`（接入 hook）
  - `.gitignore`（加 `/audit/`）
- **Affected docs:**
  - `docs/audit-guide.md`（rewrite 為 doctrine）
  - `docs/superpowers/specs/2026-04-27-audit-mode-design.md`（已 commit `8427848`）
  - `AGENTS.md` / `docs/plan.md` / `docs/todos.md` / `README.md` / `CHANGELOG.md`（同步更新）
- **Affected runtime artefacts:**
  - 新增 `audit/` 工作資料夾結構（local-only）
  - wifi_llapi 415 官方 case YAML 在 audit 跑完後預期會有定向修正（含 D366/D369 的 pass_criteria 重寫，verdict 對齊 workbook Fail）
- **Dependencies:**
  - 既有：`openpyxl`（workbook 讀）、`ruamel.yaml`（path-aware diff）、`gh` CLI（PR）、`pre-commit`（hook framework）
  - 不新增第三方 dep
- **Breaking changes:** 無 — `testpilot run` 行為與 case YAML schema 不變；audit 是新 path

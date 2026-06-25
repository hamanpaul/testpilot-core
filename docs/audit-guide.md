# TestPilot Audit Mode — Agent Doctrine

> 本文件定義主 agent 在 audit session 內的固定工作章法。Audit mode 與 normal
> `testpilot run` 完全分流；audit 對 case YAML 的修改必須經過 verify-edit gate、
> evidence 記錄與 provenance hook。

## 1. 何時進入 audit session

當使用者明確要求 workbook-driven calibration / audit，且預期輸出為 case YAML 修正與
PR 時，主 agent 應改走 `testpilot audit ...` 工作流，而不是直接編輯
`plugins/<plugin>/cases/D*.yaml`。

目前首發 scope 為 `wifi_llapi`。

## 2. 角色分工

| Role | 可做 | 不可做 |
|---|---|---|
| 主 agent（Copilot session） | 執行 `testpilot audit ...` CLI、用 serialwrap 驗證 candidate commands、構造 `proposed.yaml`、跑 `verify-edit` / `record` / `decide` / `apply` / `pr` | 直接改寫 `plugins/<plugin>/cases/D*.yaml` 而不經 verify-edit |
| Fleet sub-agents（Task / Explore） | read-only source survey、提供 candidate commands 與 `file:line` citations | 編輯 repo 檔案、操作 serialwrap、直接決定 bucket |

## 3. Audit session 標準流程

```text
1. testpilot audit init <plugin> --workbook <path>     -> 取得 RID
2. testpilot audit pass12 <RID>                        -> 跑 Pass 1 / Pass 2 預過濾
3. testpilot audit status <RID>                        -> 取得 needs_pass3 worklist
4. for each case in needs_pass3:
     a. fleet sub-agents 對 source 子樹做 read-only survey
     b. 主 agent 用 serialwrap 跑 candidate commands
     c. 構造 proposed.yaml（只動 white-list 欄位）
     d. testpilot audit verify-edit <RID> <case> --yaml ... --proposed ...
     e. testpilot audit record <RID> <case> --evidence pass3.json
     f. testpilot audit decide <RID> <case> --bucket applied|pending|block --reason ...
5. testpilot audit summary <RID>                       -> 產 end-of-run 摘要
6. 使用者 review summary / buckets
7. testpilot audit apply <RID>                         -> 套用 applied（必要時含 pending）
8. testpilot audit pr <RID>                            -> 建立 PR
```

## 4. YAML 編輯邊界

只允許修改：

- `steps[*].command`
- `steps[*].capture`
- `verification_command`
- `pass_criteria[*]`

禁止修改：

- `id`
- `name`
- `version`
- `source.*`
- `platform.*`
- `bands`
- `topology.*`
- `setup_steps`
- `sta_env_setup`
- `test_procedure`
- add/remove 整個 step

違反邊界時：

1. `testpilot audit verify-edit` 必須拒絕
2. provenance hook 也必須在 commit 階段擋下未經 verify-edit 的 YAML 變更

## 5. Evidence 與 citation 規範

`testpilot audit record --evidence <json>` 的輸入格式：

```json
{
  "candidate_commands": [
    {
      "command": "wl -i wl0 sr_config srg_obsscolorbmp",
      "rationale": "driver bitmap is the real oracle",
      "rerun_verdict": {"5g": "Fail", "6g": "Fail", "2.4g": "Fail"}
    }
  ],
  "citations": [
    {
      "file": "bcmdrivers/.../wlc_stf.h",
      "line": 263,
      "snippet": "uint16 srg_pbssid_bmp[4];"
    }
  ]
}
```

`citations[*]` 必須通過 mechanical 驗證：

1. 檔案存在
2. 行號合法
3. `snippet` 是該行內容的 substring（去前後空白後比對）

`audit record` 會把驗證結果寫入 `pass3_source.json` 的 `citations_verified`。

## 6. 主 agent 不可做的事

- 直接編輯 `plugins/<plugin>/cases/D*.yaml` 然後 commit
- 跳過 `verify-edit` 直接把 `proposed.yaml` 套回 repo
- 用自由發散方式重寫 workbook G/H 未提供的命令鏈
- 在沒有 source citation 的情況下把 case 標成 `applied`
- 為了對齊 workbook verdict 而改寫 case identity / topology / metadata

如果上述任一條件無法滿足，應把 case 留在 `pending` 或 `block`，而不是硬套。

## 7. Local-only artifact 與 resume 規則

- `audit/` 目錄是 gitignored local-only 工作區；evidence 不進版本控制
- 每個 audit run 必須有 RID，並把 workbook snapshot / bucket / verify-edit log 綁在同一個 run dir
- `testpilot audit pass12 <RID>` 應維持 idempotent，可重跑
- `block` 不是 final state；下次 audit run 可重新評估
- pre-commit hook `audit-yaml-provenance` 強制所有 `plugins/<plugin>/cases/D*.yaml` 變更都能對應某個 `verify_edit_log.jsonl`

## 8. 與 normal run 的關係

- `testpilot run wifi_llapi` 不產生 `audit/`，也不應該替代 audit doctrine
- audit mode 修正後的 YAML 仍由 normal run 執行，但變更必須先經過 audit gate
- alignment 與 audit 是分開責任：alignment 修 metadata drift；audit 修驗證行為與 evidence chain

## 9. 參考

- 設計文件：`docs/superpowers/specs/2026-04-27-audit-mode-design.md`
- OpenSpec main spec：`openspec/specs/audit-mode/spec.md`
- OpenSpec archive：`openspec/changes/archive/2026-04-28-add-audit-mode/`
- 舊版 calibration guide：`docs/audit-guide.md.legacy.bak`

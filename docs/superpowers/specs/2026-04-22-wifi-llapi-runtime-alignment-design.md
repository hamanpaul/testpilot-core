# wifi_llapi Runtime Alignment & Source-Workbook Decoupling — Design

- Issue: [#31](https://github.com/hamanpaul/testpilot/issues/31)
- Status: Approved (2026-04-22)
- Depends on: —
- Follow-up: audit mode design (separate thread)

## 1. Problem

`testpilot run wifi_llapi` 目前在 runtime 流程裡 reference source workbook（`plugins/wifi_llapi/reports/templates/wifi_llapi_template.xlsx` 或 CLI 傳入的 raw `*.xlsx`），會：

1. 讓跑測試時混入 workbook 當 oracle 的錯誤心智模型（「抄答案而不是跑測試」）。
2. `collect_alignment_issues` 在 run pipeline 內呼叫，把 metadata drift 的 artifact（`alignment_issues.json`）跟 run result 混在同一個 artifact 資料夾，模糊責任邊界。

同時，`plugins/wifi_llapi/cases/` 下 420 個 discoverable case 中有 168 個 `D###` 檔名與 `source.row` 不一致（以 2026-04-22 `main` snapshot 為準）。目前 `fill_case_results` 直接拿 `source.row` 當 target row 寫 result，這 168 個 case 的 regression 結果會被寫到 template report 的錯誤列上（e.g., D021 `HeCapabilities` 的結果被寫進 row 18 = `DownlinkShortGuard` 那一列），造成 report 失真。

## 2. Goals

- **Runtime 邊界**：`testpilot run wifi_llapi` 在判定與執行路徑上不得 reference source workbook；template xlsx 只作為 output skeleton 與 row↔(object, api) lookup。
- **Alignment 內建**：runtime 前內建 alignment phase，拿 template xlsx 當 row↔(object, api) 權威，對 YAML 的 `D###` / `source.row` / `id` 做自動對齊（mutate in place）。
- **Safety net**：無法自動對齊的 case 分類為 `blocked` 或 `skipped`，不執行、不污染 report，產生獨立的 artifact 供 RD 看。
- **責任分層**：alignment 處理 metadata drift；audit mode 處理 test step / pass_criteria 校正。兩者互不依賴。

## 3. Non-Goals

- 不設計 audit CLI（另外 thread 討論；`audit` 是 RD 模式、需 source code + live DUT 驗證）。
- 不自動修 `name` / `source.object` / `source.api` / `steps` / `pass_criteria`；這些欄位的錯誤歸 audit 處理。
- 不處理 repo 裡既有的 168 漂移 case 的「語意正確性」—— runtime alignment 只負責把 metadata 欄位對齊到 template；語意對不對是 audit 的責任。
- 不處理 template xlsx 重建（`build-template-report` 由獨立 CLI 處理，屬 audit / build 路徑）。

## 4. Architecture — Three Layers

| Layer | Input | Output | 這次做 |
|---|---|---|---|
| **Runtime** (`testpilot run`) | YAML (aligned), template xlsx, DUT/STA live | run report xlsx, blocked_cases.md, skipped_cases.md | ✅ |
| **Alignment** (內建於 run 流程) | YAML (raw), template xlsx | YAML (aligned), file rename | ✅ |
| **Audit** (RD 獨立 CLI) | YAML, source workbook, source code, DUT live | YAML (steps / pass_criteria 修正) | ❌ 另議 |

### Invariants

- Runtime 不 import、不讀 source workbook（原始 `*.xlsx` 如 `0401.xlsx`）。
- Runtime 不讀 `alignment_issues.json` / `source_report` / `report_source_xlsx` 任何 workbook-input artifact。
- Runtime 對 template xlsx 的讀取**只限**兩種用途：(i) `create_run_report_from_template` 的 output skeleton copy，(ii) alignment phase 的 `(row → object, api)` lookup。
- Alignment 是 deterministic function：`(YAML + template)` → `(YAML', classification)`；只會動 `D###` / `source.row` / `id`，永遠不動 `steps` / `pass_criteria` / `name` / `source.object` / `source.api` / `aliases`。
- Audit 不在 runtime 路徑；runtime code 不得 import audit module（PR#2 之後）。

## 5. Key Decisions (Q/D log)

- **Q1'**: runtime 徹底去 source workbook 化；template xlsx 保留為 row↔(object, api) 權威。
- **Q2'**: `fill_case_results` 用（alignment 後的）`source.row` 寫 report。
- **Q3**: alignment 預設 mutate YAML（rename / 改 `source.row` / 改 `id`），`git diff` 看得到，人 commit 時 review。不提供 dry-run flag。
- **Q4**: audit CLI 獨立項，另外 thread 討論，不在本 spec scope。
- **Q5**: 無法 auto-align 的 case → `blocked` 或 `skipped` 兩種狀態；在 report xlsx H 欄填 `BLOCKED: <reason>` / `SKIP: duplicate with D###`；另產 `blocked_cases.md` / `skipped_cases.md`，都寫到 `plugins/wifi_llapi/reports/<artifact>/`。
- **D1**: H 欄填標記，`G/I/J/K/L` 留空。
- **D2**: md 欄位已定義（見 §7）。
- **D3**: template xlsx 缺檔 → raise `FileNotFoundError`。
- **Collision**: 兩個 case align 到同一個 N，按 filename ascending 第一個留、之後的 `skipped`。
- **Reload after mutation**: `apply_alignment_mutations` 只動 disk；之後 reload runnable case 再 execute。

## 6. Alignment Rule

對每個 case：

1. 拿 `(source.object, source.api)` 去 `template_index.by_object_api` 反查 → canonical row `N`
2. 查不到 → `blocked / object_api_not_in_template`
3. 查到 `N`：
   - `name` 的 API token 跟 template row `N` 的 api 一致 → 評估 mutation：
     - 都一致（filename D### == N, source.row == N, id 裡的 D### == N）→ `already_aligned`
     - 有差 → `auto_aligned`，mutation 清單包含要改的欄位
   - 不一致 → 拿 name 的 API token 去 `template_index.by_api` 反查
     - 查到 `M ≠ N`（或多筆不含 N）→ `blocked / name_points_to_different_row`
     - 查不到 → `blocked / name_not_in_template`

### Collision handling

`apply_alignment_mutations` 前，對所有 `auto_aligned` / `already_aligned` 按 filename ascending 迭代；第一個指向 N 的 case 保留該狀態；之後再指到同 N 的 case 轉為 `skipped`，winner 指向該 filename。

### Mutation scope

對 `auto_aligned` case：

- **Filename**: `Path.rename("D{N:03d}_<suffix>.yaml")`，`<suffix>` 沿用原本 `_` 之後的部分。
- **`source.row`**: 改為 `N`（int）。
- **`id`**: 若 id pattern 能 match `r"wifi-llapi-D\d{3}-"`，將 `D###` 部分換為 `D{N:03d}`；否則不動 id（使用者自訂 id 格式保留）。
- **`aliases`**: 不動。stale `wifi-llapi-rXXX-` aliases 由 audit 於 live-calibrate 時清理。

## 7. Components

### PR#1 — Runtime decoupling (pure deletion / simplification)

**`src/testpilot/core/orchestrator.py`** — 移除：

- `collect_alignment_issues` import (~L63)
- `report_source_xlsx` / `source_xlsx` / `alignment_xlsx` / `source_report` 變數與分支邏輯 (~L460, L480-509)
- `collect_alignment_issues(cases, alignment_xlsx)` 呼叫與 `alignment_issues.json` 寫入 (~L511-532)
- `_load_wifi_llapi_template_source(manifest_path)` 的 runtime 呼叫 (~L502)
- run summary 裡的 `source_report` 欄位 (~L711, L778)
- `run_wifi_llapi` signature 裡的 `report_source_xlsx` (~L792, L810)

**`src/testpilot/cli.py`** — 拔 `--report-source-xlsx` flag。

**`src/testpilot/reporting/wifi_llapi_excel.py`** — 不動；`collect_alignment_issues` / `read_source_rows` / `ensure_template_report` 留著供 audit CLI / `build-template-report` 使用。

**Tests / docs**：更新 fixture 去除 `report_source_xlsx` 使用；`CHANGELOG.md` 記 CLI breaking change；`AGENTS.md` 標示 `build-template-report` 不屬 run 路徑。

### PR#2 — Alignment + blocked/skipped

**新增 `src/testpilot/reporting/wifi_llapi_align.py`**

```python
@dataclass
class TemplateIndex:
    forward: dict[int, tuple[str, str]]          # row → (object, api)
    by_object_api: dict[tuple[str, str], int]    # 反查 N
    by_api: dict[str, list[int]]                 # name fallback

@dataclass
class AlignResult:
    case_file: Path
    status: Literal["already_aligned", "auto_aligned", "blocked", "skipped"]
    source_row_before: int
    source_row_after: int | None
    filename_before: str
    filename_after: str | None
    id_before: str
    id_after: str | None
    blocked_reason: Literal[
        "object_api_not_in_template",
        "name_points_to_different_row",
        "name_not_in_template",
    ] | None = None
    skip_winner_filename: str | None = None
    template_row_object: str | None = None
    template_row_api: str | None = None

def build_template_index(template_xlsx: Path) -> TemplateIndex: ...
def align_case(case: dict, index: TemplateIndex, case_file: Path) -> AlignResult: ...
def apply_alignment_mutations(results: list[AlignResult]) -> None: ...
def write_blocked_cases_report(blocked: list[AlignResult], out_path: Path) -> None: ...
def write_skipped_cases_report(skipped: list[AlignResult], out_path: Path) -> None: ...
```

**修改 `src/testpilot/reporting/wifi_llapi_excel.py`** — 新增：

```python
def fill_blocked_markers(report_xlsx: Path, blocked: list[AlignResult]) -> None: ...
def fill_skip_markers(report_xlsx: Path, skipped: list[AlignResult]) -> None: ...
```

兩者都看原始 YAML 的 `source.row`（mutation 前那個值）；若該 row 在 `[1, template.max_row]` 範圍內，在 H 欄填對應訊息；否則 skip xlsx 寫入，僅進 md。既有 `fill_case_results` 只處理 runnable。

**修改 `src/testpilot/core/orchestrator.py`** — `run_wifi_llapi` 流程重組：

```python
cases = load_cases_dir(cases_dir)
index = build_template_index(template_path)
align_results = [align_case(c, index, case_files[i]) for i, c in enumerate(cases)]
_resolve_collisions(align_results)                      # 第二個指同 N 改成 skipped
apply_alignment_mutations(align_results)                # disk mutation
runnable_cases = [reload(r.case_file) for r in align_results if r.status in {"already_aligned", "auto_aligned"}]
blocked = [r for r in align_results if r.status == "blocked"]
skipped = [r for r in align_results if r.status == "skipped"]

report_path = create_run_report_from_template(template_path, ...)
case_results = execute(runnable_cases)
fill_case_results(report_path, case_results)            # 用 aligned source.row
fill_blocked_markers(report_path, blocked)              # H 欄 BLOCKED
fill_skip_markers(report_path, skipped)                 # H 欄 SKIP
write_blocked_cases_report(blocked, artifact_dir / "blocked_cases.md")
write_skipped_cases_report(skipped, artifact_dir / "skipped_cases.md")
finalize_report_metadata(report_path, meta)
```

run summary 新增 `alignment_summary` 欄：`{already_aligned, auto_aligned, blocked, skipped}` 計數與 mutation 清單。

## 8. Data Flow

```
load_cases_dir
  → build_template_index(template_path)       # 缺檔 raise FileNotFoundError
  → [align_case(c, index, file) for c in cases]
  → _resolve_collisions(align_results)
  → apply_alignment_mutations(align_results)  # rename + YAML rewrite
  → runnable = reload aligned YAML from disk
  → blocked / skipped 分流
  → create_run_report_from_template
  → execute runnable
  → fill_case_results(runnable)
  → fill_blocked_markers(blocked)
  → fill_skip_markers(skipped)
  → write_blocked_cases_report / write_skipped_cases_report
  → finalize_report_metadata
```

### Report artifact 結構

```
plugins/wifi_llapi/reports/<artifact_name>/
├── <report>.xlsx                    # runnable + BLOCKED + SKIP 標記混合
├── blocked_cases.md                 # Blocked 6 欄清單
├── skipped_cases.md                 # Skipped 5 欄清單
└── agent_trace/                     # 既有
```

### blocked_cases.md 欄位

| 欄 | 範例 |
|---|---|
| `case_id` | `wifi-llapi-D021-hecapabilities-accesspoint-associateddevice` |
| `filename` | `D021_hecapabilities_accesspoint_associateddevice.yaml` |
| `source.row` | `18` |
| `source.(object, api)` | `(WiFi.AccessPoint.{i}.AssociatedDevice.{i}., HeCapabilities)` |
| `template_row_(object, api)` | `(WiFi.AccessPoint.{i}.AssociatedDevice.{i}., DownlinkShortGuard)` or `—` if not found |
| `reason` | `name_points_to_different_row` |

### skipped_cases.md 欄位

| 欄 | 範例 |
|---|---|
| `case_id` | `wifi-llapi-D030-...` |
| `filename` | `D030_foo.yaml` |
| `source.row` | `21` |
| `winner_filename` | `D021_hecapabilities_accesspoint_associateddevice.yaml` |
| `template_N` | `21` |

### Report xlsx H-column content

- Runnable: command output（normal）
- Blocked: `BLOCKED: <reason>`，其他 `G/I/J/K/L` 留空
- Skipped: `SKIP: duplicate with D{N:03d}`（只帶 D 編號），其他 `G/I/J/K/L` 留空

## 9. Error Handling

### Abort types (整個 run 停下)

- Template xlsx 缺檔 → `FileNotFoundError`
- Rename 撞檔（目標實體檔已存在，非 N collision）→ `AlignmentConflictError`
- YAML 寫入 `IOError` → 冒泡、不 rollback 已完成的 mutation（`git status` 會顯示）

### Per-case blocked (run 繼續)

- `object_api_not_in_template`
- `name_points_to_different_row`
- `name_not_in_template`

### Per-case skipped (run 繼續)

- Collision：兩個 case 指向同一個 N，按 filename ascending 第二個起 → `skipped`，winner 指向第一個

### Defensive YAML shape

| 狀況 | 行為 |
|---|---|
| `source` 非 dict / 缺 `object` / 缺 `api` | 視為查不到 → `blocked / object_api_not_in_template` |
| `source.row` 非整數 / 0 / 負數 | `source_row = 0`；fill 時 skip xlsx，只進 md |
| `name` 缺失 / 非 string | 當作 name 查不到，走 `name_not_in_template` branch |
| `id` 沒有 `D###` pattern | `auto_aligned` 時不主動改 `id`，只動 filename + source.row |

### Ambiguous template

`by_object_api` 理應一對一；若發現多筆（不預期），用 `source.row` 是否落在候選 rows 之一消歧；否則 `blocked / object_api_not_in_template`，reason 附 "ambiguous"。

### Logging

- `log.info` 每個 auto_aligned：`aligned: D023_linkbandwidth.yaml -> D026_linkbandwidth.yaml (source.row 23 -> 26)`
- `log.warning` 每個 blocked / skipped
- `log.error` + raise for abort

## 10. Testing

### PR#1 tests

**Regression**：既有 orchestrator integration / `fill_case_results` / `create_run_report_from_template` / `finalize_report_metadata` unit test 在 flag 移除後仍通過。

**新增**：

- `test_run_without_report_source_xlsx` — 不傳 flag 成功產 report，`artifact_dir` 無 `alignment_issues.json`，run summary 無 `source_report` 欄位。
- `test_cli_no_report_source_xlsx_flag` — CLI parse `--report-source-xlsx` raise `unrecognized arguments`。

`test_collect_alignment_issues_on_repo_template_case` 改為純 `wifi_llapi_excel` unit test，不再 touch orchestrator path。

### PR#2 tests (`plugins/wifi_llapi/tests/test_wifi_llapi_align.py`)

Mini template fixture **test 現場 build**（`openpyxl` 或 `xlsxwriter` 產生，tmp_path 內）— 約 10 行，包含刻意設計的 collision / drift pattern。

| Test | Scenario |
|---|---|
| `test_build_template_index_happy` | 10 row fixture → 三個 dict 完整 |
| `test_align_already_aligned` | 全對 → `already_aligned`, no mutation |
| `test_align_auto_source_row_drift` | D021 情境（source.row 漂）→ `auto_aligned` |
| `test_align_auto_filename_drift` | filename 漂 → `auto_aligned` + rename |
| `test_align_auto_id_drift` | id 漂 → `auto_aligned` + id mutate |
| `test_align_blocked_object_api_not_found` | `blocked / object_api_not_in_template` |
| `test_align_blocked_name_different_row` | `blocked / name_points_to_different_row` |
| `test_align_blocked_name_not_in_template` | `blocked / name_not_in_template` |
| `test_align_skip_duplicate` | 兩 case 同 N → 後者 `skipped` |
| `test_apply_mutations_idempotent` | 對 aligned YAML 第二次跑 → 全 `already_aligned`, `git status` 乾淨 |
| `test_apply_mutations_rename_collision` | rename target 實體檔撞檔 → `AlignmentConflictError` |
| `test_apply_mutations_partial_failure` | 寫 YAML IOError → raise，部分 mutation 已落盤 |
| `test_fill_blocked_markers` | H 欄 = `BLOCKED: <reason>`, 其他欄空 |
| `test_fill_skip_markers` | H 欄 = `SKIP: duplicate with D021` |
| `test_fill_markers_row_out_of_range` | `source.row=0` → 不寫 xlsx，只進 md |
| `test_write_blocked_report_md` | 6 欄格式正確 |
| `test_write_skipped_report_md` | 5 欄格式正確 |

### Orchestrator integration tests

- `test_run_with_all_aligned_cases` — 全 runnable、無 blocked/skipped
- `test_run_with_mixed_alignment` — 2 aligned / 2 auto / 1 blocked / 1 skipped → 各自落點正確
- `test_run_alignment_mutates_tracked_files` — 用 tmp_path fixture，assert disk YAML 被 mutate

### Repo-scale smoke test (CI)

- `test_align_all_repo_cases` — 對 `plugins/wifi_llapi/cases/` 420 個 real case + 真 template 跑 `align_case`（不 apply mutation）：
  - `already_aligned + auto_aligned + blocked + skipped == 420`
  - `auto_aligned <= 168`（會隨 audit 進度下降）
  - 確認不會 mutate repo

### 驗證標準

- 兩顆 PR 各自 `uv run pytest -q` 全綠
- PR#2 合併後跑一次 `testpilot run wifi_llapi` smoke，確認：
  - 無 `alignment_issues.json`
  - 有 `blocked_cases.md` / `skipped_cases.md`（若觸發）
  - report xlsx 對應列正確（runnable 結果寫到 aligned row；blocked/skipped 寫對應標記）

## 11. Rollout

### 順序

```
PR#1 (runtime decoupling) → 合併 → PR#2 (alignment + blocked/skipped) → 合併 → release v0.2.1
```

PR#1 與 PR#2 嚴格序列（PR#2 build on PR#1 清理後的 flow）；兩顆 PR 合併後再一起 cut release。

### Version bump

v0.2.0 → **v0.2.1** (patch bump)。尚未進 stable，CLI breaking change 仍走 patch。

### PR#1 合併前驗證

- `uv run pytest -q` 全綠
- 本地 `testpilot run wifi_llapi` 無 flag 情況下正常產 report
- `artifact_dir/` 無 `alignment_issues.json`
- `testpilot run wifi_llapi --report-source-xlsx ./0401.xlsx` raise argparse error
- `CHANGELOG.md` `### Changed - BREAKING` 記 `--report-source-xlsx` 移除

### PR#2 合併前驗證

- `uv run pytest -q` 全綠（含 repo-scale smoke test）
- 本地對 repo 跑一次 `testpilot run wifi_llapi`：
  - `git status` 預期 ~168 YAML 被修改 + 少數 rename
  - `blocked_cases.md` / `skipped_cases.md` 若觸發要產出
- PR#2 分兩個 commit：code change 一個 commit、168 YAML rewrite 一個 commit（同 PR 內），review 時分開看。
- PR 描述列出 rewrite 統計（幾個 rename / 幾個 source.row 改 / 幾個 id 改）。

### 使用者感知變化

| 項目 | PR#1 後 | PR#2 後 |
|---|---|---|
| `--report-source-xlsx` flag | ❌ 不接受 | ❌ 不接受 |
| `alignment_issues.json` | 不產 | 不產 |
| `blocked_cases.md` / `skipped_cases.md` | 不產 | 視情況產 |
| 168 漂移 case 的 report row | 仍錯列 | 正確列（alignment 修正後） |
| `git status` after run | 乾淨 | 首次 ~168 YAML 改動；之後 aligned 則乾淨 |
| `testpilot wifi-llapi build-template-report` | 保留（audit / build） | 保留（audit / build） |

### 回滾

- PR#1: `git revert`，無 disk 狀態殘留。
- PR#2: `git revert` code change；已被 aligned 的 YAML **不需要** rollback（aligned 後 report 落點反而更正確）。

### Docs sync

- **`AGENTS.md`**
  - §Case Discovery 條 1 加註：「D### prefix 由 runtime alignment 自動對齊 template xlsx（`(source.object, source.api)` 反查 row N），人工不必手動維護 D###」
  - §Case Discovery 加條款：「`run` 會 mutate YAML（`source.row` / `id` / filename）；commit 時連同 case 變更一起提交」
  - 新增 §Alignment vs Audit：分界與各自 scope
- **`CHANGELOG.md`**
  - PR#1: `### Changed - BREAKING: removed --report-source-xlsx flag from testpilot run; rebuild template via build-template-report instead`
  - PR#2: `### Added: runtime alignment phase auto-corrects D### / source.row / id to template xlsx; produces blocked_cases.md / skipped_cases.md artifacts`
- **`README.md`**
  - 首次 run 可能 auto-rename / 改 YAML 的警示段落

## 12. Open Questions

- Audit CLI 的詳細設計（另外 thread）— 需 include：source workbook 比對、DUT 驗證 workflow、`aliases` 欄位清理、`name` / `steps` / `pass_criteria` 校正流程。
- 若未來 template xlsx 某列被刪除（API deprecated），使得已對齊的 case 變 `object_api_not_in_template` blocked — audit 要決定是否刪 YAML 或 deprecate case。本 spec 不處理此情境，以 blocked 反應即可。

## 13. Appendix — Current Baseline (2026-04-22)

- `main` @ `71eb53f`
- Total discoverable cases: 420
- `D### ≠ source.row` 漂移 case: **168**
- Example drifts: D021 (source.row=18), D026 (source.row=23), D075 (source.row=77)
- Template workbook: `plugins/wifi_llapi/reports/templates/wifi_llapi_template.xlsx`, 741 rows, sheet `Wifi_LLAPI`, DATA_START_ROW=4

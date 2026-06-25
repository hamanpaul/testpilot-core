# Wifi_LLAPI inventory：missing row 一次性對齊與清理（2026-04-24）

## 背景與動機

`plugins/wifi_llapi/reports/templates/wifi_llapi_template.xlsx`（Sheet `Wifi_LLAPI`）E 欄 `LLAPI` 共 415 列標為 `Support`。`plugins/wifi_llapi/cases/` 目前有 420 支 `.yaml` 加 1 支 `_template.yaml` 共 421。長期目標是「**每個 Support row 恰好對應 1 支 canonical yaml**（`filename_row == source.row == xlsx row`）」，最終 cases 數量應為 415 + `_template.yaml` = 416。

repo 已有 `scripts/wifi_llapi_reconcile_inventory.py` 在做常態對齊（Stream 1），但目前狀態仍 dirty（`376 actions, 344 blockers`）。本次工作切為**一次性 Stream 2**：

- 處理「LIBERAL 定義（檔名 row 與 source.row 都搜不到）下真正 missing 的 9 列」
- 順手刪掉 6 支 `source.row` 與 `filename_row` 都指向 Not Supported 列的 stale yaml
- 為刪除後實質仍無真實覆蓋的 1 列（row 428）從 `_template.yaml` 複製建立 canonical case
- 不碰其他 Stream 1 對齊問題（避免與既有 reconcile pipeline 撞期）

## 範圍與非範圍

**In scope**：

- 8 列 rename + metadata 對齊（rows 66, 67, 109, 110, 111, 112, 113, 114）
- 1 列 move + metadata（row 407 from `D495_*_basic`）
- 1 支 metadata-only 修正（`D495_*_verified` source.row 362 → 495）
- 6 支 stale yaml 刪除
- 1 支從 `_template.yaml` 新建（row 428）
- 一份 markdown report + 一份 JSON report
- 一支可重跑、預設 dry-run 的 Python script，置於 `tools/oneoff/2026-04-24-align-missing-rows/`

**Out of scope**：

- 其他 Stream 1 alignment 問題（例如 `D068_*_rnr.yaml` source.row=70、`D051_tx_retransmissions.yaml` source.row=53 …等 50+ 列的競爭與位移）
- `_template.yaml` 之 schema 改寫
- `scripts/wifi_llapi_reconcile_inventory.py` 之邏輯調整
- docs / openspec 變更

## 動作清單（共 17 個動作）

### A. Rename + metadata（8）

| Row | 來源檔 | 目標檔 | source.row | id |
|---|---|---|---|---|
| 66  | `D068_discoverymethodenabled_accesspoint_fils.yaml` | `D066_discoverymethodenabled_accesspoint_fils.yaml` | 68 → 66  | `wifi-llapi-D068-...-fils` → `wifi-llapi-D066-...-fils` |
| 67  | `D068_discoverymethodenabled_accesspoint_upr.yaml`  | `D067_discoverymethodenabled_accesspoint_upr.yaml`  | 68 → 67  | `wifi-llapi-D068-...-upr` → `wifi-llapi-D067-...-upr` |
| 109 | `D115_getstationstats_accesspoint.yaml`             | `D109_getstationstats.yaml`                          | 115 → 109 | `wifi-llapi-D115-getstationstats-accesspoint` → `wifi-llapi-D109-getstationstats`（slug 去 `-accesspoint`） |
| 110 | `D115_getstationstats_active.yaml`                  | `D110_getstationstats_active.yaml`                   | 115 → 110 | `wifi-llapi-D115-getstationstats-active` → `wifi-llapi-D110-getstationstats-active` |
| 111 | `D115_getstationstats_associationtime.yaml`         | `D111_getstationstats_associationtime.yaml`          | 115 → 111 | `D115-...` → `D111-...` |
| 112 | `D115_getstationstats_authenticationstate.yaml`     | `D112_getstationstats_authenticationstate.yaml`      | 115 → 112 | `D115-...` → `D112-...` |
| 113 | `D115_getstationstats_avgsignalstrength.yaml`       | `D113_getstationstats_avgsignalstrength.yaml`        | 115 → 113 | `D115-...` → `D113-...` |
| 114 | `D115_getstationstats_avgsignalstrengthbychain.yaml`| `D114_getstationstats_avgsignalstrengthbychain.yaml` | 115 → 114 | `D115-...` → `D114-...` |

每筆只動 `id` 與 `source.row` 兩欄，其餘欄位（含 `name`、`steps`、`pass_criteria`、多行註解 `test_environment` 等）一律保留原樣。

### B. Move（1）

| Row | 來源檔 | 目標檔 | source.row | id |
|---|---|---|---|---|
| 407 | `D495_retrycount_ssid_stats_basic.yaml` | `D407_retrycount_ssid_stats.yaml` | 495 → 407 | `wifi-llapi-d495-retrycount-basic` → `wifi-llapi-D407-retrycount`（去 `-basic`、大寫 D） |

xlsx row 495 與 row 407 同為 `WiFi.SSID.{i}.Stats.RetryCount` Support（xlsx 自身重複登錄）— move 後 row 495 由下一筆 metadata-only 修正補回覆蓋。

### C. Metadata-only fix（1）

| 對象 | 變更 |
|---|---|
| `D495_retrycount_ssid_stats_verified.yaml` | `source.row` 362 → 495；`id` 維持原樣（不在本次更名範圍） |

### D. Delete（6）

以 `git rm` 刪除以下 stale yaml（其 filename_row 與 source.row 皆指向 Not Supported 列，刪除不影響任何 Support row 之 LIBERAL 覆蓋）：

- `D096_uapsdenable.yaml`（row 96 UAPSDEnable）
- `D097_vendorie.yaml`（row 97 VendorIE）
- `D100_wmmenable.yaml`（row 100 WMMEnable）
- `D102_configmethodssupported.yaml`（row 102 ConfigMethodsSupported）
- `D106_relaycredentialsenable.yaml`（row 106 RelayCredentialsEnable）
- `D474_channel_radio_37.yaml`（row 474 Channel）

### E. New from `_template.yaml`（1）

| Row | 新檔 | 關鍵欄位 |
|---|---|---|
| 428 | `D428_channel_neighbour.yaml` | id `wifi-llapi-D428-channel-neighbour`；source `{row:428, object:'WiFi.AccessPoint.{i}.Neighbour.{i}.', api:'Channel'}`；name `D428 Neighbour Channel`；hlapi_command `ubus-cli "WiFi.AccessPoint.1.Neighbour.1.Channel?"`；llapi_support `Support` |

其餘欄位原本以 `_template.yaml` scaffold 建檔；後續已補成 AP-only runnable Neighbour lifecycle case，沿用 add/read/delete pattern 驗證 `Channel`。

## 帳目驗證

- 起點：420 cases + 1 `_template.yaml` = 421
- A/B/C：rename / move / metadata-only，net 0
- D：−6 → 414
- E：+1 → 415
- 加 `_template.yaml` = **416** ✓

## Script 結構

```
tools/oneoff/2026-04-24-align-missing-rows/
├── align_missing_rows.py             # 主 script
├── README.md                         # 一頁說明
├── inventory_alignment_20260424.md   # 跑完產出
└── inventory_alignment_20260424.json # 跑完產出
```

**主 script 行為**：

- Python 3.11+，依賴 `openpyxl`、`ruamel.yaml`（皆已在 `uv.lock`）
- 入口：`uv run python tools/oneoff/2026-04-24-align-missing-rows/align_missing_rows.py [--apply]`
- 預設 dry-run；`--apply` 才動 working tree
- 17 個動作以 hard-coded plan 寫死（不做任何 picker）
- 流程：
  1. 載入 xlsx，建 Support row → (object, type, param, hlapi) 對照
  2. 載入 cases/，建現況 (filename, source.row, id) 索引
  3. 對 plan 每筆動作：驗證來源檔存在、目標檔不存在；驗證對齊後一致並落在 Support 集合
  4. dry-run 印 plan；apply 才執行（rename/move 用 `git mv`、刪用 `git rm`、metadata 用 `ruamel.yaml` round-trip、新建讀 `_template.yaml` 改數欄後寫出 + `git add`）
  5. apply 完跑 post-action 驗證（見下節）；不符則 raise 並把部分結果寫入 report
  6. dry-run 與 apply 都會產出 markdown + JSON 兩份 report
- 安全：working tree 髒則 abort；任何驗證失敗即 abort、不做半套；script 跑完留在原地不刪

**Report schema**

- markdown：人讀；分四節（Renames / Move + Fix / Deletes / New from template），每節列表，最後加 post-state 摘要
- JSON：
  ```json
  {
    "generated_at": "ISO-8601",
    "mode": "dry-run | apply",
    "actions": [
      {"kind": "rename|move|metadata|delete|create",
       "row": 109,
       "from": "D115_getstationstats_accesspoint.yaml",
       "to":   "D109_getstationstats.yaml",
       "fields_changed": {"id": ["...","..."], "source.row": [115, 109]}}
    ],
    "post_state": {
      "total_cases": 415,
      "incl_template": 416,
      "support_rows": 415,
      "canonical_coverage": 294,
      "liberal_missing": 0
    }
  }
  ```

## 驗收條件

apply 完後須全數通過：

1. `ls plugins/wifi_llapi/cases/*.yaml | wc -l` = **416**
2. 對每個 xlsx Support row r，都必須至少有一支 yaml 在 `filename_row == r` 或 `source.row == r` 其中之一覆蓋到（`liberal_missing = 0`）；`canonical_coverage` 則作為 snapshot-aware 指標回報目前仍維持 `filename_row == source.row == r` 的 row 數，本 snapshot 預期為 `294/415`
3. `git status` 反映：8 R（rename）、1 R（move）、1 M（D495_verified）、6 D（delete）、1 A（D428 新增），加 `tools/oneoff/...` 目錄下的 script + README + report
4. `git diff --stat` 對 8 個 rename yaml 的差異只出現在 `id` 與 `source.row` 兩個 key
5. JSON report 中 `post_state` 必須等於 plan-derived expected state（本 snapshot 為 `canonical_coverage == 294`、`liberal_missing == 0`）

## 不在驗收範圍

- `scripts/wifi_llapi_reconcile_inventory.py` 之 blocker 數變化（會自然下降，但不是本次目標）
- 其他 Stream 1 對齊欠帳

## 未來工作（明確不在本次）

- Stream 1 reconcile pipeline 完整跑通並消除剩餘 blockers

# Counter Delta Validation — Design

- **Spec date:** 2026-04-27
- **Issues:** #38 (counter ==0 一律 fail 並註記原因) · #13 (delta-based counter validation)
- **Related follow-up:** #39 (reason_code 體系細化，本 spec 不做)
- **Scope owner:** wifi_llapi plugin
- **Status:** Draft — awaiting user review

---

## 1. Background & Motivation

LLAPI counter 類測試的核心目的是驗證「API ↔ driver wiring 是否相符」。目前 `wifi_llapi/plugin.py` 的 `_compare()` 只支援單點等值 / 不等式 / regex / contains 等 operator，並沒有「成長性」(`delta`) 概念。實際 case 表現出兩個問題：

1. **#13 已指出**：counter 案例若只比較單點 snapshot，無法分辨「driver 真的沒有 traffic」與「LLAPI 沒有接到 driver」這兩種完全不同的失敗。
2. **#38 進一步要求**：對 fail / retry / error 類 counter，若在 trigger 後 delta 仍為 0，代表「test 工況本身沒能讓 counter 動」，無法證明 API ↔ driver wiring，這條測試本身不成立、必須判 FAIL，並在報告註解欄寫明「fail 原因為 0，數值無變化」。

兩個 issue 是同一條技術線，本 spec 一次解決：建立 delta 比對基礎建設（#13），並以此表達 #38 的政策。

**核心立意（不可妥協）**

> testpilot 最主要的核心價值是乾淨可測穩定的 test case。本 spec 的所有取捨優先「強制遷移到乾淨格式」而非保留雙軌；不接受「workbook 期望 fail 因此用 `equals '0'` 當 PASS」這類語意倒裝的 case 寫法。

---

## 2. Scope

### In scope

- 在 `wifi_llapi/plugin.py` 新增 `delta_nonzero` / `delta_match` 兩個 operator
- 在 yaml step 層級新增 `phase: baseline | trigger | verify` 欄位
- 在 case 載入階段新增 phase ordering schema 驗證
- 在 `wifi_llapi_excel.py` 新增 M 欄 (`Comment`) 用於失敗註解
- 將 `WifiLlapiCaseResult.comment` 從 dead field 接上 M 欄寫入路徑
- 遷移 ~30 個 Stage A 案例（明確 fail/retry/error/discard counter）到 delta 範式
- 遷移 ~50 個 Stage B 案例（流量類 generic counter）到 delta 範式
- 新增交付物：`plugins/wifi_llapi/CASE_YAML_SYNTAX.md`（long-lived yaml syntax reference）

### Out of scope

- 把 counter validation 邏輯抽到 `src/testpilot/core/`（YAGNI；未來真有第二個 plugin 要用再做）
- `_compare()` 既有 operator 的修改 / 簽名變動
- 既有評估路徑的 `pass_criteria_not_satisfied` 細化 — 已開 **#39** 跟蹤
- 既有 ~50 個 Stage C 設定類 / 狀態類用 `equals '0'` 案例（D064 / D071 / D076 / D086 / D098 / D183 / D354 / D427-D435 等）— 它們是合法 setpoint 等值斷言，不是 counter
- workbook source xlsx 結構驗證
- BLOCKED / SKIP 的視覺渲染（仍寫 H 欄）
- 真實硬體 trigger workload 自動化（需 attenuator / 干擾源 HW）

---

## 3. Architecture Overview

### 三層職責

| 層 | 元件 | 職責 |
|---|---|---|
| **yaml** | case file | step 上標 `phase: baseline / trigger / verify`；用新的 `delta` pass-criteria 表達 delta 規則 |
| **runtime** | `wifi_llapi/plugin.py` | 沿用既有 step 線性執行；evaluate 階段依 phase 取 baseline/verify capture，呼叫 `delta_nonzero` / `delta_match` |
| **reporter** | `wifi_llapi_excel.py` | 失敗時把 `WifiLlapiCaseResult.comment` 寫入新增的 M 欄；既有 G~L 行為與 BLOCKED/SKIP 路徑不變 |

### 資料流

```
yaml case ──► step exec ──► capture (baseline) ──┐
                  │                                ├─► delta evaluator ──► verdict
                  ▼                                │      (new ops)         + comment
              trigger step (workload)              │
                  │                                │
                  ▼                                │
              capture (verify) ─────────────────── ┘
                                                          │
                                                          ▼
                                              WifiLlapiCaseResult
                                              ├─ result_*: PASS / FAIL  → I/J/K
                                              └─ comment:  失敗註解      → M (新)
```

### 關鍵設計取捨

1. **不新增 step 區塊、用 phase 欄位** — 沿用現有 `for step in case.steps` 線性執行流，phase 只是標籤，不動 step machinery
2. **delta operator 兩個就夠** — `delta_nonzero` (#38 政策) 與 `delta_match` (#13 一致性，含 tolerance)；其餘 corner case 由 yaml 多寫一條 criterion 表達
3. **comment 字串走預設常數** — `ZERO_DELTA_COMMENT = "fail 原因為 0，數值無變化"`，case yaml 不可覆寫，保證一致性與可搜尋性
4. **不抽 core** — counter validation 邏輯留在 plugin；遵守 rule of three

---

## 4. YAML Schema

### Step 端：新增 `phase:` 欄位

```yaml
steps:
- id: step_5g_api_baseline
  phase: baseline                         # 新欄位：baseline | trigger | verify
  capture: api_before_5g
  command: ubus-cli "WiFi.AccessPoint.1.AssociatedDevice.1.Retransmissions?"

- id: step_5g_drv_baseline
  phase: baseline
  capture: drv_before_5g
  command: wl -i wl0 sta_info $STA_MAC | sed -n 's/.*tx pkts retries: *\([0-9]*\).*/DriverRetransmissions=\1/p'

- id: step_5g_trigger                     # workload，case 自行設計
  phase: trigger
  command: ...                            # 例：iperf3 -u -b 0 -l 1400 --pacing-timer 1

- id: step_5g_api_verify
  phase: verify
  capture: api_after_5g
  command: ubus-cli "WiFi.AccessPoint.1.AssociatedDevice.1.Retransmissions?"

- id: step_5g_drv_verify
  phase: verify
  capture: drv_after_5g
  command: wl -i wl0 sta_info $STA_MAC | sed -n 's/.*tx pkts retries: *\([0-9]*\).*/DriverRetransmissions=\1/p'
```

**規則：**

- `phase` 為 optional；未標的 step 預設為 `verify`（向後相容、零遷移壓力）
- 一個 step 只能屬於一個 phase；互斥
- 任何 case 含 `delta_*` operator 時，必須滿足「所有 baseline 排在所有 trigger 之前；所有 verify 排在所有 trigger 之後」，否則 case 被標 BLOCKED（fail-fast）

### pass_criteria 端：兩個新 operator

```yaml
pass_criteria:
# #38 政策 — trigger 後 delta 必須非 0
- delta:
    baseline: api_before_5g.Retransmissions
    verify:   api_after_5g.Retransmissions
  operator: delta_nonzero
  description: 5g API 端 Retransmissions 在 trigger 後必須成長

# #13 政策 — API delta 必須與 driver delta 一致 (±10%)
- delta:
    baseline: api_before_5g.Retransmissions
    verify:   api_after_5g.Retransmissions
  reference_delta:
    baseline: drv_before_5g.DriverRetransmissions
    verify:   drv_after_5g.DriverRetransmissions
  operator: delta_match
  tolerance_pct: 10
  description: 5g API delta 須與 driver delta 在 ±10% 之內
```

### Operator 語意

| operator | PASS 條件 | 失敗時 reporter comment |
|---|---|---|
| `delta_nonzero` | `verify - baseline > 0`（嚴格大於；`==0` 與負數都 FAIL） | `"fail 原因為 0，數值無變化"` |
| `delta_match` | `\|api_delta - drv_delta\| / max(\|api_delta\|, \|drv_delta\|) <= tolerance_pct/100`，且兩端皆 > 0 | 兩端有任一 ≤ 0：`"fail 原因為 0，數值無變化"`；超 tol：`"fail 原因為 delta 不一致：api=X drv=Y tol=Z%"` |

### 特意不做的事

- ❌ 不引入 `tolerance_abs` / `expected_min_delta` / `retry_trigger_n` (YAGNI)
- ❌ 不為 `delta_*` 加 `value:` 欄位（避免與 `delta:` 共存產生歧義）
- ❌ case 不可覆寫 reporter 註解字串（一致性 > 個別表達力）

### 額外交付物：`plugins/wifi_llapi/CASE_YAML_SYNTAX.md`

Long-lived yaml syntax reference（非本 spec 文件本身），與 plugin code colocate。內容涵蓋：

- case top-level 欄位（`id / name / version / source / platform / hlapi_command / llapi_support / implemented_by / bands / topology / test_environment / setup_steps / sta_env_setup / test_procedure / steps / pass_criteria / verification_command`）— 由實作 phase 1 inventory 既有 case 的真實使用情況
- step 欄位（`id / target / action / capture / command / depends_on / expected / description / **phase**`）
- pass_criteria 三種形狀：`field+value` / `field+reference` / `delta+(reference_delta)`
- operator 完整列表：既有 `equals / != / contains / not_contains / regex / not_empty / empty / >= / <= / > / < / skip` + 新增 `delta_nonzero / delta_match`
- skip / blocked / Support / Blocked 等 `llapi_support` 對應寫法
- schema 驗證規則（必填、互斥、phase ordering 約束）
- 三段範例：standard case、counter-delta case、blocked case

不做：JSON Schema / pydantic 自動驗證 source-of-truth、auto-generated（人工維護即可）。

---

## 5. Runtime Flow & Operator Implementation

### evaluate 的 dispatch 改動

`Plugin.evaluate()` 既有的 `for criterion in pass_criteria` 線性掃描不動，只在進入 criterion 處理時加一個 dispatch：

```python
for idx, criterion in enumerate(criteria):
    if "delta" in criterion:                        # ← 新分支
        ok = self._evaluate_delta_criterion(case, context, criterion, idx)
    else:
        ok = self._evaluate_field_criterion(...)    # ← 既有邏輯抽函式，行為不變
    if not ok:
        return False
```

`field+value/reference` 路徑**完全不動**；只有出現 `delta:` key 才走新路徑。對既有 case 零回歸風險。

### `_evaluate_delta_criterion()` 流程

```
1. 解析 criterion["delta"] = {baseline: "<cap>.<key>", verify: "<cap>.<key>"}
2. baseline_val = self._resolve_field(context, delta["baseline"])
3. verify_val   = self._resolve_field(context, delta["verify"])
4. 兩值轉 number；任一無法轉 → FAIL (reason_code="delta_value_not_numeric")
5. delta_a = verify_val - baseline_val
6. operator dispatch:
   - delta_nonzero:
       pass = (delta_a > 0)
       on fail comment: ZERO_DELTA_COMMENT
   - delta_match:
       重複 1-5 解 reference_delta → delta_b
       require: delta_a > 0 且 delta_b > 0  (任一 ≤ 0 → reason_code="delta_zero_side")
       require: |delta_a - delta_b| / max(delta_a, delta_b) <= tolerance_pct/100  (否則 reason_code="delta_mismatch")
7. 失敗時呼叫既有 self._record_runtime_failure(
       case, phase="evaluate", comment=<上述字串>,
       category="test", reason_code=<...>,
       metadata={"delta_a":..., "delta_b":..., "tolerance_pct":...}
   )
```

### 新增常數

```python
# plugins/wifi_llapi/plugin.py
ZERO_DELTA_COMMENT = "fail 原因為 0，數值無變化"
```

### Phase ordering schema 驗證

加在 `Plugin.discover_cases()` 後：

```python
def _validate_phase_ordering(case) -> str | None:
    """Returns error string if invalid; None if OK."""
    has_delta = any("delta" in c for c in case.get("pass_criteria", []) if isinstance(c, dict))
    if not has_delta:
        return None  # 沒用 delta operator 就不檢查 phase

    phases = [(s.get("id"), str(s.get("phase","verify")).lower()) for s in case.get("steps",[])]
    last_baseline_idx = max((i for i,(_,p) in enumerate(phases) if p=="baseline"), default=-1)
    first_trigger_idx = next((i for i,(_,p) in enumerate(phases) if p=="trigger"), -1)
    last_trigger_idx  = max((i for i,(_,p) in enumerate(phases) if p=="trigger"), default=-1)
    first_verify_idx  = next((i for i,(_,p) in enumerate(phases) if p=="verify"), -1)

    if first_trigger_idx == -1:
        return "delta_* operators require at least one phase=trigger step"
    if last_baseline_idx >= first_trigger_idx:
        return f"baseline step must precede trigger; last_baseline={last_baseline_idx}, first_trigger={first_trigger_idx}"
    if first_verify_idx <= last_trigger_idx:
        return f"verify step must follow trigger; last_trigger={last_trigger_idx}, first_verify={first_verify_idx}"
    return None
```

**違規處理**：把該 case 標為 BLOCKED（`blocked_reason="invalid_delta_schema: <error>"`），交給既有 `fill_blocked_markers()` 寫進 H 欄。**不 raise，不影響其他 case 載入**。

### `_compare()` 不動

新 operator 不掛在 `_compare()` 裡（不是 single actual vs single expected 形狀）。新 operator 走獨立的 `_evaluate_delta_criterion()`。

### reason_code 對應表（本 spec 新增的 5 個）

| 失敗情境 | reason_code | category | comment |
|---|---|---|---|
| schema 驗證失敗 | `invalid_delta_schema` | (走 BLOCKED 路徑，非 runtime failure) | H 欄：`"BLOCKED: invalid_delta_schema: <error>"` |
| baseline / verify 無法 resolve 為數字 | `delta_value_not_numeric` | `test` | M 欄：`"fail 原因為 delta 端點非數值"` |
| `delta_nonzero` 失敗 | `delta_zero` | `test` | M 欄：`"fail 原因為 0，數值無變化"` |
| `delta_match` 兩端有任一 ≤ 0 | `delta_zero_side` | `test` | M 欄：`"fail 原因為 0，數值無變化"` |
| `delta_match` 兩端皆成長但差距超 tolerance | `delta_mismatch` | `test` | M 欄：`"fail 原因為 delta 不一致：api=X drv=Y tol=Z%"` |

> 既有 `pass_criteria_not_satisfied` 維持不動；其體系細化見 **#39**。

---

## 6. Reporter — 新增 M 欄為失敗註解欄

### `wifi_llapi_excel.py` 改動清單

| 位置 | 改動 |
|---|---|
| `DEFAULT_TEMPLATE_MAX_COLUMN` | `"L"` → `"M"` |
| 新增 `COMMENT_HEADER` | `"Comment"` |
| `DEFAULT_CLEAR_COLUMNS` | 加 `"M"`（template 清空時也清 M 欄） |
| `_normalize_template_headers()` | row 3 增加 `ws.cell(row=3, column=13).value = COMMENT_HEADER` |
| `fill_case_results()` | 既有 G/H/I/J/K/L 不動；新增 `_set_cell_value_safe(ws, row, "M", _truncate_comment(item.comment))` |
| `WifiLlapiCaseResult.comment` | 從 dead field 變成有實際寫入；長度上限 200 字、超過 truncate + `"..."` |

### M 欄寫入規則

| 情境 | M 欄內容 |
|---|---|
| 全部 PASS | 空 |
| `delta_nonzero` 失敗 | `"fail 原因為 0，數值無變化"` |
| `delta_match` 失敗（兩端任一為 0） | `"fail 原因為 0，數值無變化"` |
| `delta_match` 失敗（差距超 tolerance） | `"fail 原因為 delta 不一致：api=X drv=Y tol=Z%"` |
| `delta_*` 端點無法 resolve 為數字 | `"fail 原因為 delta 端點非數值"` |
| 既有 evaluate 失敗（非 delta 路徑） | 沿用既有 `_record_runtime_failure` 的 `comment` 字串（細化交給 #39） |
| BLOCKED / SKIP | M 欄空（`fill_blocked_markers()` / `fill_skip_markers()` 不寫 M 欄；簡述仍由 H 欄承擔，因為 BLOCKED/SKIP 表示「沒測 / 需要重測」，與 evaluate 失敗語意層級不同） |

### Source xlsx 沒有 M 欄怎麼辦

`build_template_from_source()` 既有的 `_trim_sheet_to_max_column()` 會自動保留到第 13 欄；source xlsx 若原本沒有第 13 欄就維持空欄，由 `_normalize_template_headers()` 補上 M 欄 header。**source 端不需要修改**。

---

## 7. Migration Plan — 存量 case

### 範圍判定 — 三層過濾流程

```
Stage A（必遷，~30 case）── api 名稱含 Retry / Retrans / Fail / Error / Drop / Discard / Glitch / BadPLCP
                           且 llapi_support: Support
                           ─► 預設走 delta_nonzero + delta_match

Stage B（個案判斷，~50 case）── api 名稱含 Count / Bytes / Packets / Stats
                                 ─► 進一步區分：
                                    ├─ counter 語意（會被流量推動）→ 遷 delta_nonzero + delta_match
                                    └─ 靜態屬性 / 儀器讀數 → 不遷，繼續用 equals + reference

Stage C（不遷，~50 case）── pass_criteria 用 equals '0' 但 api 是設定 / 狀態類
                            ─► 合法的 setpoint 等值斷言，不是 counter，明確排除
```

### Stage A 詳細名單（必遷）

```
D037, D038, D051, D052, D054                         # AssociatedDevice retransmissions / errors
D267, D268, D269, D270                               # getradiostats discard / errors
D304, D305, D306, D307, D308                         # getssidstats discard / errors / failedretranscount
D313, D316                                           # getssidstats RetransCount / UnknownProtoPackets
D325, D326, D327, D328, D329, D334                   # ssid_stats discard / errors / failedretrans / retrans
D396, D397, D398, D399, D401, D402                   # radio_stats errors / retry / retrans
D406, D407, D448, D451                               # radio_stats retry / preamble error pct
D452, D453, D454, D455, D457, D458                   # vendor stats badplcp / glitch / radio retry / retrans
D495, D580                                           # retrycount verified / affiliated sta errors
```

> Wave 1 樣板中的 **D313** 是刻意保留的例外：它用來示範 **multi-band baseline/trigger/verify phase** 與共享 trigger phase 的描述方式，因此只要求每個 band 的 `delta_nonzero`。  
> Wave 1 的 `reference_delta + delta_match` 樣板由 **D037** 承擔；等到後續 wave 為 getSSIDStats 家族選定穩定的 companion counter 後，再把同家族遷移收斂到完整的 cross-source delta_match 範式。

### Stage B 預估遷移名單

```
D031, D039, D040, D041, D042, D053, D055, D056, D057    # AssociatedDevice rx/tx bytes / packets
D128, D130, D131, D132, D135, D136, D137                # getstats rx/tx bytes / packets / retransmissions
D263-D266, D271-D276                                    # getradiostats bcast / mcast / ucast / bytes / packets
D300-D303, D309-D315                                    # getssidstats bcast / mcast / ucast / bytes / packets
D321-D324, D330-D337                                    # ssid_stats bcast / mcast / ucast / bytes / packets
D394, D395, D477, D576-D579                             # radio bytes / unknown proto / affiliated sta bytes/packets
```

### Stage C — 明確排除

D064 / D065 / D068 / D071 / D072 / D075-D082 / D086 / D090 / D093 / D098 / D104 / D105 / D179 / D183 / D251 / D354 / D366 / D369 / D427-D435 等 ~50 個用 `equals '0'` 但實為設定 / 狀態斷言的 case。**本 spec 不動**。

### 每個遷移 case 的 yaml 改動模板

以 D037 為例：

```yaml
# 遷移前
pass_criteria:
- field: result.Retransmissions
  operator: equals
  value: '0'
  description: 'Workbook v4.0.3 marks this API as Fail: LLAPI Retransmissions still reads 0.'  # ← 刪除
- field: driver_counter.DriverRetransmissions
  operator: '>'
  value: '0'

# 遷移後
steps:
- id: step_5g_api_baseline
  phase: baseline
  capture: api_before_5g
- id: step_5g_drv_baseline
  phase: baseline
  capture: drv_before_5g
- id: step_5g_trigger
  phase: trigger
  command: <workload>
- id: step_5g_api_verify
  phase: verify
  capture: api_after_5g
- id: step_5g_drv_verify
  phase: verify
  capture: drv_after_5g

pass_criteria:
- delta:
    baseline: api_before_5g.Retransmissions
    verify:   api_after_5g.Retransmissions
  operator: delta_nonzero
- delta:
    baseline: api_before_5g.Retransmissions
    verify:   api_after_5g.Retransmissions
  reference_delta:
    baseline: drv_before_5g.DriverRetransmissions
    verify:   drv_after_5g.DriverRetransmissions
  operator: delta_match
  tolerance_pct: 10
```

### Trigger workload 設計類別參考

| Counter 性質 | 典型 trigger workload |
|---|---|
| Retrans / Retry | iperf3 UDP 灌流 + 刻意降 RSSI / 干擾源 |
| TxErrors / FailedRetransCount | 同上 + 短封包 burst 製造 PHY 失敗 |
| Discard / Drop | iperf3 UDP 超 link capacity；multicast flood |
| RxBytes / TxBytes / *PacketCount | iperf3 UDP/TCP 任意工況；最容易 |
| BroadcastPackets / MulticastPackets | ping broadcast / multicast |
| BadPLCP / Glitch | 干擾源 / 鄰頻打 noise |

### PR 切分 — 三 wave

| Wave | 內容 | 規模 | 風險 |
|---|---|---|---|
| **Wave 1（基礎建設）** | runtime（phase 驗證 + delta operator）+ reporter（M 欄）+ `CASE_YAML_SYNTAX.md` + 2 個樣板 case（D037、D313） | 中 | 高 — 新基礎建設，需 unit test 完整覆蓋 |
| **Wave 2（Stage A）** | 遷移 ~30 個明確 fail/retry/error/drop case | 大 | 中 — 模式重複；trigger workload 設計成本不一 |
| **Wave 3（Stage B）** | 遷移 ~50 個 generic counter case | 大 | 低 — 多數可共用 iperf workload |

**Wave 1 必須先 merge 並通過 review**，再開 Wave 2/3 PR。Wave 2/3 可依 stat 群組（getradiostats / getssidstats / radio_stats / ssid_stats / associateddevice）進一步切 sub-PR。

---

## 8. Test Strategy

### Unit test（Wave 1 必交付）

放在 `tests/test_wifi_llapi_delta.py`（新檔）。

**A. `_evaluate_delta_criterion` 純函式邏輯**

| Test | 期望 |
|---|---|
| `test_delta_nonzero_pass` | baseline=10, verify=42 → PASS |
| `test_delta_nonzero_fail_zero` | baseline=10, verify=10 → FAIL，reason_code="delta_zero" |
| `test_delta_nonzero_fail_negative` | baseline=10, verify=5 → FAIL，reason_code="delta_zero" |
| `test_delta_nonzero_baseline_missing` | baseline 在 context 找不到 → FAIL，reason_code="delta_value_not_numeric" |
| `test_delta_nonzero_non_numeric` | verify="N/A" → FAIL，reason_code="delta_value_not_numeric" |
| `test_delta_match_pass_within_tolerance` | api=100, drv=109, tol=10% → PASS |
| `test_delta_match_pass_exact_match` | api=100, drv=100, tol=10% → PASS |
| `test_delta_match_fail_exceed_tolerance` | api=100, drv=120, tol=10% → FAIL，reason_code="delta_mismatch" |
| `test_delta_match_fail_one_side_zero` | api=100, drv=0 → FAIL，reason_code="delta_zero_side" |
| `test_delta_match_fail_both_zero` | api=0, drv=0 → FAIL，reason_code="delta_zero_side" |
| `test_delta_match_fail_negative_either_side` | 任一 delta 為負 → FAIL，reason_code="delta_zero_side" |
| `test_delta_match_tolerance_boundary` | api=100, drv=110, tol=10%（剛好）→ PASS（`<=` 包含邊界） |

**B. `_validate_phase_ordering` schema validator**

| Test | 期望 |
|---|---|
| `test_phase_ok_baseline_trigger_verify` | None（合法） |
| `test_phase_no_delta_skip_check` | None（沒有 delta criterion 不檢查） |
| `test_phase_missing_trigger` | error: "require at least one phase=trigger" |
| `test_phase_baseline_after_trigger` | error: "baseline step must precede trigger" |
| `test_phase_verify_before_trigger` | error: "verify step must follow trigger" |
| `test_phase_default_unmarked_is_verify` | step 沒寫 phase 視為 verify（向後相容） |
| `test_phase_invalid_value` | phase: "warmup" → error: "unknown phase: warmup" |

**C. dispatch — `evaluate()` 行為**

| Test | 期望 |
|---|---|
| `test_evaluate_field_path_unchanged` | 既有 `field+value` criterion 走原路徑、reason_code 仍為 `pass_criteria_not_satisfied`（regression guard） |
| `test_evaluate_delta_path_picks_new_dispatch` | criterion 含 `delta:` key → 走新路徑，不誤觸 `_compare()` |
| `test_evaluate_mixed_criteria` | 同 case 內混 field criterion 與 delta criterion，依序評估，第一個 fail 即停 |
| `test_invalid_delta_schema_marks_blocked` | phase 違規的 case 在 discover 階段被標 BLOCKED、不進到 evaluate |

### Integration test（Wave 1 必交付）

放在 `tests/test_wifi_llapi_delta_integration.py`。

**D. yaml fixture 端到端** — 用 `tests/fixtures/wifi_llapi_delta/` 放 3 個 fixture case：

- `delta_nonzero_pass.yaml` — baseline/trigger/verify mock 數值 PASS
- `delta_nonzero_fail.yaml` — verify 數值與 baseline 相同 → FAIL
- `delta_match_pass.yaml` — api/drv 兩端都成長且差距在 tol 內

跑 `Plugin.discover_cases() → execute_step()（mocked transport）→ evaluate() → fill_case_results()`，斷言 xlsx I/J/K 為 PASS / FAIL，M 欄為預期 comment 字串。

**E. reporter 行為** — 擴充 `tests/test_wifi_llapi_excel.py`：

| Test | 期望 |
|---|---|
| `test_template_max_column_is_M` | `_normalize_template_headers` 在 row 3 column 13 寫 "Comment" |
| `test_clear_columns_includes_M` | `DEFAULT_CLEAR_COLUMNS` 包含 "M" |
| `test_fill_case_results_writes_M` | `WifiLlapiCaseResult.comment` 內容寫入 M 欄 |
| `test_fill_case_results_truncates_long_comment` | comment > 200 字 → 截斷至 200 + "..." |
| `test_fill_case_results_empty_comment` | comment 為空時 M 欄為空、不寫 None |
| `test_blocked_marker_writes_H_not_M` | regression guard：BLOCKED 仍走 H 欄 |
| `test_skip_marker_writes_H_not_M` | regression guard：SKIP 仍走 H 欄 |

### Migration smoke（Wave 2/3 PR 必跑、不入 CI）

每個 Wave 2/3 PR 在 review 前，PR 作者需在描述中提供：

1. Emulated suite 跑完截圖（`pytest plugins/wifi_llapi/`，mock transport）
2. `CASE_YAML_SYNTAX.md` 同步更新（若 wave 中發現 schema 需要新欄位 / 例外）
3. 本 wave case 列表 diff（從 `equals '0'` 改成 `delta_*` 的清單）

不要求實機 trigger workload 執行（需 attenuator / 干擾源 HW，不適合 CI 化）。

### CI gating

**Wave 1 PR 要 merge 必須：**

- ✅ Unit test (A/B/C) 全綠
- ✅ Integration test (D/E) 全綠
- ✅ `tests/test_wifi_llapi_excel.py` 既有測試無 regression
- ✅ `pytest tests/` 全 suite 無 regression

**Wave 2/3 PR 要 merge：** 上述條件 + Migration smoke 證據附在 PR 描述 + 該 wave 改動的 case 在 emulated suite 拿到預期 verdict

### 不在測試範圍

- workbook source xlsx 結構驗證
- `_compare()` 既有 operator 的 regression（Wave 1 不動 `_compare()`）
- 既有 BLOCKED/SKIP 視覺渲染
- 真實硬體 trigger workload 自動化

---

## 9. Deliverables Checklist

Wave 1（基礎建設 PR）必須交付：

- [ ] `plugins/wifi_llapi/plugin.py`：`_evaluate_delta_criterion()` / `_validate_phase_ordering()` / `ZERO_DELTA_COMMENT` / dispatch 修改
- [ ] `src/testpilot/reporting/wifi_llapi_excel.py`：M 欄相關常數 + header + write path + truncate
- [ ] `tests/test_wifi_llapi_delta.py`：Unit test A/B/C 全套
- [ ] `tests/test_wifi_llapi_delta_integration.py`：Integration test D
- [ ] `tests/test_wifi_llapi_excel.py`：Integration test E 擴充
- [ ] `tests/fixtures/wifi_llapi_delta/`：3 個 fixture case
- [ ] `plugins/wifi_llapi/CASE_YAML_SYNTAX.md`：完整 yaml syntax reference
- [ ] `plugins/wifi_llapi/cases/D037_retransmissions.yaml`：遷移為 delta 範式（`delta_nonzero + delta_match` 樣板 case）
- [ ] `plugins/wifi_llapi/cases/D313_getssidstats_retranscount.yaml`：遷移為 multi-band delta 範式（shared trigger phase + per-band `delta_nonzero` 樣板 case）

Wave 2 / Wave 3 各自的遷移 PR 內容見 §7。

---

## 10. Open Questions / Follow-ups

- **#39** — `pass_criteria_not_satisfied` 細化（從 brainstorming 直接開出，本 spec 不做）
- 未來若有第二個 plugin 需要 delta 比對，再考慮把 counter validation 抽到 `src/testpilot/core/`（rule of three）
- Trigger workload 的硬體 setup（attenuator / 干擾源）— 本 spec 不規範，由 case 設計者依現場資源決定

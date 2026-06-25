# Plugin SDK 解耦工程 — MOC(Map of Content)

> 更新日期:2026-06-18
> 角色:本工程的**單一 canonical 地圖**。各 stage 的 spec/plan/change/PR 皆由此索引。
> 母 spec:`docs/superpowers/specs/2026-06-17-testpilot-plugin-sdk-design.md`

## 終局目標

把 `wifi_llapi` 從主 repo 切成**獨立 repo + pip 套件**,透過 `entry_points` 被 testpilot 自動發現;testpilot 本體收斂為**裝置中立的 plugin host 框架**,對 plugin 只承諾**穩定、版本化的公開契約(`testpilot.api`)**。`wifi_llapi` 是這個契約的第一個 dogfood 驗收者。

## 「完全解耦可測」的可量測判準

工程完成 = 同時滿足三條:

1. **boundary allow-list 清空** — `plugins/<plugin>/` production 對 `testpilot.core/schema/reporting/transport` 內部的 import **與方法呼叫**歸零(只依賴 `testpilot.api`)。
2. **物理獨立** — wifi_llapi 為獨立 repo + pip 套件,經 entry_point 被發現。
3. **雙 repo full-run CI 接回** — 目前 skip 的 `tests/test_audit_runner_facade.py`(needs full testbed)在跨 repo CI 重新啟用。

> ⚠️ 已知盲點:現行 boundary 守門只掃 **import**,抓不到 `orchestrator._method()` 這種對傳入物件的**方法呼叫耦合**。B2 把 run loop 移進 core 後此耦合自然消失;在那之前 allow-list 低估真實耦合面(runner 另有 6 個 orchestrator 私有方法呼叫)。

## Stage 路線圖

| 標籤 | 名稱 | 狀態 | 母spec 對應 | 產出 |
|---|---|---|---|---|
| **P1** | 公開層 `testpilot.api` + 堵低風險洩漏 | ✅ 已 merge | P1 前半 | [spec](specs/2026-06-17-testpilot-plugin-sdk-design.md) · [plan](plans/2026-06-17-testpilot-api-public-layer.md) · change `establish-testpilot-api-public-layer`(archived)· **PR #75** · issue #74 · capability `plugin-sdk-public-api` |
| **P1b** | reporter↔execution 解耦(runner/reporter 切兩塊 + RunResult) | ✅ 已 merge | P1 最大未知 | [spec](specs/2026-06-17-reporter-execution-decouple-design.md) · [plan](plans/2026-06-17-reporter-execution-decouple.md) · change `decouple-reporter-from-execution`(archived)· **PR #77** · issue #76 · capability `plugin-runner-reporter-separation` |
| **B1** | serialwrap → `RunBackend` 抽象(可換 provider) | 🟡 spec+plan 完,實作待 workflow | (新增,從自由原則展開) | [spec](specs/2026-06-18-serialwrap-runbackend-abstraction-design.md) · [plan](plans/2026-06-18-serialwrap-runbackend-abstraction.md) · change `abstract-serialwrap-runbackend`(4/4 valid) · capability `run-backend-abstraction` |
| **B2** | core-owned execution loop（run loop 上移 core）+ alignment 唯讀化（修 audit-invariant 違規） | 🟡 spec+plan 完,實作待 workflow | P1 host 願景核心 | [spec](specs/2026-06-18-core-owned-execution-loop-design.md) · [plan](plans/2026-06-18-core-owned-execution-loop.md) · change `core-owned-execution-loop`(ADDED + MODIFIED plugin-runner-reporter-separation) |
| **P2a** | entry_points 發現 + in-repo packaging | 🟡 spec+plan 完,實作待 workflow | 母spec P2 | [spec](specs/2026-06-18-entry-points-discovery-design.md) · [plan](plans/2026-06-18-entry-points-plugin-discovery.md) · change `entry-points-plugin-discovery` · capability `plugin-entry-points-discovery` |
| **P2b** | versioned contract（API_VERSION + 相容檢查) | 🟡 spec+plan 完,實作待 workflow | 母spec P2 | [spec](specs/2026-06-18-versioned-plugin-contract-design.md) · [plan](plans/2026-06-18-versioned-plugin-contract.md) · change `versioned-plugin-contract` · capability `versioned-plugin-contract` |
| **P3** | CLI 解耦(#70,register_cli) | 🟡 spec+plan 完,實作待 workflow | 母spec P3 | [spec](specs/2026-06-18-cli-decoupling-register-cli-design.md) · [plan](plans/2026-06-18-cli-decoupling-register-cli.md) · change `decouple-cli-register-cli` · capability `plugin-cli-registration` · closes #70 |
| **P4** | 物理切分:**core 獨立 public** + wifi_llapi/brcm 私有 repo + 雙 repo CI 接回(audit 折入 wifi;rename/vendor-中立拆分/HLAPI/部署 延後) | 🟡 spec+plan 完,實作待 workflow | 母spec P4 | [spec](specs/2026-06-18-p4-physical-repo-split-design.md) · [plan](plans/2026-06-18-physical-repo-split.md) · change `physical-repo-split`(valid)· capability `plugin-physical-distribution` |

> 標籤沿用對話慣例:B1/B2 是 P1b 之後、P2 之前插入的執行解耦兩步。**不使用「Phase 1–7」**(會與母spec P1–P4 撞名)。

## 目前狀態 / 下次接續(2026-06-18 更新)

- **規劃 branch**:`feature/serialwrap-runbackend-abstraction` —— B1/B2/P2a/P2b/P3 的 spec+propose+plan + 本 MOC 源出此 branch,**已 merge main**(commit `e53b3237`,連同 P4)。
- **已完成規劃(待實作)**:B1、B2、P2a、P2b、P3、P4 —— 各有 spec(`docs/superpowers/specs/`)、OpenSpec change(`openspec/changes/`,皆 valid)、plan(`docs/superpowers/plans/`)。**程式碼尚未實作**(刻意:實作走 workflow;6 批共 123 tasks,目前 0 完成)。
- **P4 規劃已完成(2026-06-18)**:spec(`specs/2026-06-18-p4-physical-repo-split-design.md`)+ openspec change `physical-repo-split`(proposal/design/specs/tasks,valid)+ plan(`plans/2026-06-18-physical-repo-split.md`)全到位。**北極星:拆分目的=讓 core 獨立 public**;安全邊界=「凡 public,git log 須無機敏」。關鍵反向決策:**core 切到新 public repo(fresh 無歷史)、現 repo rename 成 private wifi_llapi(留全歷史)、brcm 開新 private repo(filter-repo 帶歷史)**;audit **折入 wifi**(不抽獨立包,因 MTK 未存在=無第二消費者);CI 用 B1 replay backend 接回 full-run 測試;部署只鎖契約、實作獨立下游 stage。**已開延後 issue**:α=**#78**(rename+vendor 中立 `LLAPI-AUDIT`,gate MTK)、β=**#79**(HLAPI 共用入口);部署為下游 stage(自有 spec/plan,非 issue)。

### 下次接續步驟(順序)

1. ✅ **已完成**:整個規劃 branch merge 進 main(commit `e53b3237`,B1/B2/P2a/P2b/P3/P4 全部 spec/plan/change + MOC 成為 main living docs)。
2. ✅ **已完成**:開 issue α=**#78**(rename + audit vendor 中立拆分,gate MTK)、β=**#79**(HLAPI 共用入口抽取)。
3. **跑實作 workflow**,各 stage **各自開 branch/worktree**,依依賴順序:
   - **B1 → B2**(B2 寫在 B1 RunBackend 上)
   - **P2a → P2b**(P2b 檢查落在 P2a 改的 loader.load)
   - **P3**(可與 P2 線並行)
   - **P4**(依賴全部:allow-list 清空[B1+B2]、entry_points[P2a]、versioned[P2b]、CLI 中立[P3];另:audit 折出前驗 §前置健檢)
4. 每個實作 workflow:TDD/subagent-driven → requesting-code-review → openspec-archive → policy/commit/push/PR(R-12/R-17)。

> 提醒:這些 OpenSpec change 目前都 valid 但**未 archive**(實作完才 archive)。實作前 `openspec list` 會看到 9 個 active change(本批 6 個 B1/B2/P2a/P2b/P3/P4 + decouple-core-wifi-llapi 舊整包[**已標 SUPERSEDED**,見其 proposal.md,不再實作] + wifi-llapi-counter-delta-validation/inventory-runtime-repair 既有)。

## 依賴圖

```
P1 ✅ ──► P1b ✅ ──► B1 ──► B2 ─┐
                                 ├──► P4(物理切出)──► 雙 repo CI ──► 完全解耦可測
P1 ✅ ──► P2a ──► P2b ────────────┤
P1 ✅ ──► P3 ─────────────────────┘
```

- **B1 → B2**:B2 的 core 迴圈要寫在 B1 的 `RunBackend` 抽象上;先 B1 再 B2,避免迴圈先綁 serialwrap 再重抽(雙工)。
- **P2a → P2b**:P2b 的相容檢查落在 P2a 改過的 `loader.load()`;先 P2a 再 P2b。
- **(P2a→P2b) ∥ P3**:發現/版本化 與 CLI 解耦 互相獨立,可並行(母spec §96「P3 可與 P2 並行」)。兩線也與 B1/B2 大致獨立(不同檔域)。
- **P4 依賴全部**:需 allow-list 清空(B1+B2)、entry_points 發現(P2a)、versioned contract(P2b)、CLI 中立(P3)才切得乾淨。

## 跨 stage 已定調的設計決策

- **執行歸屬 = core-owned(B2)**,非把執行 primitive 升 public。理由:符合「plugin **host** 框架」願景;public 化會把 serialwrap/session 內部凍結成永久契約(最嚴重的過早固化)。詳見 B1/B2 spec。
- **serialwrap = 可換 provider(B1)**:引入 `RunBackend` 抽象(lifecycle + log capture 一體),serialwrap 為預設 impl、direct-ttyUSB 介面預留。命令層 `Transport` 已抽象、保留獨立。
- **行為層 / 執行面分離,映射在 provider**:case YAML 維持行為層(shell/行為,**零 case 要改**);`RunBackend` provider 持有「行為→具體指令」realization(serialwrap 用宣告式表)。可追溯靠 provider 把實際指令記進 trace。
- **增量、行為保真**:每 stage 各自 spec→plan→change,golden 測試為位元級不變的安全網。符合 [[feedback-testpilot-core-value]]「乾淨、不留雙軌或語意模糊地帶」。

## 殘留債(已追蹤,需有歸屬)

- **boundary allow-list(production)**:`runner.py` 的 `ExecutionEngine`/`build_case_session_plan`/`log_capture`(B1 清 log_capture、B2 清 ExecutionEngine/build_case_session_plan);`case_validation.py` 的 schema 私有 `_require_non_empty_string`/`_validate_string_list`(P2 versioned contract 決定升 public 或契約化)。
- **守門盲點**:import-only 掃描漏掉方法呼叫耦合(B2 後自然消解)。
- **audit-invariant 違規(現行 bug,B2 修)**:正常 run 路徑 `runner._prepare_alignment → apply_alignment_mutations` **改寫/重命名 `plugins/wifi_llapi/cases/*.yaml`**,違反 audit-mode spec「`testpilot run` SHALL NOT 修改 plugin/cases/」。無測試守門(本該抓的 `test_audit_runner_facade` 被 skip)。**B2 修正**:run 路徑 alignment 唯讀化(in-memory 算 row 供報表落點,不寫檔);drift case 照跑、報表 reason 不論 pass/fail 標 `drift=blocked(需 audit)`;持久化對齊只留 `audit apply`。並補守門測試(run 不改 cases/)。
- **audit 拆分(P4 已定調)**:`src/testpilot/audit/` 為混血(generic 框架 + wifi 具名)。**因 MTK 未存在=無第二 audit consumer,P4 不抽獨立包**;整包**折入 wifi_llapi**(脫 `testpilot.` namespace),core 甩掉 audit。折出前須解 audit→core 耦合:`validate_case`/`CaseValidationError` 已在 `testpilot.api`(換 import 即可)、`case_d_number` 待公開/內聯、`Orchestrator`(runner_facade)走 **B2** core-owned 執行入口。內部保持 generic/具名 模組邊界乾淨,供 issue α(**#78**)未來機械式抽 `LLAPI-AUDIT`。
- **platform 考量(P4 已定調)**:vendor 確認指令 + env setup 換 vendor 改動 >60%,**vendor 隨 plugin 走**(各自獨立 plugin,不抽共用 LLAPI 層)。rename `wifi_llapi→LLAPI-WIFI-BCM` + 新建 `LLAPI-WIFI-MTK` **延後 issue α(#78)**(gate 在 MTK 真的要做)。case 內 HLAPI(TR-181 (object,api))共用入口抽取 **延後 issue β(#79)**(待兩套語料庫可見、沿實際縫抽)。

## 作業流程(每個 stage)

`brainstorm → spec(docs/superpowers/specs/)→ openspec-propose → writing-plans(docs/superpowers/plans/)→ **workflow** 跑 TDD/subagent-driven → requesting-code-review → openspec-archive → policy/commit/push/PR`。governance 見 [[reference-testpilot-pr-governance]](feature/<slug> R-12、PR closing keyword R-17)。

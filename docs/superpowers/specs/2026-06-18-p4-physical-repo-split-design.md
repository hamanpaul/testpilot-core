# P4:物理切分(core 獨立 public + plugin 私有化)— 設計 spec

> 制定日期:2026-06-18
> 狀態:草案(brainstorm 已定調,待 review)
> MOC:`docs/superpowers/plugin-sdk-decoupling-MOC.md`
> 母 spec:`docs/superpowers/specs/2026-06-17-testpilot-plugin-sdk-design.md`(P4)
> 前置(須先實作並 merge):B1、B2、P2a、P2b、P3(見 §依賴與前置)

## Goal

把 monorepo 物理切成多個 repo,**讓 `testpilot` core 能獨立成 public**:

- **core** → 全新 public repo(裝置中立 plugin host + `testpilot.api` + 整體架構文件)。
- **wifi_llapi**(含折入的 audit)→ 現 repo 原地 rename、留全歷史、設 private。
- **brcm_fw_upgrade** → 新 private repo(filter-repo 帶歷史過去)。

各 repo 以 pip 套件發布、經 `entry_points`(group `testpilot.plugins`)被 core 發現,並接回目前 skip 的 full-run 測試(`tests/test_audit_runner_facade.py`),達成母 spec「完全解耦可測」三判準。

## Motivation(北極星與安全模型)

拆分的**真正目的是讓 core 能 public**。由此導出唯一的硬安全邊界:

> **凡是要 public 的 repo,其 git log 必須無機敏。**

現 monorepo 歷史累積了 lab config、vendor 詞彙、校準語料等內容(受 `AI-SEC-001` 管制:不得外洩網路/安全資訊、未授權機密、客戶/專案標籤)。因此 **core 不能沿用現有歷史**——必須在全新 repo 重起(無歷史);機敏歷史**留在 private 的 wifi_llapi repo**。這是「core 切出去重新開始、舊 repo rename 留歷史」這個反向切法的根因。

dogfood 驗收:wifi_llapi / brcm 切出後只依賴 `testpilot.api`,物理移出 core repo 仍能被發現、被執行——切得乾不乾淨即契約完不完整的證明。

## Scope

1. **三 repo 物理切分**:依 §架構 的拓樸建立/改名 repo、搬移檔案、設定可見性。
2. **audit 折入 wifi_llapi**:`src/testpilot/audit/` 從 core 移進 wifi plugin 套件(re-namespace + 解 core 內部耦合),core 徹底甩掉 audit;audit CLI 改由 plugin `register_cli()`(P3)註冊。
3. **每 repo 打包與相容**:pyproject 宣告 `entry_points`(P2a)、`api_version`(P2b)、`dependencies` pin `testpilot`(P2b);資源路徑(cases/reports/templates)以 `importlib.resources` 解析。
4. **governance scaffold 落地每 repo**:接 `paulsha-conventions` reusable policy-check(pinned SHA)+ 從 `new-project-template` scaffold;R-21 secret-scan 為 public core 的發布閘。
5. **CI 接回 full-run 測試**:wifi_llapi repo CI 以 **replay/fixture RunBackend**(B1)+ 錄製 golden serialwrap I/O,決定性地重啟 `test_audit_runner_facade`。跨 repo SDK 協調 = 釘選已發布版 + nightly 裝 `testpilot` main。
6. **整體架構文件搬到 core**(public),經 policy/secret-scan 閘後落地。

## Non-goals(本 stage 不做;見 §延後事項)

- **不** rename `wifi_llapi → LLAPI-WIFI-BCM`、**不**把 audit 抽成 vendor 中立 `LLAPI-AUDIT` 套件(無第二消費者 MTK,屬過早固化)。
- **不**做 HLAPI 共用入口抽取。
- **不**做部署/發布 infra 實作(publish 目標、private index、憑證管理、多 repo release governance 實作)——只鎖契約,實作獨立成下游 stage。
- **不**新建 `LLAPI-WIFI-MTK`(尚未存在)。

## 依賴與前置(P4 壓在這些之上,須先實作並 merge)

| 前置 | P4 依賴的具體點 |
|---|---|
| **B1** RunBackend 抽象 | CI 接回測試所需的 **replay/fixture provider** 落在 B1 的 `RunBackend` 上。 |
| **B2** core-owned execution loop | 解 `audit/runner_facade.py` 的 `testpilot.core.orchestrator.Orchestrator` 耦合;**B2 的 core-owned 執行入口須能被 audit 的 runner_facade 經 `testpilot.api` 取用**(不只 wifi runner 路徑)。allow-list(criterion #1)清空。 |
| **P2a** entry_points 發現 | 跨 repo 發現機制;P2a 已把 plugin 正規化為可安裝 package(P2a spec 明言「P4 退化成純搬檔」)。 |
| **P2b** versioned contract | 各 repo `api_version="1.0"` + `dependencies=["testpilot>=1.0,<2.0"]` + runtime 相容檢查。 |
| **P3** CLI 解耦 | audit CLI 與 wifi CLI 改由 plugin `register_cli()` 註冊,core `cli.py` 不再具名掛載。 |

**audit 折出的前置健檢(P4 開工前必驗):**

- `validate_case` / `CaseValidationError`:**已在 `testpilot.api`**(api/__init__.py)→ `audit/cli.py` import 換成 `testpilot.api`,trivial。
- `case_d_number`(`audit/runner_facade.py`):不在 api → 經 `testpilot.api` 公開,或於 runner_facade 內聯化。
- `Orchestrator`(`audit/runner_facade.py`):由 **B2** 提供 core-owned 執行入口取代直接 import;若 B2 spec 僅涵蓋 wifi runner 路徑、未涵蓋 audit runner_facade,**P4 須含補強或回頭修 B2**。

## 架構

### 1. 目標 repo 拓樸

| Repo | 內容 | 可見性 | git history | 機制 |
|---|---|---|---|---|
| **core**(新 repo) | `src/testpilot/`(host,不含 audit)+ `testpilot.api` + 整體架構文件(MOC/specs/plans/openspec)+ `plugins/_template` + governance scaffold | **public** | **fresh,無歷史** | sanitized → 全新 `git init` → R-21 secret-scan 閘 |
| **wifi_llapi**(現 repo rename) | `plugins/wifi_llapi/` + 折入的 `audit/` + cases/reports/tests + scaffold | private | **保留全歷史** | 現 repo 改名;working tree 移除 core/brcm;audit 折入 |
| **brcm_fw_upgrade**(新 repo) | `plugins/brcm_fw_upgrade/` + scaffold | private | **保留(filter-repo 帶過去)** | 從現 repo `git filter-repo` 抽出 |

依賴方向:private plugin repos → 依賴 public core(`pip install testpilot`)。**public core 不依賴任何 private plugin**(無反向洩漏)。

### 2. audit 折入 wifi_llapi

- 實體搬移:`src/testpilot/audit/` → wifi plugin 套件內(plugin namespace,**脫離 `testpilot.` 命名空間**;`testpilot.audit.*` 重寫為 plugin 套件路徑)。
- 解耦三點見 §前置健檢(validate_case 換 api;case_d_number 公開/內聯;Orchestrator 走 B2)。
- audit CLI:由 wifi plugin `register_cli()`(P3)掛載,**core `cli.py` 移除** `from testpilot.audit.cli import audit_group` 與 `main.add_command(audit_group)`。
- **內部仍保持「generic 框架 / wifi 具名」模組邊界乾淨**(同套件內分層),使未來「audit 抽成獨立 `LLAPI-AUDIT`」為機械式;**現在不建跨套件契約**(不製造雙軌)。
- plugin 自有的 `yaml_command_audit.py` 本就隨 plugin 走,不變。

### 3. 跨 repo 組裝(P2a/P2b)

- 各 plugin pyproject:`[project.entry-points."testpilot.plugins"]` 註冊;`api_version="1.0"`;`dependencies=["testpilot>=1.0,<2.0"]`。
- 安裝後組裝:`pip install testpilot`(core)+ `pip install wifi_llapi` + `pip install brcm_fw_upgrade` → core 經 `entry_points(group="testpilot.plugins")` 發現兩 plugin;P2b runtime 相容檢查把關。
- 資源路徑:cases/reports/templates 以 `importlib.resources` / `Path(module.__file__).parent` 解析(P2a 已定),隨套件走。

### 4. governance scaffold(每 repo)

- 接 `paulsha-conventions` reusable policy-check(`.project-policy.yml` + `policy-check.yml`,pinned SHA);從 `new-project-template` scaffold。
- **R-21 secret-scan = public core 發布閘**(micro 決議:policy 過即可,不另設人工複審)。
- 每 repo 各自的 R-12(branch `feature/<slug>`)/ R-17(PR closing keyword)沿用。

### 5. CI 設計

- **wifi_llapi repo**:加 replay/fixture RunBackend(B1)+ 錄製 golden serialwrap I/O;`test_audit_runner_facade` 由 `@pytest.mark.skip` 改為對 replay backend 執行 → **決定性接回**(判準 #3),無硬體、可在雲 CI 跑。
- **跨 repo SDK 協調**:plugin repo CI 預設裝**已發布、釘選版** `testpilot`(`>=1.0,<2.0`)跑回歸;另設 **nightly job 裝 `testpilot` main** 早期抓破壞(母 spec:版本檢查 P2b 為緩解)。
- **core repo**:移除 wifi/brcm 後,testpaths 不含 plugin 測試;core CI 在**無任何 vendor plugin** 下綠燈,證明 host 中立。

## 部署交接(契約鎖定,實作下游 stage)

P4 只**鎖部署契約**為邊界,不做 infra:

- 發布目標:core → public index;plugin → private index(具體 index/憑證/managed `testpilot` 命令 bootstrap / 多 repo release governance = 下游 stage)。
- 版本 pin = P2b;組裝 = entry_points。
- **P4 在 CI 以 git / test-index install 證明跨 repo 發現**,不依賴 production publish infra。

> 下游「部署 stage」接的是既有 release-install-governance 線(`2026-05-06-release-install-governance-design.md`),非本 SDK 解耦結構線。

## 遷移劇本(反向 big-bang,不留雙軌)

> 前提:B1+B2+P2a+P2b+P3 已實作 merge 進(現)main;boundary allow-list 空;§前置健檢 通過。

1. **brcm 抽出**:從現 repo 的乾淨 clone 跑 `git filter-repo --path plugins/brcm_fw_upgrade`(+ 必要共用檔)→ push 到新 private repo;加 pyproject(entry_point / api_version / pin testpilot)+ scaffold + CI。
2. **建 fresh public core repo**:全新 `git init`;搬入 sanitized core(`src/testpilot/` 去 audit、core 測試、架構文件、`_template`、core-only pyproject、scaffold);首 commit → **R-21 secret-scan 閘必須過**(public 閘)。**無歷史**。
3. **現 repo rename → wifi_llapi(private)**:於 branch 上 working tree 移除 core(`src/testpilot/` 去 audit)+ brcm;**折入 audit**(§架構2);加 pyproject + scaffold;CI 接 replay backend。**全歷史保留**(core/brcm 仍在歷史中,private 可接受)。
4. **跨 repo 驗收**:乾淨環境 `pip install` 三套件 → core 經 entry_points 發現 wifi/brcm;跑 golden;wifi repo CI 跑接回的 full-run 測試;core CI 無 vendor plugin 綠燈。
5. **收尾**:確認 core 無任何可跑的 wifi/brcm 殘留(不留雙軌);MOC/文件更新;各 repo R-12/R-17 滿足。

## 延後事項(開 issue 追蹤)

| 項目 | gate / 條件 | 標籤 |
|---|---|---|
| rename `wifi_llapi→LLAPI-WIFI-BCM` + audit 抽 vendor 中立 `LLAPI-AUDIT` + audit-profile 契約 | **LLAPI-WIFI-MTK 真的要做**(出現第二 vendor 消費者) | issue α(不掛 P5) |
| HLAPI 共用入口抽取(intent 與 vendor realization 分離) | 兩套 vendor 語料庫可見、沿實際的縫抽取 | issue β(不掛 P5) |
| 部署/發布 infra 實作 | P4 完成後緊接 | 下游部署 stage(自有 spec/plan) |

## Risks / Trade-offs

- **[core 失去 git blame/考古]** ← fresh 無歷史,為 public 安全的必要代價。緩解:完整歷史保留在 private wifi_llapi repo,需考古可回查。
- **[audit→core 耦合未隨 B2 一併解]** runner_facade 的 `Orchestrator` 若 B2 未涵蓋 audit 路徑,P4 折出受阻。緩解:§前置健檢 設為 P4 開工硬閘;必要時補強 B2。
- **[sanitization 漏網機敏進 public core]** 緩解:R-21 secret-scan 為發布閘;fresh 歷史使單點疏漏不致累積外洩。
- **[跨 repo 同步成本]**(母 spec 已標)plugin 與 SDK 跨 repo 協調。緩解:P2b 版本檢查 + 釘選版 + nightly main 早警。
- **[replay fixture 與真硬體偏移]** 錄製 I/O 可能與真機 drift。緩解:fixture 來源標注、定期以真 testbed 重錄;replay 為 CI 決定性閘,非取代實機驗收。

## 成功判準

母 spec「完全解耦可測」三條,於 P4 完成時同時成立:

1. **boundary allow-list 清空**(B1+B2 達成;P4 折出的 audit 亦只依賴 `testpilot.api`)。
2. **物理獨立**:wifi_llapi / brcm 為獨立 repo + pip 套件,經 entry_point 被發現;**core 為獨立 public repo**。
3. **雙 repo full-run CI 接回**:`test_audit_runner_facade` 於 wifi_llapi repo CI 以 replay backend 重啟綠燈。

P4 專屬:core repo 在無 vendor plugin 下 CI 綠燈且通過 R-21 secret-scan(可 public);三 repo 各接 governance scaffold。

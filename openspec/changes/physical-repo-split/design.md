## Context

P4 是 plugin-SDK 解耦工程的收尾 stage,壓在 B1/B2/P2a/P2b/P3 之上。完整設計見 `docs/superpowers/specs/2026-06-18-p4-physical-repo-split-design.md`;MOC:`docs/superpowers/plugin-sdk-decoupling-MOC.md`。現況:monorepo 含 core、`src/testpilot/audit/`、`plugins/{wifi_llapi,brcm_fw_upgrade,_template}`、整體架構文件,且全綁同一 git 歷史。**北極星=讓 core 獨立 public**;唯一硬安全邊界=**凡 public,git log 須無機敏**(`AI-SEC-001`)。

## Goals / Non-Goals

**Goals:**
- core 切成全新 public repo(fresh 無歷史)、裝置中立、可獨立安裝。
- wifi_llapi(含折入 audit)、brcm 各為獨立 private repo + pip dist,經 entry_points 被發現。
- full-run audit 測試於 plugin repo CI 以 replay backend 接回(判準 #3)。
- 每 repo 接 governance scaffold;public core 以 R-21 secret-scan 為發布閘。

**Non-Goals:**
- 不 rename `wifi_llapi→LLAPI-WIFI-BCM`、不抽 vendor 中立 `LLAPI-AUDIT`(issue α,gate MTK)。
- 不做 HLAPI 共用入口抽取(issue β)。
- 不做部署/發布 infra 實作(下游部署 stage;P4 只鎖契約並於 CI 用 git/test-index install 證明發現)。
- 不新建 `LLAPI-WIFI-MTK`(尚未存在)。

## Decisions

- **反向切:core 出去 fresh、舊 repo rename 成 wifi。** 替代:把 wifi 切出去、core 留舊 repo。否決理由:core 要 public,留舊 repo 會讓 public core 繼承機敏歷史——正好踩安全邊界。故 **core 重起無歷史**,機敏歷史封存在 private wifi repo。
- **audit 折入 wifi,不抽獨立 `LLAPI-AUDIT` 套件。** 替代:現在就沿 generic/具名縫抽 vendor 中立 audit 包。否決理由:MTK 尚未存在=無第二 audit consumer,現在抽=用樣本一凍結契約(母 spec 警告的過早固化)。折入時**保持內部 generic/具名 模組邊界乾淨**,使 issue α 未來抽取為機械式,且現在不建跨套件契約、不留雙軌。
- **audit→core 耦合解法。** `validate_case`/`CaseValidationError` 已在 `testpilot.api`(換 import);`case_d_number` 經 api 公開;`Orchestrator`(`runner_facade`)走 **B2 core-owned 執行入口**(B2 §6 已納此 cross-stage 約束)。
- **CI 接回用 replay RunBackend(B1),非實體 runner。** 替代:self-hosted 硬體 runner / 維持 skip。否決理由:硬體 runner infra 重且 flaky;維持 skip 違背判準 #3。replay 把「需實驗室」降級為「需一份錄製 fixture」,決定性、可在雲 CI 跑,並讓 B1 抽象多一正當 consumer。
- **跨 repo SDK 協調 = 釘選已發布版 + nightly main。** 釘選版穩定;nightly 裝 `testpilot` main 早抓破壞;P2b 版本檢查為第二道。
- **每 repo 接 paulsha-conventions policy-check + new-project-template scaffold。** 統一治理;R-21 secret-scan 對「private 帶機敏歷史」與「core 要 public」皆為必要防線。
- **部署只鎖契約、實作獨立下游 stage。** 替代:折進 P4。否決理由:部署有獨立 infra/憑證決策且接另一條 governance 血脈;折入會讓結構切分的批准綁在 infra 上、P4 爆量。

## Risks / Trade-offs

- **[core 失去 git blame/考古]** → 完整歷史保留在 private wifi repo,需考古可回查;為 public 安全的必要代價。
- **[audit→core 耦合未隨 B2 解清]**(runner_facade 的 Orchestrator)→ §前置健檢 設為 P4 開工硬閘;必要時補強 B2。
- **[sanitization 漏網機敏進 public core]** → R-21 secret-scan 為發布閘;fresh 歷史使單點疏漏不致累積外洩。
- **[replay fixture 與真硬體 drift]** → fixture 標注來源、定期以真 testbed 重錄;replay 為 CI 決定性閘,非取代實機驗收。
- **[跨 repo 同步成本]** → P2b 版本檢查 + 釘選版 + nightly main 早警。

## Migration Plan

> 前提:B1+B2+P2a+P2b+P3 已實作 merge;boundary allow-list 空;audit 折出前置健檢(validate_case/case_d_number/Orchestrator)通過。

1. **brcm 抽出**:現 repo 乾淨 clone 跑 `git filter-repo --path plugins/brcm_fw_upgrade`(+ 必要共用檔)→ push 新 private repo;加 pyproject(entry_point/api_version/pin testpilot)+ scaffold + CI。
2. **建 fresh public core repo**:全新 `git init`;搬入 sanitized core(`src/testpilot/` 去 audit、core 測試、架構文件、`_template`、core-only pyproject、scaffold);首 commit → **R-21 secret-scan 閘必過**。無歷史。
3. **現 repo rename → wifi_llapi(private)**:branch 上移除 core(去 audit)+ brcm;**折入 audit**(re-namespace + 解耦 + register_cli);加 pyproject + scaffold;CI 接 replay backend。全歷史保留。
4. **跨 repo 驗收**:乾淨環境 `pip install` 三套件 → core 經 entry_points 發現 wifi/brcm;跑 golden;wifi repo CI 跑接回的 full-run 測試;core CI 無 vendor plugin 綠燈。
5. **收尾**:確認 core 無可跑的 wifi/brcm 殘留(不留雙軌);MOC/文件更新;各 repo R-12/R-17 滿足。

**Rollback**:切分前於現 repo 打 tag;新 repo 未對外前可丟棄重來;core sanitization 失敗則回到 tag 重切。

## Open Questions

- `case_d_number` 公開 vs 於 runner_facade 內聯——二者等價,plan 階段定(不影響架構)。
- audit 在 wifi 套件內的確切模組路徑(`wifi_llapi.audit` 等)——plan 階段定。
- 各 plugin dist 的發布 index 與 operator 安裝 UX——屬下游部署 stage,P4 不決。

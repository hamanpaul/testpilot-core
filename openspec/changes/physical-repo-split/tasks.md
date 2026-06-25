## 1. 前置健檢(P4 開工硬閘)

- [ ] 1.1 確認 B1、B2、P2a、P2b、P3 已實作並 merge 進(現)main
- [ ] 1.2 確認 boundary allow-list 清空(B1+B2 後 wifi production 僅依賴 `testpilot.api`)
- [ ] 1.3 驗 audit→core 三耦合可解:`validate_case`/`CaseValidationError` 已在 `testpilot.api`(✓)、`case_d_number` 待公開、`Orchestrator`(`runner_facade`)有 B2 core-owned 執行入口可用
- [ ] 1.4 確認 B2 §6 跨 stage 約束已落實:core-owned 單-case 執行入口經 `testpilot.api` 可被 audit `runner_facade` 取用

## 2. api 公開面補齊(in monorepo)

- [x] 2.1 `testpilot.api` 公開 `case_d_number`(或確認等價已可用)
- [x] 2.2 確認單-case 執行入口(`orchestrator.run` 或 façade)已於 `testpilot.api` re-export
- [x] 2.3 守門:`testpilot.api.__all__` 含 audit 折出所需符號

## 3. audit 折入 wifi(in monorepo,讓切分退化成純搬檔)

- [x] 3.1 把 `src/testpilot/audit/` re-home 進 wifi plugin 套件(脫 `testpilot.` namespace)
- [x] 3.2 `audit/cli.py` import 改 `testpilot.api`(`validate_case`/`CaseValidationError`)
- [x] 3.3 `audit/runner_facade.py` 改用 `testpilot.api`(`case_d_number` + core-owned 執行入口),移除 `testpilot.core.*` import
- [x] 3.4 audit CLI 改由 wifi plugin `register_cli()` 掛載;core `cli.py` 移除 `audit_group` 具名 import 與 `main.add_command(audit_group)`
- [x] 3.5 保持 audit 內部 generic/wifi-具名 模組邊界乾淨(供 issue α 未來機械式抽取)
- [x] 3.6 守門:靜態掃描 wifi 內 audit 無 `testpilot.core.*`/`testpilot.schema.*` import;core 樹內無 audit 模組

## 4. 獨立 dist packaging(in monorepo)

- [x] 4.1 移除 P2a 過渡期把 `plugins` 塞進 testpilot wheel 的打包與 entry_points
- [x] 4.2 為 wifi/brcm 各備獨立 pyproject(entry_point group `testpilot.plugins`、`api_version="1.0"`、`dependencies=["testpilot>=1.0,<2.0"]`)
- [x] 4.3 core pyproject 收斂為 core-only(去 plugins/audit;testpaths 去 plugin 測試)
- [x] 4.4 驗證資源路徑以 `importlib.resources`/`Path(module.__file__).parent` 解析(cases/reports/templates 隨套件)

## 5. CI:replay backend 接回 full-run 測試

- [x] 5.1 在 B1 `RunBackend` 上新增 replay/fixture provider
- [x] 5.2 錄製 `test_audit_runner_facade` 所需 golden serialwrap I/O fixture(標注來源)
- [x] 5.3 將 `tests/test_audit_runner_facade.py` 由 `@pytest.mark.skip` 改為對 replay backend 執行
- [x] 5.4 驗證該測試在無硬體下決定性通過

## 6. brcm 抽出新 private repo

- [ ] 6.1 現 repo 乾淨 clone 跑 `git filter-repo --path plugins/brcm_fw_upgrade`(+ 必要共用檔)
- [ ] 6.2 push 至新 private repo;加 pyproject + new-project-template scaffold + paulsha-conventions policy-check(pinned SHA)
- [ ] 6.3 brcm repo CI 設定(裝釘選版 testpilot + nightly main)

## 7. core fresh public repo

- [ ] 7.1 全新 `git init`;搬入 sanitized core(`src/testpilot/` 去 audit、core 測試、`plugins/_template`、core-only pyproject、scaffold)
- [ ] 7.2 搬入整體架構文件(MOC/specs/plans/openspec)至 core
- [ ] 7.3 首 commit 過 **R-21 secret-scan 閘**;確認無 monorepo 歷史帶入(fresh)
- [ ] 7.4 core repo CI:無 vendor plugin 下測試綠燈

## 8. 現 repo rename → wifi_llapi(private)

- [ ] 8.1 repo rename;branch 上移除 core(去 audit)+ brcm working tree(全歷史保留)
- [ ] 8.2 落定折入的 audit + wifi pyproject + scaffold + policy-check
- [ ] 8.3 wifi repo CI:replay backend 接回 full-run 測試 + 釘選版/nightly

## 9. 跨 repo 驗收與收尾

- [ ] 9.1 乾淨環境 `pip install testpilot` + wifi + brcm → core 經 entry_points 發現兩 plugin
- [ ] 9.2 跑 golden 報表測試(位元級不變);wifi repo full-run 測試綠燈;core CI 中立綠燈
- [ ] 9.3 確認三判準:allow-list 清空、物理獨立(含 core public repo)、full-run CI 接回
- [ ] 9.4 確認無雙軌(core 無可跑的 wifi/brcm 殘留);MOC/文件更新
- [ ] 9.5 各 repo R-12(branch)/R-17(PR keyword)滿足
- [ ] 9.6 開 issue α(rename + vendor 中立 `LLAPI-AUDIT`,gate MTK)、issue β(HLAPI 共用入口);建下游部署 stage 待辦

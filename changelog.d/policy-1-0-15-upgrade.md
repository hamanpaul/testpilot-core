---
type: change
scope: policy
---
升級 hamanpaul project policy 至 v1.0.15，並完成 R-21 減敏。

## 版本升級

- `policy_version` 1.0.12 → 1.0.15（`.project-policy.yml` 與四份 agent convention 檔）。
- `workflow_ref` / `policy_engine_ref` 雙 pin 換為 v1.0.15 的
  `a764806046c410eb4f254ac0b6a8aec8b7559dab`（`policy-check.yml` 與 `release.yml` 兩支）。
- 新增 `.project-policy.yml` 的 `preflight.steps`（v1.0.13 的 canonical `preflight-ci`
  skill 需要）。
- `tests/test_release_governance.py` 中寫死的 policy_version 斷言同步更新。

## R-21 減敏（本 repo 為 public，v1.0.13 起依 visibility + tier 判定命中等級）

升級後 R-21 由「不適用」變為實際生效並命中 `structural:23 / marker:110`
（marker baseline 為少數雇主／內部代號 token；常見 vendor 名稱屬 `public_names` 不列入）。
分三類處理：

**刪除拆分殘留**
- `docs/COMPREHENSIVE_AUDIT_GUIDE.md`、`docs/AUDIT_GUIDE_INDEX.md`、
  `docs/audit-guide.md.legacy.bak`：pre-audit-mode 舊流程文件，audit doctrine 已由
  `wifi_llapi` 承接。
- `docs/audit-todo.md`、`docs/wifi-baseline-exp.md`：core/plugin 拆分前的舊快照，
  現行版本由 `wifi_llapi` 維護。
- `full_diff.patch`：293KB，於 `60d10c0` 誤 commit 的殘留產物。
- 四份 agent 檔的 `Calibration Continuation Policy` 與 `Default Lab Baseline Policy`
  兩節：屬 plugin 的操作規範（逐案校正流程、實驗室 baseline 與 image-specific
  workaround），拆分後由 plugin repo 維護；已替換為指向說明。

**live code 減敏**
- `src/testpilot/cli_support.py`：`run` 子指令的 help 範例中 `--dut-fw-ver` 的裝置型號
  改為通用佔位值（README 的 cli-help 區塊為頂層 `--help`，不含此行，R-16 不受影響）。
- `tests/test_serialwrap_binary.py` / `tests/test_verify_install_wheel_mode.py`：
  fixture 中的 `/home/<user>/...` 個人路徑改為 `/opt/...`（structural 偵測針對
  `/home/*/`，換成其他使用者名仍會命中，故改用非 `/home` 路徑）。

**歷史紀錄以 allow-list 標示**
- `secret_scan.allow` 納入 `docs/superpowers/**`、`openspec/changes/archive/**`、
  `CHANGELOG.md`。這些是當時決策的歷史紀錄，改寫等同竄改；allow-list 為 policy
  對「合法引用」設計的機制。live code 與現行 docs 皆已實際減敏，不在此清單內。

減敏後 `policy_check`（1.0.15 engine + PR context + `--repo-visibility public`）
為 pass 24 / fail 0，**未使用任何 `policy-exempt:*` 豁免 label**。

## 未納入的 gate 與已知既有問題（揭露，非本 PR 造成）

- `preflight.steps` 只宣告 `tests`，**暫不宣告 openspec gate**：本 repo 現有 4 個 spec
  （`audit-mode`、`plugin-entry-points-discovery`、`plugin-runner-reporter-separation`、
  `wifi-llapi-alignment-guardrails`）缺 `#### Scenario:` 區塊而驗證失敗，於未修改的
  `main` 上結果相同（17 passed / 4 failed）。補齊後再加回。
- `tests/test_installer.py::TestOfflineInstall::test_offline_creates_wrapper` 在本機失敗，
  同樣早於本 PR（未修改 main 上一致失敗、`main` CI 為綠）。根因為安裝腳本比對 bundle
  的 `cp311` 標籤與執行中 python 版本標籤，本機為 Python 3.12 且無 `python3.11`。
- `.gitignore` 的 `.venv/` 改為 `.venv`：帶斜線的 pattern 只匹配目錄，把 `.venv` 做成
  共用 venv 的 symlink 時不會被忽略，會污染 `git status` 並使 policy gate 打包時拋
  `AbsoluteLinkError`。

## changelog fragment 修正（含一項既有缺陷）

`docs/release-flow.md` 明定 `chore` **不是**合法 fragment type（合法值：`change` /
`deprecate` / `feat` / `fix` / `perf` / `refactor` / `remove` / `security`），
`policy_check.changelog collate` 會直接拋 `FragmentError` 拒絕執行、擋住整個 release：

- 本 fragment 原用 `type: chore`，已改為 `change`（本 PR 引入，已修正）。
- `changelog.d/serialwrap-pin-0-2-4.md` **完全沒有 YAML frontmatter**（直接以
  `### Changed` 開頭），為**早於本 PR 的既有缺陷**——代表 collate 在本 PR 之前就已經
  失敗、release 路徑已被擋住。已補上 `type: change` / `scope: install` frontmatter，
  內容維持原樣。修正後實測 `collate` 通過。

另本 fragment 原文為說明減敏而直接寫出 marker token 與被替換掉的裝置型號字串，而
`changelog.d/**` 不在 `secret_scan.allow` 內；fragment 於 release 時會被 collate 進
`CHANGELOG.md`，等同在 release notes 重新命中。已改為不揭露具體 token 的描述。

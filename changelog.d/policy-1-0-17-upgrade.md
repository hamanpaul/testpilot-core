---
type: change
scope: policy
---
同步 hamanpaul project policy 1.0.15 → 1.0.17。

- `policy_version` 1.0.15 → 1.0.17（`.project-policy.yml` 與四份 agent convention 檔）。
- `workflow_ref` / `policy_engine_ref` 雙 pin 換為 v1.0.17 的
  `9e7fabbf0b5eea9ad933fa6798764b723934a0b7`（`policy-check.yml` 與 `release.yml` 兩支，
  `uses:` 尾註 `# v1.0.17`）。
- `tests/test_release_governance.py` 中寫死的 policy_version / managed-by 斷言同步更新。

1.0.16／1.0.17 對下游 repo 未新增或變更任何規則，僅上游引擎自身的 distribution
identity、runtime bundle 與 release workflow 修正，故本次為純版本同步。1.0.16 引入
的引擎版本 gate（執行中引擎版本與 repo 宣告的 `policy_version` 不符即 fail-loud）
是本次同步的實益：pin SHA 與 `policy_version` 已同 PR 原子更新，本機
`policy_check` 預檢可與 CI 判定一致。

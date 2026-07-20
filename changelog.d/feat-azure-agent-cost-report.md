---
type: feat
scope: core
---
新增 Azure-only core agent runtime 與成本報表契約：CLI 依環境自動判定 disabled/misconfigured/ready/degraded，misconfigured 會輸出去敏 notice；core run-loop 於每案 advisory planning、opt-in tier-2 recovery 與 run-end analysis 後寫出 `artifact_dir/agent_usage` JSON/Markdown artifacts，並以 additive pointer 回傳 `core_cost_report`/`core_agent_analysis`。

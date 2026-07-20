---
type: feat
scope: core
---
新增 domain-agnostic tier-2 environment recovery：deterministic tier-1 連續失敗達門檻後，core 才於 retry gap 使用 tool-denied one-shot planner 選擇 plugin-advertised、schema/budget 驗證過的 environment action；plugin 執行後仍強制 deterministic `verify_env`，並輸出 bounded/redacted case/run audit 與 `agent_recovered` marker。provider、SDK 與 plugin callback 例外只保存 phase 及 exception type，不保存 raw exception text。（#4）

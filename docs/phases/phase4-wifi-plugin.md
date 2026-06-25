# Phase 4：Wifi_LLAPI Plugin

## Scope

將 `wifi_llapi` plugin 從 stub 推進到可真實控制 DUT/STA 並完成判讀。

## Current Status

1. case YAML 與 source row 對齊治理已在進行。
2. Excel 對外交付報告流程已完成。
3. plugin hook 尚為 stub。

## Gaps

1. `setup_env/verify_env/execute_step/evaluate` 尚未接真實 transport。
2. 尚未加入 agent 補判與身份一致性檢查。

## Acceptance Criteria

1. 具備真實環境 setup/verify。
2. 可執行 YAML step 並產出可重現證據。
3. 可做 plugin 主判 + agent 補判合併。

## Related Todo IDs

- `P4-01` ~ `P4-05`

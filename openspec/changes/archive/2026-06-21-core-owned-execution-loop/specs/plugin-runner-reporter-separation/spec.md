## MODIFIED Requirements

### Requirement: PluginBase create_runner 為執行迴圈 override
`PluginBase` SHALL 提供 optional `create_runner()`,default 回傳 `None`。orchestrator 執行 plugin 時:若 `create_runner()` 回傳非 None 物件(且具 `run`),SHALL 委派給該 runner——此為**本質不同工作的 override**(如 brcm firmware 燒錄);否則 SHALL 走 core 預設 run loop(`core/run_loop.py`),由 plugin hooks 驅動。未提供 create_runner 且無可執行 hook 的 plugin 退回 skeleton。

#### Scenario: override plugin 走自有 runner
- **WHEN** 一個實作 `create_runner()`(非 None)的 plugin 被執行
- **THEN** orchestrator 委派 `runner.run(...)`,完全由該 runner 主導整-run 與報表

#### Scenario: 未提供 create_runner 的 plugin 走 core 預設迴圈
- **WHEN** 一個未覆寫 `create_runner()`(回傳 None)但提供執行 hooks 的 plugin(如 wifi_llapi)被執行
- **THEN** orchestrator 走 core `run_loop`(**非 skeleton**),經 plugin hooks 完成整-run 與報表

#### Scenario: wifi_llapi 改走 core 預設路徑
- **WHEN** B2 後執行 `testpilot wifi_llapi`
- **THEN** wifi 不再提供 create_runner,走 core 預設 run loop;對外 UX 與報表輸出不變

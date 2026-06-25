# 設計：core ⊥ wifi_llapi 解耦

## 現況（T7 收尾）

- 報表（`create_reporter`）、驗證（`validate_case`）、執行約束（`execution_policy`）三個 hook **皆已落地**，wifi_llapi 已完全透過它們接入。
- `grep -r wifi_llapi src/testpilot/core src/testpilot/schema src/testpilot/reporting` **為空**，由 `tests/test_core_has_no_plugin_names.py` 守門（範圍只涵蓋 wifi_llapi over core/schema/reporting；`cli.py` 與 `brcm` 不在守門範圍）。
- **CLI 解耦（`register_cli`）仍待辦**：`cli.py` 為組裝根，目前仍直接具名 wifi_llapi，另案追蹤於 issue [#70](https://github.com/hamanpaul/testpilot/issues/70)。hook 已存在於 `PluginBase`，但 cli.py 尚未改走它。

## 目標與不變量

**目標**：core 對任何 plugin 零具名知識——`grep -r wifi_llapi src/testpilot/core src/testpilot/schema src/testpilot/reporting` 最終為空。wifi_llapi 完全透過 `PluginBase` 契約接入。

**不變量（不可破）**：
- verdict kernel ⊥ control-plane：SDK/plugin 永不裁決 pass/fail（既有原則）
- `testpilot wifi_llapi` 對外 UX 與報表輸出位元級不變（測試保證）
- 既有 plugin（brcm_fw_upgrade）與 `_template` 不受影響

## 現況耦合（查證）

| core 位置 | wifi_llapi 邏輯 |
|---|---|
| `reporting/wifi_llapi_*.py` ×7 | align / artifacts / excel / inventory / reproject / summary / compare_0401 |
| `core/orchestrator.py` 506–861 | `_build/_prepare/_finalize_wifi_llapi_alignment`、`build_wifi_llapi_summary` 呼叫 |
| `core/orchestrator.py` 264–273 | `_is_wifi_llapi_official_case`、`_load_wifi_llapi_agent_config`、`_wifi_llapi_execution_policy` |
| `schema/case_schema.py` | `validate_wifi_llapi_case` |
| `core/case_utils.py` | `is_wifi_llapi_official_case`、D### selector |
| `core/runner_selector.py` | wifi_llapi 強制 sequential / concurrency=1 |
| `yaml_command_audit.py` | 整檔 audit wifi_llapi YAML chained command |
| `reporting/reporter.py` | 讀 precomputed wifi_llapi summary |
| `cli.py` | import `wifi_llapi_excel`/`reproject` + `testpilot wifi_llapi` 命令 |

僅 wifi_llapi 滲入 core（brcm/qos/sigma 皆乾淨）。

## Hook 介面（重用 1 + 新增 3，皆 plugin-agnostic）

```python
class PluginBase(ABC):
    # 既有，重用 ──────────────────────────────────────────
    def create_reporter(self) -> IReporter | None: ...   # 既有，default None
    def report_formats(self) -> list[str]: ...           # 既有

    # 新增（皆 optional，default 不改變現狀）───────────────
    def validate_case(self, case: dict) -> None:
        """case 載入後的 plugin 專屬驗證；違規時 raise。default no-op。"""
        return None

    def execution_policy(self, case: dict) -> dict:
        """plugin 宣告自身執行約束（concurrency/mode/runner 選擇等）。
        default 回傳中性策略（不施加約束）。"""
        return {}

    def register_cli(self, subparsers) -> None:
        """plugin 註冊自己的 CLI 子命令。default 不註冊。"""
        return None
```

**hook ↔ 洩漏對應**：

| Hook | 吸收 |
|---|---|
| `create_reporter()`（重用） | 7 報表模組 + orchestrator alignment/summary/artifacts 流 + reporter.py 引用 |
| `validate_case()` | `validate_wifi_llapi_case` + `yaml_command_audit` + case_utils official/D### |
| `execution_policy()` | runner_selector wifi_llapi 約束 + orchestrator execution-policy delegates |
| `register_cli()` | cli.py wifi_llapi 命令；保留 `testpilot wifi_llapi` |

> YAGNI：只加現有 code 需要的 3 個 hook，命名 plugin-agnostic。將來 qos/sigma 落地若不夠用再演進——屆時才有真實第二消費者驗證形狀。

## 搬遷與 core 去具名化

```
reporting/wifi_llapi_*.py ×7          → plugins/wifi_llapi/reporting/
  compare_0401.py                     → 刪除（或 plugins/wifi_llapi/scripts/）
yaml_command_audit.py                 → plugins/wifi_llapi/
schema.validate_wifi_llapi_case       → plugins/wifi_llapi/（plugin.validate_case 呼叫）
orchestrator._*_wifi_llapi_alignment* → WifiLlapiReporter（plugin，create_reporter 回傳）
case_utils wifi_llapi helpers          → plugins/wifi_llapi/
runner_selector wifi_llapi 約束        → plugin.execution_policy()
```

core 端：
- `orchestrator`：刪 wifi_llapi import/方法；`reporter = plugin.create_reporter() or DefaultReporter(); reporter.generate(run_results)`；`plugin.validate_case(case)`；`plugin.execution_policy(case)`
- `reporter.py`：改讀 meta 的 generic `plugin_summary` key（不認 wifi_llapi）
- `cli.py`：plugin 載入後呼叫 `plugin.register_cli(subparsers)`
- `schema/case_schema.py`：保留 generic `load_case`，移除 wifi_llapi 驗證

## 風險與緩解

| 風險 | 緩解 |
|---|---|
| orchestrator(948 行) 報表流深嵌 | 小步搬、每步跑全測試；先補 golden snapshot 鎖報表輸出 |
| 既有 `IReporter` 協定不足以表達 alignment 流 | 在 **plugin 端**擴充 reporter 實作，不回頭污染 core 契約 |
| `testpilot wifi_llapi` UX 破壞 | `register_cli` 保留同名命令；端到端測試（`test_wifi_llapi_plugin_runtime`）守 UX |
| 搬移時行為漂移 | 「core 無 wifi_llapi」grep 斷言 + second-plugin smoke 證明真解耦而非改名 |

## 替代方案（已否決）

- **完整 provider protocol 體系**（ReporterProvider/CaseValidator/ExecutionPolicyProvider/CLICommandProvider）：為 qos/sigma 投機式一般化，目前唯一消費者是 wifi_llapi → 違反 YAGNI。採最小 hook，待第二 plugin 再演進。

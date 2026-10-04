# Plugin 開發指南

## 1. 建立新 Plugin

目錄範例：

```text
plugins/
  your_plugin/
    __init__.py
    plugin.py
    agent-config.yaml   # 選配，若需 CLI agent/model 優先序
    cases/
      _template.yaml
      your_test.yaml
```

`plugin.py` 需定義 `Plugin` 並繼承 `PluginBase`。

```python
from pathlib import Path
from testpilot.api import PluginBase, load_cases_dir

class Plugin(PluginBase):
    api_version = "1.0"

    @property
    def name(self) -> str:
        return "your_plugin"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def cases_dir(self) -> Path:
        return Path(__file__).parent / "cases"

    def discover_cases(self):
        return load_cases_dir(self.cases_dir)

    def setup_env(self, case, topology) -> bool:
        ...

    def verify_env(self, case, topology) -> bool:
        ...

    def execute_step(self, case, step, topology) -> dict:
        ...

    def evaluate(self, case, results) -> bool:
        ...

    def teardown(self, case, topology) -> None:
        ...
```

Plugin 對 TestPilot SDK 的穩定 import surface 是 `testpilot.api`。目前穩定
re-export 包含 `API_VERSION`, `PluginBase`, `IncompatiblePluginError`,
case schema helpers（`load_case`, `load_cases_dir`, `CaseValidationError`,
`validate_case`）、schema validation helpers（`require_non_empty_string`,
`validate_string_list`, `require_mapping`, `require_string_mapping`,
`require_bool`——供 plugin 自建 case 驗證器,不必勾 core 私有）、`TestbedConfig`、
transport contracts（`TransportBase`,
`StubTransport`, `create_transport`）、reporting contracts、run-backend
contract（`RunBackend`, `RunHandle`, `ExportRequest`, `ExportResult`）、
run preparation contract（`PreparedRun`, including API 1.4 `no_io`),
case utility helpers、tier-2 contracts（`Tier2Capability`,
`Tier2RecoveryContext`, `Tier2RecoveryAudit`, `Tier2PlanValidationError`）、
API 1.6 run-start contracts（`RunCapability`,
`PrepareRunAfterCaptureContext`, `PrepareRunGateOutcome`,
`PrepareRunGateEvidence`, `PrepareRunGateResult`）、`CliRegistrar`、run helpers（含 ctx-free 的
`run_one_case`，可選 `run_backend` 注入）, and `excel_adapter`。
直接從 `testpilot.core.*` 或 `testpilot.schema.*` 匯入視為 private
implementation detail；若有新 core/schema symbol 要成為穩定契約，必須先加入
`testpilot.api.__all__` 並更新本節。

只複製 `plugins/_template` 或建立 `plugins/your_plugin/` 目錄還不夠；在
註冊 `testpilot.plugins` entry point、並重新安裝 editable package 之前，
新 plugin 不會出現在 `testpilot list-plugins`。

建議流程：

1. 複製模板：`cp -r plugins/_template plugins/my_plugin`
2. 在負責發佈該 plugin 的套件 `pyproject.toml` 註冊 entry point：

   ```toml
   [project.entry-points."testpilot.plugins"]
   my_plugin = "my_plugin.plugin:Plugin"
   ```

3. 編輯 `plugins/my_plugin/plugin.py`，並新增 `plugins/my_plugin/cases/`
   內的 YAML cases
4. 回到該套件根目錄重新安裝，讓 Python 刷新 entry-point metadata：
   `uv pip install -e .`
5. 驗證：`testpilot list-plugins`，接著 `testpilot list-cases my_plugin`

> **開發期免安裝跑法（path mode，#30）**：步驟 2 的 entry point 一寫好，就可以用
> `testpilot /path/to/my_plugin`（專案根目錄，即含 `pyproject.toml` 那層）直接執行，
> 不必先做步驟 4 的安裝。path mode 讀的是專案自己的 entry-point 宣告，跑的是專案內
> 那份 source——即使環境裡另有同名的已安裝套件也一樣。`list-plugins` / `list-cases`
> 仍只列出**已安裝**的 plugin，因此步驟 4/5 的驗證流程不變。



### 選配 hook（plugin 透過 PluginBase 接入 core）

除上述必要方法外，plugin 可覆寫以下選配 hook，把 plugin 專屬行為透過
`PluginBase` 契約接入 core。所有 hook 預設皆為 no-op / 中性值，因此
`src/testpilot/{core,schema,reporting}` 對 plugin 維持零具名
（由 `tests/test_core_has_no_plugin_names.py` 守門）。

| Hook | 用途 | 預設 |
|------|------|------|
| `validate_case(case)` | case 載入後的 plugin 專屬驗證；違規時 raise | no-op |
| `execution_policy(case)` | 宣告執行約束（concurrency / mode / runner 選擇等） | `{}`（無約束） |
| `create_reporter()` | 回傳 plugin 專屬 reporter（`IReporter`） | `None`（用 orchestrator 預設） |
| `register_cli(registrar)` | 透過 `CliRegistrar` 註冊 installed plugin 自己的 Click 命令/群組 | no-op |
| `bind_project_root(project_root)` | 接收本次執行選定的 operator project root，供 run-start preflight 或其 artifact 使用 | no-op |
| `required_run_capabilities` | 由 host 在 Plugin preparation 前驗證必要的 run-level host 能力 | `frozenset()` |
| `prepare_run_after_capture(prepared, context)` | 嚴格 capture 與 run-start marker 驗證後、firmware-version probe 前的 opt-in gate | `None` |
| `verify_install()` | 回傳 plugin-owned install health 診斷；checkout/wheel `testpilot --verify-install` 與更新後回滾閘都會執行（更新後由新 managed venv 的 isolated process 驗證）。Wheel 的 entry-point 模組與 `Plugin` class 實作模組都需由所屬 distribution 的 RECORD 證明；editable install 需由 PEP 610 local source URL 證明；無法驗證時會阻擋驗證。`False`、例外、格式錯誤診斷也會阻擋驗證，`WARN` 維持提醒 | `[]` |
| `build_remediation_decision(case, failure_snapshot, topology, ...)` | tier-1 deterministic failure→safe-env action mapping | `None` |
| `execute_remediation(case, decision, topology)` | 執行 tier-1 allowlist action；只可修 environment | fail-closed unsupported result |
| `build_tier2_remediation_context(case, failure_snapshot, topology, ...)` | 提供已去敏、有限長度的 failure/log context、env capability catalog 與 deterministic `verify_env` 定義；core 負責 prompt/LLM/schema | `None`（tier-2 disabled） |
| `execute_tier2_remediation(case, plan, topology)` | 只在 retry 間隙執行 core 驗證過的 environment repair plan；不得修改 test semantics/verdict | fail-closed unsupported result |

目前狀態：報表（`create_reporter`）、驗證（`validate_case`）、執行約束
（`execution_policy`）與 CLI 註冊（`register_cli`）hook 已落地；
plugin 可透過 `testpilot.api.CliRegistrar` 掛載自己的 CLI surface。
SDK API `1.2` 新增的 tier-2 hooks 為選配；既有宣告 `api_version = "1.1"`
的 plugin 仍相容，但只有覆寫兩個 hooks 的 plugin 才能啟用 tier-2。
SDK API `1.3` 新增 optional `bind_project_root(project_root)` run-context hook，
預設為 no-op 且不改變既有 plugin method signatures；需要此 root-binding 行為的
plugin 應宣告 `api_version = "1.3"`，避免舊 core 靜默忽略它。
SDK API `1.4` 新增 `PreparedRun.no_io`（預設 `False`）。Plugin 只有在整個 prepared
selection 都不需要 Core 的 DUT/STA capture、sequence marker、log export 與 firmware
version query 時才設為 `True`，例如透過 `PreparedRun(cases=cases, no_io=True)` 標示全為
unsupported/N/A 的 selection；此宣告不會跳過 case planning、execution 或 reporting。
空 selection 會由 Core 自動略過上述環境 I/O。
需要宣告 `no_io=True` 的 plugin 應使用 `api_version = "1.4"`；一般既有 plugin
維持預設值即可。
SDK API `1.5` 讓 `teardown()` 回傳 cleanup 結果：`None` 保持既有成功語意；若 cleanup
失敗或無法確認，回傳下列有限欄位的 mapping。需要 Core 消費這個 mapping 的 plugin
必須宣告 `api_version = "1.5"`，API 1.4 Core 會在載入時拒絕它。

```python
{
    "status": "failed",  # 或 "unknown"
    "reason_code": "restore_verification_failed",
    "comment": "the saved mode did not read back",
    "transport_result": {"error_code": "SESSION_NOT_READY"},  # 選填
}
```

`status="failed"` 表示 cleanup 已知失敗；`status="unknown"` 表示結果無法確認。
Core 會以目前 case/attempt 建立 environment failure snapshot、將 verdict 設為失敗，
並終止本次 run，不會再 retry 該 case。若 receipt 表示操作結果 uncertain，Core 會將
狀態提升為 `unknown`。額外欄位、格式錯誤的 mapping 或一般 teardown exception 都會
fail closed。`KeyboardInterrupt` 等 cancellation 仍會向上傳遞。Plugin 的 cleanup
流程應在 mutation 結果不確定時停止後續 I/O；Core 在先前命令 receipt 已 uncertain
時會略過 teardown。仍成功回傳 `None` 的舊 plugin 不需升級 API 宣告。

### SDK API 1.6: Run-start gate

SDK API 1.6 adds a host-enforced run-start gate for plugins that must verify the
active capture binding before firmware-version probes or case execution. Existing
plugins leave `required_run_capabilities` empty and keep the legacy lifecycle. A
plugin opting in must declare API 1.6 or newer and use the typed capability:

```python
from testpilot.api import (
    PluginBase,
    PrepareRunAfterCaptureContext,
    PrepareRunGateEvidence,
    PrepareRunGateOutcome,
    PrepareRunGateResult,
    PreparedRun,
    RunCapability,
)


class Plugin(PluginBase):
    api_version = "1.6"
    required_run_capabilities = frozenset({RunCapability.STRICT_CAPTURE_BINDING})

    def prepare_run_after_capture(
        self,
        prepared: PreparedRun,
        context: PrepareRunAfterCaptureContext,
    ) -> PrepareRunGateResult:
        if self._verify_selected_targets(prepared, context):
            return PrepareRunGateResult(
                outcome=PrepareRunGateOutcome.ACCEPTED,
                reason_code="identity_verified",
                evidence=(
                    PrepareRunGateEvidence(
                        check="selected_targets",
                        outcome=PrepareRunGateOutcome.ACCEPTED,
                        reason_code="same_boot_verified",
                    ),
                ),
            )
        return PrepareRunGateResult(
            outcome=PrepareRunGateOutcome.FAILED,
            reason_code="identity_mismatch",
        )
```

Core checks the declared capability and an overridden hook before calling
`bind_project_root()` or `prepare_run()`. The required order is pure preparation,
strict capture setup, a trustworthy non-negative run-start sequence marker, this
gate, firmware-version capture, then case runners. Sequence zero is valid; `None`,
booleans, negative values, and malformed markers are not. The context is created
from the active capture handle, and its opaque `capture_binding_id` must never be
copied from operator configuration.

The gate result uses finite `accepted`, `failed`, or `unknown` outcomes and
sanitized reason/evidence tokens. Missing, malformed, raised, failed, or unknown
results create a terminal run-start abort artifact with the prepared/requested
cases listed as unexecuted. Core does not create synthetic case rows or continue
to version probes, case execution, capture export, or teardown after an uncertain
gate. Invalid strict end markers or case ranges mark run capture incomplete and
skip export; they never broaden the sequence range.

If a host cannot prove the required strict capture capability, Core rejects the
opt-in before Plugin preparation. The current production backend does not yet
provide this strict context; plugins requesting it therefore fail closed before
preparation until backend support is added. API 1.5 hosts also reject API 1.6
plugins during loading, while API 1.6 hosts continue accepting API 1.4 and 1.5
plugins through the unchanged legacy path.

每個 tier-2 capability 必須宣告 `executor_key`、`description`、
`execution_boundary` 與 `params_schema`。core 會驗證 executor allowlist、參數名稱/
型別/enum/長度與 action budget；`schema_validated` 只表示結構通過，不表示 core
理解任意 command 的 domain 語意。plugin executor 仍必須把 side effect 限制在已宣告的
environment transport/target，且不可讓該 transport 存取 case YAML、pass criteria 或
verdict artifact；core coordinator 另會在 hook 前後檢查 in-memory test semantics 未被改寫。

`register_cli()` 是 install-time registration：`testpilot.cli` import 時會掃描
installed checkout 的 `plugins/` 並掛上 plugin commands。`--root <path>` 只改變
執行時的 project root（cases/configs/testbed/report paths），不會重新掃描 `<path>/plugins`
或動態改變已註冊的 CLI surface。未提供 `--root` 時，以目前 working directory
作為 project root，與 context-free API 的預設一致。core 會在 run dispatch 前呼叫
`bind_project_root()`，並在 `prepare_run()` 前再次綁定，讓 run-start hook 使用同一 root。
若要新增/移除 plugin CLI command，請在安裝來源
checkout 內更新 plugin 後重新安裝/更新 TestPilot。

### Azure BYOK runtime 備註

- core 不再提供 `--azure` 或互動式 credential prompt；只讀取環境變數
  `COPILOT_PROVIDER_BASE_URL`、`COPILOT_PROVIDER_API_KEY`、
  `COPILOT_MODEL`、`COPILOT_PROVIDER_AZURE_API_VERSION`。
- `COPILOT_PROVIDER_TYPE` 不作為 enable switch；若有設定且值不是 `azure`，
  CLI 會輸出去敏 misconfigured notice，然後繼續 deterministic/no-agent mode。
- plugin 的 `agent-config.yaml` 只描述 runner / remediation policy，不保存
  endpoint、API key 或其他 secrets。

### SDK 契約版本

`testpilot.api.API_VERSION` 是 TestPilot 對 plugin 承諾的 SDK 契約版本，
格式固定為 `major.minor`，且刻意獨立於 `VERSION` / package release 版本。
新增相容 hook 或 symbol 時提升 minor；移除或改變既有契約時提升 major。

每個 plugin class 必須顯式宣告 `api_version`，例如 `api_version = "1.0"`。
`PluginBase.api_version` 預設為 `None`，因此未宣告者會在 `PluginLoader.load()`
被視為不相容。載入時的相容規則為：

```text
plugin.major == testpilot.api.API_VERSION.major
and testpilot.api.API_VERSION.minor >= plugin.minor
```

不符合規則、格式不是 `major.minor`、或未宣告時，loader 會 raise
`IncompatiblePluginError`，並由 `testpilot.api` 匯出供 host/CLI 捕捉。

## 2. Test Case YAML 最低欄位

必要欄位：`id`, `name`, `topology`, `steps`, `pass_criteria`

```yaml
id: "unique-case-id"
name: "Human-readable name"
topology:
  devices:
    DUT:
      role: ap
      transport: serial
steps:
  - id: step1
    action: exec
    target: DUT
    command: "..."
pass_criteria:
  - field: result
    operator: contains
    value: expected
```

變數可用 `{{VAR}}`，由 `testbed.variables` 替換。

### wifi_llapi 擴充欄位

除必要欄位外，`wifi_llapi` plugin 的 case YAML 使用以下擴充欄位：

| 欄位 | 用途 | 範例 |
|------|------|------|
| `source.report` | 來源 Excel 檔案名稱 | `0302-AT&T_LLAPI_Test_Report_20260107.xlsx` |
| `source.sheet` | 來源工作表名稱 | `Wifi_LLAPI` |
| `source.row` | 對應 Excel 行號（alignment gate 依據） | `6` |
| `source.object` | TR-181 物件路徑 | `WiFi.AccessPoint.{i}.` |
| `source.api` | API 名稱 | `kickStation()` |
| `version` | case 版本 | `1.0` |
| `platform.prplos` | prplOS 版本 | `4.0.3` |
| `platform.bdk` | BDK 版本 | `6.3.1` |
| `hlapi_command` | HLAPI 指令描述 | `ubus-cli "WiFi.AccessPoint.{i}.kickStation(...)"` |
| `llapi_support` | 支援度標記 | `Support` |
| `implemented_by` | 實作方識別 | `pWHM` |
| `bands` | 適用頻段（用於 band-level 結果拆分） | `["5g", "6g"]` |
| `env_verify` | 環境驗證步驟 | `[{action: ping, from: STA, to: DUT}]` |
| `sta_env_setup` | 實際執行的 DUT/STA 環境佈建命令；用 `DUT ...:` / `STA ...:` 小節切換 target。不可留下 `wlX` / `192.168.1.X` 這類 placeholder，runtime 會視為模板並跳過。 | multiline string |
| `test_environment` | 測試環境描述（人類可讀） | multiline string |
| `setup_steps` | 環境佈建摘要（人類可讀）；不要把 runtime baseline 硬編碼在 plugin.py | multiline string |
| `topology.links` | 裝置間連線描述 | `[{from: STA, to: DUT, band: 5g}]` |

其他 plugin 可自行定義擴充欄位，不需遵循此表。

`wifi_llapi` 的 runtime 不應再注入 band-specific DUT/STA baseline。若 case 需要 AP/STA bring-up，
請把可執行命令寫在 YAML 的 `sta_env_setup`，並用明確的 `DUT` / `STA` 區塊描述 target。

## 3. 判讀責任契約（重要）

1. `plugin.evaluate()`：主判預期內條件（pass_criteria）。
2. `agent audit`：補判預期外異常（身份錯配、資料來源不一致、上下文異常）。
3. 合併輸出：`Pass` / `Fail` / `Inconclusive`。

建議每步至少保留以下證據欄位：

1. `band`
2. `target identity`（DUT/STA 實體識別）
3. `raw output`
4. `step trace`（命令、時間、回傳碼）

## 4. Agent Config（plugin 級）

若 plugin 需要指定 CLI agent/model 優先序，使用：

- `plugins/<plugin>/agent-config.yaml`

格式：

> **注意：** `wifi_llapi` 已實作 `execution` block runtime（per-case/sequential/retry-aware timeout/per-case trace）。

```yaml
version: 1
default_mode: headless
selection_policy:
  fallback: automatic
  on_unavailable: next_priority
execution:
  scope: per_case
  mode: sequential
  max_concurrency: 1
  failure_policy: retry_then_fail_and_continue
  retry:
    max_attempts: 2
    backoff_seconds: 5
  timeout:
    base_seconds: 120
    per_step_seconds: 45
    retry_multiplier: 1.25
    max_seconds: 900
remediation:
  enabled: true
  allowed_actions: [plugin_tier1_action]  # tier-1 deterministic only
  tier2:
    enabled: false                       # plugin must opt in explicitly
    escalate_after_tier1_failures: 2
    max_invocations_per_case: 1
    max_actions: 3
    timeout_seconds: 60
    max_total_attempts: 4
runners:
  - priority: 1
    cli_agent: copilot
    model: gpt-5.4
    effort: high
    enabled: true
  - priority: 2
    cli_agent: copilot
    model: sonnet-4.6
    effort: high
    enabled: true
  - priority: 3
    cli_agent: copilot
    model: gpt-5-mini
    effort: high
    enabled: true
```

規則：

1. 依 `priority` 選擇。
2. 第一優先不可用時可自動降級。
3. `scope=per_case` 時，每個 case 都需獨立做 runner 選擇與呼叫。
4. `mode=sequential` 時，`max_concurrency` 應為 `1`。
5. `failure_policy=retry_then_fail_and_continue` 時，單 case 失敗不得中止整批 run。
6. 必須記錄 per-case selection trace（含降級原因）。
7. timeout 應隨 retry attempt 調整（建議採倍增或倍率增長並設上限）。
8. `allowed_actions` 只約束 tier-1 deterministic action；tier-2 另由 plugin hook
   宣告 capability catalog，不能沿用它來繞過 schema 或 execution boundary。
9. tier-2 預設 disabled；啟用時 `max_total_attempts` 必須至少為
   `escalate_after_tier1_failures + 2`，且所有 side effect 後仍由 core 強制
   deterministic `verify_env`。

## 5. Transport 類型慣例

| 類型 | 用途 | config key |
|---|---|---|
| serial | UART/serialwrap 控 DUT | `transport: serial` |
| adb | 控制 Android STA | `transport: adb` |
| ssh | 控制 EndpointPC/遠端設備 | `transport: ssh` |
| network | ping/arping/iperf 網路層驗證 | `transport: network` |

參考：可運行範例 `examples/sample_echo/`（`pip install -e ./examples/sample_echo` 後 `testpilot run sample_echo --case echo-hello`）。

## Runnable sample

`examples/sample_echo/` 是最小可運行 plugin 範例(獨立 pip dist,經 `testpilot.plugins`
entry-point 被發現)。它示範 entry-point 宣告、`PluginBase` 子類、`api_version`、
schema-valid case + 測試,以及 `pip install` 後被 host 發現的完整路徑:

```bash
pip install -e ./examples/sample_echo
testpilot list-plugins            # -> sample_echo
testpilot list-cases sample_echo  # -> echo-hello
testpilot run sample_echo --case echo-hello   # -> PASS
```

> entry-point value 用 top-level import package 路徑(`testpilot_sample_echo.plugin:Plugin`),
> 這對獨立安裝的 dist 才穩定;`plugins.x.plugin:Plugin` 形式需該 dist 有打包 `plugins` package。

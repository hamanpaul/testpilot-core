# TestPilot 測試計畫

## 1. 架構摘要

TestPilot 是一個 plugin-based 測試自動化引擎，主要元件：

| 元件 | 模組 | Side-effect owner | 非同步邊界 |
|---|---|---|---|
| CLI | `testpilot.cli` | stdout / exit code | Click CliRunner |
| Orchestrator | `testpilot.core.orchestrator` | report 生成、plugin dispatch | per-case agent 呼叫 |
| PluginBase | `testpilot.core.plugin_base` | 無（ABC） | — |
| Plugin Loader | `testpilot.core.plugin_loader` | filesystem discovery | — |
| Transport | `testpilot.transport.*` | 裝置 I/O（serial/adb/ssh） | subprocess / socket |
| Reporting | `testpilot.reporting.*` | Excel 檔案寫入 | — |
| Config | `testpilot.core.testbed_config` | YAML 讀取 | — |

### 狀態機

Orchestrator 的 per-case 執行流程：

```
discover → filter → [for each case]:
  setup_env → verify_env → [for each step]:
    execute_step → (success? continue : break)
  → evaluate → teardown
  → (verdict? done : retry?)
  → record result
→ fill report → finalize metadata
```

## 2. 風險矩陣

依 test-playbook 標準分類：

| 風險面 | 涵蓋測試 | 說明 |
|---|---|---|
| **Correctness** | E01–E04 | CLI 入口、transport factory、plugin contract、case filtering |
| **Timeout / Recovery** | E05–E07 | serialwrap retry、timeout escalation、fail-and-continue |
| **Resource Lifecycle** | E08 | transport connect/disconnect 狀態機 |
| **Durability** | E09 | report run_id 唯一性，避免覆蓋 |
| **Usage Drift** | E10 | CLI help text vs README 一致性 |
| **Concurrency** | — | 目前 sequential-only，暫不測試 |

## 3. 測試目錄結構

```
tests/                              ← engine & 主架構測試
  test_cli.py                       (E01) CLI 入口點
  test_transport_factory.py         (E02) Transport factory
  test_plugin_base_contract.py      (E03) PluginBase ABC 合約
  test_orchestrator_case_filtering.py (E04) Case filtering
  test_transport_serialwrap.py      (E05) Serialwrap timeout/retry
  test_orchestrator_retry.py        (E06) Retry timeout escalation
  test_orchestrator_fail_continue.py (E07) Fail-and-continue
  test_transport_lifecycle.py       (E08) Transport lifecycle
  test_report_uniqueness.py         (E09) Report 唯一性
  test_cli_doc_alignment.py         (E10) CLI/README drift 檢測
  test_plugin_loader.py             Plugin discovery（既有）
  test_case_schema.py               YAML case schema（既有）
  test_topology.py                  Testbed config（既有）
  test_copilot_session.py           Copilot SDK adapter（既有）
  test_agent_runtime.py             Agent runtime config（既有）

plugins/wifi_llapi/tests/           ← wifi_llapi plugin 專屬測試
  test_wifi_llapi_plugin_runtime.py (427 tests) case YAML 驗證
  test_wifi_llapi_excel_template.py (8 tests) Excel report pipeline
  test_orchestrator_realistic_runtime.py (6 tests) 執行路徑整合
  test_orchestrator_per_case_agent.py (2 tests) per-case agent
  test_yaml_command_audit.py        (6 tests) YAML 指令稽核
```

### 分工邏輯

- **`tests/`**：與 wifi_llapi 無關的 engine 核心測試，使用 mock/fake，不依賴實機
- **`plugins/wifi_llapi/tests/`**：100% wifi_llapi 相關，含 hardcoded case IDs / YAML 驗證

## 4. Engine Test Backlog

### Phase 1: Correctness（unit）

| ID | 檔案 | 目標 | Oracle | Harness |
|---|---|---|---|---|
| E01 | `test_cli.py` | CLI 入口點可用性 | exit_code + output 內容 | `click.testing.CliRunner` |
| E02 | `test_transport_factory.py` | Factory 回傳正確 transport type | `isinstance()` 檢查 | direct import |
| E03 | `test_plugin_base_contract.py` | ABC 禁止不完整子類 | `TypeError` on instantiation | direct import |
| E04 | `test_orchestrator_case_filtering.py` | D### 通過、underscore 排除 | count + ID 格式斷言 | `Orchestrator` instance |

### Phase 2: Recovery / Timeout

| ID | 檔案 | 目標 | Oracle | Harness |
|---|---|---|---|---|
| E05 | `test_transport_serialwrap.py` | Timeout/retry/ATTACH recovery | state machine 斷言 | monkeypatch subprocess |
| E06 | `test_orchestrator_retry.py` | Timeout escalation 公式正確 | `pytest.approx()` | direct method call |
| E07 | `test_orchestrator_fail_continue.py` | 單 case 失敗不中斷 run | mock plugin 方法 | `MagicMock` plugin |

### Phase 3: Resource Lifecycle / Durability

| ID | 檔案 | 目標 | Oracle | Harness |
|---|---|---|---|---|
| E08 | `test_transport_lifecycle.py` | connect/disconnect 狀態正確 | `is_connected` property | `StubTransport` |
| E09 | `test_report_uniqueness.py` | Report filename 含唯一 run_id | 字串包含斷言 | direct function call |

### Phase 4: Documentation Drift

| ID | 檔案 | 目標 | Oracle | Harness |
|---|---|---|---|---|
| E10 | `test_cli_doc_alignment.py` | README CLI 指令皆存在 | Click 解析無 "No such command" | regex + CliRunner |

## 5. 已知 Live Bugs 回歸對應

3x full run（v0.1.2）發現的 4 個 bug 及對應 regression test：

| Bug | 修正 | Regression Test |
|---|---|---|
| DUT dmesg kernel flood | `plugin.py`: skip `dmesg -c` | `test_wifi_llapi_plugin_runtime.py` DUT command assertions |
| 5G ModeEnabled reversion | `plugin.py`: skip redundant restore | Covered by D-series YAML runtime tests |
| 6G connect non-fatal | `plugin.py`: 6G failure → warning | Covered by multiband runtime tests |
| Multi-line printf join | `plugin.py`: join `\n` in command | Covered by D-series YAML runtime tests |

## 6. 驗證命令

```bash
# 全套
uv run pytest -q

# Engine only
uv run pytest tests/ -q

# Plugin only
uv run pytest plugins/wifi_llapi/tests/ -q

# 單一檔案
uv run pytest tests/test_cli.py -v

# 特定測試
uv run pytest tests/test_orchestrator_retry.py::TestAttemptTimeoutSeconds::test_default_policy_first_attempt -v

# Coverage (if available)
uv run pytest --cov=testpilot --cov-report=term-missing -q
```

# core ⊥ wifi_llapi 解耦 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL：用 superpowers:subagent-driven-development（建議）或 superpowers:executing-plans 逐 task 實作。步驟用 checkbox（`- [ ]`）追蹤。

**Goal：** 讓 `src/testpilot/core`、`schema`、`reporting` 對任何 plugin 零具名知識；wifi_llapi 完全透過 `PluginBase` hook 接入，行為位元級不變。

**Architecture：** 重用既有 `create_reporter()` hook + 新增 3 個 plugin-agnostic optional hook（`validate_case` / `execution_policy` / `register_cli`），把 wifi_llapi 邏輯從 core 搬回 `plugins/wifi_llapi/`，core 改走契約呼叫。每階段以既有測試 + golden snapshot 當回歸網。

**Tech Stack：** Python 3.11、pytest、uv、既有 testpilot plugin 框架（`core/plugin_base.py` / `core/plugin_loader.py`）。

**重構計畫的特性：** 多數步驟是「搬移既有函式 + 更新 import + core 改走 hook」，被搬的程式碼已存在、不在計畫中重抄；新程式碼（hook 定義、reporter wrapper、glue、測試）給出具體碼。**鐵律：每階段結束 `uv run pytest -q` 全綠且 golden snapshot 不變才能進下一階段。**

**前置：** 分支 `feature/decouple-core-wifi-llapi`（已含 openspec change、rebase 於 policy 1.0.3 main）。所有 commit 留本機，最後一起 PR。

---

## File Structure（搬遷地圖）

| 來源（core，將清空 wifi_llapi） | 目的（plugin） |
|---|---|
| `src/testpilot/reporting/wifi_llapi_{align,artifacts,excel,inventory,reproject,summary}.py` | `plugins/wifi_llapi/reporting/` |
| `src/testpilot/reporting/wifi_llapi_compare_0401.py` | 刪除（或 `plugins/wifi_llapi/scripts/`）|
| `src/testpilot/core/orchestrator.py` 的 `_build/_prepare/_finalize_wifi_llapi_alignment*`、`build_wifi_llapi_summary` 呼叫 | `plugins/wifi_llapi/reporting/reporter.py`（`WifiLlapiReporter`）|
| `src/testpilot/schema/case_schema.py: validate_wifi_llapi_case` | `plugins/wifi_llapi/`（`plugin.validate_case` 呼叫）|
| `src/testpilot/yaml_command_audit.py` | `plugins/wifi_llapi/` |
| `src/testpilot/core/case_utils.py` 的 wifi_llapi official/D### helper | `plugins/wifi_llapi/` |
| `src/testpilot/core/runner_selector.py` 的 wifi_llapi 約束 | `plugins/wifi_llapi/`（`plugin.execution_policy`）|
| `src/testpilot/cli.py` 的 wifi_llapi 命令 | `plugins/wifi_llapi/`（`plugin.register_cli`）|

新增 hook 於 `src/testpilot/core/plugin_base.py`（不搬，擴充）。

---

## Task 1：基準線安全網

**Files:** `tests/` 新增 golden + smoke

- [ ] **1.1 記錄基準**：`uv run pytest -q` 全綠，記下總數（基準）
- [ ] **1.2 補報表 golden snapshot**：對一組代表性 wifi_llapi case，產出 xlsx/markdown/html，把關鍵欄位（verdict、summary buckets、M 欄 comment、KPI 計數）存成 `tests/golden/wifi_llapi_report_baseline.json`，新增 `tests/test_wifi_llapi_report_golden.py` 斷言「跑出來 == golden」。先確認此測試在現況 PASS。
- [ ] **1.3 second-plugin smoke**：新增 `tests/test_core_unknown_plugin.py`：用 `plugins/_template`（或 inline mock plugin）跑一個 minimal case，斷言 setup→…→teardown→報表產出全程完成、core 不需 wifi_llapi。現況應 PASS（走 default 路徑）。
- [ ] **1.4 commit**：`git commit -m "test(decouple): 基準 golden snapshot + unknown-plugin smoke"`

## Task 2：擴充 PluginBase（3 hook，default 不改行為）

**Files:** Modify `src/testpilot/core/plugin_base.py`；Test `tests/test_plugin_base_hooks.py`

- [ ] **2.1 寫失敗測試**：default 實作行為。
```python
# tests/test_plugin_base_hooks.py
from plugins._template.plugin import Plugin

def test_default_hooks_are_noops():
    p = Plugin()
    assert p.validate_case({"id": "x"}) is None
    assert p.execution_policy({"id": "x"}) == {}
    assert p.register_cli(_FakeSubparsers()) is None

class _FakeSubparsers:
    def add_parser(self, *a, **k): raise AssertionError("default must not register")
```
- [ ] **2.2 跑測試**：`uv run pytest tests/test_plugin_base_hooks.py -q` → FAIL（hook 不存在）
- [ ] **2.3 加 hook**（`plugin_base.py`，與既有 optional hook 同段）：
```python
    def validate_case(self, case: dict[str, Any]) -> None:
        """case 載入後的 plugin 專屬驗證；違規 raise。default no-op。"""
        return None

    def execution_policy(self, case: dict[str, Any]) -> dict[str, Any]:
        """plugin 宣告自身執行約束（concurrency/mode/runner）。default 中性。"""
        return {}

    def register_cli(self, subparsers: Any) -> None:
        """plugin 註冊自己的 CLI 子命令。default 不註冊。"""
        return None
```
- [ ] **2.4 跑測試** → PASS；**2.5** `uv run pytest -q` 全綠（含 1.2/1.3）；**2.6 commit**

## Task 3：報表解耦（create_reporter）— 最大的一步

**Files:** Move 7 modules → `plugins/wifi_llapi/reporting/`；Create `plugins/wifi_llapi/reporting/reporter.py`；Modify `core/orchestrator.py`、`reporting/reporter.py`

- [ ] **3.1** 搬 6 個 `reporting/wifi_llapi_{align,artifacts,excel,inventory,reproject,summary}.py` → `plugins/wifi_llapi/reporting/`，更新其互相 import 與 `tests/test_wifi_llapi_*` 的 import 路徑
- [ ] **3.2** 建 `plugins/wifi_llapi/reporting/reporter.py`：`class WifiLlapiReporter`，把 orchestrator 的 `_build_wifi_llapi_alignment_summary`/`_prepare_wifi_llapi_alignment`/`_finalize_wifi_llapi_alignment_artifacts` 與 `build_wifi_llapi_summary` 呼叫流搬入，對外暴露 `generate(run_results) -> ReportBundle`（涵蓋既有 orchestrator 報表段產出）
- [ ] **3.3** `plugins/wifi_llapi/plugin.py`：實作 `create_reporter(self): return WifiLlapiReporter(...)`、`report_formats()` 回傳既有格式
- [ ] **3.4** `core/orchestrator.py`：刪 `wifi_llapi_*` import 與 `_*_wifi_llapi_alignment*` 方法；報表段改 `reporter = plugin.create_reporter() or DefaultReporter(); bundle = reporter.generate(run_results)`
- [ ] **3.5** `core/reporting/reporter.py`：把 `_wifi_llapi summary` 引用改讀 generic `meta.get("plugin_summary")`
- [ ] **3.6** 刪 `reporting/wifi_llapi_compare_0401.py` 與其 `tests/test_wifi_llapi_compare_0401.py`（或一併移 plugin scripts）
- [ ] **3.7** `uv run pytest -q` 全綠 **且 golden snapshot（1.2）不變**——此為本階段成敗關鍵。任何報表輸出 diff 必須查清（搬移錯誤 vs 預期）
- [ ] **3.8 commit**：`feat(decouple): wifi_llapi 報表移入 plugin（create_reporter）`

## Task 4：驗證/audit/case-helper 解耦（validate_case）

**Files:** Move `yaml_command_audit.py`、`schema.validate_wifi_llapi_case`、`case_utils` wifi_llapi helper → plugin；Modify `orchestrator`/`schema`/`case_utils`

- [ ] **4.1** 搬 `validate_wifi_llapi_case`（schema）+ `yaml_command_audit.py` + `case_utils` 的 `is_wifi_llapi_official_case`/D### selector → `plugins/wifi_llapi/`，更新對應測試 import
- [ ] **4.2** `plugins/wifi_llapi/plugin.py`：實作 `validate_case(case)` 呼叫搬入的驗證 + audit
- [ ] **4.3** `core/orchestrator.py`、`schema/case_schema.py`：case 載入後改呼叫 `plugin.validate_case(case)`，移除 `validate_wifi_llapi_case` 具名 import；`case_utils` 移除 wifi_llapi helper
- [ ] **4.4** `uv run pytest -q` 全綠（BLOCKED/驗證/audit 行為不變）；**4.5 commit**

## Task 5：執行約束解耦（execution_policy）

**Files:** Modify `core/runner_selector.py`、`core/orchestrator.py`、`plugins/wifi_llapi/plugin.py`

- [ ] **5.1** 把 `runner_selector` 的 wifi_llapi 約束（force sequential / concurrency=1）抽成 plugin 可宣告的策略；wifi_llapi `plugin.execution_policy(case)` 回傳 `{"mode": "sequential", "max_concurrency": 1, ...}`
- [ ] **5.2** `core/orchestrator.py`/`runner_selector.py`：改問 `plugin.execution_policy(case)`，移除 `_wifi_llapi_execution_policy`/`_load_wifi_llapi_agent_config` 等具名 delegate 與 `runner_selector` 內 wifi_llapi 具名分支
- [ ] **5.3** `uv run pytest -q` 全綠（runner 選擇/concurrency 行為不變）；**5.4 commit**

## Task 6：CLI 解耦（register_cli）

**Files:** Modify `src/testpilot/cli.py`、`plugins/wifi_llapi/plugin.py`

- [ ] **6.1** 把 `cli.py` 的 wifi_llapi 命令（`reproject`、template、`testpilot wifi_llapi` 子命令處理）搬到 `plugins/wifi_llapi/`，由 `plugin.register_cli(subparsers)` 註冊
- [ ] **6.2** `cli.py`：載入 plugin 後對每個 plugin 呼叫 `plugin.register_cli(subparsers)`；移除 `wifi_llapi_excel`/`reproject` 具名 import
- [ ] **6.3** 同步 `.project-policy.yml` 的 CLI help marker（`testpilot-wifi-llapi-help` 等）與實際輸出（R-16/release-governance cli-help-sync）
- [ ] **6.4** `uv run pytest -q` 全綠 + `testpilot wifi_llapi --help` 輸出與基準一致；**6.5 commit**

## Task 7：收尾與驗收

- [ ] **7.1** 新增 `tests/test_core_has_no_plugin_names.py`：斷言 `grep -r wifi_llapi`（用 pathlib 掃 `src/testpilot/core`、`schema`、`reporting`）結果為空
- [ ] **7.2** 跑 7.1 → 若非空，回到對應 Task 清乾淨
- [ ] **7.3** second-plugin smoke（1.3）+ golden（1.2）+ `test_wifi_llapi_plugin_runtime` 全綠
- [ ] **7.4** 全套件 `uv run pytest -q` 綠；`external-policy`（1.0.3，tier=work）本地驗證綠
- [ ] **7.5** 更新 `DESIGN.md` / `plugins/_template/README.md` / plugin-dev-guide：報表/驗證/執行/CLI 皆走 hook
- [ ] **7.6** CHANGELOG `[Unreleased]` 加條目；**commit**

---

## Self-Review

- **Spec coverage**：openspec `core-plugin-isolation` 三 requirement → Task 7.1（core 零具名）、Task 2–6（hook 契約）、Task 1.2/3.7/6.4（行為不變）全覆蓋。tasks.md 7 階段 1:1 對應。✓
- **型別一致**：`create_reporter()`/`validate_case()`/`execution_policy()`/`register_cli()` 簽名與 design.md 一致；`WifiLlapiReporter.generate()` 在 Task 3 定義後於 orchestrator 使用，無前向參照。
- **重構特性已聲明**：搬移的既有程式碼不在計畫重抄；新碼（hook/reporter/glue/測試）有具體碼。每階段 golden + 全測試是防漂移閘。
- **風險**：Task 3（orchestrator 報表流搬出）最重，golden snapshot（1.2）是它唯一可靠的回歸網——務必在 1.2 確實鎖住輸出後才動 Task 3。

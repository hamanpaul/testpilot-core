# Sample Echo Plugin — 設計 spec

> 制定日期:2026-07-04
> 狀態:草案(待 review)
> 來源:brainstorming(GitHub issue hamanpaul/testpilot-core#3「提供可運行的 sample plugin」)
> 落點決策:留在 testpilot-core repo,以 `examples/` 帶自己 pyproject 的獨立 dist 呈現(非塞進 core wheel)

## Goal

為第三方 plugin 開發者提供一個**最小、可 `pip install`、可被 host 發現、可真的跑出 Pass/Fail verdict** 的 sample plugin,作為 `testpilot.api` SDK 的對照範例,搭配 `docs/plugin-dev-guide.md`。

驗收對照 issue #3 的 demo 清單:`entry_points` 宣告、`PluginBase` 子類、`api_version`、最小 case + 測試、`pip install` 後被 host 發現。

## Motivation

現況只有 `plugins/_template/`,它是**刻意不可運行、不註冊**的 scaffold:未 override runner/reporter,`Orchestrator.run()` 只會落到 `_skeleton_run`(回 `status="skeleton — not yet implemented"`,無 verdict);其 `example.yaml` 也不符合嚴格 case schema(缺 `topology`),靠自寫 loose loader 繞過;README 教的 entry-point 寫法 `plugins.my_plugin.plugin:Plugin` 只在 pytest `pythonpath` 下可解析,真實 wheel 裝完會 import 失敗。

因此開發者手上沒有一個「照著抄就能跑」的活範例,而 `docs/plugin-dev-guide.md` 也沒有指向任何可運行 sample(且 line 264 的參考連結 `plugins/wifi_llapi/cases/_template.yaml` 在 wifi_llapi 拆分後已成死連結)。

## 落點決策(brainstorming 已定案)

| 候選形態 | 結論 |
|----------|------|
| 塞進 core wheel + 在 core `pyproject.toml` 註冊 entry-point | ❌ 破壞 core 中立契約 |
| repo 內 `examples/` 帶自己 pyproject 的獨立 dist | ✅ **採用** |
| 另開獨立 repo | ❌ 對一個 demo 過度,違背「包在 testpilot-core 裡」偏好 |
| 只更新文件 | ❌ 交付不出可執行、可安裝、可被發現的 demo |

**為何不進 core wheel(契約因素,非規模因素):** `openspec/specs/plugin-entry-points-discovery` 等規格明訂 core 為裝置中立、不含任何具名 plugin;只裝 core 時 `PluginLoader.discover()` / `testpilot list-plugins` **MUST 為空**。現況 core `pyproject.toml` 完全沒有任何 `[project.entry-points]`,wheel 只打包 `src/testpilot`(已確認)。一旦在 core pyproject 註冊 sample,每個下游 `pip install testpilot-core` 開箱 `list-plugins` 就非空,牴觸中立契約並需改動中立性 / wheel-contents 測試。

`examples/` 獨立 dist 是**唯一同時滿足「留在 testpilot-core repo」+「不破壞打包/契約/CI」**的形態,也是**唯一能真實重現「`pip install` 另一個 dist → 經 `testpilot.plugins` entry_points 被 host 發現」**的形態(現有 discovery 測試全部用 monkeypatch 假造 entry_points,從未驗證真實安裝路徑)。它 1:1 對映 `wifi_llapi` / `brcm_fw_upgrade` 兩個真實 plugin 的形狀,卻不必多養一個 repo。

## Scope

- 新增 `examples/sample_echo/`:獨立 dist `testpilot-sample-echo`(import package `testpilot_sample_echo`,plugin 名 `sample_echo`)。
- 一個真的能跑出 Pass/Fail 的 echo plugin(走 runner → `run_pipeline` 路徑,不出報表 bundle)。
- 一個符合嚴格 schema 的 case `echo-hello.yaml`。
- 示範選配 hook `register_cli`(掛一個 sample 子命令)。
- 單元 smoke 測試 + CI 一步「真實安裝後驗發現」。
- 連帶清理:`docs/plugin-dev-guide.md` 死連結與 entry-point 寫法、`README.md` 加 sample 連結、清 `plugins/wifi_llapi/reports/` 殘骸。

## Non-goals

- 不產出報表 bundle(不 override `create_reporter()` / `build_reports()`)。使用者已選「verdict-only」。
- 不把 sample 變成正式發佈、可長期依賴的 supported package(不進 `install-manifest.yaml`、不進 `uv.lock`、不背 release 版本流程)。
- 不改動 core 的既有行為 / 契約 / 中立性。
- 不改造 `plugins/_template`(只在文件層統一 entry-point 寫法的說明,不動其程式行為)。

## Architecture

### 目錄與封裝

```
examples/sample_echo/
├── pyproject.toml
├── README.md
├── src/
│   └── testpilot_sample_echo/
│       ├── __init__.py
│       ├── plugin.py
│       └── cases/
│           └── echo-hello.yaml
└── tests/
    └── test_sample_echo.py
```

`pyproject.toml` 重點:

```toml
[project]
name = "testpilot-sample-echo"
version = "0.1.0"
dependencies = ["testpilot-core"]

[project.entry-points."testpilot.plugins"]
sample_echo = "testpilot_sample_echo.plugin:Plugin"
```

- entry-point group 名**精確等於** `PluginLoader.ENTRY_POINT_GROUP = "testpilot.plugins"`。
- value 用 **top-level import package 路徑** `testpilot_sample_echo.plugin:Plugin`(可在真實 wheel 安裝後解析),而非 `_template` README 的 `plugins.x.plugin:Plugin` 形式。
- 採 `src/` layout,與 core 及真實 plugin 一致。

### Plugin(`plugin.py`)

`class Plugin(PluginBase)`,**僅 `from testpilot.api import ...`**(通過 `tests/test_plugin_sdk_api_boundary.py` 的 ALLOWLIST=空 邊界守門)。

必要成員(對照已驗證的 `PluginBase` 契約):

| 成員 | 型別/簽名 | 本 sample 的實作 |
|------|-----------|------------------|
| `api_version` | class attr `str` | `"1.0"`(對 core `API_VERSION="1.1"` 相容:major 同、api.minor 1 ≥ plugin.minor 0) |
| `name` | `@property -> str` | `"sample_echo"` |
| `discover_cases()` | `-> list[dict]` | 用 `testpilot.api.load_cases_dir` + `importlib.resources.files("testpilot_sample_echo")/"cases"` 讀自身 cases(**嚴格 schema 驗證**,非 loose loader) |
| `execute_step(case, step, topology)` | `-> dict` | 用 `testpilot.api.StubTransport`:`connect()` → `execute(command)` → 回 `{success:True, output, captured, timing}`;`command` 由 step 的 `action` + `target` 組出;`output` 即 StubTransport 回的 `"[stub] <command>"` |
| `evaluate(case, results)` | `-> bool` | 比對 `case["pass_criteria"]`:把所有 step 的 `results["steps"][*]["output"]` 串成一個合集字串,**每個** pass_criteria 字串都須出現在該合集中(any-step 比對,不綁定特定 step),全中則回 `True` |

額外 override:

- `create_runner() -> EchoRunner`:**這是讓 sample 真的跑出 verdict 的關鍵**。未 override 時 `Orchestrator.run()` 落到 `_skeleton_run`(無 verdict)。
- `register_cli(registrar)`:掛一個 demo 子命令(見下)。

其餘 hook(`version` / `setup_env` / `verify_env` / `teardown` / `validate_case` / `execution_policy` / `create_reporter` / …)全用 `PluginBase` 預設。

### Runner(`EchoRunner`,同檔內)

繞過 `_skeleton_run` 的最小 runner。`Orchestrator.run()` 的 dispatch(已驗證 `orchestrator.py`):若 `plugin.create_runner()` 回非 None 且有 `.run()`,則呼叫

```
runner.run(orchestrator, plugin_name, case_ids, dut_fw_ver, provider_config) -> dict
```

`EchoRunner.run(...)` 邏輯:

1. `cases = plugin.discover_cases()`,依 `case_ids` 過濾。
2. 逐 case 呼叫 `plugin.run_pipeline(case, topology=case.get("topology"))`。
   - `run_pipeline`(core 預設)會跑 `setup_env → verify_env → 各 step execute_step → evaluate → teardown`,回 `{verdict, comment, commands, outputs}`。
3. 匯總回一個可讀 dict:`{"plugin": plugin_name, "results": [{case_id, verdict, comment}], "verdict": all-pass}`。CLI 端會 `console.print(result)`。

### Case(`cases/echo-hello.yaml`)

符合 `case_schema`(已驗證的必要鍵):

- 頂層:`id / name / topology / steps / pass_criteria`。
- `topology.devices`:非空 mapping(補 `_template/example.yaml` 目前缺的東西)。
- 每個 `step`:`{id, action, target}`。
- `pass_criteria`:非空 list of 非空字串;內容設計成能被 echo 輸出滿足(例如 `target` 的 token 會出現在 `"[stub] <command>"` 裡),確保 deterministic Pass。

### CLI 示範(`register_cli`)

`register_cli(registrar)` 用 `testpilot.api.CliRegistrar`(方法:`add_command(click.Command)` / `add_group(click.Group)`)掛一個最小 click 命令,例:

```
testpilot sample-echo-greet --name <X>
```

印出經 plugin echo 過的字串,示範 optional CLI hook 如何把 plugin 自有命令掛上 testpilot root group。plugin 生產碼 import `click` 與 `testpilot.api.CliRegistrar`,不 import `testpilot.cli`。

## 測試策略

### 單元 smoke(`tests/test_sample_echo.py`)

對齊既有測試風格(參考 `tests/test_plugin_entry_points_discovery.py` 的假 entry_point 模式):

1. discover → `PluginLoader.load("sample_echo")`(驗 api_version 相容、`issubclass(PluginBase)`)。
2. 跑 `echo-hello`(經 `EchoRunner` 或直接 `run_pipeline`)→ 斷言 verdict = Pass。
3. 斷言 `discover_cases()` / `list-cases` 含 `echo-hello`。
4. 斷言 plugin 生產碼只 import `testpilot.api`(可複用既有 boundary 測試機制或本地斷言)。

### CI 一步:真實安裝驗發現(補現況缺口)

現況所有 discovery 測試都 monkeypatch 假 entry_points,從未驗真實 `pip install`。在 `.github/workflows/ci.yml` `uv sync` **之後**新增一步:

```bash
uv pip install ./examples/sample_echo         # ad-hoc,不動 uv.lock
.venv/bin/testpilot list-plugins              # 斷言含 sample_echo
.venv/bin/testpilot run sample_echo --case echo-hello   # 斷言 PASS
```

**不改 `uv.lock`、不改 `uv sync --locked`**;sample 維持非 workspace member。

## 連帶清理(選配,使用者已選)

- `docs/plugin-dev-guide.md`:
  - 修 line 264 死連結(`plugins/wifi_llapi/cases/_template.yaml` 已不存在)。
  - 新增「Runnable sample」章節指向 `examples/sample_echo`,附 `pip install -e . → list-plugins → list-cases → run` 的 end-to-end walkthrough。
  - 統一 entry-point 寫法說明為「可真實安裝的 top-level package 形式」(對照 README / `_template/README` 三處不一致)。
- `README.md`「Writing a Plugin」段加 sample 連結。
- 清掉 `plugins/wifi_llapi/reports/` 下 stale 執行殘骸(拆分後本不該留在 core)。

## 風險與規避

| 風險 | 規避 |
|------|------|
| 未 override runner/reporter → `_skeleton_run`,無 verdict | 提供 `EchoRunner`,明確走 runner 路徑 |
| case 缺 `topology` → `load_cases_dir` raise `CaseValidationError` | case 補齊 `topology.devices` 與 step `{action,target}`;不照抄 `_template/example.yaml` |
| plugin 誤 import core 內部(如 `from testpilot.transport.base import StubTransport`)→ boundary 測試 FAIL | 一律 `from testpilot.api import ...` |
| entry-point value 用 `plugins.x.plugin:Plugin` 形式 → 真實 wheel 裝完 import 失敗 | 用 top-level `testpilot_sample_echo.plugin:Plugin` |
| sample 進 `uv.lock` → `uv sync --locked` 可重現性壞掉 | 維持非 workspace member,CI 於 uv sync 後 ad-hoc `uv pip install` |
| sample 誤入 `install-manifest.yaml` → `scripts/install.sh` 對它 `gh release download` 抓不存在 release 而 HARD FAIL | 絕不加入 install-manifest.yaml |
| 命名撞 `_template`(前導底線,spec 明訂 MUST NOT 被 discover)或撞使用者已裝真實 plugin(duplicate entry-point 名 → `PluginLoader` raise `ValueError`) | 用明顯 demo 名 `sample_echo` |
| `get_orchestrator` 會 `stage_plugin_testbed(plugin.plugin_root, ...)`,對 stub sample 可能找不到 configs | 實作階段確認 stub 路徑不需要 testbed staging,或提供最小 configs |

## 交付定義(Definition of Done)

- `uv pip install ./examples/sample_echo` 後 `testpilot list-plugins` 含 `sample_echo`。
- `testpilot list-cases sample_echo` 含 `echo-hello`。
- `testpilot run sample_echo --case echo-hello` 輸出 verdict = Pass。
- `testpilot sample-echo-greet --name X` 可執行(CLI hook demo)。
- `tests/test_sample_echo.py` 綠;core 既有測試(boundary / neutrality / discovery)不受影響仍綠。
- CI 新增的真實安裝步驟綠。
- 文件死連結修好、sample 連結就位、`plugins/wifi_llapi/reports/` 清乾淨。

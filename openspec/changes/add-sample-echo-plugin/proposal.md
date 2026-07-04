## Why

testpilot-core 目前只有 `plugins/_template/`(刻意不可運行、不註冊的 scaffold),
第三方開發者手上沒有一個「照著抄就能跑」的活範例,`docs/plugin-dev-guide.md` 也沒有
指向任何可運行 sample(且死連結指向已拆分的 wifi_llapi)。issue #3 要求提供一個最小、
可 `pip install`、可被 host 發現、可跑出 verdict 的 sample。

## What Changes

- 新增 `examples/sample_echo/`:獨立 pip dist `testpilot-sample-echo`,經 `testpilot.plugins`
  entry-point 被發現;只依賴 `testpilot.api`;走 `create_runner()` → `run_pipeline()` 產出
  Pass verdict;示範選配 `register_cli`。
- 不進 core wheel / `install-manifest.yaml` / `uv.lock`(維持 core 中立契約)。
- CI 新增真實安裝發現 smoke(補現況只 monkeypatch 假 entry_points 的缺口)。
- 文件:修 dev-guide 死連結、加 Runnable sample 章節、README 連結;清 `plugins/wifi_llapi/reports/` 殘骸。

## Capabilities

### New Capabilities
- `plugin-sample-reference`: 專案 SHALL 提供一個最小可運行 sample plugin 作為 SDK 對照範例,
  以獨立 dist 形態經 entry_points 被發現,且僅依賴 `testpilot.api`。

## Impact

- 新增 `examples/sample_echo/`(非 core wheel、非 workspace member)。
- `.github/workflows/ci.yml` 新增 sample 安裝發現 step。
- `docs/plugin-dev-guide.md` / `README.md` 文件更新;`plugins/wifi_llapi/reports/` 清理。
- 對 core 行為 / 契約 / 中立性零影響。

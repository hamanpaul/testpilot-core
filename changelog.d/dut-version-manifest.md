---
type: feat
scope: core
---
`run_loop` 無條件呼叫 plugin 的 DUT 版本 capture（fail-soft：擷取失敗記 warning 並以 `{}` 續行、不中止 run），naming 仍以 `--dut-fw-ver` 優先、fallback 取 `manifest["git"]`，整份 manifest 存進 `meta["version_manifest"]`。html/md reporter 於報表頂部渲染收折的 Environment/Versions 區塊（缺資料 no-op、不具名 plugin）。

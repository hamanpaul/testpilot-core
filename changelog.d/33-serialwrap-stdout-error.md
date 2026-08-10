---
type: fix
scope: transport
issue: 33
---
serialwrap CLI 失敗時常把錯誤 JSON 印在 stdout（stderr 常為空），例如 daemon start
被 systemd gate 拒絕時。`runtime/_serialwrap_log.py::_run_sw` 與
`transport/serialwrap.py::_run_json` 在 `returncode != 0` 時原本只擷取 stderr 組成例外訊息，
stdout 內容整包被丟掉，實地事故只看到「RuntimeError: serialwrap failed: daemon start: 」
（冒號後空白），除錯資訊歸零。

兩處改為在保留既有前綴與 stderr 內容不動的前提下（下游 wifi_llapi 以 substring 比對錯誤字串
做分類，相容性不可破壞），於訊息結尾追加 `rc=<returncode>` 與截斷到 500 字的 stdout 摘要
（stdout 為空時省略該段），讓 stdout 攜帶的錯誤細節不再遺失。

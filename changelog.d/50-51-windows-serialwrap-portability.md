---
type: fix
issue: 50
scope: runtime
---

- Windows 可攜性（serialwrap client glue，#50 / #51）：
  - `runtime/_serialwrap_log.py::_match_device_by_id` 改以 COM 名正規化比對（`COM5` / `\\.\COM5` / `com5` → `COM5`）；原本 `Path.resolve()` 會把裸 `COM5` 解析成 `<cwd>\COM5`，永遠對不到 serialwrap 回報的 `\\.\COM5`，只能靠 index fallback 碰運氣。POSIX 維持 `resolve()` 比對不變。
  - `_run_sw`、`setup_sessions` 的 `session bind` `Popen`、`transport/serialwrap.py::_run_json` 一律 `encoding="utf-8", errors="replace"`；serialwrap 輸出固定 UTF-8，cp950 等 locale 預設編碼會在 reader thread 拋 `UnicodeDecodeError`。

---
type: feat
scope: cli
---
`testpilot --version` 除 core 版本與 source ref 外，新增穩定排序的 installed plugin inventory，顯示各 `testpilot.plugins` entry point 的 distribution version 與 `api_version`；單一 plugin metadata 或 import 失敗時以 `unknown` fail-soft 顯示，不影響其餘 inventory 或 core 版本輸出。（#18）

---
type: feat
scope: examples
---
新增可運行的最小 sample plugin `examples/sample_echo`(獨立 dist `testpilot-sample-echo`,經 `testpilot.plugins` entry-point 被發現、只依賴 `testpilot.api`、走 `create_runner`→`run_pipeline` 產出 Pass verdict,含 `register_cli` demo 與 API 邊界測試);CI 補真實安裝發現 smoke;修 `docs/plugin-dev-guide.md` 死連結並加 Runnable sample 章節、清 `plugins/wifi_llapi/reports/` 殘骸並加 `.gitignore` 規則(ignore `plugins/*/reports/` run bundle、保留 `templates/`,防 run_loop 產生的 lab 產物再被追蹤 / R-21)。對照 issue #3。

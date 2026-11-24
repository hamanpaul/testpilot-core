---
type: docs
scope: architecture
---

重構 TestPilot Core 互動式架構圖以釐清執行流程與管控邊界：獨立標示 Plugin SDK（`testpilot.api` v1.7）公開契約與選用工具庫、將 `SDK Transport` 移出 Core 管控範圍、明確區分 `RunBackend` 整輪日誌擷取與報表觸發／領域投影權責，並新增 3 頁細部流程時序圖（啟動分流、單案重試與修復、收尾擷取與報表）與可移除的滾輪縮放／多頁導覽 overlay（`tools/architecture_overlay.py`）。

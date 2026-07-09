---
type: fix
scope: reporting
---

Markdown 報表的 WiFi LLAPI Hybrid summary 表對齊 HTML 報表：空的 `WiFi.Other` catch-all 列（無 xlsx Summary 對應）改以該 band 的 **TOTAL 匯總列**呈現（取自 `bucket_totals`，統計該 band 全 category 總數），非只顯示 WiFi.Other 的 0。先前只修了 `html_reporter`（見 `feat-html-report-hybrid-summary-layout`），`reporter`(md) 未同步，本次補齊使兩者逐列一致。

---
type: feat
scope: reporting
---
HTML report 的 WiFi LLAPI Hybrid (tri-band) Summary 版面對齊 xlsx Summary sheet：section 位置移到 KPI/total-case 之下、per-case Summary 表之上；每 band 依 `5G`/`6G`/`2.4G` 分色（列底色 + 左側色條）以利區分；每 band 尾端新增粗體 **TOTAL** 小計列（取自 `bucket_totals`）；隱藏空的 `WiFi.Other` catch-all 列（真實 wifi_llapi 物件恆對到具體分類、Other 恆 0 且 xlsx 無此欄；Other 非零時仍顯示並計入 TOTAL）。

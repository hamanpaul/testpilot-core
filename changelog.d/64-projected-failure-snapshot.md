---
type: fix
scope: remediation
issue: 64
---

Runtime remediation 在 API 1.7 Plugin 移除私有 case 暫存欄位後，保留符合當次 case／attempt 的已投影 failure snapshot，避免失敗類別及 reason code 被覆蓋為 Inconclusive。欄位存在但無效、身分不符或不可讀時，安全套用 phase default，不退回私有 evidence；只有欄位缺席才保留 legacy fallback。

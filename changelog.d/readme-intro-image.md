---
type: fix
scope: docs
---

- 修正 README 架構總覽圖無法顯示的問題：`docs/assets/testpilot-core-intro.svg` 內嵌的 webp data URI 被截斷（RIFF header 宣告 174,676 bytes，實際只有 14,838 bytes，任何解碼器都無法還原），改以更新後的 `docs/assets/testpilot-core-intro.png`（2026-08-11 版，內容已對齊 framework positioning 說法）取代，並移除該壞掉的 svg。

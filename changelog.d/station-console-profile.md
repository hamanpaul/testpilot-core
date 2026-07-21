---
type: fix
scope: runtime
---
run-backend 裝置清單的 serialwrap session profile 不再硬編 `prpl-template`：優先讀 testbed 裝置的 `console_profile`（station-layer 選型鍵）、次之 `profile`，空值/缺席一律回退預設（truthy fallback，避免空 profile 產生畸形 session_id）。

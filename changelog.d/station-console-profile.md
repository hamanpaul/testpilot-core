### Changed
- run-backend 裝置清單的 serialwrap session profile 不再硬編 `prpl-template`：優先讀 testbed 裝置的 `console_profile`（station-layer 選型鍵）、次之 `profile`，未指定時維持原預設。

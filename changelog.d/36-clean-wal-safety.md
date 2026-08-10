---
type: fix
scope: runtime
issue: 36
---
`SerialwrapBackend.setup_run()` 在 `daemon_status()` 回 `None` 時，原本會呼叫
`_serialwrap_log.clean_wal()` 對硬編路徑 `/tmp/serialwrap/wal` 直接 `shutil.rmtree`
再啟動 daemon。實地事故顯示「`daemon_status()` 回 `None`」最常見的原因是 client
連不到 daemon（daemon 其實還活著），因此這段邏輯會刪掉正在跑的 daemon 仍在寫入的
WAL 目錄；daemon 對已被 unlink 的 fd 繼續寫入，遠端 bench 因此連續 6 天遺失 console
稽核紀錄（見 hamanpaul/serialwrap#173、#171）。

修法：`setup_run()` 的該分支移除 `clean_wal()` 呼叫，改為 `start_daemon()` 之後
best-effort 呼叫 `wal_reset()`（try/except，失敗只 log warning，不中斷
`setup_run()`）；WAL 輪替一律走 daemon 自身的 RPC `wal reset`（daemon 端保留歸檔），
不再由 client 端對 WAL 目錄做本地刪除。同步移除 `_serialwrap_log.clean_wal()` 與
`DEFAULT_WAL_DIR` 常數（repo 內確認無其他呼叫者）；`get_wal_path()` 原本共用
`DEFAULT_WAL_DIR` 組出的 fallback 路徑改為獨立的 `_WAL_PATH_FALLBACK`
私有常數 —— 僅供 daemon_status 拿不到 `wal_path` 時的顯示/紀錄用途，不再作為任何
刪除操作的目標路徑，`get_wal_path()` 的回傳型別與呼叫端行為維持不變。

新增回歸測試涵蓋：daemon 狀態未知分支不再呼叫 `shutil.rmtree`、`start_daemon()`
仍會被呼叫、成功後會呼叫 `wal_reset()`，以及 `wal_reset()` 拋例外時 `setup_run()`
不中斷且仍回傳可用的 `RunHandle`。

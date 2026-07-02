---
type: feat
scope: install
---
安裝流程改 flow latest-compatible：core/plugins 安裝當下解析 newest API-compatible（serialwrap 維持 manifest pin）。install.sh 交易式 resolve-before-mutate（先讀 core wheel API 再解析完整 plan 才動 venv）、任何動土後失敗以 ERR trap rollback、線上路徑也跑 `--verify-install` gate；`--update` installer/verify 失敗皆 rollback 不 brick；build-bundle build 期解析 newest-compatible + build-time API-compat gate + 寫 resolved-manifest.yaml。manifest core/plugins version 改 optional（serialwrap 必填），`--plugins name@ver` 保留釘版逃生口。

### Changed
- managed-install serialwrap pin 由 `0.2.1` 提升至 `0.2.4`（`install-manifest.yaml`）。0.2.1→0.2.4 涵蓋 serialwrap `v0.2.2`~`v0.2.4`（174 commits）：daemon 暴露命令長度上限 `limits`（serialwrap#129）、arbiter recovery 佇列 flush（#128）、autoboot 倒數窗 recovery lease（#114/#140）、realhw 穩定性測試套件、Windows 原生 daemon 與 ssh 反向隧道 CLI。serialwrap 無 SDK API 契約，故維持顯式 `version:` pin，本次為刻意 bump（`main` HEAD 即 `v0.2.4`）。

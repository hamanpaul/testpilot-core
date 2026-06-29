## Context

P4 拆分後 `scripts/install.sh` 仍 editable-install core checkout 內的 `plugins/<name>`，但那些路徑已不存在 → 安裝必失敗。本 change 重做 core 側安裝流程。完整背景、已驗證事實（含 `file:line` 證據）與 red-team blocker 清單見
`docs/superpowers/specs/2026-06-27-install-flow-dual-entry-design.md`；本文件只記架構決策、風險與遷移。

關鍵既有事實（決定設計）：
- Plugin 發現只靠 `importlib.metadata.entry_points(group="testpilot.plugins")`（`plugin_loader.py:113`），不掃目錄；裝進 venv 任何位置皆可被發現。
- 重複 entry-point 名稱會 `_normalize_entry_points` raise（`plugin_loader.py:100-104`）→ 重裝若不 reconcile 會 brick CLI。
- Plugin 資料 package 相對（`plugin_base.py:44`），wheel 裝進 site-packages 零路徑改動即可用。
- `uv build` 已自帶全部資料檔，無需額外 hatch 設定。

## Goals / Non-Goals

**Goals:**
- 雙入口：有網一鍵 + 信任 Linux 離線 bundle（零 git 認證、零網路），兩者共用同一套 wheel。
- 以 `install-manifest.yaml`（exact-pin + api_version）作為可重現、可驗相容的單一來源。
- `--update` / `--verify-install` 在 wheel 世界正確運作；安全遷移既有舊安裝。
- 根治 PyPI `testpilot` 撞名（改名 `testpilot-core`）。

**Non-Goals:**
- 跨平台/Windows wheel、平台矩陣（決策：Linux only）。
- 簽章 / Sigstore / attestation（決策：信任 Linux 機，checksum 足夠）。
- bundle 內帶 pip/setuptools/wheel bootstrap、`--require-hashes` 逐檔 hash（目標機已有 pip）。
- pipx 安裝模型；PyPI 正式發佈；`testpilot plugins add/remove` first-class 指令。
- plugin（wifi_llapi/brcm）與 serialwrap 的 repo 內變更（各自獨立 change）。

## Decisions

- **D1 安裝模型＝managed-venv + wheel（非 pipx）。** 沿用既有 `~/.local/share/testpilot/.venv` + wrapper，artifact 改 wheel。理由：plugin 是 private + 無 CLI 入口，pipx 收益有限；managed venv 仍給「一條指令、隔離」UX，且 `--update`/`--verify-install` 改動較小。捨棄 src checkout（operator 用 wheel；開發者另用自己的 editable checkout）。
- **D2 core 分發名改 `testpilot-core`，import 套件名仍 `testpilot`。** 理由：public PyPI 已有無關 `testpilot 0.2.9`，任何會解相依的安裝會撞名或裝到錯套件。替代方案「全程 `--no-index/--no-deps` 隔離」較脆（漏一條路徑即中招），故改名為根治。
- **D3 manifest 採 exact-pin（+ `--plugins name@ver` 覆寫逃生口）。** 理由：測試框架重可重現性；離線 bundle 本就 freeze，exact-pin 才能線上/離線一致，且 pin 時即可跑 API 相容閘保證「可裝即可用」。range 的解耦好處被「離線必 freeze」「相容延後爆」抵消。
- **D4 線上認證只走 `GH_TOKEN` env + `gh release download`，token 不入 URL。** 理由：`git+https://x-access-token:$TOKEN@...` 會從 `ps`/`.git/config`/log 外洩；`gh` 讀 env、不進 argv。
- **D5 離線完整性用 detached `SHA256SUMS` sidecar，不上簽章。** 信任機 + 受控傳輸下足夠；逐檔 hash 與 bootstrap 因「目標機有 pip」可省。
- **D6 重裝/更新一律 reconcile venv 至 manifest 集合。** 先 `pip uninstall` manifest 以外的 `testpilot.plugins` dist，dist 名凍結不改，避免重複 entry-point brick（`plugin_loader.py:100-104`）。
- **D7 skill 改成 core wheel 的 package data**，安裝後從 `importlib.resources` 同步；`--verify-install` 改驗 packaged 來源（消除缺 src checkout 時的誤報硬 FAIL）。

## Risks / Trade-offs

- [改名 `testpilot-core` 是 BREAKING] → plugin repo 的 `dependencies` 需同步改（各自 change）；過渡期 plugin CI 從 git 安裝改名後的 core 分支；本 change 的 README/CHANGELOG 明示 BREAKING。
- [線上 tag 尚無 wheel asset（CI build+upload 才剛加）] → installer 對無 asset 的 tag fallback `pip install git+...@$VER`（source build）；或只解析「帶 asset」的 tag。
- [manifest exact-pin 重新引入跨 repo cadence 耦合] → manifest bump 視為 core PATCH（flat profile，便宜），hub maintainer 負責；`--plugins name@ver` 作臨時覆寫逃生口。
- [API 相容只在 runtime 檢查（package range 表達不了 api_version）] → manifest 帶 `api_version` + CI 相容閘在 pin 時擋掉不相容組合；`--verify-install` 也試 `PluginLoader.load`。
- [重裝殘留／落單 plugin 造成重複或孤兒 entry-point] → D6 reconcile（desired-state 同步 + uninstall）。
- [離線 bundle 非 byte-reproducible 重 build 造成 checksum 漂移] → bundle 一律「下載 Release wheel」不重 build；third-party 用 `pip download` 同平台原生取得。

## Migration Plan

1. 既有機現況多為 `pip install --user testpilot==0.2.0`（非 src/.venv）。新 installer 偵測並 reconcile `pip --user` / pipx / legacy `~/.local/share/testpilot/src` 三種形態：pin/uninstall 舊 `testpilot`，重指 wrapper 到 managed venv，偵測到「managed venv 外可 import testpilot」時告警。
2. 釋出順序（DAG）：本 change（core）落地後產 `testpilot-core` wheel；plugin/serialwrap 各自 change 先發 wheel；core manifest 再 pin 那些版號。過渡期 installer 用 git+source fallback。
3. Rollback：`--update` 前先 `pip freeze` 快照；post-install `--verify-install` 失敗則回裝前一組；離線以「上一份 bundle」作為可重現 downgrade。

## Open Questions

- brcm_fw_upgrade 打包待稽核（dist 名/version/entry-point/api_version/韌體 blob 是否誤入 wheel）；稽核過才納 manifest「install all」預設（屬其獨立 change，但影響本 change manifest 的預設集合）。
- CI 是否同步加 build-provenance/attestation 留待 P3；本 change 範圍只到 `SHA256SUMS`。

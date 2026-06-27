## Why

P4 物理拆分把 plugin 切成各自獨立的 private repo，但一鍵安裝器沒跟上：
`scripts/install.sh` 仍 editable-install 已不存在的 `plugins/wifi_llapi`、`plugins/brcm_fw_upgrade`
（拆分後 core 的 `plugins/` 只剩 `_template/`），**安裝必失敗**。需要把安裝流程重做成
「core 與各 plugin 是各自獨立的可安裝 wheel」的世界，並提供雙入口：有網機一鍵裝、信任的離線 Linux
機（有 pip、缺 GitHub 認證）以單一 bundle 零認證零網路裝。設計依據
`docs/superpowers/specs/2026-06-27-install-flow-dual-entry-design.md`。

## What Changes

- **core distribution 改名 `testpilot` → `testpilot-core`**（import 套件名仍 `testpilot`），根治
  public PyPI 已有無關 `testpilot 0.2.9` 的 dependency-confusion 風險。**BREAKING**（套件分發名變更）。
- **安裝模型由 git-checkout 改為 managed-venv + wheel**：保留 `~/.local/share/testpilot/.venv` + wrapper，
  但不再維護 `~/.local/share/testpilot/src` 原始碼 checkout；core/plugin/serialwrap 皆以 wheel 裝入該 venv。**BREAKING**（移除 src checkout 模型）。
- **新增 `install-manifest.yaml`（exact-pin）**：pin core + 各 plugin（含所需 `api_version`）+ serialwrap，
  標 public/private 與 auth；提供 `--plugins name[@ver]` 子集/覆寫；CI 加 **API 相容性閘**。
- **線上一鍵重寫**：`gh release download`（token 只走 `GH_TOKEN` env，不入 URL）→ 先裝 core wheel、
  plugin `--no-deps`、再 serialwrap；wrapper + skill。tag 無 wheel 時 fallback git+source。
- **`testpilot --update` 重寫**：脫離 git-checkout 模型，改為 re-resolve manifest → 重裝 wheel →
  **reconcile**（uninstall manifest 以外的 plugin dist，避免重複 entry-point 直接 brick CLI）。
- **`testpilot --verify-install` 重寫**：wheel-mode 用真實 `importlib.metadata` entry_points/版本，
  嘗試 `PluginLoader.load` 驗 API 相容；skill 改驗 package data 來源（不再因缺 src checkout 而誤報）。
- **舊安裝遷移**：偵測並 reconcile `pip install --user testpilot`、pipx、legacy `src` checkout 三種形態。
- **skill 改成 package data**：`skills/testpilot-normal-test` 隨 core wheel 出貨，安裝後從 `importlib.resources` 同步。
- **離線 bundle**：新增 `build-bundle.sh`（有網 Linux box 產 wheelhouse + pinned `requirements.txt` + `SHA256SUMS`）
  與 `install.sh --offline <bundle>`（驗 checksum → `pip install --no-index --find-links`）。
- **衛生與文件**：core 版號改 `VERSION`-driven dynamic；移除 dead `.gitignore` 行；CI 加 `uv build` + `gh release upload`；
  core README 設為唯一安裝權威並對齊 `hamanpaul/*` 來源。

不含（各自獨立 repo 的後續 change）：`wifi_llapi` / `brcm_fw_upgrade` 的版號收斂+release.yml 修復+依賴改名、
`serialwrap`（canonical=`hamanpaul/serialwrap`）出 wheel。

## Capabilities

### New Capabilities
- `offline-install-bundle`: 在有網的 Linux build box 產生可攜帶的單一 wheelhouse bundle（core+plugin+serialwrap+第三方相依的 closure + pinned requirements + `SHA256SUMS`），並在信任的離線 Linux 目標機以零 git 認證、零網路完成安裝。

### Modified Capabilities
- `managed-installation`: 由 git-checkout 模型改為 manifest-pinned 的 managed-venv + wheel 模型；改寫線上安裝、`--update`、`--verify-install` 的需求，新增舊安裝遷移與「installer 消費 Release wheel asset」「core 分發名為 testpilot-core 且絕不從 PyPI 解析 core」等需求。

## Impact

- **Code**: `scripts/install.sh`（重寫＋新增 `--offline`）、新增 `scripts/build-bundle.sh`、`src/testpilot/cli.py`（`_handle_update` / `--verify-install` / 舊安裝遷移）、新增 `install-manifest.yaml` 與其解析/相容閘、`pyproject.toml`（dist 改名 `testpilot-core` + `VERSION`-driven dynamic version + skill package-data）、`.gitignore`（移除 dead 行）。
- **CI**: `.github/workflows/release.yml` 加 `uv build` + `gh release upload`；新增 manifest 相容閘與 wheel 內容斷言測試（R-19）。
- **Docs**: `README.md`（安裝段落改 wheel/雙入口模型、R-16 help markers regen）、`CHANGELOG.md [Unreleased]`、設計 spec 已存在。
- **Dependencies / 認證**: 線上需 fine-grained read-only PAT（`TESTPILOT_INSTALL_TOKEN`）涵蓋 3 個 private repo；離線目標機零認證。
- **Downstream**: plugin repo 需把依賴 `testpilot` 改 `testpilot-core`（各自 change，受本 change 的 BREAKING 改名影響）。

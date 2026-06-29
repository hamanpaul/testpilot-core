# TestPilot 雙入口安裝流程設計（Dual-Entry Install Flow）

- **Date**: 2026-06-27
- **Status**: Draft（brainstorming 產出，待 writing-plans 拆 task）
- **Owner repo (hub)**: `hamanpaul/testpilot-core`
- **Spans repos**: `testpilot-core`（hub）、`wifi_llapi`、`brcm_fw_upgrade`、`serialwrap`
- **policy_version**: 1.0.5

---

## 1. 背景與問題

P4 物理拆分（`refactor(split): standalone wifi_llapi repo`）把原本內嵌在 monorepo 的 plugin
切成各自獨立的 private repo，但**一鍵安裝器沒有跟上**：

- `testpilot-core/scripts/install.sh` 第 4 步仍 editable-install
  `$MANAGED_SRC/plugins/wifi_llapi` 與 `.../brcm_fw_upgrade`
  （`scripts/install.sh:120-127`），但拆分後 core 的 `plugins/` 只剩 `_template/` 與
  `__init__.py` —— **那兩個路徑已不存在，安裝必失敗**。
- `wifi_llapi`（本體在 `hamanpaul/wifi_llapi`）與 `brcm_fw_upgrade`
  （`hamanpaul/brcm_fw_upgrade`）皆為 **private** repo。
- 目標是提供「一鍵完成」的部署體驗，參考 `serialwrap` 的 `pipx install git+...@tag`，
  允許 plugin 各自安裝、也要能一鍵全裝。

### 本設計要解決的本質
把安裝流程從「plugin 內嵌於 core checkout」重新設計成
「**core 與各 plugin 是各自獨立的可安裝 wheel 套件**」的世界，並提供**雙入口**：

1. **線上一鍵**（有網的 provisioning/開發機）：一條指令裝好 core + 選定 plugin + serialwrap。
2. **離線 bundle**（信任的 Linux lab 機，有 Python/pip、只是沒有 GitHub 認證）：
   攜帶單一 artifact，一條指令裝好全部，目標機**零 git 認證、零網路**。

---

## 2. 已驗證事實（grounding，含證據）

這些事實由並行調查 + 對抗式 red-team 對實際 repo 驗證得出，是設計的地基。

| # | 事實 | 證據 |
|---|------|------|
| F-1 | **Plugin 發現只靠 entry_points**：core `PluginLoader` 只用 `importlib.metadata.entry_points(group="testpilot.plugins")`，runtime 不掃 `plugins/` 目錄 | `src/testpilot/core/plugin_loader.py:113`、`ENTRY_POINT_GROUP="testpilot.plugins":68` |
| F-2 | **重複 entry-point 名稱會 raise**：`_normalize_entry_points` 對重名 dist 直接 `ValueError`，且 `_discover_entry_points` 在 discover/load/load_all 都會無條件呼叫它 | `plugin_loader.py:100-104`、`:110-114` |
| F-3 | **Plugin 資料是 package 相對路徑**：`plugin_root = Path(inspect.getfile(type(self))).resolve().parent`，`cases_dir`/`band-baselines.yaml`/`reports/templates` 全部相對於它 | `plugin_base.py:42-49`、`wifi_llapi/plugin.py:149-150,154` |
| F-4 | `root/plugins/<name>/cases` 只用於 **audit `--apply`** 寫入路徑，**非**正常跑測的 case 發現路徑 | `wifi_llapi/plugin.py:42-43,510-516`、docstring `:463-464` |
| F-5 | **wheel 已自帶全部資料**：`uv build --wheel` 實測產出含全部 417 個 case YAML + template `.xlsx` + `band-baselines.yaml` + `testbed.yaml.example` + `entry_points.txt`，**無需** hatch 額外設定（資料皆在 `wifi_llapi/` package dir 內） | 實測 `wifi_llapi-0.1.0-py3-none-any.whl` namelist |
| F-6 | **CI 不產任何 artifact**：兩 repo 的 `release.yml` 只跑 `gh release create --verify-tag --generate-notes`；`ci.yml` 只跑 `pytest` | `release.yml:88-101` |
| F-7 | **SDK 相容契約只在 runtime 檢查**：`PluginLoader.load` 要求 `plugin.major==API.major` 且 `API.minor>=plugin.minor`（core `API_VERSION="1.1"`、`wifi_llapi.api_version="1.1"`） | `plugin_loader.py:42`（`_check_api_compat`） |

---

## 3. 已拍板決策

| 決策 | 選擇 |
|------|------|
| 入口 | **雙入口**：線上一鍵 + 離線 bundle |
| 安裝模型 | **A：Managed venv + wheel**（沿用 `~/.local/share/testpilot/{.venv}` + wrapper，artifact 用 wheel） |
| 離線目標機 | **信任的 Linux 機、有 python3.11+pip、只缺 GitHub 認證** → 離線層輕量化 |
| 作業 OS | **Linux only（含 WSL2）** → 單一 manylinux 平台 |
| core distribution 改名 | **要改**：`testpilot` → `testpilot-core`（import 套件名仍 `testpilot`） |
| serialwrap canonical repo | **`hamanpaul/serialwrap`**：install.sh 預設 `SERIALWRAP_REPO_URL` 與 README 由 `paulc-arc` 改 `hamanpaul`；該 repo 無 `.project-policy.yml`（policy engine 外），PR 走 zh-tw |
| brcm_fw_upgrade 本輪納入 | **納入本輪**：先稽核打包，稽核過後納入 manifest「install all」預設 |

### 因決策而砍掉的範圍（YAGNI）
- ❌ 跨平台 `pip download --platform/--abi` 矩陣（單一 Linux 平台，build box 同平台 native download）
- ❌ bundle 內帶 pip/setuptools/wheel bootstrap（目標機已有 pip）
- ❌ `--require-hashes` 全有全無逐檔 hash（改成 pinned 版本 + tar 的 `SHA256SUMS` sidecar）
- ❌ 簽章 / Sigstore / PEP 740 attestation（信任機 + 受控傳輸）
- ❌ pipx（plugin 是 private + 無 CLI 入口，硬套 pipx 收益有限；managed venv 一樣給「一條指令、隔離」的 UX）
- ❌ Windows wheel

---

## 4. 架構（分層 P0–P3）

artifact 端對線上/離線**共用同一套 wheel**；差別只在「wheel 怎麼落到目標機 + 生命週期指令」。

### P0 — 共同地基（先做，否則後面解不開）

- **改名**：core `pyproject` distribution `testpilot` → `testpilot-core`；`wifi_llapi`/`brcm_fw_upgrade`
  的 `dependencies` 由 `testpilot>=…` 改為 `testpilot-core>=…`；manifest 同步。import 套件名維持 `testpilot`。
- **版號單源**：每個 repo 以 `VERSION` 為唯一來源 → hatch dynamic version
  （`[tool.hatch.version] path = "VERSION"`）；`plugin.py` 的 `version` property 改讀
  `importlib.metadata.version("wifi_llapi")`，刪掉寫死字串。core/plugin 版號彼此獨立。
- **wheel 衛生**：
  - 修兩 repo `.gitignore`：`plugins/wifi_llapi/reports/*` → `wifi_llapi/reports/*`
    （+ `!wifi_llapi/reports/templates/`、`!.gitkeep`）；core 端該行為 dead，直接移除。
  - hatch 加 explicit `include`/`exclude` allowlist，使 wheel 內容**不依賴** `.gitignore` 正確。
  - CI 斷言：built wheel 含 `entry_points.txt` 與資料檔、且**不含** `reports/<timestamp>` 跑測 bundle。
- **修好被拷壞的 plugin `release.yml`**：移除引用不存在的
  `scripts/check_release_version.py`（`release.yml:84`）與 `tests/test_release_governance.py`（`:87`），
  或補上 plugin 版本檢查（**不可**引用 core 的 `src/testpilot/__init__.py`）；安裝步驟補跨 repo token。
- **CI 產 artifact**：每個 repo 的 `release.yml` 在 tag 時 `uv build` → `gh release upload $TAG dist/*.whl`。
  `serialwrap` 也要產 wheel（目前 `setuptools` dynamic、無 wheel asset）。
- **`install-manifest.yaml`（core）**：**exact-pin** core + 每個 plugin（精確 version + **所需 api_version**）+ serialwrap；
  每個 component 標 `public/private` 與是否需 auth。操作員可用 `--plugins name@ver` 臨時覆寫單一 component（逃生口）。
  CI 加 **API 相容性閘**：對每組 `(core, plugin)` 用 `PluginLoader` 規則比對 `api_version` vs `API_VERSION`，不相容則 fail manifest PR。
  manifest bump 由 hub maintainer 負責，視為 core PATCH（flat profile）。

### P1 — 線上一鍵（managed venv + wheel）

- **重寫 `install.sh` 線上路徑**：
  1. 先 authed 抓 `install-manifest.yaml`（`gh api` at ref；解 chicken-and-egg —— 裝 core 前就要 manifest）。
  2. 建/refresh managed venv `~/.local/share/testpilot/.venv`。
  3. `gh release download`（**token 只經 `GH_TOKEN` env，絕不塞進 URL**）取得 core+plugin wheel。
  4. **先裝 core wheel，plugin 用 `--no-deps`**（core 已滿足依賴，且避免打到 PyPI），再裝 serialwrap。
  5. 寫 wrapper `~/.local/bin/testpilot`；skill 改從**安裝後的 package data**（`importlib.resources`）同步。
  6. `--plugins wifi_llapi[,brcm_fw_upgrade]` 選子集；預設依 manifest 全裝。
- **重寫 `cli.py:_handle_update`**：脫離 git checkout 模型（移除 `managed_src/.git` 存在性 gate
  `cli.py:420`、`:451`）；改成 re-resolve manifest → 重裝 wheel 進既有 venv → **reconcile**
  （pip uninstall manifest 以外的 `testpilot.plugins` dist，避免 F-2 重名 brick）。
- **wheel-mode `--verify-install`**：當無 managed checkout 時，改用真實
  `importlib.metadata.entry_points` + `importlib.metadata.version` 逐 plugin 報版號、嘗試
  `PluginLoader.load`（把 `IncompatiblePluginError` 當 FAIL）、確認 wrapper 指向 managed venv、
  serialwrap binary 可解析。skill 改成驗 package data 來源（避免目前缺 skill 直接硬 FAIL `cli.py:195`）。
- **遷移舊安裝**：偵測並 reconcile `pip install --user testpilot==0.2.0`
  （現況：`~/.local/lib/python3.12/site-packages/testpilot-0.2.0.dist-info`）、pipx serialwrap、legacy
  `~/.local/share/testpilot/src` checkout；pin/uninstall 以免 hybrid 與重複 entry-point。
- **過渡 fallback**：tag 尚無 wheel asset 時，fallback `pip install git+https://...@$VER`（source build）。

### P2 — 離線 bundle（輕量版，信任 Linux）

- **`build-bundle.sh`**（同平台 Linux box，有網）：
  1. **下載**釋出 wheel（**不重 build**，避免 hatchling 非 byte-reproducible 造成 hash 漂移）。
  2. native `pip download` 第三方 closure（`pyyaml`/`click`/`rich`/`openpyxl`/`ruamel.yaml` 等）。
  3. 合併成 `wheelhouse/` + pinned `requirements.txt`（精確版本，**免逐檔 hash**）+ skill + `testbed.yaml.example`。
  4. **硬排除** `configs/testbed.yaml`（live lab IP/帳密）與 root `*.xlsx`/`compare-*` 在地 artifact。
  5. build-box dry-run 閘：在 throwaway venv 跑 `pip install --no-index --find-links=wheelhouse -r requirements.txt` 證明可解。
  6. 打成 `testpilot-bundle-<ver>-linux-x86_64-cp311.tar.gz` + 旁附 `SHA256SUMS`。
- **`install.sh --offline <bundle>`**：
  1. 驗 `SHA256SUMS`（sidecar / 釋出頁取得）→ 解壓。
  2. 斷言 `sys.version_info` 對得上 bundle metadata（不符 fail-fast，給清楚訊息）。
  3. 建 venv → `pip install --no-index --find-links=wheelhouse -r requirements.txt`。
  4. wrapper + skill → 跑 wheel-mode `--verify-install` 當 post-install 閘。

### P3 — 強化（輕量，因信任 Linux）

- 保留：bundle `SHA256SUMS`；線上路改 **pinned tag（不 `@main`）**；CI **不把跨 repo PAT 給 PR 跑**
  （改 GitHub App token / environment gating / PR 對 stub core 測）；一頁 **PAT runbook**
  （單一 env 名 `TESTPILOT_INSTALL_TOKEN`、fine-grained read-only contents 限那 3 個 private repo、輪替負責人）。
- 砍掉：簽章/Sigstore/attestation、平台矩陣。

---

## 5. Red-team blocker → 設計如何處理

| Blocker（已驗證） | 設計處理 |
|---|---|
| **PyPI 撞名**：public 已有無關 `testpilot 0.2.9`，plugin 依賴 `testpilot>=0.3.0,<1.0` 會打到 PyPI（`wifi pyproject:7`） | P0 改名 `testpilot-core` + 線上 plugin 一律 `--no-deps`、離線一律 `--no-index` |
| **版號四源不一致**：`VERSION=0.3.0`、`pyproject:3=0.1.0`、`plugin.py:146="0.1.0"`、`__init__` 空 | P0 hatch dynamic from `VERSION` + `plugin.version` 讀 metadata |
| **`--update` 死在 git 模型**（`cli.py:420,451`） | P1 重寫 `_handle_update` |
| **重複 entry-point brick 整個 CLI**（`plugin_loader.py:100-104`） | P1 installer reconcile（uninstall 落單/重名 dist）；dist 名凍結不改 |
| **`--verify-install` 在 wheel 世界幾乎沒驗到東西 + 缺 skill 硬 FAIL**（`cli.py:149-151,195,326-327`） | P1 wheel-mode verify-install + skill 改 package data |
| **現有安裝其實是 pip --user 0.2.0**（非 src/.venv） | P1 遷移/reconcile 三種舊形態 |
| **離線 C-ext/bootstrap/hash 痛點** | 由決策瘦身：單平台 native download、目標機自帶 pip、checksum 取代逐檔 hash |
| **serialwrap 無 wheel + verify 當硬性檢查** | P0 serialwrap 出 wheel（mandatory in bundle；預設**不**含 `[redos]`/google-re2 C-ext extra） |
| **PAT 塞 URL 外洩**（`wifi ci.yml:36` 既有 pattern） | P1 只用 `GH_TOKEN` env + `gh release download`；clone 後 strip credential；P3 runbook |
| **bundle hash 與 wheel 同包 tar → 對竄改零防護** | P2 detached `SHA256SUMS` sidecar（信任機足夠；不上簽章） |
| **plugin `release.yml` 被拷壞**（引用不存在的 `check_release_version.py`/`test_release_governance.py`） | P0 先修 release.yml 再加 build |
| **兩份 README 指向死的 `paulc-arc/testpilot` URL + wifi README 寫死 `file:///home/paul_chen/...`** | Phase D：core README 設唯一權威、wifi README 縮成「我是 plugin」、清死 URL/個人路徑 |
| **manifest 重新引入 split 想拿掉的耦合** | manifest 契約明定：exact-pin、hub maintainer bump、bump 視為 core PATCH（flat profile）；`--plugins name@ver` 可覆寫 |

---

## 6. 跨 4 repo 分工 + 釋出 DAG

```
協調 issue（追蹤順序；各 repo PR body 用 Closes #N，R-17）
 │
 ├─ Phase A 各 repo 修地基（可並行）
 │    testpilot-core : 改名 testpilot-core + .gitignore 清 dead 行 + version dynamic
 │    wifi_llapi     : 版號收斂 + .gitignore 修正 + wheel allowlist + 修 release.yml + 依賴改 testpilot-core
 │    brcm_fw_upgrade: 先稽核打包(dist名/version/entry-point/api_version/韌體blob 是否進 wheel) 後同 wifi
 │
 ├─ Phase B 各 plugin/serialwrap 先發出「帶 wheel asset」的 release   ← core 必須靠這個才能 pin
 │
 ├─ Phase C testpilot-core hub（等 B 的 wheel 存在後）
 │    install-manifest.yaml + API 相容閘
 │    install.sh（線上 + 離線）+ build-bundle.sh
 │    _handle_update 重寫 + wheel-mode verify-install + 舊安裝遷移 + skill→package data
 │    core README 設唯一安裝權威 + R-16 help markers regen
 │
 └─ Phase D 收尾
      wifi/brcm README 縮成 plugin 說明、清死 URL/個人路徑（R-18/R-22）
      serialwrap：以 hamanpaul/serialwrap 為準，install.sh 預設 + README 由 paulc-arc 改 hamanpaul
      PAT runbook、CI secret 強化
```

每個 repo：各自 `feature/<slug>` 分支（off non-main）+ `CHANGELOG.md [Unreleased]` entry（R-09）+
PR template checklist + zh-tw（`serialwrap` 若 canonical 為 `paulc-arc` 走 en_US）。

---

## 7. Roadmap（Phase A–D + 每個 PR 驗收條件）

> 以下為實作藍圖；writing-plans 階段再把每個 PR 拆成逐步 task。

### Phase A — 地基（並行）

**A1. core PR — `feature/dist-rename-and-hygiene`**
- 內容：`pyproject` distribution → `testpilot-core`；`VERSION` 驅動 hatch dynamic version；`.gitignore` 移除 dead `plugins/wifi_llapi/reports/*`。
- 驗收：`uv build` 出 `testpilot_core-<VERSION>-py3-none-any.whl`；`pytest -q` 全綠；`python -m policy_check --repo .` 無 failure；`testpilot --version` 與 `VERSION` 一致。

**A2. wifi_llapi PR — `feature/wheel-release-readiness`**
- 內容：版號收斂（`VERSION` 單源 + hatch dynamic + `plugin.version` 讀 metadata）；依賴改 `testpilot-core>=…`；`.gitignore` 修 `wifi_llapi/reports/*`；hatch include/exclude allowlist；修好 `release.yml`（移除/替換不存在的檢查、補 `TESTPILOT_INSTALL_TOKEN`）。
- 驗收：`uv build` 出 wheel 且含 entry_points + 417 cases + template，**不含** `reports/<ts>` bundle（CI 斷言）；`release.yml` dry-run tag 成功；`pytest -q` 全綠。

**A3. brcm_fw_upgrade PR — `feature/wheel-release-readiness`**（**本輪納入**）
- 前置：**先稽核**其打包（dist 名、version 來源、`testpilot.plugins` entry-point、`api_version`、韌體 blob/secret 是否誤入 wheel）。
- 內容/驗收：同 A2（依稽核結果調整）。稽核過後**納入 manifest「install all」預設**；若稽核發現阻斷性打包問題（如韌體 blob 過大、site-packages 路徑假設），回報並於 spec 補對策後再納。

### Phase B — 先發 plugin/serialwrap wheel release

**B1.** cut `wifi_llapi`、`brcm_fw_upgrade`（A3 稽核過）、`serialwrap`（canonical = `hamanpaul/serialwrap`）的第一個帶 wheel asset 的 release。
- 驗收：`gh release view <tag>` 看得到 `*.whl` asset；在乾淨 venv `pip install --no-index --find-links` 該 wheel 可裝且 `testpilot list-plugins` 認得。

### Phase C — core hub installer

**C1. core PR — `feature/install-flow-dual-entry`**（本 spec 主體）
- 內容：`install-manifest.yaml` + API 相容閘（CI）；`install.sh` 線上路徑重寫（manifest 預抓 / `gh release download` / core-first + plugin `--no-deps` / serialwrap / wrapper / skill from package data / `--plugins`）；`build-bundle.sh`；`install.sh --offline`；`_handle_update` 重寫；wheel-mode `--verify-install`；舊安裝遷移；core README 設唯一安裝權威 + R-16 markers。
- 驗收：
  - 線上：在乾淨容器 `TESTPILOT_INSTALL_TOKEN=… bash scripts/install.sh` → `testpilot --verify-install` 全綠、`testpilot list-cases wifi_llapi` 有 case。
  - 離線：`build-bundle.sh` 產出 tar + `SHA256SUMS`；在**斷網** venv `bash install.sh --offline <bundle>` → verify-install 全綠。
  - 重跑 install.sh idempotent（無重複 entry-point error）；`--update` 可升降級且 reconcile 落單 plugin。
  - token 不出現在 stdout/stderr/log（加測試斷言）。
  - `python -m policy_check --repo .` 無 failure；CI 跑新測試（R-19）。

### Phase D — 收尾

**D1. wifi_llapi / brcm PR — `feature/readme-plugin-reduction`**：README 縮成「我是 plugin，安裝見 testpilot-core」，刪重複 managed-install/curl/`file://` 內容與 dead `scripts/install.sh` 樹引用（R-18/R-22）。
**D2. serialwrap**：canonical = **`hamanpaul/serialwrap`**。把 install.sh 預設 `SERIALWRAP_REPO_URL`、兩份 README 連結、manifest 由 `paulc-arc` 對齊到 `hamanpaul`；serialwrap 出 wheel（`setuptools` build，pin `setuptools>=62.3` 確保巢狀 `skill/**` package-data 進 wheel）；PR 走 zh-tw。
**D3. core PR — `feature/install-security-hardening`**：pinned tag（不 `@main`）、CI 不把 PAT 給 PR 跑、PAT runbook 文件。

---

## 8. 明確排除 / 延後（Out of scope）

- Windows wheel / 跨平台矩陣（決策：Linux only）。
- 簽章 / Sigstore / PEP 740 attestation（決策：信任 Linux 機）。
- bundle 內帶 pip/setuptools/wheel bootstrap、`--require-hashes` 逐檔 hash（決策：目標機有 pip）。
- pipx 安裝模型（選 A：managed venv）。
- PyPI 正式發佈（現行 publication scope = GitHub tag + Release asset）。
- `testpilot plugins add/remove` first-class 子指令（C 層 UX，列為 A 之後可選打磨）。

---

## 9. 風險與待澄清

- **R-1 brcm_fw_upgrade 打包待稽核（本輪納入）**：已決定本輪納入，但其打包形狀（dist 名、version、entry-point、api_version、韌體 blob 是否誤入 wheel、site-packages 路徑假設）尚未驗證；Phase A3 先稽核，稽核過才納 manifest「install all」預設，發現阻斷性問題則回報補對策。
- **R-2 serialwrap repo 身分（已決）**：canonical = `hamanpaul/serialwrap`。install.sh 預設與兩份 README 目前寫 `paulc-arc/serialwrap`，需於 D2 對齊到 hamanpaul。serialwrap 無 `.project-policy.yml`（policy engine 外），PR 走 zh-tw。
- **R-3 manifest 釋出耦合**：exact-pin 讓 plugin hotfix 需 core re-release 才對 operator 生效；採「manifest bump = core PATCH（flat profile）」並允許 `--plugins name@ver` 覆寫以緩解。
- **R-4 跨 repo 釋出順序**：B 必須在 C 之前（plugin wheel 先存在 core 才能 pin/抓）；用協調 issue 強制順序。
- **R-5 首發過渡**：既有 tag 無 wheel asset，installer 需 git+source fallback，直到 CI build+upload 落地並 cut 新 tag。

---

## 10. 測試 / 驗證策略

- **單元**：manifest 解析/驗證；API 相容閘；wheel-mode verify-install 對 `importlib.metadata` 的行為。
- **打包**：CI `uv build` 後斷言 wheel 內含 `entry_points.txt` + 資料檔、不含跑測 bundle。
- **整合（容器）**：乾淨容器跑線上 install.sh → `verify-install` / `list-cases`；斷網 venv 跑 `--offline` bundle → `verify-install`。
- **冪等/升級**：重跑 install.sh、`--update` 升降級、移除 manifest 中 plugin 後 reconcile 不殘留 entry-point。
- **安全**：斷言 token 不入 stdout/stderr/log；`set -x` 不覆蓋帶 token 段落。

---

## 11. 每 repo policy checklist（landing 時）

對每個觸及 repo（`testpilot-core` / `wifi_llapi` / `brcm_fw_upgrade` / `serialwrap`）：

- [ ] 在 `feature/<slug>` 分支（off non-main）
- [ ] `CHANGELOG.md [Unreleased]` 有 entry（或標 `skip-changelog` + 理由）
- [ ] PR template checklist 全勾
- [ ] `uv run pytest -q` 全綠
- [ ] `python -m policy_check --repo .` 無 failure
- [ ] R-17：PR body `Closes #N`（指向協調 issue）
- [ ] R-18：README/docs 與本次介面變動同步（或上 `policy-exempt:docs-sync`）
- [ ] R-19：新增測試套件已被 CI 執行
- [ ] R-16：CLI help markers（`--update`/`--verify-install`）若變動已 regen
- [ ] 語言：`hamanpaul/*` 用 zh-tw；`paulc-arc/*` 用 en_US

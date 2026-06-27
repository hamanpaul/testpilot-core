# TestPilot

> **[English](#english)** ｜ **[繁體中文](#繁體中文)**

---

## Install

This README is the canonical install reference. For online install (managed venv + pinned wheels), see [Quick Start](#quick-start). For offline environments or update procedures, see [Managed Install and Update](#managed-install-and-update). After any install or update, run `testpilot --verify-install` to confirm health.

## Usage

`testpilot` is the host runtime; test capabilities are provided by plugins.
Use `testpilot list-plugins` to see installed plugins and `testpilot run <plugin>`
to drive them.

## Version

The canonical project version is `VERSION`; release tags use `vX.Y.Z`.

---

## English

Plugin-based test automation framework for embedded device verification (prplOS / OpenWrt).

This repository is **TestPilot core**: the deterministic verdict kernel, the
plugin SDK (`testpilot.api`), the CLI host, transports, schema, and reporting.
It ships the plugin scaffold under `plugins/_template/` but no concrete test
plugins. Real plugins (for example `wifi_llapi` and `brcm_fw_upgrade`) live in
their own repositories and register themselves through the
`testpilot.plugins` entry-point group.

### Overview

TestPilot is a plugin-based test automation framework for prplOS / OpenWrt embedded devices. The architecture splits into two planes:

- **Deterministic verdict kernel** — test execution, evidence collection, pass/fail verdicts, and report projection.
- **Copilot SDK control plane** — per-case session foundation, lifecycle hooks, advisory audit, safe remediation, and extension surfaces such as custom agents / skills / selective MCP.

Core principle: **the Copilot SDK handles the control plane; it does NOT decide the final verdict.**

Current landed control-plane subset today:

- per-case runner selection with `selection_trace`
- best-effort per-case Copilot session foundation
- lifecycle hook dispatch (`pre_case`, `post_case`, `pre_step`, `post_step`, `on_failure`, `on_retry`)
- advisory collection plus safe-environment remediation between retry attempts

Custom agents / skills / MCP remain extension surfaces in the current codebase rather than default hot-path runtime wiring.

### Prerequisites

- **Python 3.11+**
- **git**
- **[uv](https://docs.astral.sh/uv/)** — Python package manager, preferred by the installer
- **[serialwrap](https://github.com/paulc-arc/serialwrap)** — UART serial multiplexer for DUT / STA communication; managed installs install/update it automatically

Developer checkouts that manage serialwrap manually can still set the binary path via environment variable:

```bash
export SERIALWRAP_BIN=/path/to/serialwrap
```

Or add to `configs/testbed.yaml`:

```yaml
testbed:
  serialwrap_binary: /path/to/serialwrap
```

> Resolution order: `SERIALWRAP_BIN` env var → `testbed.yaml` config → error exit.

### Quick Start

**Online one-click install** (requires a fine-grained read-only PAT with `contents: read`
for `hamanpaul/testpilot-core` and all plugin repos):

```bash
TESTPILOT_INSTALL_TOKEN=<fine-grained read-only PAT> bash scripts/install.sh
testpilot --verify-install
testpilot list-plugins
```

Install only a subset of plugins with `--plugins`:

```bash
TESTPILOT_INSTALL_TOKEN=<PAT> bash scripts/install.sh --plugins wifi_llapi
```

Once installed, list and run plugins:

```bash
testpilot list-plugins
testpilot list-cases <plugin>
testpilot run <plugin>
```

> When a plugin context is resolved, the CLI auto-stages
> `plugins/<plugin>/testbed.yaml.example` into `configs/testbed.yaml`, so each run
> starts from that plugin's shipped testbed shape with no leakage between
> plugins. Edit `configs/testbed.yaml` to match your lab — note that switching
> to a different plugin will overwrite it.

### Managed Install and Update

The supported QC/TEST install uses a managed venv with pinned wheels (no git checkout):

```bash
~/.local/share/testpilot/.venv   # managed runtime virtualenv
~/.local/bin/testpilot           # wrapper, no activation required
~/.agents/skills/testpilot-normal-test
```

**Online install** — downloads wheels via `gh release download` using a fine-grained PAT:

```bash
TESTPILOT_INSTALL_TOKEN=<fine-grained read-only PAT> bash scripts/install.sh
```

**Offline install** — build a bundle on a networked Linux box with `scripts/build-bundle.sh`,
then transfer and install on the air-gapped machine:

```bash
# Build on a networked machine:
bash scripts/build-bundle.sh

# Install on the offline machine (verifies SHA256SUMS, installs with --no-index):
bash scripts/install.sh --offline testpilot-bundle-<ver>-linux-<arch>-cp<XY>.tar.gz
```

**Update and verify:**

```bash
testpilot --update            # re-resolves manifest, reinstalls pinned wheels, reconciles plugins
testpilot --verify-install    # report install health
```

### CLI Entry Points

Use the installed `testpilot` command for normal operation. Developer checkouts can
still use `python -m testpilot.cli` when debugging the repository.

Plugin-owned CLI commands are registered from installed plugin packages when
`testpilot.cli` is imported. `--root <path>` selects the runtime project root for
cases/configs/reports; it does not dynamically replace the registered plugin CLI
surface with commands from `<path>/plugins`.

The core host commands are:

```bash
testpilot --version
testpilot list-plugins
testpilot list-cases <plugin>
testpilot run <plugin>
```

<!-- testpilot-help:start -->
<!-- BEGIN: cli-help marker="testpilot-help" -->
Usage: testpilot [OPTIONS] COMMAND [ARGS]...

  TestPilot — plugin-based test automation for embedded devices.

Options:
  --version         Show version and exit.
  -v, --verbose     Enable debug logging.
  --root DIRECTORY  Project root directory.
  --azure           Use Azure OpenAI API. Prompts for endpoint, key, and model
                    interactively.
  --update REF      Reinstall and reconcile the managed wheel install from its
                    pinned manifest, then exit. REF is accepted but cross-
                    version update is not yet implemented; the currently-
                    pinned set is reinstalled.
  --verify-install  Report managed install health and exit.
  --help            Show this message and exit.

Commands:
  install-doctor  Check manifest plugin API-compat against installed core...
  list-cases      List test cases for a plugin.
  list-plugins    List available test plugins.
  run             Run tests for a plugin.
<!-- END: cli-help marker="testpilot-help" -->
<!-- testpilot-help:end -->

<!-- testpilot-update-help:start -->
<!-- BEGIN: cli-help marker="testpilot-update-help" -->
Usage: testpilot [OPTIONS] COMMAND [ARGS]...

  TestPilot — plugin-based test automation for embedded devices.

Options:
  --version         Show version and exit.
  -v, --verbose     Enable debug logging.
  --root DIRECTORY  Project root directory.
  --azure           Use Azure OpenAI API. Prompts for endpoint, key, and model
                    interactively.
  --update REF      Reinstall and reconcile the managed wheel install from its
                    pinned manifest, then exit. REF is accepted but cross-
                    version update is not yet implemented; the currently-
                    pinned set is reinstalled.
  --verify-install  Report managed install health and exit.
  --help            Show this message and exit.

Commands:
  install-doctor  Check manifest plugin API-compat against installed core...
  list-cases      List test cases for a plugin.
  list-plugins    List available test plugins.
  run             Run tests for a plugin.
<!-- END: cli-help marker="testpilot-update-help" -->
<!-- testpilot-update-help:end -->

Repository skills for agent-assisted workflows live under `skills/`.

### Azure OpenAI (BYOK)

The `--azure` flag enables Bring-Your-Own-Key Azure OpenAI authentication.
It interactively prompts for endpoint, API key, and model, then exports the
standard `COPILOT_PROVIDER_*` environment variables for the run. API keys and
endpoints are never committed to version control; supply secrets through
environment variables or your shell profile.

```bash
testpilot --azure list-plugins
```

```bash
# Optional (default: 2024-10-21):
export COPILOT_PROVIDER_AZURE_API_VERSION=2024-10-21
```

### Writing a Plugin

Copy the SDK scaffold and register it from your plugin package:

```bash
cp -r plugins/_template plugins/my_plugin
```

```toml
[project.entry-points."testpilot.plugins"]
my_plugin = "plugins.my_plugin.plugin:Plugin"
```

```bash
uv pip install -e .
testpilot list-plugins
```

Implement the `PluginBase` contract (declare `api_version`, `name`,
`discover_cases()`, `execute_step()`, `evaluate()`; override optional hooks such
as `setup_env()`, `verify_env()`, `teardown()`, `create_reporter()`,
`create_runner()`, and `register_cli()` as needed). Plugins import the public
SDK surface from `testpilot.api`; they must not reach into `testpilot.core`,
`testpilot.schema`, `testpilot.reporting`, `testpilot.transport`, or
`testpilot.runtime` internals. See `plugins/_template/README.md` for the full
contract and optional hook table.

### Project Structure

```text
src/testpilot/
  api/        # public plugin SDK surface (testpilot.api)
  core/       # orchestrator, plugin_base, plugin_loader, testbed_config
  reporting/  # reporter and report helpers
  transport/  # transport abstractions
  schema/     # YAML case schema validation
  runtime/    # run backend
plugins/
  _template/  # plugin SDK scaffold (not discoverable on its own)
configs/      # operator-local effective testbed.yaml (auto-staged by CLI; git-ignored)
docs/         # plan, todos, phase docs
scripts/      # utility scripts (install, policy_cli_help, gen_cases)
skills/       # repository agent skills
tests/        # core test suite
```

### Versioning and Release

The canonical project version lives in `VERSION`; `pyproject.toml` and
`src/testpilot/__init__.py` mirror it and must stay identical. Release tags use
Semantic Versioning `vX.Y.Z`. User-facing pull requests should update
`CHANGELOG.md` under `Unreleased`, or explicitly record why no changelog entry
is needed.

---

## 繁體中文

針對嵌入式裝置驗證（prplOS / OpenWrt）的 plugin 化測試自動化框架。

本 repo 是 **TestPilot core**：deterministic verdict kernel、plugin SDK
（`testpilot.api`）、CLI host、transport、schema 與 reporting。它內含
`plugins/_template/` plugin 骨架，但不含任何具體測試 plugin。真正的 plugin
（例如 `wifi_llapi`、`brcm_fw_upgrade`）各自存在於獨立 repo，透過
`testpilot.plugins` entry-point group 自我註冊。

### 概觀

TestPilot 是針對 prplOS / OpenWrt 嵌入式裝置的 plugin 化測試自動化框架，架構分為兩個平面：

- **Deterministic verdict kernel** — 測試執行、證據蒐集、pass/fail 判定與報表投影。
- **Copilot SDK control plane** — per-case session foundation、lifecycle hooks、advisory audit、safe remediation，以及 custom agents / skills / 選擇性 MCP 等擴充面。

核心原則：**Copilot SDK 負責 control plane；它不決定最終 verdict。**

### 前置需求

- **Python 3.11+**
- **git**
- **[uv](https://docs.astral.sh/uv/)** — 安裝器優先採用的 Python 套件管理器
- **[serialwrap](https://github.com/paulc-arc/serialwrap)** — DUT / STA 通訊用的 UART serial multiplexer；managed install 會自動安裝/更新

手動管理 serialwrap 的開發者 checkout 可用環境變數指定路徑：

```bash
export SERIALWRAP_BIN=/path/to/serialwrap
```

> 解析順序：`SERIALWRAP_BIN` 環境變數 → `testbed.yaml` 設定 → 失敗結束。

### 快速開始

**線上一鍵安裝**（需要 fine-grained read-only PAT，具備 `hamanpaul/testpilot-core`
及所有 plugin repo 的 `contents: read` 權限）：

```bash
TESTPILOT_INSTALL_TOKEN=<fine-grained read-only PAT> bash scripts/install.sh
testpilot --verify-install
testpilot list-plugins
```

透過 `--plugins` 只安裝部分 plugin：

```bash
TESTPILOT_INSTALL_TOKEN=<PAT> bash scripts/install.sh --plugins wifi_llapi
```

安裝後，列出並執行 plugin：

```bash
testpilot list-plugins
testpilot list-cases <plugin>
testpilot run <plugin>
```

### Managed Install 與 Update

支援的 QC/TEST 安裝採用 managed venv 加 pinned wheels（不再使用 git checkout）：

```bash
~/.local/share/testpilot/.venv   # managed runtime virtualenv
~/.local/bin/testpilot           # wrapper，免 activate
~/.agents/skills/testpilot-normal-test
```

**線上安裝**：

```bash
TESTPILOT_INSTALL_TOKEN=<fine-grained read-only PAT> bash scripts/install.sh
```

**離線安裝**（先在有網路的 Linux 機器以 `scripts/build-bundle.sh` 建置 bundle，
再傳至目標機器）：

```bash
# 有網路機器上建置：
bash scripts/build-bundle.sh

# 離線機器上安裝（驗證 SHA256SUMS，以 --no-index 安裝）：
bash scripts/install.sh --offline testpilot-bundle-<ver>-linux-<arch>-cp<XY>.tar.gz
```

**更新與驗證：**

```bash
testpilot --update            # 重解析 manifest、重裝 pinned wheels、同步 plugin
testpilot --verify-install    # 回報安裝狀態
```

### CLI 進入點

正常操作使用已安裝的 `testpilot` 指令；開發者 checkout 在除錯 repo 時仍可使用
`python -m testpilot.cli`。Plugin 專屬的 CLI 指令是在 import `testpilot.cli`
時由已安裝的 plugin 套件註冊。`--root <path>` 只選擇 runtime project root
（cases/configs/reports），不會用 `<path>/plugins` 的指令動態替換已註冊的
plugin CLI 介面。

核心 host 指令：

```bash
testpilot --version
testpilot list-plugins
testpilot list-cases <plugin>
testpilot run <plugin>
```

### Azure OpenAI（BYOK）

`--azure` flag 啟用 Bring-Your-Own-Key 的 Azure OpenAI 認證，會互動式詢問
endpoint、API key 與 model，再以標準 `COPILOT_PROVIDER_*` 環境變數提供給該次
執行。API key 與 endpoint 不得提交版本控制；secrets 一律透過環境變數或 shell
profile 注入。

```bash
testpilot --azure list-plugins
```

### 撰寫 Plugin

複製 SDK 骨架並從你的 plugin 套件註冊：

```bash
cp -r plugins/_template plugins/my_plugin
```

```toml
[project.entry-points."testpilot.plugins"]
my_plugin = "plugins.my_plugin.plugin:Plugin"
```

```bash
uv pip install -e .
testpilot list-plugins
```

實作 `PluginBase` 契約（宣告 `api_version`、`name`、`discover_cases()`、
`execute_step()`、`evaluate()`；視需要覆寫 `setup_env()`、`verify_env()`、
`teardown()`、`create_reporter()`、`create_runner()`、`register_cli()` 等選用
hook）。Plugin 從 `testpilot.api` 匯入公開 SDK 介面，不得直接 reach 進
`testpilot.core` / `schema` / `reporting` / `transport` / `runtime` 內部。完整
契約與選用 hook 對照表見 `plugins/_template/README.md`。

### 版本與發布

canonical 版本位於 `VERSION`；`pyproject.toml` 與
`src/testpilot/__init__.py` 為鏡像，必須一致。release tag 採 Semantic
Versioning `vX.Y.Z`。對外 PR 應更新 `CHANGELOG.md` 的 `Unreleased`，或明確記錄
為何不需 changelog entry。

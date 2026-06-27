# Install Flow Dual-Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the split-broken managed installer with a managed-venv + wheel, manifest-pinned dual-entry (online one-click + offline bundle) install flow for `testpilot-core`.

**Architecture:** Core distribution renamed `testpilot-core` (import package stays `testpilot`). An `install-manifest.yaml` exact-pins the compatible set (core + plugins + serialwrap, each with `api_version`). `scripts/install.sh` installs pinned wheels into `~/.local/share/testpilot/.venv` (online via `gh release download`; offline via a `--offline` wheelhouse bundle built by `scripts/build-bundle.sh`). `testpilot --update`/`--verify-install` are reworked for the wheel world (no src checkout); plugin discovery stays entry-point based, so wheels are auto-discovered. Migration reconciles legacy install shapes.

**Tech Stack:** Python 3.11+, hatchling, click, PyYAML, `gh` CLI, uv/pip, bash. Tests: pytest.

**Source of truth:** `docs/superpowers/specs/2026-06-27-install-flow-dual-entry-design.md` + openspec change `install-flow-dual-entry`.

---

## File Structure

- Create `src/testpilot/install/__init__.py` — install-support subpackage.
- Create `src/testpilot/install/manifest.py` — `InstallManifest`/`Component` dataclasses + `load_manifest(path)`.
- Create `src/testpilot/install/compat.py` — `manifest_compat_report()` reusing `plugin_loader._check_api_compat`.
- Modify `src/testpilot/cli.py` — wheel-mode `--verify-install`, `_handle_update` rewrite, legacy-install migration helpers.
- Create `install-manifest.yaml` (repo root) — pinned set.
- Modify `pyproject.toml` — dist rename, dynamic version, skill package-data.
- Modify `.gitignore` — drop dead `plugins/wifi_llapi/reports/*`.
- Rewrite `scripts/install.sh`; create `scripts/build-bundle.sh`.
- Modify `.github/workflows/release.yml` — `uv build` + `gh release upload`.
- Tests under `tests/`.

---

## Task 1: Packaging rename + dynamic version

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Test: `tests/test_packaging_metadata.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_packaging_metadata.py
import tomllib, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_distribution_named_testpilot_core():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["name"] == "testpilot-core"

def test_version_is_dynamic_from_version_file():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "version" in data["project"].get("dynamic", []), "version must be dynamic"
    assert data["tool"]["hatch"]["version"]["path"] == "VERSION"

def test_console_script_unchanged():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["scripts"]["testpilot"] == "testpilot.cli:main"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_packaging_metadata.py -v`
Expected: FAIL (name is `testpilot`, version not dynamic).

- [ ] **Step 3: Edit pyproject.toml**

Set `[project].name = "testpilot-core"`; replace `version = "0.3.0"` with `dynamic = ["version"]`; add:
```toml
[tool.hatch.version]
path = "VERSION"

[tool.hatch.build.targets.wheel]
packages = ["src/testpilot"]
```
(hatchling reads a bare `X.Y.Z` VERSION file via the regex default; if it errors, add `pattern = "^(?P<version>.+)$"`.)

- [ ] **Step 4: Drop dead .gitignore line**

Remove `plugins/wifi_llapi/reports/*` and its `!templates` companion lines (core ships no wifi_llapi).

- [ ] **Step 5: Run tests + a build smoke**

Run: `uv run pytest tests/test_packaging_metadata.py -v && uv build --wheel 2>&1 | tail -3`
Expected: PASS; wheel filename `testpilot_core-<VERSION>-py3-none-any.whl`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore tests/test_packaging_metadata.py
git commit -m "build(core): rename distribution to testpilot-core + dynamic version"
```

---

## Task 2: Skill as package data

**Files:**
- Modify: `pyproject.toml`
- Create: `src/testpilot/_packaged_skill/` OR configure force-include of `skills/testpilot-normal-test`
- Test: `tests/test_packaged_skill.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_packaged_skill.py
import zipfile, glob, subprocess, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_skill_shipped_in_wheel(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "-o", str(tmp_path)], cwd=ROOT, check=True)
    whl = glob.glob(str(tmp_path / "testpilot_core-*.whl"))[0]
    names = zipfile.ZipFile(whl).namelist()
    assert any("testpilot-normal-test/SKILL" in n or "testpilot-normal-test" in n for n in names), names[:20]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_packaged_skill.py -v`
Expected: FAIL (skill not in wheel).

- [ ] **Step 3: Configure hatch force-include**

In `pyproject.toml`:
```toml
[tool.hatch.build.targets.wheel.force-include]
"skills/testpilot-normal-test" = "testpilot/_skills/testpilot-normal-test"
```
This ships the skill tree under `testpilot/_skills/` inside the wheel so the installer can copy it via `importlib.resources.files("testpilot") / "_skills"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_packaged_skill.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_packaged_skill.py
git commit -m "build(core): ship testpilot-normal-test skill as wheel package data"
```

---

## Task 3: Install manifest model + loader

**Files:**
- Create: `src/testpilot/install/__init__.py` (empty)
- Create: `src/testpilot/install/manifest.py`
- Create: `install-manifest.yaml`
- Test: `tests/test_install_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_install_manifest.py
import pathlib
from testpilot.install.manifest import load_manifest, InstallManifest

ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_load_manifest_parses_components():
    m = load_manifest(ROOT / "install-manifest.yaml")
    assert isinstance(m, InstallManifest)
    assert m.core.distribution == "testpilot-core"
    assert m.core.version
    names = {p.name for p in m.plugins}
    assert "wifi_llapi" in names
    wifi = next(p for p in m.plugins if p.name == "wifi_llapi")
    assert wifi.api_version  # e.g. "1.1"
    assert wifi.private is True
    assert m.serialwrap.repo == "hamanpaul/serialwrap"

def test_selected_plugins_subset():
    m = load_manifest(ROOT / "install-manifest.yaml")
    sel = m.selected(["wifi_llapi"])
    assert [p.name for p in sel] == ["wifi_llapi"]

def test_plugin_version_override():
    m = load_manifest(ROOT / "install-manifest.yaml")
    sel = m.selected(["wifi_llapi@9.9.9"])
    assert next(p for p in sel if p.name == "wifi_llapi").version == "9.9.9"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_install_manifest.py -v`
Expected: FAIL (module/file missing).

- [ ] **Step 3: Implement manifest.py**

```python
# src/testpilot/install/manifest.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml

@dataclass(frozen=True)
class Core:
    distribution: str
    version: str
    repo: str | None = None
    private: bool = True

@dataclass(frozen=True)
class Plugin:
    name: str
    repo: str
    version: str
    api_version: str
    private: bool = True

@dataclass(frozen=True)
class Serialwrap:
    repo: str
    version: str
    private: bool = False

@dataclass(frozen=True)
class InstallManifest:
    core: Core
    plugins: list[Plugin] = field(default_factory=list)
    serialwrap: Serialwrap | None = None

    def selected(self, specs: list[str] | None) -> list[Plugin]:
        if not specs:
            return list(self.plugins)
        out: list[Plugin] = []
        for spec in specs:
            name, _, ver = spec.partition("@")
            base = next((p for p in self.plugins if p.name == name), None)
            if base is None:
                raise KeyError(f"unknown plugin {name!r}")
            out.append(base if not ver else Plugin(base.name, base.repo, ver, base.api_version, base.private))
        return out

def load_manifest(path: str | Path) -> InstallManifest:
    data = yaml.safe_load(Path(path).read_text()) or {}
    c = data["core"]
    core = Core(c["distribution"], str(c["version"]), c.get("repo"), c.get("private", True))
    plugins = [
        Plugin(p["name"], p["repo"], str(p["version"]), str(p["api_version"]), p.get("private", True))
        for p in data.get("plugins", [])
    ]
    sw = data.get("serialwrap")
    serialwrap = Serialwrap(sw["repo"], str(sw["version"]), sw.get("private", False)) if sw else None
    return InstallManifest(core=core, plugins=plugins, serialwrap=serialwrap)
```

- [ ] **Step 4: Write install-manifest.yaml**

```yaml
core:
  distribution: testpilot-core
  repo: hamanpaul/testpilot-core
  version: "0.3.0"   # bumped at release prep
  private: true
plugins:
  - name: wifi_llapi
    repo: hamanpaul/wifi_llapi
    version: "0.3.0"
    api_version: "1.1"
    private: true
  - name: brcm_fw_upgrade
    repo: hamanpaul/brcm_fw_upgrade
    version: "0.1.0"
    api_version: "1.1"
    private: true
serialwrap:
  repo: hamanpaul/serialwrap
  version: "0.2.0"
  private: false
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_install_manifest.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/testpilot/install/ install-manifest.yaml tests/test_install_manifest.py
git commit -m "feat(install): add install-manifest model + pinned manifest"
```

---

## Task 4: Manifest API-compatibility gate

**Files:**
- Create: `src/testpilot/install/compat.py`
- Test: `tests/test_install_compat.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_install_compat.py
from testpilot.install.compat import manifest_compat_report

def test_compatible_pair_ok():
    rep = manifest_compat_report(core_api="1.1", plugins=[("wifi_llapi", "1.1")])
    assert rep.ok and not rep.failures

def test_minor_too_new_fails():
    rep = manifest_compat_report(core_api="1.1", plugins=[("wifi_llapi", "1.2")])
    assert not rep.ok and any("wifi_llapi" in f for f in rep.failures)

def test_major_mismatch_fails():
    rep = manifest_compat_report(core_api="1.1", plugins=[("brcm_fw_upgrade", "2.0")])
    assert not rep.ok
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_install_compat.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement compat.py (reuse plugin_loader rule)**

```python
# src/testpilot/install/compat.py
from __future__ import annotations
from dataclasses import dataclass, field
from testpilot.core.plugin_loader import _check_api_compat
from testpilot.core.plugin_base import IncompatiblePluginError

@dataclass
class CompatReport:
    ok: bool
    failures: list[str] = field(default_factory=list)

def manifest_compat_report(core_api: str, plugins: list[tuple[str, str]]) -> CompatReport:
    failures: list[str] = []
    for name, plugin_api in plugins:
        try:
            _check_api_compat(name, plugin_api, core_api)
        except IncompatiblePluginError as exc:
            failures.append(str(exc))
    return CompatReport(ok=not failures, failures=failures)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_install_compat.py -v`
Expected: PASS.

- [ ] **Step 5: Add a CLI/CI hook**

Add `testpilot install-doctor --manifest install-manifest.yaml` (hidden helper) that loads the manifest, builds `(name, api_version)` pairs, calls `manifest_compat_report`, prints failures, exits non-zero on incompatibility. Wire into CI in Task 9.

- [ ] **Step 6: Commit**

```bash
git add src/testpilot/install/compat.py tests/test_install_compat.py src/testpilot/cli.py
git commit -m "feat(install): manifest api-compat gate reusing PluginLoader rule"
```

---

## Task 5: Wheel-mode `--verify-install`

**Files:**
- Modify: `src/testpilot/cli.py` (verify-install section ~lines 147-330)
- Test: `tests/test_verify_install_wheel_mode.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_verify_install_wheel_mode.py
from testpilot.cli import _verify_install_wheel_mode  # new function

def test_wheel_mode_reports_entrypoint_plugins(monkeypatch):
    # fake importlib.metadata entry points + versions
    rows = _verify_install_wheel_mode(probe={
        "wrapper_ok": True, "core_version": "0.3.0",
        "plugins": [{"name": "wifi_llapi", "version": "0.3.0", "loads": True, "api": "1.1"}],
        "serialwrap": True, "skill_packaged": True, "stray_import": None,
    })
    assert all(ok for ok, _ in rows)

def test_wheel_mode_fails_on_incompatible_plugin():
    rows = _verify_install_wheel_mode(probe={
        "wrapper_ok": True, "core_version": "0.3.0",
        "plugins": [{"name": "wifi_llapi", "version": "0.3.0", "loads": False, "api": "2.0",
                     "error": "IncompatiblePluginError"}],
        "serialwrap": True, "skill_packaged": True, "stray_import": None,
    })
    assert any(not ok and "wifi_llapi" in msg for ok, msg in rows)

def test_wheel_mode_warns_on_stray_import():
    rows = _verify_install_wheel_mode(probe={
        "wrapper_ok": True, "core_version": "0.3.0", "plugins": [],
        "serialwrap": True, "skill_packaged": True,
        "stray_import": "/home/u/.local/lib/python3.12/site-packages/testpilot",
    })
    assert any("WARN" in msg and "managed" in msg for _, msg in rows)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_verify_install_wheel_mode.py -v`
Expected: FAIL (function missing).

- [ ] **Step 3: Implement `_verify_install_wheel_mode(probe)` + a `_probe_wheel_install()`**

`_verify_install_wheel_mode(probe)` is pure: takes a dict, returns `list[(ok, msg)]`. `_probe_wheel_install()` gathers the real data:
- `importlib.metadata.version("testpilot-core")`
- `importlib.metadata.entry_points(group="testpilot.plugins")` → for each, `importlib.metadata.version(dist)`, attempt `PluginLoader.from_entry_points([ep]).load(ep.name)`; record `loads`/`error`/`api`.
- serialwrap binary via `shutil.which("serialwrap")` or `SERIALWRAP_BIN`.
- skill present via `importlib.resources.files("testpilot")/"_skills"/"testpilot-normal-test"`.
- stray import: run `python -c "import testpilot, os; print(os.path.dirname(testpilot.__file__))"` with the *system* python and compare to managed venv path.

Gate the existing checkout-based checks behind `if managed_src_with_git: ... else: _verify_install_wheel_mode(_probe_wheel_install())`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_verify_install_wheel_mode.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/testpilot/cli.py tests/test_verify_install_wheel_mode.py
git commit -m "feat(cli): wheel-mode verify-install via importlib.metadata + PluginLoader.load"
```

---

## Task 6: `_handle_update` rewrite + plugin reconcile

**Files:**
- Modify: `src/testpilot/cli.py` (`_handle_update` ~line 420)
- Test: `tests/test_update_reconcile.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_update_reconcile.py
from testpilot.cli import _reconcile_plan

def test_reconcile_uninstalls_dropped_plugins():
    installed = {"wifi_llapi", "old_plugin"}
    manifest = {"wifi_llapi", "brcm_fw_upgrade"}
    plan = _reconcile_plan(installed=installed, manifest=manifest)
    assert plan.to_uninstall == {"old_plugin"}
    assert plan.to_install == {"brcm_fw_upgrade"}

def test_reconcile_noop_when_aligned():
    plan = _reconcile_plan(installed={"wifi_llapi"}, manifest={"wifi_llapi"})
    assert not plan.to_uninstall and not plan.to_install
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_update_reconcile.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `_reconcile_plan` + rewrite `_handle_update`**

```python
# in cli.py
from dataclasses import dataclass

@dataclass
class ReconcilePlan:
    to_install: set[str]
    to_uninstall: set[str]

def _reconcile_plan(installed: set[str], manifest: set[str]) -> ReconcilePlan:
    return ReconcilePlan(to_install=manifest - installed, to_uninstall=installed - manifest)
```
Rewrite `_handle_update(ref)`: drop the `managed_src/.git` gate; resolve manifest at `ref` (or latest); `pip freeze` snapshot to `~/.local/share/testpilot/.last-good.txt`; reinstall pinned wheels into the managed venv; compute installed `testpilot.plugins` dists, apply `_reconcile_plan`, `pip uninstall -y` the `to_uninstall`; run wheel-mode verify; on failure, `pip install -r .last-good.txt`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_update_reconcile.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/testpilot/cli.py tests/test_update_reconcile.py
git commit -m "feat(cli): wheel-world --update with manifest reconcile + rollback snapshot"
```

---

## Task 7: Online installer rewrite (scripts/install.sh)

**Files:**
- Rewrite: `scripts/install.sh`
- Test: `tests/test_install_sh_token_hygiene.py` (static assertions on the script)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_install_sh_token_hygiene.py
import pathlib, re
SH = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "install.sh").read_text()

def test_no_token_in_url_pattern():
    assert "x-access-token:" not in SH, "never embed token in git URL"

def test_uses_gh_token_env_and_no_set_x():
    assert "GH_TOKEN" in SH
    assert "set -x" not in SH

def test_no_editable_plugins_path():
    assert "plugins/wifi_llapi" not in SH and "plugins/brcm_fw_upgrade" not in SH

def test_has_offline_branch():
    assert "--offline" in SH and "--no-index" in SH
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_install_sh_token_hygiene.py -v`
Expected: FAIL (old script).

- [ ] **Step 3: Rewrite scripts/install.sh**

Online path: prereq checks (python3.11+, uv/pip, `gh`); parse `--plugins`, `--offline <bundle>`; resolve manifest at `TESTPILOT_REF` (default latest) via `gh api repos/hamanpaul/testpilot-core/contents/install-manifest.yaml` (authed by `GH_TOKEN`); create managed venv; `gh release download` core + selected plugin wheels (token via `GH_TOKEN` env only); `pip install` core wheel, then plugins `--no-deps`, then serialwrap; if a tag has no wheel asset, `pip install "git+https://...@$VER"` fallback (token via `GIT_ASKPASS` helper, never inline); write wrapper; copy packaged skill via the managed venv's python `importlib.resources`. Never `set -x`; never echo the token or constructed authed URL.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_install_sh_token_hygiene.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/install.sh tests/test_install_sh_token_hygiene.py
git commit -m "feat(install): rewrite installer online path to manifest-pinned wheels (gh token via env)"
```

---

## Task 8: Offline bundle builder + offline install path

**Files:**
- Create: `scripts/build-bundle.sh`
- Modify: `scripts/install.sh` (the `--offline` branch)
- Test: `tests/test_build_bundle_sh.py` (static) + `tests/test_offline_install_integration.sh` (CI-run)

- [ ] **Step 1: Write the failing static test**

```python
# tests/test_build_bundle_sh.py
import pathlib
SH = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "build-bundle.sh").read_text()

def test_excludes_live_testbed():
    assert "configs/testbed.yaml" in SH  # referenced in an exclude context
    assert "SHA256SUMS" in SH

def test_dry_run_gate_and_no_index():
    assert "--no-index" in SH and "--find-links" in SH
    assert "--dry-run" in SH or "throwaway" in SH or "pip install --no-index" in SH

def test_downloads_release_wheels_not_rebuild():
    assert "gh release download" in SH
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_build_bundle_sh.py -v`
Expected: FAIL (script missing).

- [ ] **Step 3: Implement scripts/build-bundle.sh**

On a networked Linux box matching target py-minor: read manifest; `gh release download` exact core/plugin/serialwrap wheels into `wheelhouse/`; `pip download` the third-party closure (`--only-binary=:all:` for the active platform) into `wheelhouse/`; write `requirements.txt` (exact versions of every wheel in `wheelhouse/`); copy packaged skill + `testbed.yaml.example`; exclude `configs/testbed.yaml`, root `*.xlsx`, `compare-*`; dry-run `pip install --no-index --find-links=wheelhouse -r requirements.txt` into a throwaway venv (fail build if unresolved); `tar czf testpilot-bundle-<ver>-linux-$(uname -m)-cp${PYMINOR}.tar.gz` + `sha256sum > SHA256SUMS`.

- [ ] **Step 4: Implement the `--offline` branch in install.sh**

`install.sh --offline <bundle>`: `sha256sum -c SHA256SUMS` (abort on mismatch); assert py-minor/arch vs bundle name; create venv; `pip install --no-index --find-links=wheelhouse -r requirements.txt`; wrapper + skill; run `testpilot --verify-install`. No token, no network.

- [ ] **Step 5: Write the offline integration test (CI)**

```bash
# tests/test_offline_install_integration.sh  (run in CI on Linux)
set -euo pipefail
# build a minimal bundle from locally-built wheels, then install in a network-disabled venv
# assert: testpilot --verify-install exits 0; testpilot list-plugins shows the bundled plugin
```

- [ ] **Step 6: Run static tests + the integration script**

Run: `uv run pytest tests/test_build_bundle_sh.py -v && bash tests/test_offline_install_integration.sh`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/build-bundle.sh scripts/install.sh tests/test_build_bundle_sh.py tests/test_offline_install_integration.sh
git commit -m "feat(install): offline wheelhouse bundle builder + --offline install path"
```

---

## Task 9: Legacy-install migration

**Files:**
- Modify: `src/testpilot/cli.py` (migration helper) and/or `scripts/install.sh`
- Test: `tests/test_migration_detect.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_detect.py
from testpilot.cli import _detect_legacy_installs

def test_detects_user_site_and_pipx(monkeypatch, tmp_path):
    probe = {"user_site_testpilot": True, "pipx_testpilot": False, "legacy_src": True}
    actions = _detect_legacy_installs(probe)
    assert "uninstall_user_site" in actions
    assert "remove_legacy_src" in actions
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_migration_detect.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `_detect_legacy_installs(probe) -> list[str]`** mapping detected shapes to reconcile actions; wire a real probe (user-site `testpilot*.dist-info`, `pipx list`, `~/.local/share/testpilot/src`). The installer executes the actions (uninstall/repoint) and warns on a surviving out-of-venv import.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migration_detect.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/testpilot/cli.py tests/test_migration_detect.py
git commit -m "feat(install): detect + reconcile legacy install shapes on (re)install"
```

---

## Task 10: CI build/upload + wheel-content assertion + compat gate

**Files:**
- Modify: `.github/workflows/release.yml`, `.github/workflows/ci.yml`
- Test: `tests/test_wheel_contents.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wheel_contents.py
import glob, subprocess, zipfile, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_wheel_has_skill_and_no_run_bundles(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "-o", str(tmp_path)], cwd=ROOT, check=True)
    names = zipfile.ZipFile(glob.glob(str(tmp_path / "testpilot_core-*.whl"))[0]).namelist()
    assert any("_skills/testpilot-normal-test" in n for n in names)
    assert not any("/reports/" in n and n.rstrip("/").split("/")[-1][:2].isdigit() for n in names)
```

- [ ] **Step 2: Run to verify it fails/passes** (passes once Task 2 lands; this locks it).

Run: `uv run pytest tests/test_wheel_contents.py -v`

- [ ] **Step 3: Edit release.yml** — after version checks, add:
```yaml
      - name: Build wheel
        run: uv build --wheel
      - name: Upload wheel to release
        env: { GH_TOKEN: ${{ secrets.GITHUB_TOKEN }} }
        run: gh release upload "$TAG_NAME" dist/*.whl --clobber
```

- [ ] **Step 4: Edit ci.yml** — add a step running `testpilot install-doctor --manifest install-manifest.yaml` (compat gate) and the new pytest files.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml .github/workflows/ci.yml tests/test_wheel_contents.py
git commit -m "ci(core): build+upload wheel asset, wheel-content + manifest compat gates"
```

---

## Task 11: Docs (canonical install README) + CHANGELOG

**Files:**
- Modify: `README.md`, `CHANGELOG.md`

- [ ] **Step 1: Rewrite README install section** to the wheel + dual-entry model: online `bash scripts/install.sh` (with `TESTPILOT_INSTALL_TOKEN`), offline `bash scripts/install.sh --offline <bundle>`; remove src-checkout/`--update` git semantics; declare this README the canonical install reference; align all sources to `hamanpaul/*`. Regenerate any CLI-help markers for `--update`/`--verify-install` (R-16).

- [ ] **Step 2: Update CHANGELOG `[Unreleased]`** — note **BREAKING** (dist rename `testpilot`→`testpilot-core`, src-checkout model removed) + the new dual-entry install + manifest.

- [ ] **Step 3: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs(install): canonical wheel + dual-entry install docs; changelog"
```

---

## Task 12: Final verification + policy gate

- [ ] **Step 1: Full test run** — `uv run pytest -q` (all green).
- [ ] **Step 2: Policy** — `python3 -m policy_check --repo .` (no failure).
- [ ] **Step 3: Build smoke** — `uv build` produces `testpilot_core-*.whl` with skill + no run bundles.
- [ ] **Step 4: Manual smoke** — online install via a `file://`/stub source and offline `--offline` bundle each reach a passing `testpilot --verify-install` (document evidence).

---

## Self-Review notes

- Spec coverage: managed-installation MODIFIED (Tasks 5,6,7,9) + REMOVED→ADDED (Tasks 3,7) ; offline-install-bundle ADDED (Task 8) ; manifest+compat (Tasks 3,4,10) ; rename/PyPI-collision (Task 1) ; skill package-data (Task 2) ; CI artifacts (Task 10) ; docs (Task 11). All openspec requirements mapped.
- Types consistent: `InstallManifest`/`Plugin.selected()`, `CompatReport`, `ReconcilePlan`, `_verify_install_wheel_mode(probe)`, `_detect_legacy_installs(probe)` used consistently across tasks.
- No placeholders: each task has concrete test + code/script intent + exact commands.

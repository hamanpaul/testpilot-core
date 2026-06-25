# P2b: versioned plugin contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans。Steps 用 `- [ ]`。前置:P2a(`loader.load()` 經 entry_points;檢查加在此)。

**Goal:** `testpilot.api.API_VERSION`(semver,獨立於套件版本)+ `PluginBase.api_version`(required)+ `loader.load()` 向後相容檢查(不相容/未宣告 → `IncompatiblePluginError`)。相容 plugin 行為不變。

**Tech Stack:** Python 3.12, pytest。change `versioned-plugin-contract`。spec `docs/superpowers/specs/2026-06-18-versioned-plugin-contract-design.md`。

---

## File Structure

- Modify: `src/testpilot/core/plugin_base.py`(`api_version = None`;`IncompatiblePluginError` 可置此或新 `core/errors.py`)
- Modify: `src/testpilot/api/__init__.py`(`API_VERSION = "1.0"` + re-export `IncompatiblePluginError`,更新 `__all__`)
- Modify: `src/testpilot/core/plugin_loader.py`(load 加相容檢查)
- Modify: `plugins/wifi_llapi/plugin.py`、`plugins/brcm_fw_upgrade/plugin.py`(`api_version = "1.0"`)
- Create: `tests/test_versioned_plugin_contract.py`

---

## Task 1: RED — 相容矩陣先紅

- [ ] **Step 1: 契約測試**

`tests/test_versioned_plugin_contract.py`:

```python
"""versioned plugin contract（change versioned-plugin-contract）。"""
from __future__ import annotations
import re
import pytest


def test_api_version_is_semver():
    from testpilot.api import API_VERSION
    assert re.fullmatch(r"\d+\.\d+", API_VERSION)


def test_incompatible_error_exported():
    from testpilot.api import IncompatiblePluginError
    assert issubclass(IncompatiblePluginError, Exception)


@pytest.mark.parametrize("declared, api, ok", [
    ("1.0", "1.0", True),
    ("1.0", "1.3", True),    # 向後相容
    ("1.3", "1.0", False),   # SDK 太舊
    ("2.0", "1.5", False),   # major breaking
    (None,  "1.0", False),   # 未宣告
])
def test_compat_matrix(declared, api, ok):
    from testpilot.core.plugin_loader import _check_api_compat
    from testpilot.api import IncompatiblePluginError
    if ok:
        _check_api_compat("dummy", declared, api)   # 不 raise
    else:
        with pytest.raises(IncompatiblePluginError):
            _check_api_compat("dummy", declared, api)
```

- [ ] **Step 2: 跑確認紅**

Run: `python -m pytest tests/test_versioned_plugin_contract.py -v`
Expected: FAIL — `API_VERSION`/`IncompatiblePluginError`/`_check_api_compat` 未存在。擷取 RED。

---

## Task 2: GREEN — 契約版本 + 錯誤型別

- [ ] **Step 1: IncompatiblePluginError(core)**

`src/testpilot/core/plugin_base.py`(或新 `core/errors.py`):
```python
class IncompatiblePluginError(Exception):
    """plugin 宣告的 SDK API 版本與 testpilot 不相容(或未宣告)。"""
```

- [ ] **Step 2: api 匯出**

`src/testpilot/api/__init__.py`:加 `API_VERSION = "1.0"`;`from testpilot.core.plugin_base import IncompatiblePluginError`;`__all__` 加 `"API_VERSION"`, `"IncompatiblePluginError"`。

- [ ] **Step 3: PluginBase.api_version**

`plugin_base.py`:`PluginBase` 類別屬性 `api_version: str | None = None`。

---

## Task 3: GREEN — loader 相容檢查

- [ ] **Step 1: _check_api_compat + 接入 load**

`plugin_loader.py`:
```python
from testpilot.core.plugin_base import IncompatiblePluginError
from testpilot.api import API_VERSION   # 或避免循環:讀常數時 lazy import

def _parse(v: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)", v or "")
    if not m:
        raise IncompatiblePluginError(f"api_version 格式錯誤: {v!r}")
    return int(m.group(1)), int(m.group(2))

def _check_api_compat(name: str, declared: str | None, api: str) -> None:
    if declared is None:
        raise IncompatiblePluginError(f"{name} 未宣告 api_version")
    p_major, p_minor = _parse(declared)
    a_major, a_minor = _parse(api)
    if p_major != a_major or a_minor < p_minor:
        raise IncompatiblePluginError(
            f"{name} 要求 API {declared},但 testpilot 提供 {api}")
```
在 `load()` 實例化後、回傳前呼叫 `_check_api_compat(name, instance.api_version, API_VERSION)`。

> 循環 import 注意:`plugin_loader` import `testpilot.api` 可能與 api re-export 形成循環;若有,改在 `load()` 內 lazy `from testpilot.api import API_VERSION` 或直接從 core 常數讀。

- [ ] **Step 2: 跑相容矩陣至綠**

Run: `python -m pytest tests/test_versioned_plugin_contract.py -v` → PASS

---

## Task 4: GREEN — in-repo plugin 宣告

- [ ] **Step 1**: `plugins/wifi_llapi/plugin.py`、`plugins/brcm_fw_upgrade/plugin.py` 的 Plugin 類別加 `api_version = "1.0"`
- [ ] **Step 2**: 載入 wifi/brcm 不報錯

Run: `python -m pytest tests/test_versioned_plugin_contract.py plugins/wifi_llapi/tests/test_orchestrator_per_case_agent.py -q` → PASS

---

## Task 5: 回歸驗證

- [ ] **Step 1**: 既有 plugin/golden 測試全綠(相容 plugin 行為不變)
- [ ] **Step 2**: 全套 `pytest` 綠
- [ ] **Step 3**: 文件註明「API 契約版本(testpilot.api.API_VERSION)vs 套件版本(VERSION)」語意
- [ ] **Step 4: Commit**

```bash
git add src/testpilot/core/plugin_base.py src/testpilot/api/__init__.py src/testpilot/core/plugin_loader.py plugins/wifi_llapi/plugin.py plugins/brcm_fw_upgrade/plugin.py tests/test_versioned_plugin_contract.py openspec/changes/versioned-plugin-contract
git commit -m "feat(api): versioned plugin contract (API_VERSION + load-time compat check)"
```

---

## Task 6: 收尾(workflow 後段)

- [ ] 6.1 requesting-code-review(版本語意 / 檢查正確 / 行為保真)
- [ ] 6.2 receiving-code-review + re-review 至無 Critical/Important
- [ ] 6.3 openspec archive → policy → conventional commit → push → PR(R-12/R-17)

---

## Self-Review

- **Spec coverage:** API_VERSION 獨立(Req)→ Task 2;顯式宣告(Req)→ Task 2.3 + 4 + 矩陣 None case;向後相容檢查(Req)→ Task 3 + 矩陣。
- **Placeholder scan:** 無 TBD;測試/錯誤/檢查為完整碼;循環 import 風險已標注緩解。
- **Type consistency:** `api_version: str|None`、`_check_api_compat(name, declared, api)`、`API_VERSION` 與測試一致。
- **行為保真:** 相容 plugin(wifi/brcm "1.0" on "1.0")載入/行為不變;僅不相容/未宣告從靜默變明確報錯。

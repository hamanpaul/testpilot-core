"""驗收守門：core/schema/reporting 對 plugin 零具名（wifi_llapi/brcm）。

本測試證明 core ⊥ wifi_llapi 解耦為「真解耦」而非改名——wifi_llapi 完全
透過 ``PluginBase`` hook（create_reporter / validate_case / execution_policy / register_cli）
接入，``src/testpilot/{core,schema,reporting}`` 不得再出現 ``wifi_llapi`` 字串。

* ``src/testpilot/cli.py`` 另由 ``tests/test_cli_plugin_registration.py`` 守
  CLI plugin 註冊零具名；wifi_llapi 的 CLI help 相容字串另有既有例外。
"""

from __future__ import annotations

from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "testpilot"
GUARDED_DIRS = ("core", "schema", "reporting")
WIFI_FORBIDDEN = "wifi_llapi"


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for sub in GUARDED_DIRS:
        base = SRC_ROOT / sub
        for py in base.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            files.append(py)
    return files


def test_core_schema_reporting_have_no_wifi_llapi_names() -> None:
    offenders: list[str] = []
    for py in _iter_py_files():
        text = py.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if WIFI_FORBIDDEN in line:
                offenders.append(f"{py}:{lineno}")

    assert not offenders, (
        f"core/schema/reporting 不得具名 '{WIFI_FORBIDDEN}'，但發現以下位置：\n"
        + "\n".join(offenders)
        + "\n（plugin 應透過 PluginBase hook 接入；CLI help 相容字串不在此守門範圍）"
    )


def test_src_testpilot_has_no_brcm_names() -> None:
    offenders: list[str] = []
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts or "_template" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "brcm" in line.lower():
                offenders.append(f"{py}:{lineno}")

    assert not offenders, (
        "src/testpilot 不得具名 brcm，brcm_fw_upgrade schema/validation 必須留在 plugin：\n"
        + "\n".join(offenders)
    )

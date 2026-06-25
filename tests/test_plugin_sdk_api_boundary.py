"""Boundary guard for the testpilot.api plugin contract.

change: establish-testpilot-api-public-layer

兩個保證:
1. testpilot.api 匯出已承諾的公開契約表面(且為與原模組相同的物件)。
2. plugins/* production code 不得 reach 進 testpilot.core/schema/reporting/
   transport/runtime 內部,除非列於明示 allow-list(每筆標註負責消除的後續 change)。

靜態檢查範圍:涵蓋 `from X import ...`(ast.ImportFrom)與 `import X`(ast.Import);
plain guarded import 一律視為違規(plugin 應走 testpilot.api)。動態/字串 import
(如 importlib.import_module("testpilot.core...."))亦納入守門。
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS_ROOT = REPO_ROOT / "plugins"

# 公開符號 -> 其原始模組(用 identity 比對,確保 re-export 非複製)
PUBLIC_SURFACE = {
    "PluginBase": "testpilot.core.plugin_base",
    "PreparedRun": "testpilot.core.prepared_run",
    "IReporter": "testpilot.reporting.reporter",
    "MarkdownReporter": "testpilot.reporting.reporter",
    "JsonReporter": "testpilot.reporting.reporter",
    "HtmlReporter": "testpilot.reporting.html_reporter",
    "generate_reports": "testpilot.reporting.reporter",
    "TransportBase": "testpilot.transport.base",
    "StubTransport": "testpilot.transport.base",
    "create_transport": "testpilot.transport.factory",
    "load_case": "testpilot.schema.case_schema",
    "load_cases_dir": "testpilot.schema.case_schema",
    "CaseValidationError": "testpilot.schema.case_schema",
    "validate_case": "testpilot.schema.case_schema",
    "require_non_empty_string": "testpilot.schema.case_schema",
    "validate_string_list": "testpilot.schema.case_schema",
    "require_mapping": "testpilot.schema.case_schema",
    "require_string_mapping": "testpilot.schema.case_schema",
    "require_bool": "testpilot.schema.case_schema",
    "TestbedConfig": "testpilot.core.testbed_config",
    "stringify_step_command": "testpilot.core.case_utils",
    "step_command_lines": "testpilot.core.case_utils",
    "case_band_results": "testpilot.core.case_utils",
    "case_matches_requested_ids": "testpilot.core.case_utils",
    "overall_case_status": "testpilot.core.case_utils",
    "sanitize_case_id": "testpilot.core.case_utils",
    "resolve_serialwrap_binary": "testpilot.serialwrap_binary",
    "RunBackend": "testpilot.runtime.run_backend",
    "RunHandle": "testpilot.runtime.run_backend",
    "ExportRequest": "testpilot.runtime.run_backend",
    "ExportResult": "testpilot.runtime.run_backend",
}

# plugin 不得直接 reach 進的內部命名空間
GUARDED_PREFIXES = (
    "testpilot.core",
    "testpilot.schema",
    "testpilot.reporting",
    "testpilot.transport",
    "testpilot.runtime",
    "testpilot.serialwrap_binary",
)

# 已知、已記錄、尚未消除的洩漏。(module, symbol) -> 負責消除的後續 change。
ALLOWLIST = {}


def _is_guarded(module: str) -> bool:
    return any(module == p or module.startswith(p + ".") for p in GUARDED_PREFIXES)


def _production_py_files():
    for plugin_root in sorted(PLUGINS_ROOT.iterdir()):
        if not plugin_root.is_dir() or plugin_root.name.startswith("_"):
            continue
        for path in sorted(plugin_root.rglob("*.py")):
            parts = path.relative_to(plugin_root).parts
            if "tests" in parts or "scripts" in parts:
                continue
            yield path


def _collect_str_constants(tree: ast.Module) -> dict[str, str]:
    """module-level name -> str 常數(含 AnnAssign);抓 `m = "testpilot.core.x"; import_module(m)`
    evasion。只收頂層、且排除任何也在函式內被當參數/賦值的同名(scope/shadowing 安全),
    避免把函式區域變數誤解析成外層常數而誤報(Copilot Tier B review)。"""
    module_consts: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        target = None
        value = None
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        if target is not None and isinstance(value, ast.Constant) and isinstance(value.value, str):
            module_consts[target] = value.value
    shadowed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs):
                shadowed.add(arg.arg)
            if a.vararg:
                shadowed.add(a.vararg.arg)
            if a.kwarg:
                shadowed.add(a.kwarg.arg)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Name):
                            shadowed.add(t.id)
    return {k: v for k, v in module_consts.items() if k not in shadowed}


def _import_module_callables(tree: ast.AST) -> set[str]:
    """import_module 的可呼叫名,含 `from importlib import import_module as X` 的 alias。"""
    names = {"import_module", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    names.add(alias.asname or "import_module")
    return names


def _resolve_str(node: ast.AST, constants: dict[str, str]) -> str | None:
    """best-effort 把 AST 解析成 str:字面、常數變數、或兩者的 `+` 串接。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_str(node.left, constants)
        right = _resolve_str(node.right, constants)
        if left is not None and right is not None:
            return left + right
    return None


def _rel(path):
    """REPO_ROOT 相對路徑;對 REPO_ROOT 外的路徑(如測試 tmp)退回原路徑,不炸。"""
    try:
        return path.relative_to(REPO_ROOT)
    except ValueError:
        return path


def _guarded_import_violations(paths) -> list[str]:
    violations = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constants = _collect_str_constants(tree)
        import_callables = _import_module_callables(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                if not _is_guarded(node.module):
                    continue
                for alias in node.names:
                    if (node.module, alias.name) not in ALLOWLIST:
                        violations.append(
                            f"{_rel(path)}:{node.lineno} "
                            f"-> from {node.module} import {alias.name}"
                        )
            elif isinstance(node, ast.Import):
                # plain `import testpilot.core.x` 一律違規:plugin 應走 testpilot.api
                for alias in node.names:
                    if _is_guarded(alias.name):
                        violations.append(
                            f"{_rel(path)}:{node.lineno} "
                            f"-> import {alias.name}"
                        )
            elif isinstance(node, ast.Call):
                func = node.func
                is_import_call = (
                    isinstance(func, ast.Attribute) and func.attr == "import_module"
                ) or (
                    isinstance(func, ast.Name) and func.id in import_callables
                )
                if is_import_call and node.args:
                    # 解析字面 / 常數變數 / 常數串接,堵掉「藏在變數或 alias 後面」的
                    # 動態 import evasion(codex Tier B finding)。純運算(f-string 等)無法
                    # 靜態證明,plugin production 目前零此用法,留為已知限制不誤報自家子模組。
                    target = _resolve_str(node.args[0], constants)
                    if target is not None and _is_guarded(target):
                        violations.append(
                            f"{_rel(path)}:{node.lineno} "
                            f"-> dynamic import {target}"
                        )
    return violations


def test_public_surface_exports_same_objects():
    api = importlib.import_module("testpilot.api")
    assert hasattr(api, "__all__"), "testpilot.api must declare __all__"
    for name, origin_mod in PUBLIC_SURFACE.items():
        assert name in api.__all__, f"{name} missing from testpilot.api.__all__"
        origin = importlib.import_module(origin_mod)
        assert getattr(api, name) is getattr(origin, name), (
            f"testpilot.api.{name} is not the same object as {origin_mod}.{name}"
        )
    excel = importlib.import_module("testpilot.api.excel_adapter")
    origin_excel = importlib.import_module("testpilot.reporting.excel_adapter")
    for fn in ("col_to_index", "is_merged_cell", "open_workbook"):
        assert getattr(excel, fn) is getattr(origin_excel, fn), (
            f"testpilot.api.excel_adapter.{fn} mismatch"
        )


def test_plugins_do_not_breach_core_boundary():
    violations = _guarded_import_violations(_production_py_files())
    assert not violations, (
        "plugin production code breaches testpilot.api boundary "
        "(repoint to testpilot.api or add to ALLOWLIST with a follow-up change):\n"
        + "\n".join(violations)
    )


def test_guard_catches_dynamic_import_evasions(tmp_path):
    """硬化守門:藏在常數變數 / `import_module as X` alias / 常數串接後面的 guarded
    動態 import 必須被抓到;合法的自家子模組動態 import 不誤報(codex Tier B finding)。"""
    snippet = (
        "import importlib\n"
        "from importlib import import_module as im\n"
        "_M = 'testpilot.core.plugin_loader'\n"
        "def a():\n    return importlib.import_module(_M)\n"
        "def b():\n    return im('testpilot.schema.case_schema')\n"
        "def c():\n    return importlib.import_module('testpilot.' + 'core.orchestrator')\n"
        "def d():\n    return importlib.import_module('wifi_llapi.sub')\n"
    )
    f = tmp_path / "evasion.py"
    f.write_text(snippet, encoding="utf-8")
    joined = "\n".join(_guarded_import_violations([f]))
    assert "testpilot.core.plugin_loader" in joined, "常數變數 evasion 未抓到"
    assert "testpilot.schema.case_schema" in joined, "alias evasion 未抓到"
    assert "testpilot.core.orchestrator" in joined, "常數串接 evasion 未抓到"
    assert "wifi_llapi.sub" not in joined, "自家子模組動態 import 被誤報"


def test_core_and_reporting_have_no_serialwrap_names():
    """run-level serialwrap 具體邏輯只能存在於 runtime backend(P3)。"""
    import re
    targets = [REPO_ROOT / "src" / "testpilot" / "core",
               REPO_ROOT / "src" / "testpilot" / "reporting"]
    pat = re.compile(r"serialwrap|log_capture|\bwal\b", re.IGNORECASE)
    hits = []
    for root in targets:
        for p in root.rglob("*.py"):
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if pat.search(line):
                    hits.append(f"{p.relative_to(REPO_ROOT)}:{i}: {line.strip()}")
    assert not hits, "core/reporting 仍具名 serialwrap:\n" + "\n".join(hits)

"""Runnable minimal sample plugin for the TestPilot SDK.

Demonstrates the full plugin contract against ``testpilot.api``:
- entry-point registration (see pyproject.toml)
- a ``PluginBase`` subclass with ``api_version``
- a schema-valid case + deterministic Pass verdict
- an optional ``register_cli`` command

Production code imports ONLY from ``testpilot.api`` (SDK boundary).
"""
from __future__ import annotations

from typing import Any

from testpilot.api import PluginBase, StubTransport, load_cases_dir


class Plugin(PluginBase):
    """Echo everything back through a StubTransport; pass when the echoed
    output contains every ``pass_criteria`` token."""

    api_version = "1.0"

    @property
    def name(self) -> str:
        return "sample_echo"

    def discover_cases(self) -> list[dict[str, Any]]:
        # cases_dir defaults to <plugin_root>/cases; load_cases_dir enforces
        # the strict case schema (and silently skips malformed files).
        return load_cases_dir(self.cases_dir)

    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> dict[str, Any]:
        transport = StubTransport()
        transport.connect()
        command = step.get("command") or f"{step.get('action', '')} {step.get('target', '')}".strip()
        raw = transport.execute(command)
        # StubTransport.execute returns {returncode, stdout, stderr, elapsed};
        # map stdout -> the `output` key PluginBase.run_pipeline reads.
        return {
            "success": raw["returncode"] == 0,
            "output": raw["stdout"],
            "captured": raw,
            "timing": raw["elapsed"],
        }

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        # results == {"steps": {step_id: step_result_dict}} (dict, not list)
        combined = " ".join(
            str(r.get("output", "")) for r in results.get("steps", {}).values()
        )
        criteria = case.get("pass_criteria", [])
        return all(str(c) in combined for c in criteria)

    def create_runner(self) -> "EchoRunner":
        # Returning a runner routes Orchestrator.run() away from _skeleton_run
        # (which never produces a verdict) into run_pipeline.
        return EchoRunner(self)

    def register_cli(self, registrar: Any) -> None:
        import click

        @click.command("sample-echo-greet")
        @click.option("--name", default="world", help="Name to greet.")
        def greet(name: str) -> None:
            """Echo a greeting through the stub transport (sample CLI hook)."""
            transport = StubTransport()
            transport.connect()
            click.echo(transport.execute(f"echo hello {name}")["stdout"])

        registrar.add_command(greet)


class EchoRunner:
    """Minimal runner: drives run_pipeline per case and aggregates verdicts.

    Orchestrator._run_via_runner calls
    ``run(orchestrator, plugin_name, case_ids, dut_fw_ver, provider_config)``.
    """

    def __init__(self, plugin: Plugin) -> None:
        self._plugin = plugin

    def run(
        self,
        orchestrator: Any,
        plugin_name: str,
        case_ids: list[str] | None,
        dut_fw_ver: str | None,
        provider_config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        cases = self._plugin.discover_cases()
        if case_ids:
            wanted = {str(c).strip() for c in case_ids if str(c).strip()}
            cases = [c for c in cases if str(c.get("id")) in wanted]
        results: list[dict[str, Any]] = []
        for case in cases:
            outcome = self._plugin.run_pipeline(case, topology=case.get("topology"))
            results.append(
                {
                    "case_id": case.get("id"),
                    "verdict": bool(outcome.get("verdict")),
                    "comment": outcome.get("comment", ""),
                }
            )
        overall = "PASS" if results and all(r["verdict"] for r in results) else "FAIL"
        return {"plugin": plugin_name, "overall": overall, "results": results}

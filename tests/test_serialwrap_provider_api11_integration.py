from __future__ import annotations

import asyncio
import copy
import importlib
import json
import os
from pathlib import Path
import pty
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

import pytest
import yaml

from testpilot.api import (
    CaptureRolePlanRequest,
    PluginBase,
    PrepareRunAfterCaptureContext,
    PrepareRunGateEvidence,
    PrepareRunGateOutcome,
    PrepareRunGateResult,
)
from testpilot.core.azure_auth import AzureAgentRuntime, AzureAgentState, AzureAgentStatus
from testpilot.core.case_planning import CasePlanningResult
from testpilot.core.execution_engine import RetryResult
from testpilot.core.orchestrator import Orchestrator
from testpilot.core.plugin_loader import PluginLoader
from testpilot.core.run_analysis import RunAnalysisResult
from testpilot.core.run_start_gate import RunCapability
from testpilot.runtime.serialwrap_backend import SerialwrapBackend
from testpilot.runtime import _serialwrap_log


_PROVIDER_COMMIT = "f1bb836e3ee67116b7ccc1b566278c16059d7d15"
_PLUGIN_NAME = "api11-integration"
_CASE = {
    "id": "D001",
    "source": {"row": 1},
    "steps": [{"id": "emit", "command": "emit temporary PTY evidence"}],
    "pass_criteria": ["the temporary console accepted bytes"],
}
_CAPTURE_MARKER = "CORE_API11_CAPTURED_CASE_LINE"


class _EntryPoint:
    name = _PLUGIN_NAME

    def __init__(self, plugin_type: type[PluginBase]) -> None:
        self.plugin_type = plugin_type

    def load(self) -> type[PluginBase]:
        return self.plugin_type


class _Reporter:
    def build_reports(self, run_result: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "case_rows": [record.case_id for record in run_result.cases],
            "case_log_ranges": {
                record.case_id: {
                    "dut": record.dut_log_lines,
                    "sta": record.sta_log_lines,
                }
                for record in run_result.cases
            },
            "dut_log_path": run_result.dut_log_path,
            "artifacts": dict(run_result.artifacts),
        }


class _TargetOutputEngine:
    """Keep Core's run loop real while replacing only the external agent call."""

    def execute_with_retry(
        self,
        *,
        plugin: PluginBase,
        case: dict[str, Any],
        runner: Any,
        execution_policy: dict[str, Any],
    ) -> RetryResult:
        del runner, execution_policy
        result = plugin.execute_step(case, case["steps"][0], None)
        return RetryResult(
            verdict=result.get("success") is True,
            comment="",
            commands=[str(case["steps"][0]["command"])],
            outputs=[str(result.get("output", ""))],
            attempts=[{"verdict": result.get("success") is True}],
            attempts_used=1,
            max_attempts=1,
            failure_snapshot={},
        )


class _UnixServerThread:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.ready = threading.Event()
        self.stop_requested = threading.Event()
        self.errors: list[BaseException] = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def serve() -> None:
            try:
                await self.server.start()
                self.ready.set()
                await asyncio.to_thread(self.stop_requested.wait)
                await self.server.stop()
            except BaseException as exc:  # surface thread failures in the test
                self.errors.append(exc)
                self.ready.set()

        try:
            loop.run_until_complete(serve())
        finally:
            loop.close()

    def __enter__(self) -> "_UnixServerThread":
        self.thread.start()
        if not self.ready.wait(5):
            raise AssertionError("temporary provider Unix socket did not start")
        if self.errors:
            raise AssertionError("temporary provider Unix server failed") from self.errors[0]
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop_requested.set()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive(), "temporary provider Unix server did not stop"
        assert not self.errors, "temporary provider Unix server failed"


def _pinned_provider_root() -> Path:
    value = os.environ.get("TESTPILOT_SERIALWRAP_SOURCE_ROOT", "").strip()
    if not value:
        pytest.skip(
            "set TESTPILOT_SERIALWRAP_SOURCE_ROOT to the reviewed API 1.1 provider source"
        )
    source_root = Path(value).expanduser().resolve()
    if not source_root.is_dir():
        pytest.fail("TESTPILOT_SERIALWRAP_SOURCE_ROOT is not a directory")
    try:
        repository_root = subprocess.check_output(
            ["git", "-C", str(source_root), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        revision = subprocess.check_output(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "-C", str(source_root), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.fail("provider source root is not a readable Git worktree")
    if Path(repository_root).resolve() != source_root:
        pytest.fail("provider source root must be the Git worktree root")
    if revision != _PROVIDER_COMMIT:
        pytest.fail("provider source revision does not match the reviewed pin")
    if status.strip():
        pytest.fail("provider source worktree must be clean at the reviewed pin")
    return source_root


def _import_pinned_provider(source_root: Path) -> dict[str, Any]:
    cached = [
        module
        for name, module in sys.modules.items()
        if name == "sw_core" or name.startswith("sw_core.")
    ]
    for module in cached:
        origin = getattr(module, "__file__", None)
        if origin and not Path(origin).resolve().is_relative_to(source_root):
            pytest.fail("a different sw_core source was already imported in this process")
    sys.path.insert(0, str(source_root))
    names = (
        "sw_core",
        "sw_core.cli",
        "sw_core.config",
        "sw_core.daemon",
        "sw_core.device_watcher",
        "sw_core.rpc_posix",
        "sw_core.rx_ingress",
        "sw_core.service",
        "sw_core.session_manager",
        "sw_core.uart_io",
        "sw_core.wal",
    )
    modules = {name: importlib.import_module(name) for name in names}
    for module in modules.values():
        origin = getattr(module, "__file__", None)
        assert origin is not None
        assert Path(origin).resolve().is_relative_to(source_root)
    return modules


def _assert_echo(request: dict[str, Any], response: dict[str, Any], keys: tuple[str, ...]) -> None:
    assert response.get("ok") is True
    assert response.get("schema_version") == "1"
    for key in keys:
        assert response.get(key) == request[key]


@pytest.mark.skipif(os.name != "posix", reason="the offline integration harness requires POSIX PTY/AF_UNIX")
def test_public_core_consumer_uses_real_provider_api11_cli_rpc_wal_and_pty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = _pinned_provider_root()
    provider = _import_pinned_provider(source_root)
    monkeypatch.setenv("TESTPILOT_SERIALWRAP_SOURCE_ROOT", str(source_root))
    monkeypatch.delenv("SERIALWRAP_ENDPOINT", raising=False)

    runtime_root = Path(tempfile.mkdtemp(prefix="sw-a11-"))
    master_fd: int | None = None
    service: Any = None
    bridge: Any = None
    service_calls: list[dict[str, Any]] = []
    try:
        socket_path = runtime_root / "provider.sock"
        socket_endpoint = f"unix://{socket_path}"
        wal = provider["sw_core.wal"].WalWriter(
            wal_dir=str(runtime_root / "wal"),
            rotate_bytes=10_000_000,
        )
        monkeypatch.setattr(provider["sw_core.service"], "WalWriter", lambda: wal)

        master_fd, slave_fd = pty.openpty()
        slave_path = os.ttyname(slave_fd)
        os.close(slave_fd)
        by_id = runtime_root / "by-id" / "temporary-console"
        by_id.parent.mkdir()
        by_id.symlink_to(slave_path)
        real_path = os.path.realpath(by_id)

        profile = provider["sw_core.config"].SessionProfile(
            profile_name="temporary-api11-profile",
            com="COM0",
            act_no=0,
            alias="temporary-console",
            device_by_id=str(by_id),
            platform="shell",
            ready_probe="",
        )
        service = provider["sw_core.service"].SerialwrapService(
            [profile],
            by_id_dir=str(runtime_root / "unused-by-id"),
            by_path_dir=str(runtime_root / "unused-by-path"),
            state_path=str(runtime_root / "session-state.json"),
        )
        manager = service._sessions
        session = provider["sw_core.session_manager"].SessionRuntime(
            session_id="temporary-api11-profile:COM0",
            profile=profile,
        )
        session.state = "READY"
        session.bridge_generation = 1
        session.attached_real_path = real_path
        ingress = provider["sw_core.rx_ingress"].RxIngressBinding(
            session_id=session.session_id,
            selector="COM0",
            bridge_generation=session.bridge_generation,
        )
        ingress.accept()
        bridge = provider["sw_core.uart_io"].UARTBridge(
            "COM0",
            slave_path,
            profile.uart,
            wal,
            rx_ingress_binding=ingress,
        )
        bridge.start()
        session.bridge = bridge
        manager._sessions = {session.session_id: session}
        manager._devices = {
            str(by_id): provider["sw_core.device_watcher"].DeviceInfo(
                by_id=str(by_id),
                real_path=real_path,
            )
        }
        assert service._running is False
        assert service._watcher._thread is None

        rpc_service = service

        def record_rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
            response = rpc_service.rpc(method, params)
            service_calls.append(
                {
                    "method": method,
                    "params": copy.deepcopy(params),
                    "response": copy.deepcopy(response),
                }
            )
            return response

        server = provider["sw_core.rpc_posix"].JsonRpcUnixServer(
            str(socket_path),
            record_rpc,
            blocking_methods=provider["sw_core.daemon"].BLOCKING_RPC_METHODS,
        )

        launcher = tmp_path / "source-pinned-serialwrap"
        import_receipt = tmp_path / "provider-cli-imports.jsonl"
        launcher.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "root = Path(os.environ['TESTPILOT_SERIALWRAP_SOURCE_ROOT']).resolve()\n"
            "sys.path.insert(0, str(root))\n"
            "import sw_core, sw_core.cli\n"
            "record = {'package': str(Path(sw_core.__file__).resolve()), "
            "'cli': str(Path(sw_core.cli.__file__).resolve())}\n"
            "with open(os.environ['TESTPILOT_SERIALWRAP_IMPORT_RECEIPT'], 'a', encoding='utf-8') as stream:\n"
            "    stream.write(json.dumps(record, sort_keys=True) + '\\n')\n"
            "from sw_core.cli import main\n"
            "raise SystemExit(main())\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        monkeypatch.setenv("SERIALWRAP_BIN", str(launcher))
        monkeypatch.setenv("TESTPILOT_SERIALWRAP_IMPORT_RECEIPT", str(import_receipt))

        config_path = tmp_path / "testbed.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "testbed": {
                        "run_backend": "serialwrap",
                        "serialwrap_socket": socket_endpoint,
                        "devices": {
                            "dut": {
                                "transport": "serialwrap",
                                "selector": "COM0",
                                "expected_device_by_id": str(by_id),
                                "profile": profile.profile_name,
                                "serial_port": slave_path,
                                "binary": str(launcher),
                                "socket": socket_endpoint,
                            }
                        },
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        callback_observations: dict[str, Any] = {}

        class IntegrationPlugin(PluginBase):
            api_version = "1.6"
            required_run_capabilities = frozenset(
                {RunCapability.STRICT_CAPTURE_BINDING}
            )
            capture_role_plan_request = CaptureRolePlanRequest(roles=("dut",))

            def __init__(self) -> None:
                self.bound_config: Any = None

            @property
            def name(self) -> str:
                return _PLUGIN_NAME

            def bind_testbed_config(self, topology: Any) -> None:
                self.bound_config = topology
                callback_observations["bound_config"] = topology

            def prepare_run(self, case_ids: Any) -> Any:
                callback_observations["prepared_config"] = self.bound_config
                assert self.bound_config is not None
                assert self.bound_config.get_device("dut")["selector"] == "COM0"
                return super().prepare_run(case_ids)

            def discover_cases(self) -> list[dict[str, Any]]:
                return [copy.deepcopy(_CASE)]

            def prepare_run_after_capture(
                self,
                prepared: Any,
                context: PrepareRunAfterCaptureContext,
            ) -> PrepareRunGateResult:
                del prepared
                callback_observations["capture_context"] = context
                return PrepareRunGateResult(
                    PrepareRunGateOutcome.ACCEPTED,
                    "temporary_provider_context_accepted",
                    (
                        PrepareRunGateEvidence(
                            "temporary_role",
                            PrepareRunGateOutcome.ACCEPTED,
                            "offline_test_fixture",
                        ),
                    ),
                )

            def execute_step(
                self,
                case: dict[str, Any],
                step: dict[str, Any],
                topology: Any,
            ) -> dict[str, Any]:
                del case, step, topology
                assert master_fd is not None
                before = wal.current_seq
                os.write(master_fd, (_CAPTURE_MARKER + "\n").encode("utf-8"))
                deadline = time.monotonic() + 3.0
                while wal.current_seq <= before and time.monotonic() < deadline:
                    time.sleep(0.005)
                assert wal.current_seq > before, "temporary UART RX did not reach the provider WAL"
                return {"success": True, "output": "temporary PTY write accepted"}

            def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
                del case, results
                return True

            def create_reporter(self) -> _Reporter:
                return _Reporter()

        orchestrator = Orchestrator(
            project_root=tmp_path,
            plugins_dir=tmp_path / "plugins",
            config_path=config_path,
            agent_runtime=AzureAgentRuntime(
                AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY)
            ),
        )
        orchestrator.loader = PluginLoader.from_entry_points(
            [_EntryPoint(IntegrationPlugin)]
        )
        assert isinstance(orchestrator.run_backend, SerialwrapBackend)
        orchestrator._start_run_capture = lambda *_args, **_kwargs: pytest.fail(
            "strict integration reached the legacy capture start path"
        )
        orchestrator._stop_run_capture = lambda *_args, **_kwargs: pytest.fail(
            "strict integration reached the legacy capture stop path"
        )
        orchestrator._export_run_logs = lambda *_args, **_kwargs: pytest.fail(
            "strict integration reached the legacy unbound WAL export path"
        )
        orchestrator._build_execution_engine = lambda **_kwargs: None
        orchestrator.execution_engine = _TargetOutputEngine()
        orchestrator._plan_case = lambda **_kwargs: CasePlanningResult(
            status="skipped_no_agent"
        )
        orchestrator.runner_selector.load_agent_config = lambda *_args, **_kwargs: {}
        orchestrator.runner_selector.build_execution_policy = lambda _config: {
            "mode": "sequential",
            "max_concurrency": 1,
            "retry": {"max_attempts": 1},
            "failure_policy": "retry_then_fail_and_continue",
        }
        orchestrator.runner_selector.select_case_runner = lambda **_kwargs: (
            {"integration_fixture": True},
            {"source": "offline-integration-test"},
        )
        orchestrator._analyze_run = lambda **_kwargs: RunAnalysisResult(
            status="complete"
        )

        with _UnixServerThread(server):
            payload = orchestrator.run(_PLUGIN_NAME, ["D001"])

        if payload["status"] != "ok":
            abort = payload.get("run_abort")
            capture = payload.get("artifacts", {}).get("core_run_capture")
            begin_item = next(
                (
                    item
                    for item in service_calls
                    if item["method"] == "capture.binding.begin"
                ),
                None,
            )
            range_item = next(
                (
                    item
                    for item in service_calls
                    if item["method"] == "capture.binding.range.v1_1"
                ),
                None,
            )
            binding_tokens = (
                begin_item["response"].get("binding_tokens", [])
                if begin_item is not None
                else []
            )
            raise AssertionError(
                {
                    "status": payload.get("status"),
                    "abort": {
                        key: abort.get(key)
                        for key in (
                            "reason_code",
                            "executed_case_count",
                            "unexecuted_case_ids",
                        )
                        if isinstance(abort, dict) and key in abort
                    },
                    "capture": {
                        key: capture.get(key)
                        for key in ("status", "reason_code", "records", "pages")
                        if isinstance(capture, dict) and key in capture
                    },
                    "rpc": [
                        (
                            item["method"],
                            item["response"].get("ok"),
                            item["response"].get("error_code"),
                        )
                        for item in service_calls
                    ],
                    "rx_binding_checks": [
                        (
                            row.get("seq"),
                            row.get("rx_disposition"),
                            bool(binding_tokens)
                            and row.get("rx_binding_token") == binding_tokens[0],
                        )
                        for row in (
                            range_item["response"].get("records", [])
                            if range_item is not None
                            else []
                        )
                        if row.get("dir") == "RX"
                    ],
                }
            )
        assert payload["case_rows"] == ["D001"]
        assert callback_observations["bound_config"] is orchestrator.config
        assert callback_observations["prepared_config"] is orchestrator.config
        context = callback_observations["capture_context"]
        assert context.run_id
        assert context.start_sequence == 0
        assert context.capture_binding_id

        report_range = payload["case_log_ranges"]["D001"]["dut"]
        assert report_range == "L1-L1"
        dut_log_path = Path(payload["dut_log_path"])
        assert dut_log_path.is_file()
        assert _CAPTURE_MARKER in dut_log_path.read_text(encoding="utf-8")
        assert payload["artifacts"]["core_run_capture"]["status"] == "complete"

        methods = [item["method"] for item in service_calls]
        assert methods[0] == "capabilities.get"
        assert "capture.binding.begin" in methods
        assert methods.count("capture.binding.checkpoint") == 2
        assert "capture.binding.mark.v1_1" in methods
        assert "capture.binding.range.v1_1" in methods
        assert "capture.binding.finish.v1_1" in methods
        assert not any(
            method in methods
            for method in (
                "capture.binding.mark",
                "capture.binding.range",
                "capture.binding.finish",
                "wal.current_seq",
                "session.list",
                "device.list",
                "health.ping",
            )
        )

        begin = next(item for item in service_calls if item["method"] == "capture.binding.begin")
        begin_request = begin["params"]
        begin_response = begin["response"]
        capability = service_calls[0]["response"]["features"]["capture_binding_provider"]
        assert capability["api_version"] == "1.1"
        assert capability["supported"] is True
        assert begin_response["schema_version"] == "1"
        assert begin_response["evidence_strength"] == "posix_fd_devnode_match_v1"
        assert begin_response["plan_digest"] == begin_request["role_plan"]["digest"]
        assert begin_response["roles_count"] == 1
        assert begin_response["start_sequence"] == 0
        assert len(begin_response["binding_tokens"]) == 1
        assert len(begin_response["rx_binding_tokens"]) == 1

        checkpoints = [
            item for item in service_calls if item["method"] == "capture.binding.checkpoint"
        ]
        assert checkpoints[0]["response"]["sequence"] == begin_response["start_sequence"]
        assert checkpoints[1]["response"]["sequence"] > checkpoints[0]["response"]["sequence"]
        checkpoint_echoes = (
            "operation_id",
            "handle",
            "capture_id",
            "plan_digest",
            "wal_epoch_token",
            "start_watermark",
            "previous_position_token",
            "previous_sequence",
        )
        for item in checkpoints:
            _assert_echo(item["params"], item["response"], checkpoint_echoes)

        mark = next(item for item in service_calls if item["method"] == "capture.binding.mark.v1_1")
        mark_anchors = (
            "operation_id",
            "handle",
            "capture_id",
            "plan_digest",
            "wal_epoch_token",
            "start_watermark",
            "last_position_token",
            "last_sequence",
        )
        _assert_echo(mark["params"], mark["response"], mark_anchors)
        assert mark["params"]["last_position_token"] == checkpoints[-1]["response"]["position_token"]
        assert mark["params"]["last_sequence"] == checkpoints[-1]["response"]["sequence"]
        assert mark["response"]["end_sequence"] == checkpoints[-1]["response"]["sequence"]

        range_page = next(
            item for item in service_calls if item["method"] == "capture.binding.range.v1_1"
        )
        range_anchors = (
            "handle",
            "capture_id",
            "plan_digest",
            "wal_epoch_token",
            "start_watermark",
            "watermark",
            "start_sequence",
            "end_sequence",
            "cursor",
        )
        _assert_echo(range_page["params"], range_page["response"], range_anchors)
        assert range_page["response"]["coverage_complete"] is True
        assert range_page["response"]["next_cursor"] is None
        assert any(
            row.get("dir") == "RX"
            and row.get("rx_disposition") == "accepted"
            and row.get("com") == "COM0"
            for row in range_page["response"]["records"]
        )
        accepted_rx_rows = [
            row
            for row in range_page["response"]["records"]
            if row.get("dir") == "RX" and row.get("rx_disposition") == "accepted"
        ]
        assert accepted_rx_rows
        assert all(
            row.get("rx_binding_token") == begin_response["rx_binding_tokens"][0]
            for row in accepted_rx_rows
        )

        finish = next(
            item for item in service_calls if item["method"] == "capture.binding.finish.v1_1"
        )
        finish_anchors = (
            "operation_id",
            "handle",
            "capture_id",
            "plan_digest",
            "wal_epoch_token",
            "start_watermark",
            "watermark",
            "start_sequence",
            "end_sequence",
        )
        _assert_echo(finish["params"], finish["response"], finish_anchors)
        assert finish["response"]["complete"] is True
        assert finish["response"]["capture_status"] == "complete"

        child_imports = [
            json.loads(line)
            for line in import_receipt.read_text(encoding="utf-8").splitlines()
        ]
        assert len(child_imports) == len(service_calls)
        assert all(
            Path(item["package"]).resolve().is_relative_to(source_root)
            and Path(item["cli"]).resolve() == (source_root / "sw_core" / "cli.py").resolve()
            for item in child_imports
        )
        assert service._running is False
        assert service._watcher._thread is None
        assert _serialwrap_log._configured_owner is None
    finally:
        if bridge is not None:
            bridge.stop()
        if service is not None:
            service.stop()
        if master_fd is not None:
            os.close(master_fd)
        shutil.rmtree(runtime_root, ignore_errors=True)

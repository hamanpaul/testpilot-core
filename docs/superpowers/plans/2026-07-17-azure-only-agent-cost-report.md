# Azure-only Agent and Core Cost Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 TestPilot core 收斂成「Azure key 完整即自動啟用、無 key 即 deterministic-only」的 agent runtime，並在不修改 plugin API、plugin source 或 plugin reporter 的前提下，產生 per-case direct token、shared run-analysis token、deterministic/agent-recovery outcome 與 observational benefit cost report。

**Architecture:** CLI 只解析 Azure 環境並建立 secret-safe runtime status；core-owned run loop 在每案 deterministic execution 前執行一次 tool-denied planning，既有 tier-1 deterministic remediation 維持原路徑，tier-2 只有在 plugin 明確覆寫 capability/executor contract 時才使用同一 Azure one-shot adapter。所有 core SDK invocation 與 assistant.usage event 進入 run-scoped append-only ledger；全部 case final verdict 完成後才做 bounded batch/reducer analysis、freeze ledger、由 core 寫 JSON/Markdown artifacts，最後才呼叫既有 plugin reporter 並 additive 附上 artifact pointer。

**Tech Stack:** Python 3.11+、Click、github-copilot-sdk 0.1.x Azure provider adapter、dataclasses/StrEnum、pytest、JSON/Markdown run artifacts、uv lock/offline bundle。

## Global Constraints

- 嚴格限定 testpilot-core repo；不得修改 wifi_llapi 或任何其他 plugin repo、plugin package、agent-config.yaml、case YAML、plugin reporter、PluginBase signature 或 API_VERSION。
- 不操作 serialwrap、DUT、STA、lab state 或任何 live transport；所有測試只用 fake SDK、fake plugin、fake reporter。
- Azure 不得執行或命名 wifi_llapi 的 7 個 safe actions；pre-case planning 與 run analysis完全沒有 tools，tier-2 只能經既有 plugin-advertised schema/executor boundary。
- Azure readiness、deployment 與 provider state不可覆寫 selected runner；ExecutionEngine 傳給 plugin 的 _agent_runner identity保持原值。
- 無 key、misconfigured、SDK/provider failure、timeout、malformed response、analysis failure或core report failure都不得改變 deterministic verdict。
- 第一個 SDK/provider/auth/session failure即打開 run-scoped circuit breaker；malformed用途回應只讓該 invocation失敗，不開 provider breaker。
- Token只採 assistant.usage；session.usage_info僅作 reconciliation。不得以字元、prompt長度或 aggregate shutdown usage估算或重複加總。
- 報表中的 cost欄位固定叫 provider_cost_units；不得宣稱 USD。Cache read/write tokens分欄且不加入 model_tokens。
- 每個 implementation task先寫會因缺少行為而失敗的測試，再做最小實作；完成後立即 commit，不跨 task累積未提交 diff。
- 每個 focused GREEN只證明當前 task；最後一個 task仍必須執行全套 uv run pytest -q 與 python3 -m policy_check --repo .。
- 若 implementation 過程發現 spec需要改動，先停下更新核准規格，不可在 code中悄悄擴張 ownership或 compatibility surface。

---

### Task 1: Azure-only runtime resolution, automatic CLI wiring, and SDK packaging

**Files:**
- Modify: src/testpilot/core/azure_auth.py
- Modify: src/testpilot/cli.py
- Modify: src/testpilot/cli_support.py
- Modify: src/testpilot/core/orchestrator.py
- Modify: src/testpilot/core/copilot_session.py
- Modify: src/testpilot/core/run_loop.py
- Modify: src/testpilot/core/remediation.py
- Modify: pyproject.toml
- Modify: uv.lock
- Modify: tests/test_azure_auth.py
- Create: tests/test_azure_cli.py
- Modify: tests/test_cli_plugin_registration.py
- Modify: tests/test_copilot_session.py
- Modify: tests/test_orchestrator_session_degraded.py
- Modify: tests/test_tier2_recovery_integration.py
- Modify: tests/test_run_loop_session_degraded.py
- Modify: tests/test_wheel_contents.py
- Modify: tests/test_offline_install_integration.sh

**Interfaces:**
- Produces AzureAgentState, AzureAgentStatus, AzureAgentRuntime, resolve_azure_agent_runtime().
- AzureAgentStatus永遠不含 key、endpoint或 provider mapping；AzureAgentRuntime只以 private repr-hidden field暫存 SDK provider config。
- Orchestrator新增 keyword-only agent_runtime，預設為 disabled_no_key；既有 provider_config run參數只保留 source compatibility，不再代表 enable switch。
- CLI不再接受 --azure；COPILOT_PROVIDER_API_KEY、COPILOT_PROVIDER_BASE_URL、COPILOT_MODEL完整時自動 ready。
- 這個 task 必須同時封住所有既有 SDK 入口：disabled/misconfigured 不建 ordinary session 也不建 tier-2 requester；core run loop直接移除舊的 empty ordinary-session call。ready 時在後續 task 取代前仍存在的 tier-2路徑，也必須同時要求 plugin實際覆寫 capability/executor，並強制使用 Azure deployment/provider，不得出現可 fallback OAuth 的中間 commit。

- [ ] **Step 1: Write RED tests for state resolution and secret-safe projection**

Replace the interactive-auth tests with state-table tests:

    def test_no_key_disables_agent_even_when_other_values_exist(monkeypatch):
        monkeypatch.delenv("COPILOT_PROVIDER_API_KEY", raising=False)
        monkeypatch.setenv("COPILOT_PROVIDER_BASE_URL", "https://secret-endpoint.invalid")
        monkeypatch.setenv("COPILOT_MODEL", "deployment-a")

        runtime = resolve_azure_agent_runtime()

        assert runtime.status.state is AzureAgentState.DISABLED_NO_KEY
        assert runtime.sdk_provider_config() is None


    @pytest.mark.parametrize(
        ("endpoint", "deployment", "reason_code"),
        [
            ("", "deployment-a", "missing_endpoint"),
            ("https://example.invalid", "", "missing_deployment"),
            ("", "", "missing_endpoint_and_deployment"),
        ],
    )
    def test_key_with_partial_configuration_is_misconfigured(
        monkeypatch, endpoint, deployment, reason_code
    ):
        monkeypatch.setenv("COPILOT_PROVIDER_API_KEY", "opaque-key-sentinel")
        monkeypatch.setenv("COPILOT_PROVIDER_BASE_URL", endpoint)
        monkeypatch.setenv("COPILOT_MODEL", deployment)

        runtime = resolve_azure_agent_runtime()

        assert runtime.status.state is AzureAgentState.MISCONFIGURED
        assert runtime.status.reason_code == reason_code
        assert runtime.sdk_provider_config() is None


    def test_complete_configuration_is_azure_ready_and_ignores_provider_type(monkeypatch):
        monkeypatch.setenv("COPILOT_PROVIDER_TYPE", "openai")
        monkeypatch.setenv("COPILOT_PROVIDER_API_KEY", "opaque-key-sentinel")
        monkeypatch.setenv(
            "COPILOT_PROVIDER_BASE_URL",
            "https://example.invalid/openai/deployments/x/chat/completions",
        )
        monkeypatch.setenv("COPILOT_MODEL", "azure-deployment")
        monkeypatch.delenv("COPILOT_PROVIDER_AZURE_API_VERSION", raising=False)

        runtime = resolve_azure_agent_runtime()

        assert runtime.status.state is AzureAgentState.AZURE_READY
        assert runtime.status.deployment == "azure-deployment"
        assert runtime.status.api_version == DEFAULT_API_VERSION
        assert runtime.sdk_provider_config()["type"] == "azure"
        public = runtime.public_summary()
        assert public["initial_agent_state"] == "azure_ready"
        assert "opaque-key-sentinel" not in repr(runtime)
        assert "example.invalid" not in repr(runtime)
        assert "opaque-key-sentinel" not in json.dumps(public)
        assert "example.invalid" not in json.dumps(public)


    def test_mark_degraded_preserves_initial_state_and_only_stable_error_type(monkeypatch):
        runtime = _ready_runtime(monkeypatch)
        runtime.mark_degraded("TimeoutError")

        assert runtime.public_summary() == {
            "initial_agent_state": "azure_ready",
            "final_agent_state": "degraded",
            "deployment": "azure-deployment",
            "api_version": DEFAULT_API_VERSION,
            "reason_code": "TimeoutError",
        }

- [ ] **Step 2: Write RED CLI and packaging tests**

Create tests/test_azure_cli.py:

    def test_root_help_has_no_interactive_azure_flag():
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--azure" not in result.output


    def test_no_key_command_remains_deterministic_and_silent(monkeypatch):
        monkeypatch.delenv("COPILOT_PROVIDER_API_KEY", raising=False)
        monkeypatch.setattr(
            "testpilot.cli.PluginLoader.for_entry_points",
            lambda: _EmptyLoader(),
        )
        result = CliRunner().invoke(main, ["list-plugins"])
        assert result.exit_code == 0
        assert "Azure" not in result.output


    def test_partial_azure_configuration_warns_without_values(monkeypatch):
        monkeypatch.setenv("COPILOT_PROVIDER_API_KEY", "opaque-key-sentinel")
        monkeypatch.setenv("COPILOT_PROVIDER_BASE_URL", "https://opaque.invalid")
        monkeypatch.delenv("COPILOT_MODEL", raising=False)
        result = CliRunner().invoke(main, ["list-plugins"])
        assert result.exit_code == 0
        assert "misconfigured" in result.output
        assert "missing_deployment" in result.output
        assert "opaque-key-sentinel" not in result.output
        assert "opaque.invalid" not in result.output


    def test_ready_runtime_is_core_injected_and_plugin_ctx_is_secret_free(monkeypatch):
        captured = {}
        monkeypatch.setenv(
            "COPILOT_PROVIDER_BASE_URL",
            "https://example.invalid",
        )
        monkeypatch.setenv(
            "COPILOT_PROVIDER_API_KEY",
            "opaque-key-sentinel",
        )
        monkeypatch.setenv("COPILOT_MODEL", "azure-deployment")

        class _CapturingOrchestrator:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def discover_plugins(self):
                return []

        monkeypatch.setattr("testpilot.cli_support.Orchestrator", _CapturingOrchestrator)
        click_obj = {"root": ROOT}
        result = CliRunner().invoke(main, ["list-plugins"], obj=click_obj)
        assert result.exit_code == 0
        assert captured["agent_runtime"].status.deployment == "azure-deployment"
        assert "agent_runtime" not in click_obj
        assert click_obj["provider_config"] is None
        assert click_obj["agent_state"]["initial_agent_state"] == "azure_ready"
        assert "opaque-key-sentinel" not in repr(click_obj)
        assert "example.invalid" not in repr(click_obj)


    def test_registered_plugin_command_inherits_no_secret_capability(monkeypatch):
        _set_ready_azure_env(
            monkeypatch,
            key="opaque-key-sentinel",
            endpoint="https://example.invalid",
        )
        visible = {}
        result = _invoke_registered_plugin_command(
            callback=lambda ctx: visible.update(ctx.obj),
        )

        assert result.exit_code == 0
        assert "agent_runtime" not in visible
        assert visible["provider_config"] is None
        assert not any(
            callable(getattr(value, "sdk_provider_config", None))
            for value in visible.values()
        )
        assert "opaque-key-sentinel" not in repr(visible)
        assert "example.invalid" not in repr(visible)

Modify the wheel fixture so its ZipFile remains available, then assert metadata:

    def test_wheel_declares_copilot_sdk_runtime_dependency(wheel):
        metadata_name = next(
            name for name in wheel.namelist()
            if name.endswith(".dist-info/METADATA")
        )
        metadata = wheel.read(metadata_name).decode()
        assert "Requires-Dist: github-copilot-sdk<0.2,>=0.1.23" in metadata

Add a managed-offline smoke after install:

    echo "[INFO] Smoke: mandatory Copilot SDK adapter import"
    "$TP_HOME/.venv/bin/python" -c \
      "from copilot import CopilotSession; from testpilot.core.copilot_session import CopilotSessionManager; assert callable(CopilotSession.send_and_wait); assert callable(CopilotSession.on)"

Add an installed-SDK surface test that cannot be hidden by the shell test's local
network SKIP:

    def test_installed_copilot_sdk_has_required_one_shot_surface():
        from copilot import CopilotSession

        assert callable(CopilotSession.send_and_wait)
        assert callable(CopilotSession.on)

Add minimum Azure-only gate tests before removing the old empty-session path:

    def test_disabled_runtime_builds_no_ordinary_session_plan():
        plan = build_case_session_plan(
            "run-1",
            "D001",
            agent_runtime=_disabled_runtime(),
        )
        assert plan is None


    def test_ready_runtime_plan_forces_azure_deployment_and_provider():
        plan = build_case_session_plan(
            "run-1",
            "D001",
            agent_runtime=_ready_runtime(deployment="azure-deployment"),
        )
        assert plan["model"] == "azure-deployment"
        assert plan["provider_config"]["type"] == "azure"


    def test_no_agent_disables_tier2_requester_and_never_probes_sdk(tmp_path):
        orch = _orchestrator(
            tmp_path,
            runtime=_disabled_runtime(),
            tier2_enabled=True,
        )
        engine = orch._build_execution_engine_for_test()
        assert engine.remediation.tier2_enabled is False
        assert orch.session_manager is None


    def test_intermediate_ready_tier2_request_uses_only_azure_provider(tmp_path):
        orch = _orchestrator(
            tmp_path,
            runtime=_ready_runtime(deployment="azure-deployment"),
            tier2_enabled=True,
        )
        orch._exercise_tier2_requester()
        request = orch.session_manager.requests[0]
        assert request.model == "azure-deployment"
        assert request.provider["type"] == "azure"


    def test_inherited_tier2_hooks_never_create_temporary_requester(tmp_path):
        orch = _orchestrator(
            tmp_path,
            plugin=_DefaultPlugin(),
            runtime=_ready_runtime(),
            tier2_enabled=True,
        )
        _run_failing_case(orch)
        assert orch.session_manager.calls == []


    def test_ready_runtime_sdk_probe_failure_degrades_without_fallback(
        tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            CopilotSessionManager,
            "_load_sdk",
            Mock(side_effect=ModuleNotFoundError("opaque-import-detail")),
        )
        orch = Orchestrator(
            project_root=tmp_path,
            agent_runtime=_ready_runtime(),
        )
        public = orch.agent_runtime.public_summary()
        assert public["initial_agent_state"] == "azure_ready"
        assert public["final_agent_state"] == "degraded"
        assert public["reason_code"] == "ModuleNotFoundError"
        assert orch.session_manager is None
        assert "opaque-import-detail" not in json.dumps(public)

- [ ] **Step 3: Run RED**

Run:

    uv run pytest -q \
      tests/test_azure_auth.py \
      tests/test_azure_cli.py \
      tests/test_cli_plugin_registration.py \
      tests/test_copilot_session.py \
      tests/test_orchestrator_session_degraded.py \
      tests/test_tier2_recovery_integration.py \
      tests/test_run_loop_session_degraded.py \
      tests/test_wheel_contents.py

Expected: FAIL because interactive functions and --azure still exist, COPILOT_PROVIDER_TYPE is still an enable switch, deployment is not required, runtime status types and Azure-only SDK gates do not exist, and the SDK is not a runtime dependency.

- [ ] **Step 4: Implement the secret-safe Azure runtime**

Replace the interactive helper surface in azure_auth.py with:

    class AzureAgentState(StrEnum):
        DISABLED_NO_KEY = "disabled_no_key"
        MISCONFIGURED = "misconfigured"
        AZURE_READY = "azure_ready"
        DEGRADED = "degraded"


    @dataclass(frozen=True, slots=True)
    class AzureAgentStatus:
        state: AzureAgentState
        deployment: str = ""
        api_version: str = DEFAULT_API_VERSION
        reason_code: str = ""

        @property
        def ready(self) -> bool:
            return self.state is AzureAgentState.AZURE_READY


    class AzureAgentRuntime:
        __slots__ = (
            "initial_status",
            "status",
            "_provider_config",
        )

        def __init__(
            self,
            status: AzureAgentStatus,
            provider_config: Mapping[str, Any] | None = None,
        ) -> None:
            self.initial_status = status
            self.status = status
            self._provider_config = (
                dict(provider_config) if provider_config is not None else None
            )

        def __repr__(self) -> str:
            return f"AzureAgentRuntime(status={self.status!r})"

        def sdk_provider_config(self) -> dict[str, Any] | None:
            return (
                dict(self._provider_config)
                if self.status.ready and self._provider_config is not None
                else None
            )

        def mark_degraded(self, error_type: str) -> None:
            self.status = AzureAgentStatus(
                state=AzureAgentState.DEGRADED,
                deployment=self.initial_status.deployment,
                api_version=self.initial_status.api_version,
                reason_code=str(error_type),
            )

        def public_summary(self) -> dict[str, str]:
            return {
                "initial_agent_state": self.initial_status.state.value,
                "final_agent_state": self.status.state.value,
                "deployment": self.status.deployment,
                "api_version": self.status.api_version,
                "reason_code": self.status.reason_code,
            }


    def resolve_azure_agent_runtime(
        environ: Mapping[str, str] | None = None,
    ) -> AzureAgentRuntime:
        source = os.environ if environ is None else environ
        api_key = str(source.get("COPILOT_PROVIDER_API_KEY", "")).strip()
        endpoint = normalize_azure_base_url(
            str(source.get("COPILOT_PROVIDER_BASE_URL", ""))
        )
        deployment = str(source.get("COPILOT_MODEL", "")).strip()
        api_version = (
            str(source.get("COPILOT_PROVIDER_AZURE_API_VERSION", "")).strip()
            or DEFAULT_API_VERSION
        )
        if not api_key:
            return AzureAgentRuntime(
                AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY)
            )
        missing = [
            name
            for name, value in (("endpoint", endpoint), ("deployment", deployment))
            if not value
        ]
        if missing:
            return AzureAgentRuntime(
                AzureAgentStatus(
                    AzureAgentState.MISCONFIGURED,
                    api_version=api_version,
                    reason_code="missing_" + "_and_".join(missing),
                )
            )
        provider = {
            "type": "azure",
            "base_url": endpoint,
            "api_key": api_key,
            "wire_api": "completions",
            "azure": {"api_version": api_version},
        }
        return AzureAgentRuntime(
            AzureAgentStatus(
                AzureAgentState.AZURE_READY,
                deployment=deployment,
                api_version=api_version,
            ),
            provider,
        )

Delete AzureAuthError, prompt_azure_credentials(), export_azure_env(), verify_azure_connectivity(), setup_azure_auth(), the unused urllib.error/urllib.request imports, and tests for those removed surfaces. Retain urllib.parse because normalize_azure_base_url() still uses it.

- [ ] **Step 5: Remove interactive/OAuth routing and inject runtime**

Remove the Click option and azure parameter from main(). At normal subcommand dispatch:

    runtime = resolve_azure_agent_runtime()
    ctx.obj["agent_state"] = runtime.public_summary()
    ctx.obj["provider_config"] = None
    ctx.obj["provider_notice"] = (
        "azure_env" if runtime.status.ready else None
    )
    if runtime.status.state is AzureAgentState.MISCONFIGURED:
        console.print(
            "[yellow]Azure agent support is misconfigured "
            f"({runtime.status.reason_code}); continuing without agent support.[/yellow]"
        )

Extend get_orchestrator() without changing plugin registration:

    return Orchestrator(
        project_root=root,
        agent_runtime=resolve_azure_agent_runtime(),
    )

The legacy provider_config Click-context key remains present only for shape
compatibility and is always None. Never place the private SDK provider mapping,
API key, endpoint or secret-bearing AzureAgentRuntime in plugin-visible ctx.obj.
The root callback uses a short-lived local runtime only to publish its redacted
public_summary()/notice. Core cli_support intentionally resolves the environment
again inside get_orchestrator() and passes that private runtime directly to
Orchestrator; only core-owned call paths access sdk_provider_config(). Registered
plugin commands inherit agent_state, provider_notice and provider_config=None,
but no object exposing a provider accessor.

run_plugin_cases() must stop forwarding the secret-bearing mapping as an execution-path enable signal; the Orchestrator already owns the resolved runtime:

    result = orch.run(
        plugin_name,
        list(case_ids) if case_ids else None,
        dut_fw_ver=dut_fw_ver,
        provider_config=None,
    )

Add the optional runtime to Orchestrator.__init__ and initialize the SDK manager only when ready:

    def __init__(
        self,
        project_root: Path | str | None = None,
        plugins_dir: Path | str | None = None,
        config_path: Path | str | None = None,
        *,
        agent_runtime: AzureAgentRuntime | None = None,
    ) -> None:
        self.root = (
            Path(project_root)
            if project_root
            else Path(__file__).resolve().parents[3]
        )
        self.plugins_dir = (
            Path(plugins_dir)
            if plugins_dir
            else self.root / DEFAULT_PLUGINS_DIR
        )
        config = (
            config_path
            or self.root / DEFAULT_CONFIG_DIR / "testbed.yaml"
        )
        self.config = TestbedConfig(config)
        self.run_backend = create_run_backend(
            self.config.raw.get("testbed", {}).get("run_backend"),
            self.config.raw.get("testbed", {}),
        )
        self._run_handle = None
        self.loader = PluginLoader(self.plugins_dir)
        self.runner_selector = RunnerSelector(self.plugins_dir)
        self.execution_engine = ExecutionEngine(self.config)
        self.agent_runtime = agent_runtime or AzureAgentRuntime(
            AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY)
        )
        self.agent_session_degraded = {
            "degraded": False,
            "reason": "",
        }
        self.session_manager = (
            self._try_init_session_manager()
            if self.agent_runtime.status.ready
            else None
        )

Keep provider_config in Orchestrator.run() and custom runner call signatures for source compatibility, but CLI passes None and core enablement must consult self.agent_runtime.status.ready only. Do not change runner_selector.py.

Make _try_init_session_manager() an instance helper. If its SDK import/surface
probe fails, store only type(exc).__name__, mark the ready runtime degraded and
update agent_session_degraded without exception text; return None and never try a
different provider. Task 3 will turn the same per-run initialization failure into
a circuit-open state before any invocation is started.

In the same task, convert the current ordinary-session planner to the runtime-only
gate so no intermediate commit can create a provider-less session:

    def build_case_session_plan(
        run_id: str,
        case_id: str,
        *,
        agent_runtime: AzureAgentRuntime,
    ) -> dict[str, Any] | None:
        provider = agent_runtime.sdk_provider_config()
        if not agent_runtime.status.ready or provider is None:
            return None
        return {
            "provider": "copilot-sdk-azure",
            "provider_config": provider,
            "session_id": build_session_id(run_id, case_id=case_id),
            "model": agent_runtime.status.deployment,
            "reasoning_effort": "high",
            "status": "planned",
        }

Remove run_loop's build_case_session_plan()/_create_case_session()/active session
cleanup block now; an Azure-ready key must not cause a meaningless empty SDK
session. Keep provider_config out of every public session plan, trace and payload.
Retain build_case_session_plan() for the Task 4 actual planning turn and source
compatibility. Gate legacy _create_case_session() itself on ready state as defense
in depth, and derive both request.model and request.provider from agent_runtime
even if a caller supplies stale plan fields.

Also move the minimum tier-2 runtime/capability gate into this task.
_build_execution_engine() may create its temporary legacy requester only when
agent_runtime is ready, sdk_provider_config() is non-None, and the concrete plugin
class overrides both PluginBase.build_tier2_remediation_context and
PluginBase.execute_tier2_remediation. Do not infer this from tier-1 allowed action
names. Its request model is the Azure deployment and its provider is that private
Azure mapping. RuntimeRemediationCoordinator uses:

    self.tier2_enabled = (
        self.enabled
        and bool(self.tier2_policy.get("enabled", False))
        and self.tier2_requester is not None
    )

Task 5 will replace this temporary requester with the generic controller and
factor the override test into a typed support result. This Task 1 gate is
mandatory independently:
no-key and partial-key commits must already make zero SDK calls, and ready commits
must already have no OAuth/default-provider escape path.

- [ ] **Step 6: Add mandatory SDK dependency and refresh the lock**

Add to project.dependencies:

    "github-copilot-sdk>=0.1.23,<0.2",

Run:

    uv lock
    uv lock --check

Do not hand-edit a third-party allowlist in scripts/build-bundle.sh; its existing first-party wheel metadata closure must discover the SDK dependency.

- [ ] **Step 7: Run GREEN, offline smoke when network is available, and commit**

Run:

    uv run pytest -q \
      tests/test_azure_auth.py \
      tests/test_azure_cli.py \
      tests/test_cli_plugin_registration.py \
      tests/test_predispatch.py \
      tests/test_copilot_session.py \
      tests/test_orchestrator_session_degraded.py \
      tests/test_tier2_recovery_integration.py \
      tests/test_run_loop_session_degraded.py \
      tests/test_wheel_contents.py \
      tests/test_build_bundle_sh.py
    bash tests/test_offline_install_integration.sh
    git diff --check

Expected: all pytest tests PASS, including the installed SDK surface probe. The
shell integration either PASS, or emits its existing explicit local offline SKIP;
CI must hard-fail dependency preparation errors. A local shell SKIP is not proof
of the managed offline install path and must be reported as unverified until a CI
or local PASS is available.

Commit:

    feat(agent): 收斂 Azure-only 自動啟用與 SDK runtime

---

### Task 2: Append-only invocation and authoritative usage ledger

**Files:**
- Create: src/testpilot/core/usage_ledger.py
- Create: tests/test_usage_ledger.py

**Interfaces:**
- UsagePurpose is exactly case_planning, agent_recovery, run_analysis_batch, run_analysis_reducer.
- UsageBinding binds one started invocation to run/session/case/purpose/model.
- UsageLedger.start_invocation() returns a binding before any SDK call.
- UsageLedger.event_handler() never raises into the SDK callback.
- UsageLedger.finish_invocation() appends the terminal lifecycle event.
- UsageLedger.freeze() returns an immutable snapshot and rejects later mutation.

- [ ] **Step 1: Write RED tests for lifecycle, dedupe, validation, and allocation**

Use SDK-object-shaped events, not dict-only fixtures:

    def _usage_event(
        *,
        event_id="event-1",
        api_call_id="call-1",
        input_tokens=100.0,
        output_tokens=20.0,
    ):
        return SimpleNamespace(
            id=event_id,
            timestamp=datetime(2026, 7, 17, tzinfo=timezone.utc),
            type=SimpleNamespace(value="assistant.usage"),
            data=SimpleNamespace(
                api_call_id=api_call_id,
                model="azure-deployment",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=40.0,
                cache_write_tokens=5.0,
                cost=1.25,
                duration=2.5,
            ),
        )


    def test_started_failed_invocation_counts_call_without_usage():
        ledger = UsageLedger()
        binding = ledger.start_invocation(
            run_id="run-1",
            session_id="session-1",
            case_id="D001",
            purpose="case_planning",
            model="azure-deployment",
        )
        ledger.finish_invocation(
            binding,
            status="failed",
            error_type="TimeoutError",
        )

        snapshot = ledger.freeze()
        assert snapshot.call_count(case_id="D001", purpose="case_planning") == 1
        assert snapshot.model_tokens(case_id="D001") == 0
        assert snapshot.invocations[0].usage_status == "unavailable"


    def test_usage_dedupes_by_api_call_then_event_id():
        ledger = UsageLedger()
        binding = _binding(ledger)
        handler = ledger.event_handler(binding)
        handler(_usage_event(event_id="event-1", api_call_id="call-1"))
        handler(_usage_event(event_id="event-2", api_call_id="call-1"))
        handler(_usage_event(event_id="event-1", api_call_id="call-2"))
        ledger.finish_invocation(binding, status="completed")

        snapshot = ledger.freeze()
        assert len(snapshot.usage) == 2
        assert snapshot.duplicate_usage_events == 1
        assert snapshot.usage[0].dedupe_basis == "api_call_id"
        assert snapshot.model_tokens(case_id="D001") == 240
        assert snapshot.usage[0].cache_read_tokens == 40
        assert snapshot.usage[0].provider_cost_units == 1.25
        assert snapshot.usage[0].duration_seconds == 2.5


    def test_event_id_is_fallback_when_api_call_id_missing():
        ledger = UsageLedger()
        binding = _binding(ledger)
        handler = ledger.event_handler(binding)
        handler(_usage_event(event_id="event-1", api_call_id=None))
        handler(_usage_event(event_id="event-1", api_call_id=None))
        ledger.finish_invocation(binding, status="completed")
        snapshot = ledger.freeze()
        assert len(snapshot.usage) == 1
        assert snapshot.duplicate_usage_events == 1
        assert snapshot.usage[0].dedupe_basis == "event_id"


    @pytest.mark.parametrize(
        ("event_id", "api_call_id", "input_tokens"),
        [
            (None, None, 1.0),
            ("event", "call", -1.0),
            ("event", "call", float("nan")),
            ("event", "call", 1.5),
        ],
    )
    def test_invalid_usage_is_rejected_without_raising(
        event_id, api_call_id, input_tokens
    ):
        ledger = UsageLedger()
        binding = _binding(ledger)
        handler = ledger.event_handler(binding)
        handler(_usage_event(
            event_id=event_id,
            api_call_id=api_call_id,
            input_tokens=input_tokens,
        ))
        assert ledger.snapshot().rejected_usage_events == 1


    def test_shared_and_direct_allocation_are_not_mixed():
        ledger = UsageLedger()
        direct = _record_completed(ledger, purpose="agent_recovery", case_id="D001")
        shared = _record_completed(
            ledger, purpose="run_analysis_batch", case_id=None
        )
        snapshot = ledger.freeze()
        assert direct.allocation == "direct"
        assert shared.allocation == "shared"
        assert snapshot.model_tokens(purpose="agent_recovery") == 120
        assert snapshot.model_tokens(purpose="run_analysis_batch") == 120


    def test_session_usage_info_is_reconciliation_only():
        ledger = UsageLedger()
        binding = _binding(ledger)
        handler = ledger.event_handler(binding)
        handler(_session_usage_info_event())
        snapshot = ledger.freeze()
        assert snapshot.model_tokens() == 0
        assert snapshot.reconciliation_events == 1


    def test_freeze_rejects_later_mutation():
        ledger = UsageLedger()
        ledger.freeze()
        with pytest.raises(LedgerFrozenError):
            ledger.start_invocation(
                run_id="run-1",
                session_id="session-1",
                case_id="D001",
                purpose="case_planning",
                model="azure-deployment",
            )

- [ ] **Step 2: Run RED**

Run:

    uv run pytest -q tests/test_usage_ledger.py

Expected: collection FAIL because usage_ledger.py does not exist.

- [ ] **Step 3: Implement exact ledger types**

Use these public dataclasses:

    UsagePurpose = Literal[
        "case_planning",
        "agent_recovery",
        "run_analysis_batch",
        "run_analysis_reducer",
    ]
    UsageAllocation = Literal["direct", "shared"]
    InvocationStatus = Literal["completed", "failed"]
    UsageStatus = Literal["exact", "unavailable"]


    @dataclass(frozen=True, slots=True)
    class UsageBinding:
        invocation_id: str
        run_id: str
        session_id: str
        case_id: str | None
        purpose: UsagePurpose
        model: str
        started_at: str

        @property
        def allocation(self) -> UsageAllocation:
            return (
                "shared"
                if self.purpose.startswith("run_analysis_")
                else "direct"
            )


    @dataclass(frozen=True, slots=True)
    class InvocationRecord:
        invocation_id: str
        run_id: str
        session_id: str
        case_id: str | None
        purpose: UsagePurpose
        allocation: UsageAllocation
        model: str
        started_at: str
        finished_at: str
        status: InvocationStatus
        error_type: str
        usage_status: UsageStatus


    @dataclass(frozen=True, slots=True)
    class UsageRecord:
        invocation_id: str
        session_id: str
        api_call_id: str | None
        event_id: str | None
        dedupe_basis: Literal["api_call_id", "event_id"]
        case_id: str | None
        purpose: UsagePurpose
        allocation: UsageAllocation
        model: str
        input_tokens: int
        output_tokens: int
        cache_read_tokens: int
        cache_write_tokens: int
        provider_cost_units: float | None
        duration_seconds: float | None
        timestamp: str

        @property
        def model_tokens(self) -> int:
            return self.input_tokens + self.output_tokens


    @dataclass(frozen=True, slots=True)
    class UsageSnapshot:
        invocations: tuple[InvocationRecord, ...]
        usage: tuple[UsageRecord, ...]
        journal_lines: tuple[str, ...]
        duplicate_usage_events: int
        rejected_usage_events: int
        reconciliation_events: int

        def call_count(
            self,
            *,
            case_id: str | None = None,
            purpose: UsagePurpose | None = None,
        ) -> int:
            return sum(
                1
                for item in self.invocations
                if (case_id is None or item.case_id == case_id)
                and (purpose is None or item.purpose == purpose)
            )

        def model_tokens(
            self,
            *,
            case_id: str | None = None,
            purpose: UsagePurpose | None = None,
        ) -> int:
            return sum(
                item.model_tokens
                for item in self.usage
                if (case_id is None or item.case_id == case_id)
                and (purpose is None or item.purpose == purpose)
            )

        def case_totals(self, case_id: str) -> dict[str, int]:
            rows = [item for item in self.usage if item.case_id == case_id]
            return {
                "input_tokens": sum(item.input_tokens for item in rows),
                "output_tokens": sum(item.output_tokens for item in rows),
                "model_tokens": sum(item.model_tokens for item in rows),
                "cache_read_tokens": sum(
                    item.cache_read_tokens for item in rows
                ),
                "cache_write_tokens": sum(
                    item.cache_write_tokens for item in rows
                ),
            }


Exact UsageLedger method signatures:

    start_invocation(
        *,
        run_id: str,
        session_id: str,
        case_id: str | None,
        purpose: UsagePurpose,
        model: str,
    ) -> UsageBinding

    event_handler(
        binding: UsageBinding,
    ) -> Callable[[Any], None]

    ingest_event(
        event: Any,
        *,
        binding: UsageBinding,
    ) -> bool

    finish_invocation(
        binding: UsageBinding,
        *,
        status: InvocationStatus,
        error_type: str = "",
    ) -> None

    snapshot() -> UsageSnapshot
    freeze() -> UsageSnapshot

Internally append a sanitized invocation_started journal row in start_invocation(), one usage row per accepted assistant.usage, and an invocation_finished row in finish_invocation(). It is acceptable to keep a private index for folding final records. snapshot()/freeze() must serialize each row with compact, deterministic json.dumps() into immutable journal_lines; events.jsonl writes those strings verbatim, so callers cannot mutate frozen journal content.

assistant.usage normalization must accept enum.value and snake_case SDK attributes. input_tokens/output_tokens must both be present, finite, non-negative integral values; absent cache fields normalize to zero. Optional cost/duration are accepted only when finite and non-negative. Never persist prompt, response, quotaSnapshots, endpoint, key, provider mapping, authorization, raw exception text or session.shutdown aggregates.

UsageRecord.session_id is the stable logical request session ID from UsageBinding. The SDK-reported actual session ID remains cleanup-only and must not replace the binding or destabilize artifact dedupe keys.

Dedupe rule: api_call_id is authoritative when present. event_id is a fallback only when api_call_id is absent; the two namespaces must not cross-dedupe.

    if data.api_call_id:
        dedupe_key = (binding.session_id, str(data.api_call_id))
        dedupe_basis = "api_call_id"
        seen = self._seen_api_calls
    elif event.id:
        dedupe_key = (binding.session_id, str(event.id))
        dedupe_basis = "event_id"
        seen = self._seen_event_ids
    else:
        self._rejected_usage_events += 1
        return False
    if dedupe_key in seen:
        self._duplicate_usage_events += 1
        return False
    seen.add(dedupe_key)

Mark a completed invocation exact only when at least one accepted usage record is bound to it; otherwise usage_status remains unavailable.

- [ ] **Step 4: Run GREEN and commit**

Run:

    uv run pytest -q tests/test_usage_ledger.py
    git diff --check

Expected: PASS.

Commit:

    feat(reporting): 新增 core SDK usage ledger

---

### Task 3: Tool-denied invocation controller and first-failure circuit breaker

**Files:**
- Modify: src/testpilot/core/orchestrator.py
- Modify: src/testpilot/core/copilot_session.py
- Create: tests/test_agent_invocation.py
- Modify: tests/test_copilot_session.py
- Modify: tests/test_orchestrator_session_degraded.py

**Interfaces:**
- Orchestrator._invoke_agent_one_shot() is the only new core call seam for planning, recovery and analysis.
- A started invocation always gets a terminal completed/failed record.
- Provider/SDK/auth/session/timeout/cleanup errors trip the breaker and mark runtime degraded.
- Purpose parser/validator errors finish that call as failed but do not trip the provider breaker.
- Breaker-open and no-agent skips do not call start_invocation() and therefore do not increase calls.

- [ ] **Step 1: Write RED controller tests**

    def test_success_binds_usage_before_session_cleanup():
        manager = _UsageEmittingManager(_usage_event())
        orch = _ready_orchestrator(manager)

        raw, parsed = orch._invoke_agent_one_shot(
            run_id="run-1",
            case_id="D001",
            purpose="case_planning",
            session_id="run-run-1-case-D001-planning-1",
            prompt='{"case_id":"D001"}',
            timeout_seconds=30.0,
            validate=lambda response: json.loads(response),
        )

        assert parsed["risk_summary"] == "bounded"
        snapshot = orch.usage_ledger.snapshot()
        assert snapshot.call_count(
            case_id="D001", purpose="case_planning"
        ) == 1
        assert snapshot.model_tokens(case_id="D001") == 120
        assert manager.events == ["subscribe", "send", "usage", "unsubscribe", "delete"]


    def test_first_provider_failure_opens_breaker_and_later_call_is_not_started():
        manager = _FailingManager(TimeoutError("opaque-secret"))
        orch = _ready_orchestrator(manager)

        with pytest.raises(AgentProviderCallError):
            _invoke(orch, case_id="D001")
        with pytest.raises(AgentCallSkipped) as skipped:
            _invoke(orch, case_id="D002")

        assert skipped.value.reason == "circuit_breaker"
        assert manager.calls == 1
        assert len(orch.usage_ledger.snapshot().invocations) == 1
        assert orch.agent_runtime.public_summary()["initial_agent_state"] == "azure_ready"
        assert orch.agent_runtime.public_summary()["final_agent_state"] == "degraded"
        assert "opaque-secret" not in json.dumps(
            orch.agent_runtime.public_summary()
        )


    @pytest.mark.parametrize(
        ("target", "error"),
        [
            ("request", TypeError("opaque-constructor-detail")),
            ("handler", RuntimeError("opaque-handler-detail")),
        ],
    )
    def test_post_start_setup_failure_finishes_invocation_and_opens_breaker(
        monkeypatch, target, error
    ):
        manager = _UsageEmittingManager(_usage_event())
        orch = _ready_orchestrator(manager)
        if target == "request":
            monkeypatch.setattr(
                "testpilot.core.orchestrator.CopilotSessionRequest",
                Mock(side_effect=error),
            )
        else:
            monkeypatch.setattr(
                UsageLedger,
                "event_handler",
                Mock(side_effect=error),
            )

        with pytest.raises(AgentProviderCallError) as failed:
            _invoke(orch, case_id="D001")

        invocation = orch.usage_ledger.snapshot().invocations[0]
        assert failed.value.error_type == type(error).__name__
        assert invocation.status == "failed"
        assert invocation.error_type == type(error).__name__
        assert orch.agent_circuit_open is True
        assert manager.calls == 0
        public = json.dumps(orch.agent_runtime.public_summary())
        assert "opaque-constructor-detail" not in public
        assert "opaque-handler-detail" not in public


    def test_malformed_response_does_not_trip_provider_breaker():
        manager = _SequenceManager(["not-json", VALID_JSON])
        orch = _ready_orchestrator(manager)

        with pytest.raises(AgentResponseValidationError):
            _invoke(orch, case_id="D001", validate=json.loads)
        _invoke(orch, case_id="D002", validate=json.loads)

        assert manager.calls == 2
        assert orch.agent_circuit_open is False
        assert orch.agent_runtime.status.state is AzureAgentState.AZURE_READY


    def test_reset_run_state_replaces_ledger_and_closes_breaker():
        orch = _ready_orchestrator(_FailingManager(TimeoutError()))
        with pytest.raises(AgentProviderCallError):
            _invoke(orch, case_id="D001")
        old_ledger = orch.usage_ledger

        orch._reset_run_state()

        assert orch.usage_ledger is not old_ledger
        assert orch.usage_ledger.snapshot().invocations == ()
        assert orch.agent_circuit_open is False


    def test_disabled_runtime_never_initializes_or_calls_sdk(monkeypatch, tmp_path):
        load_sdk = Mock(side_effect=AssertionError("must not probe SDK"))
        monkeypatch.setattr(CopilotSessionManager, "_load_sdk", load_sdk)
        orch = Orchestrator(project_root=tmp_path, agent_runtime=_disabled_runtime())
        with pytest.raises(AgentCallSkipped) as skipped:
            _invoke(orch, case_id="D001")
        assert skipped.value.reason == "no_agent"
        load_sdk.assert_not_called()


    def test_ready_sdk_initialization_failure_opens_run_breaker_without_call(
        monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            CopilotSessionManager,
            "_load_sdk",
            Mock(side_effect=ImportError("opaque-import-detail")),
        )
        orch = Orchestrator(
            project_root=tmp_path,
            agent_runtime=_ready_runtime(),
        )
        orch._reset_run_state()

        with pytest.raises(AgentCallSkipped) as skipped:
            _invoke(orch, case_id="D001")

        assert skipped.value.reason == "circuit_breaker"
        assert orch.agent_circuit_open is True
        assert orch.agent_circuit_error_type == "ImportError"
        assert orch.usage_ledger.snapshot().invocations == ()
        assert "opaque-import-detail" not in json.dumps(
            orch.agent_runtime.public_summary()
        )

- [ ] **Step 2: Extend adapter tests for real event subscription order and generic wording**

Update the fake SDK session so send_and_wait() dispatches usage events to current handlers. Keep existing timeout abort, actual-session delete and cleanup precedence tests. Add assertions that:

    assert "on_event" not in client.created_config
    assert fake_session.handler_count_during_send == 1
    assert fake_session.handler_count_after_send == 0

Update one-shot compatibility errors/docstrings from tier-2-specific wording to purpose-neutral one-shot wording; the adapter itself must not know case planning, recovery or analysis.

- [ ] **Step 3: Run RED**

Run:

    uv run pytest -q \
      tests/test_agent_invocation.py \
      tests/test_copilot_session.py \
      tests/test_orchestrator_session_degraded.py

Expected: FAIL because Orchestrator has no ledger, no breaker, no generic invocation helper, and currently initializes the manager independent of the new runtime state.

- [ ] **Step 4: Implement run-scoped state and typed errors**

In orchestrator.py:

    T = TypeVar("T")


    class AgentCallSkipped(RuntimeError):
        def __init__(self, reason: Literal["no_agent", "circuit_breaker"]):
            super().__init__(reason)
            self.reason = reason


    class AgentProviderCallError(RuntimeError):
        """Provider/SDK/session failure that opens the run circuit."""

        def __init__(self, error_type: str):
            super().__init__(error_type)
            self.error_type = error_type


    class AgentResponseValidationError(ValueError):
        """Purpose-schema rejection that leaves the provider circuit closed."""

        def __init__(self, error_type: str):
            super().__init__(error_type)
            self.error_type = error_type


    def _reset_run_state(self) -> None:
        self.agent_session_degraded = {"degraded": False, "reason": ""}
        self.usage_ledger = UsageLedger()
        self.agent_circuit_open = False
        self.agent_circuit_error_type = ""
        self.agent_runtime.reset_to_initial()

        if (
            self.agent_runtime.status.ready
            and self.session_manager is None
        ):
            self.session_manager = self._try_init_session_manager()
            if not self.agent_runtime.status.ready:
                self.agent_circuit_open = True
                self.agent_circuit_error_type = (
                    self.agent_runtime.status.reason_code
                )

Call self._reset_run_state() once at the end of Orchestrator.__init__ and again at the existing start of Orchestrator.run(). Add reset_to_initial() to AzureAgentRuntime so a reused Orchestrator begins each run from the env-derived initial status. Do not re-enable SDK sessions for an initially disabled/misconfigured runtime.

- [ ] **Step 5: Implement the one-shot controller**

    def _invoke_agent_one_shot(
        self,
        *,
        run_id: str,
        case_id: str | None,
        purpose: UsagePurpose,
        session_id: str,
        prompt: str,
        timeout_seconds: float,
        validate: Callable[[str], T],
    ) -> tuple[str, T]:
        if self.agent_circuit_open:
            raise AgentCallSkipped("circuit_breaker")
        if not self.agent_runtime.status.ready:
            raise AgentCallSkipped("no_agent")

        binding = self.usage_ledger.start_invocation(
            run_id=run_id,
            session_id=session_id,
            case_id=case_id,
            purpose=purpose,
            model=self.agent_runtime.status.deployment,
        )
        try:
            provider = self.agent_runtime.sdk_provider_config()
            if provider is None:
                raise CopilotSDKUnavailableError(
                    "Azure provider config is unavailable"
                )
            on_event = self.usage_ledger.event_handler(binding)
            request = CopilotSessionRequest(
                session_id=session_id,
                model=self.agent_runtime.status.deployment,
                reasoning_effort="high",
                provider=provider,
                on_event=on_event,
            )
            if self.session_manager is None:
                raise CopilotSDKUnavailableError(
                    "Copilot SDK one-shot manager is unavailable"
                )
            raw = self.session_manager.send_one_shot(
                request,
                prompt,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            error_type = type(exc).__name__
            self.usage_ledger.finish_invocation(
                binding,
                status="failed",
                error_type=error_type,
            )
            self.agent_circuit_open = True
            self.agent_circuit_error_type = error_type
            self.agent_runtime.mark_degraded(error_type)
            self._record_agent_session_failure(
                exc,
                warning="Azure SDK one-shot failed; later agent calls are disabled",
            )
            raise AgentProviderCallError(error_type) from None

        try:
            parsed = validate(raw)
        except Exception as exc:
            error_type = type(exc).__name__
            self.usage_ledger.finish_invocation(
                binding,
                status="failed",
                error_type=error_type,
            )
            raise AgentResponseValidationError(error_type) from None

        self.usage_ledger.finish_invocation(binding, status="completed")
        return raw, parsed

Everything after start_invocation() through provider lookup, event-handler
creation, request construction, send and adapter cleanup belongs to the same
provider/setup failure boundary. Therefore every started invocation receives
exactly one terminal record, and no post-start setup exception can escape the
planning/recovery/analysis fail-soft callers.

The controller must not log raw exception text. _record_agent_session_failure() must preserve its existing warn-once behavior but derive public state solely from type(exc).__name__.

- [ ] **Step 6: Run GREEN and commit**

Run:

    uv run pytest -q \
      tests/test_agent_invocation.py \
      tests/test_copilot_session.py \
      tests/test_orchestrator_session_degraded.py
    git diff --check

Expected: PASS.

Commit:

    feat(agent): 統一 one-shot 計量與 run circuit breaker

---

### Task 4: Actual per-case Azure planning before deterministic execution

**Files:**
- Create: src/testpilot/core/case_planning.py
- Create: tests/test_case_planning.py
- Modify: src/testpilot/core/orchestrator.py
- Modify: src/testpilot/core/run_loop.py
- Modify: src/testpilot/core/copilot_session.py
- Modify: tests/test_copilot_session.py
- Modify: tests/test_run_loop_session_degraded.py
- Create: tests/test_run_loop_case_planning.py

**Interfaces:**
- build_case_planning_prompt() accepts only bounded/redacted case metadata, a filtered execution policy and non-sensitive run metadata.
- parse_case_planning_response() accepts one strict JSON object and returns CasePlanningAdvisory.
- CasePlanningResult.status is exactly completed, failed, skipped_no_agent or skipped_circuit_breaker.
- Orchestrator._plan_case() makes at most one actual one-shot attempt for a case and never mutates its inputs.
- run_loop invokes planning after selected_runner is known but before _build_execution_engine() and deterministic execute_with_retry().

- [ ] **Step 1: Write RED prompt/parser tests**

    def test_prompt_is_bounded_redacted_and_has_no_control_authority():
        case = {
            "id": "D001",
            "name": "ModeEnabled",
            "bands": ["5g"],
            "api_key": "opaque-key-sentinel",
            "steps": [{
                "id": "s1",
                "command": "get ModeEnabled password=opaque-password",
                "capture": ["ModeEnabled"],
            }],
            "pass_criteria": ["ModeEnabled == 1"],
        }
        original = deepcopy(case)

        prompt = build_case_planning_prompt(
            case=case,
            execution_policy={
                "mode": "sequential",
                "retry": {"max_attempts": 3},
                "private": "opaque-policy-secret",
            },
            run_metadata={
                "run_id": "run-1",
                "plugin_name": "fake",
                "case_ordinal": 1,
                "case_count": 2,
            },
        )

        assert len(prompt) <= 24_000
        assert case == original
        assert "opaque-key-sentinel" not in prompt
        assert "opaque-password" not in prompt
        assert "opaque-policy-secret" not in prompt
        assert "cannot change runner" in prompt
        assert '"risk_summary"' in prompt
        assert '"expected_observations"' in prompt


    def test_parser_accepts_only_fixed_schema():
        advisory = parse_case_planning_response(json.dumps({
            "risk_summary": "watch timeout",
            "attention_points": ["band association"],
            "expected_observations": ["ModeEnabled readback"],
        }))
        assert advisory.risk_summary == "watch timeout"
        assert advisory.attention_points == ("band association",)


    @pytest.mark.parametrize(
        "raw",
        [
            "not json",
            '{"risk_summary":"x","attention_points":[]}',
            '{"risk_summary":"x","attention_points":[],"expected_observations":[],"retry":9}',
            '{"risk_summary":"","attention_points":[],"expected_observations":[]}',
        ],
    )
    def test_parser_rejects_malformed_or_authoritative_output(raw):
        with pytest.raises(CasePlanningValidationError):
            parse_case_planning_response(raw)

- [ ] **Step 2: Write RED run-loop ordering and state tests**

Use two fake cases and an event list:

    def test_ready_runtime_plans_each_case_before_execution_and_uses_deployment(
        tmp_path
    ):
        events = []
        orch = _PlanningOrchestrator(
            tmp_path,
            cases=[_case("D001"), _case("D002")],
            events=events,
            runtime=_ready_runtime(deployment="azure-deployment"),
        )

        payload = run_loop.run(orch, "fake", None, None)

        assert events == [
            "plan:D001",
            "build_engine:D001",
            "execute:D001",
            "plan:D002",
            "build_engine:D002",
            "execute:D002",
        ]
        assert [request.model for request in orch.manager.requests] == [
            "azure-deployment",
            "azure-deployment",
        ]
        assert payload["status"] == "ok"


    def test_planning_is_advisory_and_selected_runner_identity_is_preserved(tmp_path):
        orch = _PlanningOrchestrator(
            tmp_path,
            selected_runner={
                "id": "plugin-runner",
                "cli_agent": "copilot",
                "model": "plugin-model-label",
                "effort": "low",
            },
            runtime=_ready_runtime(deployment="azure-deployment"),
        )
        run_loop.run(orch, "fake", None, None)

        assert orch.manager.requests[0].model == "azure-deployment"
        assert orch.executed_runners[0]["model"] == "plugin-model-label"
        trace = _read_trace(tmp_path, "D001")
        assert trace["selection_trace"]["selected"]["model"] == "plugin-model-label"
        assert trace["case_planning"]["status"] == "completed"
        assert "_agent_runner" not in trace["case_planning"]


    def test_no_key_records_skipped_no_agent_and_makes_zero_sdk_calls(tmp_path):
        orch = _PlanningOrchestrator(
            tmp_path,
            cases=[_case("D001")],
            runtime=_disabled_runtime(),
        )
        run_loop.run(orch, "fake", None, None)
        trace = _trace(tmp_path, "D001")
        assert trace["case_planning"]["status"] == "skipped_no_agent"
        assert orch.manager.calls == 0
        assert orch.execute_calls == 1


    def test_first_planning_provider_failure_skips_later_cases_via_breaker(tmp_path):
        orch = _PlanningOrchestrator(
            tmp_path,
            cases=[_case("D001"), _case("D002")],
            runtime=_ready_runtime(),
            manager=_FailingThenValidManager(TimeoutError()),
        )
        run_loop.run(orch, "fake", None, None)
        assert _trace(tmp_path, "D001")["case_planning"]["status"] == "failed"
        assert (
            _trace(tmp_path, "D002")["case_planning"]["status"]
            == "skipped_circuit_breaker"
        )
        assert orch.manager.calls == 1
        assert orch.execute_calls == 2
        assert orch.usage_ledger.snapshot().call_count(
            purpose="case_planning"
        ) == 1


    def test_malformed_planning_does_not_skip_next_case(tmp_path):
        orch = _PlanningOrchestrator(
            tmp_path,
            cases=[_case("D001"), _case("D002")],
            runtime=_ready_runtime(),
            manager=_SequenceManager(["not-json", VALID_PLANNING_JSON]),
        )
        run_loop.run(orch, "fake", None, None)
        assert _trace(tmp_path, "D001")["case_planning"]["status"] == "failed"
        assert _trace(tmp_path, "D002")["case_planning"]["status"] == "completed"
        assert orch.manager.calls == 2


    def test_local_prompt_validation_failure_is_fail_soft(
        tmp_path, monkeypatch
    ):
        orch = _PlanningOrchestrator(
            tmp_path,
            cases=[_case("D001")],
            runtime=_ready_runtime(),
        )
        monkeypatch.setattr(
            "testpilot.core.orchestrator.build_case_planning_prompt",
            Mock(
                side_effect=CasePlanningValidationError(
                    "bounded local validation failure"
                )
            ),
        )

        run_loop.run(orch, "fake", None, None)

        trace = _trace(tmp_path, "D001")
        assert trace["case_planning"]["status"] == "failed"
        assert trace["case_planning"]["error_type"] == (
            "CasePlanningValidationError"
        )
        assert orch.manager.calls == 0
        assert orch.execute_calls == 1
        assert orch.agent_circuit_open is False

- [ ] **Step 3: Run RED**

Run:

    uv run pytest -q \
      tests/test_case_planning.py \
      tests/test_run_loop_case_planning.py \
      tests/test_run_loop_session_degraded.py

Expected: FAIL because case_planning.py and the actual pre-case turn do not exist;
Task 1 already removed the empty ordinary-session call.

- [ ] **Step 4: Implement bounded planning types**

    PlanningStatus = Literal[
        "completed",
        "failed",
        "skipped_no_agent",
        "skipped_circuit_breaker",
    ]


    @dataclass(frozen=True, slots=True)
    class CasePlanningAdvisory:
        risk_summary: str
        attention_points: tuple[str, ...]
        expected_observations: tuple[str, ...]

        def to_dict(self) -> dict[str, Any]:
            return {
                "risk_summary": self.risk_summary,
                "attention_points": list(self.attention_points),
                "expected_observations": list(self.expected_observations),
            }


    @dataclass(frozen=True, slots=True)
    class CasePlanningResult:
        status: PlanningStatus
        advisory: CasePlanningAdvisory | None = None
        error_type: str = ""

        def to_trace_dict(self) -> dict[str, Any]:
            return {
                "status": self.status,
                "advisory": (
                    self.advisory.to_dict()
                    if self.advisory is not None
                    else None
                ),
                "error_type": self.error_type,
            }

Exact function signatures:

    build_case_planning_prompt(
        *,
        case: Mapping[str, Any],
        execution_policy: Mapping[str, Any],
        run_metadata: Mapping[str, Any],
    ) -> str

    parse_case_planning_response(
        raw_response: str,
    ) -> CasePlanningAdvisory

Use a fixed allowlist:

    case_payload = {
        "id": bounded(case.get("id"), 200),
        "name": bounded(case.get("name"), 500),
        "bands": bounded_string_list(case.get("bands"), limit=8),
        "steps": summarize_steps(case.get("steps"), max_items=32),
        "pass_criteria": bounded_string_list(
            case.get("pass_criteria"), limit=32, item_chars=500
        ),
    }
    policy_payload = {
        key: sanitized_copy(execution_policy[key])
        for key in (
            "mode",
            "max_concurrency",
            "retry",
            "timeout",
            "failure_policy",
        )
        if key in execution_policy
    }

Reject unknown response keys and secret-like output. Bound risk_summary to 2,000 characters, each list to 16 entries and each entry to 1,000 characters. The final prompt hard limit is 24,000 characters, safely below send_one_shot()'s 64,000-character limit.
Normalize mapping, redaction, serialization and size-limit failures raised while
building the local prompt to CasePlanningValidationError. These failures happen
before start_invocation(), never open the provider breaker and must remain
fail-soft so deterministic execution still runs.

- [ ] **Step 5: Add _plan_case() and remove empty-session behavior**

Task 1 already converted build_case_session_plan() to a runtime-only Azure gate
and removed the empty run-loop session so every intermediate commit is
provider-safe. Update the plan's session ID to the purpose-aware form below and
use it only as metadata for the actual one-shot invocation. If the legacy private
Orchestrator._create_case_session() remains for source compatibility, retain the
Task 1 ready-state gate and force both request.model and request.provider from
agent_runtime; the core run loop must not call it.

    def _plan_case(
        self,
        *,
        run_id: str,
        plugin_name: str,
        case: Mapping[str, Any],
        case_ordinal: int,
        case_count: int,
        execution_policy: Mapping[str, Any],
    ) -> CasePlanningResult:
        if self.agent_circuit_open:
            return CasePlanningResult(status="skipped_circuit_breaker")
        if not self.agent_runtime.status.ready:
            return CasePlanningResult(status="skipped_no_agent")

        case_id = str(case.get("id", "?"))
        session_plan = build_case_session_plan(
            run_id,
            case_id,
            agent_runtime=self.agent_runtime,
        )
        if session_plan is None:
            return CasePlanningResult(status="skipped_no_agent")
        try:
            prompt = build_case_planning_prompt(
                case=case,
                execution_policy=execution_policy,
                run_metadata={
                    "run_id": run_id,
                    "plugin_name": plugin_name,
                    "case_ordinal": case_ordinal,
                    "case_count": case_count,
                },
            )
            _, advisory = self._invoke_agent_one_shot(
                run_id=run_id,
                case_id=case_id,
                purpose="case_planning",
                session_id=str(session_plan["session_id"]),
                prompt=prompt,
                timeout_seconds=60.0,
                validate=parse_case_planning_response,
            )
        except AgentCallSkipped as exc:
            return CasePlanningResult(
                status=(
                    "skipped_circuit_breaker"
                    if exc.reason == "circuit_breaker"
                    else "skipped_no_agent"
                )
            )
        except CasePlanningValidationError as exc:
            return CasePlanningResult(
                status="failed",
                error_type=type(exc).__name__,
            )
        except (AgentProviderCallError, AgentResponseValidationError) as exc:
            return CasePlanningResult(
                status="failed",
                error_type=exc.error_type,
            )
        return CasePlanningResult(status="completed", advisory=advisory)

Extend build_session_id() additively:

    def build_session_id(
        run_id: str,
        *,
        case_id: str | None = None,
        remediate_attempt: int | None = None,
        purpose: str | None = None,
        invocation_index: int | None = None,
    ) -> str:
        session_id = f"run-{_sanitize_session_component(run_id)}"
        if case_id:
            session_id += f"-case-{_sanitize_session_component(case_id)}"
        if remediate_attempt is not None:
            session_id += f"-remediate-{int(remediate_attempt)}"
        elif purpose:
            session_id += f"-{_sanitize_session_component(purpose)}"
            if invocation_index is not None:
                session_id += f"-{int(invocation_index)}"
        return session_id

Retain remediate_attempt compatibility. New planning and analysis suffixes must be sanitized exactly like existing components.

In run_loop, retain Task 1's removal of the
_create_case_session()/active_session_id/_cleanup_case_session() block. The loop
order becomes:

    for case_ordinal, case in enumerate(cases, start=1):
        case_id = str(case.get("id", "?"))
        selected_runner, selection_trace = (
            orchestrator.runner_selector.select_case_runner(
                plugin_name=plugin_name,
                case=case,
                agent_config=agent_config,
            )
        )
        planning = orchestrator._plan_case(
            run_id=run_id,
            plugin_name=plugin_name,
            case=case,
            case_ordinal=case_ordinal,
            case_count=len(cases),
            execution_policy=execution_policy,
        )
        planning_by_case[case_id] = planning
        orchestrator._build_execution_engine(
            plugin_name=plugin_name,
            plugin=plugin,
            agent_config=agent_config,
            run_id=run_id,
            case_id=case_id,
            runner=selected_runner,
            provider_config=None,
        )
        retry_result = orchestrator.execution_engine.execute_with_retry(
            plugin=plugin,
            case=case,
            runner=selected_runner,
            execution_policy=execution_policy,
        )

Pass planning_result into _build_case_trace_payload() and add only:

    "case_planning": planning_result.to_trace_dict(),

Do not add planning output to case, execution_policy, selected_runner or RunResult.

- [ ] **Step 6: Run GREEN and commit**

Run:

    uv run pytest -q \
      tests/test_case_planning.py \
      tests/test_run_loop_case_planning.py \
      tests/test_run_loop_session_degraded.py \
      tests/test_copilot_session.py \
      tests/test_orchestrator_retry.py
    git diff --check

Expected: PASS.

Commit:

    feat(agent): 新增每案唯讀 Azure planning

---

### Task 5: Azure-only tier-2 gating, plugin capability detection, and fail-soft recovery usage

**Files:**
- Modify: src/testpilot/core/orchestrator.py
- Modify: src/testpilot/core/remediation.py
- Modify: tests/test_remediation.py
- Modify: tests/test_tier2_recovery_integration.py
- Create: tests/test_agent_recovery_gate.py

**Interfaces:**
- tier2_support(plugin, remediation_policy) returns supported plus a stable reason.
- supported=true requires effective remediation.enabled, tier2.enabled and both PluginBase methods overridden.
- _build_execution_engine() creates a requester only when support is true and Azure is currently ready.
- Agent recovery model is always Azure deployment; selected runner remains only plugin execution identity.
- Recovery purpose is exactly agent_recovery.
- A failure before plugin executor invocation is audited and continues deterministic retry; an executor mutation or failed deterministic verify_env remains fail-closed.

- [ ] **Step 1: Write RED support/gate tests**

    @pytest.mark.parametrize(
        ("plugin", "policy", "supported", "reason"),
        [
            (
                _DefaultPlugin(),
                _tier2_policy(enabled=True),
                False,
                "plugin_capability_unavailable",
            ),
            (
                _ContextOnlyPlugin(),
                _tier2_policy(enabled=True),
                False,
                "plugin_executor_unavailable",
            ),
            (
                _Tier2Plugin(),
                _tier2_policy(enabled=False),
                False,
                "tier2_policy_disabled",
            ),
            (
                _Tier2Plugin(),
                _tier2_policy(enabled=True),
                True,
                "",
            ),
        ],
    )
    def test_tier2_support_requires_policy_and_both_overrides(
        plugin, policy, supported, reason
    ):
        result = tier2_support(plugin, policy)
        assert result.supported is supported
        assert result.reason == reason


    def test_unsupported_plugin_never_creates_recovery_requester():
        engine = orch._build_execution_engine(
            plugin_name="fake",
            plugin=_DefaultPlugin(),
            agent_config=_tier2_agent_config(),
            run_id="run-1",
            case_id="D001",
            runner={"id": "plugin-runner", "model": "plugin-model"},
            provider_config=None,
        )
        assert orch.agent_recovery_support["D001"].to_dict() == {
            "supported": False,
            "reason": "plugin_capability_unavailable",
        }
        assert engine.hooks.handlers_for("on_retry")
        assert orch.manager.calls_for("agent_recovery") == 0


    def test_tier1_action_names_never_become_agent_capabilities_or_tools():
        plugin = _DefaultPluginWithTier1Policy(
            allowed_actions=[
                "serial_session_recover",
                "sta_band_reconnect",
                "sta_band_rebaseline",
                "dut_band_rebaseline",
                "case_env_reverify",
                "dut_reboot",
                "dut_firstboot",
            ]
        )
        _run_case(plugin=plugin, runtime=_ready_runtime())

        assert orch.manager.calls_for("agent_recovery") == 0
        planning_request = orch.manager.requests_by_purpose["case_planning"][0]
        assert planning_request.available_tools == ()
        assert planning_request.mcp_servers is None
        assert all(
            action not in orch.manager.prompts[0]
            for action in plugin.allowed_actions
        )


    def test_no_agent_keeps_deterministic_tier1_and_does_not_fail_tier2():
        result = _run_failing_then_passing_case(
            plugin=_Tier2Plugin(),
            runtime=_disabled_runtime(),
        )
        assert plugin.tier1_calls >= 1
        assert plugin.tier2_calls == 0
        assert result.verdict is True
        assert result.tier2_audit == []


    def test_recovery_uses_azure_deployment_not_selected_runner_model():
        result = _run_tier2(
            runtime=_ready_runtime(deployment="azure-deployment"),
            selected_runner={"model": "plugin-model", "effort": "low"},
        )
        request = orch.manager.requests_by_purpose["agent_recovery"][0]
        assert request.model == "azure-deployment"
        assert plugin.context_runners[0]["model"] == "plugin-model"
        assert result.agent_recovered is True
        assert orch.usage_ledger.snapshot().call_count(
            case_id="D001", purpose="agent_recovery"
        ) == 1


    def test_provider_failure_before_executor_does_not_halt_deterministic_retry():
        result = _run_tier2(
            manager=_FailingManager(TimeoutError()),
            later_attempt_verdict=True,
        )
        assert result.verdict is True
        assert plugin.tier2_calls == 0
        assert result.tier2_audit[0]["status"] == "failed"
        assert result.tier2_audit[0]["verify_gate"]["executed"] is False
        assert orch.agent_circuit_open is True


    def test_invalid_plan_does_not_open_breaker_or_halt_retry():
        result = _run_tier2(
            manager=_ManagerReturning("not-json"),
            later_attempt_verdict=True,
        )
        assert result.verdict is True
        assert orch.agent_circuit_open is False
        assert result.tier2_audit[0]["status"] == "rejected"


    def test_executor_or_verify_gate_failure_remains_fail_closed():
        result = _run_tier2(
            manager=_ValidManager(),
            plugin=_Tier2Plugin(verify_gate=False),
        )
        assert result.verdict is False
        assert result.tier2_audit[0]["verify_gate"]["passed"] is False

- [ ] **Step 2: Run RED**

Run:

    uv run pytest -q \
      tests/test_agent_recovery_gate.py \
      tests/test_remediation.py \
      tests/test_tier2_recovery_integration.py

Expected: FAIL because current tier-2 enablement only checks config, uses runner.model, treats inherited no-op methods as support, does not bind usage, and halts retry on any requester/parse failure.

- [ ] **Step 3: Implement support detection without changing PluginBase**

    @dataclass(frozen=True, slots=True)
    class Tier2Support:
        supported: bool
        reason: str = ""

        def to_dict(self) -> dict[str, Any]:
            return {
                "supported": self.supported,
                "reason": self.reason,
            }


    def tier2_support(
        plugin: Any,
        remediation_policy: Mapping[str, Any],
    ) -> Tier2Support:
        if not bool(remediation_policy.get("enabled", False)):
            return Tier2Support(False, "remediation_policy_disabled")
        tier2 = remediation_policy.get("tier2", {})
        if not isinstance(tier2, Mapping) or not bool(tier2.get("enabled", False)):
            return Tier2Support(False, "tier2_policy_disabled")
        if (
            type(plugin).build_tier2_remediation_context
            is PluginBase.build_tier2_remediation_context
        ):
            return Tier2Support(False, "plugin_capability_unavailable")
        if (
            type(plugin).execute_tier2_remediation
            is PluginBase.execute_tier2_remediation
        ):
            return Tier2Support(False, "plugin_executor_unavailable")
        return Tier2Support(True)

Do not infer support from tier-1 allowed_actions or execute_remediation().

Extend Orchestrator._reset_run_state() in this task with:

    self.agent_recovery_support: dict[str, Tier2Support] = {}

- [ ] **Step 4: Gate the requester and bind recovery usage**

At each case engine build:

    support = tier2_support(plugin, remediation_policy)
    self.agent_recovery_support[case_id] = support
    tier2_requester = None
    if support.supported and self.agent_runtime.status.ready:
        tier2_requester = _request_tier2_plan

The requester:

    def _request_tier2_plan(
        prompt: str,
        context: dict[str, Any],
    ) -> str | None:
        nonlocal remediation_invocation
        remediation_invocation += 1
        normalized_context = Tier2RecoveryContext.from_mapping(context)

        def _validate(raw: str) -> dict[str, Any]:
            return parse_tier2_plan(
                raw,
                capability_schemas=normalized_context.capability_schemas,
                max_actions=max(
                    0,
                    _safe_int(tier2_policy.get("max_actions"), 3),
                ),
            )

        raw, _ = self._invoke_agent_one_shot(
            run_id=run_id,
            case_id=case_id,
            purpose="agent_recovery",
            session_id=build_session_id(
                run_id,
                case_id=case_id,
                remediate_attempt=remediation_invocation,
            ),
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            validate=_validate,
        )
        return raw

RuntimeRemediationCoordinator must receive requester=None when Azure is disabled, misconfigured, degraded or circuit-open at engine build. Change its effective flag:

    self.tier2_enabled = (
        self.enabled
        and bool(self.tier2_policy.get("enabled", False))
        and self.tier2_requester is not None
    )

This does not disable tier-1 deterministic remediation.

- [ ] **Step 5: Split pre-execution unavailable from post-execution fail-closed**

Add tier2_disabled_for_case=False to per-case coordinator state. Replace pre-executor calls to _fail_tier2() for context/request/response/plan failure with:

    def _skip_tier2_before_execution(
        self,
        *,
        ctx: HookContext,
        data: dict[str, Any],
        state: dict[str, Any],
        audit: Tier2RecoveryAudit,
        error: str,
        status: str,
    ) -> HookResult:
        audit.status = status
        audit.error = str(sanitize_tier2_value(error))
        audit.verify_gate = {
            "passed": False,
            "executed": False,
            "error": "tier-2 flow halted before plugin executor",
        }
        state["tier2_audit"].append(audit.to_dict())
        state["tier2_disabled_for_case"] = True
        state["tier1_failure_streak"] = 0
        self._project_state(state, data)
        return HookResult(
            proceed=True,
            advice="tier-2 unavailable; continuing deterministic retry",
        )

Add not state["tier2_disabled_for_case"] to both escalation conditions. Keep _fail_tier2() and proceed=False for failures after plugin executor invocation, test-semantics guard violations and deterministic verify_env gate failures.

AgentProviderCallError maps to audit status failed; AgentResponseValidationError/Tier2PlanValidationError maps to rejected. Store only the stable type name.

- [ ] **Step 6: Update integration call ordering**

The existing tier-2 integration now has two model calls for its single case:

    purposes = [
        invocation.purpose
        for invocation in orchestrator.usage_ledger.snapshot().invocations
    ]
    assert purposes == ["case_planning", "agent_recovery"]

Update the fake manager to return purpose-appropriate planning JSON first and a valid tier-2 plan second, and emit one assistant.usage event for each. Assert:

    assert planning_request.model == "azure-deployment"
    assert recovery_request.model == "azure-deployment"
    assert trace["selection_trace"]["selected"]["model"] == "plugin-model"
    assert "provider_config" not in trace_text
    assert "opaque-key-sentinel" not in trace_text

- [ ] **Step 7: Run GREEN and commit**

Run:

    uv run pytest -q \
      tests/test_agent_recovery_gate.py \
      tests/test_remediation.py \
      tests/test_tier2_recovery.py \
      tests/test_tier2_recovery_integration.py \
      tests/test_plugin_base_hooks.py
    git diff --check

Expected: PASS.

Commit:

    feat(remediation): 以 Azure 與 plugin capability gate tier-2

---

### Task 6: Pure observational assistance metrics

**Files:**
- Create: src/testpilot/core/assistance_metrics.py
- Create: tests/test_assistance_metrics.py

**Interfaces:**
- summarize_case_assistance(record) derives one immutable case summary from CaseRunRecord.retry only.
- compute_assistance_metrics(records) returns arithmetic evidence; it never invokes Azure and never changes a verdict.
- Every metric carries evidence_level=observational and causal_uplift=unavailable.
- Rates use rate_percent; overall delta uses value_percentage_points. Empty denominators produce None, never an invented zero-percent claim.

- [ ] **Step 1: Write RED tests for exact definitions**

Build RetryResult fixtures with real attempts/remediation_history/tier2_audit shapes. The _audit() helper emits a non-empty bounded prompt by default so it represents an actual requester invocation; tests for pre-request context failure set prompt="" explicitly.

    def test_initial_and_final_pass_rates_and_delta():
        records = [
            _record("D001", attempts=[False, True], final=True),
            _record("D002", attempts=[True], final=True),
            _record("D003", attempts=[False], final=False),
        ]
        metrics = compute_assistance_metrics(records)

        assert metrics["initial_pass_rate"] == _metric(
            numerator=1, denominator=3, rate_percent=33.333333
        )
        assert metrics["final_pass_rate"] == _metric(
            numerator=2, denominator=3, rate_percent=66.666667
        )
        assert metrics["overall_observed_delta_percentage_points"] == {
            "value_percentage_points": 33.333333,
            "evidence_level": "observational",
            "causal_uplift": "unavailable",
        }


    def test_deterministic_resolution_excludes_any_tier2_intervention():
        deterministic_only = _record(
            "D001",
            attempts=[False, True],
            final=True,
            remediation=[_tier1(
                applied=True,
                verify_after=True,
                executed_actions=[{"executor_key": "generic-repair"}],
            )],
        )
        with_tier2 = _record(
            "D002",
            attempts=[False, True],
            final=True,
            remediation=[
                _tier1(applied=True, verify_after=False),
                _tier2_trace(applied=True, core_verify_after=True),
            ],
            tier2_audit=[_audit(plan=True, gate=True)],
        )

        metrics = compute_assistance_metrics([deterministic_only, with_tier2])

        assert metrics["deterministic_observed_resolution_rate"] == _metric(
            numerator=1, denominator=1, rate_percent=100.0
        )


    def test_no_decision_tier1_miss_is_not_attributed_as_intervention():
        record = _record(
            "D001",
            attempts=[False, True],
            final=True,
            remediation=[_tier1(
                applied=False,
                verify_after=None,
                core_verify_after=None,
                executed_actions=[],
                comment="tier-1 decision unavailable or rejected",
            )],
        )

        summary = summarize_case_assistance(record)
        metrics = compute_assistance_metrics([record])

        assert summary.deterministic_records == ()
        assert summary.deterministic_observed_resolution is False
        assert metrics["deterministic_observed_resolution_rate"] == _metric(
            numerator=0,
            denominator=0,
            rate_percent=None,
        )


    def test_agent_recovery_requires_invocation_gate_pass_and_final_pass():
        passed = _record(
            "D001",
            attempts=[False, True],
            final=True,
            agent_recovered=True,
            tier2_audit=[_audit(plan=True, gate=True)],
        )
        post_gate_fail = _record(
            "D002",
            attempts=[False, False],
            final=False,
            agent_recovered=True,
            tier2_audit=[_audit(plan=True, gate=True)],
        )
        rejected = _record(
            "D003",
            attempts=[False, False],
            final=False,
            agent_recovered=True,
            tier2_audit=[_audit(plan=False, gate=None, status="rejected")],
        )

        metrics = compute_assistance_metrics([passed, post_gate_fail, rejected])

        assert metrics["agent_recovery_plan_acceptance_rate"] == _metric(
            numerator=2, denominator=3, rate_percent=66.666667
        )
        assert metrics["agent_recovery_env_gate_conversion_rate"] == _metric(
            numerator=2, denominator=2, rate_percent=100.0
        )
        assert metrics["agent_recovery_observed_resolution_rate"] == _metric(
            numerator=1, denominator=2, rate_percent=50.0
        )
        assert metrics["post_gate_case_failure_rate"] == _metric(
            numerator=1, denominator=2, rate_percent=50.0
        )


    def test_empty_denominator_is_unavailable_not_zero():
        metrics = compute_assistance_metrics([
            _record("D001", attempts=[True], final=True)
        ])
        assert metrics["agent_recovery_plan_acceptance_rate"]["rate_percent"] is None
        assert metrics["agent_recovery_plan_acceptance_rate"]["denominator"] == 0
        assert metrics["agent_recovery_plan_acceptance_rate"]["causal_uplift"] == "unavailable"


    def test_agent_recovered_is_intervention_marker_not_success():
        summary = summarize_case_assistance(
            _record(
                "D001",
                attempts=[False],
                final=False,
                agent_recovered=True,
                tier2_audit=[_audit(plan=False, gate=None, status="failed")],
            )
        )
        assert summary.agent_intervened is True
        assert summary.agent_observed_resolution is False


    def test_context_failure_audit_is_not_counted_as_agent_invocation():
        record = _record(
            "D001",
            attempts=[False, True],
            final=True,
            remediation=[_tier1(
                applied=True,
                verify_after=True,
                executed_actions=[{"executor_key": "generic-repair"}],
            )],
            agent_recovered=False,
            tier2_audit=[{
                "status": "rejected",
                "prompt": "",
                "plan": None,
                "verify_gate": {
                    "executed": False,
                    "passed": False,
                },
            }],
        )
        metrics = compute_assistance_metrics([record])
        assert metrics["agent_recovery_plan_acceptance_rate"][
            "denominator"
        ] == 0
        assert metrics["deterministic_observed_resolution_rate"] == _metric(
            numerator=1,
            denominator=1,
            rate_percent=100.0,
        )

- [ ] **Step 2: Run RED**

Run:

    uv run pytest -q tests/test_assistance_metrics.py

Expected: collection FAIL because assistance_metrics.py does not exist.

- [ ] **Step 3: Implement pure summaries and metric helpers**

    @dataclass(frozen=True, slots=True)
    class CaseAssistanceSummary:
        case_id: str
        initial_pass: bool
        final_pass: bool
        deterministic_records: tuple[Mapping[str, Any], ...]
        deterministic_gate_attempts: int
        deterministic_gate_passes: int
        deterministic_observed_resolution: bool
        agent_intervened: bool
        agent_plans_accepted: int
        agent_gate_attempts: int
        agent_gate_passes: int
        agent_observed_resolution: bool
        post_gate_case_failure: bool


Exact function signatures:

    summarize_case_assistance(
        record: CaseRunRecord,
    ) -> CaseAssistanceSummary

    compute_assistance_metrics(
        records: Sequence[CaseRunRecord],
    ) -> dict[str, dict[str, Any]]

Definitions:

    initial_pass =
        bool(record.retry.attempts[0].get("verdict", False))
        if record.retry.attempts
        else bool(record.retry.verdict)
    tier1_history = [
        entry for entry in record.retry.remediation_history or []
        if entry.get("decision_source") == "tier1-deterministic"
    ]
    tier1_interventions = [
        entry
        for entry in tier1_history
        if isinstance(entry.get("executed_actions"), Sequence)
        and not isinstance(entry.get("executed_actions"), (str, bytes))
        and any(
            isinstance(action, Mapping)
            for action in entry["executed_actions"]
        )
    ]
    tier2_audit = [
        item for item in record.retry.tier2_audit or []
        if isinstance(item, Mapping)
    ]
    deterministic_observed_resolution = (
        not initial_pass
        and bool(tier1_interventions)
        and not bool(record.retry.agent_recovered)
        and bool(record.retry.verdict)
    )
    agent_invocation_audits = [
        item
        for item in tier2_audit
        if bool(record.retry.agent_recovered)
        and bool(str(item.get("prompt", "")).strip())
    ]
    gate_passed = any(
        isinstance(item.get("verify_gate"), Mapping)
        and item["verify_gate"].get("executed") is not False
        and item["verify_gate"].get("passed") is True
        for item in agent_invocation_audits
    )
    agent_observed_resolution = (
        not initial_pass
        and bool(record.retry.agent_recovered)
        and gate_passed
        and bool(record.retry.verdict)
    )

CaseAssistanceSummary.deterministic_records stores tier1_interventions, not every
tier-1 history row. This deliberately excludes the current coordinator's
"decision unavailable or rejected" miss rows, which have no executed_actions and
must not receive credit for a later pass. For
deterministic_env_gate_conversion_rate, denominator is intervention records whose
verify_after or core_verify_after is explicitly bool; numerator is explicit true.
For agent plan acceptance, denominator is agent_invocation_audits only and
numerator is plan mapping present; a context-hook audit with empty prompt and
agent_recovered=false is not a model invocation. For agent env gate conversion,
denominator includes only invocation audits whose verify_gate mapping is not
explicitly marked executed=false. For recovery resolution/post-gate failure,
denominator is initial-fail cases with agent intervention and a passed
deterministic gate.

Compute the delta from the unrounded initial/final fractions, then round rate_percent and delta to six decimal places. Use one helper:

    def _rate(numerator: int, denominator: int) -> dict[str, Any]:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "rate_percent": (
                round(numerator * 100.0 / denominator, 6)
                if denominator
                else None
            ),
            "evidence_level": "observational",
            "causal_uplift": "unavailable",
        }

- [ ] **Step 4: Run GREEN and commit**

Run:

    uv run pytest -q tests/test_assistance_metrics.py
    git diff --check

Expected: PASS.

Commit:

    feat(reporting): 新增 observational assistance metrics

---

### Task 7: Bounded run-end batch analysis and reducer

**Files:**
- Create: src/testpilot/core/run_analysis.py
- Create: tests/test_run_analysis.py
- Modify: src/testpilot/core/orchestrator.py
- Create: tests/test_run_analysis_integration.py

**Interfaces:**
- build_case_capsule() reads a final CaseRunRecord plus pre-analysis direct usage only.
- pack_case_capsules() groups complete capsules at a 48,000-character target; it never splits one capsule.
- parse_run_analysis_response() accepts one fixed JSON summary and validates referenced case IDs.
- Orchestrator._analyze_run() executes after all final verdicts, uses run_analysis_batch and optionally one run_analysis_reducer invocation, and never recursively analyzes its own usage.

- [ ] **Step 1: Write RED capsule and packing tests**

    def test_capsule_contains_final_bounded_evidence_but_no_raw_logs_or_commands():
        record = _record(
            case_id="D001",
            initial=False,
            final=True,
            outputs=["opaque-log-secret"],
            commands=["rm forbidden"],
            failure_snapshot={
                "category": "environment",
                "reason_code": "not_ready",
                "metadata": {"password": "opaque-password"},
            },
            remediation=[
                _tier1(
                    applied=True,
                    executed_actions=[
                        {"executor_key": "serial_session_recover"}
                    ],
                )
            ],
            tier2_audit=[{
                "status": "verified",
                "prompt": "opaque-agent-prompt",
                "raw_response": "opaque-agent-response",
                "plan": {
                    "actions": [
                        {"executor_key": "dut_firstboot"}
                    ]
                },
                "execution": {
                    "comment": "opaque-execution-comment"
                },
                "verify_gate": {"passed": True},
            }],
        )
        capsule = build_case_capsule(
            record,
            direct_usage=_direct_usage(tokens=120),
        )
        encoded = json.dumps(capsule.to_dict())

        assert capsule.initial_verdict == "Fail"
        assert capsule.final_verdict == "Pass"
        assert capsule.direct_model_tokens == 120
        assert "opaque-log-secret" not in encoded
        assert "rm forbidden" not in encoded
        assert "opaque-password" not in encoded
        assert "serial_session_recover" not in encoded
        assert "opaque-agent-prompt" not in encoded
        assert "opaque-agent-response" not in encoded
        assert "dut_firstboot" not in encoded
        assert "opaque-execution-comment" not in encoded


    def test_single_batch_when_payload_fits():
        capsules = [_capsule("D001"), _capsule("D002")]
        batches = pack_case_capsules(capsules, target_chars=48_000)
        assert [[item.case_id for item in batch] for batch in batches] == [
            ["D001", "D002"]
        ]


    def test_multiple_batches_preserve_complete_capsule_boundaries():
        capsules = [
            _capsule("D001", summary_chars=25_000),
            _capsule("D002", summary_chars=25_000),
        ]
        batches = pack_case_capsules(capsules, target_chars=48_000)
        assert [[item.case_id for item in batch] for batch in batches] == [
            ["D001"],
            ["D002"],
        ]


    def test_analysis_parser_rejects_unknown_case_and_control_fields():
        with pytest.raises(RunAnalysisValidationError):
            parse_run_analysis_response(
                '{"summary":"x","benefit_assessment":[],"cost_observations":[],'
                '"case_findings":[{"case_id":"D999","assessment":"x","evidence":["x"]}]}',
                allowed_case_ids={"D001"},
            )


    def test_analysis_parser_rejects_oversized_finding_assessment():
        raw = json.dumps({
            "summary": "x",
            "benefit_assessment": [],
            "cost_observations": [],
            "case_findings": [{
                "case_id": "D001",
                "assessment": "x" * 2_001,
                "evidence": [],
            }],
        })
        with pytest.raises(RunAnalysisValidationError):
            parse_run_analysis_response(
                raw,
                allowed_case_ids={"D001"},
            )

- [ ] **Step 2: Write RED integration tests for timing, batching, reducer, and fail-soft**

    def test_analysis_consumes_final_verdicts_from_completed_run_result():
        run_result = _run_result(
            records=[
                _record("D001", initial=False, final=True),
                _record("D002", initial=True, final=True),
            ]
        )
        result = orch._analyze_run(
            run_result=run_result,
            metrics=_metrics(),
            direct_usage=orch.usage_ledger.snapshot(),
        )
        assert result.status == "complete"
        assert '"initial_verdict":"Fail"' in manager.batch_prompts[0]
        assert '"final_verdict":"Pass"' in manager.batch_prompts[0]


    def test_one_batch_uses_one_shared_call_and_no_reducer():
        result = _analyze(capsules=[_capsule("D001"), _capsule("D002")])
        assert result.batch_calls == 1
        assert result.reducer_calls == 0
        purposes = [i.purpose for i in ledger.snapshot().invocations]
        assert purposes == ["run_analysis_batch"]


    def test_multiple_batches_use_exactly_one_bounded_reducer():
        result = _analyze(capsules=_oversized_capsules())
        assert result.batch_calls == 2
        assert result.reducer_calls == 1
        assert [i.purpose for i in ledger.snapshot().invocations] == [
            "run_analysis_batch",
            "run_analysis_batch",
            "run_analysis_reducer",
        ]
        assert "raw_case_evidence" not in manager.reducer_prompt


    def test_maximum_legal_batch_summaries_still_make_bounded_reducer_prompt():
        summaries = [
            _max_bounded_batch_summary(
                batch_index=index,
                evidence="opaque-case-evidence",
            )
            for index in range(1, 416)
        ]

        compact = compact_batch_summaries_for_reducer(
            summaries,
            target_chars=40_000,
        )
        prompt = build_run_analysis_reducer_prompt(
            summaries=summaries,
            metrics=_metrics(),
        )

        assert len(_compact_json(compact)) <= 40_000
        assert len(prompt) <= 64_000
        assert "opaque-case-evidence" not in prompt
        assert '"case_findings"' not in _compact_json(compact)


    def test_breaker_open_skips_analysis_without_call():
        orch.agent_circuit_open = True
        result = orch._analyze_run(
            run_result=run_result,
            metrics=_metrics(),
            direct_usage=orch.usage_ledger.snapshot(),
        )
        assert result.status == "skipped_circuit_breaker"
        assert manager.calls == 0


    def test_batch_failure_is_unavailable_and_does_not_change_verdicts():
        before = [record.retry.verdict for record in run_result.cases]
        result = orch._analyze_run(
            run_result=run_result,
            metrics=_metrics(),
            direct_usage=orch.usage_ledger.snapshot(),
        )
        after = [record.retry.verdict for record in run_result.cases]
        assert result.status == "failed"
        assert before == after


    def test_local_capsule_validation_failure_is_fail_soft(
        monkeypatch,
    ):
        before = [record.retry.verdict for record in run_result.cases]
        monkeypatch.setattr(
            "testpilot.core.orchestrator.build_case_capsule",
            Mock(
                side_effect=RunAnalysisValidationError(
                    "bounded local validation failure"
                )
            ),
        )

        result = orch._analyze_run(
            run_result=run_result,
            metrics=_metrics(),
            direct_usage=orch.usage_ledger.snapshot(),
        )

        assert result.status == "failed"
        assert result.error_type == "RunAnalysisValidationError"
        assert manager.calls == 0
        assert orch.agent_circuit_open is False
        assert [record.retry.verdict for record in run_result.cases] == before

- [ ] **Step 3: Run RED**

Run:

    uv run pytest -q \
      tests/test_run_analysis.py \
      tests/test_run_analysis_integration.py

Expected: collection FAIL because run_analysis.py and _analyze_run() do not exist.

- [ ] **Step 4: Implement bounded capsule and fixed response schema**

    @dataclass(frozen=True, slots=True)
    class CaseAnalysisCapsule:
        case_id: str
        initial_verdict: Literal["Pass", "Fail"]
        final_verdict: Literal["Pass", "Fail"]
        attempts_used: int
        failure_category: str
        failure_reason_code: str
        deterministic_remediation: dict[str, Any]
        agent_recovery: dict[str, Any]
        direct_model_tokens: int
        duration_seconds: float

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)


    AnalysisStatus = Literal[
        "complete",
        "failed",
        "skipped_no_agent",
        "skipped_circuit_breaker",
        "skipped_no_cases",
    ]


    @dataclass(frozen=True, slots=True)
    class RunAnalysisResult:
        status: AnalysisStatus
        summary: str = ""
        benefit_assessment: tuple[str, ...] = ()
        cost_observations: tuple[str, ...] = ()
        case_findings: tuple[dict[str, Any], ...] = ()
        batch_calls: int = 0
        reducer_calls: int = 0
        error_type: str = ""

        def to_dict(self) -> dict[str, Any]:
            return {
                "status": self.status,
                "summary": self.summary,
                "benefit_assessment": list(self.benefit_assessment),
                "cost_observations": list(self.cost_observations),
                "case_findings": [
                    dict(item) for item in self.case_findings
                ],
                "batch_calls": self.batch_calls,
                "reducer_calls": self.reducer_calls,
                "error_type": self.error_type,
            }

        @classmethod
        def from_mapping(
            cls,
            value: Mapping[str, Any],
            *,
            batch_calls: int,
            reducer_calls: int = 0,
            case_findings: Sequence[Mapping[str, Any]] | None = None,
        ) -> "RunAnalysisResult":
            return cls(
                status="complete",
                summary=str(value["summary"]),
                benefit_assessment=tuple(value["benefit_assessment"]),
                cost_observations=tuple(value["cost_observations"]),
                case_findings=tuple(
                    dict(item)
                    for item in (
                        value["case_findings"]
                        if case_findings is None
                        else case_findings
                    )
                ),
                batch_calls=batch_calls,
                reducer_calls=reducer_calls,
            )

Exact function signatures:

    build_case_capsule(
        record: CaseRunRecord,
        *,
        direct_usage: Mapping[str, Any],
    ) -> CaseAnalysisCapsule

    pack_case_capsules(
        capsules: Sequence[CaseAnalysisCapsule],
        *,
        target_chars: int = 48_000,
    ) -> list[tuple[CaseAnalysisCapsule, ...]]

    build_run_analysis_prompt(
        *,
        capsules: Sequence[CaseAnalysisCapsule],
        metrics: Mapping[str, Any],
        batch_index: int,
        batch_count: int,
    ) -> str

    build_run_analysis_reducer_prompt(
        *,
        summaries: Sequence[Mapping[str, Any]],
        metrics: Mapping[str, Any],
    ) -> str

    compact_batch_summaries_for_reducer(
        summaries: Sequence[Mapping[str, Any]],
        *,
        target_chars: int = 40_000,
    ) -> tuple[dict[str, Any], ...]

    parse_run_analysis_response(
        raw_response: str,
        *,
        allowed_case_ids: set[str],
    ) -> dict[str, Any]

Fixed response schema:

    {
      "summary": "bounded text",
      "benefit_assessment": ["bounded observation"],
      "cost_observations": ["bounded observation"],
      "case_findings": [
        {
          "case_id": "D001",
          "assessment": "bounded text",
          "evidence": ["bounded structured evidence reference"]
        }
      ]
    }

Reject unknown keys, secret-like values and case IDs outside the current batch.
Bound summary to 4,000 chars, both observation arrays to 32 items/1,000 chars,
findings to the number of allowed cases, each finding assessment to 2,000 chars,
and evidence to 8 items/500 chars. Validate all limits before constructing the
immutable RunAnalysisResult or writing artifacts.

CaseAnalysisCapsule.deterministic_remediation and agent_recovery may contain only counts, booleans, stable status/reason codes and gate/final outcomes. They must not include executor keys, action names, params, prompts, responses, commands or logs.

Packing must calculate compact JSON character lengths plus fixed prompt overhead; no produced one-shot prompt may exceed 64,000 chars. An individually oversized capsule is already bounded and must raise a local RunAnalysisValidationError before any provider call.

Reducer input has a separate global bound; it must not concatenate the full legal
batch responses. compact_batch_summaries_for_reducer() first creates one minimal
row per batch with only batch, summary, benefit and cost fields. It explicitly
drops case_findings/evidence. Calculate the compact JSON size of all empty rows,
fail locally if even that structural envelope exceeds target_chars, then divide
the remaining character budget across the three text fields and truncate their
joined values deterministically. Validate the final compact JSON is at most
40,000 characters. build_run_analysis_reducer_prompt() uses only this projection
plus a fixed allowlist of aggregate metrics and performs a final 64,000-character
check.

Because reducer input intentionally contains no per-case evidence, require its
case_findings response to be empty by validating with allowed_case_ids=set(). The
final RunAnalysisResult uses reducer summary/benefit/cost fields but preserves the
already validated, flattened case_findings from the batch responses. This keeps
per-case observations without sending them through an unbounded second prompt.

- [ ] **Step 5: Implement _analyze_run() using the generic controller**

    def _analyze_run(
        self,
        *,
        run_result: RunResult,
        metrics: Mapping[str, Any],
        direct_usage: UsageSnapshot,
    ) -> RunAnalysisResult:
        if not run_result.cases:
            return RunAnalysisResult(status="skipped_no_cases")
        if self.agent_circuit_open:
            return RunAnalysisResult(status="skipped_circuit_breaker")
        if not self.agent_runtime.status.ready:
            return RunAnalysisResult(status="skipped_no_agent")

        batch_attempts = 0
        reducer_attempts = 0
        try:
            capsules = [
                build_case_capsule(
                    record,
                    direct_usage=direct_usage.case_totals(record.case_id),
                )
                for record in run_result.cases
            ]
            batches = pack_case_capsules(capsules)
            summaries = []
            for index, batch in enumerate(batches, start=1):
                batch_attempts += 1
                prompt = build_run_analysis_prompt(
                    capsules=batch,
                    metrics=metrics,
                    batch_index=index,
                    batch_count=len(batches),
                )
                _, summary = self._invoke_agent_one_shot(
                    run_id=run_result.run_id,
                    case_id=None,
                    purpose="run_analysis_batch",
                    session_id=build_session_id(
                        run_result.run_id,
                        purpose="analysis-batch",
                        invocation_index=index,
                    ),
                    prompt=prompt,
                    timeout_seconds=60.0,
                    validate=lambda raw, ids={c.case_id for c in batch}: (
                        parse_run_analysis_response(
                            raw, allowed_case_ids=ids
                        )
                    ),
                )
                summaries.append(summary)
            if len(summaries) == 1:
                return RunAnalysisResult.from_mapping(
                    summaries[0],
                    batch_calls=1,
                )
            reducer_prompt = build_run_analysis_reducer_prompt(
                summaries=summaries,
                metrics=metrics,
            )
            batch_findings = [
                item
                for summary in summaries
                for item in summary["case_findings"]
            ]
            reducer_attempts = 1
            _, reduced = self._invoke_agent_one_shot(
                run_id=run_result.run_id,
                case_id=None,
                purpose="run_analysis_reducer",
                session_id=build_session_id(
                    run_result.run_id,
                    purpose="analysis-reducer",
                    invocation_index=1,
                ),
                prompt=reducer_prompt,
                timeout_seconds=60.0,
                validate=lambda raw: parse_run_analysis_response(
                    raw,
                    allowed_case_ids=set(),
                ),
            )
            return RunAnalysisResult.from_mapping(
                reduced,
                batch_calls=len(batches),
                reducer_calls=1,
                case_findings=batch_findings,
            )
        except Exception as exc:
            return RunAnalysisResult(
                status="failed",
                batch_calls=batch_attempts,
                reducer_calls=reducer_attempts,
                error_type=getattr(exc, "error_type", type(exc).__name__),
            )

The reducer prompt receives only sanitized batch summary objects plus core metrics, never original capsules. _analyze_run() itself must not trigger a second cost-analysis pass after reducer usage is recorded.

- [ ] **Step 6: Run GREEN and commit**

Run:

    uv run pytest -q \
      tests/test_run_analysis.py \
      tests/test_run_analysis_integration.py \
      tests/test_agent_invocation.py
    git diff --check

Expected: PASS.

Commit:

    feat(reporting): 新增 run-end bounded Azure analysis

---

### Task 8: Core cost artifacts, per-case totals, run-loop integration, and unsupported paths

**Files:**
- Create: src/testpilot/reporting/usage_reporter.py
- Create: tests/test_usage_reporter.py
- Modify: src/testpilot/core/run_loop.py
- Modify: src/testpilot/core/orchestrator.py
- Modify: tests/test_run_loop_session_degraded.py
- Create: tests/test_core_cost_report_integration.py
- Modify: tests/test_orchestrator_skeleton_fallback.py
- Create: tests/test_custom_runner_cost_report.py

**Interfaces:**
- build_core_cost_report() is a pure projection from final run records, planning results, tier-2 support, frozen usage, metrics, analysis and public Azure state.
- write_core_cost_artifacts() owns agent_usage/events.jsonl, cost-report.json/md and run-analysis.json/md.
- Core loop execution_path is core_run_loop and coverage is core_sdk_calls_only.
- Custom runner and skeleton paths make no core SDK call and return core_cost_report.status=unsupported_execution_path.
- Plugin build_reports(run_result) receives the unchanged RunResult; core_cost_report is attached only after it returns.

- [ ] **Step 1: Write RED pure reporter tests**

    def test_cost_report_separates_direct_shared_and_cache_tokens(tmp_path):
        report = build_core_cost_report(
            run_result=_run_result(["D001"]),
            planning_by_case={
                "D001": CasePlanningResult(
                    status="completed",
                    advisory=_advisory(),
                )
            },
            agent_recovery_support={
                "D001": Tier2Support(
                    False, "plugin_capability_unavailable"
                )
            },
            usage=_snapshot(
                _usage(
                    case_id="D001",
                    purpose="case_planning",
                    input_tokens=100,
                    output_tokens=20,
                    cache_read_tokens=40,
                ),
                _usage(
                    case_id=None,
                    purpose="run_analysis_batch",
                    input_tokens=200,
                    output_tokens=30,
                    cache_read_tokens=80,
                ),
            ),
            metrics=_metrics(),
            analysis=_analysis(),
            agent_state=_public_agent_state(),
        )

        case = report["per_case"][0]
        assert case["agent"]["calls"] == 1
        assert case["agent"]["total_tokens"] == 120
        assert case["agent_recovery"] == {
            "supported": False,
            "reason": "plugin_capability_unavailable",
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "usage_status": "not_called",
            "observed_resolution": False,
        }
        assert case["deterministic_remediation"]["tokens"] == 0
        assert case["direct_total_tokens"] == 120
        assert report["shared"]["run_analysis_tokens"] == 230
        assert report["total"] == {
            "direct_tokens": 120,
            "shared_tokens": 230,
            "all_core_model_tokens": 350,
            "usage_status": "exact",
        }
        assert report["cache_tokens"] == {
            "read": 120,
            "write": 0,
        }


    def test_failed_call_keeps_call_count_and_usage_unavailable():
        args = _base_report_args()
        args["usage"] = _snapshot(
            _failed_invocation(
                case_id="D001",
                purpose="case_planning",
            )
        )
        report = build_core_cost_report(**args)
        agent = report["per_case"][0]["agent"]
        assert agent["calls"] == 1
        assert agent["total_tokens"] == 0
        assert agent["usage_status"] == "unavailable"


    def test_deterministic_outcomes_are_counted_but_tokens_are_always_zero():
        args = _base_report_args()
        args["run_result"] = _run_result(
            ["D001"],
            remediation=[
                _tier1(
                    applied=True,
                    verify_after=True,
                    core_verify_after=False,
                    executed_actions=[{"executor_key": "opaque-generic"}],
                )
            ],
        )
        report = build_core_cost_report(**args)
        deterministic = report["per_case"][0]["deterministic_remediation"]
        assert deterministic == {
            "calls": 1,
            "tokens": 0,
            "actions": 1,
            "applied": 1,
            "failed": 0,
            "plugin_verify": {
                "attempted": 1,
                "passed": 1,
            },
            "core_next_attempt_verify": {
                "attempted": 1,
                "passed": 0,
            },
            "observed_resolution": True,
        }


    def test_provider_cost_is_unit_agnostic_and_never_usd():
        args = _base_report_args()
        args["usage"] = _snapshot(
            _usage(provider_cost_units=1.5)
        )
        report = build_core_cost_report(**args)
        encoded = json.dumps(report)
        assert report["provider_cost_units"] == 1.5
        assert "usd" not in encoded.lower()
        assert "$" not in encoded


    def test_no_agent_report_still_exists_with_zero_model_tokens():
        args = _base_report_args()
        args.update(
            agent_state=_public_agent_state(
                initial="disabled_no_key",
                final="disabled_no_key",
            ),
            usage=_snapshot(),
            analysis=RunAnalysisResult(status="skipped_no_agent"),
        )
        report = build_core_cost_report(**args)
        assert report["total"]["all_core_model_tokens"] == 0
        assert report["analysis"]["status"] == "skipped_no_agent"
        assert report["coverage"] == "core_sdk_calls_only"

- [ ] **Step 2: Write RED artifact and run-loop integration tests**

    def test_writer_creates_all_five_core_owned_artifacts(tmp_path):
        artifacts = write_core_cost_artifacts(
            artifact_dir=tmp_path,
            report=_cost_report(),
            usage=_snapshot_with_journal(),
            analysis=_analysis(),
        )
        usage_dir = tmp_path / "agent_usage"
        assert {path.name for path in usage_dir.iterdir()} == {
            "events.jsonl",
            "cost-report.json",
            "cost-report.md",
            "run-analysis.json",
            "run-analysis.md",
        }
        assert artifacts.to_payload()["json_path"].endswith(
            "agent_usage/cost-report.json"
        )


    def test_events_jsonl_has_lifecycle_and_usage_but_no_secret_material(tmp_path):
        write_core_cost_artifacts(
            artifact_dir=tmp_path,
            report=_cost_report(),
            usage=_snapshot_with_journal(),
            analysis=_analysis(),
        )
        text = (tmp_path / "agent_usage/events.jsonl").read_text()
        assert '"kind":"invocation_started"' in text
        assert '"kind":"usage"' in text
        assert '"kind":"invocation_finished"' in text
        assert "opaque-key-sentinel" not in text
        assert "opaque-endpoint.invalid" not in text
        assert "prompt" not in text
        assert "response" not in text


    def test_core_freezes_and_writes_before_plugin_reporter_without_changing_contract(
        tmp_path
    ):
        events = []
        reporter = _InspectingReporter(events)
        payload = run_loop.run(
            _orch(tmp_path, events, reporter=reporter),
            "fake",
            None,
            None,
        )

        assert events[-4:] == [
            "analysis",
            "ledger_frozen",
            "core_artifacts_written",
            "plugin_build_reports",
        ]
        assert reporter.run_result_fields == set(
            field.name for field in dataclasses.fields(RunResult)
        )
        assert reporter.run_result_had_core_cost_report is False
        assert "core_cost_report" not in reporter.payload_keys_at_return
        assert payload["core_cost_report"]["status"] == "complete"
        assert payload["core_cost_report"]["execution_path"] == "core_run_loop"


    def test_failed_local_analysis_still_writes_partial_artifacts_and_reports(
        tmp_path,
    ):
        events = []
        reporter = _InspectingReporter(events)
        orch = _orch(tmp_path, events, reporter=reporter)
        orch._analyze_run = Mock(
            return_value=RunAnalysisResult(
                status="failed",
                error_type="RunAnalysisValidationError",
            )
        )

        payload = run_loop.run(orch, "fake", None, None)

        assert payload["status"] == "ok"
        assert payload["core_cost_report"]["status"] == "partial"
        assert payload["core_cost_report"]["analysis_status"] == "failed"
        assert Path(payload["core_cost_report"]["json_path"]).is_file()
        assert events[-1] == "plugin_build_reports"


    @pytest.mark.parametrize(
        "target",
        [
            "testpilot.core.run_loop.compute_assistance_metrics",
            "testpilot.core.run_loop.build_core_cost_report",
            "testpilot.core.run_loop.write_core_cost_artifacts",
            "testpilot.core.usage_ledger.UsageLedger.freeze",
        ],
    )
    def test_any_core_report_stage_failure_is_additive_and_does_not_fail_run(
        tmp_path, monkeypatch, target
    ):
        monkeypatch.setattr(
            target,
            Mock(side_effect=OSError("opaque-path-secret")),
        )
        payload = run_loop.run(_orch(tmp_path), "fake", None, None)
        assert payload["status"] == "ok"
        assert payload["core_cost_report"]["status"] == "failed"
        assert payload["core_cost_report"]["error_type"] == "OSError"
        assert "opaque-path-secret" not in json.dumps(payload)


    def test_custom_runner_returns_unsupported_and_core_makes_no_agent_call():
        orch = _orchestrator_with_custom_runner(runtime=_ready_runtime())
        payload = orch.run("fake")
        assert orch.session_manager.calls == 0
        assert payload["core_cost_report"] == {
            "status": "unsupported_execution_path",
            "execution_path": "custom_runner",
            "coverage": "core_sdk_calls_only",
            "analysis_status": "unavailable",
        }


    def test_skeleton_returns_unsupported_and_core_makes_no_agent_call():
        orch = _orchestrator_with_skeleton_plugin(
            runtime=_ready_runtime()
        )
        payload = orch.run("fake")
        assert payload["core_cost_report"]["status"] == "unsupported_execution_path"
        assert payload["core_cost_report"]["execution_path"] == "skeleton"
        assert orch.session_manager.calls == 0

- [ ] **Step 3: Run RED**

Run:

    uv run pytest -q \
      tests/test_usage_reporter.py \
      tests/test_core_cost_report_integration.py \
      tests/test_custom_runner_cost_report.py \
      tests/test_orchestrator_skeleton_fallback.py

Expected: FAIL because usage_reporter.py, core artifacts, payload descriptor and unsupported path status do not exist.

- [ ] **Step 4: Implement exact report schema and aggregation**

    @dataclass(frozen=True, slots=True)
    class CoreCostArtifacts:
        status: Literal["complete", "partial", "failed"]
        json_path: str = ""
        markdown_path: str = ""
        analysis_status: str = ""
        execution_path: str = "core_run_loop"
        coverage: str = "core_sdk_calls_only"
        error_type: str = ""

        def to_payload(self) -> dict[str, Any]:
            return asdict(self)


Exact function signatures:

    build_core_cost_report(
        *,
        run_result: RunResult,
        planning_by_case: Mapping[str, CasePlanningResult],
        agent_recovery_support: Mapping[str, Tier2Support],
        usage: UsageSnapshot,
        metrics: Mapping[str, Any],
        analysis: RunAnalysisResult,
        agent_state: Mapping[str, str],
    ) -> dict[str, Any]

    write_core_cost_artifacts(
        *,
        artifact_dir: Path,
        report: Mapping[str, Any],
        usage: UsageSnapshot,
        analysis: RunAnalysisResult,
    ) -> CoreCostArtifacts

Top-level JSON:

    {
      "schema_version": "1.0",
      "coverage": "core_sdk_calls_only",
      "execution_path": "core_run_loop",
      "agent_state": {
        "initial_agent_state": "azure_ready",
        "final_agent_state": "degraded",
        "deployment": "azure-deployment",
        "api_version": "2024-10-21",
        "reason_code": "TimeoutError"
      },
      "per_case": [],
      "shared": {
        "run_analysis_tokens": 0,
        "batch_calls": 0,
        "reducer_calls": 0,
        "usage_status": "not_called"
      },
      "total": {
        "direct_tokens": 0,
        "shared_tokens": 0,
        "all_core_model_tokens": 0,
        "usage_status": "not_called"
      },
      "cache_tokens": {"read": 0, "write": 0},
      "provider_cost_units": null,
      "assistance_metrics": {},
      "analysis": {}
    }

Per-case JSON:

    {
      "case_id": "D001",
      "agent": {
        "purpose": "case_planning",
        "status": "completed",
        "calls": 1,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "usage_status": "exact"
      },
      "deterministic_remediation": {
        "calls": 0,
        "tokens": 0,
        "actions": 0,
        "applied": 0,
        "failed": 0,
        "plugin_verify": {
          "attempted": 0,
          "passed": 0
        },
        "core_next_attempt_verify": {
          "attempted": 0,
          "passed": 0
        },
        "observed_resolution": false
      },
      "agent_recovery": {
        "supported": false,
        "reason": "plugin_capability_unavailable",
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "usage_status": "not_called",
        "observed_resolution": false
      },
      "direct_total_tokens": 0
    }

Invocation calls come from started invocation records, not usage row count. Token totals come only from accepted usage records. If a purpose has calls but any completed/failed call lacks authoritative usage, usage_status is unavailable; if calls=0 it is not_called; otherwise exact.

total.usage_status is unavailable when any started core invocation lacks authoritative usage, exact when every started invocation has usage, and not_called when the run has zero model invocations.

provider_cost_units is null when no usage record reports cost; otherwise sum only reported values. Cache totals are informational and excluded from direct/shared/all_core_model_tokens.

For deterministic_remediation, calls counts tier1-deterministic history rows and
actions counts their sanitized executed_actions. plugin_verify separately counts
explicit bool verify_after values; core_next_attempt_verify separately counts
explicit bool core_verify_after values. Do not collapse these into one gate,
because plugin verification can pass while the core's next-attempt verification
fails. observed_resolution uses the Task 6 actual-intervention definition and
never credits a no-decision/no-action history row.

Markdown must display:

- Azure initial/final state, deployment and coverage.
- Per-case planning, deterministic remediation, separate plugin/core verification,
  agent recovery and direct total columns.
- Shared batch/reducer tokens and run total.
- All observational metrics with numerator/denominator and explicit causal uplift unavailable note.
- Analysis status and bounded narrative.
- No endpoint, provider config, raw prompt/response or raw logs.

events.jsonl writes each already-sanitized string in usage.journal_lines followed by one newline. JSON and Markdown parent directory is artifact_dir/agent_usage.

write_core_cost_artifacts() returns status=partial when analysis.status is failed, status=complete for complete or any explicit skipped_* analysis state, and status=failed only when the core artifact write itself raises. shared.batch_calls and shared.reducer_calls come from started invocation records by purpose, not from successful-response count.

- [ ] **Step 5: Integrate after final verdicts and before plugin reporter**

After constructing RunResult, keep the complete core-only reporting phase behind one fail-soft boundary:

    analysis: RunAnalysisResult | None = None
    try:
        direct_usage = orchestrator.usage_ledger.snapshot()
        metrics = compute_assistance_metrics(run_result.cases)
        analysis = orchestrator._analyze_run(
            run_result=run_result,
            metrics=metrics,
            direct_usage=direct_usage,
        )
        frozen_usage = orchestrator.usage_ledger.freeze()
        report = build_core_cost_report(
            run_result=run_result,
            planning_by_case=planning_by_case,
            agent_recovery_support=orchestrator.agent_recovery_support,
            usage=frozen_usage,
            metrics=metrics,
            analysis=analysis,
            agent_state=orchestrator.agent_runtime.public_summary(),
        )
        core_artifacts = write_core_cost_artifacts(
            artifact_dir=artifact_dir,
            report=report,
            usage=frozen_usage,
            analysis=analysis,
        )
    except Exception as exc:
        core_artifacts = CoreCostArtifacts(
            status="failed",
            analysis_status=(
                analysis.status
                if analysis is not None
                else "unavailable"
            ),
            error_type=type(exc).__name__,
        )

Only then:

    payload = build_reports(run_result)
    if isinstance(payload, dict):
        payload["core_cost_report"] = core_artifacts.to_payload()

Preserve existing agent_session_degraded and tier2_remediation additive keys.

- [ ] **Step 6: Mark non-core execution paths unsupported**

Use one helper:

    def _unsupported_cost_report(execution_path: str) -> dict[str, str]:
        return {
            "status": "unsupported_execution_path",
            "execution_path": execution_path,
            "coverage": "core_sdk_calls_only",
            "analysis_status": "unavailable",
        }

For a custom runner:

    payload = self._run_via_runner(
        plugin=plugin,
        runner=runner,
        plugin_name=plugin_name,
        case_ids=case_ids,
        dut_fw_ver=dut_fw_ver,
        provider_config=None,
    )
    if isinstance(payload, dict):
        payload["core_cost_report"] = _unsupported_cost_report(
            "custom_runner"
        )
    return payload

For skeleton, add the same key with execution_path=skeleton. These branches must not invoke _plan_case(), _build_execution_engine(), _analyze_run() or UsageLedger.start_invocation(). Keep the delegated runner call signature intact; do not claim coverage for model calls a plugin runner may make outside the core SDK adapter.

- [ ] **Step 7: Run GREEN and commit**

Run:

    uv run pytest -q \
      tests/test_usage_reporter.py \
      tests/test_core_cost_report_integration.py \
      tests/test_custom_runner_cost_report.py \
      tests/test_orchestrator_skeleton_fallback.py \
      tests/test_run_loop_session_degraded.py \
      tests/test_tier2_recovery_integration.py
    git diff --check

Expected: PASS.

Commit:

    feat(reporting): 產生 core-only agent cost report

---

### Task 9: Core documentation, policy alignment, and full verification

**Files:**
- Modify: README.md
- Modify: docs/spec.md
- Modify: docs/plan.md
- Modify: CHANGELOG.md
- Modify: AGENTS.md
- Modify: CLAUDE.md
- Modify: GEMINI.md
- Modify: .github/copilot-instructions.md
- Modify: tests/test_cli_doc_alignment.py
- Modify: tests/test_release_governance.py

**Interfaces:**
- Documentation names Azure environment variables without values.
- No current documentation or generated help mentions interactive --azure or GitHub OAuth fallback.
- Four convention files remain byte-aligned for their managed Azure policy section.
- CHANGELOG [Unreleased] records the core-only compatibility boundary and observational nature of benefit metrics.

- [ ] **Step 1: Write RED doc-alignment tests**

    @pytest.mark.parametrize(
        "path",
        [
            ROOT / "README.md",
            ROOT / "docs/spec.md",
            ROOT / "docs/plan.md",
            ROOT / "AGENTS.md",
            ROOT / "CLAUDE.md",
            ROOT / "GEMINI.md",
            ROOT / ".github/copilot-instructions.md",
        ],
    )
    def test_current_docs_have_no_interactive_azure_or_oauth_fallback(path):
        text = path.read_text(encoding="utf-8")
        assert "testpilot --azure" not in text
        assert "--azure flag" not in text
        assert "GitHub OAuth fallback" not in text
        assert "GitHub OAuth（預設）" not in text


    def test_readme_help_matches_cli_without_azure_flag():
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--azure" not in result.output
        assert "--azure" not in _read_readme_help_blocks()


    def test_four_agent_policy_files_have_identical_azure_section():
        sections = [
            _extract_azure_policy(path)
            for path in AGENT_CONVENTION_FILES
        ]
        assert len(set(sections)) == 1

- [ ] **Step 2: Run RED**

Run:

    uv run pytest -q \
      tests/test_cli_doc_alignment.py \
      tests/test_release_governance.py \
      tests/test_versioned_plugin_contract.py \
      tests/test_plugin_base_hooks.py

Expected: FAIL because README, docs/plan and all four convention files still document --azure interactive auth and OAuth fallback.

- [ ] **Step 3: Update operator and architecture docs**

README English and zh-tw sections must show:

    export COPILOT_PROVIDER_BASE_URL=https://your-resource.openai.azure.com
    export COPILOT_PROVIDER_API_KEY='<set in shell profile or secret store>'
    export COPILOT_MODEL=your-deployment-name
    export COPILOT_PROVIDER_AZURE_API_VERSION=2024-10-21
    testpilot run <plugin_name>

State:

- API key absent means deterministic/no-agent mode, with no warning.
- Key present but endpoint/deployment absent means non-blocking misconfigured warning.
- COPILOT_PROVIDER_TYPE is ignored as an enable switch; core only constructs Azure provider config.
- Azure deployment is independent from plugin runner model labels.
- Per-case planning is advisory; tier-2 requires plugin opt-in; deterministic remediation remains plugin-owned.
- Core artifacts live under artifact_dir/agent_usage and shared run-analysis tokens are not allocated to cases.
- Benefit metrics are observational and cannot claim causal uplift/regression.
- Custom runner/skeleton return unsupported_execution_path for this report.

Replace docs/plan section 8 rather than appending a contradictory section. Update docs/spec.md agent/reporting requirements to the approved runtime states, call order, usage authority, circuit behavior and ownership boundary.

Do not add a new docs/todos.md ID in Default mode. Inspect existing P5-04/R4-06 notes; only update a status note if needed for factual consistency.

- [ ] **Step 4: Synchronize all four convention files**

Use the same replacement in AGENTS.md, CLAUDE.md, GEMINI.md and .github/copilot-instructions.md:

    ## Azure OpenAI BYOK Policy

    1. TestPilot core不提供互動式 Azure enable flag；COPILOT_PROVIDER_API_KEY存在且
       endpoint/deployment完整時自動啟用，沒有 key時使用 deterministic/no-agent mode。
    2. TestPilot core只建立 Azure provider；不得 fallback到 GitHub OAuth、
       GitHub-hosted model或其他 provider。
    3. 必要環境變數：
       - COPILOT_PROVIDER_BASE_URL=<endpoint>
       - COPILOT_PROVIDER_API_KEY=<key>
       - COPILOT_MODEL=<deployment-name>
       - COPILOT_PROVIDER_AZURE_API_VERSION=<version>（預設 2024-10-21）
    4. COPILOT_PROVIDER_TYPE不作為 enable switch；agent-config.yaml只保存執行策略，
       不保存 secrets。
    5. API key與 endpoint不得提交版本控制或寫入 trace/report；secrets只透過環境或
       secret store注入。
    6. Core-owned agent calls必須 tool-denied；plugin未明確opt in tier-2 capability/
       executor時，agent recovery固定為unsupported/0。

Do not change managed-by or policy_version values.

- [ ] **Step 5: Update CHANGELOG [Unreleased]**

Add one Added entry and one Changed entry covering:

- Azure automatic readiness and removal of --azure/OAuth fallback.
- Actual per-case planning, capability-gated recovery and run-end analysis.
- assistant.usage dedupe and direct/shared totals.
- deterministic token=0 outcome reporting and observational metrics.
- strict core-only/plugin API unchanged/custom path unsupported boundary.

Do not claim USD pricing, causal uplift or wifi_llapi safe-action execution.

- [ ] **Step 6: Run doc GREEN**

Run:

    uv run pytest -q \
      tests/test_cli_doc_alignment.py \
      tests/test_release_governance.py \
      tests/test_versioned_plugin_contract.py \
      tests/test_plugin_base_hooks.py
    ! rg -n -- "testpilot --azure|--azure flag|GitHub OAuth fallback|GitHub OAuth（預設）" \
      README.md docs/spec.md docs/plan.md \
      AGENTS.md CLAUDE.md GEMINI.md .github/copilot-instructions.md
    git diff --check

Expected: pytest PASS and rg returns no stale current-policy matches. Historical changelog/spec text may remain only when explicitly labeled historical; if so, narrow the test to current policy sections and document that exception.

- [ ] **Step 7: Run the full required verification gate**

Run:

    uv run pytest -q
    python3 -m policy_check --repo .
    git diff --check
    git status --short

Expected:

- Full pytest suite PASS; no focused-only completion claim.
- policy_check reports zero failures. The pre-existing R-22 warning may remain only if unchanged and must be called out in handoff; any new warning must be fixed.
- git diff --check emits no output.
- git status lists only this task's intended documentation/test changes before commit.

If either full gate fails, diagnose and fix within this task, rerun both full commands, then commit only after both are green.

- [ ] **Step 8: Commit and verify clean worktree**

Commit:

    docs(agent): 對齊 Azure-only cost report 行為

Then run:

    git status --short
    git log -10 --oneline

Expected: clean worktree, this approved plan commit, and one immediate commit for each of Tasks 1-9 in plan order.

---

## Acceptance Traceability

| Approved requirement | Implementation task and proof |
|---|---|
| No key deterministic mode; no OAuth | Task 1 state/CLI tests; Task 8 zero-token report |
| Partial config is non-blocking and redacted | Task 1 resolver/CLI tests |
| Actual per-case planning with Azure deployment | Task 4 ordering/model tests |
| Preserve plugin runner identity | Task 4 selected-runner trace test; no RunnerSelector change |
| First provider failure opens breaker | Task 3 first-failure test; Task 4 later-case skip test |
| Malformed response does not open breaker | Tasks 3 and 4 malformed tests |
| Deterministic remediation unchanged, tokens zero | Tasks 5 and 8 deterministic tests |
| Unsupported plugin recovery is calls/tokens zero | Tasks 5 and 8 support/report tests |
| Recovery uses existing capability/executor/gate | Task 5 tier-2 integration and fail-closed post-executor tests |
| assistant.usage authoritative and deduped | Task 2 SDK-shaped dedupe/invalid-event tests |
| Invocation calls independent from token availability | Tasks 2 and 8 failed-call tests |
| Shared run analysis after all final verdicts | Task 7 timing/batch/reducer tests; Task 8 integration ordering |
| Direct/shared/run totals and provider cost units | Task 8 pure reporter tests |
| Observational benefit, no causal claim | Task 6 metric tests; Task 9 docs |
| Five core-owned artifacts before plugin reporter | Task 8 writer/order tests |
| Plugin contract and API unchanged | Task 8 RunResult field inspection; Task 9 governance test |
| Custom/skeleton unsupported, no core calls | Task 8 custom/skeleton tests |
| SDK ships in wheel/offline install | Task 1 wheel metadata and managed offline import smoke |
| Full repository gates | Task 9 full pytest and policy_check |

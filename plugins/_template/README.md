# Plugin Template

Copy this directory to create a new TestPilot plugin scaffold:

```bash
cp -r plugins/_template plugins/my_plugin
```

`_template` is not discoverable by `testpilot list-plugins` on its own. After
copying it, register the copied plugin from the package that ships it:

```toml
[project.entry-points."testpilot.plugins"]
my_plugin = "plugins.my_plugin.plugin:Plugin"
```

Then reinstall that package from its project root so Python refreshes the
entry-point metadata:

```bash
uv pip install -e .
```

Then edit:
1. `plugin.py` — keep/set `api_version = "1.0"` (or another supported
   `major.minor` SDK contract) and implement the required `PluginBase` members
2. `cases/*.yaml` — define your test cases
3. Optionally add `agent-config.yaml` for runner/agent policy
4. Verify: `testpilot list-plugins` → `testpilot list-cases my_plugin`

## Required PluginBase Contract

| Member | Purpose |
|--------|---------|
| `api_version` | SDK contract version the plugin was built against (e.g. `"1.0"`) |
| `name` | Plugin identifier (e.g., `"my_plugin"`) |
| `version` | Semantic version string |
| `discover_cases()` | Scan `cases/` directory for YAML test cases |
| `setup_env()` | Provision DUT/STA/endpoint for a test case |
| `verify_env()` | Validate environment readiness |
| `execute_step()` | Run a single test step via transport |
| `evaluate()` | Check pass criteria against step results |
| `teardown()` | Clean up after test case |

## Optional PluginBase Hooks

A plugin may override these hooks to plug plugin-specific behavior into core
through the `PluginBase` contract. All default to no-op / neutral values, so
core stays free of any plugin-specific names.

| Hook | Purpose | Default |
|------|---------|---------|
| `validate_case(case)` | Plugin-specific case validation; raise on violation | no-op |
| `execution_policy(case)` | Declare execution constraints (concurrency/mode/runner) | `{}` (no constraint) |
| `create_reporter()` | Return a plugin-specific reporter (`IReporter`) | `None` (use orchestrator default) |
| `register_cli(registrar)` | Register the plugin's Click commands/groups through `CliRegistrar` | no-op |
| `build_tier2_remediation_context(case, failure_snapshot, topology, ...)` | Return redacted failure context, an environment capability catalog, and the deterministic `verify_env` definition; core owns the prompt and LLM call | `None` (tier-2 disabled) |
| `execute_tier2_remediation(case, plan, topology)` | Execute a core-validated environment-only plan between retries; never change test semantics or verdicts | fail-closed unsupported result |

> Plugins can import `CliRegistrar` and shared CLI helpers from `testpilot.api`;
> do not import `testpilot.cli` from plugin code.
>
> Every tier-2 capability must declare its `execution_boundary` and a bounded
> `params_schema`. Core validates the plan shape and budget, while the plugin
> executor must enforce that the advertised transport/target can affect only
> environment state and cannot access case definitions or verdict artifacts.
> A plugin using these hooks must declare `api_version = "1.2"` and opt in via
> `remediation.tier2.enabled`. Tier-1 remains a separate deterministic
> `allowed_actions` boundary; tier-2 actions come only from the plugin's
> capability catalog and still pass the core-owned `verify_env` gate.

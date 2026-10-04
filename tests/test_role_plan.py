"""Contracts for neutral, private capture-role plans."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest
import yaml

from testpilot import api
from testpilot.core.plugin_base import PluginBase
from testpilot.core.prepared_run import PreparedRun
from testpilot.core.testbed_config import TestbedConfig


def _role_plan_module():
    spec = importlib.util.find_spec("testpilot.core.role_plan")
    assert spec is not None, "Core must provide the neutral role-plan types"
    return importlib.import_module("testpilot.core.role_plan")


def _testbed(tmp_path: Path, devices: dict[str, object]) -> TestbedConfig:
    path = tmp_path / "operator" / "selected-testbed.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump({"testbed": {"devices": devices}}), encoding="utf-8"
    )
    return TestbedConfig(path)


def _roles() -> dict[str, dict[str, object]]:
    return {
        "DUT": {
            "selector": "dut-session",
            "expected_device_by_id": "/dev/serial/by-id/dut-001",
            "console_profile": "dut-profile",
            "serial_port": "/dev/ttyUSB0",
            "transport": "serial",
            "password": "DUT-SECRET-DO-NOT-PROJECT",
            "unused": "DUT-UNREQUESTED-VALUE",
        },
        "STA": {
            "selector": "sta-session",
            "expected_device_by_id": "/dev/serial/by-id/sta-002",
            "profile": "sta-profile",
            "station_driver": "station-driver-v2",
            "transport": "serial",
            "token": "STA-SECRET-DO-NOT-PROJECT",
        },
    }


def _wifi_request(module):
    return module.CaptureRolePlanRequest(
        roles=["DUT", "STA"],
        provider_options=[
            module.RolePlanOptionRequest("wifi_llapi", "DUT", "transport"),
            module.RolePlanOptionRequest("wifi_llapi", "STA", "transport"),
            module.RolePlanOptionRequest("wifi_llapi", "STA", "station_driver"),
        ],
    )


def _wifi_allowlist(module):
    return (
        module.RolePlanOptionRequest("wifi_llapi", "DUT", "transport"),
        module.RolePlanOptionRequest("wifi_llapi", "STA", "transport"),
        module.RolePlanOptionRequest("wifi_llapi", "STA", "station_driver"),
    )


def test_legacy_plugin_and_prepared_run_default_to_no_role_plan() -> None:
    assert hasattr(PluginBase, "capture_role_plan_request")
    assert PluginBase.capture_role_plan_request is None
    assert getattr(PreparedRun(cases=[]), "effective_role_plan", object()) is None
    # Keep the original four-position construction shape valid.
    assert getattr(PreparedRun([], {}, False, None), "effective_role_plan", object()) is None


def test_sdk_exports_frozen_role_plan_types_without_expanding_capture_context() -> None:
    for name in (
        "CaptureRolePlanRequest",
        "RolePlanOptionRequest",
        "RolePlanIdentity",
        "RolePlanProviderOption",
        "EffectiveRolePlan",
    ):
        assert hasattr(api, name), f"testpilot.api must export {name}"

    assert api.PrepareRunAfterCaptureContext.__dataclass_fields__.keys() == {
        "run_id",
        "start_sequence",
        "capture_binding_id",
    }


def test_projection_uses_the_passed_testbed_object_and_canonical_role_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _role_plan_module()
    config = _testbed(tmp_path, _roles())
    request = _wifi_request(module)

    def forbidden_reload() -> None:
        raise AssertionError("projection must not reload config from path or CWD")

    monkeypatch.setattr(config, "load", forbidden_reload)
    config.path = tmp_path / "different-cwd" / "must-not-be-read.yaml"

    plan = module.project_capture_role_plan(
        config, request, allowed_provider_options=_wifi_allowlist(module)
    )

    assert tuple(role.role for role in plan.roles) == ("dut", "sta")
    assert plan.roles[0].selector == "dut-session"
    assert plan.roles[0].expected_device_by_id == "/dev/serial/by-id/dut-001"
    assert plan.roles[0].expected_profile == "dut-profile"
    assert plan.roles[0].serial_port == "/dev/ttyUSB0"
    assert plan.roles[1].expected_profile == "sta-profile"
    assert tuple((option.namespace, option.role, option.key) for option in plan.provider_options) == (
        ("wifi_llapi", "dut", "transport"),
        ("wifi_llapi", "sta", "station_driver"),
        ("wifi_llapi", "sta", "transport"),
    )
    assert plan.provider_options[1].value == "station-driver-v2"


def test_projection_is_immutable_redacted_and_excludes_unrequested_secrets(
    tmp_path: Path,
) -> None:
    module = _role_plan_module()
    config = _testbed(tmp_path, _roles())
    request = _wifi_request(module)
    allowlist = _wifi_allowlist(module)
    plan = module.project_capture_role_plan(
        config, request, allowed_provider_options=allowlist
    )
    before = (plan.physical_identity_digest, plan.provider_options_digest, plan.digest)

    config.devices["DUT"]["password"] = "CHANGED-SECRET-MUST-NOT-AFFECT-PLAN"
    config.devices["DUT"]["unused"] = "CHANGED-UNREQUESTED-VALUE"
    same_plan = module.project_capture_role_plan(
        config, request, allowed_provider_options=allowlist
    )

    assert before == (
        same_plan.physical_identity_digest,
        same_plan.provider_options_digest,
        same_plan.digest,
    )
    assert len(plan.physical_identity_digest) == 64
    assert len(plan.provider_options_digest) == 64
    assert len(plan.digest) == 64
    assert isinstance(plan.roles, tuple)
    assert isinstance(plan.provider_options, tuple)
    assert "dut-session" not in repr(plan)
    assert "/dev/serial/by-id/dut-001" not in repr(plan)
    assert "dut-profile" not in repr(plan)
    assert "station-driver-v2" not in repr(plan)
    assert str(config.path) not in repr(plan)
    assert "SECRET" not in repr(plan)
    assert "UNREQUESTED" not in repr(plan)

    with pytest.raises((AttributeError, TypeError)):
        plan.roles[0].selector = "other-session"
    with pytest.raises((AttributeError, TypeError)):
        plan.provider_options[0].value = "other-transport"


def test_identity_and_provider_option_digests_are_independent(tmp_path: Path) -> None:
    module = _role_plan_module()
    devices = _roles()
    config = _testbed(tmp_path, devices)
    request = _wifi_request(module)
    allowlist = _wifi_allowlist(module)
    initial = module.project_capture_role_plan(
        config, request, allowed_provider_options=allowlist
    )

    config.devices["STA"]["station_driver"] = "station-driver-v3"
    changed_option = module.project_capture_role_plan(
        config, request, allowed_provider_options=allowlist
    )
    assert initial.physical_identity_digest == changed_option.physical_identity_digest
    assert initial.provider_options_digest != changed_option.provider_options_digest
    assert initial.digest != changed_option.digest

    config.devices["STA"]["expected_device_by_id"] = "/dev/serial/by-id/sta-003"
    changed_identity = module.project_capture_role_plan(
        config, request, allowed_provider_options=allowlist
    )
    assert changed_option.physical_identity_digest != changed_identity.physical_identity_digest
    assert changed_option.provider_options_digest == changed_identity.provider_options_digest
    assert changed_option.digest != changed_identity.digest


def test_effective_plan_constructor_binds_all_digests_to_canonical_contents(
    tmp_path: Path,
) -> None:
    module = _role_plan_module()
    plan = module.project_capture_role_plan(
        _testbed(tmp_path, _roles()),
        _wifi_request(module),
        allowed_provider_options=_wifi_allowlist(module),
    )

    assert module.EffectiveRolePlan(
        plan.roles,
        plan.provider_options,
        plan.physical_identity_digest,
        plan.provider_options_digest,
        plan.digest,
    ) == plan

    with pytest.raises(module.RolePlanError, match="digest.*match"):
        module.EffectiveRolePlan(
            plan.roles, plan.provider_options, "0" * 64, "0" * 64, "0" * 64
        )

    changed_first_role = module.RolePlanIdentity(
        role=plan.roles[0].role,
        selector="different-selector",
        expected_device_by_id=plan.roles[0].expected_device_by_id,
        expected_profile=plan.roles[0].expected_profile,
        serial_port=plan.roles[0].serial_port,
    )
    with pytest.raises(module.RolePlanError, match="digest.*match"):
        module.EffectiveRolePlan(
            (changed_first_role, *plan.roles[1:]),
            plan.provider_options,
            plan.physical_identity_digest,
            plan.provider_options_digest,
            plan.digest,
        )

    with pytest.raises(module.RolePlanError, match="duplicate.*role"):
        module.EffectiveRolePlan(
            (*plan.roles, plan.roles[0]),
            plan.provider_options,
            plan.physical_identity_digest,
            plan.provider_options_digest,
            plan.digest,
        )

    with pytest.raises(module.RolePlanError, match="role order.*canonical"):
        module.EffectiveRolePlan(
            tuple(reversed(plan.roles)),
            plan.provider_options,
            plan.physical_identity_digest,
            plan.provider_options_digest,
            plan.digest,
        )

    with pytest.raises(module.RolePlanError, match="duplicate.*provider option"):
        module.EffectiveRolePlan(
            plan.roles,
            (*plan.provider_options, plan.provider_options[0]),
            plan.physical_identity_digest,
            plan.provider_options_digest,
            plan.digest,
        )

    foreign_option = module.RolePlanProviderOption(
        "wifi_llapi", "endpoint", "transport", "serial"
    )
    with pytest.raises(module.RolePlanError, match="not present in the role plan"):
        module.EffectiveRolePlan(
            plan.roles,
            (*plan.provider_options[:1], foreign_option, *plan.provider_options[1:]),
            plan.physical_identity_digest,
            plan.provider_options_digest,
            plan.digest,
        )


@pytest.mark.parametrize(
    ("role_config", "message"),
    [
        ({"alias": "dut-session", "expected_device_by_id": "/dev/dut", "profile": "dut"}, "selector"),
        ({"selector": " ", "expected_device_by_id": "/dev/dut", "profile": "dut"}, "selector"),
        ({"selector": "dut-session", "profile": "dut"}, "device_by_id"),
        ({"selector": "dut-session", "expected_device_by_id": "/dev/dut"}, "profile"),
        (
            {
                "selector": "dut-session",
                "expected_device_by_id": "/dev/dut",
                "profile": "profile-a",
                "console_profile": "profile-b",
            },
            "profile",
        ),
    ],
)
def test_requested_role_rejects_missing_or_ambiguous_identity(
    tmp_path: Path, role_config: dict[str, object], message: str
) -> None:
    module = _role_plan_module()
    config = _testbed(tmp_path, {"DUT": role_config})
    request = module.CaptureRolePlanRequest(roles=("DUT",))

    with pytest.raises(module.RolePlanError, match=message):
        module.project_capture_role_plan(config, request)


def test_conflicting_role_aliases_and_duplicate_requested_roles_fail_closed(
    tmp_path: Path,
) -> None:
    module = _role_plan_module()
    with pytest.raises(module.RolePlanError, match="duplicate.*role"):
        module.CaptureRolePlanRequest(roles=("DUT", "dut"))

    config = _testbed(
        tmp_path,
        {
            "DUT": {
                "selector": "dut-1",
                "expected_device_by_id": "/dev/dut-1",
                "profile": "dut",
            },
            "dut": {
                "selector": "dut-2",
                "expected_device_by_id": "/dev/dut-2",
                "profile": "dut",
            },
        },
    )
    request = module.CaptureRolePlanRequest(roles=("DUT",))

    with pytest.raises(module.RolePlanError, match="duplicate.*config.*role"):
        module.project_capture_role_plan(config, request)


def test_provider_options_must_be_host_allowlisted_and_present(tmp_path: Path) -> None:
    module = _role_plan_module()
    config = _testbed(tmp_path, _roles())
    request = _wifi_request(module)

    with pytest.raises(module.RolePlanError, match="not allowlisted"):
        module.project_capture_role_plan(config, request)

    allowed = tuple(
        item
        for item in _wifi_allowlist(module)
        if not (item.role == "sta" and item.key == "station_driver")
    )
    with pytest.raises(module.RolePlanError, match="not allowlisted"):
        module.project_capture_role_plan(
            config, request, allowed_provider_options=allowed
        )

    with pytest.raises(module.RolePlanError, match="sensitive provider option"):
        module.RolePlanOptionRequest("wifi_llapi", "STA", "api_key")

    config.devices["STA"].pop("station_driver")
    with pytest.raises(module.RolePlanError, match="provider option.*missing"):
        module.project_capture_role_plan(
            config, request, allowed_provider_options=_wifi_allowlist(module)
        )


def test_request_and_plan_nested_sequences_are_frozen(tmp_path: Path) -> None:
    module = _role_plan_module()
    roles = ["DUT", "STA"]
    options = [module.RolePlanOptionRequest("wifi_llapi", "STA", "station_driver")]
    request = module.CaptureRolePlanRequest(roles=roles, provider_options=options)
    roles.append("endpoint")
    options.clear()

    assert request.roles == ("dut", "sta")
    assert len(request.provider_options) == 1

    plan = module.project_capture_role_plan(
        _testbed(tmp_path, _roles()),
        request,
        allowed_provider_options=_wifi_allowlist(module),
    )
    assert tuple(role.role for role in plan.roles) == ("dut", "sta")
    assert len(plan.provider_options) == 1


def test_nested_provider_config_is_frozen_and_copied(tmp_path: Path) -> None:
    module = _role_plan_module()
    devices = _roles()
    devices["STA"]["driver_options"] = {
        "mode": "safe-mode-value",
        "flags": ["flag-a", "flag-b"],
    }
    config = _testbed(tmp_path, devices)
    option = module.RolePlanOptionRequest("wifi_llapi", "STA", "driver_options")
    request = module.CaptureRolePlanRequest(roles=("STA",), provider_options=(option,))
    plan = module.project_capture_role_plan(
        config, request, allowed_provider_options=(option,)
    )
    original_digest = plan.provider_options_digest
    config.devices["STA"]["driver_options"]["flags"].append("later-change")

    projected = plan.provider_options[0].value
    assert projected["flags"] == ("flag-a", "flag-b")
    assert plan.provider_options_digest == original_digest
    with pytest.raises(TypeError):
        projected["mode"] = "changed"
    with pytest.raises(TypeError):
        projected["flags"][0] = "changed"
    assert "safe-mode-value" not in repr(plan)


@pytest.mark.parametrize("sensitive_key", ["password", "token"])
def test_nested_sensitive_provider_fields_are_rejected(
    tmp_path: Path, sensitive_key: str
) -> None:
    module = _role_plan_module()
    devices = _roles()
    secret_value = "synthetic-secret-do-not-project"
    devices["STA"]["transport"] = {
        "mode": "serial",
        "nested": {"credentials": {sensitive_key: secret_value}},
    }
    config = _testbed(tmp_path, devices)
    option = module.RolePlanOptionRequest("wifi_llapi", "STA", "transport")
    request = module.CaptureRolePlanRequest(roles=("STA",), provider_options=(option,))

    with pytest.raises(module.RolePlanError, match="sensitive.*mapping key") as exc_info:
        module.project_capture_role_plan(
            config, request, allowed_provider_options=(option,)
        )
    assert secret_value not in str(exc_info.value)


def test_invalid_unicode_identity_is_a_sanitized_role_plan_error(
    tmp_path: Path,
) -> None:
    module = _role_plan_module()
    config = _testbed(tmp_path, _roles())
    config.devices["DUT"]["selector"] = "\ud800"
    request = module.CaptureRolePlanRequest(roles=("DUT",))

    with pytest.raises(module.RolePlanError, match="selector"):
        module.project_capture_role_plan(config, request)

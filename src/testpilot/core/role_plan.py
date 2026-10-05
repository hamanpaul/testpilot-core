"""Neutral, immutable projections of explicitly requested operator roles.

These values bind selected configuration fields only. They do not attest to a
physical device, a broker session, or ownership of a transport.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any

from testpilot.core.testbed_config import TestbedConfig

_IDENTIFIER_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_SENSITIVE_OPTION_PATTERN = re.compile(
    r"(?:password|passwd|token|secret|credential|api[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)
_MAX_ROLES = 32
_MAX_PROVIDER_OPTIONS = 64
_MAX_VALUE_DEPTH = 16
_MAX_PLAN_BYTES = 65536


class RolePlanError(ValueError):
    """A role-plan request cannot be projected without guessing."""


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise RolePlanError(f"{field_name} must be a bounded identifier")
    normalized = value.strip().casefold()
    if not _IDENTIFIER_PATTERN.fullmatch(normalized):
        raise RolePlanError(f"{field_name} must be a bounded identifier")
    return normalized


def _sequence(value: object, field_name: str, maximum: int) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise RolePlanError(f"{field_name} must be a finite sequence")
    values = tuple(value)
    if len(values) > maximum:
        raise RolePlanError(f"{field_name} exceeds its item limit")
    return values


def _utf8_length(value: str, field_name: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise RolePlanError(f"{field_name} must be valid UTF-8") from None


def _identity_value(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RolePlanError(f"requested role {field_name} is missing or invalid")
    normalized = value.strip()
    if _utf8_length(normalized, field_name) > 4096:
        raise RolePlanError(f"requested role {field_name} exceeds its size limit")
    return normalized


def _freeze_value(value: object, depth: int = 0) -> Any:
    if depth > _MAX_VALUE_DEPTH:
        raise RolePlanError("provider option value exceeds its nesting limit")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RolePlanError("provider option value must be finite")
        return value
    if isinstance(value, str):
        if _utf8_length(value, "provider option value") > 4096:
            raise RolePlanError("provider option value exceeds its size limit")
        return value
    if isinstance(value, Mapping):
        if len(value) > 256:
            raise RolePlanError("provider option mapping exceeds its item limit")
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or _utf8_length(key, "provider option key") > 256:
                raise RolePlanError("provider option mapping has an invalid key")
            if _SENSITIVE_OPTION_PATTERN.search(key):
                raise RolePlanError("sensitive data is not allowed in a provider option mapping key")
            frozen[key] = _freeze_value(item, depth + 1)
        return MappingProxyType(dict(sorted(frozen.items())))
    if isinstance(value, (list, tuple)):
        if len(value) > 256:
            raise RolePlanError("provider option sequence exceeds its item limit")
        return tuple(_freeze_value(item, depth + 1) for item in value)
    raise RolePlanError("provider option value must contain only JSON-like data")


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def _digest(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise RolePlanError("role-plan value cannot be canonically encoded") from exc
    if len(encoded) > _MAX_PLAN_BYTES:
        raise RolePlanError("role-plan projection exceeds its size limit")
    return hashlib.sha256(encoded).hexdigest()


def _physical_role_payload(roles: Sequence[RolePlanIdentity]) -> list[dict[str, Any]]:
    return [
        {
            "role": role.role,
            "selector": role.selector,
            "expected_device_by_id": role.expected_device_by_id,
            "expected_profile": role.expected_profile,
            "serial_port": role.serial_port,
        }
        for role in roles
    ]


def _provider_option_payload(
    options: Sequence[RolePlanProviderOption],
) -> list[dict[str, Any]]:
    return [
        {
            "namespace": option.namespace,
            "role": option.role,
            "key": option.key,
            "value": _json_value(option.value),
        }
        for option in options
    ]


def _whole_plan_digest(physical_digest: str, provider_digest: str) -> str:
    return _digest(
        {
            "physical_identity_digest": physical_digest,
            "provider_options_digest": provider_digest,
        }
    )


@dataclass(frozen=True, slots=True, repr=False)
class RolePlanOptionRequest:
    """Request one allowlisted namespaced config field for a generic role."""

    namespace: str
    role: str
    key: str

    def __post_init__(self) -> None:
        namespace = _identifier(self.namespace, "provider namespace")
        role = _identifier(self.role, "provider role")
        key = _identifier(self.key, "provider option key")
        if _SENSITIVE_OPTION_PATTERN.search(key):
            raise RolePlanError("sensitive provider option keys are not projectable")
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "key", key)


@dataclass(frozen=True, slots=True, repr=False)
class CaptureRolePlanRequest:
    """Optional generic role and provider-option projection request."""

    roles: tuple[str, ...]
    provider_options: tuple[RolePlanOptionRequest, ...] = ()

    def __post_init__(self) -> None:
        requested_roles = tuple(
            _identifier(role, "requested role")
            for role in _sequence(self.roles, "requested roles", _MAX_ROLES)
        )
        if len(set(requested_roles)) != len(requested_roles):
            raise RolePlanError("duplicate requested role")

        requested_options = _sequence(
            self.provider_options, "provider option requests", _MAX_PROVIDER_OPTIONS
        )
        if any(not isinstance(item, RolePlanOptionRequest) for item in requested_options):
            raise RolePlanError("provider option requests must use typed values")
        option_keys = tuple(
            (item.namespace, item.role, item.key) for item in requested_options
        )
        if len(set(option_keys)) != len(option_keys):
            raise RolePlanError("duplicate provider option request")
        role_set = set(requested_roles)
        if any(item.role not in role_set for item in requested_options):
            raise RolePlanError("provider option role was not requested")

        object.__setattr__(self, "roles", tuple(sorted(requested_roles)))
        object.__setattr__(
            self,
            "provider_options",
            tuple(sorted(requested_options, key=lambda item: (item.namespace, item.role, item.key))),
        )


@dataclass(frozen=True, slots=True, repr=False)
class RolePlanIdentity:
    """Explicit configured identity fields for one requested role."""

    role: str
    selector: str
    expected_device_by_id: str
    expected_profile: str
    serial_port: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _identifier(self.role, "role"))
        object.__setattr__(self, "selector", _identity_value(self.selector, "selector"))
        object.__setattr__(
            self,
            "expected_device_by_id",
            _identity_value(self.expected_device_by_id, "device_by_id"),
        )
        object.__setattr__(
            self,
            "expected_profile",
            _identity_value(self.expected_profile, "profile"),
        )
        if self.serial_port is not None:
            object.__setattr__(
                self, "serial_port", _identity_value(self.serial_port, "serial_port")
            )


@dataclass(frozen=True, slots=True, repr=False)
class RolePlanProviderOption:
    """One deeply immutable, host-allowlisted provider config value."""

    namespace: str
    role: str
    key: str
    value: Any

    def __post_init__(self) -> None:
        request = RolePlanOptionRequest(self.namespace, self.role, self.key)
        object.__setattr__(self, "namespace", request.namespace)
        object.__setattr__(self, "role", request.role)
        object.__setattr__(self, "key", request.key)
        object.__setattr__(self, "value", _freeze_value(self.value))


@dataclass(frozen=True, slots=True, repr=False)
class EffectiveRolePlan:
    """Frozen configuration projection with independent canonical digests."""

    roles: tuple[RolePlanIdentity, ...]
    provider_options: tuple[RolePlanProviderOption, ...]
    physical_identity_digest: str
    provider_options_digest: str
    digest: str

    def __post_init__(self) -> None:
        roles = _sequence(self.roles, "role plan identities", _MAX_ROLES)
        options = _sequence(
            self.provider_options, "role plan provider options", _MAX_PROVIDER_OPTIONS
        )
        if any(not isinstance(role, RolePlanIdentity) for role in roles):
            raise RolePlanError("role plan identities must use typed values")
        if any(not isinstance(option, RolePlanProviderOption) for option in options):
            raise RolePlanError("role plan options must use typed values")

        role_names = tuple(role.role for role in roles)
        if len(set(role_names)) != len(role_names):
            raise RolePlanError("duplicate role in effective role plan")
        if role_names != tuple(sorted(role_names)):
            raise RolePlanError("role order is not canonical")

        option_keys = tuple(
            (option.namespace, option.role, option.key) for option in options
        )
        if len(set(option_keys)) != len(option_keys):
            raise RolePlanError("duplicate provider option in effective role plan")
        if option_keys != tuple(sorted(option_keys)):
            raise RolePlanError("provider option order is not canonical")
        role_set = set(role_names)
        if any(option.role not in role_set for option in options):
            raise RolePlanError("provider option role is not present in the role plan")

        for value in (
            self.physical_identity_digest,
            self.provider_options_digest,
            self.digest,
        ):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise RolePlanError("role-plan digest is invalid")

        physical_digest = _digest(_physical_role_payload(roles))
        provider_digest = _digest(_provider_option_payload(options))
        whole_digest = _whole_plan_digest(physical_digest, provider_digest)
        if (
            self.physical_identity_digest != physical_digest
            or self.provider_options_digest != provider_digest
            or self.digest != whole_digest
        ):
            raise RolePlanError("role-plan digest does not match canonical contents")

        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "provider_options", options)


def _configured_role_entries(
    devices: Mapping[str, Any], requested_roles: tuple[str, ...]
) -> dict[str, Mapping[str, Any]]:
    requested = set(requested_roles)
    matches: dict[str, list[Mapping[str, Any]]] = {role: [] for role in requested_roles}
    for configured_role, config in devices.items():
        if not isinstance(configured_role, str):
            continue
        try:
            normalized_role = _identifier(configured_role, "configured role")
        except RolePlanError:
            continue
        if normalized_role not in requested:
            continue
        if not isinstance(config, Mapping):
            raise RolePlanError("requested role configuration must be a mapping")
        matches[normalized_role].append(config)

    result: dict[str, Mapping[str, Any]] = {}
    for role, entries in matches.items():
        if len(entries) > 1:
            raise RolePlanError("duplicate config role alias")
        if not entries:
            raise RolePlanError("requested role configuration is missing")
        result[role] = entries[0]
    return result


def _project_identity(role: str, config: Mapping[str, Any]) -> RolePlanIdentity:
    profile_fields = [
        (name, config[name])
        for name in ("profile", "console_profile")
        if name in config
    ]
    if not profile_fields:
        raise RolePlanError("requested role profile is missing or invalid")
    profiles = [_identity_value(value, "profile") for _, value in profile_fields]
    if any(profile != profiles[0] for profile in profiles[1:]):
        raise RolePlanError("requested role profile aliases conflict")

    serial_port = None
    if "serial_port" in config:
        serial_port = _identity_value(config["serial_port"], "serial_port")
    return RolePlanIdentity(
        role=role,
        selector=_identity_value(config.get("selector"), "selector"),
        expected_device_by_id=_identity_value(
            config.get("expected_device_by_id"), "device_by_id"
        ),
        expected_profile=profiles[0],
        serial_port=serial_port,
    )


def project_capture_role_plan(
    config: TestbedConfig,
    request: CaptureRolePlanRequest,
    *,
    allowed_provider_options: Sequence[RolePlanOptionRequest] = (),
) -> EffectiveRolePlan:
    """Project requested fields from the exact already-loaded testbed object.

    This helper performs no file I/O, path resolution, CWD lookup, defaults,
    broker query, or observation-based identity inference.
    """

    if not isinstance(config, TestbedConfig):
        raise RolePlanError("projection requires the selected TestbedConfig object")
    if not isinstance(request, CaptureRolePlanRequest):
        raise RolePlanError("projection requires a typed role-plan request")
    devices = config.devices
    if not isinstance(devices, Mapping):
        raise RolePlanError("selected testbed devices must be a mapping")

    config_by_role = _configured_role_entries(devices, request.roles)
    roles = tuple(
        _project_identity(role, config_by_role[role]) for role in request.roles
    )

    allowlist = _sequence(
        allowed_provider_options, "provider option allowlist", _MAX_PROVIDER_OPTIONS
    )
    if any(not isinstance(item, RolePlanOptionRequest) for item in allowlist):
        raise RolePlanError("provider option allowlist must use typed values")
    allowed_keys = tuple((item.namespace, item.role, item.key) for item in allowlist)
    if len(set(allowed_keys)) != len(allowed_keys):
        raise RolePlanError("duplicate provider option allowlist entry")
    allowed = set(allowed_keys)
    options: list[RolePlanProviderOption] = []
    for requested_option in request.provider_options:
        option_key = (
            requested_option.namespace,
            requested_option.role,
            requested_option.key,
        )
        if option_key not in allowed:
            raise RolePlanError("provider option request is not allowlisted")
        role_config = config_by_role[requested_option.role]
        if requested_option.key not in role_config:
            raise RolePlanError("provider option requested config value is missing")
        options.append(
            RolePlanProviderOption(
                *option_key, role_config[requested_option.key]
            )
        )

    provider_options = tuple(
        sorted(options, key=lambda item: (item.namespace, item.role, item.key))
    )
    physical_digest = _digest(_physical_role_payload(roles))
    provider_digest = _digest(_provider_option_payload(provider_options))
    plan_digest = _whole_plan_digest(physical_digest, provider_digest)
    return EffectiveRolePlan(
        roles=roles,
        provider_options=provider_options,
        physical_identity_digest=physical_digest,
        provider_options_digest=provider_digest,
        digest=plan_digest,
    )

"""Resolve a run logger target that is consistent with its serial transports."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence
from typing import Any

from testpilot.serialwrap_binary import (
    SERIALWRAP_BIN_ENV,
    resolve_serialwrap_binary,
)

SERIALWRAP_ENDPOINT_ENV = "SERIALWRAP_ENDPOINT"
_SERIAL_TRANSPORTS = {"serial", "serialwrap"}


@dataclass(frozen=True)
class SerialwrapLogBinding:
    """Resolved CLI target plus safe provenance suitable for a RunHandle."""

    enabled: bool
    binary: str | None
    socket: str | None
    binary_source: str
    socket_source: str
    device_count: int
    reason: str = ""

    def to_meta(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "binary_source": self.binary_source,
            "socket_source": self.socket_source,
            "device_count": self.device_count,
            "reason": self.reason,
        }


def _candidate(value: str | None) -> str | None:
    raw = os.path.expandvars(os.path.expanduser(str(value or "").strip()))
    if not raw:
        return None
    if os.path.sep in raw or raw.startswith("."):
        return str(Path(raw)) if Path(raw).is_file() else None
    return shutil.which(raw)


def _binary_identity(value: str) -> str:
    return os.path.normcase(os.path.realpath(value))


def _normalize_endpoint(value: str | None) -> str | None:
    raw = os.path.expandvars(os.path.expanduser(str(value or "").strip()))
    if not raw:
        return None
    if raw.startswith("unix://"):
        path = raw[len("unix://"):]
        return "unix://" + os.path.normcase(os.path.abspath(os.path.normpath(path)))
    if "://" in raw:
        # Preserve non-Unix endpoint schemes (notably tcp://); interpreting
        # their slashes as filesystem separators can alias a distinct socket.
        return raw
    if os.path.isabs(raw) or os.path.sep in raw:
        return "unix://" + os.path.normcase(os.path.abspath(os.path.normpath(raw)))
    return raw


def _disabled(
    reason: str,
    *,
    device_count: int,
    binary_source: str = "unresolved",
    socket_source: str = "ambiguous",
) -> SerialwrapLogBinding:
    return SerialwrapLogBinding(
        enabled=False,
        binary=None,
        socket=None,
        binary_source=binary_source,
        socket_source=socket_source,
        device_count=device_count,
        reason=reason,
    )


def resolve_serialwrap_log_binding(
    config: dict[str, Any] | None,
    *,
    backend_binary: str | None = None,
    roles: Sequence[str] | None = None,
    strict: bool = False,
) -> SerialwrapLogBinding:
    """Resolve backend logging to one explicit device target or fail closed.

    The run-level logger is not allowed to use a separate local installation
    when DUT and STA transports use a configured wrapper/socket. The environment
    remains first priority because both the transport and logger use the same
    resolver and inherited environment.
    """
    testbed = config if isinstance(config, dict) else {}
    raw_devices = testbed.get("devices", {})
    devices = raw_devices if isinstance(raw_devices, dict) else {}
    selected: list[dict[str, Any]] = []
    selected_roles: tuple[str, ...]
    if roles is None:
        if strict:
            return _disabled("strict capture requires an explicit role plan", device_count=0)
        selected_roles = ("dut", "sta")
        for role in selected_roles:
            raw = devices.get(role) or devices.get(role.upper())
            if not isinstance(raw, dict):
                continue
            transport = str(raw.get("transport") or "").strip().lower()
            if transport in _SERIAL_TRANSPORTS or (
                not transport
                and any(
                    key in raw
                    for key in ("binary", "socket", "selector", "com_port", "serial_port")
                )
            ):
                selected.append(raw)
    else:
        if isinstance(roles, (str, bytes)):
            return _disabled("strict capture role plan is invalid", device_count=0)
        selected_roles = tuple(roles)
        if (
            not selected_roles
            or len(selected_roles) > 32
            or any(type(role) is not str or not role for role in selected_roles)
            or len(set(role.casefold() for role in selected_roles)) != len(selected_roles)
        ):
            return _disabled("strict capture role plan is invalid", device_count=0)
        normalized_devices: dict[str, list[Any]] = {}
        for role_name, raw in devices.items():
            if type(role_name) is str:
                normalized_devices.setdefault(role_name.strip().casefold(), []).append(raw)
        for role in selected_roles:
            matches = normalized_devices.get(role.casefold(), [])
            if len(matches) != 1 or not isinstance(matches[0], dict):
                return _disabled(
                    "strict capture role configuration is ambiguous",
                    device_count=len(selected),
                )
            raw = matches[0]
            transport = str(raw.get("transport") or "").strip().lower()
            if strict and transport and transport not in _SERIAL_TRANSPORTS:
                return _disabled(
                    "strict capture role does not select a supported serial transport",
                    device_count=len(selected),
                )
            if strict and not transport and not str(raw.get("selector") or "").strip():
                return _disabled(
                    "strict capture role selector is missing",
                    device_count=len(selected),
                )
            if transport in _SERIAL_TRANSPORTS or (
                not transport
                and any(
                    key in raw
                    for key in ("binary", "socket", "selector", "com_port", "serial_port")
                )
            ):
                selected.append(raw)
            else:
                return _disabled(
                    "strict capture role does not select a serial transport",
                    device_count=len(selected),
                )

    if not selected:
        return _disabled(
            "no serialwrap DUT/STA transport is configured",
            device_count=0,
            binary_source="unresolved",
            socket_source="unresolved",
        )

    env_binary = _candidate(os.environ.get(SERIALWRAP_BIN_ENV))
    binary_source = (
        SERIALWRAP_BIN_ENV
        if env_binary
        else "device_config"
        if all(str(device.get("binary") or "").strip() for device in selected)
        else "device_config_and_PATH"
        if any(str(device.get("binary") or "").strip() for device in selected)
        else "PATH"
    )

    try:
        resolved_devices = [
            resolve_serialwrap_binary(
                str(device.get("binary")) if device.get("binary") else None,
                config_label="'binary' in device transport config",
            )
            for device in selected
        ]
        identities = {_binary_identity(value) for value in resolved_devices}
        if len(identities) != 1:
            return _disabled(
                "serialwrap device binaries differ",
                device_count=len(selected),
                binary_source=binary_source,
            )
        binary = resolved_devices[0]

        # A backend-only override does not change the binary selected by
        # SerialWrapTransport. Check it unless a valid environment override
        # wins for both consumers.
        if backend_binary and not env_binary:
            backend_resolved = resolve_serialwrap_binary(
                backend_binary,
                config_label="'serialwrap_binary' in testbed config",
            )
            if _binary_identity(backend_resolved) not in identities:
                return _disabled(
                    "run backend binary conflicts with serialwrap device binary",
                    device_count=len(selected),
                    binary_source=binary_source,
                )
    except (FileNotFoundError, OSError, ValueError) as exc:
        return _disabled(
            f"serialwrap binary cannot be resolved: {type(exc).__name__}",
            device_count=len(selected),
            binary_source=binary_source,
        )

    env_endpoint = os.environ.get(SERIALWRAP_ENDPOINT_ENV)
    normalized_env = _normalize_endpoint(env_endpoint)
    explicit = [
        str(device.get("socket")).strip()
        for device in selected
        if str(device.get("socket") or "").strip()
    ]
    normalized_explicit = {_normalize_endpoint(value) for value in explicit}
    if len(normalized_explicit) > 1:
        return _disabled(
            "serialwrap device endpoints differ",
            device_count=len(selected),
            binary_source=binary_source,
            socket_source="device_config",
        )

    has_default_endpoint = len(explicit) != len(selected)
    if selected and explicit and has_default_endpoint:
        if normalized_env is None or normalized_env not in normalized_explicit:
            return _disabled(
                "serialwrap device endpoints differ",
                device_count=len(selected),
                binary_source=binary_source,
                socket_source="mixed_device_config",
            )

    configured_socket = str(testbed.get("serialwrap_socket") or "").strip() or None
    if configured_socket:
        normalized_configured = _normalize_endpoint(configured_socket)
        effective_endpoints = normalized_explicit or ({normalized_env} if normalized_env else set())
        if effective_endpoints and effective_endpoints != {normalized_configured}:
            return _disabled(
                "run backend socket conflicts with serialwrap device endpoint",
                device_count=len(selected),
                binary_source=binary_source,
                socket_source="testbed_config",
            )
        if selected and not effective_endpoints:
            return _disabled(
                "run backend socket is not selected by serialwrap devices",
                device_count=len(selected),
                binary_source=binary_source,
                socket_source="testbed_config",
            )

    if explicit:
        # Pass the same spelling the selected transport passes to its CLI.
        socket = explicit[0]
        socket_source = "device_config"
    elif normalized_env:
        # Strict callers pass this exact inherited endpoint explicitly so a
        # plugin callback cannot redirect later child processes by changing
        # the environment. Legacy callers preserve their old inherited form.
        socket = env_endpoint if strict else None
        socket_source = SERIALWRAP_ENDPOINT_ENV
    else:
        # Both clients use the same serialwrap user/default endpoint resolver.
        socket = None
        socket_source = "serialwrap_default"

    if strict and socket_source == "serialwrap_default":
        return _disabled(
            "strict capture requires an explicitly configured provider endpoint",
            device_count=len(selected),
            binary_source=binary_source,
            socket_source=socket_source,
        )

    return SerialwrapLogBinding(
        enabled=True,
        binary=binary,
        socket=socket,
        binary_source=binary_source,
        socket_source=socket_source,
        device_count=len(selected),
    )

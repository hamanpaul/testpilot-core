"""Domain-neutral tier-2 environment-recovery contracts and validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json
import math
import re
from typing import Any


_MAX_DIAGNOSIS_CHARS = 2_000
_MAX_VERIFY_DEFINITION_CHARS = 2_000
_MAX_LOG_LINES = 12
_MAX_LOG_LINE_CHARS = 800
_MAX_CAPABILITIES = 20
_MAX_CAPABILITY_DESCRIPTION_CHARS = 400
_MAX_GENERIC_STRING_CHARS = 1_000
_MAX_GENERIC_ITEMS = 20
_MAX_GENERIC_KEYS = 40
_MAX_ONE_SHOT_PROMPT_CHARS = 64_000
_MAX_RAW_RESPONSE_CHARS = 64_000
_MAX_AUDIT_PROMPT_CHARS = 40_000

_EXECUTOR_KEY_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_COMMAND_LIKE_PARAM_RE = re.compile(r"(?i)(?:command|cmd|exec|shell|script|argv)")
_FENCED_JSON_RE = re.compile(
    r"\A```(?:json)?\s*(\{.*\})\s*```\Z",
    flags=re.DOTALL | re.IGNORECASE,
)
_AUTH_HEADER_RE = re.compile(
    r"(?im)(\bauthorization\s*[:=]\s*)([^\r\n,;]+)"
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|"
    r"password|passwd|secret|authorization|credential|endpoint|"
    r"base[_-]?url|psk|(?:key|wpa[_-]?)?pass[_-]?phrase|"
    r"wep[_-]?key|private[_-]?key)\b\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_SENSITIVE_JSON_VALUE_RE = re.compile(
    r'(?i)("(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|'
    r'password|passwd|secret|authorization|credential|endpoint|'
    r'base[_-]?url|psk|(?:key|wpa[_-]?)?pass[_-]?phrase|'
    r'wep[_-]?key|private[_-]?key)"\s*:\s*)'
    r'("[^"\r\n]*")'
)
_SENSITIVE_KEY_MARKERS = (
    "apikey",
    "accesstoken",
    "refreshtoken",
    "token",
    "password",
    "passwd",
    "secret",
    "authorization",
    "credential",
    "endpoint",
    "baseurl",
    "psk",
    "passphrase",
    "wepkey",
    "privatekey",
)
_FORBIDDEN_CONTROL_FIELDS = {
    "caseyaml",
    "criteria",
    "evaluation",
    "passcriteria",
    "step",
    "steps",
    "testcase",
    "teststeps",
    "verdict",
}


class Tier2PlanValidationError(ValueError):
    """Raised when an LLM tier-2 plan violates the control-plane contract."""


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _is_sensitive_key(value: Any) -> bool:
    normalized = _normalized_key(value)
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "...[TRUNCATED]"


def _redact_text(value: Any, *, limit: int = _MAX_GENERIC_STRING_CHARS) -> str:
    text = _bounded_text(value, limit)
    text = _AUTH_HEADER_RE.sub(r"\1[REDACTED]", text)
    text = _SENSITIVE_JSON_VALUE_RE.sub(r'\1"[REDACTED]"', text)
    return _SENSITIVE_ASSIGNMENT_RE.sub(r"\1[REDACTED]", text)


def sanitize_tier2_value(value: Any, *, _depth: int = 0) -> Any:
    """Redact common secret shapes and bound arbitrary prompt/audit values."""
    if _depth >= 5:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for index, (raw_key, raw_value) in enumerate(value.items()):
            if index >= _MAX_GENERIC_KEYS:
                sanitized["..."] = "[TRUNCATED]"
                break
            key = _bounded_text(raw_key, 100)
            if _is_sensitive_key(key):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_tier2_value(
                    raw_value,
                    _depth=_depth + 1,
                )
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            sanitize_tier2_value(item, _depth=_depth + 1)
            for item in list(value)[:_MAX_GENERIC_ITEMS]
        ]
    if isinstance(value, float) and not math.isfinite(value):
        return "[NON_FINITE]"
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _redact_text(value)


@dataclass(frozen=True, slots=True)
class Tier2Capability:
    """One plugin-advertised environment-only executor available to tier-2."""

    executor_key: str
    description: str
    execution_boundary: str
    params_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Tier2RecoveryContext:
    """Bounded, redacted plugin context used to build the one-shot prompt."""

    diagnosis: str
    log_excerpt: tuple[str, ...]
    capabilities: tuple[Tier2Capability, ...]
    verify_env_definition: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "Tier2RecoveryContext":
        raw_capabilities = raw.get("capabilities", [])
        if not isinstance(raw_capabilities, Sequence) or isinstance(
            raw_capabilities,
            (str, bytes, bytearray),
        ):
            raise ValueError("tier-2 capabilities must be a sequence")
        if len(list(raw_capabilities)) > _MAX_CAPABILITIES:
            raise ValueError(
                f"tier-2 capability catalog must not exceed {_MAX_CAPABILITIES} entries"
            )

        capabilities: list[Tier2Capability] = []
        seen_executor_keys: set[str] = set()
        for item in list(raw_capabilities)[:_MAX_CAPABILITIES]:
            if not isinstance(item, Mapping):
                raise ValueError("tier-2 capability must be a mapping")
            executor_key = str(item.get("executor_key", "") or "").strip()
            if not _EXECUTOR_KEY_RE.fullmatch(executor_key):
                raise ValueError(f"invalid tier-2 executor_key: {executor_key!r}")
            if executor_key in seen_executor_keys:
                raise ValueError(f"duplicate tier-2 executor_key: {executor_key}")
            seen_executor_keys.add(executor_key)
            execution_boundary = _redact_text(
                item.get("execution_boundary", ""),
                limit=_MAX_CAPABILITY_DESCRIPTION_CHARS,
            ).strip()
            if not execution_boundary:
                raise ValueError(
                    f"tier-2 capability {executor_key!r} execution_boundary "
                    "must not be empty"
                )
            raw_params_schema = item.get("params_schema", {})
            if isinstance(raw_params_schema, Mapping):
                if _contains_sensitive_material(raw_params_schema):
                    raise ValueError(
                        "tier-2 capability schema contains sensitive material"
                    )
                if _contains_forbidden_control_field(raw_params_schema):
                    raise ValueError(
                        "tier-2 capability schema contains forbidden control-plane field"
                    )
                _validate_capability_schema(raw_params_schema)
            params_schema = (
                sanitize_tier2_value(raw_params_schema)
                if isinstance(raw_params_schema, Mapping)
                else {}
            )
            capabilities.append(
                Tier2Capability(
                    executor_key=executor_key,
                    description=_redact_text(
                        item.get("description", ""),
                        limit=_MAX_CAPABILITY_DESCRIPTION_CHARS,
                    ),
                    execution_boundary=execution_boundary,
                    params_schema=dict(params_schema),
                )
            )
        if not capabilities:
            raise ValueError("tier-2 capability catalog must not be empty")

        raw_logs = raw.get("log_excerpt", [])
        logs = (
            list(raw_logs)
            if isinstance(raw_logs, Sequence)
            and not isinstance(raw_logs, (str, bytes, bytearray))
            else [raw_logs]
        )
        log_excerpt = tuple(
            _redact_text(item, limit=_MAX_LOG_LINE_CHARS)
            for item in logs[:_MAX_LOG_LINES]
        )
        verify_definition = _redact_text(
            raw.get("verify_env_definition", ""),
            limit=_MAX_VERIFY_DEFINITION_CHARS,
        ).strip()
        if not verify_definition:
            raise ValueError("tier-2 verify_env_definition must not be empty")

        metadata_raw = raw.get("metadata", {})
        metadata = (
            sanitize_tier2_value(metadata_raw)
            if isinstance(metadata_raw, Mapping)
            else {}
        )
        return cls(
            diagnosis=_redact_text(
                raw.get("diagnosis", ""),
                limit=_MAX_DIAGNOSIS_CHARS,
            ),
            log_excerpt=log_excerpt,
            capabilities=tuple(capabilities),
            verify_env_definition=verify_definition,
            metadata=dict(metadata),
        )

    @property
    def allowed_executor_keys(self) -> set[str]:
        return {capability.executor_key for capability in self.capabilities}

    @property
    def capability_schemas(self) -> dict[str, dict[str, Any]]:
        return {
            capability.executor_key: dict(capability.params_schema)
            for capability in self.capabilities
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnosis": self.diagnosis,
            "log_excerpt": list(self.log_excerpt),
            "capabilities": [item.to_dict() for item in self.capabilities],
            "verify_env_definition": self.verify_env_definition,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class Tier2RecoveryAudit:
    """Serializable audit record for one bounded tier-2 invocation."""

    case_id: str
    attempt_index: int
    tier1_failures: int
    trigger_threshold: int
    context: dict[str, Any]
    prompt: str
    raw_response: str = ""
    plan: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    verify_gate: dict[str, Any] | None = None
    status: str = "pending"
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": _bounded_text(self.case_id, 200),
            "attempt_index": int(self.attempt_index),
            "tier1_failures": int(self.tier1_failures),
            "trigger_threshold": int(self.trigger_threshold),
            "context": sanitize_tier2_value(self.context),
            "prompt": _redact_text(
                self.prompt,
                limit=_MAX_AUDIT_PROMPT_CHARS,
            ),
            "raw_response": _redact_text(
                self.raw_response,
                limit=_MAX_RAW_RESPONSE_CHARS,
            ),
            "plan": sanitize_tier2_value(self.plan),
            "execution": sanitize_tier2_value(self.execution),
            "verify_gate": sanitize_tier2_value(self.verify_gate),
            "status": _bounded_text(self.status, 100),
            "error": _redact_text(self.error, limit=2_000),
            "warnings": [
                _redact_text(item, limit=500)
                for item in self.warnings[:8]
                if str(item).strip()
            ],
            "truncated": bool(self.truncated),
        }


@dataclass(frozen=True, slots=True)
class Tier2PromptPayload:
    prompt: str
    truncated: bool = False


def _tier2_prompt_template(structured_input: str) -> str:
    return (
        "You are TestPilot's tier-2 environment-recovery planner. "
        "Produce a bounded environment repair plan only.\n\n"
        "Hard boundary: do not modify or reinterpret test steps, pass criteria, "
        "case YAML, evidence, evaluation, or verdict. Do not claim that the "
        "environment is healthy; TestPilot will run its deterministic verify_env "
        "gate after execution. Use only executor_key values listed in the plugin "
        "capability catalog.\n\n"
        "Return exactly one JSON object with this schema and no prose:\n"
        "{\n"
        '  "summary": "short diagnosis and objective",\n'
        '  "rationale": "why this ordered plan may repair the environment",\n'
        '  "actions": [\n'
        "    {\n"
        '      "executor_key": "catalog key",\n'
        '      "description": "operator-readable action",\n'
        '      "device": "optional plugin device label",\n'
        '      "band": "optional plugin scope",\n'
        '      "params": {}\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Structured failure scene and plugin contract:\n"
        f"{structured_input}"
    )


def _render_prompt_payload(payload: Mapping[str, Any]) -> str:
    structured_input = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return _tier2_prompt_template(structured_input)


def _prompt_failure_view(
    failure: Mapping[str, Any],
    *,
    compact: bool,
    minimal: bool,
) -> dict[str, Any]:
    view = dict(failure)
    if minimal:
        return {
            "category": _bounded_text(view.get("category", ""), 64),
            "reason_code": _bounded_text(view.get("reason_code", ""), 128),
            "comment": _bounded_text(view.get("comment", ""), 240),
        }
    if compact:
        trimmed = {
            "category": _bounded_text(view.get("category", ""), 64),
            "reason_code": _bounded_text(view.get("reason_code", ""), 128),
            "comment": _bounded_text(view.get("comment", ""), 400),
            "output": _bounded_text(view.get("output", ""), 600),
        }
        evidence = view.get("evidence", [])
        if isinstance(evidence, Sequence) and not isinstance(
            evidence,
            (str, bytes, bytearray),
        ):
            trimmed["evidence"] = [
                _bounded_text(item, 200)
                for item in list(evidence)[:4]
            ]
        return trimmed
    return view


def _prompt_params_schema(
    schema: Mapping[str, Any],
    *,
    compact: bool,
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for index, (raw_name, raw_spec) in enumerate(schema.items()):
        if compact and index >= 12:
            projected["..."] = "[TRUNCATED]"
            break
        name = _bounded_text(raw_name, 100)
        if isinstance(raw_spec, str):
            projected[name] = raw_spec
            continue
        if not isinstance(raw_spec, Mapping):
            projected[name] = sanitize_tier2_value(raw_spec)
            continue
        spec: dict[str, Any] = {"type": str(raw_spec.get("type", "string"))}
        if raw_spec.get("required") is True:
            spec["required"] = True
        if "enum" in raw_spec and isinstance(raw_spec["enum"], list):
            limit = 8 if compact else len(raw_spec["enum"])
            spec["enum"] = [
                sanitize_tier2_value(item)
                for item in raw_spec["enum"][:limit]
            ]
        if "max_length" in raw_spec:
            spec["max_length"] = raw_spec["max_length"]
        projected[name] = spec
    return projected


def _prompt_context_view(
    context: Tier2RecoveryContext,
    *,
    compact: bool,
    minimal: bool,
) -> dict[str, Any]:
    if minimal:
        return {
            "diagnosis": _bounded_text(context.diagnosis, 400),
            "log_excerpt": [
                _bounded_text(item, 160)
                for item in context.log_excerpt[:2]
            ],
            "capabilities": [
                {
                    "executor_key": capability.executor_key,
                    "params_schema": _prompt_params_schema(
                        capability.params_schema,
                        compact=True,
                    ),
                }
                for capability in context.capabilities[:8]
            ],
            "verify_env_definition": _bounded_text(
                context.verify_env_definition,
                400,
            ),
            "metadata": {"truncated": True},
        }
    capabilities = []
    for capability in context.capabilities:
        item: dict[str, Any] = {
            "executor_key": capability.executor_key,
            "description": _bounded_text(
                capability.description,
                160 if compact else _MAX_CAPABILITY_DESCRIPTION_CHARS,
            ),
            "execution_boundary": _bounded_text(
                capability.execution_boundary,
                160 if compact else _MAX_CAPABILITY_DESCRIPTION_CHARS,
            ),
            "params_schema": _prompt_params_schema(
                capability.params_schema,
                compact=compact,
            ),
        }
        capabilities.append(item)
    metadata = {"truncated": True} if compact else dict(context.metadata)
    return {
        "diagnosis": _bounded_text(
            context.diagnosis,
            800 if compact else _MAX_DIAGNOSIS_CHARS,
        ),
        "log_excerpt": [
            _bounded_text(item, 240 if compact else _MAX_LOG_LINE_CHARS)
            for item in (
                context.log_excerpt[:4] if compact else context.log_excerpt
            )
        ],
        "capabilities": capabilities,
        "verify_env_definition": _bounded_text(
            context.verify_env_definition,
            800 if compact else _MAX_VERIFY_DEFINITION_CHARS,
        ),
        "metadata": metadata,
    }


def build_tier2_prompt_payload(
    *,
    context: Tier2RecoveryContext | Mapping[str, Any],
    failure: Mapping[str, Any],
    tier1_failures: int,
) -> Tier2PromptPayload:
    normalized_context = Tier2RecoveryContext.from_mapping(
        context.to_dict()
        if isinstance(context, Tier2RecoveryContext)
        else context
    )
    safe_failure = sanitize_tier2_value(failure)
    base_payload = {
        "tier1_failures": max(0, int(tier1_failures)),
        "failure": _prompt_failure_view(
            safe_failure if isinstance(safe_failure, Mapping) else {},
            compact=False,
            minimal=False,
        ),
        "context": _prompt_context_view(
            normalized_context,
            compact=False,
            minimal=False,
        ),
    }
    prompt = _render_prompt_payload(base_payload)
    if len(prompt) <= _MAX_ONE_SHOT_PROMPT_CHARS:
        return Tier2PromptPayload(prompt=prompt, truncated=False)

    compact_payload = {
        "tier1_failures": base_payload["tier1_failures"],
        "failure": _prompt_failure_view(
            safe_failure if isinstance(safe_failure, Mapping) else {},
            compact=True,
            minimal=False,
        ),
        "context": _prompt_context_view(
            normalized_context,
            compact=True,
            minimal=False,
        ),
    }
    prompt = _render_prompt_payload(compact_payload)
    if len(prompt) <= _MAX_ONE_SHOT_PROMPT_CHARS:
        return Tier2PromptPayload(prompt=prompt, truncated=True)

    minimal_payload = {
        "tier1_failures": base_payload["tier1_failures"],
        "failure": _prompt_failure_view(
            safe_failure if isinstance(safe_failure, Mapping) else {},
            compact=True,
            minimal=True,
        ),
        "context": _prompt_context_view(
            normalized_context,
            compact=True,
            minimal=True,
        ),
    }
    prompt = _render_prompt_payload(minimal_payload)
    if len(prompt) > _MAX_ONE_SHOT_PROMPT_CHARS:
        raise ValueError("tier-2 prompt exceeds bounded size")
    return Tier2PromptPayload(prompt=prompt, truncated=True)


def build_tier2_prompt(
    *,
    context: Tier2RecoveryContext | Mapping[str, Any],
    failure: Mapping[str, Any],
    tier1_failures: int,
) -> str:
    """Build the core-owned one-shot prompt from bounded plugin context."""
    return build_tier2_prompt_payload(
        context=context,
        failure=failure,
        tier1_failures=tier1_failures,
    ).prompt


def _contains_forbidden_control_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _normalized_key(key) in _FORBIDDEN_CONTROL_FIELDS:
                return True
            if _contains_forbidden_control_field(item):
                return True
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return any(_contains_forbidden_control_field(item) for item in value)
    return False


def _contains_sensitive_material(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_sensitive_key(key) or _contains_sensitive_material(item):
                return True
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return any(_contains_sensitive_material(item) for item in value)
    elif isinstance(value, str):
        return _redact_text(value, limit=max(len(value), 1)) != value
    return False


_SUPPORTED_PARAM_TYPES = {
    "array": list,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "object": Mapping,
    "string": str,
}
_ALLOWED_PARAM_SPEC_FIELDS = {
    "description",
    "enum",
    "max_length",
    "required",
    "type",
}


def _validate_bounded_json_value(
    value: Any,
    *,
    path: str,
    _depth: int = 0,
) -> None:
    if _depth >= 5:
        raise ValueError(f"{path} exceeds nesting depth limit")
    if isinstance(value, Mapping):
        if len(value) > _MAX_GENERIC_KEYS:
            raise ValueError(f"{path} exceeds mapping length limit")
        for raw_key, item in value.items():
            if not isinstance(raw_key, str) or not raw_key or len(raw_key) > 100:
                raise ValueError(f"{path} contains an invalid mapping key")
            _validate_bounded_json_value(
                item,
                path=f"{path}.{raw_key}",
                _depth=_depth + 1,
            )
        return
    if isinstance(value, list):
        if len(value) > _MAX_GENERIC_ITEMS:
            raise ValueError(f"{path} exceeds sequence length limit")
        for index, item in enumerate(value):
            _validate_bounded_json_value(
                item,
                path=f"{path}[{index}]",
                _depth=_depth + 1,
            )
        return
    if isinstance(value, str):
        if len(value) > _MAX_GENERIC_STRING_CHARS:
            raise ValueError(f"{path} exceeds string length limit")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} contains a non-finite number")
    if isinstance(value, (bool, int, float)) or value is None:
        return
    raise ValueError(f"{path} contains a non-JSON value")


def _value_matches_param_type(value: Any, type_name: str) -> bool:
    expected_type = _SUPPORTED_PARAM_TYPES[type_name]
    if type_name in {"integer", "number"} and isinstance(value, bool):
        return False
    return isinstance(value, expected_type)


def _validate_capability_schema(schema: Mapping[str, Any]) -> None:
    _validate_bounded_json_value(schema, path="tier-2 capability schema")
    for raw_name, raw_spec in schema.items():
        name = str(raw_name).strip()
        if not name or len(name) > 100:
            raise ValueError(f"invalid tier-2 capability parameter: {name!r}")
        if isinstance(raw_spec, str):
            type_name = raw_spec
        elif isinstance(raw_spec, Mapping):
            unknown_fields = set(raw_spec) - _ALLOWED_PARAM_SPEC_FIELDS
            if unknown_fields:
                raise ValueError(
                    "tier-2 capability parameter schema has unsupported fields: "
                    + ", ".join(sorted(str(item) for item in unknown_fields))
                )
            type_name = str(raw_spec.get("type", "string"))
            if "required" in raw_spec and not isinstance(
                raw_spec["required"],
                bool,
            ):
                raise ValueError(
                    f"tier-2 capability parameter {name!r} required must be boolean"
                )
            if "enum" in raw_spec and not isinstance(raw_spec["enum"], list):
                raise ValueError(
                    f"tier-2 capability parameter {name!r} enum must be a list"
                )
            if "max_length" in raw_spec:
                try:
                    max_length = int(raw_spec["max_length"])
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"tier-2 capability parameter {name!r} max_length must be positive"
                    ) from exc
                if max_length < 1:
                    raise ValueError(
                        f"tier-2 capability parameter {name!r} max_length must be positive"
                    )
                if type_name not in {"array", "object", "string"}:
                    raise ValueError(
                        f"tier-2 capability parameter {name!r} max_length "
                        f"is invalid for type {type_name!r}"
                    )
        else:
            raise ValueError(
                f"tier-2 capability parameter {name!r} schema must be a type or mapping"
            )
        if type_name not in _SUPPORTED_PARAM_TYPES:
            raise ValueError(
                f"tier-2 capability parameter {name!r} has unsupported type {type_name!r}"
            )
        if (
            _COMMAND_LIKE_PARAM_RE.search(name)
            and type_name == "string"
            and (not isinstance(raw_spec, Mapping) or "enum" not in raw_spec)
        ):
            raise ValueError(
                f"tier-2 capability parameter {name!r} must declare enum"
            )
        if isinstance(raw_spec, Mapping) and "enum" in raw_spec:
            if any(
                not _value_matches_param_type(item, type_name)
                for item in raw_spec["enum"]
            ):
                raise ValueError(
                    f"tier-2 capability parameter {name!r} enum values "
                    f"must be {type_name}"
                )


def _validate_action_params(
    *,
    executor_key: str,
    params: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> None:
    try:
        _validate_bounded_json_value(
            params,
            path=f"tier-2 {executor_key!r} params",
        )
    except ValueError as exc:
        raise Tier2PlanValidationError(str(exc)) from exc
    unknown_params = set(params) - set(schema)
    if unknown_params:
        raise Tier2PlanValidationError(
            f"tier-2 {executor_key!r} params outside capability schema: "
            + ", ".join(sorted(str(item) for item in unknown_params))
        )

    for raw_name, raw_spec in schema.items():
        name = str(raw_name)
        spec = {"type": raw_spec} if isinstance(raw_spec, str) else dict(raw_spec)
        if spec.get("required") is True and name not in params:
            raise Tier2PlanValidationError(
                f"tier-2 {executor_key!r} param {name!r} is required"
            )
        if name not in params:
            continue
        value = params[name]
        type_name = str(spec.get("type", "string"))
        if not _value_matches_param_type(value, type_name):
            raise Tier2PlanValidationError(
                f"tier-2 {executor_key!r} param {name!r} must be {type_name}"
            )
        if "enum" in spec and value not in spec["enum"]:
            raise Tier2PlanValidationError(
                f"tier-2 {executor_key!r} param {name!r} is outside allowed enum"
            )
        if "max_length" in spec and len(value) > int(spec["max_length"]):
            raise Tier2PlanValidationError(
                f"tier-2 {executor_key!r} param {name!r} exceeds max_length"
            )


def _load_plan_object(raw_response: str) -> dict[str, Any]:
    text = raw_response.strip()
    fenced = _FENCED_JSON_RE.fullmatch(text)
    if fenced:
        text = fenced.group(1)

    def _reject_non_finite_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        loaded = json.loads(text, parse_constant=_reject_non_finite_constant)
    except (TypeError, ValueError) as exc:
        raise Tier2PlanValidationError(
            "tier-2 response must be one valid JSON object"
        ) from exc
    if not isinstance(loaded, dict):
        raise Tier2PlanValidationError(
            "tier-2 response must be one valid JSON object"
        )
    return loaded


def parse_tier2_plan(
    raw_response: str,
    *,
    capability_schemas: Mapping[str, Mapping[str, Any]],
    max_actions: int,
) -> dict[str, Any]:
    """Validate and normalize a one-shot response without executing it."""
    if len(raw_response) > _MAX_RAW_RESPONSE_CHARS:
        raise Tier2PlanValidationError(
            f"tier-2 response size limit exceeded ({_MAX_RAW_RESPONSE_CHARS} chars)"
        )
    try:
        action_budget = int(max_actions)
    except (TypeError, ValueError) as exc:
        raise Tier2PlanValidationError(
            "tier-2 action budget must be positive"
        ) from exc
    if action_budget < 1:
        raise Tier2PlanValidationError("tier-2 action budget must be positive")

    normalized_schemas: dict[str, dict[str, Any]] = {}
    for raw_key, raw_schema in capability_schemas.items():
        executor_key = str(raw_key)
        if not isinstance(raw_schema, Mapping):
            raise Tier2PlanValidationError(
                f"tier-2 capability schema for {executor_key!r} must be a mapping"
            )
        try:
            _validate_capability_schema(raw_schema)
        except ValueError as exc:
            raise Tier2PlanValidationError(str(exc)) from exc
        normalized_schemas[executor_key] = dict(raw_schema)

    if _redact_text(raw_response, limit=max(len(raw_response), 1)) != raw_response:
        raise Tier2PlanValidationError(
            "tier-2 response contains sensitive material"
        )
    data = _load_plan_object(raw_response)
    unknown_top_level = set(data) - {"summary", "rationale", "actions"}
    if unknown_top_level:
        raise Tier2PlanValidationError(
            "tier-2 response contains forbidden control-plane field: "
            + ", ".join(sorted(unknown_top_level))
        )
    summary = _bounded_text(data.get("summary", ""), 2_000).strip()
    if not summary:
        raise Tier2PlanValidationError("tier-2 plan summary must not be empty")
    rationale = _bounded_text(data.get("rationale", ""), 4_000).strip()

    raw_actions = data.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise Tier2PlanValidationError("tier-2 plan actions must not be empty")
    if len(raw_actions) > action_budget:
        raise Tier2PlanValidationError(
            f"tier-2 plan exceeds action budget ({len(raw_actions)} > {action_budget})"
        )

    actions: list[dict[str, Any]] = []
    allowed_action_fields = {
        "executor_key",
        "description",
        "device",
        "band",
        "params",
    }
    for raw_action in raw_actions:
        if not isinstance(raw_action, Mapping):
            raise Tier2PlanValidationError("tier-2 action must be a mapping")
        unknown_action_fields = set(raw_action) - allowed_action_fields
        if unknown_action_fields:
            raise Tier2PlanValidationError(
                "tier-2 action contains forbidden control-plane field: "
                + ", ".join(sorted(unknown_action_fields))
            )
        executor_key = str(raw_action.get("executor_key", "") or "").strip()
        if executor_key not in normalized_schemas:
            raise Tier2PlanValidationError(
                f"tier-2 executor outside plugin capability catalog: {executor_key!r}"
            )
        params = raw_action.get("params", {})
        if not isinstance(params, Mapping):
            raise Tier2PlanValidationError("tier-2 action params must be a mapping")
        if _contains_sensitive_material(params):
            raise Tier2PlanValidationError(
                "tier-2 action params contain sensitive material"
            )
        if _contains_forbidden_control_field(params):
            raise Tier2PlanValidationError(
                "tier-2 action params contain forbidden control-plane field"
            )
        _validate_action_params(
            executor_key=executor_key,
            params=params,
            schema=normalized_schemas[executor_key],
        )
        actions.append(
            {
                "executor_key": executor_key,
                "description": _bounded_text(
                    raw_action.get("description", ""),
                    1_000,
                ),
                "device": _bounded_text(raw_action.get("device", ""), 100),
                "band": _bounded_text(raw_action.get("band", ""), 100),
                "params": deepcopy(dict(params)),
                "safety_class": "tier2_env",
                "source": "tier2-agent",
            }
        )

    return {
        "summary": summary,
        "rationale": rationale,
        "source": "tier2-agent",
        "schema_validated": True,
        "actions": actions,
    }

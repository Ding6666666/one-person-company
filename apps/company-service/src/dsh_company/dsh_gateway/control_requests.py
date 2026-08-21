import json
import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

from dsh_company.domain.policy import ACTION_LEVELS

_MAX_RESPONSE_BYTES = 32 * 1024
_BoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
_Identifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
_Objective = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
_Action = Literal[
    "conversation.respond",
    "workspace.read",
    "session.history.read",
    "work.delegate",
    "workspace.write",
    "tool.shell",
    "tool.network",
    "external.publish",
]


class _StrictControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DelegationControlRequest(_StrictControlRequest):
    kind: Literal["delegation"]
    target_employee_id: _Identifier
    objective: _Objective
    acceptance_criteria: tuple[_BoundedText, ...] = Field(min_length=1, max_length=32)
    required_actions: tuple[_Action, ...] = Field(min_length=1, max_length=32)
    resource_values: tuple[_Identifier, ...] = Field(min_length=1, max_length=128)
    reason: _BoundedText

    @field_validator("required_actions", mode="before")
    @classmethod
    def _normalize_actions(cls, value: object) -> object:
        if isinstance(value, list):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value


class ApprovalControlRequest(_StrictControlRequest):
    kind: Literal["approval"]
    action: _Action
    resources: tuple[_Identifier, ...] = Field(min_length=1, max_length=128)
    reason: _BoundedText

    @field_validator("action", mode="before")
    @classmethod
    def _normalize_action(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


ControlRequest = Annotated[
    DelegationControlRequest | ApprovalControlRequest,
    Field(discriminator="kind"),
]
_CONTROL_REQUEST_ADAPTER = TypeAdapter(ControlRequest)
_CONTROL_DISCRIMINATOR_PATTERN = re.compile(
    r'"kind"\s*:\s*"(?:approval|delegation)"'
)


def is_control_request_candidate(raw: str) -> bool:
    return _CONTROL_DISCRIMINATOR_PATTERN.search(raw) is not None


def parse_control_request(raw: str) -> ControlRequest:
    if len(raw.encode("utf-8")) > _MAX_RESPONSE_BYTES:
        raise ValueError("control response must not exceed 32 KiB")
    stripped = raw.strip()
    try:
        value = json.loads(stripped)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("control response must be exactly one JSON object") from error
    if not isinstance(value, dict):
        raise ValueError("control response must be exactly one JSON object")
    try:
        request = _CONTROL_REQUEST_ADAPTER.validate_python(value)
    except ValueError as error:
        raise ValueError("invalid control request") from error
    if isinstance(request, ApprovalControlRequest) and request.action not in ACTION_LEVELS:
        raise ValueError("unknown control action")
    return request

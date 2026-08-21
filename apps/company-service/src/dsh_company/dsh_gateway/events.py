from collections.abc import Mapping
from dataclasses import dataclass

from deepseek_harness import Notification

from dsh_company.domain.ids import AttemptId

type ProjectedValue = str | int | dict[str, int]

_DIAGNOSTIC_CODES = frozenset(
    {
        "cancel_unconfirmed",
        "gateway_error",
        "id_collision",
        "runtime_process_lost",
    }
)
_USAGE_KEYS = frozenset(
    {
        "cacheReadTokens",
        "cacheWriteTokens",
        "inputTokens",
        "outputTokens",
        "reasoningTokens",
    }
)


@dataclass(frozen=True, slots=True)
class ProjectedDshEvent:
    attempt_id: AttemptId
    source_sequence: int
    details: dict[str, ProjectedValue]

    @property
    def event_type(self) -> str:
        value = self.details.get("event_type")
        if isinstance(value, str):
            return value
        method = self.details["method"]
        assert isinstance(method, str)
        return method


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _event_data(event: Mapping[str, object]) -> Mapping[str, object]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def _finish_reason(data: Mapping[str, object]) -> str | None:
    direct = _string(data.get("finishReason")) or _string(data.get("finish_reason"))
    if direct is not None:
        return direct
    reason = data.get("reason")
    return _string(reason.get("kind")) if isinstance(reason, dict) else None


def _usage(data: Mapping[str, object]) -> dict[str, int]:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return {}
    return {
        key: value
        for key, value in usage.items()
        if key in _USAGE_KEYS and isinstance(value, int) and not isinstance(value, bool)
    }


def _diagnostic_code(data: Mapping[str, object]) -> str | None:
    value = _string(data.get("diagnosticCode")) or _string(data.get("diagnostic_code"))
    return value if value in _DIAGNOSTIC_CODES else None


def project_notification(
    attempt_id: AttemptId, source_sequence: int, notification: Notification
) -> ProjectedDshEvent:
    details: dict[str, ProjectedValue] = {"method": notification.method}
    event_value = notification.payload.get("event")
    event = event_value if isinstance(event_value, dict) else {}
    event_type = _string(event.get("type"))
    data = _event_data(event)

    if event_type is not None:
        details["event_type"] = event_type
    tool_name = _string(data.get("toolName")) or _string(data.get("tool_name"))
    if tool_name is not None:
        details["tool_name"] = tool_name
    finish_reason = _finish_reason(data)
    if finish_reason is not None:
        details["finish_reason"] = finish_reason
    usage = _usage(data)
    if usage:
        details["usage"] = usage
    diagnostic_code = _diagnostic_code(data)
    if diagnostic_code is not None:
        details["diagnostic_code"] = diagnostic_code

    return ProjectedDshEvent(
        attempt_id=attempt_id,
        source_sequence=source_sequence,
        details=details,
    )

from deepseek_harness import Notification
from dsh_company.domain.ids import AttemptId
from dsh_company.dsh_gateway.events import project_notification


def test_event_projection_never_copies_content_or_arguments() -> None:
    notification = Notification(
        method="session.event",
        payload={
            "sessionId": "employee-emp-1",
            "prompt": "secret-value",
            "event": {
                "type": "tool/end",
                "data": {
                    "toolName": "web",
                    "arguments": {"query": "secret-value"},
                    "content": "secret-value",
                },
            },
        },
    )

    projected = project_notification(AttemptId("attempt-1"), 7, notification)

    assert projected.source_sequence == 7
    assert projected.details == {
        "method": "session.event",
        "event_type": "tool/end",
        "tool_name": "web",
    }
    assert "prompt" not in repr(projected)
    assert "secret-value" not in repr(projected)


def test_event_projection_keeps_only_integer_usage_and_closed_diagnostic() -> None:
    notification = Notification(
        method="session.event",
        payload={
            "event": {
                "type": "turn/end",
                "data": {
                    "finishReason": "completed",
                    "usage": {
                        "inputTokens": 12,
                        "outputTokens": 4,
                        "secret-value": 99,
                        "cost": 0.25,
                        "provider": "secret-provider-detail",
                    },
                    "diagnosticCode": "id_collision",
                    "message": "secret-value",
                },
            }
        },
    )

    projected = project_notification(AttemptId("attempt-1"), 1, notification)

    assert projected.details == {
        "method": "session.event",
        "event_type": "turn/end",
        "finish_reason": "completed",
        "usage": {"inputTokens": 12, "outputTokens": 4},
        "diagnostic_code": "id_collision",
    }
    assert "secret" not in repr(projected)


def test_event_projection_drops_unknown_diagnostic_and_boolean_usage() -> None:
    notification = Notification(
        method="session.event",
        payload={
            "event": {
                "type": "turn/end",
                "data": {
                    "usage": {"inputTokens": True},
                    "diagnosticCode": "raw-provider-error",
                },
            }
        },
    )

    projected = project_notification(AttemptId("attempt-1"), 1, notification)

    assert projected.details == {
        "method": "session.event",
        "event_type": "turn/end",
    }

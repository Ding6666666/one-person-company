import inspect

from deepseek_harness import DeepSeekHarness, RunResult, Session


def test_current_public_sdk_exposes_the_session_boundary_we_use() -> None:
    assert "session_id" in inspect.signature(DeepSeekHarness.start_session).parameters
    assert "session_id" in inspect.signature(DeepSeekHarness.run).parameters
    assert "on_notification" in inspect.signature(Session.run).parameters
    assert set(RunResult.__dataclass_fields__) >= {
        "session_id",
        "final_response",
        "finish_reason",
        "events",
        "notifications",
    }

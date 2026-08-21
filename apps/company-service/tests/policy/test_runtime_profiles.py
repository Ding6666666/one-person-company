import pytest
from dsh_company.policy.runtime_profiles import (
    RUNTIME_PROFILE_ACTIONS,
    actions_for_runtime_profile,
)


def test_runtime_profile_actions_are_exact_and_publish_is_never_exposed() -> None:
    baseline = frozenset(
        {
            "conversation.respond",
            "workspace.read",
            "session.history.read",
            "work.delegate",
        }
    )
    assert RUNTIME_PROFILE_ACTIONS == {
        "workspace_read": baseline,
        "workspace_write": baseline
        | frozenset({"workspace.write", "tool.shell", "tool.network"}),
        "network_denied": baseline,
    }
    assert all(
        "external.publish" not in actions for actions in RUNTIME_PROFILE_ACTIONS.values()
    )


def test_workspace_write_is_network_capable() -> None:
    actions = actions_for_runtime_profile("workspace_write")

    assert "tool.shell" in actions
    assert "tool.network" in actions


def test_network_denied_is_a_hard_cap() -> None:
    actions = actions_for_runtime_profile("network_denied")

    assert "workspace.write" not in actions
    assert "tool.shell" not in actions
    assert "tool.network" not in actions


def test_unknown_runtime_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown runtime profile"):
        actions_for_runtime_profile("unrestricted")

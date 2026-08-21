RUNTIME_PROFILE_ACTIONS: dict[str, frozenset[str]] = {
    "workspace_read": frozenset(
        {
            "conversation.respond",
            "workspace.read",
            "session.history.read",
            "work.delegate",
        }
    ),
    "workspace_write": frozenset(
        {
            "conversation.respond",
            "workspace.read",
            "session.history.read",
            "work.delegate",
            "workspace.write",
            "tool.shell",
            "tool.network",
        }
    ),
    "network_denied": frozenset(
        {
            "conversation.respond",
            "workspace.read",
            "session.history.read",
            "work.delegate",
        }
    ),
}


def actions_for_runtime_profile(profile: str) -> frozenset[str]:
    try:
        return RUNTIME_PROFILE_ACTIONS[profile]
    except KeyError as error:
        raise ValueError(f"unknown runtime profile: {profile}") from error

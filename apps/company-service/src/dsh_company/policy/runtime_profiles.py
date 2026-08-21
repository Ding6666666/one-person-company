from dsh_company.domain.policy import ACTION_LEVELS, ActionCatalog, ActionDefinition

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


def core_action_catalog() -> ActionCatalog:
    return ActionCatalog(
        ActionDefinition(
            action=action,
            level=level,
            runtime_profiles=frozenset(
                profile for profile, actions in RUNTIME_PROFILE_ACTIONS.items() if action in actions
            ),
        )
        for action, level in ACTION_LEVELS.items()
    )


def actions_for_runtime_profile(profile: str) -> frozenset[str]:
    try:
        return RUNTIME_PROFILE_ACTIONS[profile]
    except KeyError as error:
        raise ValueError(f"unknown runtime profile: {profile}") from error

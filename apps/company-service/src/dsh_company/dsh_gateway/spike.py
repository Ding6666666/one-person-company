from dsh_company.dsh_gateway.capability_report import (
    CapabilityObservation,
    CapabilityState,
    DshCapabilityReport,
)

_DSH_REVISION = "2db6ebd58523d14dca278e366ea0eb40499702b9"


def build_capability_report() -> DshCapabilityReport:
    """Return the public DSH capabilities verified by the Phase 1 spike."""
    return DshCapabilityReport(
        dsh_revision=_DSH_REVISION,
        observations=(
            CapabilityObservation(
                capability="session.create",
                state=CapabilityState.SUPPORTED,
                evidence="The public Python SDK returned the requested Session ID.",
            ),
            CapabilityObservation(
                capability="session.resume",
                state=CapabilityState.NOT_EXPOSED,
                evidence=(
                    "The public Python SDK and JSON-RPC expose no cold-resume entry point; "
                    "a new runtime using the same root and ID ended with an ID-collision "
                    "error before a second model request."
                ),
            ),
            CapabilityObservation(
                capability="session.events",
                state=CapabilityState.SUPPORTED,
                evidence="The public RunResult returned root events and notifications.",
            ),
            CapabilityObservation(
                capability="session.cancel",
                state=CapabilityState.CONSTRAINED,
                evidence="Only closing the Attempt-owned DeepSeekHarness is exposed.",
            ),
            CapabilityObservation(
                capability="attempt.observe",
                state=CapabilityState.NOT_EXPOSED,
                evidence="The public Python SDK exposes no Attempt observation method.",
            ),
            CapabilityObservation(
                capability="capability.list",
                state=CapabilityState.NOT_EXPOSED,
                evidence="The public Python SDK exposes no capability discovery method.",
            ),
            CapabilityObservation(
                capability="memory.provider",
                state=CapabilityState.NOT_EXPOSED,
                evidence=(
                    "The public Python SDK exposes no independent Memory Provider API; "
                    "only live-runtime Session context is currently usable."
                ),
            ),
            CapabilityObservation(
                capability="identity.agent",
                state=CapabilityState.CONSTRAINED,
                evidence=(
                    "The AgentRegistry contract equates Agent ID with Session ID, while "
                    "the public Python SDK exposes only Session ID."
                ),
            ),
        ),
    )

from dsh_company.dsh_gateway.capability_report import (
    CapabilityObservation,
    CapabilityState,
    DshCapabilityReport,
)
from dsh_company.dsh_gateway.spike import build_capability_report


def test_capability_report_is_closed_and_serializable() -> None:
    report = DshCapabilityReport(
        dsh_revision="2db6ebd58523d14dca278e366ea0eb40499702b9",
        observations=(
            CapabilityObservation(
                capability="session.create",
                state=CapabilityState.SUPPORTED,
                evidence="public SDK returned the requested session id",
            ),
        ),
    )

    assert report.model_dump(mode="json")["observations"][0]["state"] == "supported"


def test_report_contains_every_gateway_decision() -> None:
    report = build_capability_report()
    observations = report.by_name()

    assert observations["session.create"].state is CapabilityState.SUPPORTED
    assert observations["session.resume"].state is CapabilityState.NOT_EXPOSED
    assert observations["session.events"].state is CapabilityState.SUPPORTED
    assert observations["session.cancel"].state is CapabilityState.CONSTRAINED
    assert observations["attempt.observe"].state is CapabilityState.NOT_EXPOSED
    assert observations["capability.list"].state is CapabilityState.NOT_EXPOSED
    assert observations["memory.provider"].state is CapabilityState.NOT_EXPOSED
    assert observations["identity.agent"].state is CapabilityState.CONSTRAINED

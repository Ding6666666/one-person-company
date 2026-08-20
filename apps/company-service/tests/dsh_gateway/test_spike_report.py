from dsh_company.dsh_gateway.capability_report import (
    CapabilityObservation,
    CapabilityState,
    DshCapabilityReport,
)


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

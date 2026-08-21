from datetime import UTC

import pytest
from dsh_company.domain.approval import Approval, ApprovalStatus
from dsh_company.domain.ids import (
    ApprovalId,
    EmployeeId,
    EmployeeRevisionId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.work import Work, WorkNodeStatus


def test_approval_can_be_decided_once() -> None:
    approval = Approval.request(
        approval_id=ApprovalId("approval-1"),
        workspace_id=WorkspaceId("ws-1"),
        work_id=WorkId("work-1"),
        node_id=WorkNodeId("node-1"),
        action="external.publish",
        resources=("channel-a",),
        reason="发布到外部渠道",
    )

    approved = approval.approve(decided_by="user")

    assert approved.status is ApprovalStatus.APPROVED
    assert approved.requested_at.tzinfo is UTC
    assert approved.decided_at is not None
    assert approved.decided_at.tzinfo is UTC
    assert approved.decided_by == "user"
    with pytest.raises(ValueError, match="already decided"):
        approved.reject(decided_by="user")


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_waiting_approval_has_only_closed_decision_transitions(decision: str) -> None:
    _, _, node = Work.create_direct(
        work_id=WorkId("work-1"),
        graph_id=WorkGraphRevisionId("graph-1"),
        node_id=WorkNodeId("node-1"),
        workspace_id=WorkspaceId("ws-1"),
        employee_id=EmployeeId("emp-1"),
        employee_revision_id=EmployeeRevisionId("revision-1"),
        objective="发布公告",
        acceptance_criteria=("内容准确",),
        command_id="command-1",
    )
    waiting = node.wait_for_approval()

    if decision == "approved":
        decided = waiting.approval_approved()
        assert decided.status is WorkNodeStatus.READY
        assert decided.failure_code is None
    else:
        decided = waiting.approval_rejected()
        assert decided.status is WorkNodeStatus.FAILED
        assert decided.failure_code == "approval_rejected"

    with pytest.raises(ValueError, match="WAITING_APPROVAL"):
        decided.approval_approved()

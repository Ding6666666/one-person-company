from dataclasses import FrozenInstanceError

import pytest
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    EmployeeId,
    EmployeeRevisionId,
    ExecutionLinkId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.work import (
    ExecutionLink,
    ExecutionStatus,
    Work,
    WorkGraphRevision,
    WorkNode,
    WorkNodeStatus,
    WorkStatus,
    WorkStrategy,
)


def direct_work() -> tuple[Work, WorkGraphRevision, WorkNode]:
    return Work.create_direct(
        work_id=WorkId("work-1"),
        graph_id=WorkGraphRevisionId("graph-1"),
        node_id=WorkNodeId("node-1"),
        workspace_id=WorkspaceId("ws-1"),
        employee_id=EmployeeId("emp-1"),
        employee_revision_id=EmployeeRevisionId("rev-1"),
        objective="  撰写发布稿  ",
        acceptance_criteria=("包含标题", "  ", " 不超过 800 字 "),
        command_id="cmd-1",
    )


def ready_node() -> WorkNode:
    return direct_work()[2]


def running_link() -> ExecutionLink:
    return ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("link-1"),
        attempt_id=AttemptId("attempt-1"),
        node_id=WorkNodeId("node-1"),
        command_id="cmd-1",
        dsh_session_id="employee-emp-1",
    ).mark_running()


def test_direct_work_creates_one_frozen_node() -> None:
    work, graph, node = direct_work()

    assert work.status is WorkStatus.QUEUED
    assert work.objective == "撰写发布稿"
    assert work.current_graph_revision_id == graph.id
    assert graph.strategy is WorkStrategy.DIRECT
    assert graph.revision_number == 1
    assert graph.node_ids == (node.id,)
    assert graph.edges == ()
    assert node.status is WorkNodeStatus.READY
    assert node.acceptance_criteria == ("包含标题", "不超过 800 字")
    assert node.employee_revision_id == EmployeeRevisionId("rev-1")
    with pytest.raises(FrozenInstanceError):
        node.status = WorkNodeStatus.RUNNING  # type: ignore[misc]


@pytest.mark.parametrize(
    ("objective", "criteria", "message"),
    [
        ("   ", ("包含标题",), "objective"),
        ("撰写发布稿", (" ", ""), "acceptance criterion"),
    ],
)
def test_direct_work_rejects_blank_required_text(
    objective: str, criteria: tuple[str, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Work.create_direct(
            work_id=WorkId("work-1"),
            graph_id=WorkGraphRevisionId("graph-1"),
            node_id=WorkNodeId("node-1"),
            workspace_id=WorkspaceId("ws-1"),
            employee_id=EmployeeId("emp-1"),
            employee_revision_id=EmployeeRevisionId("rev-1"),
            objective=objective,
            acceptance_criteria=criteria,
            command_id="cmd-1",
        )


def test_direct_work_requires_and_normalizes_command_id() -> None:
    with pytest.raises(ValueError, match="command ID"):
        Work.create_direct(
            work_id=WorkId("work-1"),
            graph_id=WorkGraphRevisionId("graph-1"),
            node_id=WorkNodeId("node-1"),
            workspace_id=WorkspaceId("ws-1"),
            employee_id=EmployeeId("emp-1"),
            employee_revision_id=EmployeeRevisionId("rev-1"),
            objective="撰写发布稿",
            acceptance_criteria=("包含标题",),
            command_id="   ",
        )

    work, _, _ = Work.create_direct(
        work_id=WorkId("work-1"),
        graph_id=WorkGraphRevisionId("graph-1"),
        node_id=WorkNodeId("node-1"),
        workspace_id=WorkspaceId("ws-1"),
        employee_id=EmployeeId("emp-1"),
        employee_revision_id=EmployeeRevisionId("rev-1"),
        objective="撰写发布稿",
        acceptance_criteria=("包含标题",),
        command_id="  cmd-1  ",
    )

    assert work.command_id == "cmd-1"


def test_node_completion_requires_matching_attempt_and_result_reference() -> None:
    node = ready_node().start(AttemptId("attempt-1"))

    with pytest.raises(ValueError, match="attempt"):
        node.complete(AttemptId("attempt-2"), ArtifactReferenceId("artifact-1"))
    with pytest.raises(ValueError, match="result reference"):
        node.complete(AttemptId("attempt-1"), None)

    completed = node.complete(AttemptId("attempt-1"), ArtifactReferenceId("artifact-1"))
    assert completed.status is WorkNodeStatus.COMPLETED
    assert completed.output_references == (ArtifactReferenceId("artifact-1"),)
    assert node.status is WorkNodeStatus.RUNNING


def test_node_transitions_reject_invalid_source_states() -> None:
    node = ready_node()

    with pytest.raises(ValueError, match="READY"):
        node.complete(AttemptId("attempt-1"), ArtifactReferenceId("artifact-1"))
    running = node.start(AttemptId("attempt-1"))
    with pytest.raises(ValueError, match="RUNNING"):
        running.start(AttemptId("attempt-2"))
    with pytest.raises(ValueError, match="attempt"):
        running.fail(AttemptId("attempt-2"), "gateway_error")

    failed = running.fail(AttemptId("attempt-1"), "gateway_error")
    assert failed.status is WorkNodeStatus.FAILED
    assert failed.failure_code == "gateway_error"


def test_work_transitions_are_closed_and_immutable() -> None:
    work = direct_work()[0]

    running = work.start()
    assert running.status is WorkStatus.RUNNING
    assert work.status is WorkStatus.QUEUED
    assert running.complete().status is WorkStatus.COMPLETED
    assert running.block().status is WorkStatus.BLOCKED
    assert running.fail().status is WorkStatus.FAILED
    assert running.cancel().status is WorkStatus.CANCELLED
    with pytest.raises(ValueError, match="QUEUED"):
        work.complete()


def test_execution_link_distinguishes_cancel_request_and_confirmation() -> None:
    link = running_link()

    requested = link.request_cancel()
    confirmed = requested.confirm_cancelled()

    assert requested.status is ExecutionStatus.CANCEL_REQUESTED
    assert confirmed.status is ExecutionStatus.CANCELLED
    assert requested.finished_at is None
    assert confirmed.finished_at is not None


def test_pending_cancel_request_can_be_blocked_without_starting_attempt() -> None:
    work, _graph, node = direct_work()
    link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("link-1"),
        attempt_id=AttemptId("attempt-1"),
        node_id=node.id,
        command_id="cmd-1",
        dsh_session_id="employee-emp-1",
    )

    requested = link.request_cancel()
    blocked_link = requested.block(link.attempt_id, "cancel_unconfirmed")
    blocked_node = node.block_before_start("cancel_unconfirmed")
    blocked_work = work.block_before_start()

    assert requested.status is ExecutionStatus.CANCEL_REQUESTED
    assert blocked_link.status is ExecutionStatus.BLOCKED
    assert blocked_node.status is WorkNodeStatus.BLOCKED
    assert blocked_node.active_attempt_id is None
    assert blocked_work.status is WorkStatus.BLOCKED


def test_execution_link_rejects_invalid_transition_and_attempt() -> None:
    pending = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("link-1"),
        attempt_id=AttemptId("attempt-1"),
        node_id=WorkNodeId("node-1"),
        command_id="cmd-1",
        dsh_session_id="employee-emp-1",
    )

    running = pending.mark_running()
    with pytest.raises(ValueError, match="attempt"):
        running.complete(AttemptId("attempt-2"), ArtifactReferenceId("artifact-1"))
    completed = running.complete(AttemptId("attempt-1"), ArtifactReferenceId("artifact-1"))
    assert completed.status is ExecutionStatus.COMPLETED
    assert completed.finished_at is not None

from dataclasses import replace
from datetime import UTC
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dsh_company.application.ports import WorkAggregate
from dsh_company.domain.approval import Approval, ApprovalStatus
from dsh_company.domain.capabilities import CapabilityGrant, CapabilityLevel
from dsh_company.domain.delegation import (
    DelegationProposal,
    DelegationRevision,
    apply_delegation,
)
from dsh_company.domain.employee import Employee
from dsh_company.domain.ids import (
    ApprovalId,
    CapabilityGrantId,
    DelegationId,
    EmployeeId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
    WorkspaceId,
)
from dsh_company.domain.work import Work, WorkEdgeKind, WorkNodeStatus
from dsh_company.domain.workspace import Workspace
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.governance_repositories import ConcurrentApprovalDecision
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork


def _seed_governed_work(
    uow: SqlAlchemyUnitOfWork,
) -> tuple[WorkAggregate, DelegationRevision]:
    workspace = Workspace.create(WorkspaceId("ws-1"), "Governed work")
    source_employee, source_revision, source_binding = Employee.create(
        employee_id=EmployeeId("emp-a"),
        workspace_id=workspace.id,
        display_name="Author",
        responsibility="Draft",
        runtime_profile="workspace_read",
        model="deepseek-v4-flash",
    )
    target_employee, target_revision, target_binding = Employee.create(
        employee_id=EmployeeId("emp-b"),
        workspace_id=workspace.id,
        display_name="Reviewer",
        responsibility="Review",
        runtime_profile="workspace_read",
        model="deepseek-v4-flash",
    )
    work, graph, node = Work.create_direct(
        work_id=WorkId("work-1"),
        graph_id=WorkGraphRevisionId("graph-1"),
        node_id=WorkNodeId("node-1"),
        workspace_id=workspace.id,
        employee_id=source_employee.id,
        employee_revision_id=source_revision.id,
        objective="Publish a release note",
        acceptance_criteria=("Accurate",),
        command_id="command-1",
    )
    completed_node = replace(node, status=WorkNodeStatus.COMPLETED)
    original = WorkAggregate(work, graph, (completed_node,), (), ())

    uow.workspaces.add(workspace)
    uow.employees.add(source_employee, source_revision, source_binding, ())
    uow.employees.add(target_employee, target_revision, target_binding, ())
    uow.works.add(original)

    revised, delegation = apply_delegation(
        graph,
        original.nodes,
        DelegationProposal(
            proposer_employee_id=source_employee.id,
            target_employee_id=target_employee.id,
            objective="Verify facts",
            acceptance_criteria=("Cite sources",),
            required_actions=("workspace.read",),
            resource_values=("ws-1",),
        ),
        workspace_id=workspace.id,
        source_node_id=completed_node.id,
        target_employee_revision_id=target_revision.id,
        ids=lambda prefix: {
            "work-graph": "graph-2",
            "work-node": "node-2",
            "delegation": "delegation-1",
        }[prefix],
    )
    uow.works.add_revision(revised.graph, revised.nodes)
    uow.delegations.add(delegation)
    approval = Approval.request(
        approval_id=ApprovalId("approval-1"),
        workspace_id=workspace.id,
        work_id=work.id,
        node_id=revised.nodes[-1].id,
        action="external.publish",
        resources=("channel-a",),
        reason="Publish to the external release channel",
    )
    uow.approvals.add(approval)
    return original, revised


def test_pending_approval_delegation_and_graph_revision_survive_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "company.db"
    engine = create_sqlite_engine(database_path)
    create_tables(engine)
    with SqlAlchemyUnitOfWork(engine) as uow:
        original, revised = _seed_governed_work(uow)
        uow.commit()
    engine.dispose()

    restarted_engine = create_sqlite_engine(database_path)
    with SqlAlchemyUnitOfWork(restarted_engine) as uow:
        approval = uow.approvals.get(ApprovalId("approval-1"))
        delegation = uow.delegations.get(DelegationId("delegation-1"))
        graph_1 = uow.works.get_revision(WorkGraphRevisionId("graph-1"))
        graph_2 = uow.works.get_revision(WorkGraphRevisionId("graph-2"))
    restarted_engine.dispose()

    assert approval is not None and approval.status is ApprovalStatus.PENDING
    assert approval.requested_at.tzinfo is UTC
    assert delegation is not None and delegation.status == "accepted"
    assert delegation.created_at.tzinfo is UTC
    assert graph_1 is not None
    assert graph_2 is not None
    assert graph_1 == (original.graph, original.nodes)
    assert graph_2 == (revised.graph, revised.nodes)
    assert graph_2[0].node_ids == (WorkNodeId("node-1"), WorkNodeId("node-2"))
    assert graph_2[0].edges[-1].kind is WorkEdgeKind.DELEGATES_TO
    assert graph_2[1][0] == original.nodes[0]


def test_workspace_and_node_capability_grants_round_trip(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "company.db")
    create_tables(engine)
    workspace_grant = CapabilityGrant(
        id=CapabilityGrantId("workspace-grant"),
        employee_revision_id=None,
        action="external.publish",
        level=CapabilityLevel.L3,
        resource_kind="channel",
        resource_values=("release", "status"),
        requires_approval=True,
    )
    node_grant = replace(
        workspace_grant,
        id=CapabilityGrantId("node-grant"),
        action="workspace.read",
        level=CapabilityLevel.L1,
        resource_kind="workspace",
        resource_values=("ws-1",),
        requires_approval=False,
    )
    with SqlAlchemyUnitOfWork(engine) as uow:
        _seed_governed_work(uow)
        uow.workspace_grants.replace(WorkspaceId("ws-1"), (workspace_grant,))
        uow.node_grants.replace(WorkNodeId("node-2"), (node_grant,))
        uow.commit()

    with SqlAlchemyUnitOfWork(engine) as uow:
        stored_workspace_grants = uow.workspace_grants.list_for_workspace(WorkspaceId("ws-1"))
        stored_node_grants = uow.node_grants.list_for_node(WorkNodeId("node-2"))
    engine.dispose()

    assert [replace(item, id=workspace_grant.id) for item in stored_workspace_grants] == [
        workspace_grant
    ]
    assert [replace(item, id=node_grant.id) for item in stored_node_grants] == [node_grant]
    assert isinstance(stored_workspace_grants[0].resource_values, tuple)


def test_approval_decision_is_optimistic_and_reason_is_bounded(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "company.db")
    create_tables(engine)
    with SqlAlchemyUnitOfWork(engine) as uow:
        _seed_governed_work(uow)
        uow.commit()

    with SqlAlchemyUnitOfWork(engine) as uow:
        pending = uow.approvals.get(ApprovalId("approval-1"))
    assert pending is not None
    approved = pending.approve(decided_by="operator")
    rejected = pending.reject(decided_by="other-operator")

    with SqlAlchemyUnitOfWork(engine) as uow:
        uow.approvals.decide(approved)
        uow.commit()
    with pytest.raises(ConcurrentApprovalDecision):
        with SqlAlchemyUnitOfWork(engine) as uow:
            uow.approvals.decide(rejected)

    too_long = replace(
        pending,
        id=ApprovalId("approval-long"),
        reason="x" * 501,
    )
    with pytest.raises(ValueError, match="500"):
        with SqlAlchemyUnitOfWork(engine) as uow:
            uow.approvals.add(too_long)
    engine.dispose()


def test_governance_schema_has_no_raw_model_output_columns(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "company.db")
    create_tables(engine)
    with engine.connect() as connection:
        columns = {
            row[1]
            for table in ("approvals", "delegations", "work_edges")
            for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
        }
    engine.dispose()

    assert columns.isdisjoint({"prompt", "transcript", "tool_args", "final_response"})


def test_migration_backfills_membership_for_existing_direct_graph(tmp_path: Path) -> None:
    database_path = tmp_path / "company.db"
    config = Config("apps/company-service/alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(config, "0002_direct_work")
    engine = create_sqlite_engine(database_path)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO workspaces VALUES ('ws-1', 'Existing', '2026-08-21 00:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO employees VALUES "
            "('emp-1', 'ws-1', 'Existing', 'active', 'revision-1', "
            "'2026-08-21 00:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO employee_revisions VALUES "
            "('revision-1', 'emp-1', 1, 'Existing', 'workspace_read', 'model', "
            "'2026-08-21 00:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO works VALUES "
            "('work-1', 'ws-1', 'command-1', 'Existing work', 'queued', 'graph-1', "
            "'2026-08-21 00:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO work_graph_revisions VALUES "
            "('graph-1', 'work-1', 1, 'direct', '2026-08-21 00:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO work_nodes VALUES "
            "('node-1', 'graph-1', 'work-1', 'Existing work', '[\"Accurate\"]', "
            "'emp-1', 'revision-1', 'ready', NULL, NULL, 1)"
        )
    engine.dispose()

    command.upgrade(config, "head")
    restarted_engine = create_sqlite_engine(database_path)
    with SqlAlchemyUnitOfWork(restarted_engine) as uow:
        stored = uow.works.get_revision(WorkGraphRevisionId("graph-1"))
    restarted_engine.dispose()

    assert stored is not None
    assert stored[0].node_ids == (WorkNodeId("node-1"),)
    assert stored[1][0].objective == "Existing work"

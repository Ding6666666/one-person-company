import logging

from dsh_company.application.governance_service import GovernanceService
from dsh_company.domain.delegation import DelegationProposal
from dsh_company.domain.ids import (
    ApprovalId,
    ArtifactReferenceId,
    DelegationId,
    EmployeeId,
    WorkNodeId,
    new_id,
)
from dsh_company.domain.policy import PolicyEngine
from dsh_company.domain.work import ExecutionStatus, WorkNodeStatus
from dsh_company.dsh_gateway.control_requests import (
    ApprovalControlRequest,
    ControlRequest,
    DelegationControlRequest,
)

from .delegation_service import (
    DelegationCommand,
    DelegationDenied,
    DelegationService,
)
from .ports import GovernanceUnitOfWorkFactory, IdFactory
from .runtime_coordinator import RuntimeControlDenied

_LOGGER = logging.getLogger(__name__)


class RuntimeGovernanceHandler:
    def __init__(
        self,
        uow_factory: GovernanceUnitOfWorkFactory,
        policy_engine: PolicyEngine,
        *,
        ids: IdFactory = new_id,
    ) -> None:
        self._uow_factory = uow_factory
        self._policy_engine = policy_engine
        self._ids = ids

    def reconcile_startup(self) -> None:
        with self._uow_factory() as uow:
            approval_ids = tuple(item.id for item in uow.approvals.list_approved())
            delegation_ids = tuple(item.id for item in uow.delegations.list_accepted())
        for approval_id in approval_ids:
            try:
                self._reconcile_approval(approval_id)
            except Exception:
                _LOGGER.exception(
                    "Approved Company action could not be reconciled",
                    extra={"approval_id": str(approval_id)},
                )
        for delegation_id in delegation_ids:
            try:
                self._reconcile_delegation(delegation_id)
            except Exception:
                _LOGGER.exception(
                    "Accepted Company delegation could not be reconciled",
                    extra={"delegation_id": str(delegation_id)},
                )

    def _reconcile_approval(self, approval_id: ApprovalId) -> None:
        with self._uow_factory() as uow:
            approval = uow.approvals.get(approval_id)
            if approval is None:
                return
            aggregate = uow.works.get_for_node(approval.node_id)
            if aggregate is None:
                return
            node = next(
                (item for item in aggregate.nodes if item.id == approval.node_id),
                None,
            )
            if node is None or node.status is not WorkNodeStatus.WAITING_APPROVAL:
                return
        GovernanceService(
            self._uow_factory(), self._policy_engine, ids=self._ids
        ).resume_approved(approval_id)

    def _reconcile_delegation(self, delegation_id: DelegationId) -> None:
        artifact_reference_id: ArtifactReferenceId | None = None
        with self._uow_factory() as uow:
            delegation = uow.delegations.get(delegation_id)
            if delegation is None or delegation.target_node_id is None:
                return
            aggregate = uow.works.get(delegation.work_id)
            if aggregate is None:
                return
            parent = next(
                (item for item in aggregate.nodes if item.id == delegation.source_node_id),
                None,
            )
            child = next(
                (item for item in aggregate.nodes if item.id == delegation.target_node_id),
                None,
            )
            if (
                parent is None
                or child is None
                or parent.status is not WorkNodeStatus.BLOCKED
                or parent.failure_code != "waiting_delegation"
                or child.status is not WorkNodeStatus.COMPLETED
            ):
                return
            child_attempt_ids = {
                link.attempt_id
                for link in aggregate.execution_links
                if link.node_id == child.id and link.status is ExecutionStatus.COMPLETED
            }
            artifact_ids = tuple(
                artifact.id
                for artifact in aggregate.artifacts
                if artifact.source_attempt_id in child_attempt_ids
            )
            if len(artifact_ids) != 1:
                return
            artifact_reference_id = artifact_ids[0]
        DelegationService(
            self._uow_factory(), self._policy_engine, ids=self._ids
        ).child_completed(delegation_id, artifact_reference_id)

    def handle(
        self, source_node_id: WorkNodeId, request: ControlRequest
    ) -> tuple[WorkNodeId, ...]:
        if isinstance(request, ApprovalControlRequest):
            raise RuntimeControlDenied("approval_control_not_exposed")
        if not isinstance(request, DelegationControlRequest):
            raise RuntimeControlDenied("control_request_unhandled")
        with self._uow_factory() as uow:
            aggregate = uow.works.get_for_node(source_node_id)
            if aggregate is None:
                raise LookupError(f"work node not found: {source_node_id}")
            matches = tuple(node for node in aggregate.nodes if node.id == source_node_id)
            if len(matches) != 1:
                raise LookupError(f"work node not found: {source_node_id}")
            proposer_employee_id = matches[0].assigned_employee_id
        service = DelegationService(
            self._uow_factory(),
            self._policy_engine,
            ids=self._ids,
        )
        try:
            result = service.propose(
                DelegationCommand(
                    source_node_id=source_node_id,
                    proposal=DelegationProposal(
                        proposer_employee_id=proposer_employee_id,
                        target_employee_id=EmployeeId(request.target_employee_id),
                        objective=request.objective,
                        acceptance_criteria=request.acceptance_criteria,
                        required_actions=request.required_actions,
                        resource_values=request.resource_values,
                    ),
                )
            )
        except DelegationDenied:
            raise RuntimeControlDenied("delegation_rejected") from None
        return (result.target_node.id,)

    def child_completed(
        self,
        target_node_id: WorkNodeId,
        artifact_reference_id: ArtifactReferenceId,
    ) -> tuple[WorkNodeId, ...]:
        service = DelegationService(
            self._uow_factory(),
            self._policy_engine,
            ids=self._ids,
        )
        result = service.child_completed_for_node(
            target_node_id, artifact_reference_id
        )
        return () if result is None else (result.parent_node.id,)

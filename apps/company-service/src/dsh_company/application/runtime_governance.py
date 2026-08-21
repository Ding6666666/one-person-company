from dsh_company.domain.delegation import DelegationProposal
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    EmployeeId,
    WorkNodeId,
    new_id,
)
from dsh_company.domain.policy import PolicyEngine
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

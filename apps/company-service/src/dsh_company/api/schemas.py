from datetime import datetime
from typing import Annotated, Literal, cast

from pydantic import BaseModel, Field, StringConstraints, model_validator

from dsh_company.application.ports import EmployeeRecord, WorkAggregate
from dsh_company.domain.work import (
    CompanyEvent as DomainCompanyEvent,
)
from dsh_company.domain.work import (
    ExecutionStatus,
    WorkEdgeKind,
    WorkNodeStatus,
    WorkStatus,
    WorkStrategy,
)
from dsh_company.domain.workspace import Workspace as DomainWorkspace

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Responsibility = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Action = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ResourceKind = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
BoundedResource = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
OperatorName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
DelegatedObjective = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
DelegatedCriterion = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class WorkspaceCreate(BaseModel):
    name: Name


class GrantCreate(BaseModel):
    action: Action
    level: Literal[0, 1, 2, 3]
    resource_kind: ResourceKind
    resource_values: list[BoundedResource] = Field(min_length=1)
    requires_approval: bool


class WorkspaceCapabilitiesUpdate(BaseModel):
    grants: list[GrantCreate] = Field(max_length=8)


class WorkspaceGrant(BaseModel):
    action: str
    level: Literal[0, 1, 2, 3]
    resource_kind: str
    resource_values: list[str]
    requires_approval: bool


class WorkspaceCapabilities(BaseModel):
    workspace_id: str
    grants: list[WorkspaceGrant]


class EmployeeSummary(BaseModel):
    id: str
    display_name: str


class ApprovalProjection(BaseModel):
    id: str
    workspace_id: str
    work_id: str
    node_id: str
    action: str
    resources: list[str]
    reason: str
    status: Literal["pending", "approved", "rejected", "cancelled"]
    requested_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    requesting_employee: EmployeeSummary


class ApprovalDecision(BaseModel):
    decided_by: OperatorName


class ApprovalDecisionProjection(BaseModel):
    approval: ApprovalProjection
    work: "WorkProjection"


class DelegationCreate(BaseModel):
    source_node_id: NonBlank
    proposer_employee_id: NonBlank
    target_employee_id: NonBlank
    objective: DelegatedObjective
    acceptance_criteria: list[DelegatedCriterion] = Field(min_length=1, max_length=50)
    required_actions: list[Action] = Field(min_length=1, max_length=8)
    resource_values: list[BoundedResource] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_actions(self) -> "DelegationCreate":
        if len(self.required_actions) != len(set(self.required_actions)):
            raise ValueError("delegation actions must be unique")
        return self


class DelegationProjection(BaseModel):
    id: str
    workspace_id: str
    work_id: str
    source_node_id: str
    target_node_id: str | None
    proposer_employee_id: str
    target_employee_id: str
    graph_revision_id: str
    status: Literal["proposed", "accepted", "rejected", "completed"]
    created_at: datetime


class DelegationResultProjection(BaseModel):
    delegation: DelegationProjection
    work: "WorkProjection"


class DelegationCollection(BaseModel):
    delegations: list[DelegationProjection]
    eligible_employees: list[EmployeeSummary]


class EmployeeCreate(BaseModel):
    display_name: Name
    responsibility: Responsibility
    runtime_profile: Literal["workspace_read", "workspace_write", "network_denied"]
    model: ModelName
    grants: list[GrantCreate] = Field(default_factory=list)


class EmployeeRevise(BaseModel):
    responsibility: Responsibility
    runtime_profile: Literal["workspace_read", "workspace_write", "network_denied"]
    model: ModelName
    grants: list[GrantCreate] = Field(default_factory=list)


class Workspace(BaseModel):
    id: str
    name: str
    created_at: datetime

    @classmethod
    def from_domain(cls, workspace: DomainWorkspace) -> "Workspace":
        return cls(id=workspace.id, name=workspace.name, created_at=workspace.created_at)


class Grant(BaseModel):
    id: str
    employee_revision_id: str | None
    action: str
    level: Literal[0, 1, 2, 3]
    resource_kind: str
    resource_values: list[str]
    requires_approval: bool


class EmployeeRevision(BaseModel):
    id: str
    employee_id: str
    revision_number: int
    responsibility: str
    runtime_profile: str
    model: str
    created_at: datetime


class EmployeeBinding(BaseModel):
    id: str
    employee_id: str
    dsh_agent_id: str
    dsh_session_id: str
    memory_scope_id: str
    created_at: datetime


class Employee(BaseModel):
    id: str
    workspace_id: str
    display_name: str
    status: Literal["active", "paused", "archived"]
    current_revision_id: str
    created_at: datetime
    revision: EmployeeRevision
    binding: EmployeeBinding
    grants: list[Grant]

    @classmethod
    def from_record(cls, record: EmployeeRecord) -> "Employee":
        employee = record.employee
        revision = record.revision
        binding = record.binding
        return cls(
            id=employee.id,
            workspace_id=employee.workspace_id,
            display_name=employee.display_name,
            status=cast(Literal["active", "paused", "archived"], employee.status.value),
            current_revision_id=employee.current_revision_id,
            created_at=employee.created_at,
            revision=EmployeeRevision(
                id=revision.id,
                employee_id=revision.employee_id,
                revision_number=revision.revision_number,
                responsibility=revision.responsibility,
                runtime_profile=revision.runtime_profile,
                model=revision.model,
                created_at=revision.created_at,
            ),
            binding=EmployeeBinding(
                id=binding.id,
                employee_id=binding.employee_id,
                dsh_agent_id=binding.dsh_agent_id,
                dsh_session_id=binding.dsh_session_id,
                memory_scope_id=binding.memory_scope_id,
                created_at=binding.created_at,
            ),
            grants=[
                Grant(
                    id=grant.id,
                    employee_revision_id=grant.employee_revision_id,
                    action=grant.action,
                    level=cast(Literal[0, 1, 2, 3], int(grant.level)),
                    resource_kind=grant.resource_kind,
                    resource_values=list(grant.resource_values),
                    requires_approval=grant.requires_approval,
                )
                for grant in record.grants
            ],
        )


class DirectWorkCreate(BaseModel):
    model_config = {"extra": "forbid"}

    employee_id: NonBlank
    objective: NonBlank
    acceptance_criteria: list[NonBlank] = Field(min_length=1)
    command_id: NonBlank


WorkObjective = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
WorkCriterion = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
NodeKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class StrategyWorkBase(BaseModel):
    model_config = {"extra": "forbid"}

    objective: WorkObjective
    acceptance_criteria: list[WorkCriterion] = Field(min_length=1, max_length=50)
    command_id: NonBlank


class DirectStrategyInput(StrategyWorkBase):
    kind: Literal["direct"]
    employee_id: NonBlank


class StarChildInput(BaseModel):
    model_config = {"extra": "forbid"}

    employee_id: NonBlank
    objective: WorkObjective
    acceptance_criteria: list[WorkCriterion] = Field(min_length=1, max_length=50)


class StarStrategyInput(StrategyWorkBase):
    kind: Literal["star"]
    coordinator_employee_id: NonBlank
    children: list[StarChildInput] = Field(min_length=1, max_length=16)


class GraphNodeInput(BaseModel):
    model_config = {"extra": "forbid"}

    key: NodeKey
    employee_id: NonBlank
    objective: WorkObjective
    acceptance_criteria: list[WorkCriterion] = Field(min_length=1, max_length=50)
    required_actions: list[Action] = Field(default_factory=list, max_length=8)
    resource_values: list[BoundedResource] = Field(default_factory=list, max_length=50)
    resource_kinds: list[ResourceKind] = Field(default_factory=list, max_length=8)
    max_attempts: int = Field(default=1, ge=1, le=10)

    @model_validator(mode="after")
    def validate_policy_inputs(self) -> "GraphNodeInput":
        if len(self.required_actions) != len(set(self.required_actions)):
            raise ValueError("required actions must be unique")
        if len(self.resource_kinds) != len(self.required_actions):
            raise ValueError("resource kinds must align with required actions")
        return self


class GraphEdgeInput(BaseModel):
    model_config = {"extra": "forbid"}

    from_key: NodeKey
    to_key: NodeKey
    kind: WorkEdgeKind


class GraphStrategyInput(StrategyWorkBase):
    kind: Literal["graph"]
    nodes: list[GraphNodeInput] = Field(min_length=1, max_length=32)
    edges: list[GraphEdgeInput] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_unique_graph_facts(self) -> "GraphStrategyInput":
        keys = [node.key for node in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("graph node keys must be unique")
        edge_keys = [(edge.from_key, edge.to_key, edge.kind) for edge in self.edges]
        if len(edge_keys) != len(set(edge_keys)):
            raise ValueError("graph edges must be unique")
        return self


class BattleStrategyInput(StrategyWorkBase):
    kind: Literal["battle"]
    participant_employee_ids: list[NonBlank] = Field(min_length=2, max_length=4)
    summarizer_employee_id: NonBlank

    @model_validator(mode="after")
    def validate_distinct_participants(self) -> "BattleStrategyInput":
        if len(self.participant_employee_ids) != len(set(self.participant_employee_ids)):
            raise ValueError("battle participants must be distinct")
        if self.summarizer_employee_id in self.participant_employee_ids:
            raise ValueError("battle summarizer must be distinct")
        return self


StrategyWorkCreate = Annotated[
    DirectStrategyInput | StarStrategyInput | GraphStrategyInput | BattleStrategyInput,
    Field(discriminator="kind"),
]


class WorkNode(BaseModel):
    id: str
    objective: str
    acceptance_criteria: list[str]
    assigned_employee_id: str
    employee_revision_id: str
    status: WorkNodeStatus
    active_attempt_id: str | None
    failure_code: str | None
    version: int
    attempt_count: int = 0
    max_attempts: int = 1


class WorkEdge(BaseModel):
    from_node_id: str
    to_node_id: str
    kind: WorkEdgeKind


class ExecutionLink(BaseModel):
    id: str
    node_id: str
    attempt_id: str
    status: ExecutionStatus
    started_at: datetime | None
    finished_at: datetime | None
    diagnostic_code: str | None


class ArtifactReference(BaseModel):
    id: str
    kind: Literal["dsh_session_result"]
    uri: str
    created_at: datetime


class WorkProjection(BaseModel):
    id: str
    workspace_id: str
    command_id: str
    objective: str
    status: WorkStatus
    graph_revision_id: str
    graph_revision_number: int
    strategy: WorkStrategy
    nodes: list[WorkNode]
    edges: list[WorkEdge] = Field(default_factory=list)
    execution_links: list[ExecutionLink]
    artifacts: list[ArtifactReference]
    created_at: datetime

    @classmethod
    def from_aggregate(cls, aggregate: WorkAggregate) -> "WorkProjection":
        return cls(
            id=aggregate.work.id,
            workspace_id=aggregate.work.workspace_id,
            command_id=aggregate.work.command_id,
            objective=aggregate.work.objective,
            status=aggregate.work.status,
            graph_revision_id=aggregate.graph.id,
            graph_revision_number=aggregate.graph.revision_number,
            strategy=aggregate.graph.strategy,
            nodes=[
                WorkNode(
                    id=node.id,
                    objective=node.objective,
                    acceptance_criteria=list(node.acceptance_criteria),
                    assigned_employee_id=node.assigned_employee_id,
                    employee_revision_id=node.employee_revision_id,
                    status=node.status,
                    active_attempt_id=node.active_attempt_id,
                    failure_code=node.failure_code,
                    version=node.version,
                    attempt_count=node.attempt_count,
                    max_attempts=node.max_attempts,
                )
                for node in aggregate.nodes
            ],
            edges=[
                WorkEdge(
                    from_node_id=edge.from_node_id,
                    to_node_id=edge.to_node_id,
                    kind=edge.kind,
                )
                for edge in aggregate.graph.edges
            ],
            execution_links=[
                ExecutionLink(
                    id=link.id,
                    node_id=link.node_id,
                    attempt_id=link.attempt_id,
                    status=link.status,
                    started_at=link.started_at,
                    finished_at=link.finished_at,
                    diagnostic_code=link.diagnostic_code,
                )
                for link in aggregate.execution_links
            ],
            artifacts=[
                ArtifactReference(
                    id=artifact.id,
                    kind=artifact.kind,
                    uri=artifact.uri,
                    created_at=artifact.created_at,
                )
                for artifact in aggregate.artifacts
            ],
            created_at=aggregate.work.created_at,
        )


class CompanyEvent(BaseModel):
    id: str
    workspace_id: str
    work_id: str
    node_id: str | None
    attempt_id: str | None
    source_sequence: int
    event_type: str
    summary: str
    source: str
    observed_at: datetime

    @classmethod
    def from_domain(cls, event: DomainCompanyEvent) -> "CompanyEvent":
        return cls(
            id=event.id,
            workspace_id=event.workspace_id,
            work_id=event.work_id,
            node_id=event.node_id,
            attempt_id=event.attempt_id,
            source_sequence=event.source_sequence,
            event_type=event.event_type,
            summary=event.summary,
            source=event.source,
            observed_at=event.observed_at,
        )

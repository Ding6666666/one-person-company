from typing import Protocol

from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
)
from dsh_company.domain.work import ExecutionLink


class OrchestrationEngine(Protocol):
    def start(self, graph_revision_id: WorkGraphRevisionId) -> None: ...

    def dispatch_ready_nodes(self, work_id: WorkId) -> tuple[ExecutionLink, ...]: ...

    def record_completion(
        self,
        node_id: WorkNodeId,
        attempt_id: AttemptId,
        result_reference: ArtifactReferenceId,
    ) -> None: ...

    def record_failure(
        self, node_id: WorkNodeId, attempt_id: AttemptId, reason: str
    ) -> None: ...

    def request_cancel(self, node_id: WorkNodeId) -> None: ...

    def reconcile(self, work_id: WorkId) -> None: ...

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from dsh_company.domain.ids import (
    AttemptId,
    ChatExecutionId,
    EmployeeId,
    EmployeeRevisionId,
)

from .control_requests import ControlRequest
from .events import ProjectedDshEvent


@dataclass(frozen=True, slots=True)
class EmployeeRuntimeSnapshot:
    employee_id: EmployeeId
    employee_revision_id: EmployeeRevisionId
    responsibility: str
    system_prompt: str
    runtime_profile: str
    model: str
    dsh_session_id: str


@dataclass(frozen=True, slots=True)
class GatewaySubmission:
    attempt_id: AttemptId
    command_id: str
    employee: EmployeeRuntimeSnapshot
    objective: str
    acceptance_criteria: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GatewayResult:
    finish_reason: str | None
    reference_uri: str | None
    event_count: int
    control_request: ControlRequest | None = None


@dataclass(frozen=True, slots=True)
class GatewayCancelResult:
    requested: bool
    runtime_closed: bool


@dataclass(frozen=True, slots=True)
class ChatContextMessage:
    author: Literal["user", "employee", "system"]
    body: str


@dataclass(frozen=True, slots=True)
class ChatGatewaySubmission:
    execution_id: ChatExecutionId
    employee: EmployeeRuntimeSnapshot
    instruction: str
    context: tuple[ChatContextMessage, ...]
    work_context: str | None


@dataclass(frozen=True, slots=True)
class ChatGatewayResult:
    finish_reason: str | None
    response_text: str


class ChatGateway(Protocol):
    def submit_chat(self, submission: ChatGatewaySubmission) -> ChatGatewayResult: ...


class WorkGateway(Protocol):
    def submit(
        self,
        submission: GatewaySubmission,
        *,
        on_event: Callable[[ProjectedDshEvent], None],
    ) -> GatewayResult: ...

    def cancel(self, attempt_id: AttemptId) -> GatewayCancelResult: ...

    def shutdown(self) -> None: ...


class DshGateway(WorkGateway, ChatGateway, Protocol):
    pass

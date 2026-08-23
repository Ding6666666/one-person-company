from dataclasses import dataclass

from dsh_company.domain.ids import EmployeeId, WorkId, WorkspaceId


@dataclass(frozen=True, slots=True)
class SendChatMessage:
    workspace_id: WorkspaceId
    body: str
    mention_employee_ids: tuple[EmployeeId, ...]
    work_id: WorkId | None = None

    def __post_init__(self) -> None:
        normalized_body = self.body.strip()
        if not normalized_body:
            raise ValueError("message body must not be blank")
        if len(normalized_body) > 4000:
            raise ValueError("message body must be at most 4000 characters")
        unique_mentions = tuple(dict.fromkeys(self.mention_employee_ids))
        if len(unique_mentions) > 8:
            raise ValueError("a message may mention at most eight employees")
        object.__setattr__(self, "body", normalized_body)
        object.__setattr__(self, "mention_employee_ids", unique_mentions)

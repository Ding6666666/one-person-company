from types import TracebackType
from typing import Self

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from .governance_repositories import (
    ApprovalRepository,
    DelegationRepository,
    NodeCapabilityGrantRepository,
    WorkspaceCapabilityGrantRepository,
)
from .repositories import EmployeeRepository, WorkspaceRepository
from .work_repositories import CompanyEventRepository, WorkRepository


class SqlAlchemyUnitOfWork:
    workspaces: WorkspaceRepository
    employees: EmployeeRepository
    works: WorkRepository
    company_events: CompanyEventRepository
    workspace_grants: WorkspaceCapabilityGrantRepository
    node_grants: NodeCapabilityGrantRepository
    approvals: ApprovalRepository
    delegations: DelegationRepository

    def __init__(self, engine: Engine) -> None:
        self._session_factory = sessionmaker(engine, expire_on_commit=False)
        self._session: Session | None = None
        self._committed = False

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self._committed = False
        self.workspaces = WorkspaceRepository(self._session)
        self.employees = EmployeeRepository(self._session)
        self.works = WorkRepository(self._session)
        self.company_events = CompanyEventRepository(self._session)
        self.workspace_grants = WorkspaceCapabilityGrantRepository(self._session)
        self.node_grants = NodeCapabilityGrantRepository(self._session)
        self.approvals = ApprovalRepository(self._session)
        self.delegations = DelegationRepository(self._session)
        return self

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        if not self._committed:
            self._session.commit()
            self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        try:
            if not self._committed:
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import APIRouter

from dsh_company.api.company import router as company_router
from dsh_company.api.work import router as work_router
from dsh_company.application.ports import WorkCoordinator, WorkUnitOfWork
from dsh_company.domain.ids import WorkNodeId
from dsh_company.foundation.config import Settings
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork


def _unconfigured_uow() -> WorkUnitOfWork:
    raise RuntimeError("persistence assembly is not configured")


def _noop() -> None:
    return None


class _UnconfiguredWorkCoordinator:
    def enqueue(self, node_id: WorkNodeId) -> None:
        del node_id
        raise RuntimeError("work coordinator is not configured")

    def request_cancel(self, node_id: WorkNodeId) -> None:
        del node_id
        raise RuntimeError("work coordinator is not configured")


def _company_router() -> APIRouter:
    router = APIRouter()
    router.include_router(company_router)
    router.include_router(work_router)
    return router


@dataclass(frozen=True, slots=True)
class ComponentAssembly:
    uow_factory: Callable[[], WorkUnitOfWork] = _unconfigured_uow
    work_coordinator: WorkCoordinator = field(
        default_factory=_UnconfiguredWorkCoordinator
    )
    router: APIRouter = field(default_factory=_company_router)
    dispose: Callable[[], None] = _noop


def create_production_assembly(settings: Settings) -> ComponentAssembly:
    settings.data_root.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.data_root / "company.db")
    try:
        create_tables(engine)
    except BaseException:
        engine.dispose()
        raise
    return ComponentAssembly(
        uow_factory=lambda: SqlAlchemyUnitOfWork(engine),
        dispose=engine.dispose,
    )

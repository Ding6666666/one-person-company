from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import APIRouter

from dsh_company.api.company import router as company_router
from dsh_company.application.ports import UnitOfWork
from dsh_company.foundation.config import Settings
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork


def _unconfigured_uow() -> UnitOfWork:
    raise RuntimeError("persistence assembly is not configured")


def _noop() -> None:
    return None


@dataclass(frozen=True, slots=True)
class ComponentAssembly:
    uow_factory: Callable[[], UnitOfWork] = _unconfigured_uow
    router: APIRouter = field(default_factory=lambda: company_router)
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

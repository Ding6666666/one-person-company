from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import APIRouter

from dsh_company.api.company import router as company_router
from dsh_company.application.ports import UnitOfWork


def _unconfigured_uow() -> UnitOfWork:
    raise RuntimeError("persistence assembly is not configured")


@dataclass(frozen=True, slots=True)
class ComponentAssembly:
    uow_factory: Callable[[], UnitOfWork] = _unconfigured_uow
    router: APIRouter = field(default_factory=lambda: company_router)

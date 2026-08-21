from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import APIRouter

from dsh_company.api.company import router as company_router
from dsh_company.api.governance import router as governance_router
from dsh_company.api.work import router as work_router
from dsh_company.application.delegation_service import DelegationService
from dsh_company.application.governance_service import GovernanceService
from dsh_company.application.ports import WorkCoordinator, WorkUnitOfWork
from dsh_company.application.runtime_coordinator import RuntimeCoordinator
from dsh_company.application.runtime_governance import RuntimeGovernanceHandler
from dsh_company.domain.ids import WorkNodeId
from dsh_company.domain.policy import PolicyEngine
from dsh_company.dsh_gateway.adapter import PublicSdkDshGateway
from dsh_company.foundation.config import Settings
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork


def _unconfigured_uow() -> WorkUnitOfWork:
    raise RuntimeError("persistence assembly is not configured")


def _noop() -> None:
    return None


def _unconfigured_governance_service() -> GovernanceService:
    raise RuntimeError("governance assembly is not configured")


def _unconfigured_delegation_service() -> DelegationService:
    raise RuntimeError("delegation assembly is not configured")


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
    router.include_router(governance_router)
    return router


@dataclass(frozen=True, slots=True)
class ComponentAssembly:
    uow_factory: Callable[[], WorkUnitOfWork] = _unconfigured_uow
    work_coordinator: WorkCoordinator = field(default_factory=_UnconfiguredWorkCoordinator)
    governance_service_factory: Callable[[], GovernanceService] = _unconfigured_governance_service
    delegation_service_factory: Callable[[], DelegationService] = _unconfigured_delegation_service
    router: APIRouter = field(default_factory=_company_router)
    startup: Callable[[], None] = _noop
    dispose: Callable[[], None] = _noop


def create_production_assembly(settings: Settings) -> ComponentAssembly:
    settings.data_root.mkdir(parents=True, exist_ok=True)
    session_root = settings.resolved_session_root
    workspace_root = settings.resolved_workspace_root
    session_root.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.data_root / "company.db")
    try:
        create_tables(engine)
        gateway = PublicSdkDshGateway(
            session_root=session_root,
            working_directory=workspace_root,
            provider=settings.dsh_provider,
            base_url=settings.dsh_base_url,
            api_key=(
                None
                if settings.deepseek_api_key is None
                else settings.deepseek_api_key.get_secret_value()
            ),
            request_timeout_seconds=settings.dsh_request_timeout_seconds,
            shutdown_timeout_seconds=settings.dsh_shutdown_timeout_seconds,
        )

        def uow_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(engine)

        governance_handler = RuntimeGovernanceHandler(
            uow_factory,
            PolicyEngine(),
        )
        coordinator = RuntimeCoordinator(
            uow_factory,
            gateway,
            governance_handler=governance_handler,
            runtime_concurrency=settings.runtime_concurrency,
        )

        def governance_service_factory() -> GovernanceService:
            return GovernanceService(uow_factory(), PolicyEngine(), coordinator)

        def delegation_service_factory() -> DelegationService:
            return DelegationService(uow_factory(), PolicyEngine(), coordinator)
    except BaseException:
        engine.dispose()
        raise

    def dispose() -> None:
        try:
            coordinator.shutdown(wait=True)
        finally:
            engine.dispose()

    return ComponentAssembly(
        uow_factory=uow_factory,
        work_coordinator=coordinator,
        governance_service_factory=governance_service_factory,
        delegation_service_factory=delegation_service_factory,
        startup=coordinator.start,
        dispose=dispose,
    )

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import APIRouter

from dsh_company.api.capability_sources import router as capability_sources_router
from dsh_company.api.chat import router as chat_router
from dsh_company.api.company import router as company_router
from dsh_company.api.governance import router as governance_router
from dsh_company.api.plugins import router as plugins_router
from dsh_company.api.work import router as work_router
from dsh_company.application.chat_coordinator import ChatCoordinator
from dsh_company.application.delegation_service import DelegationService
from dsh_company.application.governance_service import GovernanceService
from dsh_company.application.ports import ChatDispatchQueue, WorkCoordinator, WorkUnitOfWork
from dsh_company.application.runtime_coordinator import RuntimeCoordinator
from dsh_company.application.runtime_governance import RuntimeGovernanceHandler
from dsh_company.business_plugins.registry import BusinessPluginRegistry
from dsh_company.capability_sources.registry import CapabilitySourceRegistry
from dsh_company.domain.ids import (
    ArtifactReferenceId,
    AttemptId,
    ChatExecutionId,
    WorkGraphRevisionId,
    WorkId,
    WorkNodeId,
)
from dsh_company.domain.policy import PolicyEngine
from dsh_company.domain.work import ExecutionLink
from dsh_company.dsh_gateway.adapter import PublicSdkDshGateway
from dsh_company.foundation.config import Settings
from dsh_company.orchestration.contracts import OrchestrationEngine
from dsh_company.orchestration.durable_graph import DurableGraphEngine
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


class _UnconfiguredChatDispatchQueue:
    def enqueue_chat(self, execution_id: ChatExecutionId) -> None:
        del execution_id
        raise RuntimeError("chat coordinator is not configured")


class _UnconfiguredOrchestrationEngine:
    def start(self, graph_revision_id: WorkGraphRevisionId) -> None:
        del graph_revision_id
        raise RuntimeError("orchestration engine is not configured")

    def dispatch_ready_nodes(self, work_id: WorkId) -> tuple[ExecutionLink, ...]:
        del work_id
        raise RuntimeError("orchestration engine is not configured")

    def record_completion(
        self,
        node_id: WorkNodeId,
        attempt_id: AttemptId,
        result_reference: ArtifactReferenceId,
    ) -> None:
        del node_id, attempt_id, result_reference
        raise RuntimeError("orchestration engine is not configured")

    def record_failure(self, node_id: WorkNodeId, attempt_id: AttemptId, reason: str) -> None:
        del node_id, attempt_id, reason
        raise RuntimeError("orchestration engine is not configured")

    def request_cancel(self, node_id: WorkNodeId) -> None:
        del node_id
        raise RuntimeError("orchestration engine is not configured")

    def reconcile(self, work_id: WorkId) -> None:
        del work_id
        raise RuntimeError("orchestration engine is not configured")


class _TerminalObserverProxy:
    def __init__(self) -> None:
        self.target: OrchestrationEngine | None = None

    def reconcile(self, work_id: WorkId) -> None:
        if self.target is not None:
            self.target.reconcile(work_id)


def _company_router() -> APIRouter:
    router = APIRouter()
    router.include_router(company_router)
    router.include_router(chat_router)
    router.include_router(capability_sources_router)
    router.include_router(work_router)
    router.include_router(governance_router)
    router.include_router(plugins_router)
    return router


@dataclass(frozen=True, slots=True)
class ComponentAssembly:
    uow_factory: Callable[[], WorkUnitOfWork] = _unconfigured_uow
    work_coordinator: WorkCoordinator = field(default_factory=_UnconfiguredWorkCoordinator)
    chat_dispatch_queue: ChatDispatchQueue = field(
        default_factory=_UnconfiguredChatDispatchQueue
    )
    orchestration_engine: OrchestrationEngine = field(
        default_factory=_UnconfiguredOrchestrationEngine
    )
    governance_service_factory: Callable[[], GovernanceService] = _unconfigured_governance_service
    delegation_service_factory: Callable[[], DelegationService] = _unconfigured_delegation_service
    router: APIRouter = field(default_factory=_company_router)
    startup: Callable[[], None] = _noop
    dispose: Callable[[], None] = _noop
    capability_sources: CapabilitySourceRegistry = field(default_factory=CapabilitySourceRegistry)


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

        action_catalog = BusinessPluginRegistry(uow_factory).action_catalog
        policy_engine = PolicyEngine(action_catalog)
        governance_handler = RuntimeGovernanceHandler(uow_factory, policy_engine)
        terminal_observer = _TerminalObserverProxy()
        coordinator = RuntimeCoordinator(
            uow_factory,
            gateway,
            governance_handler=governance_handler,
            terminal_observer=terminal_observer,
            runtime_concurrency=settings.runtime_concurrency,
        )
        chat_coordinator = ChatCoordinator(
            uow_factory,
            gateway,
            runtime_concurrency=settings.runtime_concurrency,
        )
        orchestration_engine = DurableGraphEngine(
            uow_factory,
            coordinator,
            policy_engine=policy_engine,
            runtime_concurrency=settings.runtime_concurrency,
        )
        terminal_observer.target = orchestration_engine

        def governance_service_factory() -> GovernanceService:
            return GovernanceService(
                uow_factory(),
                policy_engine,
                coordinator,
                terminal_observer=terminal_observer,
            )

        def delegation_service_factory() -> DelegationService:
            return DelegationService(uow_factory(), policy_engine, coordinator)
    except BaseException:
        engine.dispose()
        raise

    def startup() -> None:
        coordinator.start()
        chat_coordinator.start()

    def dispose() -> None:
        try:
            chat_coordinator.shutdown(wait=True)
        finally:
            try:
                coordinator.shutdown(wait=True)
            finally:
                engine.dispose()

    return ComponentAssembly(
        uow_factory=uow_factory,
        work_coordinator=coordinator,
        chat_dispatch_queue=chat_coordinator,
        orchestration_engine=orchestration_engine,
        governance_service_factory=governance_service_factory,
        delegation_service_factory=delegation_service_factory,
        startup=startup,
        dispose=dispose,
    )

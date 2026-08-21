from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from deepseek_harness import DeepSeekHarness, Notification

from dsh_company.domain.ids import AttemptId

from .contracts import (
    GatewayCancelResult,
    GatewayResult,
    GatewaySubmission,
)
from .control_requests import is_control_request_candidate, parse_control_request
from .events import ProjectedDshEvent, project_notification
from .supervisor import ClosableHarness, RuntimeSupervisor

_RUNTIME_PROFILES = frozenset({"workspace_read", "workspace_write", "network_denied"})
_DEFAULT_PROVIDER = "deepseek-official"
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0
_DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 10.0


class _RunResult(Protocol):
    finish_reason: str | None
    final_response: str


class _Session(Protocol):
    def run(
        self,
        prompt: str,
        *,
        on_notification: Callable[[Notification], None] | None = None,
    ) -> _RunResult: ...


class _Harness(ClosableHarness, Protocol):
    def start_session(self, session_id: str | None = None) -> _Session: ...


class _HarnessFactory(Protocol):
    def __call__(self, **config: object) -> _Harness: ...


def _prompt(submission: GatewaySubmission) -> str:
    criteria = "\n".join(f"- {criterion}" for criterion in submission.acceptance_criteria)
    return (
        f"Employee responsibility:\n{submission.employee.responsibility}\n\n"
        f"Work objective:\n{submission.objective}\n\n"
        f"Acceptance criteria:\n{criteria}\n\n"
        "Complete the work using only the capabilities exposed by the active DSH "
        "runtime profile. Return a concise result in the DSH Session."
    )


class PublicSdkDshGateway:
    def __init__(
        self,
        harness_factory: _HarnessFactory | None = None,
        *,
        session_root: Path,
        working_directory: Path | None = None,
        supervisor: RuntimeSupervisor | None = None,
        provider: str = _DEFAULT_PROVIDER,
        base_url: str | None = None,
        api_key: str | None = None,
        request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
        shutdown_timeout_seconds: float = _DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        self._harness_factory = harness_factory or cast(_HarnessFactory, DeepSeekHarness)
        self._session_root = session_root
        self._working_directory = working_directory or Path.cwd()
        self._supervisor = supervisor or RuntimeSupervisor()
        self._provider = provider
        self._base_url = base_url
        self._api_key = api_key
        self._request_timeout_seconds = request_timeout_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._cordis_root = Path(__file__).with_name("cordis")

    def submit(
        self,
        submission: GatewaySubmission,
        *,
        on_event: Callable[[ProjectedDshEvent], None],
    ) -> GatewayResult:
        runtime_profile = submission.employee.runtime_profile
        if runtime_profile not in _RUNTIME_PROFILES:
            raise ValueError(f"unknown DSH runtime profile: {runtime_profile}")
        profile_path = self._cordis_root / f"{runtime_profile}.cordis.yml"
        harness_config: dict[str, object] = {
            "provider": self._provider,
            "model": submission.employee.model,
            "cwd": str(self._working_directory),
            "session_root": str(self._session_root),
            "cordis": str(profile_path),
            "env": {
                "DSH_COMPANY_SESSION_ROOT": str(self._session_root),
                "DSH_COMPANY_WORKSPACE_ROOT": str(self._working_directory),
            },
            "request_timeout_seconds": self._request_timeout_seconds,
            "shutdown_timeout_seconds": self._shutdown_timeout_seconds,
        }
        if self._base_url is not None:
            harness_config["base_url"] = self._base_url
        if self._api_key is not None:
            harness_config["api_key"] = self._api_key
        harness = self._supervisor.create(
            submission.attempt_id,
            lambda: self._harness_factory(**harness_config),
        )
        event_count = 0

        def receive(notification: Notification) -> None:
            nonlocal event_count
            event_count += 1
            on_event(project_notification(submission.attempt_id, event_count, notification))

        try:
            session = harness.start_session(submission.employee.dsh_session_id)
            result = session.run(_prompt(submission), on_notification=receive)
            try:
                control_request = parse_control_request(result.final_response)
            except ValueError:
                if is_control_request_candidate(result.final_response):
                    raise
                control_request = None
            return GatewayResult(
                finish_reason=result.finish_reason,
                reference_uri=(
                    None
                    if control_request is not None
                    else (
                        f"dsh-session://{submission.employee.dsh_session_id}/attempt/"
                        f"{submission.attempt_id}/result"
                    )
                ),
                event_count=event_count,
                control_request=control_request,
            )
        finally:
            self._supervisor.finish(submission.attempt_id, harness)

    def cancel(self, attempt_id: AttemptId) -> GatewayCancelResult:
        return self._supervisor.cancel(attempt_id)

    def shutdown(self) -> None:
        self._supervisor.close_all()

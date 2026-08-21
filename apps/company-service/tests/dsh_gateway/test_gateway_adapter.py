from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Any

import dsh_company.dsh_gateway.adapter as gateway_adapter
import pytest
from deepseek_harness import Notification
from dsh_company.domain.ids import AttemptId, EmployeeId, EmployeeRevisionId
from dsh_company.dsh_gateway.adapter import PublicSdkDshGateway
from dsh_company.dsh_gateway.contracts import (
    EmployeeRuntimeSnapshot,
    GatewayCancelResult,
    GatewaySubmission,
)
from dsh_company.dsh_gateway.control_requests import ApprovalControlRequest
from dsh_company.dsh_gateway.supervisor import RuntimeSupervisor


@dataclass
class FakeRunResult:
    finish_reason: str | None = "completed"
    final_response: str = "must never escape the adapter"


class FakeSession:
    def __init__(
        self,
        harness: "FakeHarness",
        notifications: tuple[Notification, ...],
        run_started: Event | None = None,
        release_run: Event | None = None,
    ) -> None:
        self._harness = harness
        self._notifications = notifications
        self._run_started = run_started
        self._release_run = release_run

    def run(
        self, prompt: str, *, on_notification: Callable[[Notification], None] | None = None
    ) -> FakeRunResult:
        self._harness.prompt = prompt
        self._harness.registered_when_run = self._harness.factory.gateway_is_active(
            AttemptId("attempt-1")
        )
        if self._run_started is not None:
            self._run_started.set()
        if self._release_run is not None:
            self._release_run.wait(timeout=5)
        for notification in self._notifications:
            if on_notification is not None:
                on_notification(notification)
        return FakeRunResult(final_response=self._harness.factory.final_response)


class FakeHarness:
    def __init__(self, factory: "FakeHarnessFactory", config: dict[str, Any]) -> None:
        self.factory = factory
        self.config = config
        self.prompt: str | None = None
        self.registered_when_run = False
        self.session_id: str | None = None

    def start_session(self, session_id: str | None = None) -> FakeSession:
        self.session_id = session_id
        self.factory.last_session_id = session_id
        return FakeSession(
            self,
            self.factory.notifications,
            self.factory.run_started,
            self.factory.release_run,
        )

    def close(self) -> None:
        self.factory.close_calls.append(str(self.factory.active_attempt))


class FakeHarnessFactory:
    def __init__(
        self,
        *,
        notifications: tuple[Notification, ...] = (),
        run_started: Event | None = None,
        release_run: Event | None = None,
        final_response: str = "must never escape the adapter",
    ) -> None:
        self.notifications = notifications
        self.run_started = run_started
        self.release_run = release_run
        self.final_response = final_response
        self.last_session_id: str | None = None
        self.last_harness: FakeHarness | None = None
        self.create_calls = 0
        self.close_calls: list[str] = []
        self.active_attempt: AttemptId | None = None
        self.supervisor: RuntimeSupervisor | None = None

    def __call__(self, **config: Any) -> FakeHarness:
        self.create_calls += 1
        self.last_harness = FakeHarness(self, config)
        return self.last_harness

    def gateway_is_active(self, attempt_id: AttemptId) -> bool:
        assert self.supervisor is not None
        self.active_attempt = attempt_id
        return self.supervisor.is_active(attempt_id)


def employee_snapshot(
    *, session_id: str = "employee-emp-1", runtime_profile: str = "workspace_read"
) -> EmployeeRuntimeSnapshot:
    return EmployeeRuntimeSnapshot(
        employee_id=EmployeeId("emp-1"),
        employee_revision_id=EmployeeRevisionId("rev-1"),
        responsibility="撰写清晰、准确的发布稿",
        runtime_profile=runtime_profile,
        model="deepseek-chat",
        dsh_session_id=session_id,
    )


def submission(*, runtime_profile: str = "workspace_read") -> GatewaySubmission:
    return GatewaySubmission(
        attempt_id=AttemptId("attempt-1"),
        command_id="cmd-1",
        employee=employee_snapshot(runtime_profile=runtime_profile),
        objective="撰写发布稿",
        acceptance_criteria=("包含标题", "不超过 800 字"),
    )


def make_gateway(factory: FakeHarnessFactory, tmp_path: Path) -> PublicSdkDshGateway:
    supervisor = RuntimeSupervisor()
    gateway = PublicSdkDshGateway(
        factory,
        session_root=tmp_path / "sessions",
        working_directory=tmp_path,
        supervisor=supervisor,
    )
    factory.supervisor = supervisor
    return gateway


def test_gateway_reuses_binding_session_and_returns_reference(tmp_path: Path) -> None:
    factory = FakeHarnessFactory()
    gateway = make_gateway(factory, tmp_path)
    events = []

    result = gateway.submit(submission(), on_event=events.append)

    assert factory.last_session_id == "employee-emp-1"
    assert result.finish_reason == "completed"
    assert result.reference_uri == ("dsh-session://employee-emp-1/attempt/attempt-1/result")
    assert result.event_count == 0
    assert factory.last_harness is not None
    assert factory.last_harness.config["model"] == "deepseek-chat"
    assert factory.last_harness.registered_when_run is True
    assert factory.close_calls == ["attempt-1"]


def test_gateway_uses_deterministic_prompt_and_callback_sequence(tmp_path: Path) -> None:
    notifications = (
        Notification(method="session.status", payload={"status": "busy"}),
        Notification(
            method="session.event",
            payload={"event": {"type": "turn/end", "data": {"finishReason": "completed"}}},
        ),
    )
    factory = FakeHarnessFactory(notifications=notifications)
    gateway = make_gateway(factory, tmp_path)
    projected = []

    result = gateway.submit(submission(), on_event=projected.append)

    assert factory.last_harness is not None
    assert factory.last_harness.prompt == (
        "Employee responsibility:\n撰写清晰、准确的发布稿\n\n"
        "Work objective:\n撰写发布稿\n\n"
        "Acceptance criteria:\n- 包含标题\n- 不超过 800 字\n\n"
        "Complete the work using only the capabilities exposed by the active DSH "
        "runtime profile. Return a concise result in the DSH Session."
    )
    assert [event.source_sequence for event in projected] == [1, 2]
    assert result.event_count == 2
    assert "must never escape" not in repr(result)


def test_gateway_returns_typed_control_request_without_result_reference(
    tmp_path: Path,
) -> None:
    factory = FakeHarnessFactory(
        final_response=(
            '{"kind":"approval","action":"workspace.write",'
            '"resources":["repo-a"],"reason":"publish release"}'
        )
    )
    gateway = make_gateway(factory, tmp_path)

    result = gateway.submit(submission(), on_event=lambda event: None)

    assert isinstance(result.control_request, ApprovalControlRequest)
    assert result.reference_uri is None
    assert not hasattr(result, "raw_model_output")


def test_gateway_keeps_normal_output_as_an_opaque_reference(tmp_path: Path) -> None:
    factory = FakeHarnessFactory(final_response="A concise normal result")
    gateway = make_gateway(factory, tmp_path)

    result = gateway.submit(submission(), on_event=lambda event: None)

    assert result.control_request is None
    assert result.reference_uri == (
        "dsh-session://employee-emp-1/attempt/attempt-1/result"
    )
    assert "concise normal result" not in repr(result).lower()


def test_gateway_keeps_prose_that_mentions_kind_and_approval_as_normal_output(
    tmp_path: Path,
) -> None:
    factory = FakeHarnessFactory(
        final_response='The field "kind" needs "approval" from a reviewer.'
    )
    gateway = make_gateway(factory, tmp_path)

    result = gateway.submit(submission(), on_event=lambda event: None)

    assert result.control_request is None
    assert result.reference_uri == (
        "dsh-session://employee-emp-1/attempt/attempt-1/result"
    )


@pytest.mark.parametrize(
    "final_response",
    [
        '{"kind":"approval"}',
        'prefix {"kind":"delegation"}',
        '{"kind":"approval","action":"unknown.action",'
        '"resources":["repo-a"],"reason":"x"}',
    ],
)
def test_gateway_rejects_malformed_control_attempts(
    tmp_path: Path, final_response: str
) -> None:
    factory = FakeHarnessFactory(final_response=final_response)
    gateway = make_gateway(factory, tmp_path)

    with pytest.raises(ValueError, match="control"):
        gateway.submit(submission(), on_event=lambda event: None)

    assert factory.close_calls == ["attempt-1"]


def test_gateway_selects_checked_in_profile_and_company_environment(tmp_path: Path) -> None:
    factory = FakeHarnessFactory()
    gateway = make_gateway(factory, tmp_path)

    gateway.submit(submission(runtime_profile="workspace_write"), on_event=lambda event: None)

    assert factory.last_harness is not None
    config = factory.last_harness.config
    assert config == {
        "provider": "deepseek-official",
        "model": "deepseek-chat",
        "cwd": str(tmp_path),
        "session_root": str(tmp_path / "sessions"),
        "cordis": str(
            Path(gateway_adapter.__file__).with_name("cordis")
            / "workspace_write.cordis.yml"
        ),
        "env": {
            "DSH_COMPANY_SESSION_ROOT": str(tmp_path / "sessions"),
            "DSH_COMPANY_WORKSPACE_ROOT": str(tmp_path),
        },
        "request_timeout_seconds": 60.0,
        "shutdown_timeout_seconds": 10.0,
    }


def test_gateway_passes_explicit_provider_and_timeouts_to_sdk_factory(
    tmp_path: Path,
) -> None:
    factory = FakeHarnessFactory()
    supervisor = RuntimeSupervisor()
    gateway = PublicSdkDshGateway(
        factory,
        session_root=tmp_path / "sessions",
        working_directory=tmp_path,
        supervisor=supervisor,
        provider="configured-provider",
        request_timeout_seconds=12.5,
        shutdown_timeout_seconds=3.25,
    )
    factory.supervisor = supervisor

    gateway.submit(submission(), on_event=lambda event: None)

    assert factory.last_harness is not None
    assert factory.last_harness.config["provider"] == "configured-provider"
    assert factory.last_harness.config["request_timeout_seconds"] == 12.5
    assert factory.last_harness.config["shutdown_timeout_seconds"] == 3.25


def test_gateway_rejects_unknown_runtime_profile_without_starting_harness(
    tmp_path: Path,
) -> None:
    factory = FakeHarnessFactory()
    gateway = make_gateway(factory, tmp_path)

    with pytest.raises(ValueError, match="runtime profile"):
        gateway.submit(submission(runtime_profile="invented"), on_event=lambda event: None)

    assert factory.last_harness is None


def test_duplicate_active_attempt_is_rejected_and_cancel_closes_exactly_once(
    tmp_path: Path,
) -> None:
    run_started = Event()
    release_run = Event()
    factory = FakeHarnessFactory(run_started=run_started, release_run=release_run)
    gateway = make_gateway(factory, tmp_path)
    errors: list[BaseException] = []

    def run_submission() -> None:
        try:
            gateway.submit(submission(), on_event=lambda event: None)
        except BaseException as error:
            errors.append(error)

    worker = Thread(target=run_submission)
    worker.start()
    assert run_started.wait(timeout=5)

    with pytest.raises(ValueError, match="already active"):
        gateway.submit(submission(), on_event=lambda event: None)
    assert factory.create_calls == 1

    first = gateway.cancel(AttemptId("attempt-1"))
    second = gateway.cancel(AttemptId("attempt-1"))
    assert factory.supervisor is not None
    assert factory.supervisor.is_active(AttemptId("attempt-1")) is True
    release_run.set()
    worker.join(timeout=5)

    assert first.runtime_closed is True
    assert second.runtime_closed is True
    assert factory.close_calls == ["attempt-1"]
    assert factory.supervisor.is_active(AttemptId("attempt-1")) is False
    assert errors == []


def test_cancel_unknown_attempt_does_not_close_another_harness(tmp_path: Path) -> None:
    run_started = Event()
    release_run = Event()
    factory = FakeHarnessFactory(run_started=run_started, release_run=release_run)
    gateway = make_gateway(factory, tmp_path)
    worker = Thread(target=lambda: gateway.submit(submission(), on_event=lambda event: None))
    worker.start()
    assert run_started.wait(timeout=5)

    result = gateway.cancel(AttemptId("attempt-other"))
    release_run.set()
    worker.join(timeout=5)

    assert result.runtime_closed is False
    assert factory.close_calls == ["attempt-1"]


def test_shutdown_barrier_rejects_new_harness_creation(tmp_path: Path) -> None:
    factory = FakeHarnessFactory()
    gateway = make_gateway(factory, tmp_path)

    gateway.shutdown()

    with pytest.raises(RuntimeError, match="shutting down"):
        gateway.submit(submission(), on_event=lambda event: None)
    assert factory.create_calls == 0


def test_supervisor_does_not_start_a_harness_after_cancel_wins() -> None:
    supervisor = RuntimeSupervisor()
    harness = FakeHarness(FakeHarnessFactory(), {})
    attempt_id = AttemptId("attempt-start-cancelled")
    supervisor.register(attempt_id, harness)

    cancelled = supervisor.cancel(attempt_id)

    with pytest.raises(RuntimeError, match="already closed"):
        supervisor.start(attempt_id, harness, lambda: harness.start_session("session-1"))
    supervisor.finish(attempt_id, harness)

    assert cancelled.runtime_closed is True
    assert harness.factory.close_calls == ["None"]
    assert harness.session_id is None


def test_supervisor_serializes_runtime_start_before_cancel() -> None:
    supervisor = RuntimeSupervisor()
    harness = FakeHarness(FakeHarnessFactory(), {})
    attempt_id = AttemptId("attempt-start-first")
    supervisor.register(attempt_id, harness)
    start_entered = Event()
    release_start = Event()
    started: list[FakeSession] = []

    def start_runtime() -> FakeSession:
        start_entered.set()
        assert release_start.wait(timeout=5)
        return harness.start_session("session-1")

    start_worker = Thread(
        target=lambda: started.append(
            supervisor.start(attempt_id, harness, start_runtime)
        )
    )
    start_worker.start()
    assert start_entered.wait(timeout=5)
    cancel_results: list[GatewayCancelResult] = []
    cancel_worker = Thread(target=lambda: cancel_results.append(supervisor.cancel(attempt_id)))
    cancel_worker.start()

    assert cancel_results == []
    release_start.set()
    start_worker.join(timeout=5)
    cancel_worker.join(timeout=5)
    supervisor.finish(attempt_id, harness)

    assert len(started) == 1
    assert cancel_results == [GatewayCancelResult(requested=True, runtime_closed=True)]
    assert harness.factory.close_calls == ["None"]

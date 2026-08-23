from collections.abc import Callable
from threading import Lock
from typing import Protocol, TypeVar

from dsh_company.domain.ids import AttemptId, ChatExecutionId

from .contracts import GatewayCancelResult


class ClosableHarness(Protocol):
    def close(self) -> None: ...


HarnessT = TypeVar("HarnessT", bound=ClosableHarness)
ResultT = TypeVar("ResultT")
RuntimeId = AttemptId | ChatExecutionId


class _AttemptHandle:
    def __init__(self, harness: ClosableHarness) -> None:
        self.harness = harness
        self._close_lock = Lock()
        self._close_started = False
        self._close_succeeded = False

    def close_once(self) -> bool:
        with self._close_lock:
            if self._close_started:
                return self._close_succeeded
            self._close_started = True
            try:
                self.harness.close()
            except BaseException:
                self._close_succeeded = False
                raise
            self._close_succeeded = True
            return True

    def start_unless_closed(self, starter: Callable[[], ResultT]) -> ResultT:
        with self._close_lock:
            if self._close_started:
                raise RuntimeError("runtime attempt is already closed")
            return starter()


class RuntimeSupervisor:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active: dict[RuntimeId, _AttemptHandle] = {}
        self._closing = False

    def register(self, attempt_id: RuntimeId, harness: ClosableHarness) -> None:
        with self._lock:
            if self._closing:
                raise RuntimeError("runtime supervisor is shutting down")
            if attempt_id in self._active:
                raise ValueError(f"attempt {attempt_id} is already active")
            self._active[attempt_id] = _AttemptHandle(harness)

    def create(
        self, attempt_id: RuntimeId, harness_factory: Callable[[], HarnessT]
    ) -> HarnessT:
        with self._lock:
            if self._closing:
                raise RuntimeError("runtime supervisor is shutting down")
            if attempt_id in self._active:
                raise ValueError(f"attempt {attempt_id} is already active")
            harness = harness_factory()
            self._active[attempt_id] = _AttemptHandle(harness)
            return harness

    def cancel(self, attempt_id: RuntimeId) -> GatewayCancelResult:
        with self._lock:
            handle = self._active.get(attempt_id)
        if handle is None:
            return GatewayCancelResult(requested=True, runtime_closed=False)
        return GatewayCancelResult(requested=True, runtime_closed=handle.close_once())

    def start(
        self,
        attempt_id: RuntimeId,
        harness: ClosableHarness,
        starter: Callable[[], ResultT],
    ) -> ResultT:
        with self._lock:
            handle = self._active.get(attempt_id)
        if handle is None or handle.harness is not harness:
            raise ValueError(f"attempt {attempt_id} does not own the supplied harness")
        return handle.start_unless_closed(starter)

    def finish(self, attempt_id: RuntimeId, harness: ClosableHarness) -> None:
        with self._lock:
            handle = self._active.get(attempt_id)
        if handle is None or handle.harness is not harness:
            raise ValueError(f"attempt {attempt_id} does not own the supplied harness")
        try:
            handle.close_once()
        finally:
            with self._lock:
                if self._active.get(attempt_id) is handle:
                    del self._active[attempt_id]

    def is_active(self, attempt_id: RuntimeId) -> bool:
        with self._lock:
            return attempt_id in self._active

    def close_all(self) -> None:
        with self._lock:
            self._closing = True
            handles = tuple(self._active.values())
        first_error: BaseException | None = None
        for handle in handles:
            try:
                handle.close_once()
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

from dataclasses import dataclass
from pathlib import Path
from typing import override

from deepseek_harness import DeepSeekHarness, RunResult


@dataclass(frozen=True, slots=True)
class SpikeCancelResult:
    requested: bool
    runtime_closed: bool


class SpikeAttemptHandle:
    def __init__(self, harness: DeepSeekHarness) -> None:
        self._harness = harness
        self._closed = False

    def cancel(self) -> SpikeCancelResult:
        if not self._closed:
            self._harness.close()
            self._closed = True
        return SpikeCancelResult(requested=True, runtime_closed=True)


class _RecordingHarness(DeepSeekHarness):
    def __init__(self, runtime: "RecordingHarnessRuntime") -> None:
        self._runtime = runtime

    @override
    def close(self) -> None:
        self._runtime.close_calls += 1


class RecordingHarnessRuntime:
    """Lifecycle-only test double; it does not execute or persist Sessions."""

    def __init__(self, working_directory: Path) -> None:
        self._working_directory = working_directory
        self.close_calls = 0

    def start(self, session_id: str, prompt: str) -> SpikeAttemptHandle:
        del session_id, prompt
        return SpikeAttemptHandle(_RecordingHarness(self))


class DshSpikeRuntime:
    def __init__(self, *, base_url: str, session_root: Path, working_directory: Path) -> None:
        self._base_url = base_url
        self._session_root = session_root
        self._working_directory = working_directory

    def run(self, session_id: str, prompt: str) -> RunResult:
        with DeepSeekHarness(
            provider="deepseek-official",
            model="dsh-company-spike-model",
            cwd=str(self._working_directory),
            session_root=str(self._session_root),
            base_url=self._base_url,
            api_key="dsh-company-spike-key",
            request_timeout_seconds=20,
            shutdown_timeout_seconds=2,
        ) as harness:
            return harness.run(prompt, session_id=session_id)

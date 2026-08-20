from pathlib import Path

from deepseek_harness import DeepSeekHarness, RunResult


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

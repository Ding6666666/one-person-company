import json
from collections.abc import Mapping
from math import isfinite
from typing import Any, Protocol

from maseval import AgentAdapter
from maseval.core.history import MessageHistory


class CompanyEvaluationClient(Protocol):
    def run_and_wait(
        self, workspace_id: str, strategy: str, objective: str
    ) -> Mapping[str, Any]: ...


_BOOLEAN_METRICS = frozenset(("task_success", "policy_invariants_passed"))
_FLOAT_METRICS = frozenset(("milestone_rate", "acceptance_rate"))
_INTEGER_METRICS = frozenset(
    (
        "token_count",
        "duration_ms",
        "user_interventions",
        "invalid_delegations",
        "duplicate_nodes",
        "policy_violations",
    )
)
_STRING_METRICS = frozenset(("recovery_outcome",))


def _project_metrics(value: object) -> dict[str, bool | float | int | str]:
    if not isinstance(value, Mapping):
        return {}

    projected: dict[str, bool | float | int | str] = {}
    for field in _BOOLEAN_METRICS:
        item = value.get(field)
        if type(item) is bool:
            projected[field] = item
    for field in _FLOAT_METRICS:
        item = value.get(field)
        if type(item) is float and isfinite(item) and 0.0 <= item <= 1.0:
            projected[field] = item
    for field in _INTEGER_METRICS:
        item = value.get(field)
        if type(item) is int and item >= 0:
            projected[field] = item
    for field in _STRING_METRICS:
        item = value.get(field)
        if type(item) is str and item.strip():
            projected[field] = item
    return projected


def _project_summary(summary: Mapping[str, Any]) -> dict[str, object]:
    projected: dict[str, object] = {}
    for field in ("status", "work_id"):
        item = summary.get(field)
        if type(item) is str and item.strip():
            projected[field] = item
    task_success = summary.get("task_success")
    if type(task_success) is bool:
        projected["task_success"] = task_success
    metrics = summary.get("metrics")
    if isinstance(metrics, Mapping):
        projected["metrics"] = _project_metrics(metrics)
    return projected


class CompanyStrategyAgentAdapter(AgentAdapter):
    """Evaluate the complete Company client while retaining only safe system facts."""

    def __init__(
        self,
        client: CompanyEvaluationClient,
        *,
        workspace_id: str,
        strategy: str,
        name: str,
    ) -> None:
        # MASEval 0.5.1 takes the wrapped instance and name positionally.
        super().__init__(client, name)
        self._client = client
        self._workspace_id = workspace_id
        self._strategy = strategy
        self._messages: list[dict[str, str]] = []

    def _run_agent(self, query: str) -> str:
        self._messages.append({"role": "user", "content": query})
        summary = self._client.run_and_wait(self._workspace_id, self._strategy, query)
        safe_summary = _project_summary(summary)
        result = json.dumps(safe_summary, ensure_ascii=False, sort_keys=True)
        self._messages.append({"role": "assistant", "content": result})
        return result

    def get_messages(self) -> MessageHistory:
        return MessageHistory(self._messages)

import json
from typing import Any

from dsh_company.evaluation.maseval_adapter import CompanyStrategyAgentAdapter
from maseval import AgentAdapter
from maseval.core.history import MessageHistory


class FakeCompanyClient:
    def __init__(self, summary: dict[str, Any]) -> None:
        self.summary = summary
        self.calls: list[tuple[str, str, str]] = []

    def run_and_wait(self, workspace_id: str, strategy: str, objective: str) -> dict[str, Any]:
        self.calls.append((workspace_id, strategy, objective))
        return self.summary


def test_maseval_adapter_runs_complete_company_strategy_and_returns_safe_summary() -> None:
    client = FakeCompanyClient(
        {
            "status": "completed",
            "work_id": "work-1",
            "task_success": True,
            "metrics": {"token_count": 321, "duration_ms": 45},
        }
    )
    adapter = CompanyStrategyAgentAdapter(
        client, workspace_id="ws-1", strategy="battle", name="dsh-company-battle"
    )

    result = adapter.run("提出品牌方案")

    assert isinstance(adapter, AgentAdapter)
    assert client.calls == [("ws-1", "battle", "提出品牌方案")]
    assert json.loads(result) == client.summary
    assert isinstance(adapter.get_messages(), MessageHistory)
    assert adapter.get_messages().to_list()[-1]["role"] == "assistant"
    assert "raw_model_output" not in result
    assert "transcript" not in result


def test_adapter_whitelists_system_outcome_instead_of_exposing_model_text() -> None:
    client = FakeCompanyClient(
        {
            "status": "completed",
            "work_id": "work-1",
            "task_success": True,
            "metrics": {
                "task_success": True,
                "milestone_rate": 1.0,
                "acceptance_rate": 0.5,
                "token_count": 321,
                "duration_ms": 45,
                "user_interventions": 0,
                "invalid_delegations": 0,
                "duplicate_nodes": 0,
                "policy_violations": 0,
                "recovery_outcome": "not_required",
                "policy_invariants_passed": True,
                "raw_model_output": "nested private raw text",
                "transcript": [{"role": "assistant", "content": "nested private trace"}],
                "tool_arguments": {"secret": "nested private tool arguments"},
                "duration_ms_object": {"value": 45},
            },
            "raw_model_output": "private raw text",
            "transcript": [{"role": "assistant", "content": "private trace"}],
        }
    )
    adapter = CompanyStrategyAgentAdapter(
        client, workspace_id="ws-1", strategy="direct", name="dsh-company-direct"
    )

    result = adapter.run("完成任务")

    assert json.loads(result) == {
        "metrics": {
            "acceptance_rate": 0.5,
            "duplicate_nodes": 0,
            "duration_ms": 45,
            "invalid_delegations": 0,
            "milestone_rate": 1.0,
            "policy_invariants_passed": True,
            "policy_violations": 0,
            "recovery_outcome": "not_required",
            "task_success": True,
            "token_count": 321,
            "user_interventions": 0,
        },
        "status": "completed",
        "task_success": True,
        "work_id": "work-1",
    }
    assert "private raw text" not in result
    assert "private trace" not in result
    assert "private tool arguments" not in result
    assert adapter.get_messages().to_list()[-1]["content"] == result


def test_adapter_drops_known_metric_fields_with_non_scalar_or_wrong_scalar_types() -> None:
    client = FakeCompanyClient(
        {
            "status": "completed",
            "work_id": "work-1",
            "task_success": True,
            "metrics": {
                "task_success": 1,
                "milestone_rate": {"value": 1.0},
                "token_count": {"tool_arguments": "private arguments"},
                "duration_ms": True,
                "recovery_outcome": ["recovered"],
                "policy_invariants_passed": "true",
            },
        }
    )
    adapter = CompanyStrategyAgentAdapter(
        client, workspace_id="ws-1", strategy="direct", name="dsh-company-direct"
    )

    result = adapter.run("完成任务")

    assert json.loads(result)["metrics"] == {}
    assert "private arguments" not in result


def test_adapter_drops_top_level_fields_with_wrong_types_or_blank_ids() -> None:
    client = FakeCompanyClient(
        {
            "status": ["completed"],
            "work_id": "  ",
            "task_success": 1,
            "metrics": {},
        }
    )
    adapter = CompanyStrategyAgentAdapter(
        client, workspace_id="ws-1", strategy="direct", name="dsh-company-direct"
    )

    result = adapter.run("完成任务")

    assert json.loads(result) == {"metrics": {}}
    assert adapter.get_messages().to_list()[-1]["content"] == result

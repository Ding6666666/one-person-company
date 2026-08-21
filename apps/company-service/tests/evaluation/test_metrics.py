import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from dsh_company.evaluation.models import EvaluationRun, SystemRunOutcome
from dsh_company.evaluation.runner import compute_metrics


def _outcome(**overrides: object) -> SystemRunOutcome:
    values: dict[str, object] = {
        "task_succeeded": True,
        "milestones": (True, True, False),
        "acceptance_checks": (True, False),
        "token_count": 1_200,
        "duration_ms": 800,
        "user_interventions": 1,
        "invalid_delegations": 0,
        "duplicate_nodes": 0,
        "policy_violations": 0,
        "recovery_outcome": "not_required",
    }
    values.update(overrides)
    return SystemRunOutcome(**values)  # type: ignore[arg-type]


def test_metrics_compare_complete_system_outcomes() -> None:
    metrics = compute_metrics(_outcome())

    assert metrics.task_success is True
    assert metrics.milestone_rate == pytest.approx(2 / 3)
    assert metrics.acceptance_rate == pytest.approx(1 / 2)
    assert metrics.token_count == 1_200
    assert metrics.duration_ms == 800
    assert metrics.user_interventions == 1
    assert metrics.invalid_delegations == 0
    assert metrics.duplicate_nodes == 0
    assert metrics.policy_violations == 0
    assert metrics.policy_invariants_passed is True
    assert metrics.recovery_outcome == "not_required"


def test_policy_invariants_fail_for_any_system_policy_defect() -> None:
    metrics = compute_metrics(_outcome(invalid_delegations=1))

    assert metrics.policy_invariants_passed is False


def test_empty_milestone_and_acceptance_sets_have_zero_rates() -> None:
    metrics = compute_metrics(_outcome(milestones=(), acceptance_checks=()))

    assert metrics.milestone_rate == 0.0
    assert metrics.acceptance_rate == 0.0


def test_evaluation_run_keeps_benchmark_metadata_outside_production_models() -> None:
    started_at = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    ended_at = datetime(2026, 8, 21, 8, 1, tzinfo=UTC)
    metrics = compute_metrics(_outcome())

    run = EvaluationRun(
        task_set_version="company-v1",
        strategy="battle",
        model="keyless-deterministic",
        employee_revisions=("revision-a", "revision-b"),
        runtime_profiles=("workspace-read",),
        started_at=started_at,
        ended_at=ended_at,
        work_id="work-1",
        metrics=metrics,
    )

    assert run.task_set_version == "company-v1"
    assert run.metrics == metrics
    assert run.to_dict() == {
        "employee_revisions": ["revision-a", "revision-b"],
        "ended_at": "2026-08-21T08:01:00+00:00",
        "metrics": {
            "acceptance_rate": 0.5,
            "duplicate_nodes": 0,
            "duration_ms": 800,
            "invalid_delegations": 0,
            "milestone_rate": pytest.approx(2 / 3),
            "policy_invariants_passed": True,
            "policy_violations": 0,
            "recovery_outcome": "not_required",
            "task_success": True,
            "token_count": 1_200,
            "user_interventions": 1,
        },
        "model": "keyless-deterministic",
        "runtime_profiles": ["workspace-read"],
        "started_at": "2026-08-21T08:00:00+00:00",
        "strategy": "battle",
        "task_set_version": "company-v1",
        "work_id": "work-1",
    }


def test_evaluation_run_projection_preserves_corresponding_metadata_order() -> None:
    now = datetime(2026, 8, 21, tzinfo=UTC)
    run = EvaluationRun(
        task_set_version="company-v1",
        strategy="battle",
        model="keyless",
        employee_revisions=("revision-b", "revision-a"),
        runtime_profiles=("write", "read"),
        started_at=now,
        ended_at=now,
        work_id="work-1",
        metrics=compute_metrics(_outcome()),
    )

    projection = run.to_dict()

    assert projection["employee_revisions"] == ["revision-b", "revision-a"]
    assert projection["runtime_profiles"] == ["write", "read"]
    json.dumps(projection)


@pytest.mark.parametrize("field", ["task_set_version", "strategy", "model", "work_id"])
def test_evaluation_run_rejects_blank_identity_fields(field: str) -> None:
    values = {
        "task_set_version": "company-v1",
        "strategy": "direct",
        "model": "keyless",
        "employee_revisions": ("revision-a",),
        "runtime_profiles": ("read",),
        "started_at": datetime(2026, 8, 21, tzinfo=UTC),
        "ended_at": datetime(2026, 8, 21, tzinfo=UTC),
        "work_id": "work-1",
        "metrics": compute_metrics(_outcome()),
    }
    values[field] = "  "

    with pytest.raises(ValueError, match=field):
        EvaluationRun(**values)  # type: ignore[arg-type]


def test_evaluation_run_requires_aware_ordered_timestamps() -> None:
    now = datetime(2026, 8, 21, tzinfo=UTC)
    common = {
        "task_set_version": "company-v1",
        "strategy": "direct",
        "model": "keyless",
        "employee_revisions": ("revision-a",),
        "runtime_profiles": ("read",),
        "work_id": "work-1",
        "metrics": compute_metrics(_outcome()),
    }

    with pytest.raises(ValueError, match="timezone-aware"):
        EvaluationRun(
            **common,
            started_at=datetime(2026, 8, 21),
            ended_at=datetime(2026, 8, 21),
        )
    with pytest.raises(ValueError, match="ended_at"):
        EvaluationRun(
            **common,
            started_at=now,
            ended_at=now - timedelta(seconds=1),
        )


def test_evaluation_run_accepts_non_utc_aware_timestamps() -> None:
    zone = timezone(timedelta(hours=8))
    now = datetime(2026, 8, 21, tzinfo=zone)
    run = EvaluationRun(
        task_set_version="company-v1",
        strategy="direct",
        model="keyless",
        employee_revisions=("revision-a",),
        runtime_profiles=("read",),
        started_at=now,
        ended_at=now,
        work_id="work-1",
        metrics=compute_metrics(_outcome()),
    )

    projected_start = run.to_dict()["started_at"]
    assert isinstance(projected_start, str)
    assert projected_start.endswith("+08:00")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("token_count", -1),
        ("duration_ms", -1),
        ("user_interventions", -1),
        ("invalid_delegations", -1),
        ("duplicate_nodes", -1),
        ("policy_violations", -1),
    ],
)
def test_system_counters_cannot_be_negative(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=field):
        _outcome(**{field: value})


@pytest.mark.parametrize("value", [True, 1.0])
def test_system_counters_require_exact_integers(value: object) -> None:
    with pytest.raises(ValueError, match="token_count"):
        _outcome(token_count=value)


def test_system_check_sequences_require_exact_booleans() -> None:
    with pytest.raises(ValueError, match="milestones"):
        _outcome(milestones=(True, 2))
    with pytest.raises(ValueError, match="acceptance_checks"):
        _outcome(acceptance_checks=(True, 1))


def test_evaluation_metrics_validate_rates_and_recovery_outcome() -> None:
    metrics = compute_metrics(_outcome())

    with pytest.raises(ValueError, match="milestone_rate"):
        replace(metrics, milestone_rate=float("nan"))
    with pytest.raises(ValueError, match="acceptance_rate"):
        replace(metrics, acceptance_rate=1.1)
    with pytest.raises(ValueError, match="recovery_outcome"):
        replace(metrics, recovery_outcome="  ")
    with pytest.raises(ValueError, match="token_count"):
        replace(metrics, token_count=True)
    with pytest.raises(ValueError, match="duration_ms"):
        replace(metrics, duration_ms=1.0)  # type: ignore[arg-type]


def test_company_v1_task_fixtures_have_consistent_fields_and_approval_budget() -> None:
    task_file = Path(__file__).parents[4] / "benchmarks" / "company" / "tasks.jsonl"
    rows = [json.loads(line) for line in task_file.read_text(encoding="utf-8").splitlines()]
    expected_fields = {
        "task_id",
        "family",
        "objective",
        "acceptance_checks",
        "allowed_strategies",
        "max_tokens",
        "max_duration_ms",
        "max_user_interventions",
    }

    assert len(rows) == 7
    assert all(set(row) == expected_fields for row in rows)
    approval = next(row for row in rows if row["family"] == "approval_allow_reject")
    assert approval["max_user_interventions"] == 2

from .models import EvaluationMetrics, SystemRunOutcome


def _rate(checks: tuple[bool, ...]) -> float:
    return sum(checks) / len(checks) if checks else 0.0


def compute_metrics(outcome: SystemRunOutcome) -> EvaluationMetrics:
    """Project comparable system metrics from one complete Company run."""

    policy_invariants_passed = (
        outcome.invalid_delegations == 0
        and outcome.duplicate_nodes == 0
        and outcome.policy_violations == 0
    )
    return EvaluationMetrics(
        task_success=outcome.task_succeeded,
        milestone_rate=_rate(outcome.milestones),
        acceptance_rate=_rate(outcome.acceptance_checks),
        token_count=outcome.token_count,
        duration_ms=outcome.duration_ms,
        user_interventions=outcome.user_interventions,
        invalid_delegations=outcome.invalid_delegations,
        duplicate_nodes=outcome.duplicate_nodes,
        policy_violations=outcome.policy_violations,
        policy_invariants_passed=policy_invariants_passed,
        recovery_outcome=outcome.recovery_outcome,
    )

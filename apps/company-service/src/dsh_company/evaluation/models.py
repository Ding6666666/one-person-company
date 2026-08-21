from dataclasses import dataclass
from datetime import datetime
from math import isfinite

_COUNTER_FIELDS = (
    "token_count",
    "duration_ms",
    "user_interventions",
    "invalid_delegations",
    "duplicate_nodes",
    "policy_violations",
)


def _require_nonblank_string(value: object, field_name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be a nonblank string")


def _require_counter(value: object, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a nonnegative integer")


@dataclass(frozen=True, slots=True)
class SystemRunOutcome:
    """Closed system facts used to compare complete Company executions."""

    task_succeeded: bool
    milestones: tuple[bool, ...]
    acceptance_checks: tuple[bool, ...]
    token_count: int
    duration_ms: int
    user_interventions: int
    invalid_delegations: int
    duplicate_nodes: int
    policy_violations: int
    recovery_outcome: str

    def __post_init__(self) -> None:
        if type(self.task_succeeded) is not bool:
            raise ValueError("task_succeeded must be a boolean")
        if any(type(item) is not bool for item in self.milestones):
            raise ValueError("milestones must contain only booleans")
        if any(type(item) is not bool for item in self.acceptance_checks):
            raise ValueError("acceptance_checks must contain only booleans")
        for field_name in _COUNTER_FIELDS:
            _require_counter(getattr(self, field_name), field_name)
        _require_nonblank_string(self.recovery_outcome, "recovery_outcome")


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    task_success: bool
    milestone_rate: float
    acceptance_rate: float
    token_count: int
    duration_ms: int
    user_interventions: int
    invalid_delegations: int
    duplicate_nodes: int
    policy_violations: int
    policy_invariants_passed: bool
    recovery_outcome: str

    def __post_init__(self) -> None:
        if type(self.task_success) is not bool:
            raise ValueError("task_success must be a boolean")
        for field_name in ("milestone_rate", "acceptance_rate"):
            value = getattr(self, field_name)
            if type(value) is not float or not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be a finite rate from 0 to 1")
        for field_name in _COUNTER_FIELDS:
            _require_counter(getattr(self, field_name), field_name)
        if type(self.policy_invariants_passed) is not bool:
            raise ValueError("policy_invariants_passed must be a boolean")
        _require_nonblank_string(self.recovery_outcome, "recovery_outcome")

    def to_dict(self) -> dict[str, bool | float | int | str]:
        return dict(
            sorted(
                {
                    "task_success": self.task_success,
                    "milestone_rate": self.milestone_rate,
                    "acceptance_rate": self.acceptance_rate,
                    "token_count": self.token_count,
                    "duration_ms": self.duration_ms,
                    "user_interventions": self.user_interventions,
                    "invalid_delegations": self.invalid_delegations,
                    "duplicate_nodes": self.duplicate_nodes,
                    "policy_violations": self.policy_violations,
                    "policy_invariants_passed": self.policy_invariants_passed,
                    "recovery_outcome": self.recovery_outcome,
                }.items()
            )
        )


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    """Serializable benchmark metadata; this is not a production persistence model."""

    task_set_version: str
    strategy: str
    model: str
    employee_revisions: tuple[str, ...]
    runtime_profiles: tuple[str, ...]
    started_at: datetime
    ended_at: datetime
    work_id: str
    metrics: EvaluationMetrics

    def __post_init__(self) -> None:
        for field_name in ("task_set_version", "strategy", "model", "work_id"):
            _require_nonblank_string(getattr(self, field_name), field_name)
        for field_name in ("employee_revisions", "runtime_profiles"):
            values = getattr(self, field_name)
            if type(values) is not tuple or any(
                type(item) is not str or not item.strip() for item in values
            ):
                raise ValueError(f"{field_name} must contain frozen nonblank strings")
        if (
            not isinstance(self.started_at, datetime)
            or not isinstance(self.ended_at, datetime)
            or self.started_at.utcoffset() is None
            or self.ended_at.utcoffset() is None
        ):
            raise ValueError("started_at and ended_at must be timezone-aware")
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        if not isinstance(self.metrics, EvaluationMetrics):
            raise ValueError("metrics must be EvaluationMetrics")

    def to_dict(self) -> dict[str, object]:
        return dict(
            sorted(
                {
                    "task_set_version": self.task_set_version,
                    "strategy": self.strategy,
                    "model": self.model,
                    "employee_revisions": list(self.employee_revisions),
                    "runtime_profiles": list(self.runtime_profiles),
                    "started_at": self.started_at.isoformat(),
                    "ended_at": self.ended_at.isoformat(),
                    "work_id": self.work_id,
                    "metrics": self.metrics.to_dict(),
                }.items()
            )
        )

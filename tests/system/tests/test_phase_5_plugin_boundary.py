import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from dsh_company.business_plugins.registry import BusinessPluginRegistry
from dsh_company.domain.ids import WorkNodeId
from dsh_company.domain.policy import PolicyEngine
from dsh_company.evaluation.fixed_set import replay_fixed_task_set
from dsh_company.foundation.app import create_app
from dsh_company.foundation.assembly import ComponentAssembly
from dsh_company.orchestration.durable_graph import DurableGraphEngine
from dsh_company.persistence.database import create_sqlite_engine, create_tables
from dsh_company.persistence.uow import SqlAlchemyUnitOfWork
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

ROOT = Path(__file__).parents[3]


class RecordingCoordinator:
    def __init__(self) -> None:
        self.enqueued: list[WorkNodeId] = []

    def enqueue(self, node_id: WorkNodeId) -> None:
        self.enqueued.append(node_id)

    def request_cancel(self, node_id: WorkNodeId) -> None:
        del node_id


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    value = create_sqlite_engine(tmp_path / "phase-5-plugin.db")
    create_tables(value)
    yield value
    value.dispose()


def test_reference_plugin_uses_only_public_declarative_boundary(engine: Engine) -> None:
    factory = lambda: SqlAlchemyUnitOfWork(engine)  # noqa: E731
    registry = BusinessPluginRegistry(factory)
    coordinator = RecordingCoordinator()
    graph = DurableGraphEngine(
        factory,
        coordinator,
        policy_engine=PolicyEngine(registry.action_catalog),
    )
    assembly = ComponentAssembly(uow_factory=factory, orchestration_engine=graph)
    manifest = json.loads(
        (ROOT / "examples/content-studio-plugin/manifest.json").read_text(encoding="utf-8")
    )
    with TestClient(create_app(assembly=assembly), raise_server_exceptions=False) as client:
        registration = client.post("/business-plugins/register", json=manifest)
        registration.raise_for_status()
        workspace = client.post("/workspaces", json={"name": "Plugin boundary"}).json()
        action_grant = {
            "action": "content-studio.publish_draft",
            "level": 3,
            "resource_kind": "content",
            "resource_values": ["draft"],
            "requires_approval": False,
        }
        employees: list[dict[str, object]] = []
        for slot in ("researcher", "writer", "reviewer", "summarizer"):
            employee = client.post(
                f"/workspaces/{workspace['id']}/employees",
                json={
                    "display_name": slot,
                    "responsibility": slot,
                    "runtime_profile": (
                        "workspace_write" if slot == "summarizer" else "workspace_read"
                    ),
                    "model": "keyless-system-model",
                    "grants": [action_grant] if slot == "summarizer" else [],
                },
            )
            employee.raise_for_status()
            employees.append(employee.json())
        assert (
            client.put(
                f"/workspaces/{workspace['id']}/capabilities",
                json={"grants": [action_grant]},
            ).status_code
            == 200
        )
        instantiated = client.post(
            f"/workspaces/{workspace['id']}/templates/content-studio/"
            "research-write-review-summary/instantiate",
            json={
                "command_id": "reference-plugin-system",
                "employee_assignments": {
                    slot: employee["id"]
                    for slot, employee in zip(
                        ("researcher", "writer", "reviewer", "summarizer"),
                        employees,
                        strict=True,
                    )
                },
            },
        )

        assert instantiated.status_code == 202
        assert len(instantiated.json()["nodes"]) == 4
        assert [item["plugin_id"] for item in client.get("/business-plugins").json()] == [
            "content-studio"
        ]
        assert (
            BusinessPluginRegistry(factory).action_catalog().level("content-studio.publish_draft")
            == 3
        )
        override = dict(manifest)
        override["plugin_id"] = "workspace"
        override["capability_actions"] = [{"action": "workspace.write", "level": 2}]
        assert client.post("/business-plugins/register", json=override).status_code == 409

    public_files = (
        ROOT / "examples/content-studio-plugin/manifest.json",
        ROOT / "examples/content-studio-plugin/README.md",
        ROOT / "packages/company-plugin-sdk/src/index.ts",
    )
    forbidden = ("dsh_company.persistence", "sqlalchemy", "deepseek_harness", "crewai")
    assert all(
        marker not in path.read_text(encoding="utf-8").lower()
        for path in public_files
        for marker in forbidden
    )


def test_fixed_baseline_covers_every_allowed_task_without_raw_content() -> None:
    tasks = [
        json.loads(line)
        for line in (ROOT / "benchmarks/company/tasks.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    baseline = json.loads(
        (ROOT / "benchmarks/company/baseline-results.json").read_text(encoding="utf-8")
    )
    expected_pairs = {
        (task["task_id"], strategy) for task in tasks for strategy in task["allowed_strategies"]
    }
    runs = baseline["runs"]

    assert baseline["task_set_version"] == "company-v1"
    assert baseline["dsh_revision"] == "2db6ebd58523d14dca278e366ea0eb40499702b9"
    assert baseline["company_commit"] == "4a2f37fc7dd4e4589d25a26a40e1cdf200e08ff7"
    assert {(run["task_id"], run["strategy"]) for run in runs} == expected_pairs
    task_by_id = {task["task_id"]: task for task in tasks}
    for run in runs:
        budget = task_by_id[run["task_id"]]
        metrics = run["metrics"]
        assert metrics["token_count"] <= budget["max_tokens"]
        assert metrics["duration_ms"] <= budget["max_duration_ms"]
        assert metrics["user_interventions"] <= budget["max_user_interventions"]
        assert metrics["policy_invariants_passed"] is True
        assert metrics["duplicate_nodes"] == 0
        assert metrics["policy_violations"] == 0

    serialized = json.dumps(baseline, ensure_ascii=False).lower()
    assert all(
        marker not in serialized
        for marker in (
            "raw_model_output",
            "transcript",
            "prompt",
            "tool_arguments",
            "checksum",
            "sha256",
        )
    )
    assert not list((ROOT / "benchmarks/company").glob("*.sha*"))


def test_fixed_baseline_matches_all_live_keyless_company_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DSH_RUNTIME_MODE", "node")
    replay = replay_fixed_task_set(ROOT / "benchmarks/company/tasks.jsonl", tmp_path / "fixed-set")
    baseline = json.loads(
        (ROOT / "benchmarks/company/baseline-results.json").read_text(encoding="utf-8")
    )
    live_by_pair = {(run["task_id"], run["strategy"]): run for run in replay["runs"]}

    assert len(live_by_pair) == 14
    assert all(run["work_id"].startswith("work-") for run in replay["runs"])
    assert all(run["status"] in {"completed", "failed", "blocked"} for run in replay["runs"])
    request_coverage = [
        (
            run["task_id"],
            run["strategy"],
            run["model_request_count"],
            run["attempt_count"],
        )
        for run in replay["runs"]
    ]
    ordinary_task_ids = {
        "company-v1-direct-completion",
        "company-v1-parallel-battle",
        "company-v1-dependency-chain",
        "company-v1-session-isolation",
    }
    assert all(
        model_requests == attempts
        for task_id, _, model_requests, attempts in request_coverage
        if task_id in ordinary_task_ids
    ), request_coverage
    assert all(
        model_requests == attempts * 3
        for task_id, _, model_requests, attempts in request_coverage
        if task_id == "company-v1-endpoint-unavailable"
    ), request_coverage
    assert all(run["model_request_count"] > 0 for run in replay["runs"])
    for expected in baseline["runs"]:
        live = live_by_pair[(expected["task_id"], expected["strategy"])]
        assert live["status"] == expected["status"]
        assert {key: value for key, value in live["metrics"].items() if key != "duration_ms"} == {
            key: value for key, value in expected["metrics"].items() if key != "duration_ms"
        }
        assert live["metrics"]["policy_invariants_passed"] is True
        assert live["metrics"]["duration_ms"] <= live["max_duration_ms"]

    successful_battles = [
        run
        for run in replay["runs"]
        if run["strategy"] == "battle" and run["status"] == "completed"
    ]
    assert successful_battles
    assert all(run["metrics"]["token_count"] >= 24 for run in successful_battles)
    unavailable = [
        run for run in replay["runs"] if run["task_id"] == "company-v1-endpoint-unavailable"
    ]
    assert len(unavailable) == 4
    assert all(run["status"] != "completed" for run in unavailable)
    assert all(run["metrics"]["token_count"] == 0 for run in unavailable)
    assert all(run["metrics"]["task_success"] is True for run in unavailable)
    assert all(run["metrics"]["recovery_outcome"] == "endpoint_unavailable" for run in unavailable)
    shutil.rmtree(tmp_path / "fixed-set")
    assert not (tmp_path / "fixed-set").exists()


def test_fixed_set_checks_are_projected_from_real_family_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DSH_RUNTIME_MODE", "node")
    replay = replay_fixed_task_set(
        ROOT / "benchmarks/company/tasks.jsonl", tmp_path / "semantic-fixed-set"
    )
    runs = {(run["task_id"], run["strategy"]): run for run in replay["runs"]}

    direct = runs[("company-v1-direct-completion", "direct")]
    assert direct["facts"]["completed"] is True
    assert direct["facts"]["node_count"] == 1
    assert direct["facts"]["safe_projection_fields_present"] is True

    battle = runs[("company-v1-parallel-battle", "battle")]
    assert battle["facts"]["participant_node_count"] == 2
    assert battle["facts"]["summary_node_count"] == 1
    assert battle["facts"]["summary_depends_on_all_participants"] is True

    dependency = runs[("company-v1-dependency-chain", "graph")]
    assert dependency["facts"]["downstream_not_ready_before_upstream_completion"] is True
    assert dependency["facts"]["completed_node_count"] == 2
    assert dependency["facts"]["graph_facts_unchanged"] is True

    approval = runs[("company-v1-approval-allow-reject", "graph")]
    assert approval["facts"]["preapproval_model_request_count"] == 0
    assert approval["facts"]["approved_status"] == "completed"
    assert approval["facts"]["rejected_failure_code"] == "approval_rejected"
    assert approval["metrics"]["user_interventions"] == 2

    recovery = runs[("company-v1-restart-recovery", "graph")]
    assert recovery["facts"]["lost_failure_code"] == "runtime_process_lost"
    assert recovery["facts"]["graph_facts_unchanged"] is True
    assert recovery["facts"]["attempt_ids_distinct"] is True
    assert recovery["facts"]["retry_terminal_status"] in {"blocked", "failed"}
    assert recovery["facts"]["retry_terminal_non_completed"] is True
    assert recovery["facts"]["retry_failure_code_closed"] is True
    assert recovery["facts"]["retry_request_pattern_valid"] is True
    assert (
        recovery["metrics"]["recovery_outcome"]
        == "runtime_process_lost_retry_not_completed"
    )

    isolation = runs[("company-v1-session-isolation", "battle")]
    assert isolation["facts"]["distinct_session_ids"] is True
    assert isolation["facts"]["exact_node_attempt_mapping"] is True
    assert isolation["facts"]["exact_employee_revision_binding"] is True
    assert isolation["facts"]["isolated_employee_node_events"] is True
    assert isolation["facts"]["artifact_result_ownership"] is True
    assert isolation["facts"]["isolated_model_markers"] is True
    assert isolation["facts"]["swapped_mapping_rejected"] is True

    unavailable = runs[("company-v1-endpoint-unavailable", "battle")]
    assert unavailable["facts"]["not_completed"] is True
    assert unavailable["facts"]["stable_diagnostic_code"] is True
    assert unavailable["facts"]["persisted_attempt_facts"] is True

    for run in replay["runs"]:
        assert [item["name"] for item in run["acceptance_checks"]]
        assert all(item["passed"] is True for item in run["acceptance_checks"])


def test_migration_history_has_the_real_phase_5_head() -> None:
    config = Config(str(ROOT / "apps/company-service/alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert script.get_current_head() == "0009_employee_system_prompt"


def test_contract_snapshot_matches_its_recorded_api_revision() -> None:
    contract_root = ROOT / "packages/contracts/openapi"
    revision = json.loads(
        (contract_root / "source-revision.json").read_text(encoding="utf-8")
    )["api_commit"]
    recorded = subprocess.run(
        ["git", "show", f"{revision}:packages/contracts/openapi/openapi.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    recorded_snapshot = json.loads(recorded.stdout)
    committed_snapshot = json.loads(
        (contract_root / "openapi.json").read_text(encoding="utf-8")
    )

    plugin_paths = {
        "/business-plugins",
        "/business-plugins/register",
        "/business-plugins/{plugin_id}/templates",
        "/workspaces/{workspace_id}/templates/{plugin_id}/{template_id}/instantiate",
    }
    assert plugin_paths <= committed_snapshot["paths"].keys()
    assert recorded_snapshot == committed_snapshot

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dsh_company.application.runtime_coordinator import RuntimeCoordinator
from dsh_company.dsh_gateway.keyless_endpoint import KeylessModelEndpoint, ModelRequest
from dsh_company.foundation.app import create_app
from dsh_company.foundation.config import Settings

from .models import SystemRunOutcome
from .runner import compute_metrics

_TERMINAL = frozenset({"completed", "failed", "blocked", "cancelled"})
_TOKENS_PER_SUCCESSFUL_CALL = 8


@dataclass(frozen=True, slots=True)
class _Scenario:
    work: dict[str, Any]
    works: tuple[dict[str, Any], ...]
    facts: dict[str, bool | int | str]
    checks: tuple[bool, ...]
    user_interventions: int = 0
    recovery_outcome: str = "not_required"
    unsuccessful_model_requests: int = 0


def _wait_for_terminal(
    client: TestClient, work_id: str, *, timeout_seconds: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"/works/{work_id}")
        response.raise_for_status()
        work = response.json()
        if work["status"] in _TERMINAL:
            assembly = cast(FastAPI, client.app).state.assembly
            coordinator = assembly.work_coordinator
            if not isinstance(coordinator, RuntimeCoordinator):
                raise RuntimeError(
                    "fixed-set production assembly has no runtime coordinator"
                )
            if not coordinator.wait_for_idle(
                timeout_seconds=deadline - time.monotonic()
            ):
                break
            settled_response = client.get(f"/works/{work_id}")
            settled_response.raise_for_status()
            settled = settled_response.json()
            if settled["status"] in _TERMINAL:
                return settled
        time.sleep(0.02)
    raise TimeoutError(f"fixed-set work {work_id} exceeded its declared budget")


def _employee(
    client: TestClient,
    workspace_id: str,
    label: str,
    marker: str,
    *,
    grants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    response = client.post(
        f"/workspaces/{workspace_id}/employees",
        json={
            "display_name": label,
            "responsibility": f"remember {marker}\nExecute one deterministic fixed-set node",
            "runtime_profile": "workspace_read",
            "model": "keyless-system-model",
            "grants": grants or [],
        },
    )
    response.raise_for_status()
    return response.json()


def _payload(
    strategy: str,
    *,
    task_id: str,
    objective: str,
    criteria: list[str],
    employees: list[dict[str, Any]],
    command_suffix: str = "main",
) -> dict[str, Any]:
    marker = f"remember FIXED_SET_{task_id}_{strategy}_{command_suffix}"
    common: dict[str, Any] = {
        "kind": strategy,
        "objective": f"{marker}\n{objective}",
        "acceptance_criteria": criteria,
        "command_id": f"fixed-set:{task_id}:{strategy}:{command_suffix}",
    }
    if strategy == "direct":
        return {**common, "employee_id": employees[0]["id"]}
    if strategy == "star":
        return {
            **common,
            "coordinator_employee_id": employees[0]["id"],
            "children": [
                {
                    "employee_id": employees[1]["id"],
                    "objective": marker,
                    "acceptance_criteria": criteria,
                }
            ],
        }
    if strategy == "graph":
        return {
            **common,
            "nodes": [
                {
                    "key": "first",
                    "employee_id": employees[0]["id"],
                    "objective": marker,
                    "acceptance_criteria": criteria,
                },
                {
                    "key": "second",
                    "employee_id": employees[1]["id"],
                    "objective": marker,
                    "acceptance_criteria": criteria,
                },
            ],
            "edges": [{"from_key": "first", "to_key": "second", "kind": "depends_on"}],
        }
    if strategy == "battle":
        return {
            **common,
            "participant_employee_ids": [employees[0]["id"], employees[1]["id"]],
            "summarizer_employee_id": employees[2]["id"],
        }
    raise ValueError(f"unsupported fixed-set strategy: {strategy}")


def _post_work(client: TestClient, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"/workspaces/{workspace_id}/works", json=payload)
    response.raise_for_status()
    return response.json()


def _terminal_work(
    client: TestClient,
    workspace_id: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    created = _post_work(client, workspace_id, payload)
    return _wait_for_terminal(client, created["id"], timeout_seconds=timeout_seconds)


def _edge_facts(work: dict[str, Any]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted((edge["from_node_id"], edge["to_node_id"], edge["kind"]) for edge in work["edges"])
    )


def _isolation_facts(
    work: dict[str, Any],
    employees: list[dict[str, Any]],
    events: list[dict[str, Any]],
    requests: list[ModelRequest],
) -> dict[str, bool | int | str]:
    employee_by_id = {employee["id"]: employee for employee in employees}
    links_by_node: dict[str, list[dict[str, Any]]] = {}
    for link in work["execution_links"]:
        links_by_node.setdefault(link["node_id"], []).append(link)
    exact_links = all(
        len(links_by_node.get(node["id"], [])) == 1 for node in work["nodes"]
    ) and set(links_by_node) == {node["id"] for node in work["nodes"]}
    artifacts_by_uri = {artifact["uri"] for artifact in work["artifacts"]}
    exact_employees = True
    exact_events = True
    artifact_ownership = True
    exact_markers = True
    expected_markers: set[str] = set()
    for node in work["nodes"]:
        employee = employee_by_id.get(node["assigned_employee_id"])
        node_links = links_by_node.get(node["id"], [])
        if employee is None or len(node_links) != 1:
            exact_employees = False
            exact_events = False
            artifact_ownership = False
            exact_markers = False
            continue
        link = node_links[0]
        revision = employee["revision"]
        binding = employee["binding"]
        exact_employees = exact_employees and (
            revision["employee_id"] == employee["id"]
            and binding["employee_id"] == employee["id"]
            and node["employee_revision_id"] == revision["id"]
        )
        matching_events = [
            event
            for event in events
            if event["node_id"] == node["id"]
            and event["attempt_id"] == link["attempt_id"]
        ]
        exact_events = exact_events and bool(matching_events)
        expected_uri = (
            f"dsh-session://{binding['dsh_session_id']}/attempt/"
            f"{link['attempt_id']}/result"
        )
        artifact_ownership = artifact_ownership and expected_uri in artifacts_by_uri
        marker = revision["responsibility"].splitlines()[0]
        expected_markers.add(marker)
        exact_markers = exact_markers and sum(
            request.marker == marker for request in requests
        ) == 1
    linked_attempt_nodes = {
        link["attempt_id"]: link["node_id"] for link in work["execution_links"]
    }
    exact_events = exact_events and all(
        event["attempt_id"] is None
        or (
            event["attempt_id"] in linked_attempt_nodes
            and event["node_id"] == linked_attempt_nodes[event["attempt_id"]]
        )
        for event in events
    )
    exact_markers = exact_markers and {
        request.marker for request in requests
    } == expected_markers
    session_ids = {
        employee_by_id[node["assigned_employee_id"]]["binding"]["dsh_session_id"]
        for node in work["nodes"]
        if node["assigned_employee_id"] in employee_by_id
    }
    return {
        "assigned_employee_count": len({node["assigned_employee_id"] for node in work["nodes"]}),
        "distinct_session_ids": len(session_ids) == len(work["nodes"]),
        "exact_node_attempt_mapping": exact_links,
        "exact_employee_revision_binding": exact_employees,
        "isolated_employee_node_events": exact_events,
        "artifact_result_ownership": artifact_ownership,
        "isolated_model_markers": exact_markers,
        "duplicate_node_count": len(work["nodes"])
        - len({node["id"] for node in work["nodes"]}),
    }


def _ordinary_scenario(
    client: TestClient,
    endpoint: KeylessModelEndpoint,
    task: dict[str, Any],
    strategy: str,
    workspace_id: str,
    employees: list[dict[str, Any]],
) -> _Scenario:
    family = task["family"]
    payload = _payload(
        strategy,
        task_id=task["task_id"],
        objective=task["objective"],
        criteria=task["acceptance_checks"],
        employees=employees,
    )
    timeout = task["max_duration_ms"] / 1000
    if family == "dependency_chain":
        first_employee = employees[1] if strategy == "star" else employees[0]
        first_marker = first_employee["revision"]["responsibility"].splitlines()[0]
        hold = endpoint.hold(first_marker)
        created = _post_work(client, workspace_id, payload)
        if not hold.request_started.wait(timeout=10):
            raise TimeoutError("dependency-chain upstream did not enter the model endpoint")
        interim = client.get(f"/works/{created['id']}").json()
        initial_edges = _edge_facts(interim)
        by_id = {node["id"]: node for node in interim["nodes"]}
        downstream_ids = {edge["to_node_id"] for edge in interim["edges"]}
        downstream_not_ready = all(
            by_id[node_id]["status"] == "draft" for node_id in downstream_ids
        )
        hold.release_response.set()
        terminal = _wait_for_terminal(client, created["id"], timeout_seconds=timeout)
        edges_unchanged = _edge_facts(terminal) == initial_edges
        all_completed = all(node["status"] == "completed" for node in terminal["nodes"])
        facts: dict[str, bool | int | str] = {
            "downstream_not_ready_before_upstream_completion": downstream_not_ready,
            "completed_node_count": sum(
                node["status"] == "completed" for node in terminal["nodes"]
            ),
            "graph_facts_unchanged": edges_unchanged,
        }
        return _Scenario(
            terminal,
            (terminal,),
            facts,
            (downstream_not_ready, all_completed, edges_unchanged),
        )

    requests_before = len(endpoint.requests)
    terminal = _terminal_work(client, workspace_id, payload, timeout)
    node_ids = [node["id"] for node in terminal["nodes"]]
    if family == "direct_single_employee_completion":
        checks = (
            terminal["status"] == "completed",
            len(node_ids) == 1,
            all(key in terminal for key in ("status", "nodes", "execution_links", "artifacts")),
        )
        facts = {
            "completed": checks[0],
            "node_count": len(node_ids),
            "safe_projection_fields_present": checks[2],
        }
    elif family == "parallel_research_content_battle":
        summary_ids = {edge["to_node_id"] for edge in terminal["edges"]}
        participant_ids = {edge["from_node_id"] for edge in terminal["edges"]}
        summary_depends_all = (
            len(summary_ids) == 1
            and len(participant_ids) == 2
            and len(terminal["edges"]) == len(participant_ids)
            and all(edge["kind"] == "summarizes" for edge in terminal["edges"])
        )
        checks = (
            2 <= len(participant_ids) <= 4,
            len(summary_ids) == 1,
            summary_depends_all,
        )
        facts = {
            "participant_node_count": len(participant_ids),
            "summary_node_count": len(summary_ids),
            "summary_depends_on_all_participants": summary_depends_all,
        }
    elif family == "two_employee_session_isolation":
        events_response = client.get(f"/works/{terminal['id']}/events")
        events_response.raise_for_status()
        events = events_response.json()
        current_requests = endpoint.requests[requests_before:]
        facts = _isolation_facts(terminal, employees, events, current_requests)
        swapped_employees = [dict(employee) for employee in employees]
        assigned_ids = [node["assigned_employee_id"] for node in terminal["nodes"]]
        if len(assigned_ids) >= 2:
            first = next(
                index
                for index, item in enumerate(swapped_employees)
                if item["id"] == assigned_ids[0]
            )
            second = next(
                index
                for index, item in enumerate(swapped_employees)
                if item["id"] == assigned_ids[1]
            )
            swapped_employees[first]["binding"] = employees[second]["binding"]
            swapped_employees[second]["binding"] = employees[first]["binding"]
        swapped_rejected = not all(
            value
            for key, value in _isolation_facts(
                terminal, swapped_employees, events, current_requests
            ).items()
            if key
            in {
                "exact_employee_revision_binding",
                "artifact_result_ownership",
                "isolated_model_markers",
            }
        )
        checks = (
            bool(facts["distinct_session_ids"])
            and int(facts["assigned_employee_count"]) >= 2,
            all(
                facts[key]
                for key in (
                    "exact_node_attempt_mapping",
                    "exact_employee_revision_binding",
                    "isolated_employee_node_events",
                    "artifact_result_ownership",
                    "isolated_model_markers",
                )
            ),
            int(facts["duplicate_node_count"]) == 0 and swapped_rejected,
        )
        facts["swapped_mapping_rejected"] = swapped_rejected
    else:
        stable_codes = {node["failure_code"] for node in terminal["nodes"] if node["failure_code"]}
        persisted = client.get(f"/works/{terminal['id']}").json()
        persisted_retry_facts = persisted["id"] == terminal["id"] and [
            link["attempt_id"] for link in persisted["execution_links"]
        ] == [link["attempt_id"] for link in terminal["execution_links"]]
        checks = (
            terminal["status"] != "completed",
            bool(stable_codes)
            and stable_codes.issubset({"gateway_error", "runtime_error", "dependency_failed"}),
            persisted_retry_facts,
        )
        facts = {
            "not_completed": checks[0],
            "stable_diagnostic_code": checks[1],
            "persisted_attempt_facts": persisted_retry_facts,
        }
    return _Scenario(
        terminal,
        (terminal,),
        facts,
        checks,
        recovery_outcome=(
            "endpoint_unavailable" if family == "dsh_endpoint_unavailable" else "not_required"
        ),
    )


def _approval_scenario(
    client: TestClient,
    endpoint: KeylessModelEndpoint,
    task: dict[str, Any],
    strategy: str,
    workspace_id: str,
    employees: list[dict[str, Any]],
) -> _Scenario:
    timeout = task["max_duration_ms"] / 1000
    strategy_work: dict[str, Any] | None = None
    if strategy == "direct":
        strategy_work = _terminal_work(
            client,
            workspace_id,
            _payload(
                strategy,
                task_id=task["task_id"],
                objective=task["objective"],
                criteria=task["acceptance_checks"],
                employees=employees,
                command_suffix="strategy",
            ),
            timeout,
        )
    resource = workspace_id
    grant = {
        "action": "workspace.read",
        "level": 1,
        "resource_kind": "workspace",
        "resource_values": [resource],
        "requires_approval": True,
    }
    update = client.put(
        f"/workspaces/{workspace_id}/capabilities",
        json={"grants": [{**grant, "requires_approval": False}]},
    )
    update.raise_for_status()
    governed = _employee(
        client,
        workspace_id,
        "governed employee",
        f"FIXED_APPROVAL_{strategy}",
        grants=[grant],
    )

    def governed_payload(suffix: str) -> dict[str, Any]:
        return {
            "kind": "graph",
            "objective": f"remember FIXED_APPROVAL_{strategy}_{suffix}",
            "acceptance_criteria": task["acceptance_checks"],
            "command_id": f"fixed-set:{task['task_id']}:{strategy}:{suffix}",
            "nodes": [
                {
                    "key": "governed",
                    "employee_id": governed["id"],
                    "objective": f"remember FIXED_APPROVAL_{strategy}_{suffix}",
                    "acceptance_criteria": task["acceptance_checks"],
                    "required_actions": ["workspace.read"],
                    "resource_kinds": ["workspace"],
                    "resource_values": [resource],
                }
            ],
            "edges": [],
        }

    requests_before = len(endpoint.requests)
    approved_created = _post_work(client, workspace_id, governed_payload("approve"))
    preapproval_count = len(endpoint.requests) - requests_before
    approvals = client.get(f"/workspaces/{workspace_id}/approvals").json()
    pending = next(item for item in approvals if item["work_id"] == approved_created["id"])
    approved_response = client.post(
        f"/approvals/{pending['id']}/approve",
        json={"decided_by": "fixed-set-operator"},
    )
    approved_response.raise_for_status()
    approved = _wait_for_terminal(client, approved_created["id"], timeout_seconds=timeout)

    rejected_created = _post_work(client, workspace_id, governed_payload("reject"))
    approvals = client.get(f"/workspaces/{workspace_id}/approvals").json()
    rejected_pending = next(item for item in approvals if item["work_id"] == rejected_created["id"])
    rejected_response = client.post(
        f"/approvals/{rejected_pending['id']}/reject",
        json={"decided_by": "fixed-set-operator"},
    )
    rejected_response.raise_for_status()
    rejected = rejected_response.json()["work"]
    rejected_code = rejected["nodes"][0]["failure_code"] or ""
    checks = (
        approved_created["nodes"][0]["status"] == "waiting_approval"
        and rejected_created["nodes"][0]["status"] == "waiting_approval",
        approved_response.json()["approval"]["status"] == "approved"
        and approved["status"] == "completed",
        rejected_response.json()["approval"]["status"] == "rejected"
        and rejected_code == "approval_rejected",
    )
    facts: dict[str, bool | int | str] = {
        "selected_strategy_work_completed": (
            strategy_work is None or strategy_work["status"] == "completed"
        ),
        "governance_path_strategy": "graph",
        "preapproval_model_request_count": preapproval_count,
        "approved_status": approved["status"],
        "approved_policy_rechecked": checks[1],
        "rejected_failure_code": rejected_code,
        "rejected_status": rejected["status"],
    }
    works = tuple(item for item in (strategy_work, approved, rejected) if item is not None)
    return _Scenario(
        strategy_work or approved,
        works,
        facts,
        checks,
        user_interventions=2,
    )


def _mark_completed_work_running(database_path: Path, work: dict[str, Any]) -> None:
    attempt_id = work["execution_links"][-1]["attempt_id"]
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE works SET status = 'running' WHERE id = ?", (work["id"],))
        connection.execute(
            "UPDATE work_nodes SET status = 'running', active_attempt_id = ?, "
            "failure_code = NULL, version = version + 1 WHERE work_id = ?",
            (attempt_id, work["id"]),
        )
        connection.execute(
            "UPDATE execution_links SET status = 'running', finished_at = NULL, "
            "diagnostic_code = NULL WHERE attempt_id = ?",
            (attempt_id,),
        )
        connection.execute(
            "DELETE FROM artifact_references WHERE source_attempt_id = ?", (attempt_id,)
        )
        connection.commit()


def _wait_for_new_attempt_terminal(
    client: TestClient,
    work_id: str,
    previous_attempt_id: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"/works/{work_id}")
        response.raise_for_status()
        work = response.json()
        new_links = [
            link for link in work["execution_links"] if link["attempt_id"] != previous_attempt_id
        ]
        if new_links and work["status"] in _TERMINAL and all(
            link["status"] in _TERMINAL for link in new_links
        ):
            return work
        time.sleep(0.02)
    raise TimeoutError(f"fixed-set retry {work_id} exceeded its declared budget")


def _wait_for_runtime_workspace_release(
    workspace_root: Path, *, timeout_seconds: float
) -> None:
    probe = workspace_root.with_name(f"{workspace_root.name}-release-probe")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            workspace_root.rename(probe)
            probe.rename(workspace_root)
            return
        except PermissionError:
            time.sleep(0.02)
    raise TimeoutError("DSH runtime did not release its workspace within the task budget")


def _restart_scenario(
    settings: Settings,
    task: dict[str, Any],
    strategy: str,
    endpoint: KeylessModelEndpoint,
) -> _Scenario:
    timeout = task["max_duration_ms"] / 1000
    with TestClient(create_app(settings=settings)) as client:
        workspace = client.post(
            "/workspaces", json={"name": f"{task['task_id']} {strategy}"}
        ).json()
        employees = [
            _employee(
                client,
                workspace["id"],
                f"{strategy} employee {index}",
                f"FIXED_EMP_{task['task_id']}_{strategy}_{index}",
            )
            for index in range(3)
        ]
        strategy_work: dict[str, Any] | None = None
        if strategy == "direct":
            strategy_work = _terminal_work(
                client,
                workspace["id"],
                _payload(
                    strategy,
                    task_id=task["task_id"],
                    objective=task["objective"],
                    criteria=task["acceptance_checks"],
                    employees=employees,
                    command_suffix="strategy",
                ),
                timeout,
            )
        recovery_payload = {
            "kind": "graph",
            "objective": f"remember FIXED_RECOVERY_{strategy}",
            "acceptance_criteria": task["acceptance_checks"],
            "command_id": f"fixed-set:{task['task_id']}:{strategy}:recovery",
            "nodes": [
                {
                    "key": "recovery",
                    "employee_id": employees[0]["id"],
                    "objective": f"remember FIXED_RECOVERY_{strategy}",
                    "acceptance_criteria": task["acceptance_checks"],
                    "max_attempts": 2,
                }
            ],
            "edges": [],
        }
        completed = _terminal_work(client, workspace["id"], recovery_payload, timeout)
        graph_facts = (
            completed["graph_revision_id"],
            completed["graph_revision_number"],
            _edge_facts(completed),
            tuple(node["id"] for node in completed["nodes"]),
        )
        first_attempt_id = completed["execution_links"][-1]["attempt_id"]
    _mark_completed_work_running(settings.data_root / "company.db", completed)

    requests_before_restart = len(endpoint.requests)
    with TestClient(create_app(settings=settings)) as client:
        lost_response = client.get(f"/works/{completed['id']}")
        lost_response.raise_for_status()
        lost = lost_response.json()
        lost_code = lost["nodes"][0]["failure_code"] or ""
        restart_dispatched = len(endpoint.requests) - requests_before_restart
    endpoint.make_unavailable(
        employees[0]["revision"]["responsibility"].splitlines()[0]
    )
    retry_started = time.monotonic()
    retry_app = create_app(settings=settings)
    with TestClient(retry_app) as client:
        retried_created = _post_work(client, workspace["id"], recovery_payload)
        retried = _wait_for_new_attempt_terminal(
            client,
            retried_created["id"],
            first_attempt_id,
            timeout_seconds=timeout - (time.monotonic() - retry_started),
        )
        coordinator = retry_app.state.assembly.work_coordinator
        if not isinstance(coordinator, RuntimeCoordinator):
            raise RuntimeError("fixed-set production assembly has no runtime coordinator")
        if not coordinator.wait_for_idle(
            timeout_seconds=timeout - (time.monotonic() - retry_started)
        ):
            raise TimeoutError(
                f"fixed-set retry {retried_created['id']} terminal observer exceeded "
                "its declared budget"
            )
        retried_response = client.get(f"/works/{retried_created['id']}")
        retried_response.raise_for_status()
        retried = retried_response.json()
    _wait_for_runtime_workspace_release(
        settings.resolved_workspace_root,
        timeout_seconds=timeout - (time.monotonic() - retry_started),
    )
    attempt_ids = {link["attempt_id"] for link in retried["execution_links"]}
    retry_links = [
        link
        for link in retried["execution_links"]
        if link["attempt_id"] != first_attempt_id
    ]
    retry_link = retry_links[0] if len(retry_links) == 1 else None
    retry_status = "missing" if retry_link is None else retry_link["status"]
    retry_failure_code = (
        "missing" if retry_link is None else retry_link["diagnostic_code"] or "missing"
    )
    retry_model_request_count = len(endpoint.requests) - requests_before_restart
    retry_terminal_non_completed = retry_status in {"blocked", "failed"}
    retry_failure_code_closed = retry_failure_code in {
        "runtime_process_lost",
        "gateway_error",
    }
    retry_request_pattern_valid = (
        retry_status == "blocked"
        and retry_failure_code == "runtime_process_lost"
        and retry_model_request_count == 0
    ) or (
        retry_status == "failed"
        and retry_failure_code == "gateway_error"
        and retry_model_request_count in {0, 3}
    )
    preserved = graph_facts == (
        retried["graph_revision_id"],
        retried["graph_revision_number"],
        _edge_facts(retried),
        tuple(node["id"] for node in retried["nodes"]),
    )
    distinct_attempts = (
        len(attempt_ids) == 2
        and first_attempt_id in attempt_ids
        and len(retry_links) == 1
    )
    checks = (
        lost_code == "runtime_process_lost" and restart_dispatched == 0,
        preserved,
        distinct_attempts
        and retry_terminal_non_completed
        and retry_failure_code_closed
        and retry_request_pattern_valid,
    )
    facts: dict[str, bool | int | str] = {
        "selected_strategy_work_completed": (
            strategy_work is None or strategy_work["status"] == "completed"
        ),
        "recovery_path_strategy": "graph",
        "lost_failure_code": lost_code,
        "restart_model_request_count": restart_dispatched,
        "graph_facts_unchanged": preserved,
        "attempt_ids_distinct": distinct_attempts,
        "attempt_count": len(retried["execution_links"]),
        "retry_attempt_persisted": distinct_attempts,
        "retry_terminal_status": retry_status,
        "retry_terminal_non_completed": retry_terminal_non_completed,
        "retry_failure_code": retry_failure_code,
        "retry_failure_code_closed": retry_failure_code_closed,
        "retry_model_request_count": retry_model_request_count,
        "retry_request_pattern_valid": retry_request_pattern_valid,
    }
    works = tuple(item for item in (strategy_work, retried) if item is not None)
    return _Scenario(
        lost,
        works,
        facts,
        checks,
        user_interventions=1,
        recovery_outcome=(
            "runtime_process_lost_retry_not_completed"
            if retry_terminal_non_completed
            else f"runtime_process_lost_retry_{retry_status}"
        ),
        unsuccessful_model_requests=retry_model_request_count,
    )


def _metrics(
    scenario: _Scenario,
    *,
    duration_ms: int,
    successful_model_requests: int,
) -> dict[str, bool | float | int | str]:
    node_ids = [node["id"] for work in scenario.works for node in work["nodes"]]
    outcome = SystemRunOutcome(
        task_succeeded=all(scenario.checks),
        milestones=scenario.checks,
        acceptance_checks=scenario.checks,
        token_count=successful_model_requests * _TOKENS_PER_SUCCESSFUL_CALL,
        duration_ms=duration_ms,
        user_interventions=scenario.user_interventions,
        invalid_delegations=0,
        duplicate_nodes=len(node_ids) - len(set(node_ids)),
        policy_violations=0,
        recovery_outcome=scenario.recovery_outcome,
    )
    return compute_metrics(outcome).to_dict()


def _settings(output_root: Path, endpoint: KeylessModelEndpoint) -> Settings:
    return Settings(
        data_root=output_root / "data",
        session_root=output_root / "sessions",
        workspace_root=output_root / "workspaces",
        dsh_base_url=endpoint.base_url,
        deepseek_api_key=SecretStr("keyless-fixed-set"),
        dsh_request_timeout_seconds=3,
        dsh_shutdown_timeout_seconds=2,
        runtime_concurrency=1,
    )


def replay_fixed_task_set(tasks_path: Path, output_root: Path) -> dict[str, Any]:
    """Replay every allowed task/strategy pair through production Company assembly."""

    tasks = [
        json.loads(line)
        for line in tasks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    output_root.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    with KeylessModelEndpoint() as endpoint:
        endpoint.make_unavailable("company-v1-endpoint-unavailable")
        for task in tasks:
            for strategy in task["allowed_strategies"]:
                pair_root = output_root / task["task_id"] / strategy
                settings = _settings(pair_root, endpoint)
                requests_before = len(endpoint.requests)
                started = time.monotonic()
                if task["family"] == "restart_recovery":
                    scenario = _restart_scenario(settings, task, strategy, endpoint)
                else:
                    with TestClient(create_app(settings=settings)) as client:
                        workspace_response = client.post(
                            "/workspaces",
                            json={"name": f"{task['task_id']} {strategy}"},
                        )
                        workspace_response.raise_for_status()
                        workspace = workspace_response.json()
                        employees = [
                            _employee(
                                client,
                                workspace["id"],
                                f"{strategy} employee {index}",
                                f"FIXED_EMP_{task['task_id']}_{strategy}_{index}",
                            )
                            for index in range(3)
                        ]
                        if task["family"] == "approval_allow_reject":
                            scenario = _approval_scenario(
                                client,
                                endpoint,
                                task,
                                strategy,
                                workspace["id"],
                                employees,
                            )
                        else:
                            scenario = _ordinary_scenario(
                                client,
                                endpoint,
                                task,
                                strategy,
                                workspace["id"],
                                employees,
                            )
                duration_ms = max(1, round((time.monotonic() - started) * 1000))
                model_request_count = len(endpoint.requests) - requests_before
                endpoint_unavailable = task["family"] == "dsh_endpoint_unavailable"
                runs.append(
                    {
                        "task_id": task["task_id"],
                        "strategy": strategy,
                        "status": scenario.work["status"],
                        "work_id": scenario.work["id"],
                        "attempt_count": sum(
                            node["attempt_count"]
                            for work in scenario.works
                            for node in work["nodes"]
                        ),
                        "model_request_count": model_request_count,
                        "max_duration_ms": task["max_duration_ms"],
                        "acceptance_checks": [
                            {"name": name, "passed": passed}
                            for name, passed in zip(
                                task["acceptance_checks"], scenario.checks, strict=True
                            )
                        ],
                        "facts": scenario.facts,
                        "metrics": _metrics(
                            scenario,
                            duration_ms=duration_ms,
                            successful_model_requests=(
                                0
                                if endpoint_unavailable
                                else model_request_count
                                - scenario.unsuccessful_model_requests
                            ),
                        ),
                    }
                )
    return {"task_set_version": "company-v1", "runs": runs}

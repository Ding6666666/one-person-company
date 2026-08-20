# Phase 3 Direct Work Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通“用户把工作直接交给一名 Employee → DSH 持久 Session 执行 → Company 保存状态、事件与结果引用 → 用户查看历史/取消/恢复”的完整闭环。

**Architecture:** Direct 也使用单节点 WorkGraphRevision，因此后续多节点不会替换数据模型。Application 先提交 Company 事实，再由 RuntimeCoordinator 调用 DshGateway；一次 ExecutionLink/Attempt 独占一个 Harness。DSH 原始 transcript 和最终文本不复制进 Company DB，DB 只保存安全事件投影和 `dsh-session://` ArtifactReference。

**Tech Stack:** Phase 2 stack、DeepSeek Harness Python SDK、ThreadPoolExecutor、SQLite、FastAPI background coordinator、React/Vitest。

---

## 目标结构

```text
apps/company-service/src/dsh_company/
├── domain/work.py
├── application/work_commands.py
├── application/work_service.py
├── application/runtime_coordinator.py
├── dsh_gateway/contracts.py
├── dsh_gateway/adapter.py
├── dsh_gateway/events.py
├── dsh_gateway/supervisor.py
├── persistence/work_models.py
├── persistence/work_repositories.py
└── api/work.py
apps/dsh-company-plugin/src/client/
├── WorkList.tsx
├── WorkComposer.tsx
├── WorkDetail.tsx
└── CompanyHistory.tsx
```

### Task 1: 定义 Direct Work、单节点图和 ExecutionLink Domain

**Files:**

- Modify: `apps/company-service/src/dsh_company/domain/ids.py`
- Create: `apps/company-service/src/dsh_company/domain/work.py`
- Create: `apps/company-service/tests/domain/test_work.py`

- [ ] **Step 1: 写状态与单节点图测试**

```python
def test_direct_work_creates_one_frozen_node() -> None:
    work, graph, node = Work.create_direct(
        work_id=WorkId("work-1"),
        graph_id=WorkGraphRevisionId("graph-1"),
        node_id=WorkNodeId("node-1"),
        workspace_id=WorkspaceId("ws-1"),
        employee_id=EmployeeId("emp-1"),
        employee_revision_id=EmployeeRevisionId("rev-1"),
        objective="撰写发布稿",
        acceptance_criteria=("包含标题", "不超过 800 字"),
        command_id="cmd-1",
    )

    assert work.status is WorkStatus.QUEUED
    assert graph.strategy is WorkStrategy.DIRECT
    assert graph.revision_number == 1
    assert node.status is WorkNodeStatus.READY
    assert node.employee_revision_id == EmployeeRevisionId("rev-1")


def test_node_completion_requires_result_reference() -> None:
    node = ready_node().start(AttemptId("attempt-1"))

    with pytest.raises(ValueError, match="result reference"):
        node.complete(AttemptId("attempt-1"), None)


def test_execution_link_distinguishes_cancel_request_and_confirmation() -> None:
    link = ExecutionLink.dispatch(
        execution_link_id=ExecutionLinkId("link-1"),
        attempt_id=AttemptId("attempt-1"),
        node_id=WorkNodeId("node-1"),
        command_id="cmd-1",
        dsh_session_id="employee-emp-1",
    ).mark_running()

    requested = link.request_cancel()
    confirmed = requested.confirm_cancelled()

    assert requested.status is ExecutionStatus.CANCEL_REQUESTED
    assert confirmed.status is ExecutionStatus.CANCELLED
```

- [ ] **Step 2: 确认红灯**

Run: `uv run pytest apps/company-service/tests/domain/test_work.py -q`

Expected: collection FAIL because work types do not exist.

- [ ] **Step 3: 增加 ID、枚举与不可变实体**

Add IDs `WorkId`, `WorkGraphRevisionId`, `WorkNodeId`, `ExecutionLinkId`, `AttemptId`, `CompanyEventId`, and `ArtifactReferenceId` with the existing `NewType` pattern.

Define closed states:

```python
class WorkStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkNodeStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionStatus(StrEnum):
    DISPATCH_PENDING = "dispatch_pending"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkStrategy(StrEnum):
    DIRECT = "direct"
```

Implement immutable `Work`, `WorkGraphRevision`, `WorkNode`, `ExecutionLink`, `ArtifactReference`, and `CompanyEvent`. Every transition returns `dataclasses.replace(self, ...)`; invalid source state or mismatched Attempt ID raises `ValueError`.

`ArtifactReference` fields are:

```python
id: ArtifactReferenceId
workspace_id: WorkspaceId
kind: Literal["dsh_session_result"]
uri: str
source_session_id: str
source_attempt_id: AttemptId
created_at: datetime
```

- [ ] **Step 4: 实现 Direct 工厂**

`Work.create_direct` validates nonblank objective and at least one nonblank criterion, creates revision 1, one READY node, and freezes the supplied EmployeeRevision ID. It does not call DSH.

- [ ] **Step 5: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/domain/test_work.py -q
git add apps/company-service/src/dsh_company/domain apps/company-service/tests/domain/test_work.py
git commit -m "feat: define direct work and execution domain"
```

### Task 2: 持久化 Work、Node、Attempt、Event 与 ArtifactReference

**Files:**

- Create: `apps/company-service/alembic/versions/0002_direct_work.py`
- Create: `apps/company-service/src/dsh_company/persistence/work_models.py`
- Create: `apps/company-service/src/dsh_company/persistence/work_repositories.py`
- Modify: `apps/company-service/src/dsh_company/persistence/uow.py`
- Create: `apps/company-service/tests/persistence/test_work_store.py`

- [ ] **Step 1: 写 round-trip、幂等和事件顺序测试**

```python
def test_direct_graph_and_attempt_round_trip(sqlite_uow) -> None:
    aggregate = direct_work_fixture(command_id="cmd-1")
    with sqlite_uow as uow:
        uow.works.add(aggregate)
        uow.commit()

    with sqlite_uow as uow:
        stored = uow.works.get(aggregate.work.id)

    assert stored == aggregate


def test_command_id_is_unique_per_workspace(sqlite_uow) -> None:
    with sqlite_uow as uow:
        uow.works.add(direct_work_fixture(work_id="work-1", command_id="cmd-1"))
        uow.commit()
    with pytest.raises(DuplicateCommand):
        with sqlite_uow as uow:
            uow.works.add(direct_work_fixture(work_id="work-2", command_id="cmd-1"))
            uow.commit()


def test_company_events_keep_attempt_source_sequence(sqlite_uow) -> None:
    seed_events(sqlite_uow, attempt_id="attempt-1", sequences=(1, 2, 3))
    with sqlite_uow as uow:
        events = uow.company_events.list_for_work(WorkId("work-1"))
    assert [event.source_sequence for event in events] == [1, 2, 3]
```

- [ ] **Step 2: 确认红灯**

Run the persistence test. Expected: FAIL because work repositories are absent.

- [ ] **Step 3: 创建 migration**

Create tables:

```text
works(id PK, workspace_id FK, command_id, objective, status, current_graph_revision_id, created_at, UNIQUE(workspace_id, command_id))
work_graph_revisions(id PK, work_id FK, revision_number, strategy, created_at, UNIQUE(work_id, revision_number))
work_nodes(id PK, graph_revision_id FK, work_id FK, objective, acceptance_criteria_json, assigned_employee_id FK, employee_revision_id FK, status, active_attempt_id, failure_code, version)
execution_links(id PK, node_id FK, attempt_id UNIQUE, command_id UNIQUE, dsh_session_id, status, started_at, finished_at, diagnostic_code)
artifact_references(id PK, workspace_id FK, kind, uri, source_session_id, source_attempt_id UNIQUE, created_at)
company_events(id PK, workspace_id FK, work_id FK, node_id, attempt_id, source_sequence, event_type, summary, source, observed_at, UNIQUE(attempt_id, source_sequence))
```

Acceptance criteria and event details use JSON only for bounded scalar/list data; no prompt, transcript, tool arguments or final response column exists.

- [ ] **Step 4: 实现映射和 repositories**

Expose `WorkAggregate(work, graph, nodes, execution_links, artifacts)` and repositories:

```python
works.add(aggregate)
works.get(work_id)
works.get_by_command(workspace_id, command_id)
works.list_for_workspace(workspace_id)
works.list_dispatch_pending()
works.list_running()
company_events.append(event)
company_events.list_for_work(work_id)
```

Use optimistic `version` update for nodes; zero updated rows raises `ConcurrentNodeUpdate`.

- [ ] **Step 5: 转绿、migration round trip、提交**

```powershell
uv run pytest apps/company-service/tests/persistence/test_work_store.py -q
uv run alembic -c apps/company-service/alembic.ini upgrade head
uv run alembic -c apps/company-service/alembic.ini downgrade -1
uv run alembic -c apps/company-service/alembic.ini upgrade head
git add apps/company-service/alembic apps/company-service/src/dsh_company/persistence apps/company-service/tests/persistence/test_work_store.py
git commit -m "feat: persist direct work lifecycle"
```

### Task 3: 定义 DshGateway 并适配公开 SDK

**Files:**

- Create: `apps/company-service/src/dsh_company/dsh_gateway/contracts.py`
- Create: `apps/company-service/src/dsh_company/dsh_gateway/events.py`
- Create: `apps/company-service/src/dsh_company/dsh_gateway/supervisor.py`
- Create: `apps/company-service/src/dsh_company/dsh_gateway/adapter.py`
- Create: `apps/company-service/src/dsh_company/dsh_gateway/cordis/workspace_read.cordis.yml`
- Create: `apps/company-service/src/dsh_company/dsh_gateway/cordis/workspace_write.cordis.yml`
- Create: `apps/company-service/src/dsh_company/dsh_gateway/cordis/network_denied.cordis.yml`
- Create: `apps/company-service/tests/dsh_gateway/test_gateway_adapter.py`
- Create: `apps/company-service/tests/dsh_gateway/test_event_projection.py`

- [ ] **Step 1: 写 Gateway 契约、事件安全和取消测试**

```python
def test_gateway_reuses_binding_session_and_returns_reference(fake_harness_factory) -> None:
    gateway = PublicSdkDshGateway(fake_harness_factory, session_root=Path("sessions"))
    result = gateway.submit(
        GatewaySubmission(
            attempt_id=AttemptId("attempt-1"),
            command_id="cmd-1",
            employee=employee_snapshot(session_id="employee-emp-1"),
            objective="撰写发布稿",
            acceptance_criteria=("包含标题",),
        ),
        on_event=lambda event: None,
    )

    assert fake_harness_factory.last_session_id == "employee-emp-1"
    assert result.finish_reason == "completed"
    assert result.reference_uri == "dsh-session://employee-emp-1/attempt/attempt-1/result"


def test_event_projection_never_copies_content_or_arguments() -> None:
    projected = project_notification(AttemptId("attempt-1"), 7, notification_with_secrets())

    assert projected.source_sequence == 7
    assert projected.details == {"method": "session.event", "event_type": "tool/end", "tool_name": "web"}
    assert "prompt" not in repr(projected)
    assert "secret-value" not in repr(projected)


def test_cancel_closes_exactly_the_attempt_owned_harness(fake_harness_factory) -> None:
    gateway = running_gateway(fake_harness_factory, attempt_id="attempt-1")
    result = gateway.cancel(AttemptId("attempt-1"))

    assert result.runtime_closed is True
    assert fake_harness_factory.close_calls == ["attempt-1"]
```

- [ ] **Step 2: 确认红灯**

Run the focused tests. Expected: collection FAIL for absent contracts/adapter.

- [ ] **Step 3: 定义端口类型**

```python
@dataclass(frozen=True, slots=True)
class EmployeeRuntimeSnapshot:
    employee_id: EmployeeId
    employee_revision_id: EmployeeRevisionId
    responsibility: str
    runtime_profile: str
    model: str
    dsh_session_id: str


@dataclass(frozen=True, slots=True)
class GatewaySubmission:
    attempt_id: AttemptId
    command_id: str
    employee: EmployeeRuntimeSnapshot
    objective: str
    acceptance_criteria: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GatewayResult:
    finish_reason: str | None
    reference_uri: str
    event_count: int


class DshGateway(Protocol):
    def submit(self, submission: GatewaySubmission, *, on_event: Callable[[ProjectedDshEvent], None]) -> GatewayResult: ...
    def cancel(self, attempt_id: AttemptId) -> GatewayCancelResult: ...
```

There is intentionally no production `observe()` because Phase 1 proved it is not exposed.

- [ ] **Step 4: 实现事件投影与 Supervisor**

`project_notification` copies only method, event type, tool name, finish reason, integer usage and closed diagnostic code. `source_sequence` is the per-Attempt callback order starting at 1; the DB uniqueness constraint provides idempotency. No hash is created.

`RuntimeSupervisor` maps Attempt ID to one active Harness, rejects duplicate active Attempt IDs, closes once, and removes the handle only after `Session.run` settles and close finishes.

- [ ] **Step 5: 实现 SDK adapter**

The adapter:

1. selects a checked-in Cordis runtime profile from `workspace_read`, `workspace_write`, `network_denied`;
2. constructs one Harness using employee model and stable Session ID;
3. registers before `Session.run`;
4. numbers callback events;
5. returns only finish reason, count and URI;
6. always closes/removes in `finally`;
7. never stores `final_response`.

Prompt format is deterministic:

```text
Employee responsibility:
{responsibility}

Work objective:
{objective}

Acceptance criteria:
- {criterion}

Complete the work using only the capabilities exposed by the active DSH runtime profile. Return a concise result in the DSH Session.
```

Create the three Cordis files by adapting only the public SDK server, model, Session persistence, sandbox/filesystem and tool composition from `multi-agent@2330adb:apps/control-service/src/dsh_multi_agent/runtime_dsh/cordis`. `workspace_read` exposes no write/shell tool; `workspace_write` exposes filesystem write and local shell and is therefore also network-capable at the Company policy layer; `network_denied` exposes neither shell nor network. Every file uses the new data/session environment names and contains no Git, worktree, CrewAI or old role configuration.

- [ ] **Step 6: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/dsh_gateway/test_gateway_adapter.py apps/company-service/tests/dsh_gateway/test_event_projection.py -q
git add apps/company-service/src/dsh_company/dsh_gateway apps/company-service/tests/dsh_gateway
git commit -m "feat: adapt public DSH SDK for direct work"
```

### Task 4: 实现 Direct WorkService 与 RuntimeCoordinator

**Files:**

- Create: `apps/company-service/src/dsh_company/application/work_commands.py`
- Create: `apps/company-service/src/dsh_company/application/work_service.py`
- Create: `apps/company-service/src/dsh_company/application/runtime_coordinator.py`
- Modify: `apps/company-service/src/dsh_company/application/ports.py`
- Create: `apps/company-service/tests/application/test_work_service.py`
- Create: `apps/company-service/tests/application/test_runtime_coordinator.py`

- [ ] **Step 1: 写创建幂等和事务边界测试**

```python
def test_create_direct_work_is_idempotent_by_workspace_command(fake_uow) -> None:
    service = WorkService(fake_uow, ids=SequentialIds())
    command = CreateDirectWork(
        workspace_id=WorkspaceId("ws-1"), employee_id=EmployeeId("emp-1"),
        objective="撰写发布稿", acceptance_criteria=("包含标题",), command_id="cmd-1",
    )

    first = service.create_direct(command)
    second = service.create_direct(command)

    assert second.work.id == first.work.id
    assert fake_uow.commits == 1


def test_coordinator_commits_pending_before_calling_dsh(fake_uow, recording_gateway) -> None:
    coordinator = RuntimeCoordinator(fake_uow, recording_gateway)
    coordinator.dispatch(WorkNodeId("node-1"))

    assert recording_gateway.calls[0].company_commit_count == 1
```

- [ ] **Step 2: 确认红灯**

Run both tests. Expected: collection FAIL because work services are absent.

- [ ] **Step 3: 实现创建命令**

```python
@dataclass(frozen=True, slots=True)
class CreateDirectWork:
    workspace_id: WorkspaceId
    employee_id: EmployeeId
    objective: str
    acceptance_criteria: tuple[str, ...]
    command_id: str
```

`WorkService.create_direct` checks existing command first, validates active Employee in Workspace, reads current immutable Revision/Binding, creates the single-node aggregate plus `DISPATCH_PENDING` ExecutionLink, commits once, and asks the coordinator queue to dispatch only after commit.

- [ ] **Step 4: 实现 Coordinator 成功/失败路径**

On dispatch:

1. transaction A changes Link/Node/Work to RUNNING and commits;
2. external `gateway.submit` runs without a DB transaction;
3. each callback opens a short transaction and appends a safe CompanyEvent;
4. success transaction creates ArtifactReference, completes Node/Work/Link and appends `work.completed`;
5. exception transaction marks FAILED with a closed diagnostic code; exception text is logged, not stored.

Use a bounded `ThreadPoolExecutor(max_workers=settings.runtime_concurrency)`; default is 4.

- [ ] **Step 5: 实现取消和启动协调**

`request_cancel` first persists `CANCEL_REQUESTED`, then calls Gateway. A confirmed close transitions to CANCELLED. If no active runtime exists, transition Node/Work/Link to BLOCKED with `cancel_unconfirmed`.

On service startup:

- `DISPATCH_PENDING` attempts are requeued;
- `RUNNING` attempts become BLOCKED with `runtime_process_lost`;
- no state is inferred from elapsed time.

- [ ] **Step 6: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/application/test_work_service.py apps/company-service/tests/application/test_runtime_coordinator.py -q
git add apps/company-service/src/dsh_company/application apps/company-service/tests/application
git commit -m "feat: orchestrate durable direct work attempts"
```

### Task 5: 暴露 Work、History 与 Cancel API

**Files:**

- Create: `apps/company-service/src/dsh_company/api/work.py`
- Modify: `apps/company-service/src/dsh_company/api/schemas.py`
- Modify: `apps/company-service/src/dsh_company/foundation/assembly.py`
- Create: `apps/company-service/tests/api/test_work_api.py`
- Modify: `packages/contracts/openapi/openapi.json`
- Modify: `packages/contracts/openapi/source-revision.json`
- Modify: `apps/dsh-company-plugin/src/contracts/generated/openapi.ts`

- [ ] **Step 1: 写 API 测试**

```python
def test_create_direct_work_returns_accepted_projection(client, seeded_employee) -> None:
    response = client.post(
        f"/workspaces/{seeded_employee.workspace_id}/works",
        json={
            "employee_id": seeded_employee.id,
            "objective": "撰写发布稿",
            "acceptance_criteria": ["包含标题"],
            "command_id": "cmd-1",
        },
    )
    assert response.status_code == 202
    assert response.json()["strategy"] == "direct"
    assert response.json()["nodes"][0]["status"] in {"ready", "running"}


def test_history_contains_safe_company_events_not_model_content(client, completed_work) -> None:
    response = client.get(f"/works/{completed_work.id}/events")
    body = response.json()
    assert body[-1]["event_type"] == "work.completed"
    assert "final_response" not in json.dumps(body)
```

- [ ] **Step 2: 确认红灯并实现 routes**

Expected initial FAIL: 404. Implement:

```text
POST /workspaces/{workspace_id}/works -> 202
GET  /workspaces/{workspace_id}/works -> 200
GET  /works/{work_id} -> 200
GET  /works/{work_id}/events -> 200
POST /works/{work_id}/cancel -> 202
```

All read routes verify the Work belongs to the selected Workspace when a Workspace path is present. Result DTO exposes ArtifactReference URI, not raw DSH output.

- [ ] **Step 3: 转绿并更新契约**

```powershell
uv run pytest apps/company-service/tests/api/test_work_api.py -q
$apiCommit = git rev-parse HEAD
pnpm run contracts:capture -- --api-commit $apiCommit
pnpm run contracts:generate
pnpm --filter @dsh/company-plugin typecheck
```

- [ ] **Step 4: Commit**

```powershell
git add apps/company-service/src/dsh_company/api apps/company-service/src/dsh_company/foundation apps/company-service/tests/api/test_work_api.py packages/contracts apps/dsh-company-plugin/src/contracts/generated/openapi.ts
git commit -m "feat: expose direct work and company history API"
```

### Task 6: 构建 Direct Work 与历史 UI

**Files:**

- Modify: `apps/dsh-company-plugin/src/client/api.ts`
- Modify: `apps/dsh-company-plugin/src/client/controller.ts`
- Create: `apps/dsh-company-plugin/src/client/WorkList.tsx`
- Create: `apps/dsh-company-plugin/src/client/WorkComposer.tsx`
- Create: `apps/dsh-company-plugin/src/client/WorkDetail.tsx`
- Create: `apps/dsh-company-plugin/src/client/CompanyHistory.tsx`
- Create: `apps/dsh-company-plugin/src/client/Work.module.css`
- Modify: `apps/dsh-company-plugin/src/client/CompanySurface.tsx`
- Modify: `apps/dsh-company-plugin/src/client/locales.ts`
- Create: `apps/dsh-company-plugin/tests/direct-work.client.spec.tsx`

- [ ] **Step 1: 写工作闭环 UI 测试**

```tsx
it('submits direct work, renders authoritative progress, and cancels explicitly', async () => {
  const remote = new FakeCompanyRemote({ employees: [employeeFixture], work: runningWorkFixture })
  render(<CompanySurface remote={remote} initialWorkspaceId="ws-1" />)

  await user.click(screen.getByRole('link', { name: '工作' }))
  await user.type(screen.getByLabelText('工作目标'), '撰写发布稿')
  await user.type(screen.getByLabelText('验收标准'), '包含标题')
  await user.selectOptions(screen.getByLabelText('负责员工'), 'emp-1')
  await user.click(screen.getByRole('button', { name: '开始工作' }))

  expect(await screen.findByText('运行中')).toBeVisible()
  await user.click(screen.getByRole('button', { name: '请求取消' }))
  expect(remote.cancelCalls).toEqual(['work-1'])
})
```

- [ ] **Step 2: 确认红灯、实现页面、转绿**

Initial FAIL: Work components absent. Implement:

- Direct is the only strategy and default;
- one selected active Employee is required;
- one criterion per nonblank line;
- status badges use server enum only;
- polling refreshes projection but never converts timeout into terminal state;
- cancellation first shows “取消请求中”，only confirmed server status shows “已取消”；
- ArtifactReference opens a DSH Session link only if the host supports the URI; otherwise display a copyable reference;
- events use `aria-live="polite"` for newly observed company events.

Run:

```powershell
pnpm --filter @dsh/company-plugin test -- direct-work.client.spec.tsx
pnpm --filter @dsh/company-plugin typecheck
pnpm --filter @dsh/company-plugin build
```

Expected: focused test and build pass.

- [ ] **Step 3: Commit**

```powershell
git add apps/dsh-company-plugin
git commit -m "feat: add direct employee work experience"
```

### Task 7: 验证真实 DSH 闭环、取消与重启

**Files:**

- Create: `tests/system/tests/test_phase_3_direct_work.py`
- Modify: `tools/check.py`
- Modify: `README.md`
- Modify: `docs/README.md`

- [ ] **Step 1: 写 keyless 端到端测试**

Start Company Service with a temporary DB/session root and Phase 1 keyless endpoint. Through HTTP:

1. create Workspace and Employee;
2. create Direct Work;
3. wait until terminal;
4. assert Work COMPLETED, one ArtifactReference, safe events, and no raw final text in DB/API;
5. create a second Work on the same Employee and assert DSH request contains prior Session context;
6. start a slow Work, request cancel, assert CANCEL_REQUESTED precedes CANCELLED;
7. seed RUNNING, restart Service, assert BLOCKED/runtime_process_lost.

- [ ] **Step 2: 确认红灯、接入 production coordinator、转绿**

Initial failure must be a missing coordinator lifecycle. Wire startup to reconcile and start executor, shutdown to reject new dispatch and close active runtimes. Rerun until the system test passes.

- [ ] **Step 3: 公共门禁与提交**

```powershell
uv run pytest tests/system/tests/test_phase_3_direct_work.py -q
python tools/check.py
git diff --check
git add tests/system tools/check.py README.md docs apps/company-service/src/dsh_company/foundation
git commit -m "test: verify direct DSH work lifecycle"
```

## Phase 3 完成定义

- Direct Work 从 UI/API 到真实 DSH Session 完成闭环；
- 同一 Employee 重用同一持久 Session，另一 Employee 不混用；
- Company DB 不含原始 prompt、模型最终文本或工具参数；
- command ID 幂等，Attempt ID 唯一，事件按来源顺序去重；
- 取消请求与确认分离；
- 重启后 RUNNING 不伪造终态，而是 BLOCKED/runtime_process_lost；
- Direct 成为 Phase 5 所有策略的基线。

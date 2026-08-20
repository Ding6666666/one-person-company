# Phase 2 Company and Employee Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在没有模型凭据的情况下创建独立 Workspace 和长期 Employee，并持久化员工版本、基础工具授权与稳定 DSH Session 绑定。

**Architecture:** Domain 使用纯 Python 不可变类型表达公司与员工不变量；Application 通过 Repository/UnitOfWork 端口执行用例；SQLAlchemy/Alembic 保存事实；FastAPI/OpenAPI 暴露命令与查询；DSH 插件 Host 启动本地服务，React Client 提供 Workspace/Employee 页面。创建 Employee 只分配稳定标识，不启动 DSH Runtime。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、SQLAlchemy 2.0.45、Alembic 1.17.2、SQLite；React 18.2、TypeScript、Zod、DSH/Cordis；Pytest、Vitest、Testing Library。

---

## 目标结构

```text
apps/company-service/src/dsh_company/
├── domain/
│   ├── ids.py
│   ├── workspace.py
│   ├── employee.py
│   └── capabilities.py
├── application/
│   ├── commands.py
│   ├── ports.py
│   └── company_service.py
├── persistence/
│   ├── database.py
│   ├── models.py
│   ├── repositories.py
│   └── uow.py
├── api/
│   ├── errors.py
│   ├── schemas.py
│   └── company.py
└── foundation/assembly.py
apps/company-service/alembic/
apps/dsh-company-plugin/src/
├── host/
├── client/
└── remote-contract.ts
```

### Task 1: 定义 Workspace、Employee 与基础能力 Domain

**Files:**

- Create: `apps/company-service/src/dsh_company/domain/__init__.py`
- Create: `apps/company-service/src/dsh_company/domain/ids.py`
- Create: `apps/company-service/src/dsh_company/domain/workspace.py`
- Create: `apps/company-service/src/dsh_company/domain/capabilities.py`
- Create: `apps/company-service/src/dsh_company/domain/employee.py`
- Create: `apps/company-service/tests/domain/test_company_models.py`

- [ ] **Step 1: 写领域不变量测试**

```python
from dsh_company.domain.capabilities import CapabilityLevel, default_employee_grants
from dsh_company.domain.employee import Employee, EmployeeAgentBinding, EmployeeRevision
from dsh_company.domain.ids import EmployeeId, WorkspaceId
from dsh_company.domain.workspace import Workspace


def test_workspace_name_is_required() -> None:
    with pytest.raises(ValueError, match="workspace name"):
        Workspace.create(WorkspaceId("ws-1"), "   ")


def test_employee_creation_freezes_revision_and_stable_dsh_identity() -> None:
    employee, revision, binding = Employee.create(
        employee_id=EmployeeId("emp-1"),
        workspace_id=WorkspaceId("ws-1"),
        display_name="内容编辑",
        responsibility="撰写并校对新闻内容",
        runtime_profile="workspace_read",
        model="deepseek-v4-flash",
    )

    assert revision.revision_number == 1
    assert employee.current_revision_id == revision.id
    assert binding.dsh_agent_id == "employee-emp-1"
    assert binding.dsh_session_id == "employee-emp-1"
    assert binding.memory_scope_id == "dsh-session:employee-emp-1"


def test_default_tools_are_present_but_not_high_risk() -> None:
    grants = default_employee_grants(WorkspaceId("ws-1"))

    assert {(grant.action, grant.level) for grant in grants} == {
        ("conversation.respond", CapabilityLevel.L0),
        ("workspace.read", CapabilityLevel.L1),
        ("session.history.read", CapabilityLevel.L1),
    }
    assert all(grant.requires_approval is False for grant in grants)


def test_binding_rejects_different_agent_and_session_ids() -> None:
    with pytest.raises(ValueError, match="Agent ID must equal Session ID"):
        EmployeeAgentBinding.create(
            employee_id=EmployeeId("emp-1"),
            dsh_agent_id="agent-1",
            dsh_session_id="session-1",
        )
```

- [ ] **Step 2: 确认红灯**

Run: `uv run pytest apps/company-service/tests/domain/test_company_models.py -q`

Expected: collection FAIL because `dsh_company.domain` is absent.

- [ ] **Step 3: 实现标识与 Workspace**

`ids.py`:

```python
from typing import NewType
from uuid import uuid4

WorkspaceId = NewType("WorkspaceId", str)
EmployeeId = NewType("EmployeeId", str)
EmployeeRevisionId = NewType("EmployeeRevisionId", str)
CapabilityGrantId = NewType("CapabilityGrantId", str)
EmployeeAgentBindingId = NewType("EmployeeAgentBindingId", str)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"
```

`workspace.py`:

```python
from dataclasses import dataclass
from datetime import UTC, datetime

from .ids import WorkspaceId


@dataclass(frozen=True, slots=True)
class Workspace:
    id: WorkspaceId
    name: str
    created_at: datetime

    @classmethod
    def create(cls, workspace_id: WorkspaceId, name: str) -> "Workspace":
        normalized = name.strip()
        if not normalized:
            raise ValueError("workspace name must not be blank")
        return cls(id=workspace_id, name=normalized, created_at=datetime.now(UTC))
```

- [ ] **Step 4: 实现能力等级和默认工具**

```python
from dataclasses import dataclass
from enum import IntEnum

from .ids import CapabilityGrantId, EmployeeRevisionId, WorkspaceId, new_id


class CapabilityLevel(IntEnum):
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    id: CapabilityGrantId
    employee_revision_id: EmployeeRevisionId | None
    action: str
    level: CapabilityLevel
    resource_kind: str
    resource_values: tuple[str, ...]
    requires_approval: bool


def default_employee_grants(workspace_id: WorkspaceId) -> tuple[CapabilityGrant, ...]:
    values = (str(workspace_id),)
    return tuple(
        CapabilityGrant(
            id=CapabilityGrantId(new_id("grant")),
            employee_revision_id=None,
            action=action,
            level=level,
            resource_kind="workspace",
            resource_values=values,
            requires_approval=False,
        )
        for action, level in (
            ("conversation.respond", CapabilityLevel.L0),
            ("workspace.read", CapabilityLevel.L1),
            ("session.history.read", CapabilityLevel.L1),
        )
    )
```

- [ ] **Step 5: 实现 Employee、Revision 与 Binding**

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .ids import (
    EmployeeAgentBindingId,
    EmployeeId,
    EmployeeRevisionId,
    WorkspaceId,
    new_id,
)


class EmployeeStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class EmployeeRevision:
    id: EmployeeRevisionId
    employee_id: EmployeeId
    revision_number: int
    responsibility: str
    runtime_profile: str
    model: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EmployeeAgentBinding:
    id: EmployeeAgentBindingId
    employee_id: EmployeeId
    dsh_agent_id: str
    dsh_session_id: str
    memory_scope_id: str
    created_at: datetime

    @classmethod
    def create(
        cls, *, employee_id: EmployeeId, dsh_agent_id: str, dsh_session_id: str
    ) -> "EmployeeAgentBinding":
        if dsh_agent_id != dsh_session_id:
            raise ValueError("DSH Agent ID must equal Session ID for the verified SDK")
        return cls(
            id=EmployeeAgentBindingId(new_id("binding")),
            employee_id=employee_id,
            dsh_agent_id=dsh_agent_id,
            dsh_session_id=dsh_session_id,
            memory_scope_id=f"dsh-session:{dsh_session_id}",
            created_at=datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class Employee:
    id: EmployeeId
    workspace_id: WorkspaceId
    display_name: str
    status: EmployeeStatus
    current_revision_id: EmployeeRevisionId
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        employee_id: EmployeeId,
        workspace_id: WorkspaceId,
        display_name: str,
        responsibility: str,
        runtime_profile: str,
        model: str,
    ) -> tuple["Employee", EmployeeRevision, EmployeeAgentBinding]:
        name = display_name.strip()
        duty = responsibility.strip()
        if not name or not duty:
            raise ValueError("employee name and responsibility must not be blank")
        now = datetime.now(UTC)
        revision = EmployeeRevision(
            id=EmployeeRevisionId(new_id("revision")),
            employee_id=employee_id,
            revision_number=1,
            responsibility=duty,
            runtime_profile=runtime_profile,
            model=model,
            created_at=now,
        )
        session_id = f"employee-{employee_id}"
        binding = EmployeeAgentBinding.create(
            employee_id=employee_id,
            dsh_agent_id=session_id,
            dsh_session_id=session_id,
        )
        return (
            cls(employee_id, workspace_id, name, EmployeeStatus.ACTIVE, revision.id, now),
            revision,
            binding,
        )
```

- [ ] **Step 6: 转绿、依赖方向检查与提交**

```powershell
uv run pytest apps/company-service/tests/domain/test_company_models.py -q
uv run python -c "import dsh_company.domain.employee, sys; assert not any(name.startswith(('fastapi','sqlalchemy','deepseek_harness')) for name in sys.modules)"
git add apps/company-service/src/dsh_company/domain apps/company-service/tests/domain
git commit -m "feat: define company and employee domain"
```

Expected: tests pass and Domain imports none of the forbidden frameworks.

### Task 2: 建立 SQLite、Alembic 与 Repository/UoW

**Files:**

- Modify: `apps/company-service/pyproject.toml`
- Create: `apps/company-service/alembic.ini`
- Create: `apps/company-service/alembic/env.py`
- Create: `apps/company-service/alembic/versions/0001_company_core.py`
- Create: `apps/company-service/src/dsh_company/persistence/database.py`
- Create: `apps/company-service/src/dsh_company/persistence/models.py`
- Create: `apps/company-service/src/dsh_company/persistence/repositories.py`
- Create: `apps/company-service/src/dsh_company/persistence/uow.py`
- Create: `apps/company-service/tests/persistence/test_company_store.py`
- Modify: `uv.lock`

- [ ] **Step 1: 写持久化契约测试**

```python
def test_workspace_employee_revision_grants_and_binding_round_trip(sqlite_uow) -> None:
    workspace = Workspace.create(WorkspaceId("ws-1"), "内容公司")
    employee, revision, binding = Employee.create(
        employee_id=EmployeeId("emp-1"), workspace_id=workspace.id,
        display_name="编辑", responsibility="写作", runtime_profile="workspace_read",
        model="deepseek-v4-flash",
    )
    grants = default_employee_grants(workspace.id)

    with sqlite_uow as uow:
        uow.workspaces.add(workspace)
        uow.employees.add(employee, revision, binding, grants)
        uow.commit()

    with sqlite_uow as uow:
        stored = uow.employees.get(employee.id)

    assert stored is not None
    assert stored.employee == employee
    assert stored.revision == revision
    assert stored.binding == binding
    assert {grant.action for grant in stored.grants} == {
        "conversation.respond", "workspace.read", "session.history.read"
    }


def test_workspace_boundary_filters_employee_queries(sqlite_uow) -> None:
    seed_two_workspaces(sqlite_uow)

    with sqlite_uow as uow:
        employees = uow.employees.list_for_workspace(WorkspaceId("ws-a"))

    assert [item.employee.id for item in employees] == [EmployeeId("emp-a")]
```

- [ ] **Step 2: 确认红灯**

Run: `uv run pytest apps/company-service/tests/persistence/test_company_store.py -q`

Expected: collection FAIL because persistence modules are absent.

- [ ] **Step 3: 添加数据库依赖与表结构**

Add `alembic==1.17.2` and `sqlalchemy==2.0.45`. Define ORM rows for exactly:

```text
workspaces(id PK, name, created_at)
employees(id PK, workspace_id FK, display_name, status, current_revision_id, created_at)
employee_revisions(id PK, employee_id FK, revision_number, responsibility, runtime_profile, model, created_at, UNIQUE(employee_id, revision_number))
capability_grants(id PK, employee_revision_id FK, action, level, resource_kind, resource_values_json, requires_approval)
employee_agent_bindings(id PK, employee_id UNIQUE FK, dsh_agent_id, dsh_session_id, memory_scope_id, created_at)
```

The first migration creates only these tables and indexes `employees.workspace_id`, `employee_revisions.employee_id`, and `capability_grants.employee_revision_id`.

- [ ] **Step 4: 实现 Repository 与 UoW**

Repository result:

```python
@dataclass(frozen=True, slots=True)
class EmployeeRecord:
    employee: Employee
    revision: EmployeeRevision
    binding: EmployeeAgentBinding
    grants: tuple[CapabilityGrant, ...]
```

`SqlAlchemyUnitOfWork.__enter__` creates a Session and repositories; `commit()` commits once; `__exit__` rolls back when uncommitted and always closes. Repository mapping converts JSON resource values to tuples and never returns ORM objects.

- [ ] **Step 5: 转绿并验证 migration**

```powershell
uv lock
uv sync --all-packages --all-groups
uv run pytest apps/company-service/tests/persistence/test_company_store.py -q
uv run alembic -c apps/company-service/alembic.ini upgrade head
uv run alembic -c apps/company-service/alembic.ini downgrade base
uv run alembic -c apps/company-service/alembic.ini upgrade head
```

Expected: tests pass and all migration commands exit 0.

- [ ] **Step 6: Commit**

```powershell
git add apps/company-service/pyproject.toml apps/company-service/alembic.ini apps/company-service/alembic apps/company-service/src/dsh_company/persistence apps/company-service/tests/persistence uv.lock
git commit -m "feat: persist company and employee facts"
```

### Task 3: 实现 Application 用例且创建员工不调用 DSH

**Files:**

- Create: `apps/company-service/src/dsh_company/application/__init__.py`
- Create: `apps/company-service/src/dsh_company/application/commands.py`
- Create: `apps/company-service/src/dsh_company/application/ports.py`
- Create: `apps/company-service/src/dsh_company/application/company_service.py`
- Create: `apps/company-service/tests/application/test_company_service.py`

- [ ] **Step 1: 写创建与修订用例测试**

```python
def test_create_employee_is_local_and_does_not_start_dsh(fake_uow, forbidden_gateway) -> None:
    service = CompanyService(fake_uow, id_factory=SequentialIds())
    workspace = service.create_workspace(CreateWorkspace(name="内容公司"))

    result = service.create_employee(CreateEmployee(
        workspace_id=workspace.id,
        display_name="编辑",
        responsibility="写作",
        runtime_profile="workspace_read",
        model="deepseek-v4-flash",
        grants=(),
    ))

    assert result.employee.display_name == "编辑"
    assert result.binding.dsh_session_id.startswith("employee-")
    assert forbidden_gateway.calls == []


def test_revise_employee_appends_revision_without_rewriting_old_one(fake_uow) -> None:
    seeded = seed_employee(fake_uow)
    service = CompanyService(fake_uow, id_factory=SequentialIds())

    revised = service.revise_employee(ReviseEmployee(
        employee_id=seeded.employee.id,
        responsibility="写作和事实核查",
        runtime_profile="workspace_read",
        model="deepseek-v4-flash",
        grants=(),
    ))

    assert revised.revision.revision_number == 2
    assert fake_uow.employee_revisions(seeded.employee.id)[0].responsibility == "写作"
```

- [ ] **Step 2: 确认红灯**

Run: `uv run pytest apps/company-service/tests/application/test_company_service.py -q`

Expected: collection FAIL because application modules are absent.

- [ ] **Step 3: 定义命令和端口**

```python
@dataclass(frozen=True, slots=True)
class CreateWorkspace:
    name: str


@dataclass(frozen=True, slots=True)
class GrantInput:
    action: str
    level: CapabilityLevel
    resource_kind: str
    resource_values: tuple[str, ...]
    requires_approval: bool


@dataclass(frozen=True, slots=True)
class CreateEmployee:
    workspace_id: WorkspaceId
    display_name: str
    responsibility: str
    runtime_profile: str
    model: str
    grants: tuple[GrantInput, ...]
```

`UnitOfWork` exposes `workspaces` and `employees`, plus `commit()`. Do not add a DSH port to this service; Phase 2 creation cannot touch runtime.

- [ ] **Step 4: 实现 CompanyService**

`create_employee` must:

1. read and validate the Workspace;
2. create Employee/Revision/Binding;
3. merge the three default grants with explicit grants by action, explicit input winning;
4. set each grant's `employee_revision_id` to the new revision;
5. persist and commit once;
6. return `EmployeeRecord`.

`revise_employee` appends a revision, replaces the employee's `current_revision_id`, attaches a complete grant snapshot, and leaves Binding unchanged.

- [ ] **Step 5: 转绿、检查依赖与提交**

```powershell
uv run pytest apps/company-service/tests/application/test_company_service.py -q
uv run python -c "import dsh_company.application.company_service, sys; assert 'fastapi' not in sys.modules"
git add apps/company-service/src/dsh_company/application apps/company-service/tests/application
git commit -m "feat: add local company management use cases"
```

### Task 4: 暴露 Workspace/Employee API 与 OpenAPI

**Files:**

- Create: `apps/company-service/src/dsh_company/api/errors.py`
- Create: `apps/company-service/src/dsh_company/api/schemas.py`
- Create: `apps/company-service/src/dsh_company/api/company.py`
- Create: `apps/company-service/src/dsh_company/foundation/assembly.py`
- Modify: `apps/company-service/src/dsh_company/foundation/app.py`
- Create: `apps/company-service/tests/api/test_company_api.py`
- Modify: `packages/contracts/openapi/openapi.json`
- Modify: `packages/contracts/openapi/source-revision.json`
- Modify: `apps/dsh-company-plugin/src/contracts/generated/openapi.ts`

- [ ] **Step 1: 写 API 行为测试**

```python
def test_create_workspace_and_employee_without_provider_credentials(client) -> None:
    workspace = client.post("/workspaces", json={"name": "内容公司"})
    employee = client.post(
        f"/workspaces/{workspace.json()['id']}/employees",
        json={
            "display_name": "编辑",
            "responsibility": "撰写内容",
            "runtime_profile": "workspace_read",
            "model": "deepseek-v4-flash",
            "grants": [],
        },
    )

    assert workspace.status_code == 201
    assert employee.status_code == 201
    assert employee.json()["binding"]["dsh_session_id"].startswith("employee-")


def test_unknown_workspace_uses_stable_error_envelope(client) -> None:
    response = client.get("/workspaces/missing/employees")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "workspace_not_found"
    assert response.json()["error"]["correlation_id"]
```

- [ ] **Step 2: 确认红灯**

Run: `uv run pytest apps/company-service/tests/api/test_company_api.py -q`

Expected: FAIL with 404 for missing routes.

- [ ] **Step 3: 实现 schema、router 与 assembly**

Define transport types:

```python
class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class GrantCreate(BaseModel):
    action: str = Field(min_length=1, max_length=120)
    level: Literal[0, 1, 2, 3]
    resource_kind: str
    resource_values: list[str]
    requires_approval: bool


class EmployeeCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    responsibility: str = Field(min_length=1, max_length=4000)
    runtime_profile: Literal["workspace_read", "workspace_write", "network_denied"]
    model: str = Field(min_length=1, max_length=200)
    grants: list[GrantCreate] = []
```

Routes return 201 for create, 200 for list/get/revise, and map missing resources to the stable error envelope. `ComponentAssembly` supplies the router and UoW factory to `create_app`; API handlers call only `CompanyService`.

- [ ] **Step 4: 转绿并更新契约**

```powershell
uv run pytest apps/company-service/tests/api/test_company_api.py -q
$apiCommit = git rev-parse HEAD
pnpm run contracts:capture -- --api-commit $apiCommit
pnpm run contracts:generate
pnpm --filter @dsh/company-plugin typecheck
```

Expected: API tests pass and generated types contain Workspace and Employee schemas.

- [ ] **Step 5: Commit**

```powershell
git add apps/company-service/src/dsh_company/api apps/company-service/src/dsh_company/foundation apps/company-service/tests/api packages/contracts apps/dsh-company-plugin/src/contracts/generated/openapi.ts
git commit -m "feat: expose company and employee API"
```

### Task 5: 迁移最小 Host 生命周期和 loopback transport

**Files:**

- Create: `apps/dsh-company-plugin/src/host/config.ts`
- Create: `apps/dsh-company-plugin/src/host/lifecycle.ts`
- Create: `apps/dsh-company-plugin/src/host/plugin.ts`
- Create: `apps/dsh-company-plugin/src/host/service.ts`
- Create: `apps/dsh-company-plugin/src/remote-contract.ts`
- Create: `apps/dsh-company-plugin/src/remote.ts`
- Modify: `apps/dsh-company-plugin/src/index.ts`
- Modify: `apps/dsh-company-plugin/cordis.patch.yml`
- Create: `apps/dsh-company-plugin/tests/host-lifecycle.spec.ts`
- Create: `apps/dsh-company-plugin/tests/remote.spec.ts`

- [ ] **Step 1: 写 Host 启停与路径围栏测试**

Port the source tests from `multi-agent@2330adb` and change the contract to:

```typescript
expect(lifecycle.command()).toEqual([
  pythonPath, '-m', 'uvicorn', 'dsh_company.asgi:app',
  '--host', '127.0.0.1', '--port', String(port),
])
expect(resolveHostConfig(config).environment.DSH_COMPANY_DATA_ROOT).toBe(dataRoot)
expect(() => remote.request({ method: 'GET', path: '/outside' })).toThrow('route_not_allowed')
```

Allowed paths are `/health`, `/workspaces`, `/workspaces/*/employees`, and `/employees/*`; methods are GET/POST only in Phase 2.

- [ ] **Step 2: 确认红灯**

Run: `pnpm --filter @dsh/company-plugin test -- host-lifecycle.spec.ts remote.spec.ts`

Expected: tests FAIL because Host lifecycle and remote modules are absent.

- [ ] **Step 3: 适配最小实现**

Adapt only these patterns from the fixed source:

- child process start/health wait/ordered stop;
- credential value passed only to child environment when DSH execution is later requested;
- typed connection state;
- loopback HTTP request with path allowlist;
- credential update causes service restart.

Use names `CompanyHostLifecycle`, `CompanyPluginService`, `company`, `DSH_COMPANY_*`, and module `dsh_company.asgi`. Delete every old execution, worktree and M1–M7 route.

- [ ] **Step 4: 转绿并提交**

```powershell
pnpm --filter @dsh/company-plugin test -- host-lifecycle.spec.ts remote.spec.ts
pnpm --filter @dsh/company-plugin typecheck
pnpm --filter @dsh/company-plugin build
git add apps/dsh-company-plugin
git commit -m "port: adapt DSH host lifecycle from multi-agent@2330adb"
```

### Task 6: 构建 Workspace/Employee React 页面

**Files:**

- Modify: `apps/dsh-company-plugin/package.json`
- Create: `apps/dsh-company-plugin/src/client/api.ts`
- Create: `apps/dsh-company-plugin/src/client/controller.ts`
- Create: `apps/dsh-company-plugin/src/client/CompanyLauncher.tsx`
- Create: `apps/dsh-company-plugin/src/client/CompanySurface.tsx`
- Create: `apps/dsh-company-plugin/src/client/WorkspaceList.tsx`
- Create: `apps/dsh-company-plugin/src/client/EmployeeDirectory.tsx`
- Create: `apps/dsh-company-plugin/src/client/EmployeeForm.tsx`
- Create: `apps/dsh-company-plugin/src/client/locales.ts`
- Create: `apps/dsh-company-plugin/src/client/ui/Primitives.tsx`
- Create: `apps/dsh-company-plugin/src/client/*.module.css`
- Modify: `apps/dsh-company-plugin/src/client/index.ts`
- Create: `apps/dsh-company-plugin/tests/company-core.client.spec.tsx`
- Modify: `pnpm-lock.yaml`

- [ ] **Step 1: 写用户闭环测试**

```tsx
it('creates a workspace and employee without starting DSH execution', async () => {
  const remote = new FakeCompanyRemote()
  render(<CompanySurface remote={remote} />)

  await user.click(screen.getByRole('button', { name: '创建工作区' }))
  await user.type(screen.getByLabelText('名称'), '内容公司')
  await user.click(screen.getByRole('button', { name: '确认创建' }))
  await user.click(screen.getByRole('link', { name: '内容公司' }))
  await user.click(screen.getByRole('button', { name: '创建员工' }))
  await user.type(screen.getByLabelText('员工名称'), '编辑')
  await user.type(screen.getByLabelText('职责'), '撰写内容')
  await user.click(screen.getByRole('button', { name: '保存员工' }))

  expect(await screen.findByRole('heading', { name: '编辑' })).toBeVisible()
  expect(remote.executionCalls).toEqual([])
})
```

- [ ] **Step 2: 确认红灯**

Install React/Zod/Testing Library dependencies, then run the focused test. Expected: FAIL because the components are absent.

- [ ] **Step 3: 实现最小 API/controller/UI**

- `ProductApi` uses generated OpenAPI types and throws stable `ApiError`;
- controller loads Workspace list, selected Workspace employees, create commands and explicit loading/error states;
- launcher opens a dedicated Company overlay/page;
- Workspace is always required before Employee creation;
- Employee form exposes responsibility, runtime profile, model and advanced grant rows;
- the three default grants are displayed as defaults but saved by the server even if the form sends none;
- all Dialog fields have labels, validation text, Escape close, focus trap and trigger focus restore;
- Chinese and English strings come from the locale map.

- [ ] **Step 4: 转绿并做真实构建**

```powershell
pnpm install
pnpm --filter @dsh/company-plugin test -- company-core.client.spec.tsx
pnpm --filter @dsh/company-plugin typecheck
pnpm --filter @dsh/company-plugin build
```

Expected: focused test passes and both bundles build.

- [ ] **Step 5: Commit**

```powershell
git add apps/dsh-company-plugin pnpm-lock.yaml
git commit -m "feat: add workspace and employee management UI"
```

### Task 7: Phase 2 系统验收

**Files:**

- Create: `tests/system/tests/test_phase_2_company_core.py`
- Modify: `README.md`
- Modify: `docs/README.md`

- [ ] **Step 1: 写重启与隔离系统测试**

The test must start the ASGI app against a temporary file DB, create two Workspaces and one Employee each, dispose the app/database, recreate them from the same DB, and assert:

```python
assert [item["display_name"] for item in list_a.json()] == ["编辑 A"]
assert [item["display_name"] for item in list_b.json()] == ["编辑 B"]
assert list_a.json()[0]["binding"]["dsh_session_id"] != list_b.json()[0]["binding"]["dsh_session_id"]
```

- [ ] **Step 2: 确认红灯、接入真实 assembly、转绿**

Run the system test before assembly wiring. Expected: FAIL because the default app does not create persistence components. Wire `create_production_assembly(Settings())` to engine/UoW/router, then rerun and expect PASS.

- [ ] **Step 3: 完整门禁**

```powershell
uv run pytest tests/system/tests/test_phase_2_company_core.py -q
python tools/check.py
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit**

```powershell
git add tests/system README.md docs apps/company-service/src/dsh_company/foundation
git commit -m "test: verify durable isolated company core"
```

## Phase 2 完成定义

- Workspace 和 Employee 可从 UI/API 创建；
- 创建流程完全本地，不需要 provider credential，不启动 DSH；
- EmployeeRevision 不可变，Binding 稳定且 Agent ID 等于 Session ID；
- 基础工具默认存在，额外能力可配置等级和资源范围；
- SQLite 重启恢复和 Workspace 隔离通过；
- OpenAPI、TypeScript、Host/Client build 和公共门禁全绿。

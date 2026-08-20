# Phase 4 Permissions Approvals and Delegation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Employee 在 Workspace、员工版本、Work Node 临时授权和 DSH Runtime 的共同边界内执行，并支持可审计的高等级审批与一次或多次显式员工委派。

**Architecture:** PolicyEngine 是纯 Domain 服务，先做资格与资源交集，再返回 allow/deny/require_approval；Application 在真正 dispatch 前重新求值。Approval 与 Delegation 是 Company DB 权威事实。Employee 通过 DSH 返回严格、完整的控制请求 JSON；Core 验证后才创建新 Graph Revision，模型文本本身没有授权效力。

**Tech Stack:** Phase 3 stack、Pydantic discriminated unions、SQLAlchemy/Alembic、React approval/delegation UI。

---

## 目标结构

```text
apps/company-service/src/dsh_company/
├── domain/policy.py
├── domain/approval.py
├── domain/delegation.py
├── application/governance_service.py
├── application/delegation_service.py
├── dsh_gateway/control_requests.py
├── policy/runtime_profiles.py
└── api/governance.py
apps/dsh-company-plugin/src/client/
├── CapabilityEditor.tsx
├── ApprovalInbox.tsx
└── DelegationView.tsx
```

### Task 1: 定义动作目录、权限交集和 Runtime Profile 上限

**Files:**

- Create: `apps/company-service/src/dsh_company/domain/policy.py`
- Create: `apps/company-service/src/dsh_company/policy/__init__.py`
- Create: `apps/company-service/src/dsh_company/policy/runtime_profiles.py`
- Create: `apps/company-service/tests/policy/test_policy_engine.py`
- Create: `apps/company-service/tests/policy/test_runtime_profiles.py`

- [ ] **Step 1: 写授权交集测试**

```python
def test_action_requires_every_layer_and_intersects_resources() -> None:
    decision = PolicyEngine().decide(ActionRequest(
        action="workspace.write",
        workspace_grant=grant("workspace.write", L2, {"repo-a", "repo-b"}),
        employee_grant=grant("workspace.write", L2, {"repo-a"}),
        node_grant=grant("workspace.write", L2, {"repo-a", "repo-c"}),
        runtime_grant=grant("workspace.write", L2, {"repo-a"}),
    ))

    assert decision.kind is DecisionKind.ALLOW
    assert decision.effective_resources == frozenset({"repo-a"})


def test_missing_layer_denies_instead_of_inheriting() -> None:
    decision = PolicyEngine().decide(action_request(employee_grant=None))
    assert decision.kind is DecisionKind.DENY
    assert decision.reason == "employee_not_granted"


def test_l3_or_explicit_flag_requires_approval() -> None:
    decision = PolicyEngine().decide(action_request(
        action="external.publish",
        level=L3,
        requires_approval=True,
    ))
    assert decision.kind is DecisionKind.REQUIRE_APPROVAL


def test_empty_resource_intersection_denies() -> None:
    decision = PolicyEngine().decide(action_request(
        workspace_resources={"repo-a"}, employee_resources={"repo-b"}
    ))
    assert decision.kind is DecisionKind.DENY
    assert decision.reason == "resource_scope_empty"
```

- [ ] **Step 2: 确认红灯**

Run policy tests. Expected: collection FAIL because policy modules are absent.

- [ ] **Step 3: 实现封闭动作目录和决策类型**

```python
ACTION_LEVELS: dict[str, CapabilityLevel] = {
    "conversation.respond": CapabilityLevel.L0,
    "workspace.read": CapabilityLevel.L1,
    "session.history.read": CapabilityLevel.L1,
    "work.delegate": CapabilityLevel.L1,
    "workspace.write": CapabilityLevel.L2,
    "tool.shell": CapabilityLevel.L2,
    "tool.network": CapabilityLevel.L2,
    "external.publish": CapabilityLevel.L3,
}


class DecisionKind(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    kind: DecisionKind
    reason: str
    effective_resources: frozenset[str] = frozenset()
```

Unknown action denies with `unknown_action`. Each known action requires all four layers. The effective set is the intersection; a grant using `("*",)` is the layer's unbounded value but does not expand other layers.

- [ ] **Step 4: 实现 DSH Runtime Profile 映射**

```python
RUNTIME_PROFILE_ACTIONS: dict[str, frozenset[str]] = {
    "workspace_read": frozenset({"conversation.respond", "workspace.read", "session.history.read", "work.delegate"}),
    "workspace_write": frozenset({"conversation.respond", "workspace.read", "session.history.read", "work.delegate", "workspace.write", "tool.shell", "tool.network"}),
    "network_denied": frozenset({"conversation.respond", "workspace.read", "session.history.read", "work.delegate"}),
}
```

No current profile grants `external.publish`. `workspace_write` is treated as network-capable because local shell can reach the network; users who need a hard network boundary must select `network_denied`. Even an approved action remains blocked if the chosen Runtime Profile does not expose it.

- [ ] **Step 5: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/policy -q
git add apps/company-service/src/dsh_company/domain/policy.py apps/company-service/src/dsh_company/policy apps/company-service/tests/policy
git commit -m "feat: enforce layered company capability policy"
```

### Task 2: 定义 Approval、Delegation、WorkEdge 与不可变图修订

**Files:**

- Modify: `apps/company-service/src/dsh_company/domain/ids.py`
- Modify: `apps/company-service/src/dsh_company/domain/work.py`
- Create: `apps/company-service/src/dsh_company/domain/approval.py`
- Create: `apps/company-service/src/dsh_company/domain/delegation.py`
- Create: `apps/company-service/tests/domain/test_governance.py`
- Create: `apps/company-service/tests/domain/test_delegation.py`

- [ ] **Step 1: 写审批状态和图修订测试**

```python
def test_approval_can_be_decided_once() -> None:
    approval = Approval.request(
        approval_id=ApprovalId("approval-1"), workspace_id=WorkspaceId("ws-1"),
        work_id=WorkId("work-1"), node_id=WorkNodeId("node-1"),
        action="external.publish", resources=("channel-a",), reason="发布到外部渠道",
    )
    approved = approval.approve(decided_by="user")

    assert approved.status is ApprovalStatus.APPROVED
    with pytest.raises(ValueError, match="already decided"):
        approved.reject(decided_by="user")


def test_delegation_creates_new_revision_without_rewriting_completed_nodes() -> None:
    original = graph_with_completed_sibling_and_running_parent()
    proposal = DelegationProposal(
        proposer_employee_id=EmployeeId("emp-a"),
        target_employee_id=EmployeeId("emp-b"),
        objective="事实核查",
        acceptance_criteria=("列出来源",),
        required_actions=("workspace.read",),
        resource_values=("ws-1",),
    )

    revised, delegation = apply_delegation(original, proposal, ids=SequentialIds())

    assert revised.revision_number == original.revision_number + 1
    assert revised.nodes[original.nodes[0].id] == original.nodes[0]
    assert revised.edges[-1].kind is WorkEdgeKind.DELEGATES_TO
    assert delegation.target_employee_id == EmployeeId("emp-b")
```

- [ ] **Step 2: 确认红灯**

Run the domain tests. Expected: FAIL for missing Approval/Delegation/WorkEdge types.

- [ ] **Step 3: 实现 Approval 与 Delegation 类型**

Approval statuses are `pending`, `approved`, `rejected`, `cancelled`; only pending can transition. Store action, resource tuple, reason, requested_at, decided_at and decided_by.

Delegation fields:

```python
id: DelegationId
workspace_id: WorkspaceId
work_id: WorkId
source_node_id: WorkNodeId
target_node_id: WorkNodeId
proposer_employee_id: EmployeeId
target_employee_id: EmployeeId
graph_revision_id: WorkGraphRevisionId
status: Literal["proposed", "accepted", "rejected", "completed"]
created_at: datetime
```

Add `WorkEdgeKind = depends_on | delegates_to` and `WorkEdge(from_node_id, to_node_id, kind)`. `WorkGraphRevision` now owns tuples of node IDs and edges. `apply_delegation` copies all prior nodes/edges, adds one target node and a `delegates_to` edge, and creates a new immutable revision.

Add `WAITING_APPROVAL = "waiting_approval"` to `WorkNodeStatus`; it can transition only to READY after an approved request, or FAILED after rejection.

- [ ] **Step 4: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/domain/test_governance.py apps/company-service/tests/domain/test_delegation.py -q
git add apps/company-service/src/dsh_company/domain apps/company-service/tests/domain
git commit -m "feat: define approvals and delegation revisions"
```

### Task 3: 持久化授权上限、临时授权、审批、委派和边

**Files:**

- Create: `apps/company-service/alembic/versions/0003_governance.py`
- Modify: `apps/company-service/src/dsh_company/persistence/models.py`
- Modify: `apps/company-service/src/dsh_company/persistence/work_models.py`
- Create: `apps/company-service/src/dsh_company/persistence/governance_repositories.py`
- Modify: `apps/company-service/src/dsh_company/persistence/uow.py`
- Create: `apps/company-service/tests/persistence/test_governance_store.py`

- [ ] **Step 1: 写持久化测试**

```python
def test_pending_approval_and_delegation_revision_survive_restart(sqlite_uow) -> None:
    seed_governed_work(sqlite_uow)
    with sqlite_uow as uow:
        approval = uow.approvals.get(ApprovalId("approval-1"))
        delegation = uow.delegations.get(DelegationId("delegation-1"))
        graph = uow.works.get_revision(WorkGraphRevisionId("graph-2"))

    assert approval.status is ApprovalStatus.PENDING
    assert delegation.status == "accepted"
    assert graph.edges[-1].kind is WorkEdgeKind.DELEGATES_TO
```

- [ ] **Step 2: 确认红灯并创建 migration**

Expected initial FAIL. Create:

```text
workspace_capability_grants(workspace_id, action, level, resource_kind, resource_values_json, requires_approval, PK(workspace_id, action))
node_capability_grants(node_id, action, level, resource_kind, resource_values_json, requires_approval, PK(node_id, action))
work_edges(id PK, graph_revision_id FK, from_node_id FK, to_node_id FK, kind)
approvals(id PK, workspace_id FK, work_id FK, node_id FK, action, resources_json, reason, status, requested_at, decided_at, decided_by)
delegations(id PK, workspace_id FK, work_id FK, source_node_id FK, target_node_id FK, proposer_employee_id FK, target_employee_id FK, graph_revision_id FK, status, created_at)
```

No approval stores raw model output; `reason` is bounded to 500 characters.

- [ ] **Step 3: 实现 repositories、转绿、migration round trip**

```powershell
uv run pytest apps/company-service/tests/persistence/test_governance_store.py -q
uv run alembic -c apps/company-service/alembic.ini upgrade head
uv run alembic -c apps/company-service/alembic.ini downgrade -1
uv run alembic -c apps/company-service/alembic.ini upgrade head
git add apps/company-service/alembic apps/company-service/src/dsh_company/persistence apps/company-service/tests/persistence/test_governance_store.py
git commit -m "feat: persist company governance facts"
```

### Task 4: 解析 DSH 控制请求并实施审批边界

**Files:**

- Create: `apps/company-service/src/dsh_company/dsh_gateway/control_requests.py`
- Modify: `apps/company-service/src/dsh_company/dsh_gateway/contracts.py`
- Modify: `apps/company-service/src/dsh_company/dsh_gateway/adapter.py`
- Create: `apps/company-service/src/dsh_company/application/governance_service.py`
- Modify: `apps/company-service/src/dsh_company/application/runtime_coordinator.py`
- Create: `apps/company-service/tests/dsh_gateway/test_control_requests.py`
- Create: `apps/company-service/tests/application/test_governance_service.py`

- [ ] **Step 1: 写严格控制请求解析测试**

```python
def test_parses_complete_delegation_request_only() -> None:
    parsed = parse_control_request(json.dumps({
        "kind": "delegation",
        "target_employee_id": "emp-b",
        "objective": "事实核查",
        "acceptance_criteria": ["列出来源"],
        "required_actions": ["workspace.read"],
        "resource_values": ["ws-1"],
        "reason": "需要独立核查",
    }))
    assert isinstance(parsed, DelegationControlRequest)


@pytest.mark.parametrize("raw", [
    '{"kind":"delegation"}',
    'prefix {"kind":"delegation"}',
    '{"kind":"approval","action":"unknown.action","resources":[]}',
])
def test_rejects_partial_embedded_or_unknown_requests(raw) -> None:
    with pytest.raises(ValueError):
        parse_control_request(raw)
```

- [ ] **Step 2: 写批准前不得 dispatch 的测试**

```python
def test_high_level_action_waits_for_approval(fake_uow, recording_gateway) -> None:
    service = GovernanceService(fake_uow, PolicyEngine())
    approval = service.authorize(action_command("external.publish"))

    assert approval.status is ApprovalStatus.PENDING
    assert recording_gateway.calls == []
    assert fake_uow.node.status is WorkNodeStatus.WAITING_APPROVAL


def test_approved_action_is_rechecked_before_dispatch(fake_uow, policy_engine) -> None:
    approval = approved_fixture(action="workspace.write")
    fake_uow.remove_employee_grant("workspace.write")

    result = GovernanceService(fake_uow, policy_engine).resume_approved(approval.id)

    assert result.kind is DecisionKind.DENY
    assert fake_uow.dispatches == []
```

- [ ] **Step 3: 确认红灯并实现解析器**

The parser accepts at most 32 KiB and requires the entire trimmed response to be one JSON object. Use Pydantic discriminated unions for `delegation` and `approval`; reject extra fields and unknown actions. GatewayResult returns the typed request in memory and still creates a DSH result reference only for normal output.

- [ ] **Step 4: 实现 GovernanceService**

`authorize` loads four grant layers and returns:

- ALLOW: coordinator may dispatch;
- DENY: node becomes BLOCKED with the closed reason;
- REQUIRE_APPROVAL: create pending Approval and set node `waiting_approval`.

`approve`/`reject` use optimistic status update. `resume_approved` recomputes current policy before dispatch. Rejection transitions the waiting node to FAILED/`approval_rejected` and creates a CompanyEvent.

- [ ] **Step 5: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/dsh_gateway/test_control_requests.py apps/company-service/tests/application/test_governance_service.py -q
git add apps/company-service/src/dsh_company/dsh_gateway apps/company-service/src/dsh_company/application apps/company-service/tests
git commit -m "feat: enforce approval before governed actions"
```

### Task 5: 实现经过验证的 Employee 委派闭环

**Files:**

- Create: `apps/company-service/src/dsh_company/application/delegation_service.py`
- Modify: `apps/company-service/src/dsh_company/application/runtime_coordinator.py`
- Create: `apps/company-service/tests/application/test_delegation_service.py`

- [ ] **Step 1: 写资格、越权和恢复父节点测试**

```python
def test_delegation_requires_same_workspace_active_target_and_capabilities(fake_uow) -> None:
    result = DelegationService(fake_uow, PolicyEngine()).propose(valid_proposal(target="emp-b"))
    assert result.delegation.status == "accepted"
    assert result.target_node.status is WorkNodeStatus.READY


def test_delegation_cannot_expand_resource_scope(fake_uow) -> None:
    proposal = valid_proposal(resources=("repo-outside",))
    with pytest.raises(DelegationDenied, match="resource_scope_empty"):
        DelegationService(fake_uow, PolicyEngine()).propose(proposal)


def test_completed_child_resumes_parent_with_reference_not_transcript(fake_uow) -> None:
    service = DelegationService(fake_uow, PolicyEngine())
    resumed = service.child_completed(
        DelegationId("delegation-1"),
        ArtifactReferenceId("artifact-child"),
    )
    assert resumed.parent_node.status is WorkNodeStatus.READY
    assert resumed.input_references == (ArtifactReferenceId("artifact-child"),)
```

- [ ] **Step 2: 确认红灯并实现服务**

The service validates proposer/target Workspace and active status, `work.delegate` policy, target required actions/resources, and graph acyclicity. Accepted proposal creates a new revision, READY child, BLOCKED parent with `waiting_delegation`, and Delegation. Coordinator dispatches the child. Completion adds only ArtifactReference ID to the parent and creates a new parent Attempt on the same parent Employee Session.

Rejected proposals create a rejected Delegation and a safe CompanyEvent; they do not mutate the graph.

- [ ] **Step 3: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/application/test_delegation_service.py -q
git add apps/company-service/src/dsh_company/application apps/company-service/tests/application/test_delegation_service.py
git commit -m "feat: add bounded employee delegation"
```

### Task 6: 暴露治理 API 和 UI

**Files:**

- Create: `apps/company-service/src/dsh_company/api/governance.py`
- Modify: `apps/company-service/src/dsh_company/api/schemas.py`
- Modify: `apps/company-service/src/dsh_company/foundation/assembly.py`
- Create: `apps/company-service/tests/api/test_governance_api.py`
- Modify: `apps/dsh-company-plugin/src/client/api.ts`
- Create: `apps/dsh-company-plugin/src/client/CapabilityEditor.tsx`
- Create: `apps/dsh-company-plugin/src/client/ApprovalInbox.tsx`
- Create: `apps/dsh-company-plugin/src/client/DelegationView.tsx`
- Modify: `apps/dsh-company-plugin/src/client/WorkDetail.tsx`
- Create: `apps/dsh-company-plugin/tests/governance.client.spec.tsx`
- Modify: OpenAPI snapshot/generated types

- [ ] **Step 1: 写 API/UI 测试**

API covers:

```text
PUT  /workspaces/{id}/capabilities
GET  /workspaces/{id}/approvals
POST /approvals/{id}/approve
POST /approvals/{id}/reject
POST /works/{id}/delegations
GET  /works/{id}/delegations
```

UI test approves one pending request and asserts only then the refreshed node leaves `waiting_approval`; another test rejects and asserts no dispatch call. Delegation form must show only eligible active Employees returned by the server.

- [ ] **Step 2: 确认红灯、实现 API/UI、更新契约**

Implement stable 409 errors `approval_already_decided` and `delegation_denied`. UI displays action, exact resource scope, reason and requesting Employee; destructive/external approvals require explicit buttons, never click-through row actions.

Run:

```powershell
uv run pytest apps/company-service/tests/api/test_governance_api.py -q
$apiCommit = git rev-parse HEAD
pnpm run contracts:capture -- --api-commit $apiCommit
pnpm run contracts:generate
pnpm --filter @dsh/company-plugin test -- governance.client.spec.tsx
pnpm --filter @dsh/company-plugin typecheck
pnpm --filter @dsh/company-plugin build
```

Expected: all commands pass.

- [ ] **Step 3: Commit**

```powershell
git add apps/company-service apps/dsh-company-plugin packages/contracts
git commit -m "feat: add company governance experience"
```

### Task 7: Phase 4 系统验收

**Files:**

- Create: `tests/system/tests/test_phase_4_governance.py`
- Modify: `tools/check.py`
- Modify: `README.md`

- [ ] **Step 1: 写系统场景**

The keyless scenario must prove:

1. L2 write denied when any grant layer is missing;
2. pending L3 approval causes zero DSH dispatches;
3. approval followed by grant removal still denies on recheck;
4. rejection never dispatches;
5. same-Workspace eligible delegation creates revision 2 and child Attempt;
6. cross-Workspace target and broader resources reject;
7. child completion resumes parent using only ArtifactReference ID;
8. restart preserves pending Approval and accepted Delegation.

- [ ] **Step 2: 转绿与完整门禁**

```powershell
uv run pytest tests/system/tests/test_phase_4_governance.py -q
python tools/check.py
git diff --check
```

Expected: all scenarios and gates pass.

- [ ] **Step 3: Commit**

```powershell
git add tests/system tools/check.py README.md
git commit -m "test: verify permissions approvals and delegation"
```

## Phase 4 完成定义

- 每个动作都经过四层权限与资源交集；
- Runtime Profile 不能被 Company 授权扩大；
- Approval 在动作前创建，决定一次，批准后再次校验；
- Delegation 只在同 Workspace、同资源边界和目标能力满足时接受；
- 委派创建新 Graph Revision，不重写已完成事实；
- DSH 控制请求严格解析但不自动成为权威；
- API/UI/重启与 keyless 系统门禁全绿。

# Phase 5 Work Graph Evaluation and Business Plugins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Direct 基线上交付持久多节点 Work Graph、Star/Graph/Battle 策略、确定性 Employee 选择、MASEval 系统评测和不污染 Core 的业务插件契约。

**Architecture:** DurableGraphEngine 只根据 Company DB 图事实求就绪节点并调用既有 RuntimeCoordinator；它不运行 LLM。策略只是生成经过同一验证器的图。MASEval 0.5.1 通过薄 AgentAdapter 调用完整 Company 系统并读取系统指标，不进入生产依赖。业务插件注册命名空间化能力和确定性模板，通过公开 API 使用 Core，不加载任意后端代码。

**Tech Stack:** Phase 4 stack、拓扑排序、bounded executor、MASEval 0.5.1 dev dependency、React strategy forms、OpenAPI/TypeScript plugin SDK。

---

## 目标结构

```text
apps/company-service/src/dsh_company/
├── orchestration/
│   ├── contracts.py
│   ├── graph_validation.py
│   ├── durable_graph.py
│   ├── selector.py
│   └── strategies.py
├── evaluation/
│   ├── models.py
│   ├── runner.py
│   └── maseval_adapter.py
├── business_plugins/
│   ├── manifest.py
│   ├── registry.py
│   └── templates.py
└── api/plugins.py
packages/company-plugin-sdk/
examples/content-studio-plugin/
benchmarks/company/
```

### Task 1: 完成多节点图模型与 DAG 验证

**Files:**

- Modify: `apps/company-service/src/dsh_company/domain/work.py`
- Create: `apps/company-service/src/dsh_company/orchestration/__init__.py`
- Create: `apps/company-service/src/dsh_company/orchestration/graph_validation.py`
- Create: `apps/company-service/tests/orchestration/test_graph_validation.py`

- [ ] **Step 1: 写边语义、环和完成历史测试**

```python
def test_valid_graph_accepts_all_four_edge_kinds() -> None:
    graph = graph_fixture(
        nodes=("research", "draft", "review", "summary"),
        edges=(
            ("research", "draft", "depends_on"),
            ("draft", "review", "reviews"),
            ("research", "summary", "summarizes"),
            ("draft", "summary", "delegates_to"),
        ),
    )
    GraphValidator().validate(graph)


def test_cycle_is_rejected_with_path() -> None:
    graph = graph_fixture(nodes=("a", "b", "c"), edges=(
        ("a", "b", "depends_on"), ("b", "c", "depends_on"), ("c", "a", "depends_on"),
    ))
    with pytest.raises(InvalidGraph, match="a -> b -> c -> a"):
        GraphValidator().validate(graph)


def test_new_revision_cannot_rewrite_completed_node() -> None:
    previous = graph_with_completed_node("node-a")
    candidate = replace_node_objective(previous, "node-a", "rewritten")
    with pytest.raises(InvalidGraph, match="completed_node_changed"):
        GraphValidator().validate_revision(previous, candidate)
```

- [ ] **Step 2: 确认红灯**

Run: `uv run pytest apps/company-service/tests/orchestration/test_graph_validation.py -q`

Expected: collection FAIL because graph validation is absent.

- [ ] **Step 3: 扩展封闭图类型**

`WorkEdgeKind` becomes:

```python
class WorkEdgeKind(StrEnum):
    DEPENDS_ON = "depends_on"
    DELEGATES_TO = "delegates_to"
    REVIEWS = "reviews"
    SUMMARIZES = "summarizes"
```

`WorkNodeStatus` includes `DRAFT`, `READY`, `RUNNING`, `WAITING_APPROVAL`, `BLOCKED`, `COMPLETED`, `FAILED`, `CANCELLED`. Node adds `required_actions`, `resource_values`, `input_references`, `output_references`, `max_attempts`, and `attempt_count`.

- [ ] **Step 4: 实现验证器**

Validation rules:

1. at least one node;
2. unique node/edge IDs;
3. every edge endpoint exists;
4. no self-edge;
5. Kahn topological sort visits all nodes;
6. assigned Employee and Revision IDs are nonblank;
7. completed/failed/cancelled nodes from previous revision are byte-for-byte equal;
8. every input reference resolves to an ArtifactReference or an upstream node;
9. all required actions exist in the action catalog.

Cycle diagnostics use a deterministic DFS over sorted node IDs to produce one path.

- [ ] **Step 5: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/orchestration/test_graph_validation.py -q
git add apps/company-service/src/dsh_company/domain/work.py apps/company-service/src/dsh_company/orchestration apps/company-service/tests/orchestration
git commit -m "feat: validate immutable company work graphs"
```

### Task 2: 实现 DurableGraphEngine 的就绪、并发和失败协调

**Files:**

- Create: `apps/company-service/src/dsh_company/orchestration/contracts.py`
- Create: `apps/company-service/src/dsh_company/orchestration/durable_graph.py`
- Modify: `apps/company-service/src/dsh_company/application/runtime_coordinator.py`
- Modify: `apps/company-service/src/dsh_company/foundation/assembly.py`
- Create: `apps/company-service/tests/orchestration/test_durable_graph.py`

- [ ] **Step 1: 写就绪与并发测试**

```python
def test_only_nodes_with_completed_dependencies_become_ready(engine, graph_store) -> None:
    graph_store.save(graph_fixture(nodes=("a", "b", "c"), edges=(
        ("a", "c", "depends_on"), ("b", "c", "depends_on"),
    ), statuses={"a": "completed", "b": "running", "c": "draft"}))

    ready = engine.dispatch_ready_nodes(WorkId("work-1"))

    assert ready == ()


def test_dispatch_is_bounded_and_command_ids_are_stable(engine, coordinator) -> None:
    seed_ten_independent_ready_nodes(engine.store)
    dispatched = engine.dispatch_ready_nodes(WorkId("work-1"))

    assert len(coordinator.active_calls) == 4
    assert [item.command_id for item in dispatched[:2]] == [
        "work-1:graph-1:node-1:attempt-1",
        "work-1:graph-1:node-2:attempt-1",
    ]


def test_failed_dependency_blocks_downstream_with_explicit_reason(engine) -> None:
    seed_failed_upstream(engine.store)
    engine.reconcile(WorkId("work-1"))
    assert engine.store.node("downstream").status is WorkNodeStatus.BLOCKED
    assert engine.store.node("downstream").failure_code == "dependency_failed"
```

- [ ] **Step 2: 确认红灯**

Run durable engine tests. Expected: collection FAIL.

- [ ] **Step 3: 定义 OrchestrationEngine 端口**

```python
class OrchestrationEngine(Protocol):
    def start(self, graph_revision_id: WorkGraphRevisionId) -> None: ...
    def dispatch_ready_nodes(self, work_id: WorkId) -> tuple[ExecutionLink, ...]: ...
    def record_completion(self, node_id: WorkNodeId, attempt_id: AttemptId, result_reference: ArtifactReferenceId) -> None: ...
    def record_failure(self, node_id: WorkNodeId, attempt_id: AttemptId, reason: str) -> None: ...
    def request_cancel(self, node_id: WorkNodeId) -> None: ...
    def reconcile(self, work_id: WorkId) -> None: ...
```

- [ ] **Step 4: 实现持久调度**

`DurableGraphEngine` loads the current revision in one short transaction, computes eligible DRAFT/BLOCKED nodes, reevaluates PolicyEngine, changes allowed nodes to READY, creates attempts until `runtime_concurrency` capacity, commits, then calls RuntimeCoordinator after commit. Completion/failure triggers another dispatch pass.

Edge semantics:

- `depends_on`: all upstream COMPLETED;
- `reviews`: reviewed upstream COMPLETED and its output becomes input;
- `summarizes`: all upstream terminal and at least one COMPLETED; failed inputs are represented by safe status references;
- `delegates_to`: target follows Phase 4 delegation status.

No exception string changes state; use closed codes.

- [ ] **Step 5: 实现 retry/reconcile**

Retry creates a new Attempt while `attempt_count < max_attempts`; completed Attempt facts stay immutable. Restart applies Phase 3 `runtime_process_lost`, then leaves user/engine to retry. `reconcile` never queries an unsupported DSH observe API.

- [ ] **Step 6: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/orchestration/test_durable_graph.py -q
git add apps/company-service/src/dsh_company/orchestration apps/company-service/src/dsh_company/application/runtime_coordinator.py apps/company-service/src/dsh_company/foundation/assembly.py apps/company-service/tests/orchestration
git commit -m "feat: add durable company graph engine"
```

### Task 3: 实现 Direct、Star、Graph、Battle 与确定性 Employee Selector

**Files:**

- Create: `apps/company-service/src/dsh_company/orchestration/selector.py`
- Create: `apps/company-service/src/dsh_company/orchestration/strategies.py`
- Create: `apps/company-service/tests/orchestration/test_selector.py`
- Create: `apps/company-service/tests/orchestration/test_strategies.py`

- [ ] **Step 1: 写资格过滤测试**

```python
def test_selector_filters_before_ranking_and_never_selects_all_by_default() -> None:
    candidates = Selector().eligible(
        employees=employee_fixtures(8),
        required_actions=("workspace.read",),
        resources=("ws-1",),
        delegation_allowlist=frozenset({"emp-2", "emp-3", "emp-4"}),
    )

    assert [item.employee_id for item in candidates] == ["emp-2", "emp-3", "emp-4"]
    assert Selector().choose(candidates, limit=2) == candidates[:2]
```

- [ ] **Step 2: 写策略形状测试**

```python
def test_battle_builds_parallel_workers_and_one_summary_node() -> None:
    graph = StrategyFactory().battle(
        work=work_fixture(),
        participants=(employee("emp-a"), employee("emp-b"), employee("emp-c")),
        summarizer=employee("emp-s"),
        objective="提出品牌方案",
        criteria=("列出依据",),
    )

    assert len(graph.nodes) == 4
    assert [edge.kind for edge in graph.edges] == [
        WorkEdgeKind.SUMMARIZES,
        WorkEdgeKind.SUMMARIZES,
        WorkEdgeKind.SUMMARIZES,
    ]
    assert graph.nodes[-1].assigned_employee_id == EmployeeId("emp-s")
```

- [ ] **Step 3: 确认红灯并实现 Selector**

Eligibility intersection is exactly: same Workspace, ACTIVE, required actions, resources, delegation allowlist, approval policy. Ranking is stable by explicit user order then Employee ID. No learned ranking or performance score enters Phase 5.

- [ ] **Step 4: 实现策略工厂**

- Direct: existing one node;
- Star: coordinator Employee summary node plus user-defined child objectives;
- Graph: explicit node/edge request, validated by GraphValidator;
- Battle: 2–4 distinct participant nodes plus one summarizer, every edge participant→summary with `summarizes`.

Strategy factory produces DRAFT graphs only; Core validates, persists and starts them. Battle summary instruction must say “整理共同点、去重并明确列出分歧，不替用户作最终决定”。

- [ ] **Step 5: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/orchestration/test_selector.py apps/company-service/tests/orchestration/test_strategies.py -q
git add apps/company-service/src/dsh_company/orchestration apps/company-service/tests/orchestration
git commit -m "feat: add explicit company collaboration strategies"
```

### Task 4: 暴露多策略 API 和可解释 UI

**Files:**

- Modify: `apps/company-service/src/dsh_company/api/work.py`
- Modify: `apps/company-service/src/dsh_company/api/schemas.py`
- Create: `apps/company-service/tests/api/test_graph_api.py`
- Create: `apps/dsh-company-plugin/src/client/StrategyComposer.tsx`
- Create: `apps/dsh-company-plugin/src/client/WorkGraphView.tsx`
- Create: `apps/dsh-company-plugin/src/client/BattleView.tsx`
- Modify: `apps/dsh-company-plugin/src/client/WorkDetail.tsx`
- Modify: `apps/dsh-company-plugin/src/client/locales.ts`
- Create: `apps/dsh-company-plugin/tests/work-graph.client.spec.tsx`
- Modify: OpenAPI snapshot/generated types

- [ ] **Step 1: 写 API 和 UI 测试**

API creation accepts a discriminated union:

```python
class DirectStrategyInput(BaseModel):
    kind: Literal["direct"]
    employee_id: str


class BattleStrategyInput(BaseModel):
    kind: Literal["battle"]
    participant_employee_ids: list[str] = Field(min_length=2, max_length=4)
    summarizer_employee_id: str
```

Star and Graph inputs include explicit nodes/edges and assigned Employee IDs. Tests reject duplicated Battle participants, cycles, ineligible employees and unknown actions with stable 422/409 codes.

UI test selects Battle, chooses three eligible Employees and a summarizer, submits, then asserts three parallel node cards and one summary node connected by accessible textual dependency labels.

- [ ] **Step 2: 确认红灯、实现、更新契约**

The UI is a strategy-specific form, not a generic visual workflow editor. Graph view renders status, assigned Employee, dependencies, attempts, Approval and failure code from server projection. Color is supplementary; every state has text/icon/ARIA label.

Run API test, contract capture/generation, focused Vitest, typecheck and build. Expected: all pass.

- [ ] **Step 3: Commit**

```powershell
git add apps/company-service apps/dsh-company-plugin packages/contracts
git commit -m "feat: add multi-employee work graph experience"
```

### Task 5: 建立固定公司任务集和 MASEval 0.5.1 Adapter

**Files:**

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `apps/company-service/src/dsh_company/evaluation/__init__.py`
- Create: `apps/company-service/src/dsh_company/evaluation/models.py`
- Create: `apps/company-service/src/dsh_company/evaluation/runner.py`
- Create: `apps/company-service/src/dsh_company/evaluation/maseval_adapter.py`
- Create: `apps/company-service/tests/evaluation/test_metrics.py`
- Create: `apps/company-service/tests/evaluation/test_maseval_adapter.py`
- Create: `benchmarks/company/tasks.jsonl`
- Create: `benchmarks/company/README.md`

- [ ] **Step 1: 添加 dev-only MASEval 依赖**

Add `maseval==0.5.1` to a separate dependency group `evaluation`; never add it to Company Service runtime dependencies. Run `uv lock` and `uv sync --group evaluation`.

- [ ] **Step 2: 写指标和 adapter 测试**

```python
def test_metrics_compare_complete_systems() -> None:
    metrics = compute_metrics(run_fixture(
        milestones=(True, True, False), token_count=1200, duration_ms=800,
        user_interventions=1, duplicate_nodes=0, policy_violations=0,
    ))
    assert metrics.milestone_rate == pytest.approx(2 / 3)
    assert metrics.policy_invariants_passed is True


def test_maseval_adapter_runs_company_strategy_and_returns_system_summary(fake_client) -> None:
    adapter = CompanyStrategyAgentAdapter(
        fake_client, workspace_id="ws-1", strategy="battle", name="dsh-company-battle"
    )
    result = adapter.run("提出品牌方案")

    assert json.loads(result)["status"] == "completed"
    assert adapter.get_messages().to_list()[-1]["role"] == "assistant"
    assert "raw_model_output" not in result
```

- [ ] **Step 3: 确认红灯并实现评测模型**

`EvaluationRun` captures task set version, strategy, model, Employee revisions, runtime profiles, start/end, Work ID and metrics. Metrics are task success, milestone rate, acceptance rate, token count, duration, user interventions, invalid delegations, duplicate nodes, policy violations and recovery outcome. Evaluation records live under benchmark output, not production Company tables.

- [ ] **Step 4: 实现 MASEval adapter**

Use official framework-agnostic API:

```python
from maseval import AgentAdapter
from maseval.core.history import MessageHistory


class CompanyStrategyAgentAdapter(AgentAdapter):
    def __init__(self, client, *, workspace_id: str, strategy: str, name: str) -> None:
        super().__init__(client, name)
        self._client = client
        self._workspace_id = workspace_id
        self._strategy = strategy
        self._messages: list[dict[str, str]] = []

    def _run_agent(self, query: str) -> str:
        self._messages.append({"role": "user", "content": query})
        summary = self._client.run_and_wait(self._workspace_id, self._strategy, query)
        result = json.dumps(summary, ensure_ascii=False, sort_keys=True)
        self._messages.append({"role": "assistant", "content": result})
        return result

    def get_messages(self) -> MessageHistory:
        return MessageHistory(self._messages)
```

`run_and_wait` returns only system outcome and metrics, never DSH transcript. Tests use a fake client; system benchmark uses the keyless Company Service.

- [ ] **Step 5: 创建第一批任务族**

`tasks.jsonl` contains versioned deterministic fixtures for:

- Direct single-employee completion;
- parallel research/content Battle;
- dependency chain;
- approval allow/reject;
- restart recovery;
- two-Employee Session isolation;
- DSH endpoint unavailable.

Each row contains `task_id`, `family`, `objective`, `acceptance_checks`, `allowed_strategies`, `max_tokens`, `max_duration_ms`, and `max_user_interventions`. No provider credential or copyrighted benchmark content is committed.

- [ ] **Step 6: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/evaluation -q
uv run --group evaluation python -c "from importlib.metadata import version; print(version('maseval'))"
git add pyproject.toml uv.lock apps/company-service/src/dsh_company/evaluation apps/company-service/tests/evaluation benchmarks
git commit -m "feat: add system-level company strategy evaluation"
```

Expected: tests pass and installed version prints `0.5.1`.

### Task 6: 定义业务插件契约和参考插件

**Files:**

- Create: `apps/company-service/src/dsh_company/business_plugins/__init__.py`
- Create: `apps/company-service/src/dsh_company/business_plugins/manifest.py`
- Create: `apps/company-service/src/dsh_company/business_plugins/registry.py`
- Create: `apps/company-service/src/dsh_company/business_plugins/templates.py`
- Create: `apps/company-service/src/dsh_company/api/plugins.py`
- Create: `apps/company-service/alembic/versions/0004_business_plugins.py`
- Create: `apps/company-service/tests/business_plugins/test_registry.py`
- Create: `apps/company-service/tests/api/test_plugins_api.py`
- Create: `packages/company-plugin-sdk/package.json`
- Create: `packages/company-plugin-sdk/src/index.ts`
- Create: `examples/content-studio-plugin/manifest.json`
- Create: `examples/content-studio-plugin/README.md`
- Create: `docs/development/software-plugin-adaptation.md`
- Modify: `pnpm-workspace.yaml`

- [ ] **Step 1: 写命名空间与模板边界测试**

```python
def test_plugin_can_register_namespaced_actions_and_templates(registry) -> None:
    registration = registry.register(BusinessPluginManifest(
        plugin_id="content-studio",
        version="0.1.0",
        capability_actions=(PluginAction("content-studio.publish_draft", CapabilityLevel.L3),),
        templates=(content_campaign_template(),),
    ))
    assert registration.plugin_id == "content-studio"


def test_plugin_cannot_replace_core_actions_or_embed_code(registry) -> None:
    with pytest.raises(InvalidPluginManifest, match="action_namespace"):
        registry.register(manifest_with_action("workspace.write"))
    with pytest.raises(InvalidPluginManifest, match="unsupported field"):
        registry.register(manifest_with_extra({"python": "exec(...)"}))
```

- [ ] **Step 2: 确认红灯并实现 manifest**

```python
class BusinessPluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plugin_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    version: str
    display_name: str
    capability_actions: tuple[PluginAction, ...] = ()
    templates: tuple[WorkTemplate, ...] = ()
```

Every action starts `{plugin_id}.`. Templates contain declarative node/edge shapes, Employee slots and acceptance criteria; no executable code, prompt override, SQL, URL callback or package path field exists.

- [ ] **Step 3: 持久化注册元数据并暴露 API**

Create `business_plugin_registrations(plugin_id PK, version, display_name, manifest_json, registered_at)` and routes:

```text
POST /business-plugins/register
GET  /business-plugins
GET  /business-plugins/{plugin_id}/templates
POST /workspaces/{workspace_id}/templates/{plugin_id}/{template_id}/instantiate
```

Instantiation requires explicit Employee assignment for every slot and runs the same GraphValidator/PolicyEngine. A plugin never writes Core tables directly.

- [ ] **Step 4: 生成 TypeScript SDK**

`@dsh/company-plugin-sdk` exports generated transport types plus a `CompanyPluginClient` that calls only public plugin/work endpoints. It has no database, DSH runtime or Host lifecycle dependency.

- [ ] **Step 5: 创建参考内容插件和软件插件迁移说明**

Reference manifest registers one L3 draft-publish action and one “调研→撰写→审核→汇总” template. The README shows registration and instantiation through SDK.

`software-plugin-adaptation.md` maps old `multi-agent` assets:

- Git/worktree/runtime tools remain owned by the software plugin;
- software roles become recommended Employee revisions, not Core enums;
- Task/Delivery/Integration become plugin objects plus Work/ArtifactReference links;
- plugin calls public template/work/approval APIs;
- no old database migration or CrewAI flow moves into Core.

- [ ] **Step 6: 转绿、build、migration、提交**

```powershell
uv run pytest apps/company-service/tests/business_plugins apps/company-service/tests/api/test_plugins_api.py -q
uv run alembic -c apps/company-service/alembic.ini upgrade head
pnpm install
pnpm --filter @dsh/company-plugin-sdk build
git add apps packages examples docs pnpm-workspace.yaml pnpm-lock.yaml
git commit -m "feat: define company business plugin boundary"
```

### Task 7: 运行固定比较并完成产品级验收

**Files:**

- Create: `tests/system/tests/test_phase_5_work_graph.py`
- Create: `tests/system/tests/test_phase_5_plugin_boundary.py`
- Create: `benchmarks/company/baseline-results.json`
- Create: `docs/development/strategy-selection.md`
- Modify: `tools/check.py`
- Modify: `README.md`
- Modify: `docs/README.md`

- [ ] **Step 1: 写系统门禁**

The graph test covers bounded parallel dispatch, dependency readiness, one failed branch, summary with partial inputs, Approval wait, cancellation, retry, restart and immutable revision history. The plugin test registers the reference manifest, instantiates it, rejects core action override and proves the plugin has no direct persistence import.

- [ ] **Step 2: 运行 keyless strategy comparison**

Run Direct, Star, Graph and Battle on every allowed task with the same keyless model behavior and budgets. Write `baseline-results.json` with task-set version, DSH revision, Company commit, per-strategy metrics and no raw model text. No checksum file is created.

- [ ] **Step 3: 选择默认策略规则**

`strategy-selection.md` records:

- Direct remains global default;
- a task family may opt into another strategy only if all policy/recovery invariants pass and its primary success metric improves without exceeding its declared token/duration/intervention budget;
- no strategy wins globally by average score alone;
- every change reruns the fixed task set.

- [ ] **Step 4: 完整验证**

```powershell
uv run pytest tests/system/tests/test_phase_5_work_graph.py tests/system/tests/test_phase_5_plugin_boundary.py -q
uv run pytest apps/company-service/tests -q
pnpm run check
python tools/check.py
git diff --check
```

Expected: all commands exit 0; no skipped policy, recovery or isolation scenario.

- [ ] **Step 5: Commit**

```powershell
git add tests/system benchmarks/company/baseline-results.json docs tools/check.py README.md
git commit -m "test: establish company graph and plugin baselines"
```

## Phase 5 完成定义

- DurableGraphEngine 从 Company DB 求就绪、受限并发、协调失败与恢复；
- Direct、Star、Graph、Battle 共享同一 Domain/Policy/Gateway；
- Employee Selector 先过滤资格，再显式选择少量员工；
- MASEval 0.5.1 仅在 evaluation group，通过薄 Adapter 评测完整系统；
- Direct 与多员工策略在同任务、模型和预算下有可追踪基线；
- 业务插件只能注册命名空间能力和声明式模板；
- 软件开发系统有明确适配路径，但旧代码和 CrewAI 未进入 Core；
- 完整 keyless、迁移、API、Client build 和系统测试全绿。

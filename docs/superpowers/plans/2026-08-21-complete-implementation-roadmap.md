# DSH Company Complete Implementation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过五个可独立验收的 Phase，把空白 `dsh-company` 仓库建设成围绕一人公司、以持久 DSH Agent 为员工的通用多智能体系统，并留下明确的业务插件扩展边界。

**Architecture:** Company Core 只拥有公司、员工、工作、授权、审批、委派和图状态；DSH 始终拥有 Agent Runtime、Session、工具执行、沙盒、原始事件和持续上下文。五个 Phase 严格顺序执行，每一阶段都交付可运行软件和迁移门槛，后续阶段只依赖前一阶段已验证的公开契约。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、SQLAlchemy 2、Alembic、SQLite、DSH Python SDK；React 18、TypeScript、Zod、DSH/Cordis Host/Client；OpenAPI；Pytest、Vitest、Ruff、Pyright；MASEval 0.5.1 仅用于开发评测。

---

## 1. 五阶段总览

| Phase | 核心问题 | 可运行交付物 | 进入下一阶段的硬门槛 |
|---|---|---|---|
| Phase 1 | 工程能否稳定构建；DSH 公开能力真实支持什么 | 独立仓库、Company Service 健康端点、DSH 插件双入口、契约链路、DSH 能力矩阵 | keyless gate 全绿；两个 Session 隔离与恢复通过；不支持项有明确降级结论 |
| Phase 2 | 用户能否建立公司和长期员工 | Workspace、Employee、Revision、CapabilityGrant、Binding 的数据库/API/UI | 无凭据可创建 Workspace/Employee；重启后配置不丢失；跨 Workspace 查询隔离 |
| Phase 3 | 一名员工能否持续完成工作 | Direct 单节点 Work、ExecutionLink、DSH Gateway、事件投影、结果引用、历史、取消与恢复 | 完整创建→执行→历史闭环；稳定 Session 连续；取消和重启不伪造成功 |
| Phase 4 | 员工如何在权限边界内协作 | L0–L3 授权、资源交集、Approval、Delegation、审批 UI | 高等级动作执行前必有批准；拒绝不可继续；委派不能扩大权限 |
| Phase 5 | 何时值得使用多员工；如何扩展业务 | DurableGraphEngine、Star/Graph/Battle、Selector、MASEval Adapter、Business Plugin Contract | Direct 与多员工策略可同预算比较；图恢复通过；首个示例插件只能通过公开契约接入 |

## 2. 计划文件与执行顺序

Phase 1 分成两个连续子计划，因为工程地基与 DSH 能力验证是两个独立可测试的软件单元：

1. [Phase 1A：仓库与工程基础](2026-08-21-repository-foundation.md)
2. [Phase 1B：DSH 公共能力 Spike](2026-08-21-phase-1-dsh-capability-spike.md)
3. [Phase 2：公司与员工核心](2026-08-21-phase-2-company-core.md)
4. [Phase 3：Direct 工作闭环](2026-08-21-phase-3-direct-work.md)
5. [Phase 4：权限、审批与委派](2026-08-21-phase-4-governance.md)
6. [Phase 5：Work Graph、Battle、评测与业务插件](2026-08-21-phase-5-work-graph-evaluation-and-plugins.md)

不得并行执行相邻 Phase。一个 Phase 内只有不修改相同文件、且不共享迁移或契约的任务可以并行。

## 3. 跨阶段权威边界

### 3.1 Company Core 保存

- Workspace 与员工组织事实；
- EmployeeRevision 与 CapabilityGrant；
- EmployeeAgentBinding 中的 DSH 标识关联；
- Work、Graph Revision、Node、Edge、ExecutionLink；
- Delegation、Approval、CompanyEvent；
- ArtifactReference，不复制 Artifact 内容；
- 必要且带来源时间的 DSH 状态投影。

### 3.2 DSH 保存

- Agent/Session 生命周期与原始会话日志；
- 模型消息、工具调用、Job、沙盒与运行时事件；
- 当前 Session 上下文与其持久化；
- DSH 未来公开的 Memory Provider 数据。

### 3.3 当前 DSH 能力基线

Phase 1 必须以实际 Spike 重新生成结论；后续计划采用以下源码已确认的初始事实：

| 能力 | 当前公开事实 | 产品处理 |
|---|---|---|
| 创建 Session | Python SDK `DeepSeekHarness.start_session(session_id)` | 支持 |
| 恢复 Session | 使用同一 `session_root` 与 `session_id` 重新运行 | 支持，Phase 1 实测 |
| Agent ID | AgentRegistry 公共契约规定 `agent.id === agent.session.id`；Python SDK 只暴露 Session ID | Binding 当前令 `dsh_agent_id == dsh_session_id` |
| 事件/结果 | `RunResult.events`、`notifications`、`final_response`、`finish_reason` | 支持，只保存安全投影与引用 |
| 取消 | Python SDK 无 Session cancel；关闭一次 Attempt 独占的 Harness | 有约束支持，请求与确认分开记录 |
| observe | Python SDK 无跨进程 Attempt observe | 重启时标为 `blocked/runtime_process_lost`，允许新 Attempt 恢复 |
| 动态能力目录 | Python SDK 未暴露 Tool/Skill/Connector 列表 | 使用经过测试的受控 Runtime Profile 目录 |
| Memory Provider | Python SDK 未暴露独立写入/查询 API | Phase 1–5 只使用 Session 连续上下文，不在 Core 自建 Memory |

任何 DSH 升级若改变该表，先更新 Phase 1 能力矩阵和 Gateway 契约，再修改产品代码。

## 4. 跨阶段类型演进

```text
Phase 2
Workspace ─┬─ Employee ─ EmployeeRevision ─ CapabilityGrant
           └─ EmployeeAgentBinding

Phase 3
Workspace ─ Work ─ WorkGraphRevision ─ WorkNode
                       │                  └─ ExecutionLink ─ ArtifactReference
                       └─ CompanyEvent

Phase 4
WorkNode ─ Approval
WorkGraphRevision ─ Delegation ─ WorkNode/WorkEdge

Phase 5
WorkGraphRevision ─ WorkNode[] ─ WorkEdge[]
         │               └─ DurableGraphEngine
         ├─ Direct / Star / Graph / Battle
         ├─ EvaluationRun
         └─ BusinessPluginRegistration / WorkTemplate
```

已提交的终态事实不得被后续 Phase 重写。新增字段需要 Alembic migration；新增 API 先改 Python schema，再捕获 OpenAPI 并生成 TypeScript。

## 5. 固定工程规则

- 每个行为先写失败测试，确认失败原因，再写最小实现；
- Domain 不导入 FastAPI、SQLAlchemy、DSH SDK 或第三方编排框架；
- Application 只依赖 Repository、UnitOfWork、DshGateway、OrchestrationEngine 端口；
- API 不直接写 SQL 或调用 DSH；
- UI 不推断权威状态，不因轮询超时把运行标成成功或失败；
- 外部 DSH 调用和 Company DB 事务不伪装成一个原子事务；
- 每次 dispatch 使用稳定 `command_id`，每次实际运行使用新 `attempt_id`；
- 原始 prompt、模型输出和工具参数不复制进 CompanyEvent；
- `multi-agent` 保持独立，软件开发代码只在 Phase 5 通过插件契约做适配验证；
- CrewAI、LangGraph、AFlow 和 EvoAgentX 均不进入生产 Core；
- MASEval 是 dev dependency，只读取评测适配器输出。

## 6. 每阶段统一完成检查

每个 Phase 最后必须执行：

```powershell
python tools/check.py
git diff --check
git status --short
```

涉及数据库时还要执行：

```powershell
uv run alembic -c apps/company-service/alembic.ini upgrade head
uv run alembic -c apps/company-service/alembic.ini downgrade -1
uv run alembic -c apps/company-service/alembic.ini upgrade head
```

涉及 API 时还要执行：

```powershell
$apiCommit = git rev-parse HEAD
pnpm run contracts:capture -- --api-commit $apiCommit
pnpm run contracts:generate
pnpm --filter @dsh/company-plugin typecheck
```

涉及 DSH 实际运行时还要用 keyless mock endpoint 完成系统测试；真实凭据 smoke 只能是显式、非 CI 的人工门禁。

## 7. 产品级完成定义

Phase 5 结束时，一个用户必须能够：

1. 创建一个 Workspace 作为公司或部门；
2. 自由创建多个 Employee，配置职责、Runtime Profile、模型和能力等级；
3. 把工作直接交给某名员工，并在同一持久 Session 上继续；
4. 查看公司视角的工作、事件、结果引用和失败原因；
5. 对高等级动作批准或拒绝；
6. 允许有权限的员工委派给另一名员工，但不能越权；
7. 选择 Direct、Star、Graph 或 Battle，并看到真实节点状态；
8. 在 Service 重启后恢复公司事实，对丢失的 Runtime Attempt 给出真实阻塞状态；
9. 用固定公司任务集比较策略成功率、成本、耗时和用户介入；
10. 让软件开发等业务能力通过公开插件契约接入，而不污染 Company Core。

系统不声称拥有 DSH 尚未公开的动态能力发现、跨进程 Attempt observe 或独立 Memory Provider API。这些能力只能在后续 DSH 升级重新通过 Phase 1 后进入产品。

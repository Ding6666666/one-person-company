# Company Work Graph、编排与评测

**状态：** 设计草案，2026-08-21，等待书面复核。

本文定义 DSH Company 如何组织多名 Employee 完成工作，以及如何用 benchmark 决定具体编排实现。它不把 Company Core 变成另一套 Agent Runtime。

## 1. 设计依据

2025–2026 的研究没有证明一个多智能体框架在所有任务和模型上始终最好，反而共同支持以下原则：

- [FLOW（ICLR 2025）](https://proceedings.iclr.cc/paper_files/paper/2025/hash/ba84da6921f3040b74ee163aa7451f53-Abstract-Conference.html)用 Activity-on-Vertex 图表达依赖、并发和运行中调整；
- [MultiAgentBench（ACL 2025）](https://aclanthology.org/2025.acl-long.421/)显示 star、chain、tree、graph 等拓扑的效果依任务而变，graph 在其研究场景中最好；
- [AFlow（ICLR 2025 Oral）](https://proceedings.iclr.cc/paper_files/paper/2025/hash/5492ecbce4439401798dcd2c90be94cd-Abstract-Conference.html)证明工作流可以通过执行反馈离线优化，但其搜索结果不应直接成为生产事实；
- [Graph-of-Agents（ICLR 2026）](https://proceedings.iclr.cc/paper_files/paper/2026/file/21a87fb07e9ab0ecc4d9d1b940676229-Paper-Conference.pdf)显示按任务选择少量相关 Agent 可以优于让所有 Agent 同时参与；
- [MASEval（ACL 2026）](https://aclanthology.org/2026.acl-demo.34/)显示框架影响可以接近模型影响，且没有单一框架在全部组合上占优；
- [EXP-Bench（ICLR 2026）](https://proceedings.iclr.cc/paper_files/paper/2026/hash/c411f5b2d9c55f1685e72db224ad8b0e-Abstract-Conference.html)显示复杂端到端 Agent 工作仍远不可靠，因此里程碑、验收和人工审批不能省略。

据此，Company Core 采用图原生、评测驱动、运行框架可替换的设计。

## 2. Work Graph 模型

一个 `Work` 拥有按版本保存的 `WorkGraphRevision`。每个版本由节点和有向边组成。

### 2.1 WorkNode

节点至少包含：

- `node_id` 和所属 `work_id`；
- `objective`：本节点目标；
- `acceptance_criteria`：可验证的完成条件；
- `assigned_employee_id`：执行员工；
- `employee_revision_id`：本次执行冻结的员工配置；
- `required_capabilities` 和资源范围；
- `input_references` 和 `output_references`；
- 当前状态、版本和尝试次数；
- 审批要求、失败原因和恢复信息。

节点不保存 DSH 原始 transcript 或推理过程。

### 2.2 WorkEdge

第一阶段支持四种边语义：

- `depends_on`：上游完成后下游才能就绪；
- `delegates_to`：记录由哪个员工或节点发起委派；
- `reviews`：下游检查上游是否满足验收标准；
- `summarizes`：下游汇总多个上游结果。

图必须有向无环。循环式改进通过创建新的节点或 Graph Revision 表达，不通过运行时无限回边表达。

### 2.3 节点状态

```text
draft
  → ready
  → running
      → waiting_approval → running
      → blocked → ready
      → completed
      → failed
      → cancelled
```

- `ready` 只表示依赖满足且授权有效；
- `running` 只表示已创建权威 DSH Attempt，不代表仍然健康；
- `waiting_approval` 必须关联未决 Approval；
- `blocked` 必须有可操作原因，例如缺少用户输入或 DSH 暂时不可用；
- `completed` 必须有验收结果和输出引用；
- `failed`、`cancelled`、`completed` 是该 Node Revision 的终态。

## 3. 图的产生和调整

第一阶段允许三种来源创建 Work Graph：

1. Core 为直接交办创建单节点图；
2. 用户选择的业务模板创建确定性图；
3. 获得委派权限的 Employee 通过 DSH 提交 `GraphChangeProposal`。

Agent 提案不是权威状态。Core 接收提案后必须验证：

- 所有 Employee 属于当前 Workspace 且处于可用状态；
- 提案者有权委派目标 Employee；
- 新节点的能力和资源范围没有越权；
- 图保持无环，所有输入引用可解析；
- 已完成节点和历史事实没有被重写；
- 需要审批的变化已产生 Approval。

验证通过后创建新的不可变 WorkGraphRevision。运行中节点继续绑定其开始时的 Graph Revision；新版本只影响尚未开始或明确迁移的节点。

## 4. 内置协作策略

### 4.1 Direct

单个 Employee 完成单节点 Work。它是基线，也是简单任务的默认方式；系统不为了体现“多 Agent”而强制增加员工。

### 4.2 Star

一名获授权的 Employee 提出拆分和目标员工，多个子节点执行后返回给发起节点汇总。Core 负责权限验证和状态，不硬编码“经理”角色。

### 4.3 Graph

按照显式依赖并行或顺序执行多个节点。仅就绪节点可以分发；失败是否阻塞下游由边和业务策略明确决定。

### 4.4 Battle

Battle 是 Graph 的一种预定义形状：多个并行处理节点加一个 `summarizes` 节点。参与者由用户指定或从获授权员工中选择少量相关员工，不广播给 Workspace 全体。汇总节点整理、去重、标记分歧并上报，不替用户作最终决定。

## 5. Employee 选择

Employee Selector 先做确定性资格过滤：

```text
当前 Workspace
∩ 可用 Employee
∩ required_capabilities
∩ 资源范围
∩ 委派白名单
∩ 审批策略允许的候选
```

过滤后，第一阶段由用户或发起 Employee 从候选中明确选择。后续可以根据职责描述、历史表现、成本和当前负载排序，但排序不能绕过资格过滤，也不能默认选择所有员工。

## 6. OrchestrationEngine 端口

Company Application 面向以下能力编程：

```text
start(work_graph_revision)
dispatch_ready_nodes(work_id)
record_completion(node_id, attempt_id, result_reference)
record_failure(node_id, attempt_id, reason)
request_revision(work_id, graph_change_proposal)
request_cancel(node_id)
reconcile(work_id)
```

这是业务端口，不是一个通用工作流 DSL。端口的输入输出使用 Company Domain 类型，第三方框架类型不得穿过边界。

## 7. DurableGraphEngine

第一阶段生产实现使用最小的 DurableGraphEngine：

- Company DB 是图、节点和状态的唯一权威；
- 通过拓扑依赖查询寻找 ready 节点；
- 使用受限并发向 DSH Gateway 分发；
- 每次分发创建持久化 Attempt 和稳定命令 ID；
- DSH 事件只更新来源明确的投影；
- Service 重启后通过 `reconcile` 与 DSH 协调运行态；
- 审批、阻塞、失败和取消都是显式状态，不由异常文本隐式推断。

该引擎不实现 LLM 推理、工具调用、个人 Memory、任意代码节点或可视化流程编辑器。

## 8. DSH Gateway 端口

编排层只依赖 DSH Gateway 的稳定语义：

```text
list_capabilities(workspace_id)
start_or_resume(employee_binding, node_context)
submit(session_link, instruction, command_id)
observe(attempt_id)
cancel(attempt_id)
request_memory_write(employee_binding, company_knowledge_reference)
```

实际方法名在 DSH public API spike 后确定，但语义边界不变。`request_memory_write` 表示通过 DSH 已配置能力提出写入，不意味着 Company Core 直接访问 Provider 数据库。

## 9. 第三方框架位置

- CrewAI 不进入 Company Core；旧项目中的固定角色 CrewAI Flow 保留在软件系统历史中。
- LangGraph 可以实现 OrchestrationEngine 适配器参加 benchmark，但不能成为 Company 状态的第二账本。
- AFlow/EvoAgentX 只作为未来离线优化器，根据已脱敏的 benchmark 轨迹提出工作模板或策略候选；候选必须重新评测并由用户启用。
- MASEval 是开发与评测依赖，不参与生产请求、员工身份、权限或公司持久化。

## 10. 评测架构

项目为 MASEval 提供 DSH Company Adapter，使自研引擎和第三方适配器在同一任务、模型、Employee 配置和权限下运行。

### 10.1 第一批任务族

- 单员工专业任务：验证 Direct 基线；
- 可并行研究或内容任务：比较 Direct、Star、Graph 和 Battle；
- 有依赖的业务任务：验证拓扑、输入传递和局部失败；
- 高等级外部动作：验证审批前不执行、批准后继续、拒绝后停止；
- Service 重启：验证 Attempt 协调和状态恢复；
- 两名员工连续任务：验证 Session/Memory 连续性与隔离；
- DSH 或 Memory Provider 暂时不可用：验证真实阻塞和恢复。

### 10.2 指标

- 最终任务成功率；
- 里程碑完成率和验收通过率；
- 错误委派、重复节点和无效沟通次数；
- Token、推理成本、耗时和用户介入次数；
- 审批与权限不变量是否全部满足；
- 重启恢复和取消是否与 DSH 权威状态一致；
- 每名 Employee 的 Session/Memory 连续性与隔离是否成立。

### 10.3 选择规则

没有框架因论文排名自动成为默认实现。候选引擎必须在固定版本的公司任务集上，与 Direct 和 DurableGraphEngine 基线使用相同模型、能力和运行预算比较。

默认策略或引擎只有在以下条件同时成立时才可以变更：

- 所有权限、审批、隔离和恢复不变量通过；
- 在声明的目标任务族上改善预先指定的主要指标；
- 没有用不可接受的成本、延迟或用户介入换取表面成功率；
- 完整配置、轨迹摘要和 benchmark 版本可追踪。

不同任务族可以选择不同策略；系统不追求一个全局最佳拓扑。

## 11. 第一实施前的 DSH Spike

在大规模实现 UI 和 Domain 前，必须用 DSH 公共接口验证：

1. 创建两个不同 Employee 的 Agent/Session；
2. 独立执行并读取事件、结果与取消状态；
3. 重启 Company Service 后恢复 Session；
4. 验证当前上下文或配置的 Memory 可连续召回；
5. 验证两名 Employee 的 Memory 范围互不混淆；
6. 记录 DSH Agent ID、Session ID 和 EmployeeAgentBinding 的真实关系。

Spike 只验证架构风险，不创建临时兼容层。若 DSH 公共 API 缺少必需能力，应先调整 Gateway 设计或推动 DSH 能力，而不是在 Company Core 复制 Runtime/Memory。

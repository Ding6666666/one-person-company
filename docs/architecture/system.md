# DSH Company 系统架构

**状态：** 设计草案，2026-08-21，等待书面复核。

本文定义第一阶段 Company Core 的组件、依赖方向、权威数据源和运行边界。产品语义以[产品方向](../product/one-person-company-product-direction.md)为准；工作图和评测细节见[图编排与评测](orchestration-and-evaluation.md)。

## 1. 架构目标

DSH Company 是一人公司的组织与协作控制层。它把长期存在、拥有连续记忆的 DSH Agent 表达为 Employee，允许用户自由配置员工并组织他们完成工作。

架构必须同时满足：

- Employee 是稳定的产品身份，不被一次运行或单个 Session 取代；
- DSH 是 Agent Runtime、Session、Tool、Skill、Connector 和个人 Memory 的权威；
- Company Core 保存公司组织、工作、委派、审批、会议和共享历史；
- 员工类型和协作拓扑可变，不硬编码经理、执行者、审核者等角色；
- 高等级动作必须经过资源范围和审批策略；
- 业务插件扩展业务能力，但不能重新定义 Workspace、Employee 或绕过 Core；
- 原软件开发系统保持独立，后续作为业务插件接入。

## 2. 非目标

第一阶段不建设：

- 第二套 Agent Runtime、模型路由、工具调用协议或沙盒；
- 自研长期 Memory 引擎；
- 通用可视化工作流设计器或任意代码工作流平台；
- 插件市场、在线动态安装和跨 Workspace 集团层级；
- 无人监督的自动经营、绩效系统和成本驾驶舱；
- 对 CrewAI、AutoGen、LangGraph 等框架的统一兼容层。

## 3. 系统上下文

```text
┌──────────────────────── DSH Host ────────────────────────┐
│                                                          │
│  DSH Agent / Session / Tool / Skill / Connector / Memory │
│                     ▲                                    │
│                     │ public DSH capability              │
│                     ▼                                    │
│  ┌────────────── DSH Company Plugin ──────────────────┐  │
│  │ React Company UI                                   │  │
│  │ TypeScript Host Lifecycle / Credential Boundary    │  │
│  └──────────────────────┬─────────────────────────────┘  │
└─────────────────────────┼────────────────────────────────┘
                          │ loopback API
                          ▼
               ┌──────────────────────┐
               │ Company Control API  │
               │ Application Services │
               │ Work Graph Engine    │
               │ DSH Gateway Adapter  │
               └──────────┬───────────┘
                          │
                          ▼
                    Company SQLite

第三方 Memory Provider 通过 DSH 接入；业务插件通过 Company Core 的公开扩展边界接入。
```

第一阶段沿用已验证的本地插件部署模式：TypeScript Host 只负责 Company Service 的生命周期、凭据边界和 loopback 连接；Python Service 负责公司业务状态和 DSH Gateway。Host 不保存业务事实。

## 4. 组件与依赖方向

### 4.1 Company UI

提供 Workspace、Employee、工作、委派、审批、Battle 和历史视图。UI 只展示服务端投影，不根据定时器、消息文本或本地缓存推断权威状态。

### 4.2 Company API

把应用命令和查询暴露给 UI 与业务插件。API 负责协议验证和错误映射，不直接实现领域转换、SQL 或 DSH 行为。

### 4.3 Application

协调一个完整用例的事务与外部调用，例如创建员工、直接交办、批准动作、委派工作和恢复失败节点。Application 依赖端口，不依赖具体数据库、Web 框架或第三方编排框架。

### 4.4 Domain

保存纯业务模型、状态和不变量。Domain 不依赖 FastAPI、SQLAlchemy、React、DSH SDK 或编排框架。

第一阶段核心实体为：

- `Workspace`：相互独立的一人公司边界；
- `Employee`：长期员工身份；
- `EmployeeRevision`：职责、行为、模型和 Runtime 配置的不可变版本；
- `CapabilityGrant`：能力动作、等级、资源范围和审批要求；
- `EmployeeAgentBinding`：Employee 与 DSH Agent 配置、Memory 范围的稳定关联；
- `Work`：用户希望公司完成的目标；
- `WorkGraphRevision`、`WorkNode`、`WorkEdge`：可版本化的工作分解和依赖；
- `ExecutionLink`：Work Node 与 DSH Session/运行尝试的关联；
- `Delegation`：谁把什么工作委派给谁；
- `Approval`：高等级动作的请求和用户决定；
- `CompanyEvent`：公司视角的可读历史；
- `ArtifactReference`：对 DSH 或业务插件产出的引用，不复制其内部事实。

Battle 是一种 Work Graph 策略，不单独提升为全局业务实体。会议在第一阶段只保留架构位置，其正式数据结构在会议设计确认后加入。

### 4.5 Persistence

使用 SQLAlchemy 2、SQLite 和 Alembic 保存 Company Core 事实。它实现 Repository 和 Unit of Work，不向 Domain/Application 泄露 ORM 类型。

### 4.6 DSH Gateway

通过 DSH 的公开能力完成：

- 读取可分配的 Tool、Skill、Connector 和 Runtime 能力；
- 根据 EmployeeAgentBinding 创建或恢复员工运行载体；
- 向 DSH Session 提交工作并读取权威事件和结果；
- 请求取消运行；
- 通过 DSH 配置的 Memory 能力写入或召回员工经验。

Gateway 不复制 DSH 推理循环，不读取私有实现字段，也不把 DSH 原始 transcript、工具调用和事件保存为第二套账本。

### 4.7 OrchestrationEngine

执行 Company Work Graph 的就绪判断、并发分发、节点完成、审批等待、失败恢复和图版本切换。它是 Application 依赖的端口；第一实现是最小的 DurableGraphEngine，第三方框架只能通过适配器实现该端口。

### 4.8 Business Plugin

业务插件可以提供页面、业务资源、工作模板、Employee 配置建议和少量业务专属 DSH Tool。插件通过公开命令和查询使用 Core，不直接写 Core 数据表、不启动旁路 Agent，也不依赖其他插件的内部存储。

## 5. 权威数据源

| 事实 | 权威来源 | Company Core 可保存的内容 |
|---|---|---|
| Workspace、Employee、职责和授权 | Company DB | 完整事实与版本 |
| Work Graph、委派、审批、Battle 汇总 | Company DB | 完整事实与版本 |
| DSH Session 消息、Job、Event、工具调用 | DSH | ID、公司关联和必要状态投影 |
| Agent 当前上下文和运行结果 | DSH | Session/Attempt 关联与结果引用 |
| 员工个人长期 Memory | DSH 与所配置 Provider | Memory 绑定、写入意图；第一阶段不保存内容副本 |
| 公司会议、决定和共享历史 | Company DB | 完整公司事实 |
| 插件业务对象 | 对应业务插件 | Core ID 关联和通用 ArtifactReference |

任何投影都必须带来源和新鲜度。投影不可覆盖来源事实，DSH 不可用时应显示不可用或过期，不得伪造成功状态。

## 6. 核心执行链路

### 6.1 直接交办

```text
用户创建 Work
→ Core 创建单节点 Work Graph
→ 校验 Employee、能力和资源范围
→ DSH Gateway 创建或恢复员工 Session
→ DSH 执行并产生事件
→ Core 保存公司状态与结果引用
→ 节点完成，Work 完成
```

### 6.2 员工委派

```text
员工提出委派
→ Core 校验委派能力、目标员工和权限边界
→ 创建新的 Work Graph Revision、Node 和 Delegation
→ 目标员工通过 DSH 执行
→ 结果沿依赖边返回发起节点
```

委派不能扩大任一员工的能力、资源范围或审批权限。

### 6.3 高等级审批

DSH 或 Core 在执行动作前产生审批请求。Approval 进入 Company DB 后节点转为等待审批；批准后以同一 Node 和新的运行尝试继续，拒绝后按拒绝结果结束或退回重规划。UI 隐藏按钮不构成授权，实际动作边界必须再次验证。

### 6.4 Battle

Battle 把目标拆成多个并行节点，分配给获授权的少量员工，再由一个汇总节点整理、去重、标记分歧并上报。最终业务决定仍属于用户。

## 7. 一致性、失败与恢复

- Company DB 事务只提交 Company 事实；外部 DSH 调用不能与数据库伪装成一个原子事务。
- 每次 Node dispatch 使用稳定命令 ID；重复请求返回同一业务结果或安全重试，不创建不可解释的重复工作。
- Service 重启后，`running` 节点必须与 DSH 权威状态协调，不能仅因本地曾进入运行态就判断成功或失败。
- DSH 暂时不可用时，未开始的 Node 保持可恢复阻塞状态；已开始的 Attempt 先协调再决定恢复方式。
- 已完成节点的历史不可被图调整重写；调整产生新的 WorkGraphRevision。
- 取消是显式状态转换，并通过 DSH Gateway 请求停止实际运行；请求取消与确认停止是两个事实。
- Memory Provider 不可用不应导致公司事实丢失。需要 Memory 的工作应明确失败或阻塞，不把未写入的内容报告为已记住。

## 8. 权限边界

Company Core 保存 L0–L3 动作等级、资源范围和审批策略；DSH 在实际工具和沙盒边界执行权限。两层职责不同：Core 决定公司是否授权，DSH 决定运行时能否真正执行。

Node 获得的有效权限是以下范围的交集：

```text
Workspace 上限
∩ Employee CapabilityGrant
∩ Work/Node 临时授权
∩ DSH Runtime 实际能力
```

委派、图调整和业务插件都不能扩大该交集。

## 9. 技术栈和代码布局

第一阶段沿用原项目已验证的技术组合：

- Python 3.13；
- FastAPI、Pydantic、SQLAlchemy 2、Alembic、SQLite；
- React 18、TypeScript、Zod；
- DSH/Cordis 插件 Host 与 Client；
- OpenAPI 作为 Python/TypeScript 传输契约；
- Pytest、Vitest、Pyright、Ruff 和生产构建作为门禁。

目标布局：

```text
apps/
  company-service/
    src/dsh_company/
      domain/
      application/
      persistence/
      policy/
      dsh_gateway/
      orchestration/
      api/
      foundation/
  dsh-company-plugin/
packages/
  contracts/
docs/
tests/system/
```

代码复用必须遵循[`multi-agent` 复用策略](../development/multi-agent-reuse.md)，不得把旧软件领域模型作为新 Core 的起点。

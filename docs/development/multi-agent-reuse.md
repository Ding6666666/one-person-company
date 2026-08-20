# 从 `multi-agent` 选择性复用代码

**状态：** 开发策略已确认，2026-08-21，作为实施计划的迁移边界。

本文规定如何从 `E:\Project\dsh\multi-agent` 高效复用已经验证的工程能力，同时避免把软件开发业务模型带入新的 Company Core。

## 1. 复用基线

复用审查基于 `multi-agent` 提交：

```text
2330adbb89cd72cba29f4ed17b70f37036fecaba
feat: add employee quick-create dialog
```

后续若从更新提交迁移，迁移提交必须记录新的来源 SHA。`dsh-company` 不通过 Git submodule、运行时包依赖或共享数据库依赖 `multi-agent`。

DSH 公共接口与插件构建的初始 vendor 基线固定为：

```text
2db6ebd58523d14dca278e366ea0eb40499702b9
```

该提交将作为 `vendor/deepseek-harness` submodule 引入；它是 DSH 平台依赖，不是 `multi-agent` 业务代码依赖。升级 DSH 时必须在独立提交中更新 submodule，并重新执行 DSH 能力 Spike 与公共门禁。

## 2. 总体策略

采用“新 Core、选择性迁移”而不是整仓复制：

- `dsh-company` 从新的 Domain 和数据库 schema 开始；
- 只迁移与产品语义无关、已经验证的工程基础；
- 与旧领域耦合的模块只复用设计和测试经验，按新端口重写；
- 软件开发领域和页面留在 `multi-agent`，以后通过正式业务插件边界接入；
- 暂不抽取两个仓库共同依赖的公共包。只有同一抽象在两个真实产品中稳定后，才评估独立共享包。

## 3. 模块处置

### 3.1 可迁移并改名

| 来源 | 迁移目标 | 必须调整 |
|---|---|---|
| 根目录 Python/Node workspace 与检查骨架 | `dsh-company` 工程骨架 | 包名、路径、依赖和检查目标 |
| `packages/contracts` 的生成与一致性工具 | 新 contracts 包 | 输入 OpenAPI、生成命名空间 |
| `foundation/app.py`、`assembly.py`、日志和 correlation 模式 | `dsh_company.foundation` | 删除 execution/worktree 专属字段 |
| DSH plugin 构建、Host/Client 双入口模式 | `dsh-company-plugin` | 包名、路由、服务模块和环境配置 |
| `connection-controller` 与 loopback transport 模式 | Company 连接层 | 允许路径、错误码、DTO 和产品名称 |
| 通用 CSS tokens 与基础可访问性测试 | Company UI | 删除旧导航和软件状态含义 |

迁移意味着复制到新命名空间并接受新仓库所有权，不意味着两个仓库继续共享源文件。

### 3.2 抽取后适配

| 来源 | 可复用部分 | 不得带入 |
|---|---|---|
| `runtime_dsh` | public SDK 接入、生命周期、事件映射、取消与协调测试思路 | task/worktree、delivery summary、旧 PermissionSnapshot、自建 MemoryContext |
| Host lifecycle | 子进程启停、健康检查、凭据边界、退出协调 | 旧服务模块、旧环境变量和 `/m2`–`/m5` 路径 |
| Persistence | SQLAlchemy/Alembic 初始化、Repository/UoW 模式 | 旧 ORM models、迁移历史、Git/Delivery/Workflow store |
| Policy | 默认拒绝、动作级授权、审批前检查 | 固定角色、Git/merge/worktree 权限名 |
| API | 错误 envelope、correlation、OpenAPI 生成 | 旧业务 router、M1–M7 DTO 和状态枚举 |
| UI Primitives | Button、Card、Dialog、Drawer、FormField、状态可访问性 | 生成的 AgentType、manager/executor/reviewer/integrator 色彩映射 |

这些模块不能直接整目录复制。必须先定义新端口和测试，再迁移满足该端口的最小代码。

### 3.3 只参考，不迁移

- `domain`：Workspace=Git repository、固定角色、Delivery、Integration 等旧语义；
- `application`：围绕软件 Task、Execution、Delivery 的用例；
- `orchestration`：CrewAI Manager Flow 和固定 Coordinator 角色；
- `memory`：项目自建 Memory store，与“Memory 交给 DSH”冲突；
- `git_collaboration`：完整留给未来软件开发插件；
- 旧 ORM models 和全部 Alembic migrations；
- 旧 API router、OpenAPI schema 和生成 DTO；
- TaskBoard、DeliveryReview、IntegrationView、OperationsView 等软件业务页面；
- 旧 ProductController、固定路由表和业务 locale 文案。

MeetingRoom、EmployeeDirectory 和 WorkspaceLauncher 可以作为交互参考，但必须按新 Domain/API 重建，不能保留旧 DTO 和业务状态。

## 4. 每次迁移的操作规则

每个可复用能力使用一个独立迁移单元：

1. 在 `dsh-company` 写出新模块的公开契约和会失败的行为测试；
2. 从记录的 `multi-agent` SHA 迁移满足契约所需的最小实现；
3. 删除 `dsh_multi_agent`、M1–M7、Git、Delivery、固定角色和旧 Memory 语义；
4. 运行该模块的聚焦测试、类型检查和构建；
5. 检查依赖方向，确保 Foundation/Domain 不反向依赖适配器；
6. 使用单独提交记录来源，例如：

```text
port: adapt DSH host lifecycle from multi-agent@2330adb
port: adapt accessible UI primitives from multi-agent@2330adb
```

如果迁移后保留旧实现的大量分支才能通过测试，应停止迁移并按新契约重写，而不是增加兼容层。

## 5. 建议实施顺序

### Phase 1：仓库基础与 DSH 公共能力

先建立 Python/Node workspace、许可证、contracts、CI 和检查命令，再验证两个 Employee Session 的创建、事件、取消、重启恢复和上下文隔离。只有能力矩阵通过，EmployeeAgentBinding 和正式 Gateway 才进入产品实现。

### Phase 2：公司与员工核心

实现 Workspace、Employee、EmployeeRevision、CapabilityGrant、EmployeeAgentBinding、SQLite 持久化、Host 生命周期、最小 API 和 UI。创建员工不启动 DSH，也不要求 provider credential。

### Phase 3：Direct 工作闭环

实现单节点 Work Graph、DSH Gateway、ExecutionLink、事件投影、结果引用、历史、取消与重启协调。Direct 是所有多员工策略的正确性与成本基线。

### Phase 4：权限、审批与委派

实现 L0–L3 四层动作授权、资源范围、Approval、显式 Delegation 和不可变 Graph Revision。此阶段不需要 CrewAI 或动态图优化。

### Phase 5：Work Graph、评测与业务插件

实现 DurableGraphEngine、Star/Graph/Battle、失败协调、MASEval Adapter 和声明式业务插件边界。用固定公司任务集比较 Direct 与多员工策略，并用参考插件验证 Core 不被业务污染。

## 6. 迁移完成条件

一个迁移单元只有在以下事实全部成立时才算完成：

- 新模块名称和公开类型只表达 Company 语义；
- 没有运行时依赖 `multi-agent` 仓库或其数据库；
- 来源提交已记录；
- 原能力中适用于新契约的测试已迁移或等价重写；
- 新聚焦测试、类型检查和生产构建通过；
- 未引入 CrewAI、自建 Memory、Git 或固定角色概念；
- `multi-agent` 仓库没有因迁移被删除、改写或降级。

## 7. 何时抽公共包

第一阶段不提前创建 `dsh-shared`。满足以下现实条件后才评估抽包：

- `dsh-company` 和软件开发插件都在生产路径使用同一抽象；
- 两边的修改原因相同，而不只是代码长得相似；
- 包可以独立测试和版本化，不依赖任一产品 Domain；
- 抽取能减少真实重复维护，而不是为了目录整洁。

在此之前，少量重复的基础代码比错误的共享抽象更容易演进。

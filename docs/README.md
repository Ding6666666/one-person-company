# DSH Company 文档

本文档集把产品方向、系统权威边界、编排机制和代码复用策略分开维护。实现代码必须以这些文档为边界；如果实现需要改变已确认的产品语义，应先修改并重新确认对应设计。

## 推荐阅读顺序

1. [产品方向](product/one-person-company-product-direction.md)：解释为什么做、Workspace 和 Employee 代表什么，以及第一阶段成功标准。
2. [系统架构](architecture/system.md)：定义 Company Core、DSH、Memory Provider 和业务插件的职责与权威数据源。
3. [图编排与评测](architecture/orchestration-and-evaluation.md)：定义 Company Work Graph、可替换编排引擎、DSH Gateway 和 benchmark 驱动的框架选择。
4. [`multi-agent` 代码复用策略](development/multi-agent-reuse.md)：定义哪些代码迁移、哪些只参考、哪些保留为软件开发插件。
5. [API 契约开发规则](development/contracts.md)：定义 schema 所有权、OpenAPI 快照、TypeScript 生成代码和兼容性审查要求。
6. [DSH 公共能力矩阵](development/dsh-capability-matrix.md)：记录固定 DSH revision 的八项公开能力证据、限制和产品决策。

## 实施计划

1. [完整五阶段路线图](superpowers/plans/2026-08-21-complete-implementation-roadmap.md)：阶段依赖、跨阶段边界和产品级完成定义。
2. [Phase 1A：仓库与工程基础](superpowers/plans/2026-08-21-repository-foundation.md)：独立仓库、最小服务、DSH 插件双入口、OpenAPI 契约和公共门禁。
3. [Phase 1B：DSH 公共能力 Spike](superpowers/plans/2026-08-21-phase-1-dsh-capability-spike.md)：用真实 runtime 与 keyless endpoint 固定 Session、恢复、隔离和取消语义。
4. [Phase 2：公司与员工核心](superpowers/plans/2026-08-21-phase-2-company-core.md)：Workspace、Employee、Revision、基础工具授权、持久化、API 与 UI。
5. [Phase 3：Direct 工作闭环](superpowers/plans/2026-08-21-phase-3-direct-work.md)：单员工工作、DSH Gateway、历史、取消和重启恢复。
6. [Phase 4：权限、审批与委派](superpowers/plans/2026-08-21-phase-4-governance.md)：四层授权、Approval、Delegation 和治理 UI。
7. [Phase 5：Work Graph、评测与业务插件](superpowers/plans/2026-08-21-phase-5-work-graph-evaluation-and-plugins.md)：DurableGraphEngine、Star/Graph/Battle、MASEval 和插件边界。

## 当前状态

- 产品方向已经确认。
- 系统架构、编排设计和代码复用策略已经确认。
- Phase 1A 仓库与工程基础已实现并通过验收；Phase 1B DSH 公共能力 Spike 已实现，能力边界见固定矩阵。
- Phase 2 Company Core 已实现 Workspace、Employee、不可变 Revision、能力授权、稳定 Binding、
  SQLite 重启恢复、Workspace 隔离及管理 UI；创建流程完全本地，不需要 Provider 凭据且不启动 DSH。
- Phase 3 已接通 Direct Work 的 HTTP/UI 数据面、真实公开 DSH Gateway、Attempt 独占运行时、
  安全事件投影、ArtifactReference、取消请求/确认以及启动协调。Company DB 不保存原始
  transcript、工具参数或模型最终文本。
- 持久恢复的是 Company Core 事实。固定 DSH 公共 SDK 仍未公开 cold Session resume，稳定的
  Employee Binding 不代表进程退出后可恢复 live DSH Session。同一 Binding 的前一个 Harness
  关闭后，第二个 Work 在第二次模型请求前得到 SDK error；Company 将其记录为
  `failed/gateway_error`，不伪造成完成或自行实现 Memory/恢复框架。重启时发现的 RUNNING
  Attempt 记录为 `blocked/runtime_process_lost`。
- 原 `multi-agent` 仓库保持独立、可构建和可验证。

## 文档权威顺序

当文档之间出现冲突时，按以下顺序处理：

1. 已确认的产品方向决定产品语义；
2. 系统架构决定组件和数据所有权；
3. 编排与评测设计决定工作执行方式；
4. 代码复用策略只能影响迁移方法，不能改变前三者。

发现冲突时应修正文档，不允许通过代码兼容层同时保留两套相互矛盾的语义。

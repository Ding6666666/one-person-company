# DSH Company 文档

本文档集把产品方向、系统权威边界、编排机制和代码复用策略分开维护。实现代码必须以这些文档为边界；如果实现需要改变已确认的产品语义，应先修改并重新确认对应设计。

## 推荐阅读顺序

1. [产品方向](product/one-person-company-product-direction.md)：解释为什么做、Workspace 和 Employee 代表什么，以及第一阶段成功标准。
2. [系统架构](architecture/system.md)：定义 Company Core、DSH、Memory Provider 和业务插件的职责与权威数据源。
3. [图编排与评测](architecture/orchestration-and-evaluation.md)：定义 Company Work Graph、可替换编排引擎、DSH Gateway 和 benchmark 驱动的框架选择。
4. [`multi-agent` 代码复用策略](development/multi-agent-reuse.md)：定义哪些代码迁移、哪些只参考、哪些保留为软件开发插件。

## 当前状态

- 产品方向已经确认。
- 系统架构与编排设计已形成书面草案，等待最终复核后进入实施计划。
- `dsh-company` 尚未开始实现，不应在设计复核前创建业务代码骨架。
- 原 `multi-agent` 仓库保持独立、可构建和可验证。

## 文档权威顺序

当文档之间出现冲突时，按以下顺序处理：

1. 已确认的产品方向决定产品语义；
2. 系统架构决定组件和数据所有权；
3. 编排与评测设计决定工作执行方式；
4. 代码复用策略只能影响迁移方法，不能改变前三者。

发现冲突时应修正文档，不允许通过代码兼容层同时保留两套相互矛盾的语义。

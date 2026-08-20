# DSH 公共能力矩阵

本矩阵锁定 DSH Company Phase 1B 只通过公开 Python SDK 与 JSON-RPC 验证到的能力。
固定 DSH gitlink 为 `2db6ebd58523d14dca278e366ea0eb40499702b9`。未公开的能力在
Company Core 中不以替代实现伪造。

## 可重复验证

公共检查先准备上游提供的 Node runtime carrier，再运行不需要 Provider 凭据的真实
Session 测试：

```powershell
pnpm --dir vendor/deepseek-harness --config.verify-deps-before-run=warn run build:lib
pnpm --dir vendor/deepseek-harness --config.verify-deps-before-run=warn run build:python-runtime --node-only --skip-build
$env:DSH_RUNTIME_MODE = 'node'
uv run pytest apps/company-service/tests/dsh_gateway -q
uv run python tools/check.py
```

`tools/check.py` 只向子进程传递固定的非敏感环境变量，并固定
`DSH_RUNTIME_MODE=node`；它不会转发 Provider 凭据。
固定的 pnpm 11.7.0 会把 `-- --node-only` 中的分隔符原样传给 builder 并拒绝该位置参数，
所以公共门禁使用上面的等价形式 `--node-only`。门禁先完成一次 `build:lib`，再以
`--skip-build` 让 carrier builder 复用该产物；它不会跳过实际的 vendor lib 构建。门禁也把 pnpm 的依赖状态策略固定为只告警，
不允许它自动重写依赖；依赖仍由
仓库和 CI 的 frozen install 步骤准备。

## 已验证观察

| 能力 | 状态 | 公开证据 |
|---|---|---|
| `session.create` | `SUPPORTED` | 公开 Python SDK 接受指定 Session ID，并在结果中返回相同 ID。 |
| `session.resume` | `NOT_EXPOSED` | 公开 Python SDK 与 JSON-RPC 没有 cold-resume 入口；使用相同 root/ID 的新 runtime 在第二次模型请求前以 `id collision` 错误结束。 |
| `session.events` | `SUPPORTED` | 公开 `RunResult` 返回 root events 与 notifications。 |
| `session.cancel` | `CONSTRAINED` | 只能关闭单个 Attempt 所拥有的 `DeepSeekHarness`；`Session` 没有独立 cancel 方法。 |
| `attempt.observe` | `NOT_EXPOSED` | 公开 Python SDK 没有 Attempt 状态观察方法。 |
| `capability.list` | `NOT_EXPOSED` | 公开 Python SDK 没有 Tool、Skill、Connector 或 Runtime 的能力发现方法。 |
| `memory.provider` | `NOT_EXPOSED` | 公开 Python SDK 没有独立 Memory Provider API；当前只能使用 live runtime 内已支持的 Session 上下文。 |
| `identity.agent` | `CONSTRAINED` | `AgentRegistry` 契约令 Agent ID 等于 Session ID，而公开 Python SDK 只暴露 Session ID。 |

隔离测试还证明：两个不同 Session ID 的顺序独立 DSH 执行没有交叉携带另一个
Employee 的 marker。该结果不代表进程退出后可以恢复 Session。

## 产品决策与限制

- `EmployeeAgentBinding.dsh_agent_id = EmployeeAgentBinding.dsh_session_id`，直到公开 SDK
  暴露独立 Agent 身份。
- one running `ExecutionLink` owns one `DeepSeekHarness`；关闭 Harness 是当前唯一可验证的
  Attempt 取消语义。
- restart of an active `Attempt` becomes `blocked/runtime_process_lost`；Core 不把 ID collision
  解释为已恢复或已完成。
- employee continuity uses the persistent DSH `Session` 仅限 live runtime 与上述已支持范围；
  当前公开接口不保证 cold restart continuity。
- Company Core does not implement a substitute memory store；Memory Provider API 未公开时记录
  真实限制。
- runtime profiles are checked-in capability catalogs until DSH exposes discovery；这些目录是
  产品配置，不伪装成 DSH 动态发现结果。

此矩阵描述固定 revision 的公开能力。后续只有新的公开接口与真实测试证据才能改变状态。

import type { CoreAction, PermissionActionDefinition, PermissionPreset } from './types.js'

const text = (zh: string, en: string) => ({ zh, en }) as const

export const permissionActions: readonly PermissionActionDefinition[] = [
  { action: 'conversation.respond', label: text('回复对话', 'Respond'), description: text('在会话中返回工作结果', 'Return results in conversations'), level: 0, requiresApproval: false, runtimeSupported: true },
  { action: 'workspace.read', label: text('读取工作区', 'Read workspace'), description: text('查看工作区文件和上下文', 'Read workspace files and context'), level: 1, requiresApproval: false, runtimeSupported: true },
  { action: 'session.history.read', label: text('查看会话历史', 'Read session history'), description: text('读取自己的历史工作记录', 'Read its own work history'), level: 1, requiresApproval: false, runtimeSupported: true },
  { action: 'work.delegate', label: text('委派工作', 'Delegate work'), description: text('把明确任务交给其他员工', 'Delegate defined work to another employee'), level: 1, requiresApproval: false, runtimeSupported: true },
  { action: 'workspace.write', label: text('修改工作区', 'Modify workspace'), description: text('创建或修改工作区内容', 'Create or change workspace content'), level: 2, requiresApproval: false, runtimeSupported: true },
  { action: 'tool.shell', label: text('运行终端工具', 'Run terminal tools'), description: text('执行运行配置允许的命令', 'Run commands allowed by the runtime profile'), level: 2, requiresApproval: false, runtimeSupported: true },
  { action: 'tool.network', label: text('访问网络', 'Access network'), description: text('连接运行配置允许的外部服务', 'Connect to services allowed by the runtime'), level: 2, requiresApproval: true, runtimeSupported: true },
  { action: 'external.publish', label: text('对外发布', 'Publish externally'), description: text('向外部目标发布内容', 'Publish content to an external destination'), level: 3, requiresApproval: true, runtimeSupported: false },
]

const observer: readonly CoreAction[] = ['conversation.respond', 'workspace.read', 'session.history.read']
const collaborator: readonly CoreAction[] = [...observer, 'work.delegate']
const executor: readonly CoreAction[] = [...collaborator, 'workspace.write', 'tool.shell', 'tool.network']

export const permissionPresets: Readonly<Record<'observer' | 'collaborator' | 'executor' | 'administrator' | 'custom', PermissionPreset>> = {
  observer: { key: 'observer', label: text('观察者', 'Observer'), description: text('可以阅读、理解并回复，但不会修改内容。', 'Can read, understand, and respond without changing content.'), actions: observer },
  collaborator: { key: 'collaborator', label: text('协作者', 'Collaborator'), description: text('可以参与规划、评审和工作委派。', 'Can plan, review, and delegate work.'), actions: collaborator },
  executor: { key: 'executor', label: text('执行者', 'Executor'), description: text('可以修改工作区、运行工具并按授权访问网络。', 'Can modify the workspace, run tools, and use authorized network access.'), actions: executor },
  administrator: { key: 'administrator', label: text('管理员', 'Administrator'), description: text('包含执行能力，并展示需要审批的高权限动作。', 'Includes execution and approval-gated high-impact actions.'), actions: [...executor, 'external.publish'] },
  custom: { key: 'custom', label: text('自定义', 'Custom'), description: text('从执行者权限开始，逐项调整能力。', 'Starts from Executor and allows individual changes.'), actions: [...executor] },
}

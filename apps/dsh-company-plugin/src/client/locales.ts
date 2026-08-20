export const NS = 'dsh.company'

export const zh = {
  title: 'DSH Company',
  close: '关闭',
  createWorkspace: '创建工作区',
  createEmployee: '创建员工',
  workspaceName: '名称',
  confirmCreate: '确认创建',
  employeeName: '员工名称',
  responsibility: '职责',
  runtimeProfile: '运行配置',
  model: '模型',
  advancedGrants: '高级授权',
  grantAction: '授权动作',
  grantLevel: '授权等级',
  resourceKind: '资源类型',
  resourceValues: '资源范围',
  requiresApproval: '需要审批',
  addGrant: '添加授权',
  saveEmployee: '保存员工',
  cancel: '取消',
  loading: '正在加载',
  noWorkspace: '请先选择工作区',
  emptyEmployees: '还没有员工',
  nameRequired: '请输入名称',
  workspaceNameTooLong: '名称不能超过 120 个字符',
  employeeNameRequired: '请输入员工名称',
  employeeNameTooLong: '员工名称不能超过 120 个字符',
  responsibilityRequired: '请输入职责',
  responsibilityTooLong: '职责不能超过 4000 个字符',
  modelRequired: '请输入模型',
  modelTooLong: '模型不能超过 200 个字符',
  grantActionRequired: '请输入授权动作',
  grantActionTooLong: '授权动作不能超过 120 个字符',
  resourceKindRequired: '请输入资源类型',
  defaultGrants: '服务器默认授权',
} as const

export const en: Record<keyof typeof zh, string> = {
  title: 'DSH Company',
  close: 'Close',
  createWorkspace: 'Create workspace',
  createEmployee: 'Create employee',
  workspaceName: 'Name',
  confirmCreate: 'Confirm creation',
  employeeName: 'Employee name',
  responsibility: 'Responsibility',
  runtimeProfile: 'Runtime profile',
  model: 'Model',
  advancedGrants: 'Advanced grants',
  grantAction: 'Grant action',
  grantLevel: 'Grant level',
  resourceKind: 'Resource kind',
  resourceValues: 'Resource scope',
  requiresApproval: 'Requires approval',
  addGrant: 'Add grant',
  saveEmployee: 'Save employee',
  cancel: 'Cancel',
  loading: 'Loading',
  noWorkspace: 'Select a workspace first',
  emptyEmployees: 'No employees yet',
  nameRequired: 'Enter a name',
  workspaceNameTooLong: 'Name must be at most 120 characters',
  employeeNameRequired: 'Enter an employee name',
  employeeNameTooLong: 'Employee name must be at most 120 characters',
  responsibilityRequired: 'Enter a responsibility',
  responsibilityTooLong: 'Responsibility must be at most 4000 characters',
  modelRequired: 'Enter a model',
  modelTooLong: 'Model must be at most 200 characters',
  grantActionRequired: 'Enter a grant action',
  grantActionTooLong: 'Grant action must be at most 120 characters',
  resourceKindRequired: 'Enter a resource kind',
  defaultGrants: 'Server default grants',
}

export type CompanyLocaleKey = keyof typeof zh
export type CompanyLocale = 'zh' | 'en'
export type Translate = (key: CompanyLocaleKey) => string

export function translate(locale: CompanyLocale): Translate {
  const dictionary = locale === 'en' ? en : zh
  return key => dictionary[key]
}

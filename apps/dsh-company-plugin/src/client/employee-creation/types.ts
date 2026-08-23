export type RoleTemplateKey =
  | 'product-manager'
  | 'frontend-engineer'
  | 'backend-engineer'
  | 'fullstack-engineer'
  | 'algorithm-engineer'
  | 'test-engineer'
  | 'custom'

export type PermissionPresetKey = 'observer' | 'collaborator' | 'executor' | 'administrator' | 'custom'
export type CoreAction =
  | 'conversation.respond'
  | 'workspace.read'
  | 'session.history.read'
  | 'work.delegate'
  | 'workspace.write'
  | 'tool.shell'
  | 'tool.network'
  | 'external.publish'

export interface LocalizedText {
  readonly zh: string
  readonly en: string
}

export interface RoleTemplate {
  readonly key: RoleTemplateKey
  readonly avatarKey: RoleTemplateKey
  readonly name: LocalizedText
  readonly summary: LocalizedText
  readonly workType: LocalizedText
  readonly nicknameExample: LocalizedText
  readonly responsibility: LocalizedText
  readonly systemPrompt: LocalizedText
  readonly taskTags: readonly LocalizedText[]
  readonly permissionPreset: PermissionPresetKey
  readonly recommendedModel: string
  readonly skillRefs: readonly string[]
  readonly toolRefs: readonly string[]
}

export interface PermissionActionDefinition {
  readonly action: CoreAction
  readonly label: LocalizedText
  readonly description: LocalizedText
  readonly level: 0 | 1 | 2 | 3
  readonly requiresApproval: boolean
  readonly runtimeSupported: boolean
}

export interface PermissionPreset {
  readonly key: PermissionPresetKey
  readonly label: LocalizedText
  readonly description: LocalizedText
  readonly actions: readonly CoreAction[]
}

import { describe, expect, it } from 'vitest'

import { permissionPresets } from '../src/client/employee-creation/permissions.js'
import { roleTemplates } from '../src/client/employee-creation/roleTemplates.js'

describe('employee creation model', () => {
  it('publishes six product and technology templates plus custom', () => {
    expect(roleTemplates.map(template => template.key)).toEqual([
      'product-manager',
      'frontend-engineer',
      'backend-engineer',
      'fullstack-engineer',
      'algorithm-engineer',
      'test-engineer',
      'custom',
    ])
    expect(roleTemplates.every(template => template.skillRefs.length === 0 && template.toolRefs.length === 0)).toBe(true)
  })

  it('provides a structured professional system prompt for every role', () => {
    expect(roleTemplates.every(template =>
      template.systemPrompt.zh.includes('# 角色定位') &&
      template.systemPrompt.zh.includes('# 工作边界') &&
      template.systemPrompt.zh.includes('# 标准工作流程') &&
      template.systemPrompt.zh.includes('# 输出要求') &&
      template.systemPrompt.zh.includes('# 协作与汇报') &&
      template.systemPrompt.zh.includes('# 能力使用规则') &&
      template.systemPrompt.en.includes('# Role identity')
    )).toBe(true)
    expect(roleTemplates.find(template => template.key === 'custom')?.systemPrompt.zh).toContain('根据用户填写的工作类型和职责开展工作')
  })

  it('starts custom permissions with the executor action set', () => {
    expect(permissionPresets.custom.actions).toEqual(permissionPresets.executor.actions)
    expect(permissionPresets.custom.actions).not.toBe(permissionPresets.executor.actions)
  })
})

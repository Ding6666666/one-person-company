import { describe, expect, it } from 'vitest'

import { employeeAvatars } from '../src/client/employee-creation/avatars.js'
import { roleTemplates } from '../src/client/employee-creation/roleTemplates.js'

describe('employee avatar assets', () => {
  it('maps every role template to a packaged png', () => {
    expect(Object.keys(employeeAvatars)).toEqual(roleTemplates.map(template => template.avatarKey))
    expect(Object.values(employeeAvatars).every(source => source.startsWith('data:image/png;base64,') || source.includes('.png'))).toBe(true)
  })
})

// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'

import { cleanup, render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { EmployeeForm } from '../src/client/EmployeeForm.js'
import { translate } from '../src/client/locales.js'

afterEach(cleanup)

describe('employee creation wizard', () => {
  it('uses the work type as the display name when the optional nickname is blank', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(async () => undefined)
    render(<EmployeeForm pending={false} onCancel={() => undefined} onSave={onSave} t={translate('zh')} />)

    await user.click(screen.getByRole('button', { name: /产品经理/u }))
    await user.click(screen.getByRole('button', { name: '下一步' }))
    expect(screen.getByLabelText('昵称（选填）')).toHaveValue('')
    await user.click(screen.getByRole('button', { name: '下一步' }))
    await user.click(screen.getByRole('button', { name: '下一步' }))
    await user.click(screen.getByRole('button', { name: '下一步' }))

    expect(screen.getByRole('heading', { name: '产品管理' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: '创建员工' }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      display_name: '产品管理',
      work_type: '产品管理',
    }))
  })

  it('expands a role card and carries its editable defaults through all five steps', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn(async () => undefined)
    render(<EmployeeForm pending={false} onCancel={() => undefined} onSave={onSave} t={translate('zh')} />)

    await user.click(screen.getByRole('button', { name: /产品经理/u }))
    expect(screen.getByText('把用户需求转化为清晰、可执行的产品方案')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '下一步' }))
    expect(screen.getByLabelText('工作类型')).toHaveValue('产品管理')
    expect(screen.getByLabelText('昵称（选填）')).toHaveAttribute('placeholder', '例如：小策')

    await user.click(screen.getByRole('button', { name: '高级设置' }))
    expect(screen.getByLabelText<HTMLInputElement>('System Prompt').value).toContain('# 角色定位')
    await user.clear(screen.getByLabelText('System Prompt'))
    await user.type(screen.getByLabelText('System Prompt'), '使用经过确认的专业执行规则。')

    await user.type(screen.getByLabelText('昵称（选填）'), '小策')
    await user.click(screen.getByRole('button', { name: '下一步' }))
    await user.click(screen.getByRole('button', { name: /执行者/u }))
    expect(screen.getByText('可以修改工作区、运行工具并按授权访问网络。')).toBeVisible()
    expect(screen.getByRole('checkbox', { name: /回复对话/u }).closest('label')).toHaveAttribute('data-selected', 'true')
    expect(screen.getByRole('checkbox', { name: /对外发布/u }).closest('label')).toHaveAttribute('data-disabled', 'true')
    await user.click(screen.getByRole('button', { name: '下一步' }))
    expect(screen.getByText('暂未连接 Skill 来源')).toBeVisible()
    expect(screen.getByText('暂未连接 Tool 来源')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '下一步' }))
    expect(screen.getByRole('heading', { name: '确认员工档案' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: '创建员工' }))

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      display_name: '小策', role_template_key: 'product-manager', work_type: '产品管理',
      avatar_key: 'product-manager', runtime_profile: 'workspace_write', model: 'deepseek-v4-flash',
      system_prompt: '使用经过确认的专业执行规则。',
    }))
  })

  it('clears a nickname whenever a role card is selected', async () => {
    const user = userEvent.setup()
    render(<EmployeeForm pending={false} onCancel={() => undefined} onSave={async () => undefined} t={translate('zh')} />)

    await user.click(screen.getByRole('button', { name: /产品经理/u }))
    await user.click(screen.getByRole('button', { name: '下一步' }))
    await user.type(screen.getByLabelText('昵称（选填）'), '不会保留')
    await user.click(screen.getByRole('button', { name: '上一步' }))
    await user.click(screen.getByRole('button', { name: /前端工程师/u }))
    await user.click(screen.getByRole('button', { name: '下一步' }))

    expect(screen.getByLabelText('昵称（选填）')).toHaveValue('')
  })
})

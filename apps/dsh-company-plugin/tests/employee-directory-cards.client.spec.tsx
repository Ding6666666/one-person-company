// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'

import { cleanup, render, screen, within } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Employee } from '../src/client/api.js'
import { EmployeeDirectory } from '../src/client/EmployeeDirectory.js'
import { translate } from '../src/client/locales.js'

describe('employee directory cards', () => {
  afterEach(cleanup)

  it('shows team statistics and a guided empty state', async () => {
    const onCreate = vi.fn()
    const user = userEvent.setup()
    render(<EmployeeDirectory employees={[]} workspaceSelected onCreate={onCreate} t={translate('zh')} />)

    expect(screen.getByRole('region', { name: '员工中心' })).toBeVisible()
    expect(screen.getByText('员工总数').nextElementSibling).toHaveTextContent('0')
    expect(screen.getByRole('heading', { name: '组建你的第一支 AI 团队' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: '创建第一位员工' }))
    expect(onCreate).toHaveBeenCalledOnce()
  })

  it('uses the persisted role avatar and exposes the full role details', () => {
    const employee = {
      id: 'employee-1', workspace_id: 'workspace-1', display_name: '小策', status: 'active',
      current_revision_id: 'revision-1', created_at: '2026-08-22T00:00:00Z', binding: {}, grants: [],
      revision: { role_template_key: 'product-manager', avatar_key: 'product-manager', work_type: '产品管理', responsibility: '梳理需求与优先级', runtime_profile: 'workspace_read', model: 'deepseek-v4-flash', skill_refs: [], tool_refs: [] },
    } as unknown as Employee

    render(<EmployeeDirectory employees={[employee]} workspaceSelected onCreate={() => undefined} t={translate('zh')} />)

    expect(screen.getByRole('img', { name: '小策' })).toHaveAttribute('src', expect.stringContaining('product-manager.png'))
    expect(screen.getByText('产品管理')).toBeVisible()
    expect(screen.getByText('梳理需求与优先级')).toBeVisible()
  })

  it('opens complete employee details in a drawer and restores focus when closed', async () => {
    const employee = {
      id: 'employee-1', workspace_id: 'workspace-1', display_name: '小策', status: 'active',
      current_revision_id: 'revision-1', created_at: '2026-08-22T00:00:00Z', binding: {},
      grants: [{ action: 'workspace.read', level: 'allow', resource_kind: 'workspace', resource_values: [], requires_approval: false }],
      revision: { role_template_key: 'product-manager', avatar_key: 'product-manager', work_type: '产品管理', responsibility: '梳理需求与优先级', system_prompt: 'You are a product manager.', runtime_profile: 'workspace_read', model: 'deepseek-v4-flash', skill_refs: ['roadmap'], tool_refs: ['browser'] },
    } as unknown as Employee
    const user = userEvent.setup()
    render(<EmployeeDirectory employees={[employee]} workspaceSelected onCreate={() => undefined} t={translate('zh')} />)

    const trigger = screen.getByRole('button', { name: '查看小策详情' })
    await user.click(trigger)
    const drawer = screen.getByRole('dialog', { name: '员工详情' })
    expect(drawer).toHaveAttribute('data-variant', 'drawer')
    expect(within(drawer).getByText('roadmap')).toBeVisible()
    expect(within(drawer).getByText('browser')).toBeVisible()
    expect(within(drawer).getByText('workspace.read')).toBeVisible()
    await user.click(within(drawer).getByRole('button', { name: '关闭' }))
    expect(trigger).toHaveFocus()
  })
})

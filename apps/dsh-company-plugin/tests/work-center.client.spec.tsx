// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'

import { cleanup, render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { WorkProjection } from '../src/client/api.js'
import { translate } from '../src/client/locales.js'
import { WorkList } from '../src/client/WorkList.js'

afterEach(cleanup)

function work(id: string, status: WorkProjection['status']): WorkProjection {
  return { id, workspace_id: 'ws-1', command_id: `cmd-${id}`, objective: `任务 ${id}`, status, graph_revision_id: `graph-${id}`, graph_revision_number: 1, strategy: 'direct', created_at: '2026-08-22T00:00:00Z', nodes: [], execution_links: [], artifacts: [] }
}

describe('work center', () => {
  it('summarizes work and exposes status-rich cards', () => {
    render(<WorkList works={[work('1', 'running'), work('2', 'queued'), work('3', 'completed')]} workspaceSelected selectedWorkId={undefined} onSelect={() => undefined} onCreate={() => undefined} t={translate('zh')} />)

    expect(screen.getByRole('region', { name: '工作中心' })).toBeVisible()
    expect(screen.getByText('任务总数').nextElementSibling).toHaveTextContent('3')
    expect(screen.getByText('执行中').nextElementSibling).toHaveTextContent('1')
    expect(screen.getByRole('link', { name: '任务 1' }).closest('li')).toHaveAttribute('data-status', 'running')
  })

  it('uses a guided empty state to create work', async () => {
    const onCreate = vi.fn()
    const user = userEvent.setup()
    render(<WorkList works={[]} workspaceSelected selectedWorkId={undefined} onSelect={() => undefined} onCreate={onCreate} t={translate('zh')} />)
    expect(screen.getByRole('heading', { name: '给团队安排第一项工作' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: '创建第一项工作' }))
    expect(onCreate).toHaveBeenCalledOnce()
  })
})

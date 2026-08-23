// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { CompanySurface } from '../src/client/CompanySurface.js'
import type { CompanyTransportRequest, RemoteResult } from '../src/remote-contract.js'

afterEach(cleanup)

describe('Company workbench', () => {
  it('presents compact company navigation and loads the selected center', async () => {
    const requests: CompanyTransportRequest[] = []
    const remote = {
      async request(input: CompanyTransportRequest): Promise<RemoteResult<unknown>> {
        requests.push(input)
        if (input.method === 'GET' && input.path === '/workspaces') {
          return { status: 200, body: [{ id: 'ws-1', name: '软件开发公司', created_at: '2026-08-22T00:00:00Z' }] }
        }
        if (input.method === 'GET' && input.path === '/workspaces/ws-1/employees') {
          return { status: 200, body: [] }
        }
        if (input.method === 'GET' && input.path === '/workspaces/ws-1/messages') {
          return { status: 200, body: { messages: [] } }
        }
        if (input.method === 'GET' && input.path === '/workspaces/ws-1/works') {
          return { status: 200, body: [] }
        }
        throw new Error(`Unexpected request: ${input.method} ${input.path}`)
      },
    }
    const user = userEvent.setup()

    render(<CompanySurface remote={remote} initialWorkspaceId="ws-1" />)

    const navigation = await screen.findByRole('navigation', { name: '公司导航' })
    expect(navigation).toBeVisible()
    expect(within(navigation).getByRole('link', { name: '公司群聊' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: /软件开发公司/u })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('main')).toHaveAttribute('data-company-page', 'chat')

    await user.click(within(navigation).getByRole('link', { name: '工作' }))

    expect(within(navigation).getByRole('link', { name: '工作' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('main')).toHaveAttribute('data-company-page', 'work')
    await waitFor(() => expect(requests).toContainEqual(expect.objectContaining({
      method: 'GET',
      path: '/workspaces/ws-1/works',
    })))
  })
})

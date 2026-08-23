// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'

import { cleanup, render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { vi } from 'vitest'

import type { ChatMessageProjection, Employee } from '../src/client/api.js'
import { filterMentionCandidates, mentionEmployeeIds } from '../src/client/chat/mention.js'
import { CompanyChat } from '../src/client/CompanyChat.js'
import { ProductApi } from '../src/client/api.js'
import { CompanyController } from '../src/client/controller.js'
import { translate } from '../src/client/locales.js'
import type { CompanyTransportRequest, RemoteResult } from '../src/remote-contract.js'

afterEach(cleanup)

const employee = (id: string, name: string, workType: string, responsibility: string): Employee => ({
  id,
  workspace_id: 'ws-1',
  display_name: name,
  status: 'active',
  current_revision_id: `revision-${id}`,
  created_at: '2026-08-23T00:00:00Z',
  revision: {
    id: `revision-${id}`,
    employee_id: id,
    revision_number: 1,
    responsibility,
    system_prompt: '完成职责范围内的工作。',
    runtime_profile: 'workspace_write',
    model: 'deepseek-v4-flash',
    created_at: '2026-08-23T00:00:00Z',
    role_template_key: 'custom',
    work_type: workType,
    avatar_key: 'custom',
    skill_refs: [],
    tool_refs: [],
  },
  binding: {
    id: `binding-${id}`,
    employee_id: id,
    dsh_agent_id: `agent-${id}`,
    dsh_session_id: `session-${id}`,
    memory_scope_id: `memory-${id}`,
    created_at: '2026-08-23T00:00:00Z',
  },
  grants: [],
})

describe('company chat mentions', () => {
  const employees = [
    employee('emp-product', '小策', '产品经理', '负责需求分析与产品规划'),
    employee('emp-front', '小前', '前端工程师', '负责交互界面实现'),
  ]

  it('filters candidates by nickname, role, and responsibility', () => {
    expect(filterMentionCandidates(employees, '小策').map(item => item.id)).toEqual(['emp-product'])
    expect(filterMentionCandidates(employees, '前端').map(item => item.id)).toEqual(['emp-front'])
    expect(filterMentionCandidates(employees, '需求分析').map(item => item.id)).toEqual(['emp-product'])
  })

  it('serializes selected employees to stable unique ids', () => {
    expect(mentionEmployeeIds([employees[1]!, employees[0]!, employees[1]!])).toEqual([
      'emp-front',
      'emp-product',
    ])
  })
})

describe('CompanyChat', () => {
  const employees = [
    employee('emp-product', '小策', '产品经理', '负责需求分析与产品规划'),
    employee('emp-front', '小前', '前端工程师', '负责交互界面实现'),
  ]

  it('selects an employee from @ autocomplete and sends its stable id', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn(async () => {})
    render(<CompanyChat
      messages={[]}
      employees={employees}
      workspaceSelected
      pending={false}
      onSend={onSend}
      onRetry={async () => {}}
      onOpenWork={async () => {}}
      t={translate('zh')}
    />)

    await user.type(screen.getByLabelText('发送消息'), '@前')
    await user.click(screen.getByRole('option', { name: /小前.*前端工程师/u }))
    await user.type(screen.getByLabelText('发送消息'), '请检查首页')
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect(onSend).toHaveBeenCalledWith('@小前 请检查首页', ['emp-front'])
  })

  it('shows employee execution states and opens a task discussion', async () => {
    const user = userEvent.setup()
    const onOpenWork = vi.fn(async () => {})
    const message: ChatMessageProjection = {
      id: 'message-1',
      workspace_id: 'ws-1',
      author_kind: 'system',
      message_kind: 'work_card',
      body: '产品官网改版',
      employee_id: null,
      reply_to_message_id: null,
      work_id: 'work-1',
      created_at: '2026-08-23T00:00:00Z',
      mentions: ['emp-product'],
      executions: [{
        id: 'execution-1', message_id: 'message-1', employee_id: 'emp-product', status: 'running',
        failure_code: null, retry_count: 0, created_at: '2026-08-23T00:00:00Z', updated_at: '2026-08-23T00:00:00Z',
      }],
      work_card: {
        id: 'work-1', objective: '产品官网改版', status: 'running', strategy: 'star', employee_ids: ['emp-product'],
      },
    }
    render(<CompanyChat
      messages={[message]}
      employees={employees}
      workspaceSelected
      pending={false}
      onSend={async () => {}}
      onRetry={async () => {}}
      onOpenWork={onOpenWork}
      t={translate('zh')}
    />)

    expect(screen.getByText('执行中')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '打开任务讨论串' }))
    expect(onOpenWork).toHaveBeenCalledWith('work-1')
  })
})

describe('company chat controller', () => {
  it('loads the company conversation and sends structured mention ids', async () => {
    const requests: CompanyTransportRequest[] = []
    const remote = {
      async request(input: CompanyTransportRequest): Promise<RemoteResult<unknown>> {
        requests.push(input)
        if (input.method === 'GET' && input.path === '/workspaces/ws-1/employees') return { status: 200, body: [] }
        if (input.method === 'GET' && input.path === '/workspaces/ws-1/messages') return { status: 200, body: { messages: [] } }
        if (input.method === 'POST' && input.path === '/workspaces/ws-1/messages') {
          return {
            status: 201,
            body: {
              id: 'message-1', workspace_id: 'ws-1', author_kind: 'user', message_kind: 'text',
              body: '@小前 检查首页', employee_id: null, reply_to_message_id: null, work_id: null,
              created_at: '2026-08-23T00:00:00Z', mentions: ['emp-front'], executions: [], work_card: null,
            },
          }
        }
        throw new Error(`Unexpected request: ${input.method} ${input.path}`)
      },
    }
    const controller = new CompanyController(new ProductApi(remote))

    await controller.selectWorkspace('ws-1')
    await controller.sendChatMessage('@小前 检查首页', ['emp-front'])

    expect(controller.snapshot().messages).toHaveLength(1)
    expect(requests.at(-1)).toMatchObject({
      method: 'POST', path: '/workspaces/ws-1/messages',
      body: { body: '@小前 检查首页', mention_employee_ids: ['emp-front'] },
    })
  })
})

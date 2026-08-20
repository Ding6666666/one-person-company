// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import type { components } from '../src/contracts/generated/openapi.js'
import type { CompanyRemoteNamespace, CompanyTransportRequest, RemoteResult } from '../src/remote-contract.js'
import { createCompanyRemote, ProductApi } from '../src/client/api.js'
import { CompanyController } from '../src/client/controller.js'
import { CompanySurface } from '../src/client/CompanySurface.js'

type Schemas = components['schemas']

const now = '2026-08-21T00:00:00Z'

afterEach(cleanup)

function employee(workspaceId: string, id: string, displayName: string): Schemas['Employee'] {
  return {
    id,
    workspace_id: workspaceId,
    display_name: displayName,
    status: 'active',
    current_revision_id: `revision-${id}`,
    created_at: now,
    revision: {
      id: `revision-${id}`,
      employee_id: id,
      revision_number: 1,
      responsibility: 'Write',
      runtime_profile: 'workspace_read',
      model: 'deepseek-v4-flash',
      created_at: now,
    },
    binding: {
      id: `binding-${id}`,
      employee_id: id,
      dsh_agent_id: `employee-${id}`,
      dsh_session_id: `employee-${id}`,
      memory_scope_id: `employee-${id}`,
      created_at: now,
    },
    grants: [],
  }
}

class DeferredCompanyRemote implements CompanyRemoteNamespace {
  private readonly pending: Array<{
    readonly input: CompanyTransportRequest
    readonly resolve: (result: RemoteResult<unknown>) => void
  }> = []

  async connection(): Promise<RemoteResult<{ readonly status: 'online' }>> {
    return { status: 200, body: { status: 'online' } }
  }

  request(input: CompanyTransportRequest): Promise<RemoteResult<unknown>> {
    return new Promise(resolve => this.pending.push({ input, resolve }))
  }

  respond(method: 'GET' | 'POST', path: string, body: unknown): void {
    const index = this.pending.findIndex(item => item.input.method === method && item.input.path === path)
    if (index < 0) throw new Error(`No pending request for ${method} ${path}`)
    const [request] = this.pending.splice(index, 1)
    request!.resolve({ status: method === 'POST' ? 201 : 200, body })
  }
}

class FakeCompanyRemote implements CompanyRemoteNamespace {
  readonly executionCalls: unknown[] = []
  readonly requests: CompanyTransportRequest[] = []
  readonly workspaces: Schemas['Workspace'][] = []
  readonly employees = new Map<string, Schemas['Employee'][]>()
  listFailure = false
  workspaceCreateFailure = false
  employeeCreateFailure = false

  async connection(): Promise<RemoteResult<{ readonly status: 'online' }>> {
    return { status: 200, body: { status: 'online' } }
  }

  async request(input: CompanyTransportRequest): Promise<RemoteResult<unknown>> {
    this.requests.push(input)
    if (input.method === 'GET' && input.path === '/workspaces') {
      if (this.listFailure) {
        return {
          status: 503,
          body: { error: { code: 'company_unavailable', message: 'Unavailable', correlation_id: 'corr-1' } },
        }
      }
      return { status: 200, body: [...this.workspaces] }
    }
    if (input.method === 'POST' && input.path === '/workspaces') {
      if (this.workspaceCreateFailure) {
        this.workspaceCreateFailure = false
        return {
          status: 503,
          body: { error: { code: 'workspace_create_failed', message: 'Unavailable', correlation_id: 'corr-workspace' } },
        }
      }
      const body = input.body as Schemas['WorkspaceCreate']
      const workspace: Schemas['Workspace'] = { id: `ws-${this.workspaces.length + 1}`, name: body.name, created_at: now }
      this.workspaces.push(workspace)
      this.employees.set(workspace.id, [])
      return { status: 201, body: workspace }
    }
    const employeesPath = /^\/workspaces\/([^/]+)\/employees$/u.exec(input.path)
    if (employeesPath !== null) {
      const workspaceId = decodeURIComponent(employeesPath[1]!)
      if (input.method === 'GET') return { status: 200, body: [...(this.employees.get(workspaceId) ?? [])] }
      if (this.employeeCreateFailure) {
        this.employeeCreateFailure = false
        return {
          status: 503,
          body: { error: { code: 'employee_create_failed', message: 'Unavailable', correlation_id: 'corr-employee' } },
        }
      }
      const body = input.body as Schemas['EmployeeCreate']
      const id = `emp-${(this.employees.get(workspaceId)?.length ?? 0) + 1}`
      const employee: Schemas['Employee'] = {
        id,
        workspace_id: workspaceId,
        display_name: body.display_name,
        status: 'active',
        current_revision_id: `revision-${id}`,
        created_at: now,
        revision: {
          id: `revision-${id}`,
          employee_id: id,
          revision_number: 1,
          responsibility: body.responsibility,
          runtime_profile: body.runtime_profile,
          model: body.model,
          created_at: now,
        },
        binding: {
          id: `binding-${id}`,
          employee_id: id,
          dsh_agent_id: `employee-${id}`,
          dsh_session_id: `employee-${id}`,
          memory_scope_id: `employee-${id}`,
          created_at: now,
        },
        grants: [],
      }
      this.employees.get(workspaceId)?.push(employee)
      return { status: 201, body: employee }
    }
    throw new Error(`Unexpected fake request: ${input.method} ${input.path}`)
  }
}

describe('Company core client', () => {
  it('keeps the latest workspace employees when an earlier selection resolves last', async () => {
    const remote = new DeferredCompanyRemote()
    const controller = new CompanyController(new ProductApi(remote))

    const selectA = controller.selectWorkspace('ws-a')
    const selectB = controller.selectWorkspace('ws-b')
    remote.respond('GET', '/workspaces/ws-b/employees', [employee('ws-b', 'emp-b', 'B')])
    await selectB
    remote.respond('GET', '/workspaces/ws-a/employees', [employee('ws-a', 'emp-a', 'A')])
    await selectA

    expect(controller.snapshot()).toMatchObject({
      selectedWorkspaceId: 'ws-b',
      employees: [{ id: 'emp-b' }],
    })
  })

  it('discards a late employee create result after selection moves to another workspace', async () => {
    const remote = new DeferredCompanyRemote()
    const controller = new CompanyController(new ProductApi(remote))
    const selectA = controller.selectWorkspace('ws-a')
    remote.respond('GET', '/workspaces/ws-a/employees', [])
    await selectA

    const createA = controller.createEmployee({
      display_name: 'A', responsibility: 'Write', runtime_profile: 'workspace_read', model: 'deepseek-v4-flash', grants: [],
    })
    const selectB = controller.selectWorkspace('ws-b')
    remote.respond('GET', '/workspaces/ws-b/employees', [employee('ws-b', 'emp-b', 'B')])
    await selectB
    remote.respond('POST', '/workspaces/ws-a/employees', employee('ws-a', 'emp-a', 'A'))

    await expect(createA).resolves.toBeUndefined()
    expect(controller.snapshot()).toMatchObject({
      selectedWorkspaceId: 'ws-b',
      pending: false,
      employees: [{ id: 'emp-b' }],
    })
  })

  it('maps a failed Typert carrier connection to the stable offline state', async () => {
    const remote = createCompanyRemote({
      connection: async () => ({ ok: false, error: new Error('carrier unavailable') }),
      request: async () => ({ ok: false, error: new Error('carrier unavailable') }),
    })

    await expect(remote.connection()).resolves.toEqual({
      status: 503,
      body: { status: 'offline', code: 'COMPANY_SERVICE_UNAVAILABLE' },
    })
  })

  it('creates a workspace and employee without starting DSH execution', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    render(<CompanySurface remote={remote} />)

    await user.click(await screen.findByRole('button', { name: '创建工作区' }))
    await user.type(screen.getByLabelText('名称'), '内容公司')
    await user.click(screen.getByRole('button', { name: '确认创建' }))
    await user.click(await screen.findByRole('link', { name: '内容公司' }))
    await user.click(screen.getByRole('button', { name: '创建员工' }))

    expect(screen.getByText('conversation.respond')).toBeVisible()
    expect(screen.getByText('workspace.read')).toBeVisible()
    expect(screen.getByText('session.history.read')).toBeVisible()
    await user.type(screen.getByLabelText('员工名称'), '编辑')
    await user.type(screen.getByLabelText('职责'), '撰写内容')
    await user.selectOptions(screen.getByLabelText('运行配置'), 'workspace_write')
    await user.clear(screen.getByLabelText('模型'))
    await user.type(screen.getByLabelText('模型'), 'deepseek-chat')
    await user.click(screen.getByRole('button', { name: '高级授权' }))
    expect(screen.getByLabelText('授权动作')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '保存员工' }))

    expect(await screen.findByRole('heading', { name: '编辑' })).toBeVisible()
    expect(remote.executionCalls).toEqual([])
    expect(remote.requests.at(-1)).toMatchObject({
      method: 'POST',
      path: '/workspaces/ws-1/employees',
      body: {
        display_name: '编辑',
        responsibility: '撰写内容',
        runtime_profile: 'workspace_write',
        model: 'deepseek-chat',
        grants: [],
      },
    })
  })

  it('clears the workspace mutation error phase after a successful retry', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    remote.workspaceCreateFailure = true
    render(<CompanySurface remote={remote} />)

    await user.click(await screen.findByRole('button', { name: '创建工作区' }))
    await user.type(screen.getByLabelText('名称'), '内容公司')
    await user.click(screen.getByRole('button', { name: '确认创建' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('workspace_create_failed')

    await user.click(screen.getByRole('button', { name: '确认创建' }))
    expect(await screen.findByRole('link', { name: '内容公司' })).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('clears the employee mutation error phase after a successful retry', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    render(<CompanySurface remote={remote} />)
    await user.click(await screen.findByRole('button', { name: '创建工作区' }))
    await user.type(screen.getByLabelText('名称'), '内容公司')
    await user.click(screen.getByRole('button', { name: '确认创建' }))
    await user.click(await screen.findByRole('link', { name: '内容公司' }))
    await user.click(screen.getByRole('button', { name: '创建员工' }))
    await user.type(screen.getByLabelText('员工名称'), '编辑')
    await user.type(screen.getByLabelText('职责'), '撰写内容')
    remote.employeeCreateFailure = true

    await user.click(screen.getByRole('button', { name: '保存员工' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('employee_create_failed')
    await user.click(screen.getByRole('button', { name: '保存员工' }))

    expect(await screen.findByRole('heading', { name: '编辑' })).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('validates the published workspace name length before sending', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    render(<CompanySurface remote={remote} />)
    await user.click(await screen.findByRole('button', { name: '创建工作区' }))
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: 'x'.repeat(121) } })
    await user.click(screen.getByRole('button', { name: '确认创建' }))

    expect(screen.getByRole('alert')).toHaveTextContent('名称不能超过 120 个字符')
    expect(remote.requests.filter(request => request.method === 'POST' && request.path === '/workspaces')).toEqual([])
  })

  it.each([
    ['员工名称', 121, '员工名称不能超过 120 个字符', false],
    ['职责', 4001, '职责不能超过 4000 个字符', false],
    ['模型', 201, '模型不能超过 200 个字符', false],
    ['授权动作', 121, '授权动作不能超过 120 个字符', true],
  ] as const)('validates the published %s length before sending', async (label, length, message, advanced) => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    render(<CompanySurface remote={remote} />)
    await user.click(await screen.findByRole('button', { name: '创建工作区' }))
    await user.type(screen.getByLabelText('名称'), '内容公司')
    await user.click(screen.getByRole('button', { name: '确认创建' }))
    await user.click(await screen.findByRole('link', { name: '内容公司' }))
    await user.click(screen.getByRole('button', { name: '创建员工' }))
    fireEvent.change(screen.getByLabelText('员工名称'), { target: { value: '编辑' } })
    fireEvent.change(screen.getByLabelText('职责'), { target: { value: '撰写内容' } })
    if (advanced) await user.click(screen.getByRole('button', { name: '高级授权' }))
    fireEvent.change(screen.getByLabelText(label), { target: { value: 'x'.repeat(length) } })
    await user.click(screen.getByRole('button', { name: '保存员工' }))

    expect(screen.getByRole('alert')).toHaveTextContent(message)
    expect(remote.requests.filter(request =>
      request.method === 'POST' && /\/employees$/u.test(request.path),
    )).toEqual([])
  })

  it('requires a selected workspace and renders explicit loading and errors', async () => {
    const remote = new FakeCompanyRemote()
    remote.listFailure = true
    render(<CompanySurface remote={remote} />)

    expect(screen.getByRole('status')).toHaveTextContent('正在加载')
    expect(await screen.findByRole('alert')).toHaveTextContent('company_unavailable')
    expect(screen.getByRole('button', { name: '创建员工' })).toBeDisabled()
  })

  it('validates an explicit grant locally before sending an employee request', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    render(<CompanySurface remote={remote} />)

    await user.click(await screen.findByRole('button', { name: '创建工作区' }))
    await user.type(screen.getByLabelText('名称'), '内容公司')
    await user.click(screen.getByRole('button', { name: '确认创建' }))
    await user.click(await screen.findByRole('link', { name: '内容公司' }))
    await user.click(screen.getByRole('button', { name: '创建员工' }))
    await user.type(screen.getByLabelText('员工名称'), '编辑')
    await user.type(screen.getByLabelText('职责'), '撰写内容')
    await user.click(screen.getByRole('button', { name: '高级授权' }))
    await user.type(screen.getByLabelText('授权动作'), ' workspace.write ')
    await user.clear(screen.getByLabelText('资源类型'))
    await user.click(screen.getByRole('button', { name: '保存员工' }))

    expect(screen.getByRole('alert')).toHaveTextContent('请输入资源类型')
    expect(remote.requests.filter(request =>
      request.method === 'POST' && /\/employees$/u.test(request.path),
    )).toEqual([])

    await user.type(screen.getByLabelText('资源类型'), ' workspace ')
    await user.click(screen.getByRole('button', { name: '保存员工' }))
    expect(await screen.findByRole('heading', { name: '编辑' })).toBeVisible()
    expect(remote.requests.at(-1)).toMatchObject({
      body: {
        grants: [{ action: 'workspace.write', resource_kind: 'workspace' }],
      },
    })
  })

  it('labels and validates dialogs, traps focus, closes on Escape, and restores trigger focus', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    render(<CompanySurface remote={remote} />)
    const trigger = await screen.findByRole('button', { name: '创建工作区' })

    await user.click(trigger)
    const name = screen.getByLabelText('名称')
    const submit = screen.getByRole('button', { name: '确认创建' })
    expect(name).toHaveFocus()
    await user.click(submit)
    expect(screen.getByRole('alert')).toHaveTextContent('请输入名称')

    submit.focus()
    await user.tab()
    expect(name).toHaveFocus()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('renders English copy from the locale map', async () => {
    const remote = new FakeCompanyRemote()
    render(<CompanySurface remote={remote} locale="en" />)

    expect(await screen.findByRole('button', { name: 'Create workspace' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Create employee' })).toBeDisabled()
  })
})

// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
      system_prompt: 'Act as a professional employee.',
      runtime_profile: 'workspace_read',
      model: 'deepseek-v4-flash',
      created_at: now,
      role_template_key: 'custom',
      work_type: '自定义工作',
      avatar_key: 'custom',
      skill_refs: [],
      tool_refs: [],
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
  legacyEmployeeResponse = false

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
          system_prompt: body.system_prompt,
          runtime_profile: body.runtime_profile,
          model: body.model,
          created_at: now,
          role_template_key: body.role_template_key,
          work_type: body.work_type,
          avatar_key: body.avatar_key,
          skill_refs: body.skill_refs ?? [],
          tool_refs: body.tool_refs ?? [],
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
      if (this.legacyEmployeeResponse) {
        const response = structuredClone(employee) as unknown as { revision: Record<string, unknown> }
        delete response.revision.system_prompt
        return { status: 201, body: response }
      }
      return { status: 201, body: employee }
    }
    throw new Error(`Unexpected fake request: ${input.method} ${input.path}`)
  }
}

async function openCustomProfile(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(screen.getByRole('button', { name: /自定义角色/u }))
  await user.click(screen.getByRole('button', { name: '下一步' }))
}

async function fillCustomProfile(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.type(screen.getByLabelText('工作类型'), '内容运营')
  await user.type(screen.getByLabelText('昵称（选填）'), '编辑')
  await user.type(screen.getByLabelText('职责'), '撰写内容')
}

async function reachEmployeeReview(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(screen.getByRole('button', { name: '下一步' }))
  await user.click(screen.getByRole('button', { name: '下一步' }))
  await user.click(screen.getByRole('button', { name: '下一步' }))
}

describe('Company core client', () => {
  it('normalizes employee revision fields omitted by observed local service versions', async () => {
    const complete = employee('ws-1', 'emp-1', '产品经理')
    const withoutPrompt = structuredClone(complete) as unknown as { revision: Record<string, unknown> }
    delete withoutPrompt.revision.system_prompt
    const legacy = structuredClone(withoutPrompt)
    delete legacy.revision.role_template_key
    delete legacy.revision.work_type
    delete legacy.revision.avatar_key
    delete legacy.revision.skill_refs
    delete legacy.revision.tool_refs
    const responses = [withoutPrompt, legacy]
    const api = new ProductApi({
      request: async () => ({ status: 201, body: responses.shift() }),
    })
    const input: Schemas['EmployeeCreate'] = {
      display_name: '产品经理', role_template_key: 'product-manager', work_type: '产品管理', avatar_key: 'product-manager',
      responsibility: '规划产品', system_prompt: '专业完成产品工作。', runtime_profile: 'workspace_write', model: 'deepseek-v4-flash',
    }

    await expect(api.createEmployee('ws-1', input)).resolves.toMatchObject({
      revision: { system_prompt: '' },
    })
    await expect(api.createEmployee('ws-1', input)).resolves.toMatchObject({
      revision: {
        system_prompt: '', role_template_key: 'custom', work_type: '自定义工作', avatar_key: 'custom',
        skill_refs: [], tool_refs: [],
      },
    })
  })

  it('still rejects an employee response missing a core binding', async () => {
    const invalid = structuredClone(employee('ws-1', 'emp-1', '产品经理')) as unknown as Record<string, unknown>
    delete invalid.binding
    const api = new ProductApi({ request: async () => ({ status: 201, body: invalid }) })

    await expect(api.createEmployee('ws-1', {
      display_name: '产品经理', role_template_key: 'product-manager', work_type: '产品管理', avatar_key: 'product-manager',
      responsibility: '规划产品', system_prompt: '专业完成产品工作。', runtime_profile: 'workspace_write', model: 'deepseek-v4-flash',
    })).rejects.toMatchObject({ code: 'invalid_company_response' })
  })

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
      display_name: 'A', role_template_key: 'custom', work_type: '自定义工作', avatar_key: 'custom',
      responsibility: 'Write', system_prompt: 'Act as a professional employee.', runtime_profile: 'workspace_read', model: 'deepseek-v4-flash', grants: [],
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
    await openCustomProfile(user)
    await fillCustomProfile(user)
    await reachEmployeeReview(user)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '创建员工' }))

    expect(await screen.findByRole('heading', { name: '编辑' })).toBeVisible()
    expect(remote.executionCalls).toEqual([])
    expect(remote.requests.at(-1)).toMatchObject({
      method: 'POST',
      path: '/workspaces/ws-1/employees',
      body: {
        display_name: '编辑',
        role_template_key: 'custom',
        work_type: '内容运营',
        responsibility: '撰写内容',
        runtime_profile: 'workspace_write',
        model: 'deepseek-v4-flash',
      },
    })
  })

  it('provides an explicit close control on the employee creation dialog', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    remote.workspaces.push({ id: 'ws-1', name: '内容公司', created_at: now })
    remote.employees.set('ws-1', [])
    render(<CompanySurface remote={remote} />)

    await user.click(await screen.findByRole('link', { name: '内容公司' }))
    await user.click(screen.getByRole('button', { name: '创建员工' }))
    const dialog = screen.getByRole('dialog', { name: '创建员工' })
    await user.click(within(dialog).getByRole('button', { name: '关闭创建员工' }))

    expect(screen.queryByRole('dialog', { name: '创建员工' })).not.toBeInTheDocument()
  })

  it('closes the dialog and renders the employee after an observed legacy success response', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    remote.legacyEmployeeResponse = true
    remote.workspaces.push({ id: 'ws-1', name: '内容公司', created_at: now })
    remote.employees.set('ws-1', [])
    render(<CompanySurface remote={remote} />)

    await user.click(await screen.findByRole('link', { name: '内容公司' }))
    await user.click(screen.getByRole('button', { name: '创建员工' }))
    await openCustomProfile(user)
    await user.type(screen.getByLabelText('工作类型'), '内容运营')
    await user.type(screen.getByLabelText('职责'), '撰写内容')
    await reachEmployeeReview(user)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '创建员工' }))

    await waitFor(() => expect(screen.queryByRole('dialog', { name: '创建员工' })).not.toBeInTheDocument())
    expect(await screen.findByRole('heading', { name: '内容运营' })).toBeVisible()
    expect(screen.queryByText('invalid_company_response')).not.toBeInTheDocument()
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
    await openCustomProfile(user)
    await fillCustomProfile(user)
    await reachEmployeeReview(user)
    remote.employeeCreateFailure = true

    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '创建员工' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('employee_create_failed')
    expect(screen.getByRole('dialog', { name: '创建员工' })).toBeVisible()
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '创建员工' }))

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

  it('validates the editable employee profile before advancing', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    render(<CompanySurface remote={remote} />)
    await user.click(await screen.findByRole('button', { name: '创建工作区' }))
    await user.type(screen.getByLabelText('名称'), '内容公司')
    await user.click(screen.getByRole('button', { name: '确认创建' }))
    await user.click(await screen.findByRole('link', { name: '内容公司' }))
    await user.click(screen.getByRole('button', { name: '创建员工' }))
    await openCustomProfile(user)
    fireEvent.change(screen.getByLabelText('工作类型'), { target: { value: '内容运营' } })
    fireEvent.change(screen.getByLabelText('昵称（选填）'), { target: { value: 'x'.repeat(121) } })
    fireEvent.change(screen.getByLabelText('职责'), { target: { value: '撰写内容' } })
    await user.click(screen.getByRole('button', { name: '下一步' }))

    expect(screen.getByRole('alert')).toHaveTextContent('请完整填写工作类型和职责。')
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

  it('starts custom permissions from the executor actions', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    render(<CompanySurface remote={remote} />)

    await user.click(await screen.findByRole('button', { name: '创建工作区' }))
    await user.type(screen.getByLabelText('名称'), '内容公司')
    await user.click(screen.getByRole('button', { name: '确认创建' }))
    await user.click(await screen.findByRole('link', { name: '内容公司' }))
    await user.click(screen.getByRole('button', { name: '创建员工' }))
    await openCustomProfile(user)
    await fillCustomProfile(user)
    await user.click(screen.getByRole('button', { name: '下一步' }))
    await user.click(screen.getByRole('button', { name: /自定义/u }))
    expect(screen.getByLabelText(/修改工作区/u)).toBeChecked()
    await user.click(screen.getByRole('button', { name: '下一步' }))
    await user.click(screen.getByRole('button', { name: '下一步' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '创建员工' }))
    expect(await screen.findByRole('heading', { name: '编辑' })).toBeVisible()
    const request = remote.requests.at(-1)!
    expect((request.body as Schemas['EmployeeCreate']).grants).toEqual(expect.arrayContaining([
      expect.objectContaining({ action: 'workspace.write', resource_kind: 'workspace' }),
    ]))
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
    expect(screen.getByRole('button', { name: '关闭' })).toHaveFocus()
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

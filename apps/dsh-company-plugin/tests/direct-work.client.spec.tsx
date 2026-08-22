// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CompanySurface } from '../src/client/CompanySurface.js'
import { WorkDetail } from '../src/client/WorkDetail.js'
import { ProductApi } from '../src/client/api.js'
import { CompanyController } from '../src/client/controller.js'
import { translate } from '../src/client/locales.js'
import type { components } from '../src/contracts/generated/openapi.js'
import type { CompanyRemoteNamespace, CompanyTransportRequest, RemoteResult } from '../src/remote-contract.js'

type Schemas = components['schemas']
type Work = Schemas['WorkProjection']

const now = '2026-08-21T00:00:00Z'

const workspace: Schemas['Workspace'] = { id: 'ws-1', name: '内容公司', created_at: now }
const employee: Schemas['Employee'] = {
  id: 'emp-1',
  workspace_id: workspace.id,
  display_name: '编辑',
  status: 'active',
  current_revision_id: 'rev-1',
  created_at: now,
  revision: {
    id: 'rev-1', employee_id: 'emp-1', revision_number: 1, responsibility: '撰写内容', system_prompt: '你是一名专业编辑。',
    runtime_profile: 'workspace_read', model: 'deepseek-chat', created_at: now,
    role_template_key: 'custom', work_type: '自定义工作', avatar_key: 'custom', skill_refs: [], tool_refs: [],
  },
  binding: {
    id: 'binding-1', employee_id: 'emp-1', dsh_agent_id: 'employee-emp-1',
    dsh_session_id: 'employee-emp-1', memory_scope_id: 'employee-emp-1', created_at: now,
  },
  grants: [],
}

function projection(status: Schemas['WorkStatus'], executionStatus: Schemas['ExecutionStatus'] = 'running'): Work {
  return {
    id: 'work-1', workspace_id: workspace.id, command_id: 'cmd-1', objective: '撰写发布稿',
    status, graph_revision_id: 'graph-1', graph_revision_number: 1, strategy: 'direct', created_at: now,
    nodes: [{
      id: 'node-1', objective: '撰写发布稿', acceptance_criteria: ['包含标题'],
      assigned_employee_id: employee.id, employee_revision_id: employee.current_revision_id,
      status: status === 'queued' ? 'ready' : status, active_attempt_id: 'attempt-1', failure_code: null, version: 1,
      attempt_count: 1, max_attempts: 1,
    }],
    execution_links: [{
      id: 'link-1', node_id: 'node-1', attempt_id: 'attempt-1', status: executionStatus,
      started_at: now, finished_at: null, diagnostic_code: null,
    }],
    artifacts: [],
  }
}

class FakeCompanyRemote implements CompanyRemoteNamespace {
  readonly requests: CompanyTransportRequest[] = []
  currentWork: Work | undefined
  events: Schemas['CompanyEvent'][] = []
  cancelResponse: Work = projection('running', 'cancel_requested')
  employeeRecords: Schemas['Employee'][] = [employee]
  workspaceRecords: Schemas['Workspace'][] = [workspace]

  async connection(): Promise<RemoteResult<{ readonly status: 'online' }>> {
    return { status: 200, body: { status: 'online' } }
  }

  async request(input: CompanyTransportRequest): Promise<RemoteResult<unknown>> {
    this.requests.push(input)
    if (input.method === 'GET' && input.path === '/workspaces') return { status: 200, body: this.workspaceRecords }
    if (input.method === 'GET' && input.path === '/workspaces/ws-1/employees') return { status: 200, body: this.employeeRecords }
    if (input.method === 'GET' && input.path === '/workspaces/ws-2/employees') return { status: 200, body: [] }
    if (input.method === 'GET' && input.path === '/workspaces/ws-1/works') {
      return { status: 200, body: this.currentWork === undefined ? [] : [this.currentWork] }
    }
    if (input.method === 'GET' && input.path === '/workspaces/ws-2/works') return { status: 200, body: [] }
    if (input.method === 'POST' && input.path === '/workspaces/ws-1/works') {
      this.currentWork = projection('running')
      return { status: 202, body: this.currentWork }
    }
    if (input.method === 'GET' && input.path === '/works/work-1') return { status: 200, body: this.currentWork }
    if (input.method === 'GET' && input.path === '/works/work-1/events') return { status: 200, body: this.events }
    if (input.method === 'POST' && input.path === '/works/work-1/cancel') {
      this.currentWork = this.cancelResponse
      return { status: 202, body: this.cancelResponse }
    }
    throw new Error(`Unexpected fake request: ${input.method} ${input.path}`)
  }
}

class DelayedWorkListRemote extends FakeCompanyRemote {
  private resolveWorkList: ((result: RemoteResult<unknown>) => void) | undefined

  override async request(input: CompanyTransportRequest): Promise<RemoteResult<unknown>> {
    if (input.method === 'GET' && input.path === '/workspaces/ws-1/works') {
      this.requests.push(input)
      return new Promise(resolve => { this.resolveWorkList = resolve })
    }
    return super.request(input)
  }

  respondWithEmptyWorkList(): void {
    if (this.resolveWorkList === undefined) throw new Error('No pending work list request')
    this.resolveWorkList({ status: 200, body: [] })
  }

  respondWithFailedWorkList(): void {
    if (this.resolveWorkList === undefined) throw new Error('No pending work list request')
    this.resolveWorkList({
      status: 503,
      body: { error: { code: 'work_list_failed', message: 'Unavailable', correlation_id: 'corr-list' } },
    })
  }
}

class DelayedCancelRemote extends FakeCompanyRemote {
  private resolveCancel: ((result: RemoteResult<unknown>) => void) | undefined

  override async request(input: CompanyTransportRequest): Promise<RemoteResult<unknown>> {
    if (input.method === 'POST' && input.path === '/works/work-1/cancel') {
      this.requests.push(input)
      return new Promise(resolve => { this.resolveCancel = resolve })
    }
    if (input.method === 'GET' && input.path === '/works/work-2') {
      return { status: 200, body: { ...projection('running'), id: 'work-2', objective: '第二项工作' } }
    }
    if (input.method === 'GET' && input.path === '/works/work-2/events') return { status: 200, body: [] }
    return super.request(input)
  }

  finishCancel(): void {
    if (this.resolveCancel === undefined) throw new Error('No pending cancel request')
    this.resolveCancel({ status: 202, body: projection('running', 'cancel_requested') })
  }
}

class SlowPollingRemote extends FakeCompanyRemote {
  delayProjection = false
  projectionCalls = 0
  eventCalls = 0
  private readonly pending: Array<() => void> = []

  override async request(input: CompanyTransportRequest): Promise<RemoteResult<unknown>> {
    if (input.method === 'GET' && input.path === '/works/work-1') {
      this.projectionCalls += 1
      if (this.delayProjection) {
        return new Promise(resolve => this.pending.push(() => resolve({ status: 200, body: this.currentWork })))
      }
    }
    if (input.method === 'GET' && input.path === '/works/work-1/events') {
      this.eventCalls += 1
      if (this.delayProjection) {
        return new Promise(resolve => this.pending.push(() => resolve({ status: 200, body: this.events })))
      }
    }
    return super.request(input)
  }

  releasePollingResponses(): void {
    for (const resolve of this.pending.splice(0)) resolve()
  }
}

class FlakyInitialSelectionRemote extends FakeCompanyRemote {
  private failuresRemaining = 2

  override async request(input: CompanyTransportRequest): Promise<RemoteResult<unknown>> {
    if (
      this.failuresRemaining > 0
      && input.method === 'GET'
      && (input.path === '/works/work-1' || input.path === '/works/work-1/events')
    ) {
      this.failuresRemaining -= 1
      return {
        status: 503,
        body: { error: { code: 'work_selection_failed', message: 'Unavailable', correlation_id: 'corr-selection' } },
      }
    }
    return super.request(input)
  }
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
})

describe('Direct work client', () => {
  it('does not offer cancellation for a blocked runtime_process_lost execution', () => {
    const blocked = projection('blocked', 'blocked')
    blocked.nodes[0]!.failure_code = 'runtime_process_lost'
    render(<WorkDetail work={blocked} events={[]} pending={false} onCancel={vi.fn()} t={translate('zh')} />)

    expect(screen.getByText('已阻塞')).toBeVisible()
    expect(screen.getByText('runtime_process_lost')).toBeVisible()
    expect(screen.queryByRole('button', { name: '请求取消' })).not.toBeInTheDocument()
  })

  it('renders authoritative graph facts for selected Direct work', () => {
    const direct = projection('blocked')
    direct.nodes[0]!.status = 'waiting_approval'
    direct.nodes[0]!.failure_code = 'policy_wait'
    direct.nodes[0]!.attempt_count = 1
    direct.nodes[0]!.max_attempts = 2

    render(<WorkDetail work={direct} events={[]} pending={false} onCancel={vi.fn()} employees={[employee]} t={translate('en')} />)

    const card = screen.getByRole('article', { name: /撰写发布稿/ })
    expect(card).toHaveTextContent('编辑')
    expect(card).toHaveTextContent('Waiting for approval')
    expect(card).toHaveTextContent('Attempts: 1 / 2')
    expect(card).toHaveTextContent('Approval: waiting')
    expect(card).toHaveTextContent('policy_wait')
  })

  it('offers cancellation only while execution is dispatching or running', () => {
    const view = render(<WorkDetail
      work={projection('running', 'running')}
      events={[]}
      pending={false}
      onCancel={vi.fn()}
      t={translate('zh')}
    />)
    expect(screen.getByRole('button', { name: '请求取消' })).toBeVisible()

    view.rerender(<WorkDetail
      work={projection('running', 'cancel_requested')}
      events={[]}
      pending={false}
      onCancel={vi.fn()}
      t={translate('zh')}
    />)
    expect(screen.getByText('取消请求中')).toBeVisible()
    expect(screen.queryByRole('button', { name: '请求取消' })).not.toBeInTheDocument()

    view.rerender(<WorkDetail
      work={projection('queued', 'dispatch_pending')}
      events={[]}
      pending={false}
      onCancel={vi.fn()}
      t={translate('zh')}
    />)
    expect(screen.getByRole('button', { name: '请求取消' })).toBeVisible()
  })

  it('does not let a stale work list erase a work created while that list was loading', async () => {
    const remote = new DelayedWorkListRemote()
    const controller = new CompanyController(new ProductApi(remote))
    await controller.selectWorkspace('ws-1')

    const loading = controller.loadWorks()
    await controller.createDirectWork({
      employee_id: 'emp-1', objective: '撰写发布稿', acceptance_criteria: ['包含标题'], command_id: 'cmd-1',
    })
    remote.respondWithEmptyWorkList()
    await loading

    expect(controller.snapshot().works).toMatchObject([{ id: 'work-1' }])
  })

  it('does not let a stale work list failure overwrite a successful work creation', async () => {
    const remote = new DelayedWorkListRemote()
    const controller = new CompanyController(new ProductApi(remote))
    await controller.selectWorkspace('ws-1')

    const loading = controller.loadWorks()
    await controller.createDirectWork({
      employee_id: 'emp-1', objective: '撰写发布稿', acceptance_criteria: ['包含标题'], command_id: 'cmd-1',
    })
    remote.respondWithFailedWorkList()
    await loading

    expect(controller.snapshot()).toMatchObject({ phase: 'ready', error: undefined, works: [{ id: 'work-1' }] })
  })

  it('clears the previous work mutation state when selection moves during cancellation', async () => {
    const remote = new DelayedCancelRemote()
    const controller = new CompanyController(new ProductApi(remote))
    await controller.selectWorkspace('ws-1')
    await controller.createDirectWork({
      employee_id: 'emp-1', objective: '撰写发布稿', acceptance_criteria: ['包含标题'], command_id: 'cmd-1',
    })

    const cancelling = controller.cancelSelectedWork()
    await controller.selectWork('work-2')
    expect(controller.snapshot()).toMatchObject({ selectedWorkId: 'work-2', pending: false })
    remote.finishCancel()
    await cancelling
    expect(controller.snapshot()).toMatchObject({ selectedWorkId: 'work-2', pending: false })
  })

  it('submits direct work, renders authoritative progress, and distinguishes requested from confirmed cancellation', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    render(<CompanySurface remote={remote} initialWorkspaceId="ws-1" pollingIntervalMs={20} />)

    await user.click(await screen.findByRole('link', { name: '工作' }))
    await user.click(screen.getByRole('button', { name: '创建工作' }))
    await user.type(screen.getByLabelText('工作目标'), '  撰写发布稿  ')
    await user.type(screen.getByLabelText('验收标准'), ' 包含标题 \n\n  不超过 800 字 ')
    await user.selectOptions(screen.getByLabelText('负责员工'), employee.id)
    await user.click(screen.getByRole('button', { name: '开始工作' }))

    expect(await screen.findByText('运行中')).toBeVisible()
    expect(remote.requests.find(request => request.method === 'POST' && request.path === '/workspaces/ws-1/works')).toMatchObject({
      method: 'POST',
      path: '/workspaces/ws-1/works',
      body: { employee_id: 'emp-1', objective: '撰写发布稿', acceptance_criteria: ['包含标题', '不超过 800 字'] },
    })
    await user.click(screen.getByRole('button', { name: '请求取消' }))
    expect(await screen.findByText('取消请求中')).toBeVisible()
    expect(screen.queryByText('已取消')).not.toBeInTheDocument()

    remote.currentWork = projection('cancelled', 'cancelled')
    expect(await screen.findByText('已取消', {}, { timeout: 1_000 })).toBeVisible()
  })

  it('requires an active employee, objective, and one nonblank criterion before sending', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    remote.employeeRecords = [{ ...employee, status: 'paused' }]
    render(<CompanySurface remote={remote} initialWorkspaceId="ws-1" />)

    await user.click(await screen.findByRole('link', { name: '工作' }))
    await user.click(screen.getByRole('button', { name: '创建工作' }))
    await user.click(screen.getByRole('button', { name: '开始工作' }))
    expect(screen.getByText('请输入工作目标')).toHaveAttribute('role', 'alert')

    fireEvent.change(screen.getByLabelText('工作目标'), { target: { value: '撰写发布稿' } })
    fireEvent.change(screen.getByLabelText('验收标准'), { target: { value: '  \n  ' } })
    await user.click(screen.getByRole('button', { name: '开始工作' }))
    expect(screen.getByText('请至少输入一条验收标准')).toHaveAttribute('role', 'alert')

    fireEvent.change(screen.getByLabelText('验收标准'), { target: { value: '包含标题' } })
    await user.click(screen.getByRole('button', { name: '开始工作' }))
    expect(screen.getByText('请选择一名在职员工')).toHaveAttribute('role', 'alert')
    expect(remote.requests.filter(request => request.method === 'POST' && /\/works$/u.test(request.path))).toEqual([])
  })

  it('keeps a running projection nonterminal across polling and cleans its timer on unmount', async () => {
    const remote = new FakeCompanyRemote()
    remote.currentWork = projection('running')
    const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout')
    const rendered = render(<CompanySurface remote={remote} initialWorkspaceId="ws-1" pollingIntervalMs={10} />)

    await userEvent.click(await screen.findByRole('link', { name: '工作' }))
    await userEvent.click(await screen.findByRole('link', { name: '撰写发布稿' }))
    await new Promise(resolve => setTimeout(resolve, 35))
    expect(screen.getByText('运行中')).toBeVisible()
    expect(remote.requests.filter(request => request.path === '/works/work-1').length).toBeGreaterThan(1)

    rendered.unmount()
    expect(clearTimeoutSpy).toHaveBeenCalled()
    clearTimeoutSpy.mockRestore()
  })

  it('serializes slow polling and eventually publishes the authoritative projection', async () => {
    const remote = new SlowPollingRemote()
    remote.currentWork = projection('running')
    const rendered = render(<CompanySurface remote={remote} initialWorkspaceId="ws-1" pollingIntervalMs={60_000} />)
    await userEvent.click(await screen.findByRole('link', { name: '工作' }))
    await userEvent.click(await screen.findByRole('link', { name: '撰写发布稿' }))
    expect(await screen.findByText('运行中')).toBeVisible()
    expect(remote.projectionCalls).toBe(1)
    expect(remote.eventCalls).toBe(1)

    remote.delayProjection = true
    remote.currentWork = projection('completed', 'completed')
    vi.useFakeTimers()
    rendered.rerender(<CompanySurface remote={remote} initialWorkspaceId="ws-1" pollingIntervalMs={10} />)

    await act(async () => { await vi.advanceTimersByTimeAsync(100) })
    expect(remote.projectionCalls).toBe(2)
    expect(remote.eventCalls).toBe(2)

    await act(async () => { remote.releasePollingResponses(); await Promise.resolve() })
    expect(screen.getByText('已完成')).toBeVisible()
    expect(vi.getTimerCount()).toBe(0)
    rendered.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not start polling before a delayed initial work selection publishes', async () => {
    const remote = new SlowPollingRemote()
    remote.currentWork = projection('running')
    const rendered = render(<CompanySurface remote={remote} initialWorkspaceId="ws-1" pollingIntervalMs={10} />)
    await userEvent.click(await screen.findByRole('link', { name: '工作' }))
    const workLink = await screen.findByRole('link', { name: '撰写发布稿' })

    remote.delayProjection = true
    vi.useFakeTimers()
    fireEvent.click(workLink)
    await act(async () => { await vi.advanceTimersByTimeAsync(100) })

    expect(remote.projectionCalls).toBe(1)
    expect(remote.eventCalls).toBe(1)
    remote.currentWork = projection('completed', 'completed')
    await act(async () => { remote.releasePollingResponses(); await Promise.resolve() })
    expect(screen.getByText('已完成')).toBeVisible()
    expect(vi.getTimerCount()).toBe(0)
    rendered.unmount()
  })

  it('allows an initial work selection error to be retried explicitly', async () => {
    const remote = new FlakyInitialSelectionRemote()
    remote.currentWork = projection('running')
    render(<CompanySurface remote={remote} initialWorkspaceId="ws-1" />)
    await userEvent.click(await screen.findByRole('link', { name: '工作' }))
    const workLink = await screen.findByRole('link', { name: '撰写发布稿' })

    await userEvent.click(workLink)
    expect(await screen.findByRole('alert')).toHaveTextContent('work_selection_failed')
    await userEvent.click(workLink)

    expect(await screen.findByText('运行中')).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('stops a slow polling loop when workspace selection changes', async () => {
    const remote = new SlowPollingRemote()
    remote.workspaceRecords = [workspace, { id: 'ws-2', name: '第二公司', created_at: now }]
    remote.currentWork = projection('running')
    const rendered = render(<CompanySurface remote={remote} initialWorkspaceId="ws-1" pollingIntervalMs={60_000} />)
    await userEvent.click(await screen.findByRole('link', { name: '工作' }))
    await userEvent.click(await screen.findByRole('link', { name: '撰写发布稿' }))
    expect(await screen.findByText('运行中')).toBeVisible()

    remote.delayProjection = true
    vi.useFakeTimers()
    rendered.rerender(<CompanySurface remote={remote} initialWorkspaceId="ws-1" pollingIntervalMs={10} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(10) })
    fireEvent.click(screen.getByRole('link', { name: '第二公司' }))
    await act(async () => { remote.releasePollingResponses(); await Promise.resolve() })
    await act(async () => { await vi.advanceTimersByTimeAsync(100) })

    expect(remote.projectionCalls).toBe(2)
    expect(remote.eventCalls).toBe(2)
    expect(vi.getTimerCount()).toBe(0)
    rendered.unmount()
  })

  it('renders safe company history in a polite live region and copies an unsupported artifact URI', async () => {
    const user = userEvent.setup()
    const remote = new FakeCompanyRemote()
    remote.currentWork = {
      ...projection('completed', 'completed'),
      artifacts: [{ id: 'artifact-1', kind: 'dsh_session_result', uri: 'dsh-session://employee-1/result', created_at: now }],
    }
    remote.events = [{
      id: 'event-1', workspace_id: 'ws-1', work_id: 'work-1', node_id: 'node-1', attempt_id: 'attempt-1',
      source_sequence: 1, event_type: 'work.completed', summary: '工作已完成', source: 'company', observed_at: now,
    }]
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    render(<CompanySurface remote={remote} initialWorkspaceId="ws-1" />)

    await user.click(await screen.findByRole('link', { name: '工作' }))
    await user.click(await screen.findByRole('link', { name: '撰写发布稿' }))
    const history = await screen.findByRole('log', { name: '公司事件' })
    expect(history).toHaveAttribute('aria-live', 'polite')
    expect(history).toHaveTextContent('工作已完成')
    expect(screen.queryByRole('link', { name: '打开结果' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '复制结果引用' }))
    expect(writeText).toHaveBeenCalledWith('dsh-session://employee-1/result')
    expect(await screen.findByRole('status')).toHaveTextContent('结果引用已复制')
  })

  it('reports clipboard rejection accessibly while preserving the selectable reference', async () => {
    const user = userEvent.setup()
    const work = {
      ...projection('completed', 'completed'),
      artifacts: [{ id: 'artifact-1', kind: 'dsh_session_result' as const, uri: 'dsh-session://employee-1/result', created_at: now }],
    }
    const writeText = vi.fn(async () => { throw new Error('clipboard denied') })
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    render(<WorkDetail work={work} events={[]} pending={false} onCancel={vi.fn()} t={translate('zh')} />)

    expect(screen.getByLabelText('结果引用')).toHaveValue('dsh-session://employee-1/result')
    await user.click(screen.getByRole('button', { name: '复制结果引用' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('无法复制结果引用')
  })

})

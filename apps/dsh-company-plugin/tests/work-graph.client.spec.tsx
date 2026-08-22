// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CompanySurface } from '../src/client/CompanySurface.js'
import { StrategyComposer, type StrategyDraft, validateStrategyDraft } from '../src/client/StrategyComposer.js'
import { WorkDetail } from '../src/client/WorkDetail.js'
import { WorkGraphView } from '../src/client/WorkGraphView.js'
import type { Employee, StrategyWorkCreate, WorkProjection } from '../src/client/api.js'
import { translate } from '../src/client/locales.js'
import type { CompanyRemoteNamespace, CompanyTransportRequest, RemoteResult } from '../src/remote-contract.js'

const now = '2026-08-21T00:00:00Z'
const t = translate('en')

const employee = (index: number): Employee => ({
  id: `emp-${index}`,
  workspace_id: 'ws-1',
  display_name: `Employee ${index}`,
  status: 'active',
  current_revision_id: `rev-${index}`,
  created_at: now,
  revision: {
    id: `rev-${index}`,
    employee_id: `emp-${index}`,
    revision_number: 1,
    responsibility: 'Collaborate',
    system_prompt: 'Act as a professional collaborator.',
    runtime_profile: 'workspace_read',
    model: 'deepseek-chat',
    created_at: now,
    role_template_key: 'custom',
    work_type: '自定义工作',
    avatar_key: 'custom',
    skill_refs: [],
    tool_refs: [],
  },
  binding: {
    id: `binding-${index}`,
    employee_id: `emp-${index}`,
    dsh_agent_id: `session-${index}`,
    dsh_session_id: `session-${index}`,
    memory_scope_id: `session-${index}`,
    created_at: now,
  },
  grants: [],
})

afterEach(cleanup)

describe('multi-employee work graph experience', () => {
  it('enforces every generated strategy bound and graph invariant locally', () => {
    const activeIds = new Set(['emp-1', 'emp-2', 'emp-3', 'emp-4'])
    const base: StrategyDraft = {
      strategy: 'direct', objective: 'Objective', criteria: ['Criterion'], directEmployee: 'emp-1',
      participants: [], summarizer: '', coordinator: '', starRows: [], graphRows: [], edgeRows: [],
    }

    expect(validateStrategyDraft({ ...base, objective: 'x'.repeat(4001) }, activeIds)).toHaveProperty('objective', 'workObjectiveTooLong')
    expect(validateStrategyDraft({ ...base, criteria: Array.from({ length: 51 }, () => 'ok') }, activeIds)).toHaveProperty('criteria', 'criteriaTooMany')
    expect(validateStrategyDraft({ ...base, criteria: ['x'.repeat(501)] }, activeIds)).toHaveProperty('criteria', 'criterionTooLong')
    expect(validateStrategyDraft({ ...base, strategy: 'star', coordinator: 'emp-1', starRows: Array.from({ length: 17 }, () => ({ employeeId: 'emp-2', objective: 'Child' })) }, activeIds)).toHaveProperty('star', 'starChildrenTooMany')
    expect(validateStrategyDraft({ ...base, strategy: 'star', coordinator: 'emp-1', starRows: [{ employeeId: 'emp-2', objective: 'x'.repeat(4001) }] }, activeIds)).toHaveProperty('star.objective.0', 'childObjectiveTooLong')

    const graphRows = [
      { key: 'a', employeeId: 'emp-1', objective: 'A' },
      { key: 'b', employeeId: 'emp-2', objective: 'B' },
    ]
    expect(validateStrategyDraft({ ...base, strategy: 'graph', graphRows: Array.from({ length: 33 }, (_, index) => ({ key: `n-${index}`, employeeId: 'emp-1', objective: 'N' })) }, activeIds)).toHaveProperty('graph', 'graphNodesTooMany')
    expect(validateStrategyDraft({ ...base, strategy: 'graph', graphRows: [{ key: 'x'.repeat(121), employeeId: 'missing', objective: 'x'.repeat(4001) }] }, activeIds)).toMatchObject({
      'graph.key.0': 'nodeKeyTooLong', 'graph.employee.0': 'activeEmployeeRequired', 'graph.objective.0': 'nodeObjectiveTooLong',
    })
    expect(validateStrategyDraft({ ...base, strategy: 'graph', graphRows: [graphRows[0]!, { ...graphRows[1]!, key: 'a' }] }, activeIds)).toHaveProperty('graph.key.1', 'nodeKeyDuplicate')
    expect(validateStrategyDraft({ ...base, strategy: 'graph', graphRows, edgeRows: Array.from({ length: 129 }, () => ({ fromKey: 'a', toKey: 'b', kind: 'depends_on' })) }, activeIds)).toHaveProperty('edges', 'graphEdgesTooMany')
    expect(validateStrategyDraft({ ...base, strategy: 'graph', graphRows, edgeRows: [{ fromKey: 'a', toKey: 'missing', kind: 'depends_on' }] }, activeIds)).toHaveProperty('edge.0', 'edgeEndpointUnknown')
    expect(validateStrategyDraft({ ...base, strategy: 'graph', graphRows, edgeRows: [{ fromKey: 'a', toKey: 'a', kind: 'depends_on' }] }, activeIds)).toHaveProperty('edge.0', 'edgeSelfReference')
    expect(validateStrategyDraft({ ...base, strategy: 'graph', graphRows, edgeRows: [{ fromKey: 'a', toKey: 'b', kind: 'depends_on' }, { fromKey: 'a', toKey: 'b', kind: 'depends_on' }] }, activeIds)).toHaveProperty('edge.1', 'edgeDuplicate')
    expect(validateStrategyDraft({ ...base, strategy: 'graph', graphRows, edgeRows: [{ fromKey: 'a', toKey: 'b', kind: 'depends_on' }, { fromKey: 'b', toKey: 'a', kind: 'reviews' }] }, activeIds)).toHaveProperty('edges', 'graphCycle')

    expect(validateStrategyDraft({ ...base, strategy: 'battle', participants: ['emp-1'], summarizer: 'emp-2' }, activeIds)).toHaveProperty('participants', 'battleParticipantCount')
    expect(validateStrategyDraft({ ...base, strategy: 'battle', participants: ['emp-1', 'emp-1'], summarizer: 'emp-2' }, activeIds)).toHaveProperty('participants', 'battleParticipantsDistinct')
    expect(validateStrategyDraft({ ...base, strategy: 'battle', participants: ['emp-1', 'emp-2'], summarizer: 'emp-2' }, activeIds)).toHaveProperty('summarizer', 'battleSummarizerDistinct')
  })

  it('associates local validation errors with fields and never sends invalid input', async () => {
    const onStart = vi.fn<(input: StrategyWorkCreate) => Promise<void>>().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<StrategyComposer employees={[employee(1), employee(2)]} pending={false} onCancel={() => undefined} onStart={onStart} t={t} />)

    fireEvent.change(screen.getByLabelText('Work objective'), { target: { value: 'x'.repeat(4001) } })
    await user.type(screen.getByLabelText('Acceptance criteria'), 'Criterion')
    await user.selectOptions(screen.getByLabelText('Responsible employee'), 'emp-1')
    await user.click(screen.getByRole('button', { name: 'Start work' }))

    expect(screen.getByText('Work objective must be at most 4000 characters')).toHaveAttribute('role', 'alert')
    expect(screen.getByLabelText('Work objective')).toHaveAttribute('aria-invalid', 'true')
    expect(onStart).not.toHaveBeenCalled()
  })

  it('submits an explicit Battle with three participants and a distinct summarizer', async () => {
    const employees = [1, 2, 3, 4].map(employee)
    const onStart = vi.fn<(input: StrategyWorkCreate) => Promise<void>>().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<StrategyComposer employees={employees} pending={false} onCancel={() => undefined} onStart={onStart} t={t} />)

    await user.selectOptions(screen.getByLabelText('Strategy'), 'battle')
    await user.type(screen.getByLabelText('Work objective'), 'Propose a launch campaign')
    await user.type(screen.getByLabelText('Acceptance criteria'), 'Cites evidence')
    await user.click(screen.getByRole('button', { name: 'Start work' }))
    expect(screen.getByText('Select 2–4 participants')).toHaveAttribute('role', 'alert')
    for (const name of ['Employee 1', 'Employee 2', 'Employee 3']) {
      await user.click(screen.getByRole('checkbox', { name }))
    }
    await user.selectOptions(screen.getByLabelText('Summarizer'), 'emp-4')
    await user.click(screen.getByRole('button', { name: 'Start work' }))

    expect(onStart).toHaveBeenCalledOnce()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(onStart.mock.calls[0]?.[0]).toMatchObject({
      kind: 'battle',
      participant_employee_ids: ['emp-1', 'emp-2', 'emp-3'],
      summarizer_employee_id: 'emp-4',
    })
  })

  it('creates a Battle through the company surface and renders the authoritative four-node projection', async () => {
    const employees = [1, 2, 3, 4].map(employee)
    const requests: CompanyTransportRequest[] = []
    const projection: WorkProjection = {
      id: 'work-battle', workspace_id: 'ws-1', command_id: 'cmd-battle', objective: 'Compare launch proposals',
      status: 'completed', graph_revision_id: 'graph-battle', graph_revision_number: 1, strategy: 'battle', created_at: now,
      nodes: [
        ...[1, 2, 3].map(index => ({
          id: `node-${index}`, objective: `Proposal ${index}`, acceptance_criteria: ['Evidence'],
          assigned_employee_id: `emp-${index}`, employee_revision_id: `rev-${index}`,
          status: 'completed' as const, active_attempt_id: null, failure_code: null, version: 1,
          attempt_count: 1, max_attempts: 1,
        })),
        {
          id: 'node-summary', objective: 'Summary', acceptance_criteria: ['Synthesize'],
          assigned_employee_id: 'emp-4', employee_revision_id: 'rev-4', status: 'completed',
          active_attempt_id: null, failure_code: null, version: 1, attempt_count: 1, max_attempts: 1,
        },
      ],
      edges: [1, 2, 3].map(index => ({
        from_node_id: `node-${index}`, to_node_id: 'node-summary', kind: 'summarizes' as const,
      })),
      execution_links: [], artifacts: [],
    }
    const remote: CompanyRemoteNamespace = {
      async connection(): Promise<RemoteResult<{ readonly status: 'online' }>> {
        return { status: 200, body: { status: 'online' } }
      },
      async request(input): Promise<RemoteResult<unknown>> {
        requests.push(input)
        if (input.method === 'GET' && input.path === '/workspaces') {
          return { status: 200, body: [{ id: 'ws-1', name: 'Workspace', created_at: now }] }
        }
        if (input.method === 'GET' && input.path === '/workspaces/ws-1/employees') return { status: 200, body: employees }
        if (input.method === 'GET' && input.path === '/workspaces/ws-1/works') return { status: 200, body: [] }
        if (input.method === 'POST' && input.path === '/workspaces/ws-1/works') return { status: 202, body: projection }
        if (input.method === 'GET' && input.path === '/works/work-battle/events') return { status: 200, body: [] }
        throw new Error(`Unexpected fake request: ${input.method} ${input.path}`)
      },
    }
    const user = userEvent.setup()
    render(<CompanySurface remote={remote} initialWorkspaceId="ws-1" pollingIntervalMs={60_000} locale="en" />)

    await user.click(await screen.findByRole('link', { name: 'Work' }))
    await user.click(await screen.findByRole('button', { name: 'Create work' }))
    await user.selectOptions(screen.getByLabelText('Strategy'), 'battle')
    await user.type(screen.getByLabelText('Work objective'), 'Compare launch proposals')
    await user.type(screen.getByLabelText('Acceptance criteria'), 'Synthesize evidence')
    for (const name of ['Employee 1', 'Employee 2', 'Employee 3']) {
      await user.click(screen.getByRole('checkbox', { name }))
    }
    await user.selectOptions(screen.getByLabelText('Summarizer'), 'emp-4')
    await user.click(screen.getByRole('button', { name: 'Start work' }))

    const post = requests.find(request => request.method === 'POST' && request.path === '/workspaces/ws-1/works')
    expect(post?.body).toMatchObject({
      kind: 'battle', participant_employee_ids: ['emp-1', 'emp-2', 'emp-3'], summarizer_employee_id: 'emp-4',
    })
    const graph = await screen.findByRole('region', { name: 'Work graph' })
    expect(within(graph).getAllByRole('article')).toHaveLength(4)
    expect(within(graph).getByRole('article', { name: /Proposal 1/ })).toHaveTextContent('Employee 1')
    expect(within(graph).getByRole('article', { name: /Proposal 2/ })).toHaveTextContent('Employee 2')
    expect(within(graph).getByRole('article', { name: /Proposal 3/ })).toHaveTextContent('Employee 3')
    expect(within(graph).getByRole('article', { name: /Summary/ })).toHaveTextContent('Employee 4')
    expect(within(graph).getAllByText(/Proposal [123] summarizes Summary/)).toHaveLength(3)
  })

  it('renders server graph facts with textual status, attempts, approval, failure, and edges', () => {
    const work = {
      id: 'work-1',
      workspace_id: 'ws-1',
      command_id: 'cmd-1',
      objective: 'Propose a launch campaign',
      status: 'blocked',
      graph_revision_id: 'graph-1',
      graph_revision_number: 1,
      strategy: 'battle',
      created_at: now,
      nodes: [
        {
          id: 'node-a', objective: 'Proposal A', acceptance_criteria: ['Evidence'], assigned_employee_id: 'emp-1',
          employee_revision_id: 'rev-1', status: 'completed', active_attempt_id: 'attempt-a', failure_code: null,
          version: 2, attempt_count: 1, max_attempts: 2,
        },
        {
          id: 'node-summary', objective: 'Summary', acceptance_criteria: ['Differences'], assigned_employee_id: 'emp-4',
          employee_revision_id: 'rev-4', status: 'waiting_approval', active_attempt_id: null,
          failure_code: 'dependency_failed', version: 3, attempt_count: 1, max_attempts: 2,
        },
      ],
      edges: [{ from_node_id: 'node-a', to_node_id: 'node-summary', kind: 'summarizes' }],
      execution_links: [],
      artifacts: [],
    } satisfies WorkProjection

    render(<WorkGraphView work={work} employees={[employee(1), employee(4)]} t={t} />)

    expect(screen.getByRole('article', { name: /Proposal A/ })).toHaveTextContent('Completed')
    expect(screen.getByRole('article', { name: /Summary/ })).toHaveTextContent('Waiting for approval')
    expect(screen.getByRole('article', { name: /Summary/ })).toHaveTextContent('dependency_failed')
    expect(screen.getByRole('article', { name: /Summary/ })).toHaveTextContent('Attempts: 1 / 2')
    expect(screen.getByText('Proposal A summarizes Summary')).toBeVisible()
  })

  it('does not offer Direct-only cancellation for a running graph work', () => {
    const work = {
      id: 'work-graph-cancel', workspace_id: 'ws-1', command_id: 'cmd', objective: 'Graph work',
      status: 'running', graph_revision_id: 'graph-1', graph_revision_number: 1, strategy: 'graph', created_at: now,
      nodes: [{
        id: 'node-1', objective: 'Node', acceptance_criteria: ['Done'], assigned_employee_id: 'emp-1',
        employee_revision_id: 'rev-1', status: 'running', active_attempt_id: 'attempt-1', failure_code: null,
        version: 2, attempt_count: 1, max_attempts: 1,
      }],
      edges: [],
      execution_links: [{
        id: 'link-1', node_id: 'node-1', attempt_id: 'attempt-1', status: 'running',
        started_at: now, finished_at: null, diagnostic_code: null,
      }],
      artifacts: [],
    } satisfies WorkProjection

    render(<WorkDetail work={work} events={[]} pending={false} onCancel={() => undefined} t={t} />)

    expect(screen.queryByRole('button', { name: 'Request cancellation' })).not.toBeInTheDocument()
  })
})

// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApprovalInbox } from '../src/client/ApprovalInbox.js'
import { CapabilityEditor } from '../src/client/CapabilityEditor.js'
import { DelegationView } from '../src/client/DelegationView.js'
import { translate } from '../src/client/locales.js'
import { ApiError, ProductApi, type WorkspaceGrant, type WorkProjection } from '../src/client/api.js'

const t = translate('en')
const now = '2026-08-21T00:00:00Z'
const work: WorkProjection = {
  id: 'work-1', workspace_id: 'ws-1', command_id: 'cmd-1', objective: 'Publish notes', status: 'blocked',
  graph_revision_id: 'graph-1', graph_revision_number: 1, strategy: 'direct', created_at: now,
  nodes: [{ id: 'node-1', objective: 'Publish notes', acceptance_criteria: ['Published'], assigned_employee_id: 'emp-a', employee_revision_id: 'rev-a', status: 'waiting_approval', active_attempt_id: null, failure_code: null, version: 2 }],
  execution_links: [{ id: 'link-1', node_id: 'node-1', attempt_id: 'attempt-1', status: 'dispatch_pending', started_at: null, finished_at: null, diagnostic_code: null }],
  artifacts: [],
}
const runningWork: WorkProjection = {
  ...work,
  status: 'running',
  nodes: [{ ...work.nodes[0]!, status: 'running', active_attempt_id: 'attempt-1' }],
  execution_links: [{ ...work.execution_links[0]!, status: 'running', started_at: now }],
}

function capabilityApi(
  grants: WorkspaceGrant[],
  replaceWorkspaceCapabilities = vi.fn(),
): ProductApi {
  return {
    getWorkspaceCapabilities: vi.fn().mockResolvedValue({ workspace_id: 'ws-1', grants }),
    replaceWorkspaceCapabilities,
  } as unknown as ProductApi
}

afterEach(cleanup)

describe('company governance client', () => {
  it('carries governance requests through the typed company remote', async () => {
    const request = vi.fn().mockResolvedValue({
      status: 200,
      body: {
        workspace_id: 'ws-1',
        grants: [{ action: 'workspace.write', level: 2, resource_kind: 'repository', resource_values: ['repo-a'], requires_approval: true }],
      },
    })
    const api = new ProductApi({ request })

    await expect(api.replaceWorkspaceCapabilities('ws-1', {
      grants: [{ action: 'workspace.write', level: 2, resource_kind: 'repository', resource_values: ['repo-a'], requires_approval: true }],
    })).resolves.toMatchObject({ workspace_id: 'ws-1' })
    expect(request).toHaveBeenCalledWith(expect.objectContaining({
      method: 'PUT', path: '/workspaces/ws-1/capabilities',
    }))
    await expect(api.getWorkspaceCapabilities('ws-1')).resolves.toMatchObject({ workspace_id: 'ws-1' })
    expect(request).toHaveBeenCalledWith(expect.objectContaining({
      method: 'GET', path: '/workspaces/ws-1/capabilities',
    }))
  })

  it('moves a waiting node only after an explicit approval returns authoritative work', async () => {
    let resolveDecision!: (value: Awaited<ReturnType<ProductApi['approveApproval']>>) => void
    const approveApproval = vi.fn(() => new Promise<Awaited<ReturnType<ProductApi['approveApproval']>>>(resolve => { resolveDecision = resolve }))
    const onWorkUpdated = vi.fn()
    const api = {
      listApprovals: vi.fn().mockResolvedValue([{
        id: 'approval-1', workspace_id: 'ws-1', work_id: 'work-1', node_id: 'node-1',
        action: 'external.publish', resources: ['channel-a'], reason: 'Release approved notes', status: 'pending',
        requested_at: now, decided_at: null, decided_by: null,
        requesting_employee: { id: 'emp-a', display_name: 'Publisher' },
      }]),
      approveApproval,
      rejectApproval: vi.fn(),
    } as unknown as ProductApi
    render(<ApprovalInbox api={api} workspaceId="ws-1" onWorkUpdated={onWorkUpdated} t={t} />)

    expect(await screen.findByText('external.publish')).toBeVisible()
    expect(screen.getByText('channel-a')).toBeVisible()
    expect(screen.getByText('Release approved notes')).toBeVisible()
    expect(screen.getByText('Publisher')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(onWorkUpdated).not.toHaveBeenCalled()
    resolveDecision({
      approval: { ...(await api.listApprovals('ws-1'))[0]!, status: 'approved', decided_at: now, decided_by: 'operator' },
      work: { ...work, nodes: [{ ...work.nodes[0]!, status: 'ready' }] },
    })
    await waitFor(() => expect(onWorkUpdated).toHaveBeenCalledWith(expect.objectContaining({ nodes: [expect.objectContaining({ status: 'ready' })] })))
    expect(screen.queryByText('external.publish')).not.toBeInTheDocument()
  })

  it('rejects explicitly and never calls the approval dispatch path', async () => {
    const rejectApproval = vi.fn().mockResolvedValue({
      approval: {
        id: 'approval-1', workspace_id: 'ws-1', work_id: 'work-1', node_id: 'node-1', action: 'workspace.write',
        resources: ['repo-a'], reason: 'Unsafe change', status: 'rejected', requested_at: now, decided_at: now,
        decided_by: 'operator', requesting_employee: { id: 'emp-a', display_name: 'Publisher' },
      },
      work: { ...work, status: 'failed', nodes: [{ ...work.nodes[0]!, status: 'failed', failure_code: 'approval_rejected' }] },
    })
    const approveApproval = vi.fn()
    const api = {
      listApprovals: vi.fn().mockResolvedValue([{ ...rejectApproval.mock.results, id: 'approval-1', workspace_id: 'ws-1', work_id: 'work-1', node_id: 'node-1', action: 'workspace.write', resources: ['repo-a'], reason: 'Unsafe change', status: 'pending', requested_at: now, decided_at: null, decided_by: null, requesting_employee: { id: 'emp-a', display_name: 'Publisher' } }]),
      approveApproval, rejectApproval,
    } as unknown as ProductApi
    render(<ApprovalInbox api={api} workspaceId="ws-1" onWorkUpdated={() => undefined} t={t} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Reject' }))
    expect(rejectApproval).toHaveBeenCalledWith('approval-1', 'operator')
    expect(approveApproval).not.toHaveBeenCalled()
  })

  it('reloads approvals when the authoritative work enters waiting approval', async () => {
    const approval = {
      id: 'approval-late', workspace_id: 'ws-1', work_id: 'work-1', node_id: 'node-1', action: 'workspace.write',
      resources: ['repo-a'], reason: 'Late request', status: 'pending' as const, requested_at: now,
      decided_at: null, decided_by: null, requesting_employee: { id: 'emp-a', display_name: 'Publisher' },
    }
    const listApprovals = vi.fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([approval])
    const api = { listApprovals, approveApproval: vi.fn(), rejectApproval: vi.fn() } as unknown as ProductApi
    const view = render(<ApprovalInbox
      api={api} workspaceId="ws-1" refreshKey="node-1:ready:1" onWorkUpdated={() => undefined} t={t}
    />)
    expect(await screen.findByText('No pending approvals')).toBeVisible()

    view.rerender(<ApprovalInbox
      api={api} workspaceId="ws-1" refreshKey="node-1:waiting_approval:2" onWorkUpdated={() => undefined} t={t}
    />)

    expect(await screen.findByText('Late request')).toBeVisible()
    expect(listApprovals).toHaveBeenCalledTimes(2)
  })

  it('uses only server-returned eligible employees and reports delegation state', async () => {
    const createDelegation = vi.fn().mockResolvedValue({
      delegation: { id: 'delegation-1', workspace_id: 'ws-1', work_id: 'work-1', source_node_id: 'node-1', target_node_id: 'node-2', proposer_employee_id: 'emp-a', target_employee_id: 'emp-b', graph_revision_id: 'graph-2', status: 'accepted', created_at: now },
      work: { ...work, graph_revision_id: 'graph-2', graph_revision_number: 2 },
    })
    const api = {
      listDelegations: vi.fn().mockResolvedValue({ delegations: [], eligible_employees: [{ id: 'emp-b', display_name: 'Reviewer' }] }),
      createDelegation,
    } as unknown as ProductApi
    render(<DelegationView api={api} work={runningWork} onWorkUpdated={() => undefined} t={t} />)

    const target = await screen.findByRole('combobox', { name: 'Delegate to' })
    expect(target).toHaveTextContent('Reviewer')
    expect(target).not.toHaveTextContent('Archived employee')
    await userEvent.selectOptions(target, 'emp-b')
    await userEvent.type(screen.getByLabelText('Delegated objective'), 'Review facts')
    await userEvent.type(screen.getByLabelText('Delegated acceptance criteria'), 'Cite sources')
    await userEvent.type(screen.getByLabelText('Required actions'), 'workspace.read')
    await userEvent.type(screen.getByLabelText('Resource scope'), 'repo-a')
    await userEvent.click(screen.getByRole('button', { name: 'Delegate' }))
    expect(createDelegation).toHaveBeenCalledWith('work-1', expect.objectContaining({ target_employee_id: 'emp-b' }))
    expect(await screen.findByText('Accepted')).toBeVisible()
  })

  it('derives delegation source and proposer from the current running child node', async () => {
    const childRunning: WorkProjection = {
      ...runningWork,
      nodes: [
        { ...runningWork.nodes[0]!, id: 'node-parent', assigned_employee_id: 'emp-a', status: 'blocked', failure_code: 'waiting_delegation' },
        { ...runningWork.nodes[0]!, id: 'node-child', assigned_employee_id: 'emp-b', employee_revision_id: 'rev-b', active_attempt_id: 'attempt-child' },
      ],
      execution_links: [
        { ...runningWork.execution_links[0]!, id: 'link-parent', node_id: 'node-parent', status: 'blocked', diagnostic_code: 'waiting_delegation' },
        { ...runningWork.execution_links[0]!, id: 'link-child', node_id: 'node-child', attempt_id: 'attempt-child' },
      ],
    }
    const createDelegation = vi.fn().mockResolvedValue({
      delegation: { id: 'delegation-2', workspace_id: 'ws-1', work_id: 'work-1', source_node_id: 'node-child', target_node_id: 'node-next', proposer_employee_id: 'emp-b', target_employee_id: 'emp-c', graph_revision_id: 'graph-3', status: 'accepted', created_at: now },
      work: childRunning,
    })
    const api = {
      listDelegations: vi.fn().mockResolvedValue({ delegations: [], eligible_employees: [{ id: 'emp-c', display_name: 'Fact checker' }] }),
      createDelegation,
    } as unknown as ProductApi
    render(<DelegationView api={api} work={childRunning} onWorkUpdated={() => undefined} t={t} />)
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Delegate to' }), 'emp-c')
    fireEvent.change(screen.getByLabelText('Delegated objective'), { target: { value: 'Check facts' } })
    fireEvent.change(screen.getByLabelText('Delegated acceptance criteria'), { target: { value: 'Cite source' } })
    fireEvent.change(screen.getByLabelText('Required actions'), { target: { value: 'workspace.read' } })
    fireEvent.change(screen.getByLabelText('Resource scope'), { target: { value: 'repo-a' } })
    await userEvent.click(screen.getByRole('button', { name: 'Delegate' }))

    expect(createDelegation).toHaveBeenCalledWith('work-1', expect.objectContaining({
      source_node_id: 'node-child', proposer_employee_id: 'emp-b',
    }))
  })

  it('disables delegation when work has no current running source', async () => {
    const api = {
      listDelegations: vi.fn().mockResolvedValue({ delegations: [], eligible_employees: [{ id: 'emp-b', display_name: 'Reviewer' }] }),
      createDelegation: vi.fn(),
    } as unknown as ProductApi
    render(<DelegationView api={api} work={work} onWorkUpdated={() => undefined} t={t} />)

    expect(await screen.findByText('No running delegation source')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Delegate' })).toBeDisabled()
  })

  it('allows an empty capability projection to revoke every workspace grant', async () => {
    const replaceWorkspaceCapabilities = vi.fn().mockResolvedValue({ workspace_id: 'ws-1', grants: [] })
    const api = capabilityApi([], replaceWorkspaceCapabilities)
    render(<CapabilityEditor api={api} workspaceId="ws-1" t={t} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Save capabilities' }))
    expect(replaceWorkspaceCapabilities).toHaveBeenCalledWith('ws-1', { grants: [] })
    expect(await screen.findByRole('status')).toHaveTextContent('Capabilities saved')
  })

  it('loads authoritative capabilities before enabling replacement', async () => {
    let resolveLoad!: (value: Awaited<ReturnType<ProductApi['getWorkspaceCapabilities']>>) => void
    const grant: WorkspaceGrant = { action: 'workspace.write', level: 2, resource_kind: 'repository', resource_values: ['repo-a'], requires_approval: true }
    const api = {
      getWorkspaceCapabilities: vi.fn(() => new Promise<Awaited<ReturnType<ProductApi['getWorkspaceCapabilities']>>>(resolve => { resolveLoad = resolve })),
      replaceWorkspaceCapabilities: vi.fn(),
    } as unknown as ProductApi
    render(<CapabilityEditor api={api} workspaceId="ws-1" t={t} />)

    expect(screen.getByRole('button', { name: 'Save capabilities' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('Loading')
    resolveLoad({ workspace_id: 'ws-1', grants: [grant] })

    expect(await screen.findByDisplayValue('repo-a')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Save capabilities' })).toBeEnabled()
  })

  it('shows capability load errors and retries the authoritative read', async () => {
    const getWorkspaceCapabilities = vi.fn()
      .mockRejectedValueOnce(new ApiError('company_request_failed', 'offline'))
      .mockResolvedValueOnce({ workspace_id: 'ws-1', grants: [] })
    const api = { getWorkspaceCapabilities, replaceWorkspaceCapabilities: vi.fn() } as unknown as ProductApi
    render(<CapabilityEditor api={api} workspaceId="ws-1" t={t} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load capabilities')
    expect(screen.getByRole('button', { name: 'Save capabilities' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save capabilities' })).toBeEnabled())
    expect(getWorkspaceCapabilities).toHaveBeenCalledTimes(2)
  })

  it.each([
    ['nine grants', Array.from({ length: 9 }, (_value, index) => ({ action: `invalid-${index}`, level: 1, resource_kind: 'workspace', resource_values: ['ws-1'], requires_approval: false }))],
    ['blank resource kind', [{ action: 'workspace.read', level: 1, resource_kind: ' ', resource_values: ['ws-1'], requires_approval: false }]],
    ['oversized resource', [{ action: 'workspace.read', level: 1, resource_kind: 'workspace', resource_values: ['x'.repeat(201)], requires_approval: false }]],
    ['empty resource list', [{ action: 'workspace.read', level: 1, resource_kind: 'workspace', resource_values: [], requires_approval: false }]],
  ])('rejects invalid capability input locally: %s', async (_name, grants) => {
    const replaceWorkspaceCapabilities = vi.fn()
    render(<CapabilityEditor
      api={capabilityApi(grants as WorkspaceGrant[], replaceWorkspaceCapabilities)}
      workspaceId="ws-1"
      t={t}
    />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Save capabilities' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Save capabilities' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Capability configuration is invalid')
    expect(replaceWorkspaceCapabilities).not.toHaveBeenCalled()
  })

  it('accepts all eight closed actions and reports a server 422 separately', async () => {
    const grants: WorkspaceGrant[] = [
      ['conversation.respond', 0], ['workspace.read', 1], ['session.history.read', 1], ['work.delegate', 1],
      ['workspace.write', 2], ['tool.shell', 2], ['tool.network', 2], ['external.publish', 3],
    ].map(([action, level]) => ({
      action: String(action), level: level as 0 | 1 | 2 | 3, resource_kind: 'workspace',
      resource_values: ['ws-1', 'ws-2'], requires_approval: false,
    }))
    const replaceWorkspaceCapabilities = vi.fn().mockRejectedValue(
      new ApiError('company_request_failed', 'invalid', undefined, 422),
    )
    render(<CapabilityEditor
      api={capabilityApi(grants, replaceWorkspaceCapabilities)}
      workspaceId="ws-1"
      t={t}
    />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Save capabilities' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Save capabilities' }))
    expect(replaceWorkspaceCapabilities).toHaveBeenCalledOnce()
    expect(await screen.findByRole('alert')).toHaveTextContent('Fix the capability fields')
  })

  it('rejects unknown and oversized delegation fields before transport', async () => {
    const createDelegation = vi.fn()
    const api = {
      listDelegations: vi.fn().mockResolvedValue({ delegations: [], eligible_employees: [{ id: 'emp-b', display_name: 'Reviewer' }] }),
      createDelegation,
    } as unknown as ProductApi
    render(<DelegationView api={api} work={runningWork} onWorkUpdated={() => undefined} t={t} />)

    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Delegate to' }), 'emp-b')
    await userEvent.type(screen.getByLabelText('Delegated objective'), 'Review facts')
    await userEvent.type(screen.getByLabelText('Delegated acceptance criteria'), 'Cite sources')
    await userEvent.type(screen.getByLabelText('Required actions'), 'unknown.action')
    await userEvent.type(screen.getByLabelText('Resource scope'), 'repo-a')
    await userEvent.click(screen.getByRole('button', { name: 'Delegate' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Complete every delegation field')
    expect(createDelegation).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Delegated acceptance criteria')).not.toHaveAttribute('maxlength')
    expect(screen.getByLabelText('Required actions')).not.toHaveAttribute('maxlength')
    expect(screen.getByLabelText('Resource scope')).not.toHaveAttribute('maxlength')
  })

  it('submits API-valid serialized multi-value delegation boundaries', async () => {
    const createDelegation = vi.fn().mockResolvedValue({
      delegation: { id: 'delegation-1', workspace_id: 'ws-1', work_id: 'work-1', source_node_id: 'node-1', target_node_id: 'node-2', proposer_employee_id: 'emp-a', target_employee_id: 'emp-b', graph_revision_id: 'graph-2', status: 'accepted', created_at: now },
      work,
    })
    const api = {
      listDelegations: vi.fn().mockResolvedValue({ delegations: [], eligible_employees: [{ id: 'emp-b', display_name: 'Reviewer' }] }),
      createDelegation,
    } as unknown as ProductApi
    render(<DelegationView api={api} work={runningWork} onWorkUpdated={() => undefined} t={t} />)
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Delegate to' }), 'emp-b')
    fireEvent.change(screen.getByLabelText('Delegated objective'), { target: { value: 'Review facts' } })
    fireEvent.change(screen.getByLabelText('Delegated acceptance criteria'), { target: { value: `${'a'.repeat(500)}\n${'b'.repeat(500)}` } })
    fireEvent.change(screen.getByLabelText('Required actions'), { target: { value: [
      'conversation.respond', 'workspace.read', 'session.history.read', 'work.delegate',
      'workspace.write', 'tool.shell', 'tool.network', 'external.publish',
    ].join(',') } })
    fireEvent.change(screen.getByLabelText('Resource scope'), { target: { value: `${'a'.repeat(200)},${'b'.repeat(200)}` } })

    await userEvent.click(screen.getByRole('button', { name: 'Delegate' }))
    expect(createDelegation).toHaveBeenCalledWith('work-1', expect.objectContaining({
      acceptance_criteria: ['a'.repeat(500), 'b'.repeat(500)],
      required_actions: expect.arrayContaining(['conversation.respond', 'external.publish']),
      resource_values: ['a'.repeat(200), 'b'.repeat(200)],
    }))
  })

  it.each([
    ['objective item', 'objective', 'x'.repeat(501)],
    ['criterion item', 'criteria', 'x'.repeat(501)],
    ['criterion count', 'criteria', Array.from({ length: 51 }, () => 'x').join('\n')],
    ['action item', 'actions', 'x'.repeat(121)],
    ['action count', 'actions', Array.from({ length: 9 }, () => 'workspace.read').join(',')],
    ['resource item', 'resources', 'x'.repeat(201)],
    ['resource count', 'resources', Array.from({ length: 51 }, () => 'x').join(',')],
  ])('enforces the delegation OpenAPI boundary: %s', async (_name, field, invalidValue) => {
    const createDelegation = vi.fn()
    const api = {
      listDelegations: vi.fn().mockResolvedValue({ delegations: [], eligible_employees: [{ id: 'emp-b', display_name: 'Reviewer' }] }),
      createDelegation,
    } as unknown as ProductApi
    render(<DelegationView api={api} work={runningWork} onWorkUpdated={() => undefined} t={t} />)
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Delegate to' }), 'emp-b')
    const fields = {
      objective: screen.getByLabelText('Delegated objective'),
      criteria: screen.getByLabelText('Delegated acceptance criteria'),
      actions: screen.getByLabelText('Required actions'),
      resources: screen.getByLabelText('Resource scope'),
    }
    fireEvent.change(fields.objective, { target: { value: 'Review facts' } })
    fireEvent.change(fields.criteria, { target: { value: 'Cite sources' } })
    fireEvent.change(fields.actions, { target: { value: 'workspace.read' } })
    fireEvent.change(fields.resources, { target: { value: 'repo-a' } })
    fireEvent.change(fields[field as keyof typeof fields], { target: { value: invalidValue } })

    await userEvent.click(screen.getByRole('button', { name: 'Delegate' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Complete every delegation field')
    expect(createDelegation).not.toHaveBeenCalled()
  })

  it('distinguishes server 422 field feedback from a policy denial', async () => {
    const createDelegation = vi
      .fn()
      .mockRejectedValueOnce(new ApiError('company_request_failed', 'invalid', undefined, 422))
      .mockRejectedValueOnce(new ApiError('delegation_denied', 'denied', undefined, 409))
    const api = {
      listDelegations: vi.fn().mockResolvedValue({ delegations: [], eligible_employees: [{ id: 'emp-b', display_name: 'Reviewer' }] }),
      createDelegation,
    } as unknown as ProductApi
    render(<DelegationView api={api} work={runningWork} onWorkUpdated={() => undefined} t={t} />)
    const fill = async (): Promise<void> => {
      await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Delegate to' }), 'emp-b')
      await userEvent.type(screen.getByLabelText('Delegated objective'), 'Review facts')
      await userEvent.type(screen.getByLabelText('Delegated acceptance criteria'), 'Cite sources')
      await userEvent.type(screen.getByLabelText('Required actions'), 'workspace.read')
      await userEvent.type(screen.getByLabelText('Resource scope'), 'repo-a')
    }
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Delegate' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Fix the delegation fields')
    await userEvent.click(screen.getByRole('button', { name: 'Delegate' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Delegation denied')
  })

  it('ignores a capability save that completes after the workspace changes', async () => {
    let resolveSave!: (value: Awaited<ReturnType<ProductApi['replaceWorkspaceCapabilities']>>) => void
    const replaceWorkspaceCapabilities = vi.fn(() => new Promise<Awaited<ReturnType<ProductApi['replaceWorkspaceCapabilities']>>>(resolve => { resolveSave = resolve }))
    const grant: WorkspaceGrant = { action: 'workspace.read', level: 1, resource_kind: 'workspace', resource_values: ['ws-1'], requires_approval: false }
    const api = {
      getWorkspaceCapabilities: vi.fn((workspaceId: string) => Promise.resolve({ workspace_id: workspaceId, grants: workspaceId === 'ws-1' ? [grant] : [] })),
      replaceWorkspaceCapabilities,
    } as unknown as ProductApi
    const view = render(<CapabilityEditor api={api} workspaceId="ws-1" t={t} />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save capabilities' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Save capabilities' }))

    view.rerender(<CapabilityEditor api={api} workspaceId="ws-2" t={t} />)
    resolveSave({ workspace_id: 'ws-1', grants: [grant] })

    await waitFor(() => expect(screen.getByRole('button', { name: 'Save capabilities' })).toBeEnabled())
    expect(screen.queryByText('Capabilities saved')).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('ws-1')).not.toBeInTheDocument()
  })

  it('preserves an edited capability draft across same-workspace polling rerenders', async () => {
    const api = capabilityApi([])
    const view = render(<CapabilityEditor api={api} workspaceId="ws-1" t={t} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add capability' }))
    expect(screen.getByDisplayValue('ws-1')).toBeVisible()

    view.rerender(<CapabilityEditor api={api} workspaceId="ws-1" t={t} />)
    expect(screen.getByDisplayValue('ws-1')).toBeVisible()

    view.rerender(<CapabilityEditor api={api} workspaceId="ws-2" t={t} />)
    expect(screen.queryByDisplayValue('ws-1')).not.toBeInTheDocument()
  })

  it('ignores an approval decision that completes after the workspace changes', async () => {
    let resolveDecision!: (value: Awaited<ReturnType<ProductApi['approveApproval']>>) => void
    const approval = {
      id: 'approval-1', workspace_id: 'ws-1', work_id: 'work-1', node_id: 'node-1', action: 'workspace.write',
      resources: ['repo-a'], reason: 'Change', status: 'pending' as const, requested_at: now, decided_at: null,
      decided_by: null, requesting_employee: { id: 'emp-a', display_name: 'Publisher' },
    }
    const api = {
      listApprovals: vi.fn((workspaceId: string) => Promise.resolve(workspaceId === 'ws-1' ? [approval] : [])),
      approveApproval: vi.fn(() => new Promise<Awaited<ReturnType<ProductApi['approveApproval']>>>(resolve => { resolveDecision = resolve })),
      rejectApproval: vi.fn(),
    } as unknown as ProductApi
    const onWorkUpdated = vi.fn()
    const view = render(<ApprovalInbox api={api} workspaceId="ws-1" onWorkUpdated={onWorkUpdated} t={t} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }))

    view.rerender(<ApprovalInbox api={api} workspaceId="ws-2" onWorkUpdated={onWorkUpdated} t={t} />)
    resolveDecision({ approval: { ...approval, status: 'approved', decided_at: now, decided_by: 'operator' }, work })

    await screen.findByText('No pending approvals')
    expect(onWorkUpdated).not.toHaveBeenCalled()
    expect(screen.queryByText('workspace.write')).not.toBeInTheDocument()
  })

  it('ignores a delegation that completes after the selected work changes', async () => {
    let resolveDelegation!: (value: Awaited<ReturnType<ProductApi['createDelegation']>>) => void
    const createDelegation = vi.fn(() => new Promise<Awaited<ReturnType<ProductApi['createDelegation']>>>(resolve => { resolveDelegation = resolve }))
    const api = {
      listDelegations: vi.fn().mockResolvedValue({ delegations: [], eligible_employees: [{ id: 'emp-b', display_name: 'Reviewer' }] }),
      createDelegation,
    } as unknown as ProductApi
    const onWorkUpdated = vi.fn()
    const view = render(<DelegationView api={api} work={runningWork} onWorkUpdated={onWorkUpdated} t={t} />)
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Delegate to' }), 'emp-b')
    await userEvent.type(screen.getByLabelText('Delegated objective'), 'Review facts')
    await userEvent.type(screen.getByLabelText('Delegated acceptance criteria'), 'Cite sources')
    await userEvent.type(screen.getByLabelText('Required actions'), 'workspace.read')
    await userEvent.type(screen.getByLabelText('Resource scope'), 'repo-a')
    await userEvent.click(screen.getByRole('button', { name: 'Delegate' }))

    const nextWork = { ...runningWork, id: 'work-2', command_id: 'cmd-2' }
    view.rerender(<DelegationView api={api} work={nextWork} onWorkUpdated={onWorkUpdated} t={t} />)
    resolveDelegation({
      delegation: { id: 'delegation-1', workspace_id: 'ws-1', work_id: 'work-1', source_node_id: 'node-1', target_node_id: 'node-2', proposer_employee_id: 'emp-a', target_employee_id: 'emp-b', graph_revision_id: 'graph-2', status: 'accepted', created_at: now },
      work,
    })

    await waitFor(() => expect(screen.getByRole('button', { name: 'Delegate' })).toBeEnabled())
    expect(onWorkUpdated).not.toHaveBeenCalled()
    expect(screen.queryByText('Accepted')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Delegated objective')).toHaveValue('')
  })
})

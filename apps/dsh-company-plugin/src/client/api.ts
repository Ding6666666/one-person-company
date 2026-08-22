import type {
  RemoteResult as TypertRemoteResult,
  TypertRemoteContribution,
  TypertRemoteNamespace,
} from '@deepseek-ai/dsh-typert-protocol'
import { z } from 'zod'

import type { components } from '../contracts/generated/openapi.js'
import type {
  CompanyConnectionState,
  CompanyRemoteNamespace,
  CompanyRequestPath,
  RemoteResult,
} from '../remote-contract.js'

export type ApiSchemas = components['schemas']
export type Workspace = ApiSchemas['Workspace']
export type Employee = ApiSchemas['Employee']
export type WorkspaceCreate = ApiSchemas['WorkspaceCreate']
export type EmployeeCreate = ApiSchemas['EmployeeCreate']
export type DirectWorkCreate = ApiSchemas['DirectWorkCreate']
export type DirectStrategyInput = ApiSchemas['DirectStrategyInput']
export type StarStrategyInput = ApiSchemas['StarStrategyInput']
export type GraphStrategyInput = ApiSchemas['GraphStrategyInput']
export type BattleStrategyInput = ApiSchemas['BattleStrategyInput']
export type StrategyWorkCreate = DirectStrategyInput | StarStrategyInput | GraphStrategyInput | BattleStrategyInput
export type WorkProjection = ApiSchemas['WorkProjection']
export type CompanyEvent = ApiSchemas['CompanyEvent']
export type WorkspaceGrant = ApiSchemas['WorkspaceGrant']
export type WorkspaceCapabilities = ApiSchemas['WorkspaceCapabilities']
export type WorkspaceCapabilitiesUpdate = ApiSchemas['WorkspaceCapabilitiesUpdate']
export type ApprovalProjection = ApiSchemas['ApprovalProjection']
export type ApprovalDecisionProjection = ApiSchemas['ApprovalDecisionProjection']
export type DelegationCreate = ApiSchemas['DelegationCreate']
export type DelegationCollection = ApiSchemas['DelegationCollection']
export type DelegationResultProjection = ApiSchemas['DelegationResultProjection']
export type CapabilitySourceView = ApiSchemas['CapabilitySourceView']
export type CapabilityEntryView = ApiSchemas['CapabilityEntryView']
export type CapabilityImport = ApiSchemas['CapabilityImport']
export type RuntimeOptions = ApiSchemas['RuntimeOptions']

const workspaceSchema: z.ZodType<Workspace> = z.object({
  id: z.string(),
  name: z.string(),
  created_at: z.string(),
})
const grantSchema = z.object({
  id: z.string(),
  employee_revision_id: z.string().nullable(),
  action: z.string(),
  level: z.union([z.literal(0), z.literal(1), z.literal(2), z.literal(3)]),
  resource_kind: z.string(),
  resource_values: z.array(z.string()),
  requires_approval: z.boolean(),
})
const revisionSchema = z.object({
  id: z.string(),
  employee_id: z.string(),
  revision_number: z.number(),
  responsibility: z.string(),
  system_prompt: z.string(),
  runtime_profile: z.string(),
  model: z.string(),
  created_at: z.string(),
  role_template_key: z.string(),
  work_type: z.string(),
  avatar_key: z.string(),
  skill_refs: z.array(z.string()),
  tool_refs: z.array(z.string()),
})
const bindingSchema = z.object({
  id: z.string(),
  employee_id: z.string(),
  dsh_agent_id: z.string(),
  dsh_session_id: z.string(),
  memory_scope_id: z.string(),
  created_at: z.string(),
})
const employeeSchema: z.ZodType<Employee> = z.object({
  id: z.string(),
  workspace_id: z.string(),
  display_name: z.string(),
  status: z.enum(['active', 'paused', 'archived']),
  current_revision_id: z.string(),
  created_at: z.string(),
  revision: revisionSchema,
  binding: bindingSchema,
  grants: z.array(grantSchema),
})
const workNodeStatusSchema = z.enum(['draft', 'ready', 'waiting_approval', 'running', 'blocked', 'completed', 'failed', 'cancelled'])
const workStatusSchema = z.enum(['queued', 'running', 'blocked', 'completed', 'failed', 'cancelled'])
const executionStatusSchema = z.enum([
  'dispatch_pending', 'running', 'cancel_requested', 'blocked', 'completed', 'failed', 'cancelled',
])
const workProjectionSchema: z.ZodType<WorkProjection> = z.object({
  id: z.string(),
  workspace_id: z.string(),
  command_id: z.string(),
  objective: z.string(),
  status: workStatusSchema,
  graph_revision_id: z.string(),
  graph_revision_number: z.number(),
  strategy: z.enum(['direct', 'star', 'graph', 'battle']),
  nodes: z.array(z.object({
    id: z.string(),
    objective: z.string(),
    acceptance_criteria: z.array(z.string()),
    assigned_employee_id: z.string(),
    employee_revision_id: z.string(),
    status: workNodeStatusSchema,
    active_attempt_id: z.string().nullable(),
    failure_code: z.string().nullable(),
    version: z.number(),
    attempt_count: z.number().default(0),
    max_attempts: z.number().default(1),
  })),
  edges: z.array(z.object({
    from_node_id: z.string(),
    to_node_id: z.string(),
    kind: z.enum(['depends_on', 'delegates_to', 'reviews', 'summarizes']),
  })).default([]),
  execution_links: z.array(z.object({
    id: z.string(),
    node_id: z.string(),
    attempt_id: z.string(),
    status: executionStatusSchema,
    started_at: z.string().nullable(),
    finished_at: z.string().nullable(),
    diagnostic_code: z.string().nullable(),
  })),
  artifacts: z.array(z.object({
    id: z.string(),
    kind: z.literal('dsh_session_result'),
    uri: z.string(),
    created_at: z.string(),
  })),
  created_at: z.string(),
})
const companyEventSchema: z.ZodType<CompanyEvent> = z.object({
  id: z.string(),
  workspace_id: z.string(),
  work_id: z.string(),
  node_id: z.string().nullable(),
  attempt_id: z.string().nullable(),
  source_sequence: z.number(),
  event_type: z.string(),
  summary: z.string(),
  source: z.string(),
  observed_at: z.string(),
})
const workspaceGrantSchema: z.ZodType<WorkspaceGrant> = z.object({
  action: z.string(), level: z.union([z.literal(0), z.literal(1), z.literal(2), z.literal(3)]),
  resource_kind: z.string(), resource_values: z.array(z.string()), requires_approval: z.boolean(),
})
const workspaceCapabilitiesSchema: z.ZodType<WorkspaceCapabilities> = z.object({
  workspace_id: z.string(), grants: z.array(workspaceGrantSchema),
})
const employeeSummarySchema = z.object({ id: z.string(), display_name: z.string() })
const approvalProjectionSchema: z.ZodType<ApprovalProjection> = z.object({
  id: z.string(), workspace_id: z.string(), work_id: z.string(), node_id: z.string(), action: z.string(),
  resources: z.array(z.string()), reason: z.string(), status: z.enum(['pending', 'approved', 'rejected', 'cancelled']),
  requested_at: z.string(), decided_at: z.string().nullable(), decided_by: z.string().nullable(),
  requesting_employee: employeeSummarySchema,
})
const approvalDecisionProjectionSchema: z.ZodType<ApprovalDecisionProjection> = z.object({
  approval: approvalProjectionSchema, work: workProjectionSchema,
})
const delegationProjectionSchema = z.object({
  id: z.string(), workspace_id: z.string(), work_id: z.string(), source_node_id: z.string(), target_node_id: z.string().nullable(),
  proposer_employee_id: z.string(), target_employee_id: z.string(), graph_revision_id: z.string(),
  status: z.enum(['proposed', 'accepted', 'rejected', 'completed']), created_at: z.string(),
})
const delegationCollectionSchema: z.ZodType<DelegationCollection> = z.object({
  delegations: z.array(delegationProjectionSchema), eligible_employees: z.array(employeeSummarySchema),
})
const delegationResultProjectionSchema: z.ZodType<DelegationResultProjection> = z.object({
  delegation: delegationProjectionSchema, work: workProjectionSchema,
})
const errorSchema = z.object({
  error: z.object({ code: z.string(), message: z.string(), correlation_id: z.string() }),
})
const capabilitySourceSchema: z.ZodType<CapabilitySourceView> = z.object({
  id: z.string(), kind: z.enum(['skill', 'tool']), display_name: z.string(),
})
const capabilityEntrySchema: z.ZodType<CapabilityEntryView> = z.object({
  ref: z.string(), source_id: z.string(), kind: z.enum(['skill', 'tool']), name: z.string(),
  description: z.string(), version: z.string(), required_actions: z.array(z.string()),
})
const runtimeOptionsSchema: z.ZodType<RuntimeOptions> = z.object({
  provider: z.string(), default_model: z.string(),
})

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly correlationId?: string,
    readonly status?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export class ProductApi {
  constructor(private readonly remote: Pick<CompanyRemoteNamespace, 'request'>) {}

  listWorkspaces(): Promise<Workspace[]> {
    return this.request('GET', '/workspaces', undefined, z.array(workspaceSchema))
  }

  createWorkspace(body: WorkspaceCreate): Promise<Workspace> {
    return this.request('POST', '/workspaces', body, workspaceSchema)
  }

  listEmployees(workspaceId: string): Promise<Employee[]> {
    return this.request(
      'GET',
      `/workspaces/${encodeURIComponent(workspaceId)}/employees`,
      undefined,
      z.array(employeeSchema),
    )
  }

  createEmployee(workspaceId: string, body: EmployeeCreate): Promise<Employee> {
    return this.request(
      'POST',
      `/workspaces/${encodeURIComponent(workspaceId)}/employees`,
      body,
      employeeSchema,
    )
  }

  listCapabilitySources(kind: 'skill' | 'tool'): Promise<CapabilitySourceView[]> {
    return this.request('GET', `/capability-sources/${kind}`, undefined, z.array(capabilitySourceSchema))
  }

  listCapabilityEntries(kind: 'skill' | 'tool'): Promise<CapabilityEntryView[]> {
    return this.request('GET', `/capability-entries/${kind}`, undefined, z.array(capabilityEntrySchema))
  }

  importCapability(body: CapabilityImport): Promise<CapabilityEntryView> {
    return this.request('POST', '/capability-imports', body, capabilityEntrySchema)
  }

  getRuntimeOptions(): Promise<RuntimeOptions> {
    return this.request('GET', '/runtime-options', undefined, runtimeOptionsSchema)
  }

  listWorks(workspaceId: string): Promise<WorkProjection[]> {
    return this.request(
      'GET',
      `/workspaces/${encodeURIComponent(workspaceId)}/works`,
      undefined,
      z.array(workProjectionSchema),
    )
  }

  createDirectWork(workspaceId: string, body: DirectWorkCreate): Promise<WorkProjection> {
    return this.request(
      'POST',
      `/workspaces/${encodeURIComponent(workspaceId)}/works`,
      body,
      workProjectionSchema,
    )
  }

  createWork(workspaceId: string, body: StrategyWorkCreate): Promise<WorkProjection> {
    return this.request(
      'POST',
      `/workspaces/${encodeURIComponent(workspaceId)}/works`,
      body,
      workProjectionSchema,
    )
  }

  getWork(workId: string): Promise<WorkProjection> {
    return this.request('GET', `/works/${encodeURIComponent(workId)}`, undefined, workProjectionSchema)
  }

  listWorkEvents(workId: string): Promise<CompanyEvent[]> {
    return this.request(
      'GET',
      `/works/${encodeURIComponent(workId)}/events`,
      undefined,
      z.array(companyEventSchema),
    )
  }

  cancelWork(workId: string): Promise<WorkProjection> {
    return this.request('POST', `/works/${encodeURIComponent(workId)}/cancel`, undefined, workProjectionSchema)
  }

  replaceWorkspaceCapabilities(workspaceId: string, body: WorkspaceCapabilitiesUpdate): Promise<WorkspaceCapabilities> {
    return this.request('PUT', `/workspaces/${encodeURIComponent(workspaceId)}/capabilities`, body, workspaceCapabilitiesSchema)
  }

  getWorkspaceCapabilities(workspaceId: string): Promise<WorkspaceCapabilities> {
    return this.request('GET', `/workspaces/${encodeURIComponent(workspaceId)}/capabilities`, undefined, workspaceCapabilitiesSchema)
  }

  listApprovals(workspaceId: string): Promise<ApprovalProjection[]> {
    return this.request('GET', `/workspaces/${encodeURIComponent(workspaceId)}/approvals`, undefined, z.array(approvalProjectionSchema))
  }

  approveApproval(approvalId: string, decidedBy: string): Promise<ApprovalDecisionProjection> {
    return this.request('POST', `/approvals/${encodeURIComponent(approvalId)}/approve`, { decided_by: decidedBy }, approvalDecisionProjectionSchema)
  }

  rejectApproval(approvalId: string, decidedBy: string): Promise<ApprovalDecisionProjection> {
    return this.request('POST', `/approvals/${encodeURIComponent(approvalId)}/reject`, { decided_by: decidedBy }, approvalDecisionProjectionSchema)
  }

  listDelegations(workId: string): Promise<DelegationCollection> {
    return this.request('GET', `/works/${encodeURIComponent(workId)}/delegations`, undefined, delegationCollectionSchema)
  }

  createDelegation(workId: string, body: DelegationCreate): Promise<DelegationResultProjection> {
    return this.request('POST', `/works/${encodeURIComponent(workId)}/delegations`, body, delegationResultProjectionSchema)
  }

  private async request<T>(
    method: 'GET' | 'POST' | 'PUT',
    path: CompanyRequestPath,
    body: unknown,
    schema: z.ZodType<T>,
  ): Promise<T> {
    const result = await this.remote.request(body === undefined ? { method, path } : { method, path, body })
    if (result.status >= 400) {
      const error = errorSchema.safeParse(result.body)
      if (error.success) {
        throw new ApiError(error.data.error.code, error.data.error.message, error.data.error.correlation_id, result.status)
      }
      throw new ApiError('company_request_failed', 'Company request failed', result.correlationId, result.status)
    }
    const parsed = schema.safeParse(result.body)
    if (!parsed.success) throw new ApiError('invalid_company_response', 'Company response did not match its contract')
    return parsed.data
  }
}

declare module '@deepseek-ai/dsh-typert-protocol' {
  interface TypertRemoteMap {
    'company/connection': () => Promise<TypertRemoteResult<RemoteResult<CompanyConnectionState>>>
    'company/request': (
      input: Parameters<CompanyRemoteNamespace['request']>[0],
    ) => Promise<TypertRemoteResult<RemoteResult<unknown>>>
  }
  interface TypertRemoteNamespaceMap {
    company: TypertRemoteNamespace<'company'>
  }
}

const strictJson = (typeSymbol: string) => ({
  mode: 'strict' as const,
  typeSymbol,
  schema: z.json(),
})

export const COMPANY_REMOTE = {
  package: '@dsh/company-plugin',
  descriptors: [
    {
      id: '@dsh/company-plugin#company/connection',
      service: 'company',
      namespace: 'company',
      method: 'connection',
      invocation: { kind: 'direct' },
      parameters: [],
      result: strictJson('CompanyConnectionResult'),
    },
    {
      id: '@dsh/company-plugin#company/request',
      service: 'company',
      namespace: 'company',
      method: 'request',
      invocation: { kind: 'direct' },
      parameters: [{
        name: 'input',
        wire: 'input',
        source: 'json',
        codec: strictJson('CompanyProductRequest'),
      }],
      result: strictJson('CompanyProductResult'),
    },
  ],
} as const satisfies TypertRemoteContribution

type CarrierResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: unknown }

export interface CompanyCarrierRemote {
  connection(): Promise<CarrierResult<RemoteResult<CompanyConnectionState>>>
  request(input: Parameters<CompanyRemoteNamespace['request']>[0]): Promise<CarrierResult<RemoteResult<unknown>>>
}

const unavailable = (): RemoteResult<unknown> => ({
  status: 503,
  body: { error: { code: 'company_remote_unavailable', message: 'Company remote unavailable', correlation_id: 'remote' } },
})
const unavailableConnection = (): RemoteResult<CompanyConnectionState> => ({
  status: 503,
  body: { status: 'offline', code: 'COMPANY_SERVICE_UNAVAILABLE' },
})

export function createCompanyRemote(remote: CompanyCarrierRemote): CompanyRemoteNamespace {
  return {
    async connection() {
      try {
        const result = await remote.connection()
        return result.ok ? result.value : unavailableConnection()
      } catch {
        return unavailableConnection()
      }
    },
    async request(input) {
      try {
        const result = await remote.request(input)
        return result.ok ? result.value : unavailable()
      } catch {
        return unavailable()
      }
    },
  }
}

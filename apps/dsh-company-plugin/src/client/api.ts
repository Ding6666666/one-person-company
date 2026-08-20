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
  runtime_profile: z.string(),
  model: z.string(),
  created_at: z.string(),
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
const errorSchema = z.object({
  error: z.object({ code: z.string(), message: z.string(), correlation_id: z.string() }),
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

  private async request<T>(
    method: 'GET' | 'POST',
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

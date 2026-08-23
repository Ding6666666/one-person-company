import type { paths } from './contracts/generated/openapi.js'

export type CompanyRequestMethod = 'GET' | 'POST' | 'PUT'
type OpenApiPath = Extract<keyof paths, string>
type MaterializePath<Path extends string> =
  Path extends `${infer Prefix}{${string}}${infer Suffix}`
    ? `${Prefix}${string}${MaterializePath<Suffix>}`
    : Path

export type CompanyRequestPath =
  | MaterializePath<OpenApiPath>
  | `/workspaces/${string}/messages?work_id=${string}`

export interface RemoteResult<T> {
  readonly status: number
  readonly correlationId?: string
  readonly body: T
}

export type CompanyConnectionState =
  | { readonly status: 'online' }
  | { readonly status: 'offline'; readonly code: 'COMPANY_SERVICE_UNAVAILABLE' }

export interface CompanyTransportRequest {
  readonly method: CompanyRequestMethod
  readonly path: CompanyRequestPath
  readonly body?: unknown
  readonly correlationId?: string
}

export interface CompanyRemoteNamespace {
  connection(): Promise<RemoteResult<CompanyConnectionState>>
  request(input: CompanyTransportRequest): Promise<RemoteResult<unknown>>
}

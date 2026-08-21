import type { components, paths } from './generated/openapi.js'

export type { components, operations, paths } from './generated/openapi.js'

export type BusinessPluginManifest = components['schemas']['BusinessPluginManifest-Input']
export type BusinessPluginRegistration = components['schemas']['BusinessPluginRegistration']
export type WorkTemplate = components['schemas']['WorkTemplate-Output']
export type TemplateInstantiation = components['schemas']['TemplateInstantiation']
export type WorkProjection = components['schemas']['WorkProjection']

export interface CompanyPluginTransportRequest {
  readonly method: 'GET' | 'POST'
  readonly path: string
  readonly body?: unknown
}

export interface CompanyPluginTransportResult {
  readonly status: number
  readonly body: unknown
}

export interface CompanyPluginTransport {
  request(input: CompanyPluginTransportRequest): Promise<CompanyPluginTransportResult>
}

export class CompanyPluginError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`Company plugin API returned ${status}`)
    this.name = 'CompanyPluginError'
  }
}

export class CompanyPluginClient {
  constructor(private readonly transport: CompanyPluginTransport) {}

  register(manifest: BusinessPluginManifest): Promise<BusinessPluginRegistration> {
    return this.request('POST', '/business-plugins/register', manifest)
  }

  list(): Promise<BusinessPluginRegistration[]> {
    return this.request('GET', '/business-plugins')
  }

  templates(pluginId: string): Promise<WorkTemplate[]> {
    return this.request(
      'GET',
      `/business-plugins/${segment(pluginId)}/templates` as keyof paths & string,
    )
  }

  instantiate(
    workspaceId: string,
    pluginId: string,
    templateId: string,
    input: TemplateInstantiation,
  ): Promise<WorkProjection> {
    return this.request(
      'POST',
      `/workspaces/${segment(workspaceId)}/templates/${segment(pluginId)}/${segment(templateId)}/instantiate`,
      input,
    )
  }

  private async request<T>(
    method: 'GET' | 'POST',
    path: string,
    body?: unknown,
  ): Promise<T> {
    const result = await this.transport.request({
      method,
      path,
      ...(body === undefined ? {} : { body }),
    })
    if (result.status < 200 || result.status >= 300) {
      throw new CompanyPluginError(result.status, result.body)
    }
    return result.body as T
  }
}

function segment(value: string): string {
  const normalized = value.trim()
  if (normalized.length === 0 || normalized.includes('/')) {
    throw new TypeError('path segment must be non-blank and contain no slash')
  }
  return encodeURIComponent(normalized)
}

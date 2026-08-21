import type {
  CompanyTransportRequest,
  RemoteResult,
} from './remote-contract.js'

const REQUEST_TIMEOUT_MS = 10_000

export interface LoopbackTransportOptions {
  readonly baseUrl: string
  readonly fetch?: typeof fetch
  readonly timeoutMs?: number
}

export interface LoopbackTransport {
  request(input: CompanyTransportRequest): Promise<RemoteResult<unknown>>
}

function resolveCompanyPath(baseUrl: string, method: string, path: string): string {
  if (method !== 'GET' && method !== 'POST' && method !== 'PUT') throw new Error('method_not_allowed')
  const allowed = path === '/health'
    || path === '/workspaces'
    || /^\/workspaces\/[^/]+\/employees$/u.test(path)
    || /^\/workspaces\/[^/]+\/(?:works|approvals|capabilities)$/u.test(path)
    || /^\/employees\/[^/]+(?:\/revisions)?$/u.test(path)
    || /^\/works\/[^/]+(?:\/(?:events|cancel|delegations))?$/u.test(path)
    || /^\/approvals\/[^/]+\/(?:approve|reject)$/u.test(path)
    || path === '/business-plugins'
    || path === '/business-plugins/register'
    || /^\/business-plugins\/[^/]+\/templates$/u.test(path)
    || /^\/workspaces\/[^/]+\/templates\/[^/]+\/[^/]+\/instantiate$/u.test(path)
  if (!allowed) throw new Error('route_not_allowed')

  const base = new URL(baseUrl)
  if (base.protocol !== 'http:' || base.hostname !== '127.0.0.1') {
    throw new Error('loopback_base_required')
  }
  return new URL(path, base).toString()
}

export function createLoopbackTransport(options: LoopbackTransportOptions): LoopbackTransport {
  const request = options.fetch ?? fetch
  const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS
  return {
    request(input) {
      const url = resolveCompanyPath(options.baseUrl, input.method, input.path)
      return send(request, timeoutMs, url, input)
    },
  }
}

async function send(
  request: typeof fetch,
  timeoutMs: number,
  url: string,
  input: CompanyTransportRequest,
): Promise<RemoteResult<unknown>> {
  const headers: Record<string, string> = {}
  let body: string | undefined
  if (input.body !== undefined) {
    body = JSON.stringify(input.body)
    if (body === undefined) throw new Error('request_body_not_serializable')
    headers['content-type'] = 'application/json'
  }
  if (input.correlationId !== undefined) headers['x-correlation-id'] = input.correlationId
  const response = await request(url, {
    method: input.method,
    headers,
    ...(body === undefined ? {} : { body }),
    signal: AbortSignal.timeout(timeoutMs),
  })
  const text = await response.text()
  const parsed = text.length === 0 ? null : JSON.parse(text) as unknown
  const correlationId = response.headers.get('x-correlation-id') ?? undefined
  return correlationId === undefined
    ? { status: response.status, body: parsed }
    : { status: response.status, correlationId, body: parsed }
}

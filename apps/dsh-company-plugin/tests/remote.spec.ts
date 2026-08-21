import { Context } from '@deepseek-ai/cordis'
import { remoteMethods } from '@deepseek-ai/dsh-typert-protocol'
import { describe, expect, it, vi } from 'vitest'

import { CompanyPluginService, type ManagedLifecycle } from '../src/host/plugin.js'
import CompanyHostService from '../src/host/service.js'
import { createLoopbackTransport } from '../src/remote.js'
import type { CompanyTransportRequest } from '../src/remote-contract.js'

function lifecycle(events: string[], id: number): ManagedLifecycle {
  return {
    status: 'stopped',
    async start() {
      this.status = 'online'
      events.push(`start:${id}`)
      return { healthUrl: 'http://127.0.0.1:43123/health' }
    },
    async dispose() {
      this.status = 'stopped'
      events.push(`stop:${id}`)
    },
  }
}

describe('Company loopback transport', () => {
  it.each([
    ['GET', '/health'],
    ['GET', '/workspaces'],
    ['POST', '/workspaces'],
    ['GET', '/workspaces/ws-1/employees'],
    ['POST', '/workspaces/ws-1/employees'],
    ['GET', '/employees/emp-1'],
    ['POST', '/employees/emp-1/revisions'],
    ['PUT', '/workspaces/ws-1/capabilities'],
    ['GET', '/workspaces/ws-1/capabilities'],
    ['GET', '/workspaces/ws-1/approvals'],
    ['POST', '/approvals/approval-1/approve'],
    ['POST', '/approvals/approval-1/reject'],
    ['GET', '/works/work-1/delegations'],
    ['POST', '/works/work-1/delegations'],
    ['POST', '/business-plugins/register'],
    ['GET', '/business-plugins'],
    ['GET', '/business-plugins/content-studio/templates'],
    ['POST', '/workspaces/ws-1/templates/content-studio/campaign/instantiate'],
  ] as const)('allows %s %s from the generated company contract', async (method, path) => {
    const fetch = vi.fn(async () => new Response('{}', { status: 200 }))
    const remote = createLoopbackTransport({ baseUrl: 'http://127.0.0.1:43123', fetch })

    await expect(remote.request({ method, path })).resolves.toMatchObject({ status: 200 })
    expect(fetch).toHaveBeenCalledWith(`http://127.0.0.1:43123${path}`, expect.objectContaining({ method }))
  })

  it('rejects routes outside the company contract synchronously', () => {
    const remote = createLoopbackTransport({ baseUrl: 'http://127.0.0.1:43123' })

    expect(() => remote.request(
      { method: 'GET', path: '/outside' } as unknown as CompanyTransportRequest,
    )).toThrow('route_not_allowed')
  })

  it('rejects methods outside the company contract synchronously', () => {
    const remote = createLoopbackTransport({ baseUrl: 'http://127.0.0.1:43123' })

    expect(() => remote.request({ method: 'DELETE' as 'GET', path: '/workspaces' })).toThrow('method_not_allowed')
  })

  it.each(['https://example.com/workspaces', '//example.com/workspaces', '/../outside']) (
    'never sends %s beyond the loopback boundary',
    path => {
      const remote = createLoopbackTransport({ baseUrl: 'http://127.0.0.1:43123' })
      expect(() => remote.request(
        { method: 'GET', path } as CompanyTransportRequest,
      )).toThrow('route_not_allowed')
    },
  )
})

describe('CompanyPluginService', () => {
  it('restarts the service after a credential update', async () => {
    const events: string[] = []
    let next = 0
    const service = new CompanyPluginService({
      createLifecycle: () => lifecycle(events, ++next),
    })

    await service.connection()
    await service.credentialUpdated()
    await service.connection()

    expect(events).toEqual(['start:1', 'stop:1', 'start:2'])
    await service.dispose()
  })

  it('finishes the old stop before starting after a credential update', async () => {
    let finishStop: (() => void) | undefined
    const stopGate = new Promise<void>(resolve => { finishStop = resolve })
    const events: string[] = []
    let next = 0
    const service = new CompanyPluginService({
      createLifecycle: () => {
        const managed = lifecycle(events, ++next)
        if (next !== 1) return managed
        return {
          ...managed,
          async dispose() {
            events.push('stop-start:1')
            await stopGate
            managed.status = 'stopped'
            events.push('stop-finish:1')
          },
        }
      },
    })
    await service.connection()

    const update = service.credentialUpdated()
    await vi.waitFor(() => expect(events).toContain('stop-start:1'))
    const reconnect = service.connection()
    await Promise.resolve()
    expect(events).not.toContain('start:2')

    finishStop?.()
    await update
    await reconnect
    expect(events).toEqual(['start:1', 'stop-start:1', 'stop-finish:1', 'start:2'])
    await service.dispose()
  })

  it('waits for an active request before credential rotation stops the child', async () => {
    let finishRequest: ((response: Response) => void) | undefined
    const response = new Promise<Response>(resolve => { finishRequest = resolve })
    const events: string[] = []
    const request = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      const result = await response
      events.push('request:end')
      return result
    })
    const service = new CompanyPluginService({ createLifecycle: () => lifecycle(events, 1) })
    try {
      await service.connection()
      const active = service.request({ method: 'GET', path: '/workspaces' })
      await vi.waitFor(() => expect(request).toHaveBeenCalledOnce())

      const rotation = service.credentialUpdated()
      await Promise.resolve()
      expect(events).toEqual(['start:1'])

      finishRequest?.(new Response('[]', { status: 200 }))
      await active
      await rotation
      expect(events).toEqual(['start:1', 'request:end', 'stop:1'])
    } finally {
      request.mockRestore()
      await service.dispose()
    }
  })

  it('waits for an active request before plugin disposal stops the child', async () => {
    let finishRequest: ((response: Response) => void) | undefined
    const response = new Promise<Response>(resolve => { finishRequest = resolve })
    const events: string[] = []
    const request = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      const result = await response
      events.push('request:end')
      return result
    })
    const service = new CompanyPluginService({ createLifecycle: () => lifecycle(events, 1) })
    try {
      await service.connection()
      const active = service.request({ method: 'GET', path: '/workspaces' })
      await vi.waitFor(() => expect(request).toHaveBeenCalledOnce())

      const disposal = service.dispose()
      await Promise.resolve()
      expect(events).toEqual(['start:1'])

      finishRequest?.(new Response('[]', { status: 200 }))
      await active
      await disposal
      expect(events).toEqual(['start:1', 'request:end', 'stop:1'])
    } finally {
      request.mockRestore()
      await service.dispose()
    }
  })

  it('stops its child when the plugin is disposed', async () => {
    const events: string[] = []
    const service = new CompanyPluginService({ createLifecycle: () => lifecycle(events, 1) })
    await service.connection()

    await service.dispose()

    expect(events).toEqual(['start:1', 'stop:1'])
  })
})

describe('Company Host remote discovery', () => {
  it('publishes connection and request in the company Typert namespace', async () => {
    const ctx = new Context().extend({
      credentials: { resolve: async () => undefined },
    })
    const service = new CompanyHostService(ctx, {
      pythonPath: 'python.exe',
      serviceDirectory: 'C:/company-service',
      dataRoot: 'C:/company-data',
    })

    expect(service.typertRemote).toMatchObject({
      service,
      serviceKey: 'company',
      namespace: 'company',
    })
    expect(remoteMethods(service)).toEqual([
      { method: 'connection', invocation: { kind: 'direct' } },
      { method: 'request', invocation: { kind: 'direct' } },
    ])
  })
})

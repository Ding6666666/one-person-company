import { EventEmitter } from 'node:events'
import { createServer } from 'node:net'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { resolveHostConfig } from '../src/host/config.js'
import {
  CompanyHostLifecycle,
  reserveLoopbackPort,
  selectChildEnvironment,
  type ChildProcessLike,
} from '../src/host/lifecycle.js'

class FakeChild extends EventEmitter implements ChildProcessLike {
  readonly pid = 43123
  exitCode: number | null = null
  readonly kill = vi.fn((signal: NodeJS.Signals) => {
    if (signal === 'SIGTERM') queueMicrotask(() => this.exit(0))
    return true
  })

  exit(code: number): void {
    this.exitCode = code
    this.emit('exit', code, null)
  }
}

const activeHosts: CompanyHostLifecycle[] = []

afterEach(async () => {
  await Promise.all(activeHosts.splice(0).map(async host => host.dispose().catch(() => undefined)))
})

function createHost(overrides: Partial<ConstructorParameters<typeof CompanyHostLifecycle>[0]> = {}) {
  const host = new CompanyHostLifecycle({
    pythonPath: 'python.exe',
    serviceDirectory: 'C:/company-service',
    startupTimeoutMs: 25,
    pollIntervalMs: 1,
    reservePort: async () => 43123,
    fetch: vi.fn(async () => new Response(
      JSON.stringify({ status: 'ok', service: 'dsh-company' }),
      { status: 200 },
    )),
    spawn: vi.fn(() => new FakeChild()),
    ...overrides,
  })
  activeHosts.push(host)
  return host
}

describe('Company Host configuration', () => {
  it('uses the company data root and no inherited credential values', () => {
    const dataRoot = 'C:\\profile\\dsh-company'
    const resolved = resolveHostConfig({
      pythonPath: 'python.exe',
      serviceDirectory: 'C:/company-service',
      dataRoot,
    })

    expect(resolved.environment.DSH_COMPANY_DATA_ROOT).toBe(dataRoot)
    expect(resolved.environment).not.toHaveProperty('DEEPSEEK_API_KEY')
  })

  it('selects fixed child inputs without enumerating ambient credential names', () => {
    const ambient = new Proxy({ PATH: 'C:/Python' } as NodeJS.ProcessEnv, {
      ownKeys() {
        throw new Error('ambient environment must not be enumerated')
      },
      get(target, property, receiver) {
        if (property === 'DEEPSEEK_API_KEY') throw new Error('credential must not be read')
        return Reflect.get(target, property, receiver) as unknown
      },
    })

    expect(selectChildEnvironment(ambient, { DSH_COMPANY_DATA_ROOT: 'C:/company' })).toEqual({
      PATH: 'C:/Python',
      DSH_COMPANY_DATA_ROOT: 'C:/company',
    })
  })
})

describe('CompanyHostLifecycle', () => {
  it('starts the company ASGI service on loopback with a shell-free command', async () => {
    const spawn = vi.fn(() => new FakeChild())
    const host = createHost({ spawn, environment: { ACCESS_TOKEN: 'not-forwarded' } })

    const endpoints = await host.start()

    expect(host.command()).toEqual([
      'python.exe', '-m', 'uvicorn', 'dsh_company.asgi:app',
      '--host', '127.0.0.1', '--port', '43123',
    ])
    expect(endpoints).toEqual({ healthUrl: 'http://127.0.0.1:43123/health' })
    expect(spawn).toHaveBeenCalledWith('python.exe', host.command().slice(1), expect.objectContaining({
      shell: false,
      windowsHide: true,
      env: expect.not.objectContaining({ ACCESS_TOKEN: 'not-forwarded' }),
    }))
    expect(host.status).toBe('online')
  })

  it('passes an explicitly supplied credential only to the child environment', async () => {
    const spawn = vi.fn(() => new FakeChild())
    const host = createHost({ spawn, credential: 'synthetic-test-value' })

    await host.start()

    expect(spawn).toHaveBeenCalledWith(expect.any(String), expect.any(Array), expect.objectContaining({
      env: expect.objectContaining({ DEEPSEEK_API_KEY: 'synthetic-test-value' }),
    }))
  })

  it('does not create unconsumed child output pipes', async () => {
    const spawn = vi.fn(() => new FakeChild())
    const host = createHost({ spawn })

    await host.start()

    expect(spawn).toHaveBeenCalledWith(expect.any(String), expect.any(Array), expect.objectContaining({
      stdio: ['ignore', 'ignore', 'ignore'],
    }))
  })

  it('waits for the child to exit before reporting stopped', async () => {
    const child = new FakeChild()
    const host = createHost({ spawn: () => child })
    await host.start()

    await expect(host.dispose()).resolves.toBe('stopped')

    expect(child.kill).toHaveBeenCalledWith('SIGTERM')
    expect(child.exitCode).toBe(0)
    expect(host.status).toBe('stopped')
  })

  it('cleans up a child that never becomes healthy', async () => {
    const child = new FakeChild()
    const host = createHost({
      spawn: () => child,
      fetch: vi.fn(async () => new Response('{}', { status: 503 })),
    })

    await expect(host.start()).rejects.toThrow('did not become healthy')

    expect(child.kill).toHaveBeenCalledWith('SIGTERM')
    expect(host.status).toBe('stopped')
  })

  it('does not publish online when the child exits with a healthy response in flight', async () => {
    const child = new FakeChild()
    const host = createHost({
      spawn: () => child,
      fetch: vi.fn(async () => {
        child.exit(1)
        return new Response(
          JSON.stringify({ status: 'ok', service: 'dsh-company' }),
          { status: 200 },
        )
      }),
    })

    await expect(host.start()).rejects.toThrow('did not become healthy')

    expect(host.status).toBe('stopped')
  })
})

describe('loopback port allocation', () => {
  it('releases the selected port before returning it', async () => {
    const port = await reserveLoopbackPort()
    const server = createServer()
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject)
      server.listen({ host: '127.0.0.1', port }, resolve)
    })
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
  })
})

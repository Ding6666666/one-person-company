import type {
  CompanyConnectionState,
  CompanyRemoteNamespace,
  RemoteResult,
} from '../remote-contract.js'
import { createLoopbackTransport, type LoopbackTransport } from '../remote.js'

export interface ManagedLifecycle {
  status: string
  start(): Promise<{ healthUrl: string }>
  dispose(): Promise<unknown>
}

export interface CompanyPluginOptions {
  readonly resolveCredential?: () => Promise<string | undefined>
  readonly createLifecycle: (credential: string | undefined) => ManagedLifecycle
}

export class CompanyPluginService implements CompanyRemoteNamespace {
  private lifecycle: ManagedLifecycle | undefined
  private transport: LoopbackTransport | undefined
  private startPromise: Promise<RemoteResult<CompanyConnectionState>> | undefined
  private invalidationPromise: Promise<void> | undefined
  private activeRequests = 0
  private readonly requestDrainWaiters = new Set<() => void>()
  private disposed = false

  constructor(private readonly options: CompanyPluginOptions) {}

  connection(): Promise<RemoteResult<CompanyConnectionState>> {
    if (this.disposed) return Promise.resolve(this.unavailable())
    if (this.invalidationPromise !== undefined) return this.connectAfterInvalidation()
    if (this.transport !== undefined && this.lifecycle?.status === 'online') {
      return Promise.resolve({ status: 200, body: { status: 'online' } })
    }
    if (this.startPromise !== undefined) return this.startPromise
    const attempt = this.startFreshLifecycle()
    this.startPromise = attempt
    void attempt.finally(() => {
      if (this.startPromise === attempt) this.startPromise = undefined
    })
    return attempt
  }

  async request(input: Parameters<CompanyRemoteNamespace['request']>[0]): Promise<RemoteResult<unknown>> {
    if (this.transport === undefined || this.lifecycle?.status !== 'online') {
      const connected = await this.connection()
      if (connected.body.status !== 'online' || this.transport === undefined) return connected
    }
    const transport = this.transport
    this.activeRequests += 1
    try {
      return await transport.request(input)
    } finally {
      this.activeRequests -= 1
      if (this.activeRequests === 0) {
        for (const resolve of this.requestDrainWaiters) resolve()
        this.requestDrainWaiters.clear()
      }
    }
  }

  credentialUpdated(): Promise<void> {
    if (this.disposed) return Promise.resolve()
    this.transport = undefined
    if (this.invalidationPromise !== undefined) return this.invalidationPromise
    const attempt = this.retireLifecycle()
    this.invalidationPromise = attempt
    void attempt.then(
      () => { if (this.invalidationPromise === attempt) this.invalidationPromise = undefined },
      () => { if (this.invalidationPromise === attempt) this.invalidationPromise = undefined },
    )
    return attempt
  }

  async dispose(): Promise<void> {
    this.disposed = true
    this.transport = undefined
    await this.invalidationPromise?.catch(() => undefined)
    await this.startPromise
    await this.waitForRequestDrain()
    await this.stopLifecycle()
  }

  private async connectAfterInvalidation(): Promise<RemoteResult<CompanyConnectionState>> {
    try {
      await this.invalidationPromise
    } catch {
      return this.unavailable()
    }
    return this.connection()
  }

  private async retireLifecycle(): Promise<void> {
    await this.startPromise
    await this.waitForRequestDrain()
    await this.stopLifecycle()
  }

  private waitForRequestDrain(): Promise<void> {
    if (this.activeRequests === 0) return Promise.resolve()
    return new Promise(resolve => this.requestDrainWaiters.add(resolve))
  }

  private async startFreshLifecycle(): Promise<RemoteResult<CompanyConnectionState>> {
    if (this.lifecycle !== undefined) {
      try {
        await this.stopLifecycle()
      } catch {
        return this.unavailable()
      }
    }
    return this.startLifecycle()
  }

  private async startLifecycle(): Promise<RemoteResult<CompanyConnectionState>> {
    let lifecycle: ManagedLifecycle | undefined
    try {
      const credential = await this.options.resolveCredential?.()
      if (this.disposed) return this.unavailable()
      lifecycle = this.options.createLifecycle(credential)
      this.lifecycle = lifecycle
      const endpoints = await lifecycle.start()
      if (this.disposed) {
        await lifecycle.dispose()
        return this.unavailable()
      }
      this.transport = createLoopbackTransport({ baseUrl: endpoints.healthUrl.replace(/\/health$/u, '') })
      return { status: 200, body: { status: 'online' } }
    } catch {
      if (lifecycle !== undefined) await lifecycle.dispose().catch(() => undefined)
      if (this.lifecycle === lifecycle) this.lifecycle = undefined
      return this.unavailable()
    }
  }

  private async stopLifecycle(): Promise<void> {
    this.transport = undefined
    const lifecycle = this.lifecycle
    if (lifecycle !== undefined) {
      await lifecycle.dispose()
      if (this.lifecycle === lifecycle) this.lifecycle = undefined
    }
  }

  private unavailable(): RemoteResult<CompanyConnectionState> {
    return {
      status: 503,
      body: { status: 'offline', code: 'COMPANY_SERVICE_UNAVAILABLE' },
    }
  }
}

import { spawn as nodeSpawn } from 'node:child_process'
import { createServer } from 'node:net'

const SAFE_ENVIRONMENT_NAMES = [
  'APPDATA',
  'COMSPEC',
  'HOME',
  'LOCALAPPDATA',
  'PATH',
  'PATHEXT',
  'SYSTEMROOT',
  'TEMP',
  'TMP',
  'WINDIR',
] as const

const COMPANY_ENVIRONMENT_NAMES = [
  'DSH_COMPANY_DATA_ROOT',
  'DSH_COMPANY_SESSION_ROOT',
  'DSH_RUNTIME_MODE',
  'UV_PROJECT_ENVIRONMENT',
] as const

export type HostStatus = 'stopped' | 'starting' | 'online' | 'stopping' | 'stop_failed'

export interface ChildProcessLike {
  readonly pid?: number | undefined
  readonly exitCode: number | null
  once(event: 'exit', listener: (code: number | null, signal: NodeJS.Signals | null) => void): unknown
  once(event: 'error', listener: (error: Error) => void): unknown
  kill(signal: NodeJS.Signals): boolean
}

export interface SpawnOptions {
  readonly cwd: string
  readonly env: NodeJS.ProcessEnv
  readonly shell: false
  readonly stdio: ['ignore', 'ignore', 'ignore']
  readonly windowsHide: true
}

export type ProcessSpawner = (
  command: string,
  args: readonly string[],
  options: SpawnOptions,
) => ChildProcessLike

export interface HostEndpoints {
  readonly healthUrl: string
}

export interface CompanyHostLifecycleOptions {
  readonly executable: string
  readonly executableArguments: readonly string[]
  readonly serviceDirectory: string
  readonly startupTimeoutMs?: number
  readonly pollIntervalMs?: number
  readonly shutdownTimeoutMs?: number
  readonly environment?: NodeJS.ProcessEnv
  readonly credential?: string
  readonly spawn?: ProcessSpawner
  readonly fetch?: typeof fetch
  readonly reservePort?: () => Promise<number>
  readonly delay?: (milliseconds: number) => Promise<void>
  readonly prepareRuntime?: () => Promise<void>
}

function delay(milliseconds: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, milliseconds))
}

export function selectChildEnvironment(
  ambient: NodeJS.ProcessEnv,
  configured: NodeJS.ProcessEnv,
): NodeJS.ProcessEnv {
  const selected: NodeJS.ProcessEnv = {}
  for (const name of [...SAFE_ENVIRONMENT_NAMES, ...COMPANY_ENVIRONMENT_NAMES]) {
    const value = configured[name] ?? ambient[name]
    if (value !== undefined) selected[name] = value
  }
  return selected
}

export function buildChildEnvironment(
  source: NodeJS.ProcessEnv,
  credential?: string,
): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {
    PYTHONDONTWRITEBYTECODE: '1',
    PYTHONUNBUFFERED: '1',
  }
  for (const name of SAFE_ENVIRONMENT_NAMES) {
    if (source[name] !== undefined) environment[name] = source[name]
  }
  for (const name of COMPANY_ENVIRONMENT_NAMES) {
    if (source[name] !== undefined) environment[name] = source[name]
  }
  if (credential !== undefined && credential.length > 0) {
    environment.DEEPSEEK_API_KEY = credential
  }
  return environment
}

export async function reserveLoopbackPort(): Promise<number> {
  const server = createServer()
  return new Promise<number>((resolve, reject) => {
    server.once('error', reject)
    server.listen({ host: '127.0.0.1', port: 0 }, () => {
      const address = server.address()
      if (address === null || typeof address === 'string') {
        server.close(() => reject(new Error('Loopback server did not provide a numeric port.')))
        return
      }
      server.close(error => error === undefined ? resolve(address.port) : reject(error))
    })
  })
}

export class CompanyHostLifecycle {
  private readonly sourceEnvironment: NodeJS.ProcessEnv
  private readonly startupTimeoutMs: number
  private readonly pollIntervalMs: number
  private readonly shutdownTimeoutMs: number
  private readonly processSpawner: ProcessSpawner
  private readonly request: typeof fetch
  private readonly allocatePort: () => Promise<number>
  private readonly wait: (milliseconds: number) => Promise<void>
  private child: ChildProcessLike | undefined
  private exitPromise: Promise<void> | undefined
  private assignedPort: number | undefined
  private spawnFailed = false

  status: HostStatus = 'stopped'

  constructor(private readonly options: CompanyHostLifecycleOptions) {
    this.sourceEnvironment = selectChildEnvironment(process.env, options.environment ?? {})
    this.startupTimeoutMs = options.startupTimeoutMs ?? 5_000
    this.pollIntervalMs = options.pollIntervalMs ?? 100
    this.shutdownTimeoutMs = options.shutdownTimeoutMs ?? 2_000
    this.processSpawner = options.spawn ?? ((command, args, spawnOptions) => nodeSpawn(command, args, spawnOptions))
    this.request = options.fetch ?? fetch
    this.allocatePort = options.reservePort ?? reserveLoopbackPort
    this.wait = options.delay ?? delay
  }

  command(): readonly string[] {
    if (this.assignedPort === undefined) throw new Error('Company Host port is not assigned.')
    return [
      this.options.executable,
      ...this.options.executableArguments,
      '-m',
      'uvicorn',
      'dsh_company.asgi:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(this.assignedPort),
    ]
  }

  async start(): Promise<HostEndpoints> {
    if (this.status !== 'stopped') throw new Error('Company Host lifecycle is not stopped.')
    this.status = 'starting'
    this.spawnFailed = false
    try {
      this.assignedPort = await this.allocatePort()
      await this.options.prepareRuntime?.()
      const command = this.command()
      this.child = this.processSpawner(command[0]!, command.slice(1), {
        cwd: this.options.serviceDirectory,
        env: buildChildEnvironment(this.sourceEnvironment, this.options.credential),
        shell: false,
        stdio: ['ignore', 'ignore', 'ignore'],
        windowsHide: true,
      })
      this.attachChild(this.child)
      const endpoints = { healthUrl: `http://127.0.0.1:${this.assignedPort}/health` }
      await this.waitForHealth(endpoints.healthUrl)
      if (this.spawnFailed || this.child.exitCode !== null) {
        throw new Error('Company service exited during startup.')
      }
      this.status = 'online'
      return endpoints
    } catch {
      await this.stopProcess().catch(() => undefined)
      this.status = 'stopped'
      throw new Error('Python company service did not become healthy.')
    }
  }

  async dispose(): Promise<'stopped'> {
    if (this.status === 'stopped' && (this.child === undefined || this.child.exitCode !== null)) {
      return 'stopped'
    }
    this.status = 'stopping'
    try {
      await this.stopProcess()
      this.status = 'stopped'
      return 'stopped'
    } catch (error) {
      this.status = 'stop_failed'
      throw error
    }
  }

  private attachChild(child: ChildProcessLike): void {
    this.exitPromise = new Promise(resolve => {
      child.once('exit', () => {
        if (this.status === 'online') this.status = 'stopped'
        resolve()
      })
      child.once('error', () => {
        this.spawnFailed = true
        resolve()
      })
    })
  }

  private async waitForHealth(healthUrl: string): Promise<void> {
    const deadline = Date.now() + this.startupTimeoutMs
    while (Date.now() < deadline) {
      if (this.spawnFailed || this.child?.exitCode !== null) break
      try {
        const response = await this.request(healthUrl, { signal: AbortSignal.timeout(250) })
        const health = await response.json() as { status?: unknown; service?: unknown }
        if (
          response.ok
          && health.status === 'ok'
          && health.service === 'dsh-company'
          && !this.spawnFailed
          && this.child?.exitCode === null
        ) return
      } catch {
        // The child may not have opened its loopback socket yet.
      }
      await this.wait(this.pollIntervalMs)
    }
    throw new Error('Health check timed out.')
  }

  private async stopProcess(): Promise<void> {
    const child = this.child
    if (child === undefined || child.exitCode !== null) return
    child.kill('SIGTERM')
    try {
      await this.waitForExit()
    } catch {
      child.kill('SIGKILL')
      try {
        await this.waitForExit()
      } catch {
        throw new Error('Python company service did not stop.')
      }
    }
  }

  private async waitForExit(): Promise<void> {
    if (this.exitPromise === undefined) return
    await Promise.race([
      this.exitPromise,
      this.wait(this.shutdownTimeoutMs).then(() => {
        throw new Error('Shutdown timed out.')
      }),
    ])
  }
}

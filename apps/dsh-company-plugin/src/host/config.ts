import { resolve } from 'node:path'

export interface Config {
  readonly pythonPath?: string
  readonly serviceDirectory?: string
  readonly dataRoot?: string
  readonly startupTimeoutSeconds?: number
  readonly shutdownTimeoutSeconds?: number
}

export interface ResolvedHostConfig {
  readonly executable: string
  readonly executableArguments: readonly string[]
  readonly serviceDirectory: string
  readonly dataRoot: string
  readonly runtimeArchive: string
  readonly runtimeDirectory: string
  readonly startupTimeoutSeconds: number
  readonly shutdownTimeoutSeconds: number
  readonly environment: NodeJS.ProcessEnv
}

function required(value: string, name: string): string {
  if (value.trim().length === 0) throw new TypeError(`${name} must not be blank`)
  return value
}

function optional(value: string | undefined, name: string): string | undefined {
  return value === undefined ? undefined : required(value, name)
}

export function resolveHostConfig(config: Config, packageRoot: string): ResolvedHostConfig {
  const explicitPython = optional(config.pythonPath, 'pythonPath')
  const dataRoot = resolve(
    optional(config.dataRoot, 'dataRoot') ?? resolve(process.cwd(), 'dsh-company-data'),
  )
  return {
    executable: explicitPython ?? 'uv',
    executableArguments: explicitPython === undefined
      ? ['run', '--frozen', '--no-dev', '--project', resolve(packageRoot), 'python']
      : [],
    serviceDirectory: resolve(
      optional(config.serviceDirectory, 'serviceDirectory')
      ?? resolve(packageRoot, 'apps/company-service'),
    ),
    dataRoot,
    runtimeArchive: resolve(packageRoot, 'artifacts/dsh-python-node-runtime.tgz'),
    runtimeDirectory: resolve(
      packageRoot,
      'vendor/deepseek-harness/python/sdk-runtime/src/deepseek_harness_runtime/runtime/node',
    ),
    startupTimeoutSeconds: config.startupTimeoutSeconds ?? 30,
    shutdownTimeoutSeconds: config.shutdownTimeoutSeconds ?? 10,
    environment: {
      DSH_COMPANY_DATA_ROOT: dataRoot,
      DSH_COMPANY_SESSION_ROOT: resolve(dataRoot, 'sessions'),
      DSH_RUNTIME_MODE: 'node',
      UV_PROJECT_ENVIRONMENT: resolve(dataRoot, 'python-environment'),
    },
  }
}

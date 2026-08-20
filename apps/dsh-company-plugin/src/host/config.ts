import { resolve } from 'node:path'

export interface Config {
  readonly pythonPath: string
  readonly serviceDirectory: string
  readonly dataRoot: string
  readonly startupTimeoutSeconds?: number
  readonly shutdownTimeoutSeconds?: number
}

export interface ResolvedHostConfig {
  readonly pythonPath: string
  readonly serviceDirectory: string
  readonly dataRoot: string
  readonly startupTimeoutSeconds: number
  readonly shutdownTimeoutSeconds: number
  readonly environment: NodeJS.ProcessEnv
}

function required(value: string, name: string): string {
  if (value.trim().length === 0) throw new TypeError(`${name} must not be blank`)
  return value
}

export function resolveHostConfig(config: Config): ResolvedHostConfig {
  const dataRoot = resolve(required(config.dataRoot, 'dataRoot'))
  return {
    pythonPath: required(config.pythonPath, 'pythonPath'),
    serviceDirectory: resolve(required(config.serviceDirectory, 'serviceDirectory')),
    dataRoot,
    startupTimeoutSeconds: config.startupTimeoutSeconds ?? 30,
    shutdownTimeoutSeconds: config.shutdownTimeoutSeconds ?? 10,
    environment: {
      DSH_COMPANY_DATA_ROOT: dataRoot,
      DSH_COMPANY_SESSION_ROOT: resolve(dataRoot, 'sessions'),
    },
  }
}

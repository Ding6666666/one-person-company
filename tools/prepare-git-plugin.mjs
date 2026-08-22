import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { delimiter, join, resolve } from 'node:path'

const commands = [
  ['git', 'submodule', 'update', '--init', '--recursive'],
  [
    'pnpm', '--dir', 'vendor/deepseek-harness', 'install', '--frozen-lockfile',
  ],
  [
    'pnpm', '--dir', 'vendor/deepseek-harness',
    '--config.verify-deps-before-run=warn', 'run', 'build:lib',
  ],
  [
    'pnpm', '--config.verify-deps-before-run=warn',
    '--filter', '@dsh/company-plugin-build', 'build',
  ],
  [
    'pnpm', '--dir', 'vendor/deepseek-harness',
    '--config.verify-deps-before-run=warn', 'run', 'build:python-runtime',
    '--node-only', '--skip-build',
  ],
  [
    'node', 'tools/runtime-archive.mjs', '--create',
    'vendor/deepseek-harness/python/sdk-runtime/src/deepseek_harness_runtime/runtime/node',
    'artifacts/dsh-python-node-runtime.tgz',
  ],
]

function resolvePnpmInvocation() {
  if (process.platform !== 'win32') {
    return { executable: 'pnpm', arguments: [] }
  }

  const npmExecPath = process.env.npm_execpath
  if (npmExecPath !== undefined && existsSync(npmExecPath)) {
    return { executable: process.execPath, arguments: [npmExecPath] }
  }

  for (const directory of (process.env.PATH ?? '').split(delimiter)) {
    const candidates = [
      join(directory, 'node_modules', 'pnpm', 'bin', 'pnpm.mjs'),
      resolve(directory, '..', 'pnpm', 'bin', 'pnpm.mjs'),
    ]
    for (const candidate of candidates) {
      if (existsSync(candidate)) {
        return { executable: process.execPath, arguments: [candidate] }
      }
    }
  }
  throw new Error('the pnpm JavaScript entry point was not found on PATH')
}

function run() {
  const pnpm = resolvePnpmInvocation()
  const environment = { ...process.env, CI: 'true' }
  for (const [command, ...arguments_] of commands) {
    const invoked = command === 'node'
      ? process.execPath
      : command === 'pnpm'
        ? pnpm.executable
        : command
    const prefix = command === 'pnpm' ? pnpm.arguments : []
    const result = spawnSync(invoked, [...prefix, ...arguments_], {
      stdio: 'inherit',
      shell: false,
      env: environment,
    })
    if (result.error !== undefined) throw result.error
    if (result.status !== 0) process.exit(result.status ?? 1)
  }
}

if (process.argv[2] === '--describe') {
  process.stdout.write(`${JSON.stringify(commands)}\n`)
} else if (process.argv[2] === '--resolve-pnpm') {
  process.stdout.write(`${JSON.stringify(resolvePnpmInvocation())}\n`)
} else {
  run()
}

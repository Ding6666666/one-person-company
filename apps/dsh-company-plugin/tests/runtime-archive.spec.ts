import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'
import * as tar from 'tar'

import { ensurePackagedRuntime } from '../src/host/runtime.js'

describe('packaged DSH Python runtime', () => {
  it('extracts the archived node dependency closure when absent', async () => {
    const root = await mkdtemp(join(tmpdir(), 'dsh-company-runtime-'))
    try {
      const sourceRoot = join(root, 'source')
      const nested = join(sourceRoot, 'node', 'node_modules', '@fixture', 'runtime')
      await mkdir(nested, { recursive: true })
      await writeFile(join(sourceRoot, 'node', 'package.json'), '{"name":"fixture"}\n')
      await writeFile(join(nested, 'index.js'), 'export const ready = true\n')
      const carrier = join(
        sourceRoot,
        'node',
        'node_modules',
        '@deepseek-ai',
        'dsh-sdk-jsonrpc-demo',
        'lib',
      )
      await mkdir(carrier, { recursive: true })
      await writeFile(join(carrier, 'packaged-bin.js'), 'export {}\n')
      const archive = join(root, 'runtime.tgz')
      await tar.c({ cwd: sourceRoot, file: archive, gzip: true }, ['node'])
      const destination = join(root, 'installed', 'node')
      await mkdir(destination, { recursive: true })
      await writeFile(join(destination, 'package.json'), '{"name":"source-only"}\n')

      await ensurePackagedRuntime(archive, destination)

      await expect(readFile(
        join(destination, 'node_modules', '@fixture', 'runtime', 'index.js'),
        'utf8',
      )).resolves.toBe('export const ready = true\n')
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  it('uses an existing staged runtime without requiring an archive', async () => {
    const root = await mkdtemp(join(tmpdir(), 'dsh-company-runtime-'))
    try {
      const destination = join(root, 'node')
      const carrier = join(
        destination,
        'node_modules',
        '@deepseek-ai',
        'dsh-sdk-jsonrpc-demo',
        'lib',
      )
      await mkdir(carrier, { recursive: true })
      await writeFile(join(destination, 'package.json'), '{"name":"existing"}\n')
      await writeFile(join(carrier, 'packaged-bin.js'), 'export {}\n')

      await expect(ensurePackagedRuntime(join(root, 'missing.tgz'), destination)).resolves.toBeUndefined()
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })
})

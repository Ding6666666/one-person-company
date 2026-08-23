import { readFile } from 'node:fs/promises'

import { describe, expect, it } from 'vitest'

describe('DSH Company plugin bundle', () => {
  it('publishes the repository root as the DSH bundle', async () => {
    const root = JSON.parse(await readFile(new URL('../../../package.json', import.meta.url), 'utf8'))
    const patch = await readFile(new URL('../../../cordis.patch.yml', import.meta.url), 'utf8')

    expect(root.name).toBe('@dsh/company-plugin')
    expect(root.private).toBe(false)
    expect(root.exports['.'].default).toBe('./apps/dsh-company-plugin/dist/index.mjs')
    expect(root.exports['./client'].default).toBe('./apps/dsh-company-plugin/dist/client.js')
    expect(root.dsh.bundle.patch).toBe('./cordis.patch.yml')
    expect(root.dsh.client.inject).toContain('@deepseek-ai/dsh-client-connection')
    expect(patch).toContain(`name: '${root.name}'`)
  })

  it('declares independent host and client exports', async () => {
    const manifest = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))

    expect(manifest.name).toBe('@dsh/company-plugin-build')
    expect(manifest.exports['.'].default).toBe('./dist/index.mjs')
    expect(manifest.exports['./client'].default).toBe('./dist/client.js')
    expect(manifest.dsh.bundle.patch).toBe('./cordis.patch.yml')
  })

  it('builds a DSH client module-loader bundle', async () => {
    const root = JSON.parse(await readFile(new URL('../../../package.json', import.meta.url), 'utf8'))
    const bundle = await readFile(new URL('../dist/client.js', import.meta.url), 'utf8')

    expect(bundle).toContain('window.__ModuleLoader__.load')
    expect(bundle).toContain(`id: "${root.name}"`)
    expect(bundle).toContain('data:image/png;base64,')
    expect(bundle).not.toContain('../assets/employee-avatars')
  })
})

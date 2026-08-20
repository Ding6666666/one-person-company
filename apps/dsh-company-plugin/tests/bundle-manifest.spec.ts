import { readFile } from 'node:fs/promises'

import { describe, expect, it } from 'vitest'

describe('DSH Company plugin bundle', () => {
  it('declares independent host and client exports', async () => {
    const manifest = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))

    expect(manifest.name).toBe('@dsh/company-plugin')
    expect(manifest.exports['.'].default).toBe('./dist/index.mjs')
    expect(manifest.exports['./client'].default).toBe('./dist/client.js')
    expect(manifest.dsh.bundle.patch).toBe('./cordis.patch.yml')
  })

  it('builds a DSH client module-loader bundle', async () => {
    const bundle = await readFile(new URL('../dist/client.js', import.meta.url), 'utf8')

    expect(bundle).toContain('window.__ModuleLoader__.load')
    expect(bundle).toContain('@dsh/company-plugin')
  })
})

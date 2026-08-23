import { describe, expect, it, vi } from 'vitest'

import { apply, createCompanyCredentials, inject } from '../src/client/index.js'

describe('DSH Company client injection contract', () => {
  it('adapts only the write-only DeepSeek credential reference', async () => {
    const face = {
      describe: vi.fn(async () => ({
        result: {
          ok: true,
          value: {
            credentials: {
              DEEPSEEK_API_KEY: { configured: true, source: 'file', writable: true },
            },
          },
        },
      })),
      set: vi.fn(async () => ({ result: { ok: true, value: {} } })),
      unset: vi.fn(async () => ({ result: { ok: true, value: {} } })),
    }
    const credentials = createCompanyCredentials(face as never)

    await expect(credentials.describe()).resolves.toEqual({
      configured: true,
      source: 'file',
      writable: true,
    })
    await credentials.set('synthetic-key')
    await credentials.unset()

    expect(face.describe).toHaveBeenCalledWith({ refs: ['DEEPSEEK_API_KEY'] })
    expect(face.set).toHaveBeenCalledWith({
      ref: 'DEEPSEEK_API_KEY',
      value: 'synthetic-key',
    })
    expect(face.unset).toHaveBeenCalledWith({ ref: 'DEEPSEEK_API_KEY' })
  })

  it('mounts and resolves its own remote namespace without a circular inject', async () => {
    expect(inject).toEqual(['slots', 'remote', 'locale', 'connection'])

    let mounted = false
    const unmount = vi.fn(async () => {})
    const carrier = {
      connection: vi.fn(),
      request: vi.fn(),
    }
    const connection = { api: { llm: { models: vi.fn(async () => ({ result: { ok: true, value: { groups: [], failures: [] } } })) } } }
    const get = vi.fn((name: string) => {
      expect(mounted).toBe(true)
      if (name === 'remote.company') return carrier
      if (name === 'connection') return connection
      throw new Error(`unexpected service: ${name}`)
    })
    const remote = {
      $mount: vi.fn(async () => {
        mounted = true
        return unmount
      }),
      get company(): never {
        throw new Error('cannot get property "remote.company" without inject')
      },
    }
    const disposeLocale = vi.fn()
    const disposeLauncher = vi.fn()
    const disposeSurface = vi.fn()
    const ctx = {
      get,
      locale: { register: vi.fn(() => disposeLocale) },
      remote,
      slots: {
        inject: vi.fn()
          .mockReturnValueOnce(disposeLauncher)
          .mockReturnValueOnce(disposeSurface),
      },
    }

    const dispose = await apply(ctx as never)

    expect(get).toHaveBeenCalledTimes(2)
    await dispose()
    expect(disposeSurface).toHaveBeenCalledOnce()
    expect(disposeLauncher).toHaveBeenCalledOnce()
    expect(unmount).toHaveBeenCalledOnce()
    expect(disposeLocale).toHaveBeenCalledOnce()
  })
})

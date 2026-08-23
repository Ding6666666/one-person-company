import { describe, expect, it, vi } from 'vitest'

import { CompanyPluginClient, CompanyPluginError } from '../src/index.js'
import type { components } from '../src/generated/openapi.js'

describe('CompanyPluginClient', () => {
  it('publishes the generated company chat collection', () => {
    const collection: components['schemas']['ChatMessageCollection'] = { messages: [] }

    expect(collection.messages).toEqual([])
  })
  it('calls only the public business plugin and template endpoints', async () => {
    const request = vi.fn(async (input: { method: string, path: string, body?: unknown }) => ({
      status: input.method === 'POST' ? 201 : 200,
      body: input.body ?? [],
    }))
    const client = new CompanyPluginClient({ request })
    const manifest = {
      plugin_id: 'content-studio',
      version: '0.1.0',
      display_name: 'Content Studio',
      capability_actions: [],
      templates: [],
    }

    await client.register(manifest)
    await client.list()
    await client.templates('content-studio')
    await client.instantiate('ws-1', 'content-studio', 'campaign', {
      command_id: 'campaign-1',
      employee_assignments: { author: 'emp-1' },
    })

    expect(request.mock.calls.map(([input]) => [input.method, input.path])).toEqual([
      ['POST', '/business-plugins/register'],
      ['GET', '/business-plugins'],
      ['GET', '/business-plugins/content-studio/templates'],
      ['POST', '/workspaces/ws-1/templates/content-studio/campaign/instantiate'],
    ])
  })

  it('surfaces non-success responses without importing Core internals', async () => {
    const client = new CompanyPluginClient({
      request: async () => ({ status: 409, body: { error: { code: 'version_conflict' } } }),
    })

    await expect(client.list()).rejects.toEqual(
      expect.objectContaining<Partial<CompanyPluginError>>({ status: 409 }),
    )
  })
})

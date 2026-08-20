import type { ClientContext } from '@deepseek-ai/dsh-client-runtime/client'

export const inject: readonly string[] = []

export async function apply(_ctx: ClientContext): Promise<() => Promise<void>> {
  return async () => {}
}

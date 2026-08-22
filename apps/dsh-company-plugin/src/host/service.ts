import { fileURLToPath } from 'node:url'

import type { Context } from '@deepseek-ai/cordis'
import { credentialRef } from '@deepseek-ai/dsh-credentials'
import { Remote, TypertRemoteService } from '@deepseek-ai/dsh-typert-protocol'

import type { Config } from './config.js'
import { resolveHostConfig } from './config.js'
import { CompanyHostLifecycle } from './lifecycle.js'
import { CompanyPluginService } from './plugin.js'
import { ensurePackagedRuntime } from './runtime.js'

const CREDENTIAL_REF = credentialRef('DEEPSEEK_API_KEY')
const PACKAGE_ROOT = fileURLToPath(new URL('../../../', import.meta.url))

declare module '@deepseek-ai/cordis' {
  interface Context {
    company: CompanyHostService
  }

}

export class CompanyHostService extends TypertRemoteService {
  static inject = ['credentials']

  private readonly product: CompanyPluginService

  constructor(ctx: Context, config: Config) {
    super(ctx, 'company')
    const resolved = resolveHostConfig(config, PACKAGE_ROOT)
    this.product = new CompanyPluginService({
      resolveCredential: async () => (await ctx.credentials.resolve(CREDENTIAL_REF))?.value,
      createLifecycle: credential => new CompanyHostLifecycle({
        executable: resolved.executable,
        executableArguments: resolved.executableArguments,
        serviceDirectory: resolved.serviceDirectory,
        startupTimeoutMs: resolved.startupTimeoutSeconds * 1_000,
        shutdownTimeoutMs: resolved.shutdownTimeoutSeconds * 1_000,
        environment: resolved.environment,
        prepareRuntime: () => ensurePackagedRuntime(
          resolved.runtimeArchive,
          resolved.runtimeDirectory,
        ),
        ...(credential === undefined ? {} : { credential }),
      }),
    })
    ctx.on('credentials/updated', ref => {
      if (ref === CREDENTIAL_REF) return this.product.credentialUpdated()
    })
    ctx.effect(() => () => this.product.dispose(), 'dsh-company: dispose company service')
  }

  @Remote
  connection() {
    return this.product.connection()
  }

  @Remote
  request(input: Parameters<CompanyPluginService['request']>[0]) {
    return this.product.request(input)
  }
}

export default CompanyHostService

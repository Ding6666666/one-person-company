import type { ClientContext } from '@deepseek-ai/dsh-client-runtime/client'
import type { ConnectionHandle, ModelCatalogModel, ModelProviderGroup } from '@deepseek-ai/dsh-client-connection/client'
import type {} from '@deepseek-ai/dsh-api-remotes/client'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
import type {} from '@deepseek-ai/dsh-client-ui-sidebar/client'

import { COMPANY_REMOTE, createCompanyRemote } from './api.js'
import { CompanyLauncher } from './CompanyLauncher.js'
import { CompanyOverlayController } from './controller.js'
import { CompanySurfaceSlot } from './CompanySurface.js'
import type { CompanyCredentials, CredentialView } from './CredentialPanel.js'
import { en, NS, zh, type CompanyLocaleKey } from './locales.js'

export { ApiError, COMPANY_REMOTE, createCompanyRemote, ProductApi } from './api.js'
export { CompanyController, CompanyOverlayController } from './controller.js'
export { CompanyLauncher } from './CompanyLauncher.js'
export { CompanySurface } from './CompanySurface.js'
export { CompanyChat } from './CompanyChat.js'
export { CredentialPanel, type CompanyCredentials, type CredentialView } from './CredentialPanel.js'
export { EmployeeDirectory } from './EmployeeDirectory.js'
export { EmployeeForm } from './EmployeeForm.js'
export { CompanyHistory } from './CompanyHistory.js'
export { WorkComposer } from './WorkComposer.js'
export { StrategyComposer } from './StrategyComposer.js'
export { WorkGraphView } from './WorkGraphView.js'
export { BattleView } from './BattleView.js'
export { WorkDetail } from './WorkDetail.js'
export { WorkList } from './WorkList.js'
export { ApprovalInbox } from './ApprovalInbox.js'
export { CapabilityEditor } from './CapabilityEditor.js'
export { DelegationView } from './DelegationView.js'
export { WorkspaceList } from './WorkspaceList.js'
export { en, NS, translate, zh } from './locales.js'

declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface LocaleNamespaceMap {
    'dsh.company': CompanyLocaleKey
  }
}

export const inject = ['slots', 'remote', 'locale', 'connection']

const DEEPSEEK_CREDENTIAL_REF = 'DEEPSEEK_API_KEY'

type CredentialsFace = ConnectionHandle['api']['credentials']

function unwrap<T>(response: Awaited<ReturnType<CredentialsFace['describe']>> | Awaited<ReturnType<CredentialsFace['set']>> | Awaited<ReturnType<CredentialsFace['unset']>>): T {
  if (!response.result.ok) throw new Error(response.result.error.code)
  return response.result.value as T
}

export function createCompanyCredentials(face: CredentialsFace): CompanyCredentials {
  return {
    async describe(): Promise<CredentialView> {
      const value = unwrap<{ credentials: Record<string, CredentialView | undefined> }>(
        await face.describe({ refs: [DEEPSEEK_CREDENTIAL_REF] }),
      )
      return value.credentials[DEEPSEEK_CREDENTIAL_REF] ?? { configured: false, writable: true }
    },
    async set(value: string): Promise<void> {
      unwrap(await face.set({ ref: DEEPSEEK_CREDENTIAL_REF, value }))
    },
    async unset(): Promise<void> {
      unwrap(await face.unset({ ref: DEEPSEEK_CREDENTIAL_REF }))
    },
  }
}

export async function apply(ctx: ClientContext): Promise<() => Promise<void>> {
  const disposeLocale = ctx.locale.register(NS, { zh, en })
  const unmountRemote = await ctx.remote.$mount(COMPANY_REMOTE)
  const remote = createCompanyRemote(ctx.get('remote.company'))
  const connection = ctx.get('connection') as ConnectionHandle
  const credentials = createCompanyCredentials(connection.api.credentials)
  const overlay = new CompanyOverlayController()
  const disposeLauncher = ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register({
    name: 'sidebar.footer.action',
    id: 'dsh-company-launcher',
    order: 45,
    locale: NS,
    inject: () => ({ onOpen: overlay.open }),
  }, CompanyLauncher))
  const disposeSurface = ctx.slots.inject('shell.overlay', () => ctx.slots.register({
    name: 'shell.overlay',
    id: 'dsh-company-surface',
    order: 45,
    locale: NS,
    inject: () => ({
      remote,
      overlay,
      credentials,
      loadModelCatalog: async () => {
        const { result } = await connection.api.llm.models({})
        if (!result.ok) return []
        return result.value.groups.map((group: ModelProviderGroup) => ({
          provider: group.id,
          models: group.models.map((model: ModelCatalogModel) => model.id),
        }))
      },
    }),
  }, CompanySurfaceSlot))

  return async () => {
    disposeSurface()
    disposeLauncher()
    await unmountRemote()
    disposeLocale()
  }
}

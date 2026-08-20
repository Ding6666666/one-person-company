import type { ClientContext } from '@deepseek-ai/dsh-client-runtime/client'
import type {} from '@deepseek-ai/dsh-api-remotes/client'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
import type {} from '@deepseek-ai/dsh-client-ui-sidebar/client'

import { COMPANY_REMOTE, createCompanyRemote } from './api.js'
import { CompanyLauncher } from './CompanyLauncher.js'
import { CompanyOverlayController } from './controller.js'
import { CompanySurfaceSlot } from './CompanySurface.js'
import { en, NS, zh, type CompanyLocaleKey } from './locales.js'

export { ApiError, COMPANY_REMOTE, createCompanyRemote, ProductApi } from './api.js'
export { CompanyController, CompanyOverlayController } from './controller.js'
export { CompanyLauncher } from './CompanyLauncher.js'
export { CompanySurface } from './CompanySurface.js'
export { EmployeeDirectory } from './EmployeeDirectory.js'
export { EmployeeForm } from './EmployeeForm.js'
export { WorkspaceList } from './WorkspaceList.js'
export { en, NS, translate, zh } from './locales.js'

declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface LocaleNamespaceMap {
    'dsh.company': CompanyLocaleKey
  }
}

export const inject = ['slots', 'remote', 'locale']

export async function apply(ctx: ClientContext): Promise<() => Promise<void>> {
  const disposeLocale = ctx.locale.register(NS, { zh, en })
  const unmountRemote = await ctx.remote.$mount(COMPANY_REMOTE)
  const remote = createCompanyRemote(ctx.remote.company)
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
    inject: () => ({ remote, overlay }),
  }, CompanySurfaceSlot))

  return async () => {
    disposeSurface()
    disposeLauncher()
    await unmountRemote()
    disposeLocale()
  }
}

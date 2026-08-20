import { type FormEvent, useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import type { PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
import { z } from 'zod'

import type { CompanyRemoteNamespace } from '../remote-contract.js'
import { ProductApi } from './api.js'
import { CompanyController, CompanyOverlayController, useCompanyController } from './controller.js'
import { EmployeeDirectory } from './EmployeeDirectory.js'
import { EmployeeForm } from './EmployeeForm.js'
import { NS, type CompanyLocale, translate, type Translate } from './locales.js'
import styles from './CompanySurface.module.css'
import { Button, Dialog, Field } from './ui/Primitives.js'
import { WorkspaceList } from './WorkspaceList.js'

const alwaysOpen = (): boolean => true
const neverChanges = (): (() => void) => () => undefined

export interface CompanySurfaceProps {
  readonly remote: Pick<CompanyRemoteNamespace, 'request'>
  readonly locale?: CompanyLocale
  readonly t?: Translate
  readonly overlay?: CompanyOverlayController
}

export function CompanySurface({ remote, locale = 'zh', t: suppliedTranslate, overlay }: CompanySurfaceProps) {
  const controller = useMemo(() => new CompanyController(new ProductApi(remote)), [remote])
  const snapshot = useCompanyController(controller)
  const [workspaceDialog, setWorkspaceDialog] = useState(false)
  const [employeeDialog, setEmployeeDialog] = useState(false)
  const [workspaceName, setWorkspaceName] = useState('')
  const [workspaceError, setWorkspaceError] = useState<string>()
  const t = suppliedTranslate ?? translate(locale)
  const visible = useSyncExternalStore(
    overlay?.subscribe ?? neverChanges,
    overlay?.snapshot ?? alwaysOpen,
    overlay?.snapshot ?? alwaysOpen,
  )

  useEffect(() => { void controller.load() }, [controller])

  const closeWorkspaceDialog = useCallback(() => {
    setWorkspaceDialog(false)
    setWorkspaceName('')
    setWorkspaceError(undefined)
  }, [])
  const closeEmployeeDialog = useCallback(() => setEmployeeDialog(false), [])

  const submitWorkspace = async (event: FormEvent): Promise<void> => {
    event.preventDefault()
    const parsed = z.string().trim().min(1, 'required').max(120, 'tooLong').safeParse(workspaceName)
    if (!parsed.success) {
      setWorkspaceError(t(parsed.error.issues[0]?.message === 'tooLong' ? 'workspaceNameTooLong' : 'nameRequired'))
      return
    }
    const created = await controller.createWorkspace(parsed.data)
    if (created !== undefined) closeWorkspaceDialog()
  }

  if (!visible) return null
  return <section className={styles.overlay} aria-label={t('title')}>
    <header className={styles.header}>
      <h1>{t('title')}</h1>
      {overlay !== undefined && <Button type="button" onClick={overlay.close}>{t('close')}</Button>}
    </header>
    {snapshot.phase === 'loading' && <p role="status">{t('loading')}</p>}
    {snapshot.phase === 'error' && <p role="alert">{snapshot.error}</p>}
    <main className={styles.layout}>
      <WorkspaceList
        workspaces={snapshot.workspaces}
        selectedWorkspaceId={snapshot.selectedWorkspaceId}
        onSelect={workspaceId => { void controller.selectWorkspace(workspaceId) }}
        onCreate={() => setWorkspaceDialog(true)}
        t={t}
      />
      <EmployeeDirectory
        employees={snapshot.employees}
        workspaceSelected={snapshot.selectedWorkspaceId !== undefined}
        onCreate={() => setEmployeeDialog(true)}
        t={t}
      />
    </main>

    {workspaceDialog && <Dialog title={t('createWorkspace')} onClose={closeWorkspaceDialog}>
      <form className={styles.dialogForm} onSubmit={event => { void submitWorkspace(event) }} noValidate>
        <Field label={t('workspaceName')} error={workspaceError}>
          <input maxLength={120} value={workspaceName} onChange={event => setWorkspaceName(event.target.value)} />
        </Field>
        <footer className={styles.actions}>
          <Button type="button" onClick={closeWorkspaceDialog}>{t('cancel')}</Button>
          <Button type="submit" disabled={snapshot.pending}>{t('confirmCreate')}</Button>
        </footer>
      </form>
    </Dialog>}
    {employeeDialog && snapshot.selectedWorkspaceId !== undefined && <Dialog title={t('createEmployee')} onClose={closeEmployeeDialog}>
      <EmployeeForm
        pending={snapshot.pending}
        onCancel={closeEmployeeDialog}
        onSave={async (input) => {
          const created = await controller.createEmployee(input)
          if (created !== undefined) closeEmployeeDialog()
        }}
        t={t}
      />
    </Dialog>}
  </section>
}

export type CompanySurfaceSlotProps = PropsRuntime<'shell.overlay'> & PropsLocale<typeof NS> & {
  readonly remote: CompanyRemoteNamespace
  readonly overlay: CompanyOverlayController
}

export function CompanySurfaceSlot({ remote, overlay, t }: CompanySurfaceSlotProps) {
  return <CompanySurface remote={remote} overlay={overlay} t={t as Translate} />
}

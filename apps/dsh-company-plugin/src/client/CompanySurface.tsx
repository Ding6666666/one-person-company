import { type FormEvent, useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import type { PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
import { z } from 'zod'

import type { CompanyRemoteNamespace } from '../remote-contract.js'
import { ProductApi } from './api.js'
import { CompanyController, CompanyOverlayController, useCompanyController } from './controller.js'
import { CompanyChat } from './CompanyChat.js'
import { CompanyHeader, CompanyMobileNavigation, CompanyNavigation, type CompanyView } from './CompanyWorkbench.js'
import { CredentialPanel, type CompanyCredentials } from './CredentialPanel.js'
import { EmployeeDirectory } from './EmployeeDirectory.js'
import { EmployeeForm } from './EmployeeForm.js'
import { NS, type CompanyLocale, translate, type Translate } from './locales.js'
import styles from './CompanySurface.module.css'
import { Button, Dialog, Field } from './ui/Primitives.js'
import { StrategyComposer } from './StrategyComposer.js'
import { WorkDetail } from './WorkDetail.js'
import { WorkList } from './WorkList.js'

const alwaysOpen = (): boolean => true
const neverChanges = (): (() => void) => () => undefined

export interface CompanySurfaceProps {
  readonly remote: Pick<CompanyRemoteNamespace, 'request'>
  readonly locale?: CompanyLocale
  readonly t?: Translate
  readonly overlay?: CompanyOverlayController
  readonly initialWorkspaceId?: string | undefined
  readonly pollingIntervalMs?: number | undefined
  readonly credentials?: CompanyCredentials | undefined
  readonly loadModelCatalog?: (() => Promise<readonly { readonly provider: string; readonly models: readonly string[] }[]>) | undefined
}

export function CompanySurface({
  remote,
  locale = 'zh',
  t: suppliedTranslate,
  overlay,
  initialWorkspaceId,
  pollingIntervalMs = 1_000,
  loadModelCatalog,
  credentials,
}: CompanySurfaceProps) {
  const api = useMemo(() => new ProductApi(remote), [remote])
  const controller = useMemo(() => new CompanyController(api), [api])
  const snapshot = useCompanyController(controller)
  const [workspaceDialog, setWorkspaceDialog] = useState(false)
  const [employeeDialog, setEmployeeDialog] = useState(false)
  const [workDialog, setWorkDialog] = useState(false)
  const [settingsDialog, setSettingsDialog] = useState(false)
  const [workDetailOpen, setWorkDetailOpen] = useState(false)
  const [view, setView] = useState<CompanyView>('chat')
  const [workspaceName, setWorkspaceName] = useState('')
  const [workspaceError, setWorkspaceError] = useState<string>()
  const [modelOptions, setModelOptions] = useState<readonly string[]>([])
  const t = suppliedTranslate ?? translate(locale)
  const visible = useSyncExternalStore(
    overlay?.subscribe ?? neverChanges,
    overlay?.snapshot ?? alwaysOpen,
    overlay?.snapshot ?? alwaysOpen,
  )

  useEffect(() => { void controller.load(initialWorkspaceId) }, [controller, initialWorkspaceId])
  useEffect(() => {
    if (
      snapshot.selectedWorkId === undefined
      || snapshot.selectedWork === undefined
      || snapshot.selectedWork?.status === 'completed'
      || snapshot.selectedWork?.status === 'failed'
      || snapshot.selectedWork?.status === 'cancelled'
    ) return
    let stopped = false
    let timer: ReturnType<typeof globalThis.setTimeout> | undefined
    const schedule = (): void => {
      timer = globalThis.setTimeout(() => {
        void controller.refreshSelectedWork().then(() => {
          const status = controller.snapshot().selectedWork?.status
          if (!stopped && status !== undefined && status !== 'completed' && status !== 'failed' && status !== 'cancelled') schedule()
        })
      }, pollingIntervalMs)
    }
    schedule()
    return () => {
      stopped = true
      if (timer !== undefined) globalThis.clearTimeout(timer)
    }
  }, [controller, pollingIntervalMs, snapshot.selectedWork?.id, snapshot.selectedWorkId])
  useEffect(() => {
    if (view !== 'chat' || !snapshot.messages.some(message => message.executions.some(execution => execution.status === 'queued' || execution.status === 'running'))) return
    const timer = globalThis.setTimeout(() => { void controller.refreshMessages() }, pollingIntervalMs)
    return () => globalThis.clearTimeout(timer)
  }, [controller, pollingIntervalMs, snapshot.messages, view])

  const closeWorkspaceDialog = useCallback(() => {
    setWorkspaceDialog(false)
    setWorkspaceName('')
    setWorkspaceError(undefined)
  }, [])
  const closeEmployeeDialog = useCallback(() => setEmployeeDialog(false), [])
  const closeWorkDialog = useCallback(() => setWorkDialog(false), [])
  const closeWorkDetail = useCallback(() => setWorkDetailOpen(false), [])

  const showWork = (): void => {
    setView('work')
    void controller.loadWorks()
  }

  const selectView = (nextView: CompanyView): void => {
    if (nextView === 'work') showWork()
    else if (nextView === 'chat') {
      setView('chat')
      if (snapshot.discussionWorkId !== undefined) void controller.closeDiscussion()
      else void controller.refreshMessages()
    } else setView('employees')
  }

  const openEmployeeDialog = (): void => {
    setEmployeeDialog(true)
    void Promise.all([api.getRuntimeOptions(), loadModelCatalog?.() ?? Promise.resolve([])]).then(([runtime, groups]) => {
      const group = groups.find(item => item.provider === runtime.provider)
      setModelOptions([...new Set([runtime.default_model, ...(group?.models ?? [])])])
    }).catch(() => setModelOptions([]))
  }

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
    <CompanyHeader {...(overlay === undefined ? {} : { onClose: overlay.close })} t={t} />
    {snapshot.phase === 'loading' && <p role="status">{t('loading')}</p>}
    {snapshot.phase === 'error' && <p role="alert">{snapshot.error}</p>}
    <div className={styles.layout}>
      <CompanyNavigation
        workspaces={snapshot.workspaces}
        selectedWorkspaceId={snapshot.selectedWorkspaceId}
        view={view}
        onSelectWorkspace={workspaceId => {
          void controller.selectWorkspace(workspaceId).then(() => {
            if (view === 'work') void controller.loadWorks()
          })
        }}
        onCreateWorkspace={() => setWorkspaceDialog(true)}
        onSelectView={selectView}
        {...(credentials === undefined ? {} : { onOpenSettings: () => setSettingsDialog(true) })}
        t={t}
      />
      <main className={styles.content} data-company-page={view}>
        {view === 'chat' && <CompanyChat
          messages={snapshot.messages}
          employees={snapshot.employees}
          workspaceSelected={snapshot.selectedWorkspaceId !== undefined}
          pending={snapshot.pending}
          discussionWorkId={snapshot.discussionWorkId}
          onCloseDiscussion={() => { void controller.closeDiscussion() }}
          onSend={async (body, employeeIds) => { await controller.sendChatMessage(body, employeeIds) }}
          onRetry={async executionId => { await controller.retryChatExecution(executionId) }}
          onOpenWork={async workId => { setView('chat'); await controller.openDiscussion(workId) }}
          onCreateEmployee={openEmployeeDialog}
          t={t}
        />}
        {view === 'employees' && <EmployeeDirectory
          employees={snapshot.employees}
          workspaceSelected={snapshot.selectedWorkspaceId !== undefined}
          onCreate={openEmployeeDialog}
          t={t}
        />}
        {view === 'work' && <div className={styles.workLayout}>
          <WorkList
            works={snapshot.works}
            workspaceSelected={snapshot.selectedWorkspaceId !== undefined}
            selectedWorkId={snapshot.selectedWorkId}
            onSelect={workId => { setWorkDetailOpen(true); void controller.selectWork(workId) }}
            onCreate={() => setWorkDialog(true)}
            t={t}
          />
        </div>}
      </main>
    </div>
    <CompanyMobileNavigation view={view} onSelectView={selectView} t={t} />

    {workDetailOpen && snapshot.selectedWork !== undefined && <Dialog variant="drawer" initialFocus={false} className={styles.workDrawer} title={t('workDetails')} closeLabel={t('close')} onClose={closeWorkDetail}><WorkDetail
      work={snapshot.selectedWork}
      events={snapshot.events}
      pending={snapshot.pending}
      onCancel={() => { void controller.cancelSelectedWork() }}
      governance={{
        api,
        workspaceId: snapshot.selectedWork.workspace_id,
        onWorkUpdated: work => controller.applyAuthoritativeWork(work),
      }}
      employees={snapshot.employees}
      t={t}
    /></Dialog>}

    {settingsDialog && credentials !== undefined && <Dialog title={t('apiSettings')} closeLabel={t('close')} onClose={() => setSettingsDialog(false)}>
      <p>{t('apiSettingsDescription')}</p>
      <CredentialPanel credentials={credentials} t={t} />
    </Dialog>}

    {workspaceDialog && <Dialog title={t('createWorkspace')} closeLabel={t('close')} onClose={closeWorkspaceDialog}>
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
    {employeeDialog && snapshot.selectedWorkspaceId !== undefined && <Dialog className={styles.employeeDialog} title={t('createEmployee')} closeLabel={`${t('close')}${t('createEmployee')}`} onClose={closeEmployeeDialog}>
      <EmployeeForm
        pending={snapshot.pending}
        modelOptions={modelOptions}
        onCancel={closeEmployeeDialog}
        onSave={async (input) => {
          const created = await controller.createEmployee(input)
          if (created !== undefined) {
            closeEmployeeDialog()
            setView('employees')
          }
        }}
        t={t}
      />
    </Dialog>}
    {workDialog && snapshot.selectedWorkspaceId !== undefined && <Dialog className={styles.workDialog} title={t('createWork')} closeLabel={t('close')} onClose={closeWorkDialog}>
      <StrategyComposer
        employees={snapshot.employees}
        pending={snapshot.pending}
        onCancel={closeWorkDialog}
        onStart={async input => {
          const created = await controller.createStrategyWork(input)
          if (created !== undefined) {
            closeWorkDialog()
            setWorkDetailOpen(true)
            setView('chat')
            await controller.openDiscussion(created.id)
          }
        }}
        t={t}
      />
    </Dialog>}
  </section>
}

export type CompanySurfaceSlotProps = PropsRuntime<'shell.overlay'> & PropsLocale<typeof NS> & {
  readonly remote: CompanyRemoteNamespace
  readonly overlay: CompanyOverlayController
  readonly loadModelCatalog?: () => Promise<readonly { readonly provider: string; readonly models: readonly string[] }[]>
  readonly credentials: CompanyCredentials
}

export function CompanySurfaceSlot({ remote, overlay, loadModelCatalog, credentials, t }: CompanySurfaceSlotProps) {
  return <CompanySurface remote={remote} overlay={overlay} loadModelCatalog={loadModelCatalog} credentials={credentials} t={t as Translate} />
}

import { useState } from 'react'

import type { ProductApi, WorkProjection } from './api.js'
import { ApprovalInbox } from './ApprovalInbox.js'
import { CapabilityEditor } from './CapabilityEditor.js'
import { CompanyHistory } from './CompanyHistory.js'
import { DelegationView } from './DelegationView.js'
import type { Translate } from './locales.js'
import styles from './Work.module.css'
import { Button } from './ui/Primitives.js'

const statusKeys: Record<WorkProjection['status'], Parameters<Translate>[0]> = {
  queued: 'statusQueued',
  running: 'statusRunning',
  blocked: 'statusBlocked',
  completed: 'statusCompleted',
  failed: 'statusFailed',
  cancelled: 'statusCancelled',
}

function ArtifactResult({ artifact, t }: {
  readonly artifact: WorkProjection['artifacts'][number]
  readonly t: Translate
}) {
  const [copyState, setCopyState] = useState<'idle' | 'copying' | 'success' | 'error'>('idle')
  const clipboard = navigator.clipboard
  const copy = async (): Promise<void> => {
    setCopyState('copying')
    try {
      await clipboard.writeText(artifact.uri)
      setCopyState('success')
    } catch {
      setCopyState('error')
    }
  }

  return <div>
    <input aria-label={t('resultReference')} readOnly value={artifact.uri} onFocus={event => event.currentTarget.select()} />
    {clipboard?.writeText !== undefined && <Button type="button" disabled={copyState === 'copying'} onClick={() => {
      void copy()
    }}>{t('copyResultReference')}</Button>}
    {copyState === 'success' && <span role="status">{t('copySucceeded')}</span>}
    {copyState === 'error' && <span role="alert">{t('copyFailed')}</span>}
  </div>
}

export function WorkDetail({ work, events, pending, onCancel, governance, t }: {
  readonly work: WorkProjection
  readonly events: Parameters<typeof CompanyHistory>[0]['events']
  readonly pending: boolean
  readonly onCancel: () => void
  readonly governance?: {
    readonly api: ProductApi
    readonly workspaceId: string
    readonly onWorkUpdated: (work: WorkProjection) => void
  }
  readonly t: Translate
}) {
  const [governanceOpen, setGovernanceOpen] = useState(false)
  const cancelRequested = work.execution_links.some(link => link.status === 'cancel_requested')
  const canCancel = work.execution_links.some(link => link.status === 'dispatch_pending' || link.status === 'running')
  const failureCodes = work.nodes.flatMap(node => node.failure_code === null ? [] : [node.failure_code])
  const status = work.status === 'cancelled'
    ? t('statusCancelled')
    : cancelRequested
      ? t('statusCancelRequested')
      : t(statusKeys[work.status])

  return <article className={styles.detail}>
    <header>
      <div><h2>{work.objective}</h2><span className={styles.badge}>{status}</span></div>
      {canCancel && <Button type="button" disabled={pending} onClick={onCancel}>
        {t('requestCancel')}
      </Button>}
    </header>
    {failureCodes.length > 0 && <p>{t('failureReason')}: <code>{failureCodes.join(', ')}</code></p>}
    <section>
      <h3>{t('acceptanceCriteria')}</h3>
      <ul>{work.nodes.flatMap(node => node.acceptance_criteria).map((criterion, index) => <li key={`${index}-${criterion}`}>{criterion}</li>)}</ul>
    </section>
    {work.artifacts.length > 0 && <section className={styles.artifacts}>
      <h3>{t('results')}</h3>
      {work.artifacts.map(artifact => <ArtifactResult key={artifact.id} artifact={artifact} t={t} />)}
    </section>}
    {governance !== undefined && <Button type="button" onClick={() => setGovernanceOpen(value => !value)} aria-expanded={governanceOpen}>
      {t('governance')}
    </Button>}
    {governance !== undefined && governanceOpen && <>
      <CapabilityEditor api={governance.api} workspaceId={governance.workspaceId} t={t} />
      <ApprovalInbox
        api={governance.api}
        workspaceId={governance.workspaceId}
        refreshKey={work.nodes.map(node => `${node.id}:${node.status}:${node.version}`).join('|')}
        onWorkUpdated={governance.onWorkUpdated}
        t={t}
      />
      <DelegationView api={governance.api} work={work} onWorkUpdated={governance.onWorkUpdated} t={t} />
    </>}
    <CompanyHistory events={events} t={t} />
  </article>
}

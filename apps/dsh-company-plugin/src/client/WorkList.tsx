import type { WorkProjection } from './api.js'
import { CompanyEmptyState, CompanyPageHeader, CompanyStats } from './CompanyWorkbench.js'
import type { Translate } from './locales.js'
import styles from './Work.module.css'
import { Button } from './ui/Primitives.js'

export function WorkList({ works, workspaceSelected, selectedWorkId, onSelect, onCreate, t }: {
  readonly works: readonly WorkProjection[]
  readonly workspaceSelected: boolean
  readonly selectedWorkId: string | undefined
  readonly onSelect: (workId: string) => void
  readonly onCreate: () => void
  readonly t: Translate
}) {
  const running = works.filter(work => work.status === 'running').length
  const waiting = works.filter(work => work.status === 'queued' || work.status === 'blocked').length
  const completed = works.filter(work => work.status === 'completed').length
  const statusLabel = (status: WorkProjection['status']): string => t({ queued: 'statusQueued', running: 'statusRunning', blocked: 'statusBlocked', completed: 'statusCompleted', failed: 'statusFailed', cancelled: 'statusCancelled' }[status] as Parameters<Translate>[0])
  return <section className={styles.workList} aria-label={t('workCenter')}>
    <CompanyPageHeader eyebrow={t('workEyebrow')} title={t('workCenter')} description={t('workCenterDescription')} action={<Button type="button" aria-label={t('createWork')} disabled={!workspaceSelected} onClick={onCreate}>＋ {t('createWork')}</Button>} />
    <CompanyStats items={[{ label: t('workTotal'), value: works.length }, { label: t('workRunning'), value: running, tone: 'green' }, { label: t('workWaiting'), value: waiting, tone: 'orange' }, { label: t('workCompleted'), value: completed, tone: 'pink' }]} />
    {!workspaceSelected && <CompanyEmptyState icon="company" title={t('noWorkspace')} description={t('chooseCompanyDescription')} />}
    {workspaceSelected && works.length === 0 && <CompanyEmptyState icon="work" title={t('firstWorkTitle')} description={t('firstWorkDescription')}><Button type="button" onClick={onCreate}>{t('createFirstWork')}</Button></CompanyEmptyState>}
    <ul className={styles.workCards}>
      {works.map(work => <li key={work.id} data-status={work.status}>
        <a
          href={`#work-${encodeURIComponent(work.id)}`}
          aria-label={work.objective}
          aria-current={selectedWorkId === work.id ? 'page' : undefined}
          onClick={(event) => { event.preventDefault(); onSelect(work.id) }}
        ><span className={styles.workCardTop}><strong>{work.objective}</strong><span className={styles.badge}>{t('status')} · {statusLabel(work.status)}</span></span><span className={styles.workMeta}><span>{t('strategy')} · {work.strategy}</span><span>{t('nodesLabel')} · {work.nodes.length}</span></span></a>
      </li>)}
    </ul>
  </section>
}

import type { WorkProjection } from './api.js'
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
  return <section className={styles.workList}>
    <header><Button type="button" disabled={!workspaceSelected} onClick={onCreate}>{t('createWork')}</Button></header>
    {!workspaceSelected && <p>{t('noWorkspace')}</p>}
    {workspaceSelected && works.length === 0 && <p>{t('emptyWorks')}</p>}
    <ul>
      {works.map(work => <li key={work.id}>
        <a
          href={`#work-${encodeURIComponent(work.id)}`}
          aria-current={selectedWorkId === work.id ? 'page' : undefined}
          onClick={(event) => { event.preventDefault(); onSelect(work.id) }}
        >{work.objective}</a>
      </li>)}
    </ul>
  </section>
}

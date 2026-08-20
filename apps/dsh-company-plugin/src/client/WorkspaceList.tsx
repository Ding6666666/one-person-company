import type { Workspace } from './api.js'
import type { Translate } from './locales.js'
import styles from './WorkspaceList.module.css'
import { Button } from './ui/Primitives.js'

export function WorkspaceList({ workspaces, selectedWorkspaceId, onSelect, onCreate, t }: {
  readonly workspaces: readonly Workspace[]
  readonly selectedWorkspaceId: string | undefined
  readonly onSelect: (workspaceId: string) => void
  readonly onCreate: () => void
  readonly t: Translate
}) {
  return <nav className={styles.panel} aria-label={t('title')}>
    <Button type="button" onClick={onCreate}>{t('createWorkspace')}</Button>
    <ul className={styles.list}>
      {workspaces.map(workspace => <li key={workspace.id}>
        <a
          href={`#workspace-${encodeURIComponent(workspace.id)}`}
          aria-current={selectedWorkspaceId === workspace.id ? 'page' : undefined}
          onClick={(event) => {
            event.preventDefault()
            onSelect(workspace.id)
          }}
        >{workspace.name}</a>
      </li>)}
    </ul>
  </nav>
}

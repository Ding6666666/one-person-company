import type { Employee, WorkProjection } from './api.js'
import type { Translate } from './locales.js'
import styles from './Work.module.css'

const statusKey = {
  draft: 'nodeStatusDraft',
  ready: 'nodeStatusReady',
  waiting_approval: 'nodeStatusWaitingApproval',
  running: 'statusRunning',
  blocked: 'statusBlocked',
  completed: 'statusCompleted',
  failed: 'statusFailed',
  cancelled: 'statusCancelled',
} as const

const edgeKey = {
  depends_on: 'edgeDependsOn',
  delegates_to: 'edgeDelegatesTo',
  reviews: 'edgeReviews',
  summarizes: 'edgeSummarizes',
} as const

export function WorkGraphView({ work, employees = [], t }: {
  readonly work: WorkProjection
  readonly employees?: readonly Employee[] | undefined
  readonly t: Translate
}) {
  const names = new Map(employees.map(employee => [employee.id, employee.display_name]))
  const nodes = new Map(work.nodes.map(node => [node.id, node]))
  return <section aria-label={t('workGraph')} className={styles.graph}>
    <h3>{t('workGraph')}</h3>
    <div className={styles.graphNodes}>
      {work.nodes.map(node => <article key={node.id} aria-label={`${node.objective}: ${t(statusKey[node.status])}`} className={styles.graphNode}>
        <h4>{node.objective}</h4>
        <p>{t('assignedEmployee')}: {names.get(node.assigned_employee_id) ?? node.assigned_employee_id}</p>
        <p aria-label={`${t('nodeStatus')}: ${t(statusKey[node.status])}`}>{t('nodeStatus')}: {t(statusKey[node.status])}</p>
        <p>{t('attempts')}: {node.attempt_count ?? 0} / {node.max_attempts ?? 1}</p>
        {node.status === 'waiting_approval' && <p>{t('approvalWaiting')}</p>}
        {node.failure_code !== null && <p>{t('failureReason')}: <code>{node.failure_code}</code></p>}
      </article>)}
    </div>
    {(work.edges ?? []).length > 0 && <section aria-label={t('dependencies')}>
      <h4>{t('dependencies')}</h4>
      <ul>{(work.edges ?? []).map((edge, index) => {
        const from = nodes.get(edge.from_node_id)?.objective ?? edge.from_node_id
        const to = nodes.get(edge.to_node_id)?.objective ?? edge.to_node_id
        return <li key={`${index}-${edge.from_node_id}-${edge.to_node_id}`}>
          {from} {t(edgeKey[edge.kind])} {to}
        </li>
      })}</ul>
    </section>}
  </section>
}

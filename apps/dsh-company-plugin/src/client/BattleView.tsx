import type { Employee, WorkProjection } from './api.js'
import type { Translate } from './locales.js'
import { WorkGraphView } from './WorkGraphView.js'

export function BattleView({ work, employees, t }: {
  readonly work: WorkProjection
  readonly employees?: readonly Employee[] | undefined
  readonly t: Translate
}) {
  return <section aria-label={t('battleResult')}>
    <h3>{t('battleResult')}</h3>
    <p>{t('battleExplanation')}</p>
    <WorkGraphView work={work} employees={employees} t={t} />
  </section>
}

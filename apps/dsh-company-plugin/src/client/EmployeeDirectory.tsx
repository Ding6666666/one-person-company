import type { Employee } from './api.js'
import type { Translate } from './locales.js'
import styles from './EmployeeDirectory.module.css'
import { Button } from './ui/Primitives.js'

export function EmployeeDirectory({ employees, workspaceSelected, onCreate, t }: {
  readonly employees: readonly Employee[]
  readonly workspaceSelected: boolean
  readonly onCreate: () => void
  readonly t: Translate
}) {
  return <section className={styles.directory}>
    <header>
      <Button type="button" disabled={!workspaceSelected} onClick={onCreate}>{t('createEmployee')}</Button>
    </header>
    {!workspaceSelected && <p>{t('noWorkspace')}</p>}
    {workspaceSelected && employees.length === 0 && <p>{t('emptyEmployees')}</p>}
    <div className={styles.cards}>
      {employees.map(employee => <article className={styles.card} key={employee.id}>
        <h2>{employee.display_name}</h2>
        <p>{employee.revision.responsibility}</p>
        <dl>
          <dt>{t('runtimeProfile')}</dt><dd>{employee.revision.runtime_profile}</dd>
          <dt>{t('model')}</dt><dd>{employee.revision.model}</dd>
        </dl>
      </article>)}
    </div>
  </section>
}

import { useState } from 'react'
import type { Employee } from './api.js'
import { CompanyEmptyState, CompanyPageHeader, CompanyStats } from './CompanyWorkbench.js'
import { employeeAvatars } from './employee-creation/avatars.js'
import type { RoleTemplateKey } from './employee-creation/types.js'
import type { Translate } from './locales.js'
import styles from './EmployeeDirectory.module.css'
import { Button, Dialog } from './ui/Primitives.js'

export function EmployeeDirectory({ employees, workspaceSelected, onCreate, t }: {
  readonly employees: readonly Employee[]
  readonly workspaceSelected: boolean
  readonly onCreate: () => void
  readonly t: Translate
}) {
  const [selected, setSelected] = useState<Employee>()
  const active = employees.filter(employee => employee.status === 'active').length
  const roles = new Set(employees.map(employee => employee.revision.work_type)).size
  const models = new Set(employees.map(employee => employee.revision.model)).size
  return <section className={styles.directory} aria-label={t('employeeCenter')}>
    <CompanyPageHeader eyebrow={t('teamEyebrow')} title={t('employeeCenter')} description={t('employeeCenterDescription')} action={<Button type="button" aria-label={t('createEmployee')} disabled={!workspaceSelected} onClick={onCreate}>＋ {t('createEmployee')}</Button>} />
    <CompanyStats items={[{ label: t('employeesTotal'), value: employees.length }, { label: t('activeEmployees'), value: active, tone: 'green' }, { label: t('roleTypes'), value: roles, tone: 'orange' }, { label: t('modelsConfigured'), value: models, tone: 'pink' }]} />
    {!workspaceSelected && <CompanyEmptyState icon="company" title={t('noWorkspace')} description={t('chooseCompanyDescription')} />}
    {workspaceSelected && employees.length === 0 && <CompanyEmptyState icon="employees" title={t('firstTeamTitle')} description={t('firstTeamDescription')}><Button type="button" onClick={onCreate}>{t('createFirstEmployee')}</Button></CompanyEmptyState>}
    <div className={styles.cards}>
      {employees.map(employee => {
        const key = employee.revision.avatar_key in employeeAvatars
          ? employee.revision.avatar_key as RoleTemplateKey
          : 'custom'
        return <article className={styles.card} key={employee.id}>
          <button className={styles.cardButton} type="button" aria-label={t('viewEmployeeDetails').replace('{name}', employee.display_name)} onClick={() => setSelected(employee)} />
          <span className={styles.status} data-status={employee.status}>{employee.status === 'active' ? t('active') : employee.status}</span>
          <div className={styles.avatar}><span /><img src={employeeAvatars[key]} alt={employee.display_name} /></div>
          <div className={styles.identity}><small>{employee.revision.work_type}</small><h2>{employee.display_name}</h2></div>
          <p>{employee.revision.responsibility}</p>
          <dl>
            <div><dt>{t('runtimeProfile')}</dt><dd>{employee.revision.runtime_profile}</dd></div>
            <div><dt>{t('model')}</dt><dd>{employee.revision.model}</dd></div>
          </dl>
        </article>
      })}
    </div>
    {selected !== undefined && <Dialog variant="drawer" title={t('employeeDetails')} onClose={() => setSelected(undefined)}>
      <div className={styles.drawerHeader}><img src={employeeAvatars[(selected.revision.avatar_key in employeeAvatars ? selected.revision.avatar_key : 'custom') as RoleTemplateKey]} alt="" /><div><small>{selected.revision.work_type}</small><h3>{selected.display_name}</h3></div><Button type="button" onClick={() => setSelected(undefined)}>{t('close')}</Button></div>
      <section className={styles.detailSection}><h4>{t('responsibility')}</h4><p>{selected.revision.responsibility}</p></section>
      <dl className={styles.details}><div><dt>{t('status')}</dt><dd>{selected.status === 'active' ? t('active') : selected.status}</dd></div><div><dt>{t('runtimeProfile')}</dt><dd>{selected.revision.runtime_profile}</dd></div><div><dt>{t('model')}</dt><dd>{selected.revision.model}</dd></div><div><dt>{t('employeeId')}</dt><dd>{selected.id}</dd></div></dl>
      <section className={styles.detailSection}><h4>{t('permissions')}</h4><div className={styles.chips}>{selected.grants.length === 0 ? <span>{t('noneConfigured')}</span> : selected.grants.map((grant, index) => <span key={`${grant.action}-${index}`}>{grant.action}</span>)}</div></section>
      <section className={styles.detailSection}><h4>{t('skills')}</h4><div className={styles.chips}>{selected.revision.skill_refs.length === 0 ? <span>{t('noneConfigured')}</span> : selected.revision.skill_refs.map(skill => <span key={skill}>{skill}</span>)}</div></section>
      <section className={styles.detailSection}><h4>{t('tools')}</h4><div className={styles.chips}>{selected.revision.tool_refs.length === 0 ? <span>{t('noneConfigured')}</span> : selected.revision.tool_refs.map(tool => <span key={tool}>{tool}</span>)}</div></section>
    </Dialog>}
  </section>
}

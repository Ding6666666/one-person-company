import { type FormEvent, useState } from 'react'

import type { DirectWorkCreate, Employee } from './api.js'
import type { Translate } from './locales.js'
import styles from './Work.module.css'
import { Button, Field } from './ui/Primitives.js'

const commandId = (): string => globalThis.crypto.randomUUID()

export function WorkComposer({ employees, pending, onCancel, onStart, t }: {
  readonly employees: readonly Employee[]
  readonly pending: boolean
  readonly onCancel: () => void
  readonly onStart: (input: DirectWorkCreate) => Promise<void>
  readonly t: Translate
}) {
  const activeEmployees = employees.filter(employee => employee.status === 'active')
  const [objective, setObjective] = useState('')
  const [criteriaText, setCriteriaText] = useState('')
  const [employeeId, setEmployeeId] = useState('')
  const [objectiveError, setObjectiveError] = useState<string>()
  const [criteriaError, setCriteriaError] = useState<string>()
  const [employeeError, setEmployeeError] = useState<string>()

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault()
    const normalizedObjective = objective.trim()
    const criteria = criteriaText.split(/\r?\n/u).map(item => item.trim()).filter(Boolean)
    const activeEmployee = activeEmployees.some(employee => employee.id === employeeId)
    setObjectiveError(normalizedObjective === '' ? t('workObjectiveRequired') : undefined)
    setCriteriaError(criteria.length === 0 ? t('criterionRequired') : undefined)
    setEmployeeError(!activeEmployee ? t('activeEmployeeRequired') : undefined)
    if (normalizedObjective === '' || criteria.length === 0 || !activeEmployee) return
    await onStart({ employee_id: employeeId, objective: normalizedObjective, acceptance_criteria: criteria, command_id: commandId() })
  }

  return <form className={styles.composer} onSubmit={event => { void submit(event) }} noValidate>
    <p>{t('directStrategy')}</p>
    <Field label={t('workObjective')} error={objectiveError}>
      <textarea value={objective} onChange={event => setObjective(event.target.value)} />
    </Field>
    <Field label={t('acceptanceCriteria')} error={criteriaError}>
      <textarea value={criteriaText} onChange={event => setCriteriaText(event.target.value)} />
    </Field>
    <Field label={t('responsibleEmployee')} error={employeeError}>
      <select value={employeeId} onChange={event => setEmployeeId(event.target.value)}>
        <option value="">{t('selectEmployee')}</option>
        {activeEmployees.map(employee => <option key={employee.id} value={employee.id}>{employee.display_name}</option>)}
      </select>
    </Field>
    {activeEmployees.length === 0 && <p>{t('noActiveEmployees')}</p>}
    <footer className={styles.actions}>
      <Button type="button" onClick={onCancel}>{t('cancel')}</Button>
      <Button type="submit" disabled={pending}>{t('startWork')}</Button>
    </footer>
  </form>
}

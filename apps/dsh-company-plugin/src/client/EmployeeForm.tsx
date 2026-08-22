import { type FormEvent, useState } from 'react'
import { z } from 'zod'

import type { ApiSchemas, EmployeeCreate } from './api.js'
import type { Translate } from './locales.js'
import styles from './EmployeeForm.module.css'
import { Button, Field } from './ui/Primitives.js'

const defaults = ['conversation.respond', 'workspace.read', 'session.history.read'] as const
const employeeSchema = z.object({
  displayName: z.string().trim().min(1, 'required').max(120, 'tooLong'),
  responsibility: z.string().trim().min(1, 'required').max(4000, 'tooLong'),
  model: z.string().trim().min(1, 'required').max(200, 'tooLong'),
})
const explicitGrantSchema = z.object({
  action: z.string().trim().min(1, 'required').max(120, 'tooLong'),
  resourceKind: z.string().trim().min(1, 'required'),
})

interface GrantDraft {
  readonly action: string
  readonly level: ApiSchemas['GrantCreate']['level']
  readonly resourceKind: string
  readonly resourceValues: string
  readonly requiresApproval: boolean
}

const emptyGrant = (): GrantDraft => ({
  action: '',
  level: 1,
  resourceKind: 'workspace',
  resourceValues: '',
  requiresApproval: false,
})

export function EmployeeForm({ pending, onCancel, onSave, t }: {
  readonly pending: boolean
  readonly onCancel: () => void
  readonly onSave: (input: EmployeeCreate) => Promise<void>
  readonly t: Translate
}) {
  const [displayName, setDisplayName] = useState('')
  const [responsibility, setResponsibility] = useState('')
  const [runtimeProfile, setRuntimeProfile] = useState<EmployeeCreate['runtime_profile']>('workspace_read')
  const [model, setModel] = useState('deepseek-v4-flash')
  const [advanced, setAdvanced] = useState(false)
  const [grants, setGrants] = useState<GrantDraft[]>([emptyGrant()])
  const [errors, setErrors] = useState<Record<string, string>>({})

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault()
    const parsed = employeeSchema.safeParse({ displayName, responsibility, model })
    const fields = parsed.success ? {} : parsed.error.flatten().fieldErrors
    const nextErrors: Record<string, string> = {
        ...(fields.displayName === undefined ? {} : {
          displayName: t(fields.displayName[0] === 'tooLong' ? 'employeeNameTooLong' : 'employeeNameRequired'),
        }),
        ...(fields.responsibility === undefined ? {} : {
          responsibility: t(fields.responsibility[0] === 'tooLong' ? 'responsibilityTooLong' : 'responsibilityRequired'),
        }),
        ...(fields.model === undefined ? {} : {
          model: t(fields.model[0] === 'tooLong' ? 'modelTooLong' : 'modelRequired'),
        }),
    }
    const explicitRows = advanced
      ? grants.map((grant, index) => ({
          index,
          action: grant.action.trim(),
          level: grant.level,
          resourceKind: grant.resourceKind.trim(),
          resourceValues: grant.resourceValues.split(',').map(value => value.trim()).filter(Boolean),
          requiresApproval: grant.requiresApproval,
        })).filter(grant =>
          grant.action.length > 0
          || grant.resourceKind !== 'workspace'
          || grant.resourceValues.length > 0
          || grant.requiresApproval
          || grant.level !== 1)
      : []
    for (const grant of explicitRows) {
      const grantResult = explicitGrantSchema.safeParse(grant)
      if (!grantResult.success) {
        const grantFields = grantResult.error.flatten().fieldErrors
        if (grantFields.action !== undefined) {
          nextErrors[`grantAction.${grant.index}`] = t(
            grantFields.action[0] === 'tooLong' ? 'grantActionTooLong' : 'grantActionRequired',
          )
        }
        if (grantFields.resourceKind !== undefined) {
          nextErrors[`grantResourceKind.${grant.index}`] = t('resourceKindRequired')
        }
      }
    }
    setErrors(nextErrors)
    if (!parsed.success || Object.keys(nextErrors).length > 0) {
      return
    }
    const explicit = explicitRows.map(grant => ({
          action: grant.action,
          level: grant.level,
          resource_kind: grant.resourceKind,
          resource_values: grant.resourceValues,
          requires_approval: grant.requiresApproval,
        }))
    await onSave({
      display_name: parsed.data.displayName,
      role_template_key: 'custom',
      work_type: '自定义工作',
      avatar_key: 'custom',
      responsibility: parsed.data.responsibility,
      runtime_profile: runtimeProfile,
      model: parsed.data.model,
      grants: explicit,
      skill_refs: [],
      tool_refs: [],
    })
  }

  const updateGrant = (index: number, patch: Partial<GrantDraft>): void => {
    setGrants(current => current.map((grant, grantIndex) => grantIndex === index ? { ...grant, ...patch } : grant))
  }

  return <form className={styles.form} onSubmit={(event) => { void submit(event) }} noValidate>
    <Field label={t('employeeName')} error={errors.displayName}>
      <input maxLength={120} value={displayName} onChange={event => setDisplayName(event.target.value)} />
    </Field>
    <Field label={t('responsibility')} error={errors.responsibility}>
      <textarea maxLength={4000} value={responsibility} onChange={event => setResponsibility(event.target.value)} />
    </Field>
    <Field label={t('runtimeProfile')}>
      <select value={runtimeProfile} onChange={event => setRuntimeProfile(event.target.value as EmployeeCreate['runtime_profile'])}>
        <option value="workspace_read">workspace_read</option>
        <option value="workspace_write">workspace_write</option>
        <option value="network_denied">network_denied</option>
      </select>
    </Field>
    <Field label={t('model')} error={errors.model}>
      <input maxLength={200} value={model} onChange={event => setModel(event.target.value)} />
    </Field>

    <section className={styles.defaults} aria-label={t('defaultGrants')}>
      <strong>{t('defaultGrants')}</strong>
      <ul>{defaults.map(action => <li key={action}>{action}</li>)}</ul>
    </section>

    <Button type="button" aria-expanded={advanced} onClick={() => setAdvanced(value => !value)}>{t('advancedGrants')}</Button>
    {advanced && <section className={styles.grants}>
      {grants.map((grant, index) => <fieldset key={index}>
        <Field label={t('grantAction')} error={errors[`grantAction.${index}`]}>
          <input maxLength={120} value={grant.action} onChange={event => updateGrant(index, { action: event.target.value })} />
        </Field>
        <Field label={t('grantLevel')}>
          <select value={grant.level} onChange={event => updateGrant(index, { level: Number(event.target.value) as GrantDraft['level'] })}>
            <option value="0">0</option><option value="1">1</option><option value="2">2</option><option value="3">3</option>
          </select>
        </Field>
        <Field label={t('resourceKind')} error={errors[`grantResourceKind.${index}`]}>
          <input value={grant.resourceKind} onChange={event => updateGrant(index, { resourceKind: event.target.value })} />
        </Field>
        <Field label={t('resourceValues')}>
          <input value={grant.resourceValues} onChange={event => updateGrant(index, { resourceValues: event.target.value })} />
        </Field>
        <label><input type="checkbox" checked={grant.requiresApproval} onChange={event => updateGrant(index, { requiresApproval: event.target.checked })} /> {t('requiresApproval')}</label>
      </fieldset>)}
      <Button type="button" onClick={() => setGrants(current => [...current, emptyGrant()])}>{t('addGrant')}</Button>
    </section>}

    <footer className={styles.actions}>
      <Button type="button" onClick={onCancel}>{t('cancel')}</Button>
      <Button type="submit" disabled={pending}>{t('saveEmployee')}</Button>
    </footer>
  </form>
}

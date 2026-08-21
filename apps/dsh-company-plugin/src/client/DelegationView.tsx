import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, type DelegationCollection, type ProductApi, type WorkProjection } from './api.js'
import type { Translate } from './locales.js'
import { Button } from './ui/Primitives.js'

type DelegationApi = Pick<ProductApi, 'listDelegations' | 'createDelegation'>
const delegationActions = new Set([
  'conversation.respond', 'workspace.read', 'session.history.read', 'work.delegate',
  'workspace.write', 'tool.shell', 'tool.network', 'external.publish',
])

export function DelegationView({ api, work, onWorkUpdated, t }: {
  readonly api: DelegationApi
  readonly work: WorkProjection
  readonly onWorkUpdated: (work: WorkProjection) => void
  readonly t: Translate
}) {
  const runningSources = work.nodes.filter(node => node.status === 'running' && work.execution_links.some(
    link => link.node_id === node.id && link.status === 'running' && link.attempt_id === node.active_attempt_id,
  ))
  const sourceProjection = runningSources.map(node => `${node.id}:${node.active_attempt_id}`).join('|')
  const [sourceNodeId, setSourceNodeId] = useState(runningSources.length === 1 ? runningSources[0]!.id : '')
  const [collection, setCollection] = useState<DelegationCollection>({ delegations: [], eligible_employees: [] })
  const [target, setTarget] = useState('')
  const [objective, setObjective] = useState('')
  const [criteria, setCriteria] = useState('')
  const [actions, setActions] = useState('')
  const [resources, setResources] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string>()
  const generation = useRef(0)
  const currentWorkId = useRef(work.id)
  currentWorkId.current = work.id
  const load = useCallback(async () => {
    const request = ++generation.current
    setError(undefined)
    try {
      const result = await api.listDelegations(work.id)
      if (request === generation.current) setCollection(result)
    } catch { if (request === generation.current) setError(t('governanceLoadFailed')) }
  }, [api, t, work.id])
  useEffect(() => {
    setCollection({ delegations: [], eligible_employees: [] })
    setTarget(''); setObjective(''); setCriteria(''); setActions(''); setResources('')
    setPending(false); setError(undefined)
    void load()
    return () => { generation.current += 1 }
  }, [load])
  useEffect(() => {
    setSourceNodeId(current => runningSources.some(node => node.id === current)
      ? current
      : runningSources.length === 1 ? runningSources[0]!.id : '')
  }, [sourceProjection])
  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault()
    const request = generation.current
    const targetWorkId = work.id
    const source = runningSources.find(node => node.id === sourceNodeId)
    const acceptanceCriteria = criteria.split('\n').map(value => value.trim()).filter(Boolean)
    const requiredActions = actions.split(',').map(value => value.trim()).filter(Boolean)
    const resourceValues = resources.split(',').map(value => value.trim()).filter(Boolean)
    const locallyValid = source !== undefined && Boolean(target)
      && objective.trim().length > 0 && objective.trim().length <= 500
      && acceptanceCriteria.length >= 1 && acceptanceCriteria.length <= 50
      && acceptanceCriteria.every(value => value.length <= 500)
      && requiredActions.length >= 1 && requiredActions.length <= 8
      && requiredActions.every(value => value.length <= 120 && delegationActions.has(value))
      && new Set(requiredActions).size === requiredActions.length
      && resourceValues.length >= 1 && resourceValues.length <= 50
      && resourceValues.every(value => value.length <= 200)
    if (!locallyValid) { setError(t('delegationInvalid')); return }
    setPending(true); setError(undefined)
    try {
      const result = await api.createDelegation(targetWorkId, {
        source_node_id: source!.id, proposer_employee_id: source!.assigned_employee_id, target_employee_id: target,
        objective: objective.trim(), acceptance_criteria: acceptanceCriteria, required_actions: requiredActions, resource_values: resourceValues,
      })
      if (request !== generation.current || targetWorkId !== currentWorkId.current) return
      setCollection(current => ({ ...current, delegations: [...current.delegations, result.delegation] }))
      onWorkUpdated(result.work)
      setObjective(''); setCriteria(''); setActions(''); setResources('')
    } catch (cause) {
      if (request === generation.current && targetWorkId === currentWorkId.current) {
        setError(t(cause instanceof ApiError && cause.status === 422
          ? 'delegationFieldsInvalid'
          : cause instanceof ApiError && cause.status === 409
            ? 'delegationDenied'
            : 'delegationSubmitFailed'))
      }
    }
    finally {
      if (request === generation.current && targetWorkId === currentWorkId.current) setPending(false)
    }
  }
  return <section aria-labelledby="delegation-title">
    <h3 id="delegation-title">{t('delegations')}</h3>
    {error !== undefined && <><p role="alert">{error}</p><Button type="button" onClick={() => { void load() }}>{t('retry')}</Button></>}
    <ul>{collection.delegations.map(item => <li key={item.id}>{item.target_employee_id}: <span>{t(item.status === 'accepted' ? 'delegationAccepted' : item.status === 'rejected' ? 'delegationRejected' : item.status === 'completed' ? 'delegationCompleted' : 'delegationProposed')}</span></li>)}</ul>
    <form onSubmit={event => { void submit(event) }}>
      {runningSources.length === 0 && <p>{t('noRunningDelegationSource')}</p>}
      {runningSources.length > 1 && <label>{t('delegationSource')}<select aria-label={t('delegationSource')} value={sourceNodeId} onChange={event => setSourceNodeId(event.target.value)}><option value="">{t('selectDelegationSource')}</option>{runningSources.map(node => <option key={node.id} value={node.id}>{node.objective}</option>)}</select></label>}
      <label>{t('delegateTo')}<select aria-label={t('delegateTo')} value={target} onChange={event => setTarget(event.target.value)}><option value="">{t('selectEmployee')}</option>{collection.eligible_employees.map(employee => <option key={employee.id} value={employee.id}>{employee.display_name}</option>)}</select></label>
      <label>{t('delegatedObjective')}<input aria-label={t('delegatedObjective')} maxLength={500} value={objective} onChange={event => setObjective(event.target.value)} /></label>
      <label>{t('delegatedCriteria')}<textarea aria-label={t('delegatedCriteria')} value={criteria} onChange={event => setCriteria(event.target.value)} /></label>
      <label>{t('requiredActions')}<input aria-label={t('requiredActions')} value={actions} onChange={event => setActions(event.target.value)} /></label>
      <label>{t('resourceValues')}<input aria-label={t('resourceValues')} value={resources} onChange={event => setResources(event.target.value)} /></label>
      <Button type="submit" disabled={pending || collection.eligible_employees.length === 0 || sourceNodeId === ''}>{t('delegate')}</Button>
    </form>
  </section>
}

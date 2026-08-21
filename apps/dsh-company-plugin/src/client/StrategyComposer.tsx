import { type FormEvent, useId, useState } from 'react'

import type { Employee, StrategyWorkCreate } from './api.js'
import type { CompanyLocaleKey, Translate } from './locales.js'
import styles from './Work.module.css'
import { Button, Field } from './ui/Primitives.js'

type Strategy = StrategyWorkCreate['kind']
type EdgeKind = 'depends_on' | 'delegates_to' | 'reviews' | 'summarizes'
export interface GraphRow { key: string; employeeId: string; objective: string }
export interface EdgeRow { fromKey: string; toKey: string; kind: EdgeKind }
export interface StarRow { employeeId: string; objective: string }
export interface StrategyDraft {
  readonly strategy: Strategy
  readonly objective: string
  readonly criteria: readonly string[]
  readonly directEmployee: string
  readonly participants: readonly string[]
  readonly summarizer: string
  readonly coordinator: string
  readonly starRows: readonly StarRow[]
  readonly graphRows: readonly GraphRow[]
  readonly edgeRows: readonly EdgeRow[]
}

type ValidationErrors = Record<string, CompanyLocaleKey>
const commandId = (): string => globalThis.crypto.randomUUID()

export function validateStrategyDraft(draft: StrategyDraft, activeIds: ReadonlySet<string>): ValidationErrors {
  const errors: ValidationErrors = {}
  const objective = draft.objective.trim()
  if (objective === '') errors.objective = 'workObjectiveRequired'
  else if (objective.length > 4000) errors.objective = 'workObjectiveTooLong'
  if (draft.criteria.length === 0) errors.criteria = 'criterionRequired'
  else if (draft.criteria.length > 50) errors.criteria = 'criteriaTooMany'
  else if (draft.criteria.some(criterion => criterion.length > 500)) errors.criteria = 'criterionTooLong'

  if (draft.strategy === 'direct') {
    if (!activeIds.has(draft.directEmployee)) errors.employee = 'activeEmployeeRequired'
  } else if (draft.strategy === 'battle') {
    if (draft.participants.length < 2 || draft.participants.length > 4) errors.participants = 'battleParticipantCount'
    else if (new Set(draft.participants).size !== draft.participants.length) errors.participants = 'battleParticipantsDistinct'
    else if (draft.participants.some(id => !activeIds.has(id))) errors.participants = 'activeEmployeeRequired'
    if (!activeIds.has(draft.summarizer)) errors.summarizer = 'battleSummarizerRequired'
    else if (draft.participants.includes(draft.summarizer)) errors.summarizer = 'battleSummarizerDistinct'
  } else if (draft.strategy === 'star') {
    if (!activeIds.has(draft.coordinator)) errors.coordinator = 'activeEmployeeRequired'
    if (draft.starRows.length === 0) errors.star = 'starChildrenRequired'
    else if (draft.starRows.length > 16) errors.star = 'starChildrenTooMany'
    draft.starRows.forEach((row, index) => {
      const objectiveValue = row.objective.trim()
      if (!activeIds.has(row.employeeId)) errors[`star.employee.${index}`] = 'activeEmployeeRequired'
      if (objectiveValue === '') errors[`star.objective.${index}`] = 'childObjectiveRequired'
      else if (objectiveValue.length > 4000) errors[`star.objective.${index}`] = 'childObjectiveTooLong'
    })
  } else validateGraph(draft, activeIds, errors)
  return errors
}

function validateGraph(draft: StrategyDraft, activeIds: ReadonlySet<string>, errors: ValidationErrors): void {
  if (draft.graphRows.length === 0) errors.graph = 'graphNodesRequired'
  else if (draft.graphRows.length > 32) errors.graph = 'graphNodesTooMany'
  const seenKeys = new Set<string>()
  for (const [index, row] of draft.graphRows.entries()) {
    const key = row.key.trim()
    const objective = row.objective.trim()
    if (key === '') errors[`graph.key.${index}`] = 'nodeKeyRequired'
    else if (key.length > 120) errors[`graph.key.${index}`] = 'nodeKeyTooLong'
    else if (seenKeys.has(key)) errors[`graph.key.${index}`] = 'nodeKeyDuplicate'
    seenKeys.add(key)
    if (!activeIds.has(row.employeeId)) errors[`graph.employee.${index}`] = 'activeEmployeeRequired'
    if (objective === '') errors[`graph.objective.${index}`] = 'nodeObjectiveRequired'
    else if (objective.length > 4000) errors[`graph.objective.${index}`] = 'nodeObjectiveTooLong'
  }
  if (draft.edgeRows.length > 128) errors.edges = 'graphEdgesTooMany'
  const edgeKeys = new Set<string>()
  const adjacency = new Map([...seenKeys].map(key => [key, [] as string[]]))
  for (const [index, edge] of draft.edgeRows.entries()) {
    const from = edge.fromKey.trim()
    const to = edge.toKey.trim()
    const edgeKey = `${from}\0${to}\0${edge.kind}`
    if (!seenKeys.has(from) || !seenKeys.has(to)) errors[`edge.${index}`] = 'edgeEndpointUnknown'
    else if (from === to) errors[`edge.${index}`] = 'edgeSelfReference'
    else if (edgeKeys.has(edgeKey)) errors[`edge.${index}`] = 'edgeDuplicate'
    else adjacency.get(from)?.push(to)
    edgeKeys.add(edgeKey)
  }
  if (errors.edges === undefined && hasCycle(adjacency)) errors.edges = 'graphCycle'
}

function hasCycle(adjacency: ReadonlyMap<string, readonly string[]>): boolean {
  const visiting = new Set<string>()
  const visited = new Set<string>()
  const visit = (node: string): boolean => {
    if (visiting.has(node)) return true
    if (visited.has(node)) return false
    visiting.add(node)
    for (const target of adjacency.get(node) ?? []) if (visit(target)) return true
    visiting.delete(node)
    visited.add(node)
    return false
  }
  return [...adjacency.keys()].some(visit)
}

export function StrategyComposer({ employees, pending, onCancel, onStart, t }: {
  readonly employees: readonly Employee[]
  readonly pending: boolean
  readonly onCancel: () => void
  readonly onStart: (input: StrategyWorkCreate) => Promise<void>
  readonly t: Translate
}) {
  const active = employees.filter(employee => employee.status === 'active')
  const activeIds = new Set(active.map(employee => employee.id))
  const [strategy, setStrategy] = useState<Strategy>('direct')
  const [objective, setObjective] = useState('')
  const [criteriaText, setCriteriaText] = useState('')
  const [directEmployee, setDirectEmployee] = useState('')
  const [participants, setParticipants] = useState<string[]>([])
  const [summarizer, setSummarizer] = useState('')
  const [coordinator, setCoordinator] = useState('')
  const [starRows, setStarRows] = useState<StarRow[]>([{ employeeId: '', objective: '' }])
  const [graphRows, setGraphRows] = useState<GraphRow[]>([{ key: 'node-1', employeeId: '', objective: '' }])
  const [edgeRows, setEdgeRows] = useState<EdgeRow[]>([])
  const [errors, setErrors] = useState<ValidationErrors>({})
  const battleErrorId = useId()
  const starErrorId = useId()
  const graphErrorId = useId()
  const edgesErrorId = useId()
  const error = (key: string): string | undefined => errors[key] === undefined ? undefined : t(errors[key])

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault()
    const criteria = criteriaText.split(/\r?\n/u).map(item => item.trim()).filter(Boolean)
    const draft: StrategyDraft = {
      strategy, objective, criteria, directEmployee, participants, summarizer,
      coordinator, starRows, graphRows, edgeRows,
    }
    const nextErrors = validateStrategyDraft(draft, activeIds)
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length > 0) return
    const common = { objective: objective.trim(), acceptance_criteria: criteria, command_id: commandId() }
    let input: StrategyWorkCreate
    if (strategy === 'direct') input = { kind: 'direct', employee_id: directEmployee, ...common }
    else if (strategy === 'battle') input = { kind: 'battle', participant_employee_ids: participants, summarizer_employee_id: summarizer, ...common }
    else if (strategy === 'star') {
      input = {
        kind: 'star', coordinator_employee_id: coordinator,
        children: starRows.map(row => ({ employee_id: row.employeeId, objective: row.objective.trim(), acceptance_criteria: criteria })),
        ...common,
      }
    } else {
      input = {
        kind: 'graph',
        nodes: graphRows.map(row => ({
          key: row.key.trim(), employee_id: row.employeeId, objective: row.objective.trim(),
          acceptance_criteria: criteria, required_actions: [], resource_values: [], resource_kinds: [], max_attempts: 1,
        })),
        edges: edgeRows.map(row => ({ from_key: row.fromKey.trim(), to_key: row.toKey.trim(), kind: row.kind })),
        ...common,
      }
    }
    await onStart(input)
  }

  const updateGraph = (index: number, changes: Partial<GraphRow>): void => setGraphRows(rows => rows.map((row, rowIndex) => rowIndex === index ? { ...row, ...changes } : row))
  const updateStar = (index: number, changes: Partial<StarRow>): void => setStarRows(rows => rows.map((row, rowIndex) => rowIndex === index ? { ...row, ...changes } : row))
  const updateEdge = (index: number, changes: Partial<EdgeRow>): void => setEdgeRows(rows => rows.map((row, rowIndex) => rowIndex === index ? { ...row, ...changes } : row))

  return <form className={styles.composer} onSubmit={event => { void submit(event) }} noValidate>
    <Field label={t('strategy')}>
      <select value={strategy} onChange={event => { setStrategy(event.target.value as Strategy); setErrors({}) }}>
        <option value="direct">Direct</option><option value="star">Star</option><option value="graph">Graph</option><option value="battle">Battle</option>
      </select>
    </Field>
    <Field label={t('workObjective')} error={error('objective')}><textarea maxLength={4001} value={objective} onChange={event => setObjective(event.target.value)} /></Field>
    <Field label={t('acceptanceCriteria')} error={error('criteria')}><textarea value={criteriaText} onChange={event => setCriteriaText(event.target.value)} /></Field>
    {strategy === 'direct' && <Field label={t('responsibleEmployee')} error={error('employee')}><EmployeeSelect value={directEmployee} employees={active} onChange={setDirectEmployee} t={t} /></Field>}
    {strategy === 'battle' && <fieldset aria-invalid={errors.participants === undefined ? undefined : true} aria-describedby={errors.participants === undefined ? undefined : battleErrorId}>
      <legend>{t('battleParticipants')}</legend>
      {active.map(item => <label key={item.id}><input type="checkbox" checked={participants.includes(item.id)} onChange={event => setParticipants(values => event.target.checked ? [...values, item.id] : values.filter(value => value !== item.id))} />{item.display_name}</label>)}
      {errors.participants !== undefined && <span id={battleErrorId} role="alert">{t(errors.participants)}</span>}
      <Field label={t('summarizer')} error={error('summarizer')}><EmployeeSelect value={summarizer} employees={active.filter(item => !participants.includes(item.id))} onChange={setSummarizer} t={t} /></Field>
    </fieldset>}
    {strategy === 'star' && <fieldset aria-invalid={errors.star === undefined ? undefined : true} aria-describedby={errors.star === undefined ? undefined : starErrorId}>
      <legend>{t('starConfiguration')}</legend>
      {errors.star !== undefined && <span id={starErrorId} role="alert">{t(errors.star)}</span>}
      <Field label={t('coordinator')} error={error('coordinator')}><EmployeeSelect value={coordinator} employees={active} onChange={setCoordinator} t={t} /></Field>
      {starRows.map((row, index) => <div key={index}>
        <Field label={`${t('childEmployee')} ${index + 1}`} error={error(`star.employee.${index}`)}><EmployeeSelect value={row.employeeId} employees={active} onChange={employeeId => updateStar(index, { employeeId })} t={t} /></Field>
        <Field label={`${t('childObjective')} ${index + 1}`} error={error(`star.objective.${index}`)}><input maxLength={4001} value={row.objective} onChange={event => updateStar(index, { objective: event.target.value })} /></Field>
      </div>)}
      <Button type="button" disabled={starRows.length >= 16} onClick={() => setStarRows(rows => [...rows, { employeeId: '', objective: '' }])}>{t('addChild')}</Button>
    </fieldset>}
    {strategy === 'graph' && <fieldset aria-invalid={errors.graph === undefined && errors.edges === undefined ? undefined : true} aria-describedby={[errors.graph === undefined ? undefined : graphErrorId, errors.edges === undefined ? undefined : edgesErrorId].filter(Boolean).join(' ') || undefined}>
      <legend>{t('graphConfiguration')}</legend>
      {errors.graph !== undefined && <span id={graphErrorId} role="alert">{t(errors.graph)}</span>}
      {errors.edges !== undefined && <span id={edgesErrorId} role="alert">{t(errors.edges)}</span>}
      {graphRows.map((row, index) => <div key={index}>
        <Field label={`${t('nodeKey')} ${index + 1}`} error={error(`graph.key.${index}`)}><input maxLength={121} value={row.key} onChange={event => updateGraph(index, { key: event.target.value })} /></Field>
        <Field label={`${t('assignedEmployee')} ${index + 1}`} error={error(`graph.employee.${index}`)}><EmployeeSelect value={row.employeeId} employees={active} onChange={employeeId => updateGraph(index, { employeeId })} t={t} /></Field>
        <Field label={`${t('nodeObjective')} ${index + 1}`} error={error(`graph.objective.${index}`)}><input maxLength={4001} value={row.objective} onChange={event => updateGraph(index, { objective: event.target.value })} /></Field>
      </div>)}
      <Button type="button" disabled={graphRows.length >= 32} onClick={() => setGraphRows(rows => [...rows, { key: `node-${rows.length + 1}`, employeeId: '', objective: '' }])}>{t('addNode')}</Button>
      {graphRows.length >= 2 && <Button type="button" disabled={edgeRows.length >= 128} onClick={() => setEdgeRows(rows => [...rows, { fromKey: graphRows[0]?.key ?? '', toKey: graphRows[1]?.key ?? '', kind: 'depends_on' }])}>{t('addDependency')}</Button>}
      {edgeRows.map((edge, index) => <div key={index}>
        <Field label={`${t('dependencyFrom')} ${index + 1}`} error={error(`edge.${index}`)}><select value={edge.fromKey} onChange={event => updateEdge(index, { fromKey: event.target.value })}>{graphRows.map((row, rowIndex) => <option key={`${rowIndex}-${row.key}`} value={row.key}>{row.key}</option>)}</select></Field>
        <Field label={`${t('dependencyKind')} ${index + 1}`}><select value={edge.kind} onChange={event => updateEdge(index, { kind: event.target.value as EdgeKind })}><option value="depends_on">{t('edgeDependsOn')}</option><option value="delegates_to">{t('edgeDelegatesTo')}</option><option value="reviews">{t('edgeReviews')}</option><option value="summarizes">{t('edgeSummarizes')}</option></select></Field>
        <Field label={`${t('dependencyTo')} ${index + 1}`}><select value={edge.toKey} onChange={event => updateEdge(index, { toKey: event.target.value })}>{graphRows.map((row, rowIndex) => <option key={`${rowIndex}-${row.key}`} value={row.key}>{row.key}</option>)}</select></Field>
      </div>)}
    </fieldset>}
    {active.length === 0 && <p>{t('noActiveEmployees')}</p>}
    <footer className={styles.actions}><Button type="button" onClick={onCancel}>{t('cancel')}</Button><Button type="submit" disabled={pending}>{t('startWork')}</Button></footer>
  </form>
}

function EmployeeSelect({ value, employees, onChange, t, id, ...aria }: {
  readonly value: string
  readonly employees: readonly Employee[]
  readonly onChange: (value: string) => void
  readonly t: Translate
  readonly id?: string
  readonly 'aria-describedby'?: string
  readonly 'aria-invalid'?: boolean
}) {
  return <select id={id} aria-describedby={aria['aria-describedby']} aria-invalid={aria['aria-invalid']} value={value} onChange={event => onChange(event.target.value)}><option value="">{t('selectEmployee')}</option>{employees.map(item => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select>
}

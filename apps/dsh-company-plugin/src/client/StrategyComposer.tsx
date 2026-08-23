import { type FormEvent, useId, useState } from 'react'

import type { Employee, StrategyWorkCreate } from './api.js'
import type { CompanyLocaleKey, Translate } from './locales.js'
import styles from './Work.module.css'
import { Button, Field } from './ui/Primitives.js'

type Strategy = StrategyWorkCreate['kind']
type EdgeKind = 'depends_on' | 'delegates_to' | 'reviews' | 'summarizes'
type Localized = { readonly zh: string; readonly en: string }
interface StrategyPresentation {
  readonly key: Strategy
  readonly name: Localized
  readonly tag: Localized
  readonly summary: Localized
  readonly workflow: Localized
  readonly suitable: Localized
  readonly configuration: Localized
  readonly unsuitable: Localized
  readonly symbol: string
}

const strategyPresentations: readonly StrategyPresentation[] = [
  {
    key: 'direct', symbol: '→', name: { zh: '单人执行', en: 'Direct execution' }, tag: { zh: '简单直接', en: 'Clear ownership' },
    summary: { zh: '由一名员工完整负责目标与交付。', en: 'One employee owns the objective and delivery end to end.' },
    workflow: { zh: '一名员工独立负责，从目标执行到最终交付保持单一责任人。', en: 'One employee works independently and remains accountable from objective to final delivery.' },
    suitable: { zh: '边界清晰、无需多人协作的单项任务', en: 'Well-scoped tasks that do not require multi-employee collaboration' },
    configuration: { zh: '1 名负责员工', en: '1 responsible employee' },
    unsuitable: { zh: '需要并行探索、多人审核或复杂依赖的工作', en: 'Work requiring parallel exploration, multiple reviewers, or complex dependencies' },
  },
  {
    key: 'star', symbol: '✦', name: { zh: '中心协作', en: 'Coordinated team' }, tag: { zh: '并行协作', en: 'Parallel delivery' },
    summary: { zh: '协调者拆分目标，多名员工并行完成子任务。', en: 'A coordinator delegates child objectives to parallel contributors.' },
    workflow: { zh: '一名协调者统筹工作，并把独立子目标分配给多名执行员工。', en: 'A coordinator directs the work and assigns independent child objectives to contributors.' },
    suitable: { zh: '可以并行拆分、但需要统一协调和收口的任务', en: 'Parallelizable work that still needs central coordination and consolidation' },
    configuration: { zh: '1 名协调者，以及至少 1 个员工子任务', en: '1 coordinator and at least 1 employee child task' },
    unsuitable: { zh: '子任务存在复杂先后依赖或需要多轮交叉审核的流程', en: 'Processes with complex dependencies or repeated cross-review' },
  },
  {
    key: 'graph', symbol: '◇', name: { zh: '流程编排', en: 'Workflow graph' }, tag: { zh: '复杂流程', en: 'Complex workflow' },
    summary: { zh: '用任务节点和关系表达依赖、委派、审核与汇总。', en: 'Connect task nodes through dependencies, delegation, review, and summaries.' },
    workflow: { zh: '把工作拆成多个节点，并明确每个节点的负责人及节点之间的执行关系。', en: 'Break work into nodes, assign each owner, and define execution relationships between nodes.' },
    suitable: { zh: '存在先后顺序、交接、审核或多阶段产出的复杂流程', en: 'Complex flows with sequencing, handoffs, reviews, or multi-stage outputs' },
    configuration: { zh: '任务节点、负责员工，以及可选的节点关系', en: 'Task nodes, assigned employees, and optional node relationships' },
    unsuitable: { zh: '一名员工即可直接完成，或无法提前描述流程关系的任务', en: 'Tasks one employee can finish directly or whose workflow cannot be described in advance' },
  },
  {
    key: 'battle', symbol: '⇄', name: { zh: '方案竞选', en: 'Proposal battle' }, tag: { zh: '比较决策', en: 'Compare options' },
    summary: { zh: '多名员工独立提出方案，再由另一名员工比较并汇总。', en: 'Several employees propose independently; another employee compares and synthesizes.' },
    workflow: { zh: '2–4 名员工分别提出方案，再由一名不参赛的员工独立比较、判断并汇总。', en: 'Two to four employees propose independently, then a non-participant compares and synthesizes them.' },
    suitable: { zh: '需要多个独立观点或候选方案的决策任务', en: 'Decisions that benefit from multiple independent viewpoints or candidate solutions' },
    configuration: { zh: '2–4 名参赛员工，以及 1 名独立汇总员工', en: '2–4 participants and 1 independent summarizer' },
    unsuitable: { zh: '已有明确唯一执行路径，或不需要比较多个方案的任务', en: 'Tasks with one established execution path or no need to compare alternatives' },
  },
] as const

const localized = (value: Localized, language: 'zh' | 'en'): string => value[language]
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
  const language = t('cancel') === 'Cancel' ? 'en' : 'zh'
  const [strategy, setStrategy] = useState<Strategy>('direct')
  const selectedPresentation = strategyPresentations.find(item => item.key === strategy) ?? strategyPresentations[0]!
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
  const strategyTitleId = useId()
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
    <section className={styles.strategyChooser} aria-labelledby={strategyTitleId}>
      <header className={styles.strategyIntro}>
        <div><span>01</span><h3 id={strategyTitleId}>{language === 'zh' ? '选择工作策略' : 'Choose a work strategy'}</h3></div>
        <p>{language === 'zh' ? '策略决定员工如何分工、协作和汇总结果。选择后可查看完整说明。' : 'The strategy determines how employees divide, coordinate, and synthesize the work.'}</p>
      </header>
      <div className={styles.strategyGrid}>{strategyPresentations.map(item => {
        const selected = strategy === item.key
        return <button key={item.key} type="button" className={styles.strategyCard} data-strategy={item.key} aria-pressed={selected} onClick={() => { setStrategy(item.key); setErrors({}) }}>
          <span className={styles.strategyCardTop}><span className={styles.strategySymbol} aria-hidden="true">{item.symbol}</span><span className={styles.strategyTag}>{localized(item.tag, language)}</span></span>
          <span className={styles.strategyIdentity}><small>{item.key[0]!.toUpperCase() + item.key.slice(1)}</small><strong>{localized(item.name, language)}</strong></span>
          <span className={styles.strategySummary}>{localized(item.summary, language)}</span>
        </button>
      })}</div>
      <article className={styles.strategyExplanation} data-strategy={selectedPresentation.key} aria-live="polite">
        <header><span className={styles.strategySymbol} aria-hidden="true">{selectedPresentation.symbol}</span><div><small>{selectedPresentation.key[0]!.toUpperCase() + selectedPresentation.key.slice(1)}</small><strong>{localized(selectedPresentation.name, language)}</strong></div></header>
        <dl className={styles.strategyDetails}>
          <div><dt>{language === 'zh' ? '工作方式' : 'How it works'}</dt><dd>{localized(selectedPresentation.workflow, language)}</dd></div>
          <div><dt>{language === 'zh' ? '适合' : 'Best for'}</dt><dd>{localized(selectedPresentation.suitable, language)}</dd></div>
          <div><dt>{language === 'zh' ? '需要配置' : 'Configure'}</dt><dd>{localized(selectedPresentation.configuration, language)}</dd></div>
          <div><dt>{language === 'zh' ? '不建议' : 'Avoid when'}</dt><dd>{localized(selectedPresentation.unsuitable, language)}</dd></div>
        </dl>
      </article>
    </section>
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

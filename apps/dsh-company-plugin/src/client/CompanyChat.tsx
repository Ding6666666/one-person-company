import { type FormEvent, useMemo, useState } from 'react'

import type { ChatMessageProjection, Employee } from './api.js'
import { filterMentionCandidates, mentionEmployeeIds } from './chat/mention.js'
import { employeeAvatars } from './employee-creation/avatars.js'
import type { RoleTemplateKey } from './employee-creation/types.js'
import type { Translate } from './locales.js'
import styles from './CompanyChat.module.css'

export interface CompanyChatProps {
  readonly messages: readonly ChatMessageProjection[]
  readonly employees: readonly Employee[]
  readonly workspaceSelected: boolean
  readonly pending: boolean
  readonly discussionWorkId?: string | undefined
  readonly onCloseDiscussion?: (() => void) | undefined
  readonly onSend: (body: string, employeeIds: readonly string[]) => Promise<void>
  readonly onRetry: (executionId: string) => Promise<void>
  readonly onOpenWork: (workId: string) => Promise<void>
  readonly onCreateEmployee?: (() => void) | undefined
  readonly t: Translate
}

const avatarFor = (employee: Employee): string => {
  const key = employee.revision.avatar_key in employeeAvatars
    ? employee.revision.avatar_key as RoleTemplateKey
    : 'custom'
  return employeeAvatars[key]
}

export function CompanyChat({
  messages,
  employees,
  workspaceSelected,
  pending,
  discussionWorkId,
  onCloseDiscussion,
  onSend,
  onRetry,
  onOpenWork,
  onCreateEmployee,
  t,
}: CompanyChatProps) {
  const [body, setBody] = useState('')
  const [selected, setSelected] = useState<Employee[]>([])
  const mentionMatch = /(?:^|\s)@([^\s@]*)$/u.exec(body)
  const candidates = useMemo(
    () => mentionMatch === null ? [] : filterMentionCandidates(employees, mentionMatch[1] ?? '')
      .filter(employee => !selected.some(item => item.id === employee.id)),
    [employees, mentionMatch?.[1], selected],
  )
  const employeeById = useMemo(() => new Map(employees.map(employee => [employee.id, employee])), [employees])
  const activeCards = messages.filter(message => message.work_card !== null && !['completed', 'failed', 'cancelled'].includes(message.work_card.status))

  const chooseMention = (employee: Employee): void => {
    if (mentionMatch === null) return
    const prefix = body.slice(0, mentionMatch.index)
    const separator = mentionMatch[0].startsWith(' ') ? ' ' : ''
    setBody(`${prefix}${separator}@${employee.display_name} `)
    setSelected(items => [...items, employee])
  }

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault()
    const content = body.trim()
    if (!content || !workspaceSelected || pending) return
    await onSend(content, mentionEmployeeIds(selected))
    setBody('')
    setSelected([])
  }

  return <section className={styles.chat} aria-label={t('companyChat')}>
    <div className={styles.main}>
      <header className={styles.chatHeader}>
        <div><span>{discussionWorkId === undefined ? t('companyGroup') : t('workDiscussion')}</span><h2>{discussionWorkId === undefined ? t('companyChat') : messages.find(message => message.work_id === discussionWorkId)?.work_card?.objective ?? t('workDiscussion')}</h2><p>{discussionWorkId === undefined ? t('companyChatDescription') : t('workDiscussionDescription')}</p></div>
        {discussionWorkId !== undefined && onCloseDiscussion !== undefined && <button type="button" onClick={onCloseDiscussion}>{t('backToCompanyChat')}</button>}
      </header>
      {!workspaceSelected && <div className={styles.empty}><strong>{t('noWorkspace')}</strong><span>{t('chooseCompanyDescription')}</span>{onCreateEmployee !== undefined && <button type="button" disabled>{t('createEmployee')}</button>}</div>}
      {workspaceSelected && messages.length === 0 && <div className={styles.empty}><strong>{t('emptyChatTitle')}</strong><span>{t('emptyChatDescription')}</span>{employees.length === 0 && onCreateEmployee !== undefined && <button type="button" onClick={onCreateEmployee}>{t('createEmployee')}</button>}</div>}
      <ol className={styles.timeline} aria-live="polite">
        {messages.map(message => {
          const employee = message.employee_id === null ? undefined : employeeById.get(message.employee_id)
          return <li key={message.id} className={styles.message} data-author={message.author_kind}>
            <div className={styles.messageAvatar}>{employee === undefined ? (message.author_kind === 'user' ? '你' : '✦') : <img src={avatarFor(employee)} alt="" />}</div>
            <article>
              <header><strong>{employee?.display_name ?? (message.author_kind === 'user' ? t('you') : t('companySystem'))}</strong><time>{new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></header>
              {message.work_card === null ? <p>{message.body}</p> : <div className={styles.workCard}>
                <span data-status={message.work_card.status}>{t(`status${message.work_card.status[0]!.toUpperCase()}${message.work_card.status.slice(1)}` as Parameters<Translate>[0])}</span>
                <h3>{message.work_card.objective}</h3>
                <p>{t('strategy')}: {message.work_card.strategy.toUpperCase()}</p>
                <button type="button" onClick={() => { void onOpenWork(message.work_card!.id) }}>{t('openWorkDiscussion')}</button>
              </div>}
              {message.executions.length > 0 && <ul className={styles.executions}>{message.executions.map(execution => <li key={execution.id} data-status={execution.status}>
                <span>{employeeById.get(execution.employee_id)?.display_name ?? execution.employee_id}</span>
                <strong>{execution.status === 'queued' ? t('chatQueued') : execution.status === 'running' ? t('chatRunning') : execution.status === 'completed' ? t('chatCompleted') : t('chatFailed')}</strong>
                {execution.status === 'failed' && <button type="button" onClick={() => { void onRetry(execution.id) }}>{t('retry')}</button>}
              </li>)}</ul>}
            </article>
          </li>
        })}
      </ol>
      <form className={styles.composer} onSubmit={event => { void submit(event) }}>
        {selected.length > 0 && <div className={styles.mentions}>{selected.map(employee => <button key={employee.id} type="button" onClick={() => setSelected(items => items.filter(item => item.id !== employee.id))}>@{employee.display_name} ×</button>)}</div>}
        <textarea aria-label={t('sendMessage')} value={body} disabled={!workspaceSelected || pending} placeholder={t('chatPlaceholder')} onChange={event => setBody(event.target.value)} />
        {mentionMatch !== null && candidates.length > 0 && <div className={styles.suggestions} role="listbox" aria-label={t('mentionEmployees')}>{candidates.map(employee => <button key={employee.id} role="option" aria-selected="false" type="button" onClick={() => chooseMention(employee)}><img src={avatarFor(employee)} alt="" /><span><strong>{employee.display_name}</strong><small>{employee.revision.work_type}</small></span></button>)}</div>}
        <footer><span>{t('chatComposerHint')}</span><button type="submit" disabled={!workspaceSelected || pending || !body.trim()}>{t('send')}</button></footer>
      </form>
    </div>
    <aside className={styles.context}>
      <section><h3>{t('companyMembers')}</h3>{employees.map(employee => <div className={styles.member} key={employee.id}><img src={avatarFor(employee)} alt="" /><span><strong>{employee.display_name}</strong><small>{employee.revision.work_type}</small></span><i data-active={employee.status === 'active'} /></div>)}</section>
      <section><h3>{t('activeDiscussions')}</h3>{activeCards.length === 0 ? <p>{t('noActiveDiscussions')}</p> : activeCards.map(message => <button className={styles.discussion} key={message.id} type="button" onClick={() => { void onOpenWork(message.work_card!.id) }}><strong>{message.work_card!.objective}</strong><span>{message.work_card!.strategy.toUpperCase()}</span></button>)}</section>
    </aside>
  </section>
}

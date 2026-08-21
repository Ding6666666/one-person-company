import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, type ProductApi, type WorkspaceGrant } from './api.js'
import type { Translate } from './locales.js'
import { Button } from './ui/Primitives.js'

type CapabilityApi = Pick<ProductApi, 'getWorkspaceCapabilities' | 'replaceWorkspaceCapabilities'>
const levels = { 'conversation.respond': 0, 'workspace.read': 1, 'session.history.read': 1, 'work.delegate': 1, 'workspace.write': 2, 'tool.shell': 2, 'tool.network': 2, 'external.publish': 3 } as const
const knownActions = new Set<string>(Object.keys(levels))

function validGrant(grant: WorkspaceGrant): boolean {
  return knownActions.has(grant.action)
    && grant.action.length <= 120
    && levels[grant.action as keyof typeof levels] === grant.level
    && grant.resource_kind.trim().length > 0
    && grant.resource_values.length > 0
    && grant.resource_values.every(value => value.trim().length > 0 && value.trim().length <= 200)
}

export function CapabilityEditor({ api, workspaceId, t }: {
  readonly api: CapabilityApi
  readonly workspaceId: string
  readonly t: Translate
}) {
  const [draft, setDraft] = useState<WorkspaceGrant[]>([])
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string>()
  const [saved, setSaved] = useState(false)
  const generation = useRef(0)
  const currentWorkspaceId = useRef(workspaceId)
  currentWorkspaceId.current = workspaceId
  const load = useCallback(async () => {
    const request = ++generation.current
    const targetWorkspaceId = workspaceId
    setDraft([]); setPhase('loading'); setPending(false); setError(undefined); setSaved(false)
    try {
      const result = await api.getWorkspaceCapabilities(targetWorkspaceId)
      if (request !== generation.current || targetWorkspaceId !== currentWorkspaceId.current) return
      setDraft(result.grants)
      setPhase('ready')
    } catch {
      if (request === generation.current && targetWorkspaceId === currentWorkspaceId.current) {
        setDraft([]); setPhase('error'); setError(t('capabilityLoadFailed'))
      }
    }
  }, [api, t, workspaceId])
  useEffect(() => {
    void load()
    return () => { generation.current += 1 }
  }, [load])

  const add = (): void => setDraft(current => [...current, {
    action: 'workspace.read', level: 1, resource_kind: 'workspace', resource_values: [workspaceId], requires_approval: false,
  }])
  const save = async (): Promise<void> => {
    if (phase !== 'ready') return
    if (draft.length > 8 || new Set(draft.map(item => item.action)).size !== draft.length || draft.some(item => !validGrant(item))) {
      setError(t('capabilityInvalid')); return
    }
    const request = generation.current
    const targetWorkspaceId = workspaceId
    setPending(true); setError(undefined); setSaved(false)
    try {
      const normalized = draft.map(grant => ({
        ...grant,
        resource_kind: grant.resource_kind.trim(),
        resource_values: grant.resource_values.map(value => value.trim()),
      }))
      const result = await api.replaceWorkspaceCapabilities(targetWorkspaceId, { grants: normalized })
      if (request !== generation.current || targetWorkspaceId !== currentWorkspaceId.current) return
      setDraft(result.grants); setSaved(true)
    } catch (cause) {
      if (request === generation.current && targetWorkspaceId === currentWorkspaceId.current) {
        setError(t(cause instanceof ApiError && cause.status === 422 ? 'capabilityFieldsInvalid' : 'capabilitySaveFailed'))
      }
    } finally {
      if (request === generation.current && targetWorkspaceId === currentWorkspaceId.current) setPending(false)
    }
  }
  return <section aria-labelledby="capability-editor-title">
    <h3 id="capability-editor-title">{t('workspaceCapabilities')}</h3>
    {phase === 'loading' && <p role="status">{t('loading')}</p>}
    {phase === 'error' && <Button type="button" onClick={() => { void load() }}>{t('retry')}</Button>}
    {draft.map((grant, index) => <fieldset key={`${index}-${grant.action}`}>
      <label>{t('grantAction')}<select value={grant.action} onChange={event => setDraft(current => current.map((item, position) => position === index ? { ...item, action: event.target.value, level: levels[event.target.value as keyof typeof levels] } : item))}>
        {Object.entries(levels).map(([action]) => <option key={action}>{action}</option>)}
      </select></label>
      <label>{t('resourceKind')}<input value={grant.resource_kind} onChange={event => setDraft(current => current.map((item, position) => position === index ? { ...item, resource_kind: event.target.value } : item))} /></label>
      <label>{t('resourceValues')}<input value={grant.resource_values.join(', ')} onChange={event => setDraft(current => current.map((item, position) => position === index ? { ...item, resource_values: event.target.value.split(',').map(value => value.trim()).filter(Boolean) } : item))} /></label>
      <label><input type="checkbox" checked={grant.requires_approval} onChange={event => setDraft(current => current.map((item, position) => position === index ? { ...item, requires_approval: event.target.checked } : item))} />{t('requiresApproval')}</label>
      <Button type="button" onClick={() => setDraft(current => current.filter((_item, position) => position !== index))}>{t('removeCapability')}</Button>
    </fieldset>)}
    {error !== undefined && <p role="alert">{error}</p>}
    {saved && <p role="status">{t('capabilitySaved')}</p>}
    <Button type="button" disabled={phase !== 'ready' || pending} onClick={add}>{t('addCapability')}</Button>
    <Button type="button" disabled={phase !== 'ready' || pending} onClick={() => { void save() }}>{t('saveCapabilities')}</Button>
  </section>
}

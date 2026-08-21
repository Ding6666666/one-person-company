import { useCallback, useEffect, useRef, useState } from 'react'

import type { ApprovalProjection, ProductApi, WorkProjection } from './api.js'
import type { Translate } from './locales.js'
import { Button } from './ui/Primitives.js'

type ApprovalApi = Pick<ProductApi, 'listApprovals' | 'approveApproval' | 'rejectApproval'>

export function ApprovalInbox({ api, workspaceId, refreshKey, onWorkUpdated, t }: {
  readonly api: ApprovalApi
  readonly workspaceId: string
  readonly refreshKey?: string
  readonly onWorkUpdated: (work: WorkProjection) => void
  readonly t: Translate
}) {
  const [items, setItems] = useState<ApprovalProjection[]>([])
  const [pendingId, setPendingId] = useState<string>()
  const [error, setError] = useState<string>()
  const generation = useRef(0)
  const currentWorkspaceId = useRef(workspaceId)
  currentWorkspaceId.current = workspaceId
  const load = useCallback(async () => {
    const request = ++generation.current
    setError(undefined)
    try {
      const approvals = await api.listApprovals(workspaceId)
      if (request === generation.current) setItems(approvals.filter(item => item.status === 'pending'))
    } catch {
      if (request === generation.current) setError(t('governanceLoadFailed'))
    }
  }, [api, t, workspaceId])
  useEffect(() => {
    setItems([])
    setPendingId(undefined)
    setError(undefined)
    void load()
    return () => { generation.current += 1 }
  }, [load, refreshKey])

  const decide = async (item: ApprovalProjection, approve: boolean): Promise<void> => {
    const request = generation.current
    const targetWorkspaceId = workspaceId
    setPendingId(item.id)
    setError(undefined)
    try {
      const result = approve
        ? await api.approveApproval(item.id, 'operator')
        : await api.rejectApproval(item.id, 'operator')
      if (request !== generation.current || targetWorkspaceId !== currentWorkspaceId.current) return
      onWorkUpdated(result.work)
      setItems(current => current.filter(candidate => candidate.id !== item.id))
    } catch {
      if (request === generation.current && targetWorkspaceId === currentWorkspaceId.current) setError(t('governanceDecisionFailed'))
    } finally {
      if (request === generation.current && targetWorkspaceId === currentWorkspaceId.current) setPendingId(undefined)
    }
  }

  return <section aria-labelledby="approval-inbox-title">
    <h3 id="approval-inbox-title">{t('approvalInbox')}</h3>
    {error !== undefined && <><p role="alert">{error}</p><Button type="button" onClick={() => { void load() }}>{t('retry')}</Button></>}
    {items.length === 0 && error === undefined && <p>{t('emptyApprovals')}</p>}
    <ul>{items.map(item => <li key={item.id}>
      <strong>{item.action}</strong>
      <div>{t('requestingEmployee')}: <span>{item.requesting_employee.display_name}</span></div>
      <div>{t('resourceValues')}: <span>{item.resources.join(', ')}</span></div>
      <div>{t('approvalReason')}: <span>{item.reason}</span></div>
      <Button type="button" disabled={pendingId !== undefined} onClick={() => { void decide(item, true) }}>{t('approve')}</Button>
      <Button type="button" disabled={pendingId !== undefined} onClick={() => { void decide(item, false) }}>{t('reject')}</Button>
    </li>)}</ul>
  </section>
}

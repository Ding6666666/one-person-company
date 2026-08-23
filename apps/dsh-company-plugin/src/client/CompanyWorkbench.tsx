import { useState, type ReactNode } from 'react'
import type { Workspace } from './api.js'
import { CompanyIcon, type CompanyIconName } from './CompanyIcons.js'
import type { Translate } from './locales.js'
import styles from './CompanyWorkbench.module.css'

export type CompanyView = 'chat' | 'employees' | 'work'

export function CompanyHeader({ onClose, t }: { readonly onClose?: () => void; readonly t: Translate }) {
  return <header className={styles.header}><div className={styles.brandMark}><CompanyIcon name="company" /></div><div className={styles.brandCopy}><strong>{t('title')}</strong><span>{t('companyTagline')}</span></div><div className={styles.headerStatus}><span className={styles.onlineDot} />{t('serviceHealthy')}</div>{onClose !== undefined && <button className={styles.iconButton} type="button" onClick={onClose} aria-label={t('close')}><CompanyIcon name="close" /></button>}</header>
}

function ViewLink({ view, current, icon, label, accessibleLabel, onSelect }: { readonly view: CompanyView; readonly current: CompanyView; readonly icon: CompanyIconName; readonly label: string; readonly accessibleLabel?: string; readonly onSelect: (view: CompanyView) => void }) {
  return <a href={`#${view}`} aria-label={accessibleLabel} aria-current={current === view ? 'page' : undefined} onClick={event => { event.preventDefault(); onSelect(view) }}><span className={styles.navIcon}><CompanyIcon name={icon} /></span><span>{label}</span></a>
}

export function CompanyNavigation({ workspaces, selectedWorkspaceId, view, onSelectWorkspace, onCreateWorkspace, onSelectView, onOpenSettings, t }: { readonly workspaces: readonly Workspace[]; readonly selectedWorkspaceId: string | undefined; readonly view: CompanyView; readonly onSelectWorkspace: (workspaceId: string) => void; readonly onCreateWorkspace: () => void; readonly onSelectView: (view: CompanyView) => void; readonly onOpenSettings?: (() => void) | undefined; readonly t: Translate }) {
  const [workspaceOpen, setWorkspaceOpen] = useState(false)
  const selected = workspaces.find(workspace => workspace.id === selectedWorkspaceId)
  return <aside className={styles.rail}><nav className={styles.navigation} aria-label={t('companyNavigation')}><p className={styles.eyebrow}>{t('companyOverview')}</p><button className={styles.workspaceSelector} type="button" aria-expanded={workspaceOpen} onClick={() => setWorkspaceOpen(value => !value)}><span className={styles.workspaceAvatar}>{selected?.name.slice(0, 1) ?? '?'}</span><span><small>{t('workspaceSelector')}</small><strong>{selected?.name ?? t('noWorkspace')}</strong></span><CompanyIcon name="chevron" /></button><button className={styles.createWorkspace} type="button" onClick={onCreateWorkspace}><CompanyIcon name="plus" />{t('createWorkspace')}</button><div className={styles.workspaceMenu} data-open={workspaceOpen}>{workspaces.map(workspace => <a key={workspace.id} href={`#workspace-${encodeURIComponent(workspace.id)}`} aria-current={workspace.id === selectedWorkspaceId ? 'page' : undefined} onClick={event => { event.preventDefault(); onSelectWorkspace(workspace.id); setWorkspaceOpen(false) }}>{workspace.name}</a>)}</div><div className={styles.navLinks}><ViewLink view="chat" current={view} icon="chat" label={t('companyChat')} accessibleLabel={t('companyChat')} onSelect={onSelectView} /><ViewLink view="employees" current={view} icon="employees" label={t('employeeCenter')} accessibleLabel={t('employees')} onSelect={onSelectView} /><ViewLink view="work" current={view} icon="work" label={t('workCenter')} accessibleLabel={t('work')} onSelect={onSelectView} /></div><div className={styles.railCard}><CompanyIcon name="sparkles" /><strong>{t('companyTipTitle')}</strong><span>{t('companyTipBody')}</span></div>{onOpenSettings !== undefined && <button className={styles.settingsButton} type="button" onClick={onOpenSettings}><CompanyIcon name="settings" />{t('apiSettings')}</button>}</nav></aside>
}

export function CompanyMobileNavigation({ view, onSelectView, t }: { readonly view: CompanyView; readonly onSelectView: (view: CompanyView) => void; readonly t: Translate }) {
  return <nav className={styles.mobileNavigation} aria-label={t('mobileCompanyNavigation')}><ViewLink view="chat" current={view} icon="chat" label={t('companyChat')} accessibleLabel={`${t('mobileCompanyNavigation')} · ${t('companyChat')}`} onSelect={onSelectView} /><ViewLink view="employees" current={view} icon="employees" label={t('employeeCenter')} accessibleLabel={`${t('mobileCompanyNavigation')} · ${t('employeeCenter')}`} onSelect={onSelectView} /><ViewLink view="work" current={view} icon="work" label={t('workCenter')} accessibleLabel={`${t('mobileCompanyNavigation')} · ${t('workCenter')}`} onSelect={onSelectView} /></nav>
}

export function CompanyPageHeader({ eyebrow, title, description, action }: { readonly eyebrow: string; readonly title: string; readonly description: string; readonly action?: ReactNode }) { return <header className={styles.pageHeader}><div><span>{eyebrow}</span><h2>{title}</h2><p>{description}</p></div>{action}</header> }
export function CompanyStats({ items }: { readonly items: readonly { readonly label: string; readonly value: string | number; readonly tone?: string }[] }) { return <dl className={styles.stats}>{items.map(item => <div key={item.label} data-tone={item.tone}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl> }
export function CompanyEmptyState({ icon = 'sparkles', title, description, children }: { readonly icon?: CompanyIconName; readonly title: string; readonly description: string; readonly children?: ReactNode }) { return <div className={styles.emptyState}><span><CompanyIcon name={icon} /></span><h3>{title}</h3><p>{description}</p>{children}</div> }

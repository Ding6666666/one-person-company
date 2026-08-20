import type { PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type {} from '@deepseek-ai/dsh-client-ui-sidebar/client'

import { NS } from './locales.js'
import styles from './CompanyLauncher.module.css'

export type CompanyLauncherProps = PropsRuntime<'sidebar.footer.action'> & PropsLocale<typeof NS> & {
  readonly onOpen: () => void
}

export function CompanyLauncher({ wide, onOpen, t }: CompanyLauncherProps) {
  return <button className={styles.launcher} type="button" aria-label={t('title')} onClick={onOpen}>
    <span aria-hidden="true">◇</span>{wide && <span>{t('title')}</span>}
  </button>
}

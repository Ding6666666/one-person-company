import type { CompanyEvent } from './api.js'
import type { Translate } from './locales.js'
import styles from './Work.module.css'

export function CompanyHistory({ events, t }: { readonly events: readonly CompanyEvent[]; readonly t: Translate }) {
  return <section className={styles.history} role="log" aria-live="polite" aria-label={t('companyEvents')}>
    <h3>{t('companyEvents')}</h3>
    {events.length === 0 && <p>{t('emptyEvents')}</p>}
    <ol>
      {events.map(event => <li key={event.id}>
        <span className={styles.eventType}>{event.event_type}</span>
        <span>{event.summary}</span>
      </li>)}
    </ol>
  </section>
}

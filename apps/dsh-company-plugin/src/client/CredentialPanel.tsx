import { type FormEvent, useEffect, useState } from 'react'

import type { Translate } from './locales.js'
import { Button, Field } from './ui/Primitives.js'
import styles from './CredentialPanel.module.css'

export interface CredentialView {
  readonly configured: boolean
  readonly source?: string | undefined
  readonly writable: boolean
}

export interface CompanyCredentials {
  describe(): Promise<CredentialView>
  set(value: string): Promise<void>
  unset(): Promise<void>
}

export function CredentialPanel({ credentials, t }: {
  readonly credentials: CompanyCredentials
  readonly t: Translate
}) {
  const [view, setView] = useState<CredentialView>()
  const [value, setValue] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string>()

  const refresh = async (): Promise<void> => {
    try {
      setView(await credentials.describe())
      setError(undefined)
    } catch {
      setError(t('apiStatusFailed'))
    }
  }

  useEffect(() => {
    let active = true
    void credentials.describe().then(
      next => { if (active) { setView(next); setError(undefined) } },
      () => { if (active) setError(t('apiStatusFailed')) },
    )
    return () => { active = false }
  }, [credentials, t])

  const save = async (event: FormEvent): Promise<void> => {
    event.preventDefault()
    const next = value.trim()
    if (!next || view?.writable === false) return
    setPending(true)
    setError(undefined)
    try {
      await credentials.set(next)
      setValue('')
      await refresh()
    } catch {
      setError(t('apiSaveFailed'))
    } finally {
      setPending(false)
    }
  }

  const clear = async (): Promise<void> => {
    if (view?.writable !== true || !globalThis.confirm(t('confirmClearApiKey'))) return
    setPending(true)
    setError(undefined)
    try {
      await credentials.unset()
      setValue('')
      await refresh()
    } catch {
      setError(t('apiClearFailed'))
    } finally {
      setPending(false)
    }
  }

  const readOnly = view?.writable === false
  return <section className={styles.panel}>
    <div className={styles.status} data-configured={view?.configured ?? false}>
      <span className={styles.statusDot} />
      <div>
        <strong>{view?.configured ? t('apiConfigured') : t('apiNotConfigured')}</strong>
        <p>{readOnly ? t('apiManagedByEnvironment') : t('apiStoredByDsh')}</p>
      </div>
    </div>
    <form className={styles.form} onSubmit={event => { void save(event) }}>
      <Field label={t('newApiKey')} error={error}>
        <input
          type="password"
          autoComplete="new-password"
          value={value}
          disabled={pending || readOnly}
          placeholder={t('apiKeyPlaceholder')}
          onChange={event => setValue(event.target.value)}
        />
      </Field>
      <p className={styles.hint}>{t('apiKeyWriteOnlyHint')}</p>
      <Button type="submit" disabled={pending || readOnly || !value.trim()}>
        {t('saveNewApiKey')}
      </Button>
      <button
        className={styles.clearButton}
        type="button"
        disabled={pending || readOnly || !view?.configured}
        onClick={() => { void clear() }}
      >
        {t('clearApiKey')}
      </button>
    </form>
  </section>
}

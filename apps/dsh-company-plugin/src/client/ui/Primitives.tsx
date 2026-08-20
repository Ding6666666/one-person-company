import {
  type ButtonHTMLAttributes,
  cloneElement,
  type HTMLAttributes,
  type ReactElement,
  type ReactNode,
  useEffect,
  useId,
  useRef,
} from 'react'

import styles from '../Primitives.module.css'

export function Button(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...props} className={`${styles.button} ${props.className ?? ''}`} />
}

export function Field({ label, error, children }: {
  readonly label: string
  readonly error?: string | undefined
  readonly children: ReactElement<{
    readonly id?: string
    readonly 'aria-describedby'?: string
    readonly 'aria-invalid'?: boolean
  }>
}) {
  const inputId = useId()
  const errorId = useId()
  const control = cloneElement(children, {
    id: children.props.id ?? inputId,
    ...(error === undefined ? {} : { 'aria-describedby': errorId, 'aria-invalid': true }),
  })
  return <div className={styles.field}>
    <label htmlFor={control.props.id}>{label}</label>
    {control}
    {error !== undefined && <span id={errorId} className={styles.error} role="alert">{error}</span>}
  </div>
}

const focusableSelector = [
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[href]',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function Dialog({ title, onClose, children, ...props }: {
  readonly title: string
  readonly onClose: () => void
  readonly children: ReactNode
} & Omit<HTMLAttributes<HTMLDivElement>, 'title'>) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : undefined
    const node = panel.current
    const first = node?.querySelector<HTMLElement>(focusableSelector)
    first?.focus()
    const keydown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || node === null) return
      const focusable = [...node.querySelectorAll<HTMLElement>(focusableSelector)]
      const firstItem = focusable[0]
      const lastItem = focusable.at(-1)
      if (firstItem === undefined || lastItem === undefined) return
      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault()
        lastItem.focus()
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault()
        firstItem.focus()
      }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      document.removeEventListener('keydown', keydown)
      trigger?.focus()
    }
  }, [onClose])

  return <div className={styles.backdrop}>
    <div {...props} ref={panel} className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <h2 id={titleId}>{title}</h2>
      {children}
    </div>
  </div>
}

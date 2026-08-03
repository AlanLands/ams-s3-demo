import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Modal } from '../s3/components'

/**
 * One card per job on the admin page.
 *
 * The heading is a real `h2` with the section labelled by it, so the page reads
 * as four jobs in a screen-reader's landmark/heading list rather than one long
 * run of controls. `tone="danger"` adds the left rule — the same idiom
 * `.ams-scm-card` already uses to mark a panel as carrying a caveat — so a
 * destructive section is distinguishable before you read a word of it.
 */
export function AdminSection({
  title,
  description,
  tone = 'default',
  actions,
  children,
}: {
  title: string
  description?: ReactNode
  tone?: 'default' | 'danger'
  actions?: ReactNode
  children: ReactNode
}) {
  const headingId = useId()
  return (
    <section
      className={`ams-card ams-admin-section${tone === 'danger' ? ' ams-admin-section-danger' : ''}`}
      aria-labelledby={headingId}
    >
      <div className="ams-admin-section-head">
        <h2 className="ams-admin-section-title" id={headingId}>
          {title}
        </h2>
        {actions && <div className="ams-admin-row-actions">{actions}</div>}
      </div>
      {description && <p className="ams-stage-note">{description}</p>}
      {children}
    </section>
  )
}

/**
 * A shell command the console could not run for you.
 *
 * Rendered as selectable monospace text plus an explicit copy control, never as
 * a toast that disappears — when `ok: false` comes back from a service action,
 * this string is the entire remedy and the presenter is mid-demo.
 */
export function CopyableCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState<'idle' | 'done' | 'failed'>('idle')

  useEffect(() => {
    if (copied === 'idle') return
    const timer = window.setTimeout(() => setCopied('idle'), 2500)
    return () => window.clearTimeout(timer)
  }, [copied])

  return (
    <div className="ams-admin-cmd">
      <code className="ams-plan-command">{command}</code>
      <button
        type="button"
        className="ams-button-secondary ams-button-compact"
        onClick={async () => {
          // clipboard is undefined on an insecure origin, so a failure is
          // expected rather than exceptional — say so instead of silently
          // doing nothing, because the text above is still selectable.
          try {
            await navigator.clipboard.writeText(command)
            setCopied('done')
          } catch {
            setCopied('failed')
          }
        }}
      >
        Copy
      </button>
      <span role="status" aria-live="polite" className="ams-admin-cmd-status">
        {copied === 'done' ? 'Copied' : copied === 'failed' ? 'Copy blocked — select it above' : ''}
      </span>
    </div>
  )
}

/**
 * A bounded, scrollable list of paths. Long lists are the norm here (a reset
 * preview can name every file in a target), and letting one push the confirm
 * button off screen is how a dialog stops being read.
 */
export function PathList({
  label,
  paths,
  emptyLabel,
  tone = 'default',
}: {
  label: string
  paths: string[]
  emptyLabel?: string
  tone?: 'default' | 'danger'
}) {
  const labelId = useId()
  if (paths.length === 0 && !emptyLabel) return null
  return (
    <div className="ams-admin-pathgroup">
      <p className="ams-admin-pathgroup-label" id={labelId}>
        {label} <span className="ams-admin-count">({paths.length})</span>
      </p>
      {paths.length === 0 ? (
        <p className="ams-admin-pathgroup-empty">{emptyLabel}</p>
      ) : (
        <ul
          className={`ams-admin-files${tone === 'danger' ? ' ams-admin-files-danger' : ''}`}
          aria-labelledby={labelId}
        >
          {paths.map((path) => (
            <li key={path}>{path}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export type BannerTone = 'info' | 'warn' | 'danger' | 'good'

const BANNER_ICON: Record<BannerTone, string> = {
  info: 'i',
  warn: '!',
  danger: '!',
  good: '✓',
}

/**
 * Blocked reasons, warnings and results. Icon + heading text carry the meaning;
 * colour only reinforces it, so the panel survives a projector and greyscale.
 */
export function Banner({
  tone,
  title,
  children,
}: {
  tone: BannerTone
  title: string
  children?: ReactNode
}) {
  return (
    <div className={`ams-admin-banner ams-admin-banner-${tone}`}>
      <span className="ams-admin-banner-icon" aria-hidden="true">
        {BANNER_ICON[tone]}
      </span>
      <div>
        <strong className="ams-admin-banner-title">{title}</strong>
        {children}
      </div>
    </div>
  )
}

/**
 * The one confirmation dialog every destructive action on this page goes
 * through.
 *
 * Three things make it deliberate rather than a reflexive OK:
 *  - it will not enable the confirm until the caller has actually loaded the
 *    preview (`ready`), so you cannot approve a change you were never shown;
 *  - it requires the scope name typed out, so muscle memory alone cannot fire
 *    it;
 *  - it refuses outright when `blockedReason` is set, which is how the
 *    `reset_safe` gate is honoured client-side instead of firing a request we
 *    already know answers 409.
 */
export function ConfirmDialog({
  title,
  subtitle,
  confirmWord,
  confirmLabel,
  ready,
  busy,
  blockedReason,
  error,
  onConfirm,
  onClose,
  children,
}: {
  title: string
  subtitle?: ReactNode
  confirmWord: string
  confirmLabel: string
  ready: boolean
  busy: boolean
  blockedReason?: string | null
  error?: string | null
  onConfirm: () => void
  onClose: () => void
  children: ReactNode
}) {
  const [typed, setTyped] = useState('')
  const inputId = useId()
  const hintId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const blocked = !!blockedReason
  const canConfirm = ready && !busy && !blocked && typed.trim() === confirmWord

  // Modal focuses its own panel in an effect, and a child's effect runs first —
  // so an autoFocus here would be overwritten. A frame later is after both, and
  // it puts a keyboard user on the field that actually gates the action.
  useEffect(() => {
    if (blocked || !ready) return
    const frame = requestAnimationFrame(() => inputRef.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [blocked, ready])

  return (
    <Modal title={title} subtitle={subtitle} onClose={onClose} size="lg">
      {children}
      {blocked ? (
        // No confirm control at all when blocked, rather than a disabled one:
        // there is nothing to fill in and nothing that would enable it from
        // here. Cancel is spelled out so the dialog is not escapable only by
        // the × in its corner.
        <>
          <Banner tone="danger" title="Blocked — this reset is not available">
            <p className="ams-admin-banner-body">{blockedReason}</p>
          </Banner>
          <div className="ams-admin-confirm-actions">
            <button type="button" className="ams-button-secondary" onClick={onClose}>
              Close
            </button>
          </div>
        </>
      ) : (
        <form
          className="ams-admin-confirm"
          onSubmit={(event) => {
            event.preventDefault()
            if (canConfirm) onConfirm()
          }}
        >
          <label className="ams-field-label" htmlFor={inputId}>
            Type <span className="ams-admin-confirm-word">{confirmWord}</span> to confirm
          </label>
          <input
            id={inputId}
            ref={inputRef}
            className="ams-input"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            disabled={!ready || busy}
            autoComplete="off"
            spellCheck={false}
            aria-describedby={hintId}
          />
          <p className="ams-field-hint" id={hintId}>
            {ready
              ? 'This cannot be undone from the console.'
              : 'Waiting for the preview — nothing can be confirmed until you have seen what changes.'}
          </p>
          {error && (
            <Banner tone="danger" title="The reset did not run">
              <p className="ams-admin-banner-body">{error}</p>
            </Banner>
          )}
          <div className="ams-admin-confirm-actions">
            <button type="button" className="ams-button-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="ams-button-danger" disabled={!canConfirm}>
              {busy ? 'Working…' : confirmLabel}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}

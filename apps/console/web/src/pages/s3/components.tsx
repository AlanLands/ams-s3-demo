import { Fragment, useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useS3, type S3Stage } from './context'
import StageNav from './StageNav'
import { parseDiff } from './utils'
import type { TestCaseResult, TestsRunResponse } from '../../api_s3'

export function StageFrame({
  stageId,
  title,
  activity,
  children,
}: {
  stageId: S3Stage['id']
  title: string
  activity: string
  children: ReactNode
}) {
  const { stages } = useS3()
  const headingRef = useRef<HTMLHeadingElement>(null)
  const stage = stages.find((candidate) => candidate.id === stageId)
  const locked = !!stage?.locked

  useEffect(() => {
    headingRef.current?.focus()
  }, [stageId])

  return (
    <section className="ams-stage-view" aria-labelledby={`s3-stage-${stageId}`}>
      <h2 id={`s3-stage-${stageId}`} tabIndex={-1} ref={headingRef}>
        {title}
      </h2>
      {/* Activity only. A locked stage has no activity, and putting its reason
          here too would print it twice on screen and read it twice aloud — the
          reason already sits in the body below, right under the heading focus
          lands on. */}
      <div role="status" aria-live="polite" className="ams-stage-live">
        {locked ? '' : activity}
      </div>
      {/* A locked stage renders its reason instead of its body — never the body
          itself. The rail and StageNav already refuse to link here, but a stage
          is now a URL: a typed address, a stale bookmark, or Back after state
          was reset all reach it directly. The gates alone would not stop that,
          because the action buttons inside only guard against double-submit
          (`disabled={generating}`), never against their own gate — the old
          StageCard enforced it structurally by not rendering children when
          locked, and this is that guarantee restored in the one place every
          stage passes through. Without it, opening /s3/release before the
          tests run offers a live "Draft release notes" button. */}
      {locked ? (
        <div className="ams-stage-locked">
          <p className="ams-stage-locked-label">Not available yet</p>
          <p className="ams-stage-hint">
            {stage?.lockedReason ?? 'This stage is not available yet.'}
          </p>
        </div>
      ) : (
        children
      )}
      <StageNav stageId={stageId} />
    </section>
  )
}

// Per-test checklist parsed from the runner's JUnit XML — the readable
// alternative to the raw pytest dump (which stays available behind a
// "runner output" disclosure below the table).
export function TestCaseTable({ cases }: { cases: TestCaseResult[] }) {
  if (cases.length === 0) return null
  const icon = (status: TestCaseResult['status']) =>
    status === 'passed' ? '✓' : status === 'skipped' ? '○' : '✗'
  const color = (status: TestCaseResult['status']) =>
    status === 'passed'
      ? 'var(--ams-success)'
      : status === 'skipped'
        ? 'var(--ams-ink-soft)'
        : 'var(--ams-error)'
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '0.6rem' }}>
      <tbody>
        {cases.map((testCase) => (
          <Fragment key={`${testCase.classname}.${testCase.name}`}>
            <tr style={{ borderTop: '1px solid var(--ams-line)' }}>
              <td
                style={{
                  color: color(testCase.status),
                  fontWeight: 700,
                  padding: '0.35rem 0.5rem 0.35rem 0.2rem',
                  width: '1.4rem',
                }}
              >
                {icon(testCase.status)}
              </td>
              <td style={{ padding: '0.35rem 0.5rem', fontSize: 'var(--ams-text-sm)' }}>
                {testCase.description}
                <div
                  style={{
                    fontFamily: 'ui-monospace, monospace',
                    fontSize: 'var(--ams-text-xs)',
                    color: 'var(--ams-ink-soft)',
                  }}
                >
                  {testCase.name}
                </div>
              </td>
              <td
                style={{
                  padding: '0.35rem 0.2rem',
                  fontSize: 'var(--ams-text-xs)',
                  color: 'var(--ams-ink-soft)',
                  textAlign: 'right',
                  whiteSpace: 'nowrap',
                  verticalAlign: 'top',
                }}
              >
                {testCase.time_s >= 1
                  ? `${testCase.time_s.toFixed(2)} s`
                  : `${Math.max(1, Math.round(testCase.time_s * 1000))} ms`}
              </td>
            </tr>
            {testCase.message && testCase.status !== 'passed' && (
              <tr>
                <td />
                <td
                  colSpan={2}
                  style={{
                    padding: '0 0.5rem 0.5rem',
                    fontSize: 'var(--ams-text-xs)',
                    fontFamily: 'ui-monospace, monospace',
                    color: 'var(--ams-error)',
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {testCase.message}
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  )
}

// Structural, not nominal: the regression run carries no AI `label`, and this
// line only ever reads the three counters.
export function RunSummaryLine({
  run,
}: {
  run: Pick<TestsRunResponse, 'passed' | 'summary' | 'duration_s'>
}) {
  const parts: string[] = [`${run.summary.passed} passed`]
  if (run.summary.failed) parts.push(`${run.summary.failed} failed`)
  if (run.summary.errors) parts.push(`${run.summary.errors} errored`)
  if (run.summary.skipped) parts.push(`${run.summary.skipped} skipped`)
  return (
    <p style={{ margin: '0.4rem 0 0', fontSize: 'var(--ams-text-sm)' }}>
      <strong style={{ color: run.passed ? 'var(--ams-success)' : 'var(--ams-error)' }}>
        {parts.join(', ')}
      </strong>{' '}
      <span style={{ color: 'var(--ams-ink-soft)' }}>in {run.duration_s.toFixed(1)} s</span>
    </p>
  )
}

// --- Progressive disclosure ---------------------------------------------------
// The stages used to render every artifact — release notes, the design doc, the
// full test checklist, the deploy plan — stacked inline, which buried the one
// thing a non-technical viewer is following: the flow itself. The rule now is
// that a stage shows the action, a one-line status, and a compact summary that
// proves the artifact exists; the body of the artifact opens in a dialog.
//
// Nothing here changes behaviour, gating, or an API call. It only decides what
// is on screen before you ask for it.

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'summary',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

// Ref-counted, because the design doc's dialog can sit under a nested one later
// and the first to close must not unlock the page behind the second.
let openDialogCount = 0
let bodyOverflowBeforeLock = ''

/**
 * The console's one overlay dialog for artifact bodies.
 *
 * Renders through a portal on `document.body` so a stage's own stacking and
 * overflow can never clip it, and so the backdrop covers the stage rail too —
 * the rail is navigation, and navigating away mid-read is exactly what a modal
 * is supposed to suspend.
 *
 * Mount = open. The caller renders `{open && <Modal .../>}`, which keeps focus
 * capture/restore tied to the component lifecycle rather than to a prop the
 * caller has to remember to drive both ways.
 */
export function Modal({
  title,
  subtitle,
  onClose,
  children,
  size = 'md',
}: {
  title: string
  subtitle?: ReactNode
  onClose: () => void
  children: ReactNode
  size?: 'md' | 'lg'
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const headingId = useId()

  // Focus moves into the dialog on open and back to whatever opened it on
  // close — without the restore, dismissing drops a keyboard user at the top
  // of the document and they have to tab the whole stage again to get back.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    panelRef.current?.focus()
    return () => opener?.focus?.()
  }, [])

  // The page behind a modal must not scroll: on a trackpad the backdrop scrolls
  // the stage underneath it, so closing lands you somewhere you never chose.
  useEffect(() => {
    if (openDialogCount === 0) bodyOverflowBeforeLock = document.body.style.overflow
    openDialogCount += 1
    document.body.style.overflow = 'hidden'
    return () => {
      openDialogCount -= 1
      if (openDialogCount === 0) document.body.style.overflow = bodyOverflowBeforeLock
    }
  }, [])

  // Escape to dismiss, and Tab cycles inside the panel. Bound on the document
  // rather than the panel so Escape still works when focus sits on the panel
  // itself, which is where it starts.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const panel = panelRef.current
      if (!panel) return
      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      ).filter((node) => node.offsetParent !== null || node === document.activeElement)
      if (focusable.length === 0) {
        // Nothing to land on but the panel — keep focus here rather than
        // letting Tab walk off into the inert page behind the backdrop.
        event.preventDefault()
        panel.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement
      const inside = active instanceof Node && panel.contains(active) && active !== panel
      if (event.shiftKey) {
        if (!inside || active === first) {
          event.preventDefault()
          last.focus()
        }
      } else if (!inside || active === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return createPortal(
    // mousedown, not click: a click that *began* inside the panel and ended on
    // the backdrop is a text selection dragged past the edge, not a dismissal.
    <div
      className="ams-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className={`ams-sheet${size === 'lg' ? ' ams-sheet-lg' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        tabIndex={-1}
        ref={panelRef}
      >
        <div className="ams-sheet-header">
          <div className="ams-sheet-heading">
            <h2 className="ams-sheet-title" id={headingId}>
              {title}
            </h2>
            {subtitle && <p className="ams-sheet-subtitle">{subtitle}</p>}
          </div>
          <button
            type="button"
            className="ams-modal-close"
            onClick={onClose}
            aria-label={`Close ${title}`}
          >
            ×
          </button>
        </div>
        <div className="ams-sheet-body">{children}</div>
      </div>
    </div>,
    document.body
  )
}

export type ChipTone = 'pass' | 'fail' | 'warn' | 'neutral'

// Icon *and* wording carry the state — colour never does it alone, and the
// label reads correctly with the glyph stripped out by a screen reader.
const CHIP_ICON: Record<ChipTone, string> = { pass: '✓', fail: '✗', warn: '!', neutral: '' }

export function Chip({ tone = 'neutral', children }: { tone?: ChipTone; children: ReactNode }) {
  const icon = CHIP_ICON[tone]
  return (
    <span className={`ams-chip ams-chip-${tone}`}>
      {icon && (
        <span className="ams-chip-icon" aria-hidden="true">
          {icon}
        </span>
      )}
      {children}
    </span>
  )
}

/**
 * The compact stand-in an artifact leaves in the main flow: what it is, how big
 * it is, whether it passed, and the button that opens it. Deliberately fixed
 * shape — every stage's summary should read the same way from the back of a
 * room, which it will not if each one invents its own layout.
 */
export function ArtifactSummary({
  title,
  detail,
  chips,
  actions,
}: {
  title: string
  detail?: ReactNode
  chips?: ReactNode
  actions: ReactNode
}) {
  return (
    <div className="ams-card ams-artifact">
      <div className="ams-artifact-text">
        <div className="ams-artifact-head">
          <strong className="ams-artifact-title">{title}</strong>
          {chips}
        </div>
        {detail && <div className="ams-artifact-detail">{detail}</div>}
      </div>
      <div className="ams-artifact-actions">{actions}</div>
    </div>
  )
}

// One rendering of a unified diff, previously copy-pasted into four places —
// now that three of them live inside a dialog, they must not drift apart.
export function DiffView({ diffText }: { diffText: string }) {
  return (
    <>
      {parseDiff(diffText).map((file) => (
        <div key={file.path} className="ams-diff-file">
          <div className="ams-diff-file-header">
            <span>{file.path}</span>
          </div>
          <div className="ams-diff-body">
            {file.lines.map((line, index) => (
              <div
                key={index}
                className={`ams-diff-line${line.type !== 'context' ? ` ams-diff-line-${line.type}` : ''}`}
              >
                {line.text}
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  )
}

// The raw runner dump, tucked behind a disclosure so the parsed table leads.
export function RunnerOutput({ output }: { output: string }) {
  if (!output.trim()) return null
  return (
    <details style={{ marginTop: '0.6rem' }}>
      <summary style={{ cursor: 'pointer', fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>
        Show runner output
      </summary>
      <pre style={{ fontSize: 'var(--ams-text-xs)', overflowX: 'auto', whiteSpace: 'pre-wrap', marginTop: '0.4rem' }}>
        {output}
      </pre>
    </details>
  )
}

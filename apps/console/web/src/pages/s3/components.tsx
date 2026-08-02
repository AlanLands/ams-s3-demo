import { Fragment, useEffect, useRef, type ReactNode } from 'react'
import { useS3, type S3Stage } from './context'
import StageNav from './StageNav'
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

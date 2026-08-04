import type { ScmResponse, ScmState } from './api_s3'

/**
 * The source-control flow around Apply: branch → commit → push.
 *
 * Apply writes the reviewed change into the working tree, which shows *what the
 * AI produced* but skips the part every reviewer asks about — you do not edit
 * main. This panel supplies the missing frame.
 *
 * None of it runs git. The transcript is rendered from recorded state, the push
 * contacts nothing, and every state carries `simulated: true`. That is a
 * deliberate constraint, not an unfinished feature: the target apps live inside
 * this repo and the demo reset scripts restore their baseline from HEAD, so a
 * real commit would make the resets start restoring the user story instead. The banner
 * below says so on screen, and the release record repeats it under "Not
 * evidenced by this release". See s3_enhancement/scm.py.
 */

const STEPS: { key: ScmState['status']; label: string; hint: string }[] = [
  { key: 'open', label: 'Branch', hint: 'cut from main before anything was written' },
  { key: 'applied', label: 'Apply', hint: 'reviewed files written onto the branch' },
  { key: 'committed', label: 'Commit', hint: 'gated on the tests passing' },
  { key: 'pushed', label: 'Push', hint: 'hands off to the deployment pipeline' },
]

function stepIndex(status: ScmState['status']): number {
  if (status === 'abandoned') return -1
  const index = STEPS.findIndex((step) => step.key === status)
  return index < 0 ? 0 : index
}

function Flow({ status }: { status: ScmState['status'] }) {
  const reached = stepIndex(status)
  return (
    <ol className="ams-scm-flow">
      {STEPS.map((step, index) => (
        <li
          key={step.key}
          className={
            'ams-scm-step' +
            (index <= reached ? ' ams-scm-step-done' : '') +
            (status === 'abandoned' ? ' ams-scm-step-void' : '')
          }
        >
          <span className="ams-scm-step-label">{step.label}</span>
          <span className="ams-scm-step-hint">{step.hint}</span>
        </li>
      ))}
    </ol>
  )
}

function Evidence({ evidence }: { evidence: ScmResponse['test_evidence'] }) {
  const rows: { name: string; state: ScmResponse['test_evidence']['generated_suite'] }[] = [
    { name: 'Generated suite', state: evidence.generated_suite },
    { name: 'Regression (pre-existing)', state: evidence.regression_suite },
  ]
  return (
    <div className="ams-scm-evidence">
      {rows.map(({ name, state }) => (
        <div key={name} className="ams-scm-evidence-row">
          <span className="ams-scm-evidence-name">{name}</span>
          {/* "Not run" and "ran and failed" are different claims, so they get
              different words — collapsing them is how "not run" becomes green. */}
          {state === null ? (
            <span className="ams-scm-evidence-none">not run</span>
          ) : (
            <span className={state.passed ? 'ams-scm-ok' : 'ams-scm-bad'}>
              {state.passed ? '✓' : '✗'} {state.detail}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}

export function ScmPanel({
  state,
  blockers,
  evidence,
  committing,
  pushing,
  error,
  detail,
  onCommit,
  onPush,
  readOnly = false,
}: {
  state: ScmState
  blockers: string[]
  evidence: ScmResponse['test_evidence']
  committing: boolean
  pushing: boolean
  error: string | null
  detail: string | null
  onCommit: () => void
  onPush: () => void
  // The engineer sees this panel on their own stage so the branch they cut
  // and the files they applied are visible, but commit is gated on a test
  // run they do not perform — the action belongs to whoever can open that
  // gate. Read-only shows the same flow without offering a button that
  // cannot be unblocked from here.
  readOnly?: boolean
}) {
  const gateOpen = blockers.length === 0
  const canCommit = state.commit === null && state.staged_files.length > 0 && !state.abandoned_at
  const canPush = state.commit !== null && !state.pushed_at && !state.abandoned_at

  return (
    <div className="ams-card ams-scm-card">
      <div className="ams-scm-head">
        <div>
          <div className="ams-modal-section-title">Source control</div>
          <code className="ams-scm-branch">{state.branch}</code>
          <span className="ams-scm-base">off {state.base}</span>
        </div>
        <span className={`ams-scm-status ams-scm-status-${state.status}`}>{state.status}</span>
      </div>

      {/* Stated up front rather than in a footnote: the whole panel describes
          work that did not happen in a real repo, and a reader who skims the
          branch name and stops must not walk away thinking git ran. */}
      <p className="ams-scm-simulated">
        Modelled, not executed — this console does not run git or contact a remote. The
        release record repeats this under “Not evidenced by this release”.
      </p>

      <Flow status={state.status} />

      {state.abandoned_at && (
        <p className="ams-scm-abandoned">
          Branch abandoned: every applied file was reverted.
          {state.commit && ' The commit that was already made is not unmade — in a real repo the honest undo at that point is a revert commit, not a rewritten history.'}
        </p>
      )}

      <Evidence evidence={evidence} />

      {!gateOpen && canCommit && (
        <div className="ams-scm-blockers">
          <strong>Not ready to commit</strong>
          <ul>
            {blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </div>
      )}

      {state.commit && (
        <div className="ams-scm-commit">
          <code>{state.commit.sha}</code> {state.commit.message}
          <span className="ams-scm-commit-meta">
            {state.commit.files.length} file{state.commit.files.length === 1 ? '' : 's'} ·{' '}
            {state.commit.committed_at}
          </span>
        </div>
      )}

      {state.pushed_at && (
        <p className="ams-scm-pipeline">
          Pipeline <code>{state.pipeline_id}</code> would be queued for {state.branch}. No build
          ran.
        </p>
      )}

      {readOnly && (canCommit || canPush) && (
        <p className="ams-scm-detail">
          Commit and push sit with QA — the gate is the test run, so it opens on
          the tester's stage.
        </p>
      )}

      <div className="ams-scm-actions">
        {!readOnly && canCommit && (
          <button
            className="ams-button"
            onClick={onCommit}
            disabled={committing || !gateOpen}
            title={gateOpen ? undefined : blockers.join(' ')}
          >
            {committing ? 'Committing…' : 'Commit to branch'}
          </button>
        )}
        {!readOnly && canPush && (
          <button className="ams-button" onClick={onPush} disabled={pushing}>
            {pushing ? 'Pushing…' : 'Push and trigger pipeline'}
          </button>
        )}
      </div>

      {error && <p className="ams-scm-error">{error}</p>}
      {detail && <p className="ams-scm-detail">{detail}</p>}

      {state.transcript.length > 0 && (
        <details className="ams-scm-transcript">
          <summary>What a real integration would have run</summary>
          <pre>{state.transcript.join('\n')}</pre>
        </details>
      )}
    </div>
  )
}

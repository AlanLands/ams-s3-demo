import { useState } from 'react'
import type { DeploymentPlan, PlanStep, ReleaseNoteSet } from './api_s3'

const NOTE_SECTIONS: {
  key: keyof ReleaseNoteSet
  title: string
  audience: string
}[] = [
  { key: 'changelog', title: 'Client change log', audience: 'goes to the customer' },
  { key: 'ops_note', title: 'Internal operations note', audience: 'goes to whoever runs the app' },
  { key: 'whats_new', title: 'User guide — what’s new', audience: 'goes on the help page' },
]

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      className="ams-modal-link ams-note-copy"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1600)
        } catch {
          // Clipboard is permission-gated and unavailable over plain HTTP on
          // some setups; the text is on screen either way, so this is a
          // convenience that is allowed to fail quietly.
          setCopied(false)
        }
      }}
    >
      {copied ? '✓ Copied' : 'Copy'}
    </button>
  )
}

/**
 * The release note, written three times for three readers.
 *
 * These used to be one text blob containing a client note and a doc blurb,
 * which meant anyone who needed one of them deleted the other by hand. They
 * end up in three different places, so they are three fields with their own
 * copy button.
 */
export function ReleaseNotes({ notes }: { notes: ReleaseNoteSet }) {
  return (
    <div>
      {NOTE_SECTIONS.map(({ key, title, audience }) => (
        <div key={key} className="ams-note-block">
          <div className="ams-note-head">
            <span className="ams-note-title">{title}</span>
            <span className="ams-note-audience">{audience}</span>
            <CopyButton text={notes[key]} />
          </div>
          <p className="ams-note-body">{notes[key]}</p>
        </div>
      ))}
    </div>
  )
}

function StepList({ steps }: { steps: PlanStep[] }) {
  if (steps.length === 0) return <p className="ams-plan-empty">None.</p>
  return (
    <ol className="ams-plan-list">
      {steps.map((step) => (
        <li key={`${step.kind}-${step.order}`}>
          <span className={`ams-plan-kind ams-plan-kind-${step.kind}`}>{step.kind}</span>
          <strong>{step.title}</strong>
          <div className="ams-plan-detail">{step.detail}</div>
          {step.command && <code className="ams-plan-command">$ {step.command}</code>}
        </li>
      ))}
    </ol>
  )
}

/**
 * Deployment and rollback, derived rather than drafted — the order comes out
 * of the change's own service graph (see s3_enhancement/release.py).
 */
export function DeploymentPlanPanel({ plan }: { plan: DeploymentPlan }) {
  return (
    <div>
      {plan.order_reason && (
        <p className="ams-plan-reason">
          <strong>Order matters.</strong> {plan.order_reason}
        </p>
      )}
      <div className="ams-modal-section-title" style={{ marginTop: '0.6rem' }}>
        Deploy
      </div>
      <StepList steps={plan.steps} />
      <div className="ams-modal-section-title" style={{ marginTop: '0.9rem' }}>
        Rollback
      </div>
      <StepList steps={plan.rollback} />
      <p className="ams-plan-note">
        Derived from the change's file set and the target's declared migration and test
        commands — not drafted by a model.
      </p>
    </div>
  )
}

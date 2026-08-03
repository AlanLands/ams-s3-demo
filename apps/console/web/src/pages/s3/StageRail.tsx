import { Link, useLocation } from 'react-router-dom'
import type { S3Stage } from './context'

function stageState(stage: S3Stage, pathname: string) {
  if (pathname.endsWith(stage.path)) return 'current'
  if (stage.done) return 'done'
  if (stage.locked) return 'locked'
  return 'available'
}

export default function StageRail({
  activeTicketKey,
  crLabel,
  stages,
}: {
  activeTicketKey: string | null
  crLabel: string | null
  stages: S3Stage[]
}) {
  const { pathname } = useLocation()

  return (
    <nav className="ams-stage-rail" aria-label="Pipeline stages">
      <div className="ams-stage-rail-context">
        <span className="ams-eyebrow">Active work</span>
        <strong>{activeTicketKey ?? 'No ticket selected'}</strong>
        <span>{crLabel ?? 'Pick a ticket to resolve the CR context.'}</span>
      </div>
      <ol className="ams-stepper ams-stepper-rail">
        {stages.map((stage, index) => {
          const state = stageState(stage, pathname)
          const markerClass =
            state === 'done'
              ? 'ams-stepper-dot-done'
              : state === 'current'
                ? 'ams-stepper-dot-active'
                : state === 'locked'
                  ? 'ams-stepper-dot-locked'
                  : 'ams-stepper-dot-pending'
          const labelClass =
            state === 'done'
              ? 'ams-stepper-label-done'
              : state === 'current'
                ? 'ams-stepper-label-active'
                : 'ams-stepper-label-pending'
          const content = (
            <>
              <span className={`ams-stepper-dot ${markerClass}`}>{state === 'locked' ? '×' : index + 1}</span>
              <span className={`ams-stepper-label ${labelClass}`}>
                <strong>{stage.title}</strong>
                <span className="ams-stage-rail-state">
                  {state === 'current' ? 'Current' : state === 'done' ? 'Done' : state === 'locked' ? 'Locked' : 'Available'}
                </span>
                {stage.statusLabel && <span className="ams-stage-rail-status">{stage.statusLabel}</span>}
                {state === 'locked' && stage.lockedReason && (
                  <span className="ams-stage-rail-hint">{stage.lockedReason}</span>
                )}
              </span>
            </>
          )

          return (
            <li key={stage.id} className={`ams-stepper-stage ams-stepper-stage-${state}`}>
              {stage.locked ? (
                <span className="ams-stage-rail-item" aria-disabled="true">
                  {content}
                </span>
              ) : (
                <Link
                  className="ams-stage-rail-item"
                  to={stage.path}
                  aria-current={state === 'current' ? 'step' : undefined}
                >
                  {content}
                </Link>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

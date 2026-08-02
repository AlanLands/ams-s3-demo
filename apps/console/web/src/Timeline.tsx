// Ported from common/ui_timeline.py's render_timeline(): the audit-trail
// view every ticket detail page shows — who/what did each pipeline step
// (AI, a human approval, or the system), in order.

export interface TimelineEvent {
  actor: 'ai' | 'human' | 'system' | string
  action: string
  detail?: string
  ts?: string
}

const ACTOR_LABELS: Record<string, string> = {
  ai: 'AI',
  human: 'HUMAN APPROVAL',
  system: 'SYSTEM',
}

function Chip({ actor }: { actor: string }) {
  const label = ACTOR_LABELS[actor] ?? actor.toUpperCase()
  const actorClass = actor in ACTOR_LABELS ? actor : 'system'
  return <span className={`ams-timeline-chip ams-timeline-chip-${actorClass}`}>{label}</span>
}

export default function Timeline({ events }: { events: TimelineEvent[] }) {
  if (events.length === 0) {
    return <p style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-sm)' }}>No timeline events recorded yet.</p>
  }
  return (
    <div className="ams-timeline">
      {events.map((event, index) => (
        <div className="ams-timeline-item" key={index}>
          <div className="ams-timeline-top">
            <Chip actor={event.actor} />
            <span className="ams-timeline-action">
              {event.action.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
            </span>
            <span className="ams-timeline-ts">{event.ts}</span>
          </div>
          {event.detail && <div className="ams-timeline-detail">{event.detail}</div>}
        </div>
      ))}
    </div>
  )
}

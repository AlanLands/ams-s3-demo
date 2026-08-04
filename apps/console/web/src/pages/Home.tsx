import { Link } from 'react-router-dom'

interface ScenarioTile {
  code: string
  title: string
  description: string
  status: 'live' | 'preview'
  href: string
}

const SCENARIOS: ScenarioTile[] = [
  {
    code: 'S3',
    title: 'Enhancement Delivery',
    description: 'AI impact analysis, code generation, tests, docs, release notes.',
    status: 'live',
    href: '/s3',
  },
]

function StatusPill({ status }: { status: ScenarioTile['status'] }) {
  const label = status === 'live' ? 'Live' : 'Preview'
  const className = status === 'live' ? 'ams-pill ams-pill-live' : 'ams-pill ams-pill-preview'
  return <span className={className}>{label}</span>
}

export default function Home() {
  return (
    /* 760px, not 1100. This is a launcher, not a dashboard: at 1100px the rules
       and the heading ran three times the width of the one thing you can
       actually click, which reads as a page that failed to load the rest of its
       content. The container now sizes to its content. */
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '2rem 1.5rem' }}>
      <span className="ams-eyebrow">MapleSure Insurance · AMS Console</span>
      <h1 style={{ fontSize: 'var(--ams-text-2xl)', marginTop: '0.6rem' }}>AMS Service Console</h1>
      <p style={{ color: 'var(--ams-ink-soft)', maxWidth: '60ch', marginTop: '0.4rem' }}>
        Agentic applications for running the MapleSure application portfolio. Pick a scenario
        to open it.
      </p>

      {/* The metric row that used to sit here reported "Scenarios: 1" — counted
          from the hardcoded array below, so it could never say anything else,
          and it spent a rule-bounded band of the page saying it. A number that
          cannot vary is not a metric. (`.ams-metric-*` is still the right
          component and Admin uses it for figures that do move.) */}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: '1.1rem',
          marginTop: '1.75rem',
        }}
      >
        {SCENARIOS.map((scenario) => (
          /* Column flex so the CTA can be pushed to the card's bottom edge
             (`marginTop: auto` below) and every card's button lines up across
             the row regardless of how long its description runs. That replaces
             a `minHeight: 3.6em` on the paragraph, which reserved three lines
             for a two-line description and left a visible hole under it. */
          <div
            key={scenario.code}
            className="ams-card"
            style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}
          >
            {/* Per-child bottom margins are gone: the card is a flex column
                with a `gap`, so a margin here would stack on top of it and the
                rhythm would come from two competing sources. */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <span style={{ fontWeight: 600, color: 'var(--ams-accent-ink)' }}>
                {scenario.code}
              </span>
              <StatusPill status={scenario.status} />
            </div>
            <h3 style={{ fontSize: 'var(--ams-text-lg)', margin: 0 }}>{scenario.title}</h3>
            <p style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-sm)', margin: 0 }}>
              {scenario.description}
            </p>
            {/* `alignSelf` keeps the button hugging its label — a stretched
                inline-flex child would span the card. No display override:
                `.ams-button` is inline-flex now, and `inline-block` here would
                win and re-break the arrow's vertical centring. */}
            <Link
              to={scenario.href}
              className="ams-button"
              style={{ marginTop: 'auto', alignSelf: 'flex-start' }}
            >
              Open application →
            </Link>
          </div>
        ))}
      </div>
    </div>
  )
}

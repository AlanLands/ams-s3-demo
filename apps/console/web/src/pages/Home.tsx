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
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '2rem 1.5rem' }}>
      <span className="ams-eyebrow">MapleSure Insurance · AMS Console</span>
      <h1 style={{ fontSize: 'var(--ams-text-2xl)', marginTop: '0.6rem' }}>AMS Service Console</h1>
      <p style={{ color: 'var(--ams-ink-soft)', maxWidth: '60ch', marginTop: '0.4rem' }}>
        Agentic applications for running the MapleSure application portfolio. Pick a scenario
        to open it.
      </p>

      <div
        className="ams-metric-row"
        style={{
          borderTop: '1px solid var(--ams-line)',
          borderBottom: '1px solid var(--ams-line)',
          padding: '0.9rem 0',
        }}
      >
        <div className="ams-metric-tile">
          <div className="ams-metric-label">Scenarios</div>
          <div className="ams-metric-value">1</div>
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
          gap: '1.1rem',
          marginTop: '1.5rem',
        }}
      >
        {SCENARIOS.map((scenario) => (
          <div key={scenario.code} className="ams-card">
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '0.5rem',
              }}
            >
              <span style={{ fontWeight: 600, color: 'var(--ams-accent-ink)' }}>
                {scenario.code}
              </span>
              <StatusPill status={scenario.status} />
            </div>
            <h3 style={{ fontSize: 'var(--ams-text-lg)', marginBottom: '0.4rem' }}>{scenario.title}</h3>
            <p style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-sm)', minHeight: '3.6em' }}>
              {scenario.description}
            </p>
            {/* No display override — `.ams-button` is inline-flex now, and
                `inline-block` here would win and re-break the arrow's vertical
                centring. */}
            <Link to={scenario.href} className="ams-button">
              Open application →
            </Link>
          </div>
        ))}
      </div>
    </div>
  )
}

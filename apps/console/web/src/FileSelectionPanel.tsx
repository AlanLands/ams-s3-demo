import type { FileSelection } from './api_s3'

// Shared between the Generate stage (S3.tsx) and the impact-analysis modal
// (TicketModal.tsx) — both call endpoints that run file selection over the
// target's subsystems and return the same `file_selection` shape, so "how did
// the AI pick which part of the repo to touch" should look the same in both
// places instead of only ever showing up in one of them.
//
// apps/policycore/systems/*/DESIGN.md is a bank of decoy subsystems (several of them
// Java) this demo's screening step is meant to rule out — for CRs whose real
// core files aren't behind their own design doc, in_scope ends up empty and
// screened_out is the whole decoy bank. Screened-out entries must never look
// like part of the change (hence collapsed, unlabeled-as-used, by default) —
// otherwise "why is a Java subsystem in my Python-only change" is exactly
// what a reviewer sees.
export default function FileSelectionPanel({ selection }: { selection: FileSelection }) {
  const screen = selection.subsystem_screen
  const inScope = screen.in_scope
    .map((name) => ({ name, score: screen.scores[name] }))
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
  const screenedOut = screen.screened_out
    .map((name) => ({ name, score: screen.scores[name] }))
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))

  return (
    <div className="ams-card" style={{ marginTop: '0.75rem' }}>
      <div style={{ display: 'flex', gap: '2rem' }}>
        <div>
          <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)' }}>Files in this app</div>
          <div style={{ fontWeight: 700 }}>{selection.candidate_pool_size}</div>
        </div>
        <div>
          <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)' }}>
            Files used for this change
          </div>
          <div style={{ fontWeight: 700 }}>{selection.selected_files.length}</div>
        </div>
      </div>

      <div style={{ marginTop: '0.75rem' }}>
        <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)', marginBottom: '0.35rem' }}>
          Which part of the repo the AI matched this change to
        </div>
        {inScope.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
            {inScope.map(({ name, score }) => (
              <SubsystemRow key={name} name={name} score={score} inScope />
            ))}
          </div>
        ) : (
          <p style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)', margin: 0 }}>
            No subsystem doc matched closely enough — this change used the CR's fixed core file
            list directly (see "Selected source files" below), not a subsystem guess.
          </p>
        )}
      </div>

      {screenedOut.length > 0 && (
        <details style={{ marginTop: '0.6rem' }}>
          <summary style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>
            {screenedOut.length} other subsystem{screenedOut.length > 1 ? 's' : ''} screened out as
            not relevant (not part of this change)
          </summary>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', marginTop: '0.4rem' }}>
            {screenedOut.map(({ name, score }) => (
              <SubsystemRow key={name} name={name} score={score} inScope={false} />
            ))}
          </div>
        </details>
      )}

      <details style={{ marginTop: '0.75rem' }}>
        <summary>Selected source files</summary>
        <ul style={{ fontSize: 'var(--ams-text-sm)' }}>
          {selection.selected_files.map((path) => (
            <li key={path}>{path}</li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function SubsystemRow({ name, score, inScope }: { name: string; score: number; inScope: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <span
        className={`ams-pill ${inScope ? 'ams-pill-preview' : 'ams-pill-general'}`}
        style={!inScope ? { opacity: 0.6, textDecoration: 'line-through' } : undefined}
        title={inScope ? 'In scope for this change' : 'Screened out — not used for this change'}
      >
        {name}
      </span>
      <div
        style={{
          flex: 1,
          height: 6,
          borderRadius: 3,
          background: 'var(--ams-line)',
          overflow: 'hidden',
          maxWidth: 160,
        }}
      >
        <div
          style={{
            width: `${Math.max(0, Math.min(1, score ?? 0)) * 100}%`,
            height: '100%',
            background: inScope ? 'var(--ams-accent)' : 'var(--ams-ink-soft)',
          }}
        />
      </div>
      <span style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>
        {typeof score === 'number' ? score.toFixed(2) : '—'}
      </span>
    </div>
  )
}

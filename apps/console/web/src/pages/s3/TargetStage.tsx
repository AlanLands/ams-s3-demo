import { StageFrame } from './components'
import { useS3 } from './context'

export default function TargetStage() {
  const {
    isEngineer,
    activeTicketKey,
    analysisDoneForActive,
    matchPending,
    activeMatch,
    AI_LABEL,
    targetConfirmationRequired,
    targetAccepted,
    setTargetConfirmed,
    identity,
    checkOutResult,
    checkOutError,
    checkOutLockedReason,
    handleCheckOut,
    checkingOut,
    checkedOut
  } = useS3()
  const activity = checkingOut ? 'Checking out the repo.' : checkedOut ? 'Repo checked out.' : checkOutError ?? ''

  return (
    <StageFrame stageId="target" title="Target selection" activity={activity}>
      {isEngineer ? (
    <>
      {/* Repo selection — which of the team's repos this ticket belongs to.
          Deterministic tiers resolve silently; the AI tier shows its reasoning
          and, below high confidence, waits for a human to accept it. */}
      <div className="ams-card" style={{ marginBottom: '1.25rem' }}>
        <strong style={{ display: 'block', marginBottom: '0.3rem' }}>
          Repo selection
        </strong>
        {!activeTicketKey && (
          <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0' }}>
            Pick a ticket on the board above.
          </p>
        )}
        {activeTicketKey && !analysisDoneForActive && (
          <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0' }}>
            Run the impact analysis on the ticket above first — for a user story that names
            no target system, that analysis is what there is to go on.
          </p>
        )}
        {activeTicketKey && analysisDoneForActive && matchPending && (
          <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0' }}>
            Identifying the repo…
          </p>
        )}
        {activeTicketKey && analysisDoneForActive && !matchPending && !activeMatch?.resolved && (
          <p style={{ fontSize: 'var(--ams-text-sm)', margin: '0.3rem 0 0' }}>
            Couldn't identify a repo for this ticket from its user story — a human needs to
            route it.
          </p>
        )}
        {activeTicketKey && analysisDoneForActive && activeMatch?.resolved && (
          <>
            <p style={{ fontSize: 'var(--ams-text-sm)', margin: '0.3rem 0 0.5rem' }}>
              {activeMatch.method === 'ai' ? (
                <>
                  {AI_LABEL} This ticket names an application but no target system, and{' '}
                  <strong>PolicyCore</strong> owns more than one repo — so the match was
                  inferred:
                </>
              ) : (
                <>Resolved from the user story itself — no model call needed.</>
              )}
            </p>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.6rem',
                flexWrap: 'wrap',
                margin: '0.4rem 0',
              }}
            >
              <code>{activeMatch.display_name}</code>
              <span className="ams-pill ams-pill-general">
                {activeMatch.method === 'story_id'
                  ? 'matched on story identifier'
                  : activeMatch.method === 'application_header'
                    ? 'matched on application header'
                    : 'AI match'}
              </span>
              {activeMatch.confidence && (
                <span className="ams-pill ams-pill-general">
                  {activeMatch.confidence} confidence
                </span>
              )}
            </div>
            {activeMatch.reasoning && (
              <p
                style={{
                  fontSize: 'var(--ams-text-sm)',
                  fontStyle: 'italic',
                  color: 'var(--ams-ink-soft)',
                  margin: '0.3rem 0 0',
                }}
              >
                {activeMatch.reasoning}
              </p>
            )}
            {activeMatch.ranking.length > 1 && (
              <div style={{ marginTop: '0.9rem' }}>
                <div
                  style={{
                    fontSize: 'var(--ams-text-xs)',
                    color: 'var(--ams-ink-soft)',
                    marginBottom: '0.45rem',
                  }}
                >
                  All {activeMatch.ranking.length} repos considered — the runner-up
                  matters as much as the winner:
                </div>
                {activeMatch.ranking.map((candidate, index) => {
                  const isPick = candidate.target_id === activeMatch.target_id
                  return (
                    <div
                      key={candidate.target_id}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '1.4rem minmax(0, 1fr) 2.5rem',
                        alignItems: 'center',
                        gap: '0.5rem',
                        padding: '0.35rem 0',
                        borderTop: index === 0 ? 'none' : '1px solid var(--ams-line)',
                      }}
                    >
                      <span
                        style={{
                          fontSize: 'var(--ams-text-xs)',
                          fontWeight: 600,
                          color: isPick ? 'var(--ams-accent)' : 'var(--ams-ink-soft)',
                        }}
                      >
                        {index + 1}
                      </span>
                      <div style={{ minWidth: 0 }}>
                        <div
                          style={{
                            fontSize: 'var(--ams-text-xs)',
                            fontWeight: isPick ? 700 : 400,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                          title={candidate.display_name}
                        >
                          {candidate.display_name}
                          {isPick && (
                            <span
                              style={{
                                color: 'var(--ams-accent)',
                                fontWeight: 600,
                                marginLeft: '0.4rem',
                              }}
                            >
                              ← picked
                            </span>
                          )}
                        </div>
                        {/* Bar width is the model's own score, so a close
                            second reads as close rather than as also-ran. */}
                        <div
                          style={{
                            height: 5,
                            borderRadius: 3,
                            background: 'var(--ams-line)',
                            marginTop: '0.25rem',
                            overflow: 'hidden',
                          }}
                        >
                          <div
                            style={{
                              width: `${candidate.score}%`,
                              height: '100%',
                              borderRadius: 3,
                              background: isPick
                                ? 'var(--ams-accent)'
                                : 'var(--ams-ink-soft)',
                              opacity: isPick ? 1 : 0.4,
                            }}
                          />
                        </div>
                        {candidate.reasoning && (
                          <div
                            style={{
                              fontSize: 'var(--ams-text-xs)',
                              color: 'var(--ams-ink-soft)',
                              marginTop: '0.2rem',
                            }}
                          >
                            {candidate.reasoning}
                          </div>
                        )}
                      </div>
                      <span
                        style={{
                          fontSize: 'var(--ams-text-xs)',
                          fontVariantNumeric: 'tabular-nums',
                          textAlign: 'right',
                          color: isPick ? 'var(--ams-ink)' : 'var(--ams-ink-soft)',
                          fontWeight: isPick ? 700 : 400,
                        }}
                      >
                        {candidate.score}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
            {targetConfirmationRequired && !targetAccepted && (
              <div style={{ marginTop: '0.6rem' }}>
                <p style={{ fontSize: 'var(--ams-text-sm)', margin: '0 0 0.4rem' }}>
                  A model chose this, so nothing proceeds until you accept it.
                </p>
                <button
                  className="ams-button"
                  onClick={() =>
                    setTargetConfirmed((prev) => ({ ...prev, [activeTicketKey]: true }))
                  }
                >
                  Confirm this repo
                </button>
              </div>
            )}
            {targetConfirmationRequired && targetAccepted && (
              <p style={{ fontSize: 'var(--ams-text-sm)', marginTop: '0.5rem' }}>
                ✓ Confirmed by {identity?.name}
              </p>
            )}
          </>
        )}
      </div>

      <div className="ams-card" style={{ marginBottom: '1.25rem' }}>
        <strong style={{ display: 'block', marginBottom: '0.3rem' }}>
          Step 0 · Check out the repo
        </strong>
        {!checkOutResult && !checkOutError && (
          <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0.6rem' }}>
            {checkOutLockedReason ?? "Cuts this story's feature branch."}
          </p>
        )}
        <button
          className="ams-button"
          onClick={handleCheckOut}
          disabled={checkingOut || checkOutLockedReason !== null}
        >
          {checkingOut ? 'Checking out…' : 'Check out the repo'}
        </button>
        {checkedOut && !checkingOut && checkOutResult && (
          <p style={{ fontSize: 'var(--ams-text-sm)', marginTop: '0.5rem' }}>
            ✓ Checked out <code>{checkOutResult.branch}</code> off <code>{checkOutResult.base}</code>
            {checkOutResult.sha && <> (<code>{checkOutResult.sha}</code>)</>}
          </p>
        )}
        {checkOutError && (
          <p className="ams-scm-error" style={{ fontSize: 'var(--ams-text-sm)', marginTop: '0.5rem' }}>
            {checkOutError}
          </p>
        )}
      </div>

    </>
  ) : (
    <p className="ams-muted">Only engineers work through target selection.</p>
  )}
    </StageFrame>
  )
}

import { useState } from 'react'
import FileSelectionPanel from './FileSelectionPanel'
import TokenPanel from './TokenPanel'
import type {
  AnalyzeResponse,
  CrossTeamImpact,
  JiraIssue,
  TicketEvent,
  TokenPanel as TokenPanelData,
} from './api_s3'

const ASSIGNEE_ROSTER = ['Ravi Kumar', 'Elena Cruz', 'Priya Nair']

function initials(name: string | null | undefined): string {
  if (!name) return '?'
  return name.trim().charAt(0).toUpperCase()
}

function CrossTeamImpactRow({
  impact,
  created,
  assignee,
  onAssigneeChange,
  creating,
  onCreate,
  assigning,
  onAssign,
}: {
  impact: CrossTeamImpact
  created?: { key: string; assignee: string | null }
  assignee: string
  onAssigneeChange: (value: string) => void
  creating: boolean
  onCreate: () => void
  assigning: boolean
  onAssign: () => void
}) {
  return (
    <div
      style={{
        marginTop: '0.75rem',
        paddingTop: '0.75rem',
        borderTop: '1px solid var(--ams-line)',
      }}
    >
      <span className="ams-pill ams-pill-preview">{impact.app_name}</span>
      <p style={{ fontSize: '0.85rem', margin: '0.4rem 0' }}>{impact.reason}</p>
      <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)' }}>
        Suggested ticket: {impact.suggested_summary}
      </p>
      {!created && (
        <button className="ams-button-secondary" onClick={onCreate} disabled={creating}>
          {creating ? 'Creating…' : 'Create ticket in Jira'}
        </button>
      )}
      {created && (
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="ams-pill ams-pill-general">{created.key} · Open</span>
          {created.assignee ? (
            <span style={{ fontSize: '0.85rem', color: 'var(--ams-success)' }}>
              ✓ Assigned to {created.assignee}
            </span>
          ) : (
            <>
              <span style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)' }}>
                Visible to the manager as open — assign now or later:
              </span>
              <select
                className="ams-select"
                value={assignee}
                onChange={(event) => onAssigneeChange(event.target.value)}
              >
                {ASSIGNEE_ROSTER.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button className="ams-button-secondary" onClick={onAssign} disabled={assigning}>
                {assigning ? 'Assigning…' : 'Assign'}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export interface TicketModalProps {
  issue: JiraIssue
  crText: string
  crLabel: string | null
  onClose: () => void

  analysisResult?: AnalyzeResponse
  analysisLoading: boolean
  analysisError?: string
  onRunAnalysis: () => void
  // Set only for an ad-hoc (no-target) ticket whose last analyze-adhoc call
  // came back needs_clarification: true — the answer box replaces the
  // run-analysis button until it's answered (see S3.tsx's
  // handleRunAnalysisForTicket).
  clarificationQuestion?: string
  onSubmitClarification: (answer: string) => void

  crossTeamImpacts?: CrossTeamImpact[]
  crossTeamTokenPanel?: TokenPanelData
  crossTeamLoading: boolean
  onCheckCrossTeam: () => void
  createdTickets: Record<string, { key: string; assignee: string | null }>
  assigneeByApp: Record<string, string>
  onAssigneeChange: (appName: string, value: string) => void
  creatingTicketFor: string | null
  onCreateTicket: (impact: CrossTeamImpact) => void
  assigningTicketFor: string | null
  onAssignTicket: (appName: string) => void

  events: TicketEvent[]
  eventsLoading: boolean
}

const ACTOR_LABEL: Record<TicketEvent['actor'], string> = {
  ai: 'AI',
  human: 'Human approval',
  system: 'System',
}

export default function TicketModal({
  issue,
  crText,
  crLabel,
  onClose,
  analysisResult,
  analysisLoading,
  analysisError,
  onRunAnalysis,
  clarificationQuestion,
  onSubmitClarification,
  crossTeamImpacts,
  crossTeamTokenPanel,
  crossTeamLoading,
  onCheckCrossTeam,
  createdTickets,
  assigneeByApp,
  onAssigneeChange,
  creatingTicketFor,
  onCreateTicket,
  assigningTicketFor,
  onAssignTicket,
  events,
  eventsLoading,
}: TicketModalProps) {
  const [activityFilter, setActivityFilter] = useState<'all' | TicketEvent['actor']>('all')
  const visibleEvents = events.filter(
    (event) => activityFilter === 'all' || event.actor === activityFilter
  )
  const [clarificationAnswer, setClarificationAnswer] = useState('')

  function submitClarificationAnswer() {
    const trimmed = clarificationAnswer.trim()
    if (!trimmed) return
    onSubmitClarification(trimmed)
    setClarificationAnswer('')
  }

  return (
    <div className="ams-modal-backdrop" onClick={onClose}>
      <div className="ams-modal" onClick={(event) => event.stopPropagation()}>
        <div className="ams-modal-header">
          <div className="ams-modal-breadcrumb">
            {crLabel && <>{crLabel} / </>}
            <strong>{issue.key}</strong>
          </div>
          <button className="ams-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="ams-modal-body">
          <div className="ams-modal-main">
            <h2>{issue.summary}</h2>

            <div className="ams-modal-section">
              <div className="ams-modal-section-title">Description</div>
              {crText || issue.description ? (
                <div style={{ whiteSpace: 'pre-wrap', fontSize: '0.88rem' }}>
                  {crText || issue.description}
                </div>
              ) : (
                <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)' }}>
                  No description on file for this ticket.
                </p>
              )}
            </div>

            {(crLabel || issue.summary || issue.description) && (
              <div className="ams-modal-section">
                <div className="ams-modal-section-title">AI actions</div>
                {!crLabel && (
                  <p style={{ fontSize: '0.82rem', color: 'var(--ams-ink-soft)', marginBottom: '0.5rem' }}>
                    No CR linked to this ticket in this console — impact analysis below runs off
                    the ticket's own text instead.
                  </p>
                )}
                {clarificationQuestion && (
                  <div className="ams-card" style={{ marginBottom: '0.75rem' }}>
                    <strong>AI needs one clarification before analyzing</strong>
                    {/* pre-wrap: an assumptions question (analyze.build_assumption_
                        question) is a numbered list, not one line. */}
                    <p style={{ fontSize: '0.88rem', margin: '0.5rem 0', whiteSpace: 'pre-wrap' }}>
                      {clarificationQuestion}
                    </p>
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                      <input
                        className="ams-input"
                        style={{ flex: 1, minWidth: '200px' }}
                        value={clarificationAnswer}
                        onChange={(event) => setClarificationAnswer(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' && !analysisLoading) submitClarificationAnswer()
                        }}
                        placeholder="Your answer…"
                        disabled={analysisLoading}
                      />
                      <button
                        className="ams-button"
                        onClick={submitClarificationAnswer}
                        disabled={analysisLoading || !clarificationAnswer.trim()}
                      >
                        {analysisLoading ? 'Submitting…' : 'Submit answer'}
                      </button>
                    </div>
                  </div>
                )}
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                  {!clarificationQuestion && (
                    <button
                      className={analysisResult ? 'ams-button-secondary' : 'ams-button'}
                      onClick={onRunAnalysis}
                      disabled={analysisLoading}
                    >
                      {analysisLoading
                        ? 'Running…'
                        : analysisResult
                          ? 'Re-run AI impact analysis'
                          : 'Run AI impact analysis'}
                    </button>
                  )}
                  {analysisResult && !analysisLoading && (
                    <span className="ams-pill ams-pill-general">✓ Analyzed</span>
                  )}
                  {crLabel && (
                    <>
                      <button
                        className={crossTeamImpacts !== undefined ? 'ams-button-secondary' : 'ams-button'}
                        onClick={onCheckCrossTeam}
                        disabled={crossTeamLoading}
                      >
                        {crossTeamLoading
                          ? 'Checking…'
                          : crossTeamImpacts !== undefined
                            ? 'Re-check for other teams affected'
                            : 'Check for other teams affected'}
                      </button>
                      {crossTeamImpacts !== undefined && !crossTeamLoading && (
                        <span className="ams-pill ams-pill-general">
                          {crossTeamImpacts.length === 0
                            ? '✓ No teams affected'
                            : `✓ ${crossTeamImpacts.length} team${crossTeamImpacts.length > 1 ? 's' : ''} affected`}
                        </span>
                      )}
                    </>
                  )}
                </div>
                {analysisError && (
                  <p style={{ color: 'var(--ams-error)', marginTop: '0.5rem' }}>{analysisError}</p>
                )}
                {analysisResult && (
                  <div className="ams-card" style={{ marginTop: '0.75rem' }}>
                    <strong>{analysisResult.label}</strong>
                    <div style={{ whiteSpace: 'pre-wrap', fontSize: '0.85rem', marginTop: '0.5rem' }}>
                      {analysisResult.impact_analysis}
                    </div>
                    {analysisResult.assumptions.length > 0 && (
                      <div
                        style={{
                          marginTop: '0.6rem',
                          padding: '0.6rem 0.75rem',
                          background: 'var(--ams-accent-soft)',
                          border: '1px solid var(--ams-line)',
                          borderRadius: 4,
                        }}
                      >
                        {/* Reachable only once the clarification-turn budget is
                            spent — every assumption is asked about first (see
                            /s3/analyze). Say why it wasn't asked, so this doesn't
                            read as the AI choosing to assume. */}
                        <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--ams-accent-ink)' }}>
                          Still unresolved after the clarification limit — proceeding on these
                          assumptions
                        </div>
                        <ul style={{ margin: '0.35rem 0 0', paddingLeft: '1.1rem', fontSize: '0.85rem' }}>
                          {analysisResult.assumptions.map((assumption, index) => (
                            <li key={index}>{assumption}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: '2rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
                      <div>
                        <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>Effort</div>
                        <div style={{ fontWeight: 700 }}>{analysisResult.effort_estimate.hours_class}</div>
                      </div>
                      <div>
                        <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>
                          Priority-equivalent
                        </div>
                        <div style={{ fontWeight: 700 }}>
                          {analysisResult.effort_estimate.priority_equivalent}
                        </div>
                      </div>
                      {analysisResult.target_repo && (
                        <div>
                          <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>
                            Target repo
                          </div>
                          <div style={{ fontWeight: 700 }}>
                            {analysisResult.target_repo.name ?? analysisResult.target_repo.id}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
                {analysisResult?.file_selection && (
                  <FileSelectionPanel selection={analysisResult.file_selection} />
                )}
                {analysisResult?.token_panel && (
                  <div style={{ marginTop: '0.4rem' }}>
                    <TokenPanel panel={analysisResult.token_panel} />
                  </div>
                )}
                {crossTeamImpacts && (
                  <div className="ams-card" style={{ marginTop: '0.75rem' }}>
                    <strong>Other teams depended on</strong>
                    {crossTeamImpacts.length === 0 ? (
                      <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)', marginTop: '0.4rem' }}>
                        No other application teams look affected.
                      </p>
                    ) : (
                      crossTeamImpacts.map((impact) => (
                        <CrossTeamImpactRow
                          key={impact.app_name}
                          impact={impact}
                          created={createdTickets[impact.app_name]}
                          assignee={assigneeByApp[impact.app_name] || ASSIGNEE_ROSTER[0]}
                          onAssigneeChange={(value) => onAssigneeChange(impact.app_name, value)}
                          creating={creatingTicketFor === impact.app_name}
                          onCreate={() => onCreateTicket(impact)}
                          assigning={assigningTicketFor === impact.app_name}
                          onAssign={() => onAssignTicket(impact.app_name)}
                        />
                      ))
                    )}
                    {crossTeamTokenPanel && (
                      <div style={{ marginTop: '0.6rem' }}>
                        <TokenPanel panel={crossTeamTokenPanel} />
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="ams-modal-section">
              <div className="ams-modal-section-title">Activity</div>
              <div className="ams-modal-activity-tabs">
                {(['all', 'ai', 'human', 'system'] as const).map((filter) => (
                  <button
                    key={filter}
                    className={`ams-modal-activity-tab${activityFilter === filter ? ' ams-modal-activity-tab-active' : ''}`}
                    onClick={() => setActivityFilter(filter)}
                  >
                    {filter === 'all' ? 'All' : ACTOR_LABEL[filter]}
                  </button>
                ))}
              </div>
              {eventsLoading && (
                <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)' }}>Loading…</p>
              )}
              {!eventsLoading && visibleEvents.length === 0 && (
                <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)' }}>
                  No activity recorded yet — run an action above to see it show up here.
                </p>
              )}
              {!eventsLoading && visibleEvents.length > 0 && (
                <div className="ams-timeline">
                  {visibleEvents.map((event, index) => (
                    <div key={index} className="ams-timeline-item">
                      <div className="ams-timeline-top">
                        <span className={`ams-timeline-chip ams-timeline-chip-${event.actor}`}>
                          {ACTOR_LABEL[event.actor]}
                        </span>
                        <span className="ams-timeline-action">
                          {event.action.replaceAll('_', ' ')}
                        </span>
                        <span className="ams-timeline-ts">{event.ts}</span>
                      </div>
                      {event.detail && <div className="ams-timeline-detail">{event.detail}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <aside className="ams-modal-details">
            <div className="ams-modal-section-title">Details</div>
            <dl>
              <dt>Status</dt>
              <dd>{issue.status || 'To Do'}</dd>
              <dt>Assignee</dt>
              <dd style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                {issue.assignee ? (
                  <>
                    <span className="ams-avatar">{initials(issue.assignee)}</span>
                    {issue.assignee}
                  </>
                ) : (
                  'Unassigned'
                )}
              </dd>
              <dt>Application</dt>
              <dd>{crLabel ? 'PolicyCore' : '—'}</dd>
              <dt>Reporter</dt>
              <dd>{crLabel ? 'MapleSure Product Team' : 'AMS Console (auto-created)'}</dd>
              <dt>Origin</dt>
              <dd>
                {issue.origin === 'problem_record' ? (
                  <>
                    Problem record
                    {issue.problem_id && (
                      <div style={{ fontSize: '0.8rem', color: 'var(--ams-ink-soft)' }}>
                        {issue.problem_id}
                      </div>
                    )}
                  </>
                ) : (
                  'Business CR'
                )}
              </dd>
            </dl>
          </aside>
        </div>
      </div>
    </div>
  )
}

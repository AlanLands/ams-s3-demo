import { useEffect, useMemo, useState } from 'react'
import FileSelectionPanel from './FileSelectionPanel'
import TokenPanel from './TokenPanel'
import type {
  AnalyzeResponse,
  CrossTeamImpact,
  JiraIssue,
  RouteDecision,
  TicketEvent,
  TokenPanel as TokenPanelData,
} from './api_s3'

const ASSIGNEE_ROSTER = ['Ravi Kumar', 'Elena Cruz', 'Priya Nair']

function initials(name: string | null | undefined): string {
  if (!name) return '?'
  return name.trim().charAt(0).toUpperCase()
}

// The user story files in stories/*.md all share one shape: a title line, a run of
// "Key: Value" header lines, then "Section:" headings over hard-wrapped
// prose or "- " bullets. Rendering that raw (white-space: pre-wrap) turned
// the description into a wall of text where the headings, the metadata and
// the acceptance criteria all read at the same weight. Parsing the shape
// back out costs ~60 lines and makes the panel skimmable at demo distance.
//
// Anything that doesn't match the shape falls through to a paragraph, so an
// ad-hoc ticket description still renders sensibly.
type CrBlock =
  | { kind: 'meta'; rows: { label: string; value: string }[] }
  | { kind: 'heading'; text: string }
  | { kind: 'para'; text: string }
  | { kind: 'list'; items: string[] }

const META_LINE = /^([A-Za-z][A-Za-z0-9 /()-]{0,30}):[ \t]+(\S.*)$/
const TITLE_LINE = /^[A-Z]+-\d{4}-\d+\s*:/

function unwrap(lines: string[]): string {
  return lines.join(' ').replace(/\s+/g, ' ').trim()
}

// One group = one blank-line-separated block of the source text.
function parseGroup(group: string[]): CrBlock[] {
  const metaRows = group.map((line) => line.match(META_LINE)).filter(Boolean)
  if (metaRows.length === group.length && group.length >= 2) {
    return [
      {
        kind: 'meta',
        rows: metaRows.map((match) => ({ label: match![1], value: match![2] })),
      },
    ]
  }

  const blocks: CrBlock[] = []
  let body = group
  // A lone "Description:" / "Acceptance criteria:" line heads the block.
  if (/^[A-Za-z][^:]{0,40}:$/.test(group[0])) {
    const text = group[0].replace(/:$/, '')
    // The panel is already titled "Description" — don't say it twice.
    if (text.toLowerCase() !== 'description') blocks.push({ kind: 'heading', text })
    body = group.slice(1)
  }
  if (body.length === 0) return blocks

  if (body.some((line) => /^[-*]\s+/.test(line))) {
    const items: string[] = []
    let pending: string[] = []
    for (const line of body) {
      if (/^[-*]\s+/.test(line)) {
        if (pending.length) items.push(unwrap(pending))
        pending = [line.replace(/^[-*]\s+/, '')]
      } else if (pending.length) {
        pending.push(line.trim())
      } else {
        blocks.push({ kind: 'para', text: line.trim() })
      }
    }
    if (pending.length) items.push(unwrap(pending))
    blocks.push({ kind: 'list', items })
    return blocks
  }

  blocks.push({ kind: 'para', text: unwrap(body) })
  return blocks
}

function parseCrText(raw: string, summary: string): CrBlock[] {
  const lines = raw.replace(/\r\n/g, '\n').split('\n')
  let start = 0
  while (start < lines.length && !lines[start].trim()) start += 1
  // The first line is the user story title, which the <h2> above already shows.
  const first = (lines[start] ?? '').trim()
  if (first && (first === summary.trim() || TITLE_LINE.test(first))) start += 1

  const blocks: CrBlock[] = []
  let group: string[] = []
  for (const line of lines.slice(start)) {
    if (line.trim()) {
      group.push(line)
    } else if (group.length) {
      blocks.push(...parseGroup(group))
      group = []
    }
  }
  if (group.length) blocks.push(...parseGroup(group))
  return blocks
}

// Read one "Key: Value" header off the user story. The Details rail used to hardcode
// PolicyCore / MapleSure Product Team, which was simply wrong on the
// ClaimsPortal user story — the user story states both, so read them from it.
function storyMeta(text: string, label: string): string | null {
  for (const block of parseCrText(text, '')) {
    if (block.kind !== 'meta') continue
    const row = block.rows.find((candidate) => candidate.label.toLowerCase() === label.toLowerCase())
    if (row) return row.value
  }
  return null
}

// "PolicyCore (policy/claims portal)" -> "PolicyCore": the parenthetical is
// prose for the description panel, too long for a 250px rail.
function shortAppName(value: string): string {
  return value.split(' (')[0].trim()
}

// Long user stories pushed the "Run AI impact analysis" button below the fold, which
// is the one control the demo always reaches for next. Collapse the long
// ones behind a fade instead of making the presenter scroll past them.
const COLLAPSE_OVER_CHARS = 900

function StoryDescription({ text, summary }: { text: string; summary: string | null }) {
  const blocks = useMemo(() => parseCrText(text, summary ?? ''), [text, summary])
  const collapsible = text.length > COLLAPSE_OVER_CHARS
  const [expanded, setExpanded] = useState(false)
  const collapsed = collapsible && !expanded

  return (
    <div className="ams-story">
      <div className={`ams-story-body${collapsed ? ' ams-story-body-collapsed' : ''}`}>
        {blocks.map((block, index) => {
          if (block.kind === 'meta') {
            return (
              <dl className="ams-story-meta" key={index}>
                {block.rows.map((row) => (
                  <div className="ams-story-meta-row" key={row.label}>
                    <dt>{row.label}</dt>
                    <dd>{row.value}</dd>
                  </div>
                ))}
              </dl>
            )
          }
          if (block.kind === 'heading') {
            return (
              <h4 className="ams-story-heading" key={index}>
                {block.text}
              </h4>
            )
          }
          if (block.kind === 'list') {
            return (
              <ul className="ams-story-list" key={index}>
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>{item}</li>
                ))}
              </ul>
            )
          }
          return (
            <p className="ams-story-para" key={index}>
              {block.text}
            </p>
          )
        })}
      </div>
      {collapsible && (
        <button className="ams-story-toggle" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Show less' : 'Show full user story'}
        </button>
      )}
    </div>
  )
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
      <p style={{ fontSize: 'var(--ams-text-sm)', margin: '0.4rem 0' }}>{impact.reason}</p>
      <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)' }}>
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
            <span style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-success)' }}>
              ✓ Assigned to {created.assignee}
            </span>
          ) : (
            <>
              <span style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)' }}>
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

// How the ticket reached its owning application, shown above the analysis.
//
// The distinction this panel exists to make: a CI match is a CMDB lookup, not
// a model output, and it must not be rendered in the same voice as an AI
// suggestion. Only the fallback path carries the AI label — claiming the
// deterministic route "as AI" would overstate what the system did, and
// claiming the AI guess as deterministic would understate the risk.
function RoutingPanel({ decision }: { decision: RouteDecision }) {
  if (!decision.routed || !decision.application) {
    return (
      <div className="ams-card" style={{ marginTop: '0.75rem' }}>
        <div style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>Routing</div>
        <div style={{ fontSize: 'var(--ams-text-sm)', marginTop: '0.3rem' }}>
          This ticket carried no Configuration Item, so there is nothing to route on
          deterministically — the AI repo match below decides instead, and asks you to
          confirm anything it isn't sure about.
        </div>
      </div>
    )
  }

  const app = decision.application
  return (
    <div className="ams-card" style={{ marginTop: '0.75rem' }}>
      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="ams-pill ams-pill-general">{app.display_name}</span>
        <span style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>
          Routed by {decision.method === 'ci' ? 'CI' : 'business service'} “
          {decision.matched_on}” — no AI involved
        </span>
      </div>
      <div style={{ display: 'flex', gap: '2rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
        <div>
          <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)' }}>Component team</div>
          <div style={{ fontWeight: 700 }}>{app.component_team}</div>
        </div>
        <div>
          <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)' }}>Jira project</div>
          <div style={{ fontWeight: 700 }}>{app.jira_project_key}</div>
        </div>
        <div>
          <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)' }}>Tech stack</div>
          <div style={{ fontWeight: 700 }}>{app.tech_stack}</div>
        </div>
        {decision.suggested_assignee && (
          <div>
            <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)' }}>On call</div>
            <div style={{ fontWeight: 700 }}>{decision.suggested_assignee}</div>
          </div>
        )}
      </div>
      {decision.automation_available ? (
        <p style={{ fontSize: 'var(--ams-text-sm)', margin: '0.6rem 0 0', color: 'var(--ams-ink-soft)' }}>
          Repo <code>{app.repo_path}</code> — {decision.candidate_targets.length} change
          {decision.candidate_targets.length === 1 ? '' : 's'} available to run against it.
        </p>
      ) : (
        <p style={{ fontSize: 'var(--ams-text-sm)', margin: '0.6rem 0 0', color: 'var(--ams-ink-soft)' }}>
          Routed to the owning team. This console has no repo for {app.display_name}, so no
          code will be generated for it here.
        </p>
      )}
    </div>
  )
}

export interface TicketModalProps {
  issue: JiraIssue
  storyText: string
  storyLabel: string | null
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
  storyText,
  storyLabel,
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

  const application = storyMeta(storyText, 'Application')
  const storyApplication = application ? shortAppName(application) : null
  const storyReporter = storyMeta(storyText, 'Requested by')

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

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
            {storyLabel && <>{storyLabel} / </>}
            <strong>{issue.key}</strong>
            <span className="ams-modal-status">{issue.status || 'To Do'}</span>
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
              {storyText || issue.description ? (
                <StoryDescription text={storyText || issue.description || ''} summary={issue.summary} />
              ) : (
                <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)' }}>
                  No description on file for this ticket.
                </p>
              )}
            </div>

            {(storyLabel || issue.summary || issue.description) && (
              <div className="ams-modal-section">
                <div className="ams-modal-section-title">AI actions</div>
                {!storyLabel && (
                  <p style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)', marginBottom: '0.5rem' }}>
                    No user story linked to this ticket in this console — impact analysis below runs
                    off the ticket's own text instead.
                  </p>
                )}
                {clarificationQuestion && (
                  <div className="ams-card" style={{ marginBottom: '0.75rem' }}>
                    <strong>AI needs one clarification before analyzing</strong>
                    {/* pre-wrap: an assumptions question (analyze.build_assumption_
                        question) is a numbered list, not one line. */}
                    <p style={{ fontSize: 'var(--ams-text-sm)', margin: '0.5rem 0', whiteSpace: 'pre-wrap' }}>
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
                  {storyLabel && (
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
                {analysisResult?.routing && <RoutingPanel decision={analysisResult.routing} />}
                {analysisResult && (
                  <div className="ams-card" style={{ marginTop: '0.75rem' }}>
                    <strong>{analysisResult.label}</strong>
                    <div style={{ whiteSpace: 'pre-wrap', fontSize: 'var(--ams-text-sm)', marginTop: '0.5rem' }}>
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
                        <div style={{ fontSize: 'var(--ams-text-xs)', fontWeight: 700, color: 'var(--ams-accent-ink)' }}>
                          Still unresolved after the clarification limit — proceeding on these
                          assumptions
                        </div>
                        <ul style={{ margin: '0.35rem 0 0', paddingLeft: '1.1rem', fontSize: 'var(--ams-text-sm)' }}>
                          {analysisResult.assumptions.map((assumption, index) => (
                            <li key={index}>{assumption}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: '2rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
                      <div>
                        <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)' }}>Effort</div>
                        <div style={{ fontWeight: 700 }}>{analysisResult.effort_estimate.hours_class}</div>
                      </div>
                      <div>
                        <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)' }}>
                          Priority-equivalent
                        </div>
                        <div style={{ fontWeight: 700 }}>
                          {analysisResult.effort_estimate.priority_equivalent}
                        </div>
                      </div>
                      {analysisResult.target_repo && (
                        <div>
                          <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)' }}>
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
                      <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', marginTop: '0.4rem' }}>
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
                <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)' }}>Loading…</p>
              )}
              {!eventsLoading && visibleEvents.length === 0 && (
                <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)' }}>
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
            <div className="ams-modal-details-inner">
              <div className="ams-modal-section-title">Details</div>
              <dl>
                <div className="ams-modal-detail-row">
                  <dt>Status</dt>
                  <dd>{issue.status || 'To Do'}</dd>
                </div>
                <div className="ams-modal-detail-row">
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
                </div>
                <div className="ams-modal-detail-row">
                  <dt>Application</dt>
                  <dd>{storyApplication ?? (storyLabel ? 'PolicyCore' : '—')}</dd>
                </div>
                <div className="ams-modal-detail-row">
                  <dt>Reporter</dt>
                  <dd>
                    {storyReporter ??
                      (storyLabel ? 'MapleSure Product Team' : 'AMS Console (auto-created)')}
                  </dd>
                </div>
                <div className="ams-modal-detail-row">
                  <dt>Origin</dt>
                  <dd>
                    {issue.origin === 'problem_record' ? (
                      <>
                        Problem record
                        {issue.problem_id && (
                          <div style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>
                            {issue.problem_id}
                          </div>
                        )}
                      </>
                    ) : (
                      'Business user story'
                    )}
                  </dd>
                </div>
              </dl>
            </div>
          </aside>
        </div>
      </div>
    </div>
  )
}

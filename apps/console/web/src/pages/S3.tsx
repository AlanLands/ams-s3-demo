import { Fragment, useEffect, useState, type ReactNode } from 'react'
import { ApiError } from '../api'
import { useAuth } from '../AuthContext'
import FileSelectionPanel from '../FileSelectionPanel'
import TicketModal from '../TicketModal'
import TokenPanel from '../TokenPanel'
import {
  s3Api,
  type AnalyzeResponse,
  type CrossTeamImpact,
  type DesignDocFinding,
  type DesignSyncResponse,
  type EffortEstimate,
  type GenerateResponse,
  type JiraIssue,
  type MutationCheckResponse,
  type PostApplyResult,
  type QuickChatResponse,
  type TestCaseResult,
  type TestsGenerateResponse,
  type TestsRunResponse,
  type TicketEvent,
  type TokenPanel as TokenPanelData,
} from '../api_s3'

const AI_LABEL = 'AI suggestion — verify with your specialist before applying.'

// The MapleSure mockapp's own Streamlit UI (apps/policycore/app.py) — launched
// separately from the AMS console (see demo/run_mockapp.sh), same
// port .env.example documents as MOCKAPP_URL.
const MOCKAPP_URL = 'http://localhost:8501'

// Where an applied change can actually be seen running, per target. Keyed by
// target id so the post-apply "go look at it" link names the app the change
// landed in — not always the mockapp portal. The Spring ClaimsPortal target
// serves its own consoles from two Maven services (demo/run_s3_springdemo.sh:
// policy-service :8081, claims-service :8082); CR-2026-043 changes claim
// intake, so the claims console is the one worth opening.
const TARGET_APPS: Record<string, { url: string; label: string }> = {
  'springdemo-claims-deductible': {
    url: 'http://localhost:8082/',
    label: 'open the Claims Team console',
  },
}
const DEFAULT_TARGET_APP = { url: MOCKAPP_URL, label: 'open the policy portal' }

// Demo-only roster for assigning a ticket — mirrors the shared engineer
// roster's first few names (common/roster.py); this page doesn't fetch the
// live roster since a ticket assignee is illustrative here, not a real Jira
// user lookup (Jira Cloud needs an accountId, which this fictional roster
// doesn't have — see common/jira_client.py's assignee note).
const ASSIGNEE_ROSTER = ['Ravi Kumar', 'Elena Cruz', 'Priya Nair']

// QA hand-off roster — the ClaimsPortal support pair doubles as the test
// team in this demo. Once a ticket is handed to QA, only the assigned
// tester (logged in as themselves) can generate/run tests and close out.
const TESTER_ROSTER = ['Priya Nair', 'Tom Becker']

// Which CR/target a given Jira board ticket links to, so clicking it can run
// impact analysis against the right target — the AMS-098 cleanup ticket has
// no linked CR (it's a seeded example of unrelated work also on the board).
const TICKET_TARGETS: Record<string, { targetId: string | null; tierName: string; crLabel: string }> = {
  'AMS-101': { targetId: null, tierName: 'Elite', crLabel: 'CR-2026-041' },
  'AMS-102': { targetId: 'mockapp-endorsement-field-add', tierName: 'Elite', crLabel: 'CR-2026-042' },
  // The Spring Boot ClaimsPortal target (apps/claimsportal) — S3's proof
  // that the pipeline handles a second repo in a second language. tierName is
  // a required placeholder like AMS-102's; CR-2026-043 has no {{TIER_NAME}}.
  'AMS-103': { targetId: 'springdemo-claims-deductible', tierName: 'Elite', crLabel: 'CR-2026-043' },
}

// Persists the impact-analysis result and the in-progress code proposal per
// ticket to localStorage, so reloading the page (or coming back later) shows
// what was already run instead of a blank slate — the server-side staged
// proposal files under s3_enhancement/out/{proposal_id}/ this refers to stick
// around too, so "Ask"/"Apply" on a restored proposal still works as long as
// the backend process hasn't been restarted since.
const TICKET_STORAGE_PREFIX = 'ams-s3:ticket:'

interface FileChatTurn {
  role: 'user' | 'assistant'
  text: string
}

interface PersistedTicketState {
  analysis?: AnalyzeResponse
  generated?: GenerateResponse
  filePaths?: string[]
  fileReasons?: Record<string, string>
  collapsedFiles?: Record<string, boolean>
  applied?: boolean
  appliedFiles?: Record<string, boolean>
  // `{path: reason}` — persisted so a rejection survives a reload, like every
  // other review decision on the proposal. The server is still the authority:
  // the next apply/reject response overwrites this.
  rejectedFiles?: Record<string, string>
  postApplyFailure?: PostApplyResult | null
  fileChats?: Record<string, FileChatTurn[]>
  // Downstream-stage artifacts persist per ticket so the QA hand-off works
  // across logins in the same browser: the developer drafts the design doc,
  // the tester logs in later and continues from tests without re-running
  // the developer's stages.
  designDoc?: string
  // The three-beat tests stage: reviewable generated tests, the parsed run,
  // and the seeded-bug "prove the tests catch bugs" check.
  testsGenerated?: TestsGenerateResponse
  testsRun?: TestsRunResponse
  mutationCheck?: MutationCheckResponse
  releaseNotes?: string
}

function loadTicketState(ticketKey: string): PersistedTicketState {
  try {
    const raw = localStorage.getItem(TICKET_STORAGE_PREFIX + ticketKey)
    return raw ? (JSON.parse(raw) as PersistedTicketState) : {}
  } catch {
    return {}
  }
}

function saveTicketState(ticketKey: string, patch: PersistedTicketState): void {
  try {
    const current = loadTicketState(ticketKey)
    localStorage.setItem(TICKET_STORAGE_PREFIX + ticketKey, JSON.stringify({ ...current, ...patch }))
  } catch {
    // localStorage unavailable (private browsing, quota) — state just won't survive a reload.
  }
}

// --- Design-document rendering/download helpers ------------------------------
// The drafted design doc is a real hand-off artifact, so it renders as an
// actual document (letterhead, headings, lists) and downloads as a file —
// not a raw text dump in a card.

interface DocBlock {
  type: 'heading' | 'bullet' | 'paragraph'
  text: string
}

function parseDocBlocks(text: string): DocBlock[] {
  const blocks: DocBlock[] = []
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const boldHeading = line.match(/^\*\*(.+?)\*\*:?\s*$/)
    if (boldHeading) {
      blocks.push({ type: 'heading', text: boldHeading[1].replace(/:$/, '') })
      continue
    }
    const hashHeading = line.match(/^#{1,4}\s+(.*)$/)
    if (hashHeading) {
      blocks.push({ type: 'heading', text: hashHeading[1] })
      continue
    }
    if (/^\d+\.\s+[A-Za-z][A-Za-z /&-]{1,40}:?$/.test(line)) {
      blocks.push({ type: 'heading', text: line.replace(/:$/, '') })
      continue
    }
    if (/^[-*•]\s+/.test(line)) {
      blocks.push({ type: 'bullet', text: line.replace(/^[-*•]\s+/, '') })
      continue
    }
    blocks.push({ type: 'paragraph', text: line })
  }
  return blocks
}

function renderInlineBold(text: string): ReactNode[] {
  return text
    .split(/\*\*(.+?)\*\*/g)
    .map((part, index) => (index % 2 === 1 ? <strong key={index}>{part}</strong> : part))
}

function escapeHtml(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function downloadFile(filename: string, mime: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function buildDesignDocHtml(text: string, crLabel: string, ticketKey: string): string {
  const inline = (value: string) =>
    escapeHtml(value).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  const body: string[] = []
  let openList = false
  for (const block of parseDocBlocks(text)) {
    if (block.type === 'bullet' && !openList) {
      body.push('<ul>')
      openList = true
    } else if (block.type !== 'bullet' && openList) {
      body.push('</ul>')
      openList = false
    }
    if (block.type === 'heading') body.push(`<h2>${inline(block.text)}</h2>`)
    else if (block.type === 'bullet') body.push(`<li>${inline(block.text)}</li>`)
    else body.push(`<p>${inline(block.text)}</p>`)
  }
  if (openList) body.push('</ul>')
  const date = new Date().toLocaleDateString('en-CA', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>${escapeHtml(crLabel)} — Design Document</title>
<style>
  body { font-family: Georgia, 'Times New Roman', serif; max-width: 760px; margin: 3rem auto; padding: 0 1.5rem; color: #1e293b; line-height: 1.55; }
  .letterhead { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 3px double #94a3b8; padding-bottom: .6rem; }
  .letterhead .org { font-size: 1.15rem; font-weight: 700; letter-spacing: .02em; }
  .letterhead .kind { font-size: .8rem; color: #64748b; text-transform: uppercase; letter-spacing: .1em; }
  .meta { font-size: .85rem; color: #475569; margin: .8rem 0 1.6rem; }
  h2 { font-size: 1.05rem; margin: 1.4rem 0 .4rem; border-bottom: 1px solid #e2e8f0; padding-bottom: .2rem; }
  .label { margin-top: 2.2rem; font-size: .75rem; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: .6rem; }
</style></head><body>
<div class="letterhead"><span class="org">MapleSure Insurance</span><span class="kind">Internal Design Document</span></div>
<div class="meta">${escapeHtml(crLabel)} · Ticket ${escapeHtml(ticketKey)} · ${date} · Engineering → QA hand-off</div>
${body.join('\n')}
<div class="label">${escapeHtml(AI_LABEL)}</div>
</body></html>
`
}

// Backend equivalent of the above: demo/reset_s3.sh clears the server's
// ticket-events log (and reseeds mockapp, clears the LLM cache) between
// rehearsals, but has no way to reach into a browser's localStorage — without
// this check, a reset followed by a reload would still show whatever
// analysis/proposal was cached from before the reset, for tickets the server
// no longer has any record of.
const RESET_MARKER_STORAGE_KEY = 'ams-s3:reset-marker'

function clearAllPersistedTicketState(): void {
  try {
    const staleKeys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key?.startsWith(TICKET_STORAGE_PREFIX)) staleKeys.push(key)
    }
    for (const key of staleKeys) localStorage.removeItem(key)
  } catch {
    // localStorage unavailable — nothing to clear.
  }
}

interface DiffLine {
  type: 'add' | 'del' | 'meta' | 'context'
  text: string
}

interface DiffFile {
  path: string
  lines: DiffLine[]
}

// Splits codegen.py's unified-diff output (difflib.unified_diff with
// fromfile="a/<path>", tofile="b/<path>") into one section per file, so the
// UI can show "which file, what changed, ask a question about it" instead of
// one undifferentiated block of text.
function parseDiff(diffText: string): DiffFile[] {
  const files: DiffFile[] = []
  let current: DiffFile | null = null
  for (const line of diffText.split('\n')) {
    if (line.startsWith('+++ ')) {
      current = { path: line.slice(4).trim().replace(/^b\//, ''), lines: [] }
      files.push(current)
      continue
    }
    if (line.startsWith('--- ') || !current) continue
    if (line.startsWith('@@')) current.lines.push({ type: 'meta', text: line })
    else if (line.startsWith('+')) current.lines.push({ type: 'add', text: line })
    else if (line.startsWith('-')) current.lines.push({ type: 'del', text: line })
    else current.lines.push({ type: 'context', text: line })
  }
  return files
}


// Per-test checklist parsed from the runner's JUnit XML — the readable
// alternative to the raw pytest/Maven dump (which stays available behind a
// "runner output" disclosure below the table).
function TestCaseTable({ cases }: { cases: TestCaseResult[] }) {
  if (cases.length === 0) return null
  const icon = (status: TestCaseResult['status']) =>
    status === 'passed' ? '✓' : status === 'skipped' ? '○' : '✗'
  const color = (status: TestCaseResult['status']) =>
    status === 'passed'
      ? 'var(--ams-success)'
      : status === 'skipped'
        ? 'var(--ams-ink-soft)'
        : 'var(--ams-error)'
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '0.6rem' }}>
      <tbody>
        {cases.map((testCase) => (
          <Fragment key={`${testCase.classname}.${testCase.name}`}>
            <tr style={{ borderTop: '1px solid var(--ams-line)' }}>
              <td
                style={{
                  color: color(testCase.status),
                  fontWeight: 700,
                  padding: '0.35rem 0.5rem 0.35rem 0.2rem',
                  width: '1.4rem',
                }}
              >
                {icon(testCase.status)}
              </td>
              <td style={{ padding: '0.35rem 0.5rem', fontSize: '0.88rem' }}>
                {testCase.description}
                <div
                  style={{
                    fontFamily: 'ui-monospace, monospace',
                    fontSize: '0.72rem',
                    color: 'var(--ams-ink-soft)',
                  }}
                >
                  {testCase.name}
                </div>
              </td>
              <td
                style={{
                  padding: '0.35rem 0.2rem',
                  fontSize: '0.78rem',
                  color: 'var(--ams-ink-soft)',
                  textAlign: 'right',
                  whiteSpace: 'nowrap',
                  verticalAlign: 'top',
                }}
              >
                {testCase.time_s >= 1
                  ? `${testCase.time_s.toFixed(2)} s`
                  : `${Math.max(1, Math.round(testCase.time_s * 1000))} ms`}
              </td>
            </tr>
            {testCase.message && testCase.status !== 'passed' && (
              <tr>
                <td />
                <td
                  colSpan={2}
                  style={{
                    padding: '0 0.5rem 0.5rem',
                    fontSize: '0.78rem',
                    fontFamily: 'ui-monospace, monospace',
                    color: 'var(--ams-error)',
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {testCase.message}
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  )
}

function RunSummaryLine({ run }: { run: TestsRunResponse }) {
  const parts: string[] = [`${run.summary.passed} passed`]
  if (run.summary.failed) parts.push(`${run.summary.failed} failed`)
  if (run.summary.errors) parts.push(`${run.summary.errors} errored`)
  if (run.summary.skipped) parts.push(`${run.summary.skipped} skipped`)
  return (
    <p style={{ margin: '0.4rem 0 0', fontSize: '0.88rem' }}>
      <strong style={{ color: run.passed ? 'var(--ams-success)' : 'var(--ams-error)' }}>
        {parts.join(', ')}
      </strong>{' '}
      <span style={{ color: 'var(--ams-ink-soft)' }}>in {run.duration_s.toFixed(1)} s</span>
    </p>
  )
}

// The raw runner dump, tucked behind a disclosure so the parsed table leads.
function RunnerOutput({ output }: { output: string }) {
  if (!output.trim()) return null
  return (
    <details style={{ marginTop: '0.6rem' }}>
      <summary style={{ cursor: 'pointer', fontSize: '0.8rem', color: 'var(--ams-ink-soft)' }}>
        Show runner output
      </summary>
      <pre style={{ fontSize: '0.75rem', overflowX: 'auto', whiteSpace: 'pre-wrap', marginTop: '0.4rem' }}>
        {output}
      </pre>
    </details>
  )
}

type Stage = 'generate' | 'design' | 'tests' | 'notes'

// A collapsible pipeline step: minimized by default, only the stage the
// engineer clicks expands (see the single `openStage` state below) — and a
// stage that isn't unlocked yet can't be opened at all, so the codegen flow
// reads as a strict sequence instead of a wall of always-open sections.
function StageCard({
  index,
  title,
  locked,
  lockedHint,
  statusLabel,
  statusVariant,
  open,
  onToggle,
  children,
}: {
  index: number
  title: string
  locked: boolean
  lockedHint?: string | null
  statusLabel?: string | null
  statusVariant?: 'ok' | 'error'
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <div className={`ams-stage-card${locked ? ' ams-stage-card-locked' : ''}`}>
      <button
        type="button"
        className="ams-stage-header"
        onClick={onToggle}
        disabled={locked}
        aria-expanded={open}
      >
        <span className="ams-stage-index">{index}</span>
        <span className="ams-stage-title">{title}</span>
        {statusLabel && (
          <span
            className={`ams-pill ${statusVariant === 'error' ? 'ams-pill-error' : 'ams-pill-general'}`}
          >
            {statusLabel}
          </span>
        )}
        <span className="ams-stage-chevron">{open && !locked ? '▾' : '▸'}</span>
      </button>
      {locked && lockedHint && <p className="ams-stage-hint">{lockedHint}</p>}
      {!locked && open && <div className="ams-stage-body">{children}</div>}
    </div>
  )
}

export default function S3() {
  const { identity } = useAuth()
  const isManager = identity?.role === 'manager'
  const isEngineer = identity?.role === 'engineer'

  const [generated, setGenerated] = useState<GenerateResponse | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)

  const [perFileQuestion, setPerFileQuestion] = useState<Record<string, string>>({})
  const [perFileChat, setPerFileChat] = useState<Record<string, FileChatTurn[]>>({})
  const [revisingFile, setRevisingFile] = useState<string | null>(null)
  const [reviseError, setReviseError] = useState<string | null>(null)

  // Diff cards are keyed off this list rather than re-parsed straight off
  // diff_text every render — a revise/ask call that doesn't end up changing a
  // file (a plain question, or an edit the model decides not to make) yields
  // an empty unified diff for it, and difflib.unified_diff emits nothing at
  // all for an unchanged file, which would otherwise make that file's whole
  // card vanish instead of just showing "no pending changes."
  const [filePaths, setFilePaths] = useState<string[]>([])
  const [collapsedFiles, setCollapsedFiles] = useState<Record<string, boolean>>({})
  const [fileReasons, setFileReasons] = useState<Record<string, string>>({})

  const [applied, setApplied] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [appliedFiles, setAppliedFiles] = useState<Record<string, boolean>>({})
  const [applyingFile, setApplyingFile] = useState<string | null>(null)
  // `{path: reason}` for files the developer turned down. Server-owned — the
  // apply/reject responses carry it back, so this never drifts from what the
  // apply endpoint will actually honour.
  const [rejectedFiles, setRejectedFiles] = useState<Record<string, string>>({})
  const [rejectingFile, setRejectingFile] = useState<string | null>(null)
  // Path whose reason box is open; '' is a valid reason (rejecting without
  // explaining is allowed), so this can't be inferred from the reason text.
  const [rejectPromptFor, setRejectPromptFor] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [revertingFile, setRevertingFile] = useState<string | null>(null)
  const [reverting, setReverting] = useState(false)
  const [postApplyFailure, setPostApplyFailure] = useState<PostApplyResult | null>(null)
  // Design-doc drift found after Apply. Runs automatically — never a button the
  // developer has to know to press — and stays null whenever the change touched
  // no documented subsystem, which is the case for every current demo CR.
  const [designSync, setDesignSync] = useState<DesignSyncResponse | null>(null)
  const [designDocApplying, setDesignDocApplying] = useState<string | null>(null)
  const [designDocApplied, setDesignDocApplied] = useState<Record<string, boolean>>({})
  const [fixingCrash, setFixingCrash] = useState(false)
  const [fixCrashError, setFixCrashError] = useState<string | null>(null)

  const [newFilePath, setNewFilePath] = useState('')
  const [newFileInstruction, setNewFileInstruction] = useState('')
  const [addingFile, setAddingFile] = useState(false)
  const [addFileError, setAddFileError] = useState<string | null>(null)

  const [designDoc, setDesignDoc] = useState<string | null>(null)
  const [qaTester, setQaTester] = useState<string>(TESTER_ROSTER[0])
  const [handingOff, setHandingOff] = useState(false)
  const [handoffError, setHandoffError] = useState<string | null>(null)
  const [closingTicket, setClosingTicket] = useState(false)
  const [draftingDesignDoc, setDraftingDesignDoc] = useState(false)
  const [designDocError, setDesignDocError] = useState<string | null>(null)

  const [testsGenerated, setTestsGenerated] = useState<TestsGenerateResponse | null>(null)
  const [generatingTests, setGeneratingTests] = useState(false)
  const [testsRun, setTestsRun] = useState<TestsRunResponse | null>(null)
  const [runningTests, setRunningTests] = useState(false)
  const [mutationCheck, setMutationCheck] = useState<MutationCheckResponse | null>(null)
  const [mutating, setMutating] = useState(false)
  const [testError, setTestError] = useState<string | null>(null)

  const [releaseNotes, setReleaseNotes] = useState<string | null>(null)
  const [draftingNotes, setDraftingNotes] = useState(false)

  const [openStage, setOpenStage] = useState<Stage | null>(null)

  const [checkingOut, setCheckingOut] = useState(false)
  const [checkedOut, setCheckedOut] = useState(false)

  const [quickChatMessages, setQuickChatMessages] = useState<
    { role: 'user' | 'assistant'; text: string }[]
  >([])
  const [quickChatInput, setQuickChatInput] = useState('')
  const [quickChatSending, setQuickChatSending] = useState(false)
  const [quickChatError, setQuickChatError] = useState<string | null>(null)
  const [quickChatResult, setQuickChatResult] = useState<QuickChatResponse | null>(null)

  const [creatingTicketFor, setCreatingTicketFor] = useState<string | null>(null)
  const [assigningTicketFor, setAssigningTicketFor] = useState<string | null>(null)
  const [createdTickets, setCreatedTickets] = useState<
    Record<string, { key: string; assignee: string | null }>
  >({})
  const [assigneeByApp, setAssigneeByApp] = useState<Record<string, string>>({})

  const [boardIssues, setBoardIssues] = useState<JiraIssue[] | null>(null)
  const [boardError, setBoardError] = useState<string | null>(null)
  const [boardLoading, setBoardLoading] = useState(false)
  const [boardFilter, setBoardFilter] = useState('')
  const [boardStatusFilter, setBoardStatusFilter] = useState<'all' | 'open' | 'done'>('all')

  // Manager's ticket-dashboard direct-assign controls — a plain "pick a
  // name, click Assign" per unassigned ticket, separate from the
  // create-a-cross-team-ticket flow inside the modal's AI Actions section.
  const [boardAssignee, setBoardAssignee] = useState<Record<string, string>>({})
  const [assigningBoardTicket, setAssigningBoardTicket] = useState<string | null>(null)

  // Which ticket's CR the codegen section (Generate/Tests/Release notes)
  // currently targets — set by clicking a board ticket. null means "nothing
  // assigned to this engineer with a linked CR yet."
  const [activeTicketKey, setActiveTicketKey] = useState<string | null>(null)
  const [expandedTicket, setExpandedTicket] = useState<string | null>(null)
  const [ticketAnalysis, setTicketAnalysis] = useState<Record<string, AnalyzeResponse>>(() => {
    const restored: Record<string, AnalyzeResponse> = {}
    for (const ticketKey of Object.keys(TICKET_TARGETS)) {
      const persisted = loadTicketState(ticketKey).analysis
      if (persisted) restored[ticketKey] = persisted
    }
    return restored
  })
  const [ticketAnalysisLoading, setTicketAnalysisLoading] = useState<Record<string, boolean>>({})
  const [ticketAnalysisError, setTicketAnalysisError] = useState<Record<string, string>>({})
  // Set only for ad-hoc (no-target) tickets whose last analyze-adhoc call
  // came back needs_clarification: true — see handleRunAnalysisForTicket.
  const [ticketClarificationQuestion, setTicketClarificationQuestion] = useState<
    Record<string, string>
  >({})
  const [ticketCrossTeam, setTicketCrossTeam] = useState<Record<string, CrossTeamImpact[]>>({})
  const [ticketCrossTeamTokens, setTicketCrossTeamTokens] = useState<Record<string, TokenPanelData>>({})
  const [ticketCrossTeamLoading, setTicketCrossTeamLoading] = useState<Record<string, boolean>>({})
  const [ticketCrText, setTicketCrText] = useState<Record<string, string>>({})
  const [ticketEvents, setTicketEvents] = useState<Record<string, TicketEvent[]>>({})
  const [ticketEventsLoading, setTicketEventsLoading] = useState<Record<string, boolean>>({})

  const [dependencies, setDependencies] = useState<JiraIssue[] | null>(null)
  const [dependenciesLoading, setDependenciesLoading] = useState(false)
  const [markingDone, setMarkingDone] = useState<string | null>(null)

  const [screenshotBefore, setScreenshotBefore] = useState<string | null>(null)
  const [screenshotAfter, setScreenshotAfter] = useState<string | null>(null)

  function handleCheckOut() {
    setCheckingOut(true)
    setCheckedOut(false)
    setTimeout(() => {
      setCheckingOut(false)
      setCheckedOut(true)
    }, 10000)
  }

  async function handleGenerate() {
    if (!activeTicketKey) return
    const active = TICKET_TARGETS[activeTicketKey]
    setGenerating(true)
    setGenerateError(null)
    setApplied(false)
    setApplyError(null)
    setAppliedFiles({})
    setRejectedFiles({})
    setRejectPromptFor(null)
    setPostApplyFailure(null)
    setFixCrashError(null)
    setDesignDoc(null)
    setDesignDocError(null)
    try {
      const result = await s3Api.generate(active?.tierName ?? 'Elite', active?.targetId, activeTicketKey)
      const collapsed = Object.fromEntries(result.files_changed.map((path) => [path, true]))
      setGenerated(result)
      setFilePaths(result.files_changed)
      setFileReasons(result.file_reasons || {})
      setCollapsedFiles(collapsed)
      setPerFileChat({})
      saveTicketState(activeTicketKey, {
        generated: result,
        filePaths: result.files_changed,
        fileReasons: result.file_reasons || {},
        collapsedFiles: collapsed,
        fileChats: {},
        applied: false,
        appliedFiles: {},
      })
    } catch (err) {
      setGenerateError(err instanceof ApiError ? err.message : 'Code generation failed.')
    } finally {
      setGenerating(false)
    }
  }

  async function handleAskAboutFile(path: string) {
    const question = (perFileQuestion[path] || '').trim()
    if (!generated || !question) return
    setRevisingFile(path)
    setReviseError(null)
    // Chat-style: the question posts to the thread immediately and the
    // composer clears, with a typing indicator until the reply arrives.
    const askedChats = {
      ...perFileChat,
      [path]: [...(perFileChat[path] || []), { role: 'user' as const, text: question }],
    }
    setPerFileChat(askedChats)
    setPerFileQuestion((prev) => ({ ...prev, [path]: '' }))
    try {
      const result = await s3Api.revise(generated.proposal_id, `For ${path}: ${question}`)
      const nextGenerated = { ...generated, diff_text: result.diff_text, files_changed: result.files_changed }
      const nextFilePaths = Array.from(new Set([...filePaths, ...result.files_changed]))
      const nextFileReasons =
        result.message && result.files_changed.includes(path)
          ? { ...fileReasons, [path]: result.message }
          : fileReasons
      // A question (or an edit the model declines to make) comes back with no
      // files_changed, so the diff above is byte-identical to before. Say that
      // outright — otherwise an answered question is indistinguishable from a
      // broken Ask, and the reviewer sits there waiting for a diff to move.
      const changedNothing = result.files_changed.length === 0
      const reply = result.message
        ? changedNothing
          ? `${result.message}\n\n(Answered your question — no code was changed.)`
          : result.message
        : changedNothing
          ? 'Answered your question — no code was changed.'
          : 'Done — see the updated diff above.'
      const nextChats = {
        ...askedChats,
        [path]: [...askedChats[path], { role: 'assistant' as const, text: reply }],
      }
      setGenerated(nextGenerated)
      setFilePaths(nextFilePaths)
      setFileReasons(nextFileReasons)
      setPerFileChat(nextChats)
      if (activeTicketKey) {
        saveTicketState(activeTicketKey, {
          generated: nextGenerated,
          filePaths: nextFilePaths,
          fileReasons: nextFileReasons,
          fileChats: nextChats,
        })
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Revision failed.'
      setPerFileChat((prev) => ({
        ...prev,
        [path]: [
          ...(prev[path] || []),
          { role: 'assistant' as const, text: `Something went wrong: ${message}` },
        ],
      }))
      setReviseError(message)
    } finally {
      setRevisingFile(null)
    }
  }

  async function handleApply() {
    if (!generated || !activeTicketKey) return
    setApplying(true)
    setApplyError(null)
    try {
      const result = await s3Api.apply(generated.proposal_id, activeTicketKey)
      const nextAppliedFiles = { ...appliedFiles }
      for (const path of result.applied_files) nextAppliedFiles[path] = true
      const failure = result.post_apply && !result.post_apply.ok ? result.post_apply : null
      setApplied(true)
      setAppliedFiles(nextAppliedFiles)
      setRejectedFiles(result.rejected_files)
      setPostApplyFailure(failure)
      setFixCrashError(null)
      saveTicketState(activeTicketKey, {
        applied: true,
        appliedFiles: nextAppliedFiles,
        rejectedFiles: result.rejected_files,
        postApplyFailure: failure,
      })
      void runDesignSync(generated.proposal_id, result.applied_files, activeTicketKey)
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.message : 'Apply failed.')
    } finally {
      setApplying(false)
    }
  }

  // Deliberately fire-and-forget, after Apply has already been recorded as
  // succeeded: a doc check that is slow, unreachable or broken must never be
  // able to fail the apply beat. The endpoint itself answers checked:false
  // rather than erroring, so this catch is only for transport failures.
  async function runDesignSync(proposalId: string, appliedPaths: string[], ticketKey: string) {
    const active = TICKET_TARGETS[ticketKey]
    try {
      const result = await s3Api.designSync(
        proposalId,
        appliedPaths,
        ticketKey,
        active?.targetId ?? undefined,
      )
      setDesignSync(result.findings.length > 0 ? result : null)
    } catch {
      setDesignSync(null)
    }
  }

  // A flagged design doc is an ordinary staged proposal, so it applies through
  // the same endpoint as the code change — no second apply path exists.
  async function handleApplyDesignDoc(finding: DesignDocFinding) {
    if (!activeTicketKey || !finding.proposal_id) return
    setDesignDocApplying(finding.proposal_id)
    try {
      await s3Api.apply(finding.proposal_id, activeTicketKey)
      setDesignDocApplied((prev) => ({ ...prev, [finding.proposal_id]: true }))
    } catch {
      // Left un-applied and still visible; the developer can retry.
    } finally {
      setDesignDocApplying(null)
    }
  }

  // One-click recovery when the applied change crashed the app's post-apply
  // migration: feed the crash line back into the normal revise loop. The
  // instruction is a stable template built from the final exception line (not
  // the whole traceback) so a demo recording of this revise turn replays.
  async function handleFixCrash() {
    if (!generated || !activeTicketKey || !postApplyFailure) return
    const failedStep = postApplyFailure.steps.find((step) => step.returncode !== 0)
    if (!failedStep) return
    const lines = failedStep.output_tail.trim().split('\n')
    const lastLine = lines[lines.length - 1]?.trim() ?? ''
    const instruction = `Fix the post-apply crash: \`${failedStep.command}\` failed with: ${lastLine}`
    setFixingCrash(true)
    setFixCrashError(null)
    try {
      const result = await s3Api.revise(generated.proposal_id, instruction)
      const nextGenerated = { ...generated, diff_text: result.diff_text, files_changed: result.files_changed }
      const nextFilePaths = Array.from(new Set([...filePaths, ...result.files_changed]))
      setGenerated(nextGenerated)
      setFilePaths(nextFilePaths)
      setApplied(false)
      setAppliedFiles({})
      setPostApplyFailure(null)
      saveTicketState(activeTicketKey, {
        generated: nextGenerated,
        filePaths: nextFilePaths,
        applied: false,
        appliedFiles: {},
        postApplyFailure: null,
      })
    } catch (err) {
      setFixCrashError(err instanceof ApiError ? err.message : 'Revision failed.')
    } finally {
      setFixingCrash(false)
    }
  }

  async function handleApplyFile(path: string) {
    if (!generated || !activeTicketKey) return
    setApplyingFile(path)
    setApplyError(null)
    try {
      const result = await s3Api.apply(generated.proposal_id, activeTicketKey, path)
      const nextAppliedFiles = { ...appliedFiles, [path]: true }
      setAppliedFiles(nextAppliedFiles)
      setRejectedFiles(result.rejected_files)
      saveTicketState(activeTicketKey, {
        appliedFiles: nextAppliedFiles,
        rejectedFiles: result.rejected_files,
      })
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.message : 'Apply failed.')
    } finally {
      setApplyingFile(null)
    }
  }

  async function handleRejectFile(path: string) {
    if (!generated || !activeTicketKey) return
    setRejectingFile(path)
    setApplyError(null)
    try {
      const result = await s3Api.reject(
        generated.proposal_id,
        path,
        rejectReason,
        activeTicketKey
      )
      setRejectedFiles(result.rejected_files)
      saveTicketState(activeTicketKey, { rejectedFiles: result.rejected_files })
      setRejectPromptFor(null)
      setRejectReason('')
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.message : 'Reject failed.')
    } finally {
      setRejectingFile(null)
    }
  }

  async function handleClearRejection(path: string) {
    if (!generated || !activeTicketKey) return
    setRejectingFile(path)
    try {
      const result = await s3Api.clearRejection(generated.proposal_id, path, activeTicketKey)
      setRejectedFiles(result.rejected_files)
      saveTicketState(activeTicketKey, { rejectedFiles: result.rejected_files })
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.message : 'Could not undo the rejection.')
    } finally {
      setRejectingFile(null)
    }
  }

  // Revert writes to the working tree exactly as Apply does, so it re-runs the
  // post-apply migration for the same reason: the running app has to stay
  // consistent with the files on disk.
  async function handleRevertFile(path: string) {
    if (!generated || !activeTicketKey) return
    setRevertingFile(path)
    setApplyError(null)
    try {
      const result = await s3Api.revert(generated.proposal_id, activeTicketKey, path)
      const nextAppliedFiles = { ...appliedFiles }
      for (const reverted of result.reverted_files) delete nextAppliedFiles[reverted]
      setAppliedFiles(nextAppliedFiles)
      setPostApplyFailure(result.post_apply && !result.post_apply.ok ? result.post_apply : null)
      saveTicketState(activeTicketKey, { appliedFiles: nextAppliedFiles })
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.message : 'Revert failed.')
    } finally {
      setRevertingFile(null)
    }
  }

  async function handleRevertAll() {
    if (!generated || !activeTicketKey) return
    setReverting(true)
    setApplyError(null)
    try {
      const result = await s3Api.revert(generated.proposal_id, activeTicketKey)
      setApplied(false)
      setAppliedFiles({})
      setPostApplyFailure(result.post_apply && !result.post_apply.ok ? result.post_apply : null)
      // The design-doc drift panel described the applied state; once that's
      // undone it is describing something that is no longer on disk.
      setDesignSync(null)
      saveTicketState(activeTicketKey, {
        applied: false,
        appliedFiles: {},
        postApplyFailure: null,
      })
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.message : 'Revert failed.')
    } finally {
      setReverting(false)
    }
  }

  async function handleAddFile() {
    if (!generated) return
    const path = newFilePath.trim()
    const instruction = newFileInstruction.trim()
    if (!path || !instruction) return
    setAddingFile(true)
    setAddFileError(null)
    try {
      const result = await s3Api.addFile(generated.proposal_id, path, instruction, activeTicketKey ?? undefined)
      const nextGenerated = { ...generated, diff_text: result.diff_text, files_changed: result.files_changed }
      const nextFilePaths = Array.from(new Set([...filePaths, ...result.files_changed]))
      // The file the developer just explicitly asked to add is worth showing
      // expanded immediately, unlike the initial batch's collapsed default.
      const nextCollapsedFiles = { ...collapsedFiles, [path]: false }
      const nextFileReasons = result.message ? { ...fileReasons, [path]: result.message } : fileReasons
      setGenerated(nextGenerated)
      setFilePaths(nextFilePaths)
      setCollapsedFiles(nextCollapsedFiles)
      setFileReasons(nextFileReasons)
      setNewFilePath('')
      setNewFileInstruction('')
      if (activeTicketKey) {
        saveTicketState(activeTicketKey, {
          generated: nextGenerated,
          filePaths: nextFilePaths,
          collapsedFiles: nextCollapsedFiles,
          fileReasons: nextFileReasons,
        })
      }
    } catch (err) {
      setAddFileError(err instanceof ApiError ? err.message : 'Could not add file to the proposal.')
    } finally {
      setAddingFile(false)
    }
  }

  async function handleGenerateTests() {
    if (!activeTicketKey) return
    const active = TICKET_TARGETS[activeTicketKey]
    setGeneratingTests(true)
    setTestError(null)
    try {
      const result = await s3Api.testsGenerate(
        active?.tierName ?? 'Elite',
        active?.targetId,
        activeTicketKey
      )
      setTestsGenerated(result)
      // A fresh generation invalidates any previous run/proof of the old file.
      setTestsRun(null)
      setMutationCheck(null)
      saveTicketState(activeTicketKey, {
        testsGenerated: result,
        testsRun: undefined,
        mutationCheck: undefined,
      })
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : 'Test generation failed.')
    } finally {
      setGeneratingTests(false)
    }
  }

  async function handleRunTests() {
    if (!activeTicketKey) return
    const active = TICKET_TARGETS[activeTicketKey]
    setRunningTests(true)
    setTestError(null)
    try {
      const result = await s3Api.testsRun(
        active?.tierName ?? 'Elite',
        active?.targetId,
        activeTicketKey
      )
      setTestsRun(result)
      saveTicketState(activeTicketKey, { testsRun: result })
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : 'Test run failed.')
    } finally {
      setRunningTests(false)
    }
  }

  async function handleMutationCheck() {
    if (!activeTicketKey) return
    const active = TICKET_TARGETS[activeTicketKey]
    setMutating(true)
    setTestError(null)
    try {
      const result = await s3Api.testsMutation(
        active?.tierName ?? 'Elite',
        active?.targetId,
        activeTicketKey
      )
      setMutationCheck(result)
      saveTicketState(activeTicketKey, { mutationCheck: result })
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : 'Mutation check failed.')
    } finally {
      setMutating(false)
    }
  }

  async function handleDraftDesignDoc() {
    if (!activeTicketKey) return
    const active = TICKET_TARGETS[activeTicketKey]
    setDraftingDesignDoc(true)
    setDesignDocError(null)
    try {
      const result = await s3Api.designDoc(active?.tierName ?? 'Elite', active?.targetId, activeTicketKey)
      setDesignDoc(result.design_doc)
      saveTicketState(activeTicketKey, { designDoc: result.design_doc })
    } catch (err) {
      setDesignDocError(err instanceof ApiError ? err.message : 'Design doc drafting failed.')
    } finally {
      setDraftingDesignDoc(false)
    }
  }

  async function handleDraftReleaseNotes() {
    if (!activeTicketKey) return
    const active = TICKET_TARGETS[activeTicketKey]
    setDraftingNotes(true)
    try {
      const result = await s3Api.releaseNotes(active?.tierName ?? 'Elite', active?.targetId)
      setReleaseNotes(result.release_notes)
      saveTicketState(activeTicketKey, { releaseNotes: result.release_notes })
    } finally {
      setDraftingNotes(false)
    }
  }

  async function handleHandoffToQa() {
    if (!activeTicketKey) return
    const tester = qaTester || TESTER_ROSTER[0]
    setHandingOff(true)
    setHandoffError(null)
    try {
      await s3Api.assignTicket(activeTicketKey, tester)
      await s3Api.setTicketStatus(activeTicketKey, 'QA')
      setBoardIssues((prev) =>
        (prev || []).map((issue) =>
          issue.key === activeTicketKey ? { ...issue, assignee: tester, status: 'QA' } : issue
        )
      )
      loadTicketEvents(activeTicketKey)
    } catch (err) {
      setHandoffError(err instanceof ApiError ? err.message : 'QA hand-off failed.')
    } finally {
      setHandingOff(false)
    }
  }

  async function handleMarkTicketDone() {
    if (!activeTicketKey) return
    setClosingTicket(true)
    try {
      await s3Api.setTicketStatus(activeTicketKey, 'Done')
      setBoardIssues((prev) =>
        (prev || []).map((issue) =>
          issue.key === activeTicketKey ? { ...issue, status: 'Done' } : issue
        )
      )
      loadTicketEvents(activeTicketKey)
    } finally {
      setClosingTicket(false)
    }
  }

  function toggleStage(stage: Stage) {
    setOpenStage((prev) => (prev === stage ? null : stage))
  }

  async function handleQuickChatSend() {
    const message = quickChatInput.trim()
    if (!message) return
    setQuickChatSending(true)
    setQuickChatError(null)
    setQuickChatMessages((prev) => [...prev, { role: 'user', text: message }])
    setQuickChatInput('')
    setQuickChatResult(null)
    try {
      const result = await s3Api.quickImpactChat(message)
      if (result.needs_clarification && result.question) {
        setQuickChatMessages((prev) => [...prev, { role: 'assistant', text: result.question! }])
      } else {
        setQuickChatResult(result)
      }
    } catch (err) {
      setQuickChatError(err instanceof ApiError ? err.message : 'Quick question failed.')
    } finally {
      setQuickChatSending(false)
    }
  }

  async function handleQuickChatReset() {
    setQuickChatMessages([])
    setQuickChatResult(null)
    setQuickChatError(null)
    setQuickChatInput('')
    try {
      await s3Api.quickImpactChat('', true)
    } catch {
      // best-effort — a stale server-side history is harmless, it just gets
      // overwritten by the next real message anyway.
    }
  }

  async function handleCreateCrossTeamTicket(impact: CrossTeamImpact, primaryTicketKey: string) {
    setCreatingTicketFor(impact.app_name)
    try {
      // Created open/unassigned — assignment is a deliberate separate step
      // (see handleAssignCrossTeamTicket) so it's visible to the manager as
      // open and can be assigned whenever, not forced at creation time.
      const result = await s3Api.createCrossTeamTicket(
        impact.app_name,
        impact.suggested_summary,
        impact.reason,
        primaryTicketKey
      )
      setCreatedTickets((prev) => ({
        ...prev,
        [impact.app_name]: { key: result.issue.key, assignee: null },
      }))
    } catch {
      // surfaced inline via the modal's own error state in a future pass —
      // for now a failed create just leaves the "Create ticket" button live.
    } finally {
      setCreatingTicketFor(null)
    }
  }

  async function handleAssignCrossTeamTicket(appName: string) {
    const created = createdTickets[appName]
    if (!created) return
    const assignee = assigneeByApp[appName] || ASSIGNEE_ROSTER[0]
    setAssigningTicketFor(appName)
    try {
      await s3Api.assignTicket(created.key, assignee)
      setCreatedTickets((prev) => ({ ...prev, [appName]: { ...created, assignee } }))
    } finally {
      setAssigningTicketFor(null)
    }
  }

  async function handleLoadBoard() {
    setBoardLoading(true)
    setBoardError(null)
    try {
      const result = await s3Api.jiraBoard()
      setBoardIssues(result.issues)
    } catch (err) {
      setBoardError(err instanceof ApiError ? err.message : 'Could not reach Jira.')
    } finally {
      setBoardLoading(false)
    }
  }

  async function handleAssignBoardTicket(key: string) {
    const assignee = boardAssignee[key] || ASSIGNEE_ROSTER[0]
    setAssigningBoardTicket(key)
    try {
      await s3Api.assignTicket(key, assignee)
      setBoardIssues((prev) => (prev || []).map((issue) => (issue.key === key ? { ...issue, assignee } : issue)))
      loadTicketEvents(key)
    } finally {
      setAssigningBoardTicket(null)
    }
  }

  function handleTicketClick(ticketKey: string) {
    setExpandedTicket(ticketKey)
    const linked = TICKET_TARGETS[ticketKey]
    // Only tickets with a real codegen target (AMS-101/102 today) should
    // change what "Generate the change" below acts on — a cross-team
    // ticket like AMS-500 has no target, and silently falling back to the
    // default CR would be confusing with no indication it happened.
    if (linked) {
      setActiveTicketKey(ticketKey)
      if (!ticketCrText[ticketKey]) {
        s3Api
          .cr(linked.tierName, linked.targetId)
          .then((result) => setTicketCrText((prev) => ({ ...prev, [ticketKey]: result.cr_text })))
          .catch(() => {})
      }
    }
    loadTicketEvents(ticketKey)
  }

  async function loadTicketEvents(ticketKey: string) {
    setTicketEventsLoading((prev) => ({ ...prev, [ticketKey]: true }))
    try {
      const result = await s3Api.ticketEvents(ticketKey)
      setTicketEvents((prev) => ({ ...prev, [ticketKey]: result.events }))
    } catch {
      setTicketEvents((prev) => ({ ...prev, [ticketKey]: [] }))
    } finally {
      setTicketEventsLoading((prev) => ({ ...prev, [ticketKey]: false }))
    }
  }

  async function handleRunAnalysisForTicket(ticketKey: string, clarificationAnswer?: string) {
    const linked = TICKET_TARGETS[ticketKey]
    setTicketAnalysisLoading((prev) => ({ ...prev, [ticketKey]: true }))
    setTicketAnalysisError((prev) => ({ ...prev, [ticketKey]: '' }))
    try {
      let result: AnalyzeResponse
      const pendingQuestion = ticketClarificationQuestion[ticketKey]
      if (linked) {
        let answer: string | undefined
        if (pendingQuestion) {
          // A clarifying question is outstanding (e.g. an unstated field
          // default check_cr_gaps caught) — this call carries the
          // engineer's answer; the server keeps the transcript.
          answer = (clarificationAnswer || '').trim()
          if (!answer) return
        }
        const analyzeResult = await s3Api.analyze(
          linked.tierName,
          linked.targetId,
          ticketKey,
          answer,
          !pendingQuestion
        )
        if (analyzeResult.needs_clarification) {
          setTicketClarificationQuestion((prev) => ({
            ...prev,
            [ticketKey]: analyzeResult.question || '',
          }))
          return
        }
        setTicketClarificationQuestion((prev) => {
          if (!(ticketKey in prev)) return prev
          const next = { ...prev }
          delete next[ticketKey]
          return next
        })
        result = {
          label: analyzeResult.label,
          impact_analysis: analyzeResult.impact_analysis || '',
          assumptions: analyzeResult.assumptions || [],
          effort_estimate: analyzeResult.effort_estimate as EffortEstimate,
          file_selection: analyzeResult.file_selection,
          token_panel: analyzeResult.token_panel,
        }
      } else {
        // No CR/target registered for this ticket (e.g. a cross-team ticket
        // for another application) — analyze its own text directly instead.
        let crText: string
        if (pendingQuestion) {
          // A clarifying question is outstanding — this call carries the
          // engineer's answer, not the original ticket text again (the
          // server keeps the transcript server-side).
          crText = (clarificationAnswer || '').trim()
          if (!crText) return
        } else {
          const issue = (boardIssues || []).find((candidate) => candidate.key === ticketKey)
          crText = [issue?.summary, issue?.description].filter(Boolean).join('\n\n').trim()
          if (!crText) return
        }
        // The ticket's own ServiceNow context, when it arrived with any —
        // present, it routes deterministically and the server skips the LLM
        // repo match entirely (see api/routers/s3.py's analyze_adhoc).
        const issueForRouting = (boardIssues || []).find(
          (candidate) => candidate.key === ticketKey
        )
        const adhocResult = await s3Api.analyzeAdhoc(crText, ticketKey, !pendingQuestion, {
          ci: issueForRouting?.ci,
          businessService: issueForRouting?.business_service,
        })
        if (adhocResult.needs_clarification) {
          setTicketClarificationQuestion((prev) => ({
            ...prev,
            [ticketKey]: adhocResult.question || '',
          }))
          return
        }
        setTicketClarificationQuestion((prev) => {
          if (!(ticketKey in prev)) return prev
          const next = { ...prev }
          delete next[ticketKey]
          return next
        })
        result = {
          label: adhocResult.label,
          impact_analysis: adhocResult.impact_analysis || '',
          assumptions: adhocResult.assumptions || [],
          effort_estimate: adhocResult.effort_estimate as EffortEstimate,
          target_repo: adhocResult.target_repo,
          routing: adhocResult.routing,
        }
      }
      setTicketAnalysis((prev) => ({ ...prev, [ticketKey]: result }))
      saveTicketState(ticketKey, { analysis: result })
      // Work has visibly started on this ticket — move it out of To Do,
      // exactly like an engineer would drag the card on a real board.
      const issue = (boardIssues || []).find((candidate) => candidate.key === ticketKey)
      if ((issue?.status || 'To Do') === 'To Do') {
        try {
          await s3Api.setTicketStatus(ticketKey, 'In Progress')
          setBoardIssues((prev) =>
            (prev || []).map((candidate) =>
              candidate.key === ticketKey ? { ...candidate, status: 'In Progress' } : candidate
            )
          )
        } catch {
          // Board status is presentation state — the analysis itself succeeded.
        }
      }
      loadTicketEvents(ticketKey)
    } catch (err) {
      setTicketAnalysisError((prev) => ({
        ...prev,
        [ticketKey]: err instanceof ApiError ? err.message : 'Impact analysis unavailable.',
      }))
    } finally {
      setTicketAnalysisLoading((prev) => ({ ...prev, [ticketKey]: false }))
    }
  }

  async function handleCheckCrossTeamForTicket(ticketKey: string) {
    const linked = TICKET_TARGETS[ticketKey]
    if (!linked) return
    setTicketCrossTeamLoading((prev) => ({ ...prev, [ticketKey]: true }))
    try {
      const result = await s3Api.crossTeamImpact(linked.tierName, linked.targetId, ticketKey)
      setTicketCrossTeam((prev) => ({ ...prev, [ticketKey]: result.impacts }))
      setTicketCrossTeamTokens((prev) => ({ ...prev, [ticketKey]: result.token_panel }))
      setAssigneeByApp((prev) => ({
        ...Object.fromEntries(result.impacts.map((impact) => [impact.app_name, ASSIGNEE_ROSTER[0]])),
        ...prev,
      }))
      loadTicketEvents(ticketKey)
    } catch {
      setTicketCrossTeam((prev) => ({ ...prev, [ticketKey]: [] }))
    } finally {
      setTicketCrossTeamLoading((prev) => ({ ...prev, [ticketKey]: false }))
    }
  }

  async function loadDependencies(ticketKey: string) {
    setDependenciesLoading(true)
    try {
      const result = await s3Api.jiraDependencies(ticketKey)
      setDependencies(result.dependencies)
    } catch {
      setDependencies([])
    } finally {
      setDependenciesLoading(false)
    }
  }

  async function handleMarkDone(key: string) {
    setMarkingDone(key)
    try {
      await s3Api.setTicketStatus(key, 'Done')
      setDependencies((prev) =>
        (prev || []).map((dep) => (dep.key === key ? { ...dep, status: 'Done' } : dep))
      )
    } finally {
      setMarkingDone(null)
    }
  }

  // Both roles need the board: the manager's dashboard lists every ticket,
  // the engineer's board is filtered down to just their own (see below).
  useEffect(() => {
    handleLoadBoard()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Drop any locally-cached analysis/proposal state left over from before a
  // demo/reset_s3.sh — see clearAllPersistedTicketState() above.
  useEffect(() => {
    s3Api
      .resetMarker()
      .then(({ marker }) => {
        // A null lastSeen (nothing recorded yet) counts as a mismatch too:
        // any cached ticket state from before marker tracking began has no
        // provenance, so it can't be trusted to predate the last reset.
        const lastSeen = localStorage.getItem(RESET_MARKER_STORAGE_KEY)
        if (lastSeen !== marker) {
          clearAllPersistedTicketState()
          setTicketAnalysis({})
          setGenerated(null)
          setFilePaths([])
          setFileReasons({})
          setCollapsedFiles({})
          setApplied(false)
          setAppliedFiles({})
          setRejectedFiles({})
          setPostApplyFailure(null)
        }
        try {
          localStorage.setItem(RESET_MARKER_STORAGE_KEY, marker)
        } catch {
          // localStorage unavailable — nothing to persist.
        }
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!isEngineer) return
    s3Api
      .screenshot('before')
      .then((r) => setScreenshotBefore(r.image_base64))
      .catch(() => setScreenshotBefore(null))
  }, [isEngineer])

  // Auto-pick which ticket the codegen section targets: the first ticket
  // assigned to this engineer that has a linked CR. Re-evaluated whenever
  // the board changes (e.g. a manager just assigned something) so a ticket
  // reassigned away from this engineer doesn't leave a stale target.
  useEffect(() => {
    if (!isEngineer || !boardIssues) return
    setActiveTicketKey((prev) => {
      if (prev && boardIssues.some((issue) => issue.key === prev && issue.assignee === identity?.name)) {
        return prev
      }
      const mine = boardIssues.find(
        (issue) => issue.assignee === identity?.name && TICKET_TARGETS[issue.key]
      )
      return mine ? mine.key : null
    })
  }, [isEngineer, boardIssues, identity?.name])

  useEffect(() => {
    if (!isEngineer || !activeTicketKey) return
    loadDependencies(activeTicketKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEngineer, activeTicketKey])

  // Restore whatever proposal was already generated for this ticket (e.g.
  // after a page reload, or switching back to a ticket worked on earlier) —
  // saveTicketState() above is what keeps this in sync as the user works.
  useEffect(() => {
    if (!activeTicketKey) return
    const persisted = loadTicketState(activeTicketKey)
    setGenerated(persisted.generated ?? null)
    setFilePaths(persisted.filePaths ?? persisted.generated?.files_changed ?? [])
    setFileReasons(persisted.fileReasons ?? persisted.generated?.file_reasons ?? {})
    setCollapsedFiles(persisted.collapsedFiles ?? {})
    setApplied(persisted.applied ?? false)
    setAppliedFiles(persisted.appliedFiles ?? {})
    setRejectedFiles(persisted.rejectedFiles ?? {})
    setRejectPromptFor(null)
    setPostApplyFailure(persisted.postApplyFailure ?? null)
    setFixCrashError(null)
    setPerFileChat(persisted.fileChats ?? {})
    setPerFileQuestion({})
    setDesignDoc(persisted.designDoc ?? null)
    setTestsGenerated(persisted.testsGenerated ?? null)
    setTestsRun(persisted.testsRun ?? null)
    setMutationCheck(persisted.mutationCheck ?? null)
    setReleaseNotes(persisted.releaseNotes ?? null)
    setHandoffError(null)
  }, [activeTicketKey])

  useEffect(() => {
    setOpenStage(null)
  }, [activeTicketKey])

  useEffect(() => {
    if (!applied) return
    s3Api
      .screenshot('after')
      .then((r) => setScreenshotAfter(r.image_base64))
      .catch(() => setScreenshotAfter(null))
  }, [applied])

  const openDependencies = (dependencies || []).filter((dep) => dep.status !== 'Done')
  const diffFiles = generated ? parseDiff(generated.diff_text) : []
  const diffByPath = new Map(diffFiles.map((file) => [file.path, file]))
  // Only files with an actual pending diff get a review card — a file the
  // model returned unchanged (or one already applied to the repo) is not a
  // change to review. Preserve filePaths ordering for the ones that remain.
  const orderedFilePaths = Array.from(
    new Set([...filePaths, ...diffFiles.map((file) => file.path)])
  ).filter((path) => diffByPath.has(path))
  const activeLinked = activeTicketKey ? TICKET_TARGETS[activeTicketKey] : undefined
  // Which running app an applied change should send the reviewer to. Falls back
  // to the mockapp portal for the two mockapp targets (and for a ticket with no
  // linked target at all, where nothing is applyable anyway).
  const targetApp =
    (activeLinked?.targetId ? TARGET_APPS[activeLinked.targetId] : undefined) ?? DEFAULT_TARGET_APP
  const analysisDoneForActive = activeTicketKey ? !!ticketAnalysis[activeTicketKey] : false
  const activeIssue = activeTicketKey
    ? (boardIssues || []).find((issue) => issue.key === activeTicketKey)
    : undefined
  const inQa = activeIssue?.status === 'QA' || activeIssue?.status === 'Done'
  const isActiveAssignee = !!identity && activeIssue?.assignee === identity.name

  const generateLockedReason = !activeTicketKey
    ? 'Select a ticket assigned to you on the Jira board above.'
    : !analysisDoneForActive
      ? 'Open the ticket above and run AI impact analysis first.'
      : openDependencies.length > 0
        ? `Waiting on ${openDependencies.length} other team${openDependencies.length > 1 ? 's' : ''} to finish their tickets.`
        : null
  const canGenerate = generateLockedReason === null

  const canDesignDoc = generated !== null && (generated.diff_text.trim() === '' || applied)
  const designDocLockedReason = canDesignDoc
    ? null
    : 'Apply the proposed change above before drafting a design doc.'

  // Tests belong to QA: the ticket must be handed off (status QA) and the
  // logged-in user must be the assigned tester — the developer who wrote the
  // change doesn't get to verify it themselves.
  const canTest = canDesignDoc && !!designDoc && inQa && isActiveAssignee
  const testLockedReason = canTest
    ? null
    : !canDesignDoc
      ? designDocLockedReason
      : !designDoc
        ? 'Draft the design doc above before generating tests.'
        : !inQa
          ? 'Hand the ticket off to QA above — the assigned tester runs this step.'
          : `With QA — only ${activeIssue?.assignee || 'the assigned tester'} can generate and run tests.`

  const canDraftNotes = !!testsRun && (!inQa || isActiveAssignee)
  const notesLockedReason = canDraftNotes
    ? null
    : testsRun
      ? `With QA — only ${activeIssue?.assignee || 'the assigned tester'} can draft release notes.`
      : 'Generate and run tests first.'

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '2rem 1.5rem' }}>
      <span className="ams-eyebrow">
        MapleSure Insurance · AMS Console · S3
      </span>
      <h1 style={{ fontSize: '1.7rem', margin: '0.6rem 0 0.3rem' }}>Enhancement Delivery</h1>
      <p style={{ color: 'var(--ams-ink-soft)', maxWidth: '70ch', marginBottom: '1.5rem' }}>
        Live CR intake, AI-assisted code generation, generated tests, and release notes.
      </p>

      {isManager && (
      <>
      <div id="quick-question" className="ams-card" style={{ marginBottom: '1.25rem' }}>
        <strong>Quick question</strong>
        <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0.6rem' }}>
          Ask about a hypothetical change before there's a formal CR — e.g. "how much would it
          cost if I just changed a text field on the endorsement form?" Asks a clarifying
          question or two if it needs more detail, then sizes it.
        </p>
        {quickChatMessages.length > 0 && (
          <div className="ams-chat-thread" style={{ marginBottom: '0.6rem' }}>
            {quickChatMessages.map((turn, index) => (
              <div
                key={index}
                className="ams-chat-bubble"
                data-role={turn.role}
                style={{
                  fontSize: '0.85rem',
                  margin: '0.3rem 0',
                  padding: '0.5rem 0.75rem',
                  borderRadius: 6,
                  maxWidth: '80%',
                  marginLeft: turn.role === 'user' ? 'auto' : 0,
                  background: turn.role === 'user' ? 'var(--ams-accent)' : 'var(--ams-surface)',
                  color: turn.role === 'user' ? '#fff' : 'inherit',
                  border: turn.role === 'assistant' ? '1px solid var(--ams-line)' : 'none',
                }}
              >
                {turn.text}
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            className="ams-input"
            style={{ flex: 1 }}
            placeholder="Ask a quick question…"
            value={quickChatInput}
            onChange={(event) => setQuickChatInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !quickChatSending) handleQuickChatSend()
            }}
            disabled={quickChatSending}
          />
          <button
            className="ams-button"
            onClick={handleQuickChatSend}
            disabled={quickChatSending || !quickChatInput.trim()}
          >
            {quickChatSending ? 'Asking…' : 'Ask'}
          </button>
          {(quickChatMessages.length > 0 || quickChatResult) && (
            <button className="ams-button-secondary" onClick={handleQuickChatReset}>
              New question
            </button>
          )}
        </div>
        {quickChatError && <p style={{ color: 'var(--ams-error)' }}>{quickChatError}</p>}
        {quickChatResult && (
          <div className="ams-card" style={{ marginTop: '0.75rem' }}>
            <strong>{quickChatResult.label}</strong>
            <div style={{ whiteSpace: 'pre-wrap', fontSize: '0.9rem', marginTop: '0.5rem' }}>
              {quickChatResult.impact_analysis}
            </div>
            {quickChatResult.effort_estimate && (
              <div style={{ display: 'flex', gap: '2rem', marginTop: '0.75rem' }}>
                <div>
                  <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>Effort</div>
                  <div style={{ fontWeight: 700 }}>
                    {quickChatResult.effort_estimate.hours_class}
                  </div>
                </div>
                <div>
                  <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>
                    Priority-equivalent
                  </div>
                  <div style={{ fontWeight: 700 }}>
                    {quickChatResult.effort_estimate.priority_equivalent}
                  </div>
                </div>
                <div style={{ fontSize: '0.85rem', flex: 1 }}>
                  {quickChatResult.effort_estimate.reasoning}
                </div>
              </div>
            )}
            {quickChatResult.code_change_warranted && (
              <p style={{ fontSize: '0.85rem', marginTop: '0.5rem' }}>
                A concrete code change looks warranted:{' '}
                <strong>{quickChatResult.suggested_cr_summary}</strong>
              </p>
            )}
          </div>
        )}
      </div>

      <div id="ticket-dashboard" className="ams-card">
        <strong>Ticket dashboard</strong>
        <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0.6rem' }}>
          Assign an open ticket to an engineer — once assigned, they'll see it on their own
          Jira board the next time they log in.
        </p>
        {boardLoading && (
          <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)' }}>Loading…</p>
        )}
        {boardError && <p style={{ color: 'var(--ams-error)' }}>{boardError}</p>}
        {boardIssues && (
          <div className="ams-dashboard-list">
            {boardIssues.map((issue) => (
              <div
                key={issue.key}
                className={`ams-dashboard-row${expandedTicket === issue.key ? ' ams-dashboard-row-selected' : ''}`}
              >
                <div
                  role="button"
                  tabIndex={0}
                  className="ams-dashboard-row-main"
                  onClick={() => handleTicketClick(issue.key)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') handleTicketClick(issue.key)
                  }}
                >
                  <span style={{ fontWeight: 700 }}>{issue.key}</span>
                  <span style={{ color: 'var(--ams-ink-soft)' }}>{issue.summary}</span>
                  <span className="ams-pill ams-pill-general">{issue.status || 'To Do'}</span>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexShrink: 0 }}>
                  {issue.assignee ? (
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.85rem' }}>
                      <span className="ams-avatar" title={issue.assignee}>
                        {issue.assignee.trim().charAt(0).toUpperCase()}
                      </span>
                      {issue.assignee}
                    </span>
                  ) : (
                    <>
                      <select
                        className="ams-select"
                        style={{ width: 'auto' }}
                        value={boardAssignee[issue.key] || ASSIGNEE_ROSTER[0]}
                        onChange={(event) =>
                          setBoardAssignee((prev) => ({ ...prev, [issue.key]: event.target.value }))
                        }
                      >
                        {ASSIGNEE_ROSTER.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </select>
                      <button
                        className="ams-button-secondary"
                        onClick={() => handleAssignBoardTicket(issue.key)}
                        disabled={assigningBoardTicket === issue.key}
                      >
                        {assigningBoardTicket === issue.key ? 'Assigning…' : 'Assign'}
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      </>
      )}

      {isEngineer && (
      <>
      <div className="ams-card" style={{ marginBottom: '1.25rem' }}>
        <strong>Step 0 · Check out the repo</strong>
        <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0.6rem' }}>
          Visual representation only — this demo works against the repo already on
          disk; no real git operation runs here.
        </p>
        <button
          className="ams-button"
          onClick={handleCheckOut}
          disabled={checkingOut}
        >
          {checkingOut ? 'Checking out…' : 'Check out mockapp'}
        </button>
        {checkedOut && !checkingOut && (
          <p style={{ fontSize: '0.85rem', marginTop: '0.5rem' }}>
            ✓ Checked out <code>mockapp</code> @ <code>main</code> (<code>a3f9c21</code>)
          </p>
        )}
      </div>

      {/* Jira board */}
      <div id="board" className="ams-card" style={{ marginBottom: '1.25rem' }}>
        <strong>Jira board</strong>
        <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0.6rem' }}>
          Showing tickets assigned to {identity?.name}.
        </p>
        {boardLoading && (
          <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)' }}>Loading…</p>
        )}
        {boardError && <p style={{ color: 'var(--ams-error)' }}>{boardError}</p>}
        {boardIssues && (() => {
          const mine = boardIssues.filter((issue) => issue.assignee === identity?.name)
          const openCount = mine.filter((issue) => issue.status !== 'Done').length
          const doneCount = mine.filter((issue) => issue.status === 'Done').length
          const query = boardFilter.trim().toLowerCase()
          const visibleIssues = mine.filter((issue) => {
            const matchesQuery =
              !query ||
              issue.key.toLowerCase().includes(query) ||
              (issue.summary || '').toLowerCase().includes(query)
            const matchesStatus =
              boardStatusFilter === 'all' ||
              (boardStatusFilter === 'done' ? issue.status === 'Done' : issue.status !== 'Done')
            return matchesQuery && matchesStatus
          })
          return (
          <>
          <div className="ams-board-toolbar" style={{ marginTop: '0.75rem' }}>
            <input
              className="ams-input ams-board-search"
              placeholder="Filter by key or summary…"
              value={boardFilter}
              onChange={(event) => setBoardFilter(event.target.value)}
            />
            <div className="ams-board-counts">
              <button
                className={`ams-board-count${boardStatusFilter === 'open' ? ' ams-board-count-active' : ''}`}
                onClick={() => setBoardStatusFilter(boardStatusFilter === 'open' ? 'all' : 'open')}
              >
                Open <span className="ams-board-count-value">{openCount}</span>
              </button>
              <button
                className={`ams-board-count${boardStatusFilter === 'done' ? ' ams-board-count-active' : ''}`}
                onClick={() => setBoardStatusFilter(boardStatusFilter === 'done' ? 'all' : 'done')}
              >
                Done <span className="ams-board-count-value">{doneCount}</span>
              </button>
            </div>
          </div>
          {mine.length === 0 && (
            <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)' }}>
              Nothing assigned to you yet — check back once a manager assigns you a ticket.
            </p>
          )}
          <div className="ams-board" style={{ display: 'flex', gap: '0.75rem' }}>
            {['To Do', 'In Progress', 'QA', 'Done'].map((status) => (
              <div
                key={status}
                className="ams-board-column"
                style={{ flex: 1, minWidth: 0 }}
              >
                <div style={{ fontSize: '0.8rem', color: 'var(--ams-ink-soft)', marginBottom: '0.4rem' }}>
                  {status}
                </div>
                {visibleIssues
                  .filter((issue) => (issue.status || 'To Do') === status)
                  .map((issue) => (
                    <div
                      key={issue.key}
                      className={`ams-ticket-card${
                        issue.key === expandedTicket || issue.key === activeTicketKey
                          ? ' ams-ticket-card-selected'
                          : ''
                      }`}
                      role="button"
                      tabIndex={0}
                      style={{ cursor: 'pointer' }}
                      onClick={() => handleTicketClick(issue.key)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') handleTicketClick(issue.key)
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem' }}>
                        <span style={{ fontWeight: 700 }}>{issue.key}</span>
                        {issue.assignee && (
                          <span className="ams-avatar" title={issue.assignee}>
                            {issue.assignee.trim().charAt(0).toUpperCase()}
                          </span>
                        )}
                      </div>
                      <div style={{ marginTop: '0.25rem' }}>{issue.summary}</div>
                      {issue.origin === 'problem_record' && (
                        <span
                          className="ams-pill ams-pill-preview"
                          style={{ marginTop: '0.4rem', display: 'inline-block' }}
                          title={issue.problem_id ? `Derived from ${issue.problem_id}` : undefined}
                        >
                          From problem record
                        </span>
                      )}
                    </div>
                  ))}
              </div>
            ))}
          </div>
          </>
          )
        })()}
        {(screenshotBefore || screenshotAfter) && (
          <div style={{ display: 'flex', gap: '1rem', marginTop: '0.75rem' }}>
            {screenshotBefore && (
              <div>
                <div style={{ fontSize: '0.8rem', color: 'var(--ams-ink-soft)' }}>Before</div>
                <img
                  src={`data:image/png;base64,${screenshotBefore}`}
                  alt="Endorsement form before the change"
                  style={{ maxWidth: 220, border: '1px solid var(--ams-line)', borderRadius: 4 }}
                />
              </div>
            )}
            {screenshotAfter && (
              <div>
                <div style={{ fontSize: '0.8rem', color: 'var(--ams-ink-soft)' }}>After</div>
                <img
                  src={`data:image/png;base64,${screenshotAfter}`}
                  alt="Endorsement form after the change"
                  style={{ maxWidth: 220, border: '1px solid var(--ams-line)', borderRadius: 4 }}
                />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Codegen */}
      <div id="codegen">
      {!dependenciesLoading && openDependencies.length > 0 && (
        <div
          className="ams-card"
          style={{ marginBottom: '1rem', borderLeft: '3px solid var(--ams-warning)' }}
        >
          <strong>Waiting on {openDependencies.length} other team{openDependencies.length > 1 ? 's' : ''}</strong>
          <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0.6rem' }}>
            Someone (logged in as that team) marks their ticket Done, then it clears here —
            no need to reload as {identity?.name}.
          </p>
          {openDependencies.map((dep) => (
            <div
              key={dep.key}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '0.3rem 0',
              }}
            >
              <span style={{ fontSize: '0.85rem' }}>
                {dep.key} — {dep.summary} <span style={{ color: 'var(--ams-ink-soft)' }}>({dep.status})</span>
              </span>
              <button
                className="ams-button-secondary"
                onClick={() => handleMarkDone(dep.key)}
                disabled={markingDone === dep.key}
              >
                {markingDone === dep.key ? 'Marking…' : 'Mark as Done'}
              </button>
            </div>
          ))}
        </div>
      )}
      <p style={{ fontSize: '0.8rem', color: 'var(--ams-ink-soft)', marginTop: '1.5rem' }}>
        {activeTicketKey ? (
          <>
            Generating for <strong>{activeLinked?.crLabel}</strong> ({activeTicketKey}) — click a
            ticket on the board above to switch.
          </>
        ) : (
          'No ticket assigned to you with a linked CR yet — once one is, pick it up here.'
        )}
      </p>

      <StageCard
        index={1}
        title="Generate the change"
        locked={!canGenerate && !generated}
        lockedHint={generateLockedReason}
        statusLabel={
          applied && postApplyFailure
            ? '⚠ Applied — app broken'
            : applied
              ? '✓ Applied'
              : generated
                ? 'Proposed'
                : null
        }
        statusVariant={applied && postApplyFailure ? 'error' : 'ok'}
        open={openStage === 'generate'}
        onToggle={() => toggleStage('generate')}
      >
        <div>
          <button className="ams-button" onClick={handleGenerate} disabled={generating}>
            Generate the change
          </button>
        </div>
        {generateError && <p style={{ color: 'var(--ams-error)' }}>{generateError}</p>}
        {generated && (
          <>
            {generated.diff_text.trim() ? (
              <>
                <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)', marginTop: '0.75rem' }}>
                  {AI_LABEL} Nothing has been written to the repo yet — ask a question about any file
                  below, or apply once you've reviewed the diff.
                </p>
                {orderedFilePaths.map((path) => {
                  const file = diffByPath.get(path)
                  const collapsed = collapsedFiles[path] ?? true
                  return (
                    <div key={path} className="ams-diff-file">
                      <div
                        className="ams-diff-file-header"
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          cursor: 'pointer',
                          ...(collapsed
                            ? { borderRadius: 6, borderBottom: '1px solid var(--ams-line)' }
                            : {}),
                        }}
                        onClick={() =>
                          setCollapsedFiles((prev) => ({ ...prev, [path]: !collapsed }))
                        }
                      >
                        <span>{path}</span>
                        <span style={{ fontWeight: 400, fontSize: '0.78rem' }}>
                          {collapsed ? '▸ Show diff' : '▾ Hide diff'}
                        </span>
                      </div>
                      {fileReasons[path] && (
                        <p
                          style={{
                            fontSize: '0.8rem',
                            fontStyle: 'italic',
                            color: 'var(--ams-ink-soft)',
                            margin: '0.4rem 0.7rem',
                          }}
                        >
                          {fileReasons[path]}
                        </p>
                      )}
                      {path in rejectedFiles && (
                        <div
                          style={{
                            display: 'flex',
                            gap: '0.5rem',
                            alignItems: 'center',
                            flexWrap: 'wrap',
                            margin: '0.4rem 0.7rem',
                            fontSize: '0.8rem',
                          }}
                        >
                          <span className="ams-pill ams-pill-preview">Rejected</span>
                          <span style={{ color: 'var(--ams-ink-soft)' }}>
                            {rejectedFiles[path]
                              ? rejectedFiles[path]
                              : 'No reason given. Excluded from Apply.'}
                          </span>
                          <button
                            className="ams-button-secondary"
                            onClick={() => handleClearRejection(path)}
                            disabled={rejectingFile === path}
                          >
                            {rejectingFile === path ? 'Undoing…' : 'Undo reject'}
                          </button>
                        </div>
                      )}
                      {!collapsed && (
                        <>
                          <div className="ams-diff-body">
                            {file ? (
                              file.lines.map((line, index) => (
                                <div
                                  key={index}
                                  className={`ams-diff-line${line.type !== 'context' ? ` ams-diff-line-${line.type}` : ''}`}
                                >
                                  {line.text}
                                </div>
                              ))
                            ) : (
                              <div
                                className="ams-diff-line"
                                style={{ color: 'var(--ams-ink-soft)', fontStyle: 'italic' }}
                              >
                                No pending changes to this file right now.
                              </div>
                            )}
                          </div>
                          {((perFileChat[path] || []).length > 0 || revisingFile === path) && (
                            <div
                              className="ams-chat-thread"
                              style={{ margin: '0.5rem 0.7rem 0.2rem' }}
                            >
                              {(perFileChat[path] || []).map((turn, index) => (
                                <div
                                  key={index}
                                  className="ams-chat-bubble"
                                  data-role={turn.role}
                                  style={{
                                    fontSize: '0.85rem',
                                    margin: '0.3rem 0',
                                    padding: '0.5rem 0.75rem',
                                    borderRadius: 6,
                                    maxWidth: '80%',
                                    // Replies carry deliberate line breaks (e.g. the
                                    // "no code was changed" note) — don't collapse them.
                                    whiteSpace: 'pre-wrap',
                                    marginLeft: turn.role === 'user' ? 'auto' : 0,
                                    background:
                                      turn.role === 'user' ? 'var(--ams-accent)' : 'var(--ams-surface)',
                                    color: turn.role === 'user' ? '#fff' : 'inherit',
                                    border:
                                      turn.role === 'assistant' ? '1px solid var(--ams-line)' : 'none',
                                  }}
                                >
                                  {turn.text}
                                </div>
                              ))}
                              {revisingFile === path && (
                                <div
                                  className="ams-chat-bubble"
                                  data-role="assistant"
                                  style={{
                                    fontSize: '0.85rem',
                                    margin: '0.3rem 0',
                                    padding: '0.5rem 0.75rem',
                                    borderRadius: 6,
                                    maxWidth: '80%',
                                    background: 'var(--ams-surface)',
                                    border: '1px solid var(--ams-line)',
                                    color: 'var(--ams-ink-soft)',
                                    fontStyle: 'italic',
                                  }}
                                >
                                  Thinking…
                                </div>
                              )}
                              <p
                                style={{
                                  fontSize: '0.7rem',
                                  color: 'var(--ams-ink-soft)',
                                  margin: '0.15rem 0 0',
                                }}
                              >
                                {AI_LABEL}
                              </p>
                            </div>
                          )}
                          <div className="ams-diff-ask">
                            <input
                              className="ams-input"
                              style={{ flex: 1 }}
                              placeholder={`Ask about ${path}…`}
                              value={perFileQuestion[path] || ''}
                              onChange={(event) =>
                                setPerFileQuestion((prev) => ({ ...prev, [path]: event.target.value }))
                              }
                              onKeyDown={(event) => {
                                if (event.key === 'Enter') handleAskAboutFile(path)
                              }}
                              disabled={revisingFile === path || applied}
                            />
                            <button
                              className="ams-button-secondary"
                              onClick={() => handleAskAboutFile(path)}
                              disabled={
                                revisingFile === path || applied || !(perFileQuestion[path] || '').trim()
                              }
                            >
                              {revisingFile === path ? 'Asking…' : 'Ask'}
                            </button>
                            {!(path in rejectedFiles) && (
                              <button
                                className="ams-button-secondary"
                                onClick={() => handleApplyFile(path)}
                                disabled={applied || appliedFiles[path] || applyingFile === path}
                              >
                                {appliedFiles[path]
                                  ? '✓ Applied'
                                  : applyingFile === path
                                    ? 'Applying…'
                                    : 'Apply this file'}
                              </button>
                            )}
                            {/* Revert is offered only for a file actually
                                written to the tree — there is nothing to put
                                back otherwise. */}
                            {appliedFiles[path] && (
                              <button
                                className="ams-button-secondary"
                                onClick={() => handleRevertFile(path)}
                                disabled={revertingFile === path}
                              >
                                {revertingFile === path ? 'Reverting…' : 'Revert this file'}
                              </button>
                            )}
                            {!appliedFiles[path] && !applied && !(path in rejectedFiles) && (
                              <button
                                className="ams-button-secondary"
                                onClick={() => {
                                  setRejectPromptFor(path)
                                  setRejectReason('')
                                }}
                                disabled={rejectingFile === path || rejectPromptFor === path}
                              >
                                Reject
                              </button>
                            )}
                          </div>
                          {rejectPromptFor === path && (
                            <div className="ams-diff-ask">
                              <input
                                className="ams-input"
                                style={{ flex: 1 }}
                                placeholder={`Why reject ${path}? (optional)`}
                                value={rejectReason}
                                onChange={(event) => setRejectReason(event.target.value)}
                                onKeyDown={(event) => {
                                  if (event.key === 'Enter') handleRejectFile(path)
                                }}
                                autoFocus
                              />
                              <button
                                className="ams-button-secondary"
                                onClick={() => handleRejectFile(path)}
                                disabled={rejectingFile === path}
                              >
                                {rejectingFile === path ? 'Rejecting…' : 'Confirm reject'}
                              </button>
                              <button
                                className="ams-button-secondary"
                                onClick={() => setRejectPromptFor(null)}
                                disabled={rejectingFile === path}
                              >
                                Cancel
                              </button>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )
                })}
                {reviseError && (
                  <p style={{ color: 'var(--ams-error)', marginTop: '0.5rem' }}>{reviseError}</p>
                )}

                <div className="ams-card" style={{ marginTop: '1rem' }}>
                  <p style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                    Realize another file needs a change too, outside the files listed above? Add it
                    here — it joins the same reviewed diff, nothing is written to the repo until you
                    apply.
                  </p>
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <input
                      className="ams-input"
                      style={{ flex: '1 1 240px' }}
                      placeholder="Repo-relative file path, e.g. apps/policycore/core/claims.py"
                      value={newFilePath}
                      onChange={(event) => setNewFilePath(event.target.value)}
                      disabled={addingFile || applied}
                    />
                    <input
                      className="ams-input"
                      style={{ flex: '2 1 320px' }}
                      placeholder="What change does this file need?"
                      value={newFileInstruction}
                      onChange={(event) => setNewFileInstruction(event.target.value)}
                      disabled={addingFile || applied}
                    />
                    <button
                      className="ams-button-secondary"
                      onClick={handleAddFile}
                      disabled={addingFile || applied || !newFilePath.trim() || !newFileInstruction.trim()}
                    >
                      {addingFile ? 'Adding…' : 'Add to proposal'}
                    </button>
                  </div>
                  {addFileError && (
                    <p style={{ color: 'var(--ams-error)', marginTop: '0.5rem' }}>{addFileError}</p>
                  )}
                </div>

                <div
                  style={{
                    marginTop: '1rem',
                    display: 'flex',
                    gap: '0.5rem',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                  }}
                >
                  <button className="ams-button" onClick={handleApply} disabled={applying || applied}>
                    {applied ? '✓ Applied to repo' : applying ? 'Applying…' : 'Apply to repo'}
                  </button>
                  {/* Undo for a change already written to the working tree.
                      Before this existed the only way back was a full demo
                      reset, which discards every other beat's state too. */}
                  {(applied || Object.keys(appliedFiles).length > 0) && (
                    <button
                      className="ams-button-secondary"
                      onClick={handleRevertAll}
                      disabled={reverting}
                    >
                      {reverting ? 'Reverting…' : 'Revert all'}
                    </button>
                  )}
                  {Object.keys(rejectedFiles).length > 0 && !applied && (
                    <span style={{ fontSize: '0.8rem', color: 'var(--ams-ink-soft)' }}>
                      {Object.keys(rejectedFiles).length} rejected file
                      {Object.keys(rejectedFiles).length === 1 ? '' : 's'} will be skipped.
                    </span>
                  )}
                </div>
                {applyError && <p style={{ color: 'var(--ams-error)' }}>{applyError}</p>}
                {applied && postApplyFailure && (
                  <div
                    className="ams-card"
                    style={{ marginTop: '0.75rem', border: '1px solid var(--ams-error)' }}
                  >
                    <p style={{ color: 'var(--ams-error)', fontWeight: 700, marginTop: 0 }}>
                      Applied, but the app crashed on migration
                    </p>
                    <p style={{ fontSize: '0.85rem' }}>
                      The change was written to the repo, but the post-apply step that rebuilds the
                      app against it failed — the portal is likely broken until this is fixed.
                    </p>
                    {postApplyFailure.steps
                      .filter((step) => step.returncode !== 0)
                      .map((step) => (
                        <div key={step.command} style={{ marginTop: '0.5rem' }}>
                          <p style={{ fontSize: '0.8rem', margin: 0 }}>
                            <code>{step.command}</code> exited with code {step.returncode}:
                          </p>
                          <pre style={{ fontSize: '0.78rem', overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
                            {step.output_tail}
                          </pre>
                        </div>
                      ))}
                    <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                      <button className="ams-button" onClick={handleFixCrash} disabled={fixingCrash}>
                        {fixingCrash ? 'Fixing…' : 'Fix with AI'}
                      </button>
                      <span style={{ fontSize: '0.8rem', color: 'var(--ams-ink-soft)' }}>
                        Sends the crash back to the model for a revised proposal — or run
                        demo/reset_s3.sh to roll back.
                      </span>
                    </div>
                    {fixCrashError && (
                      <p style={{ color: 'var(--ams-error)', marginBottom: 0 }}>{fixCrashError}</p>
                    )}
                  </div>
                )}
                {applied && !postApplyFailure && (
                  <p style={{ color: 'var(--ams-success)', fontSize: '0.85rem' }}>
                    Applied. The app now has this capability —{' '}
                    <a href={targetApp.url} target="_blank" rel="noopener noreferrer">
                      {targetApp.label}
                    </a>{' '}
                    to try it.
                  </p>
                )}
                {applied &&
                  designSync?.findings
                    .filter((finding) => !finding.still_accurate)
                    .map((finding) => (
                      <div
                        key={finding.design_doc}
                        className="ams-card"
                        style={{ marginTop: '0.75rem' }}
                      >
                        <p style={{ fontSize: '0.8rem', margin: 0, opacity: 0.7 }}>
                          {designSync.label}
                        </p>
                        <p style={{ fontSize: '0.85rem', marginTop: '0.4rem' }}>
                          This change touched <code>{finding.subsystem}</code>, and its design
                          document no longer describes it accurately: {finding.reason} That
                          document&rsquo;s scope keywords decide whether this subsystem is
                          considered relevant to future change requests, so leaving it stale
                          causes retrieval mistakes later.
                        </p>
                        {finding.proposal_id ? (
                          designDocApplied[finding.proposal_id] ? (
                            <p
                              style={{ color: 'var(--ams-success)', fontSize: '0.85rem' }}
                            >
                              Applied — <code>{finding.design_doc}</code> now matches the code.
                            </p>
                          ) : (
                            <>
                              {parseDiff(finding.diff_text).map((file) => (
                                <div key={file.path} className="ams-diff-file">
                                  <div className="ams-diff-file-header">
                                    <span>{file.path}</span>
                                  </div>
                                  <div className="ams-diff-body">
                                    {file.lines.map((line, index) => (
                                      <div
                                        key={index}
                                        className={`ams-diff-line${line.type !== 'context' ? ` ams-diff-line-${line.type}` : ''}`}
                                      >
                                        {line.text}
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              ))}
                              <button
                                type="button"
                                className="ams-button"
                                disabled={designDocApplying === finding.proposal_id}
                                onClick={() => void handleApplyDesignDoc(finding)}
                              >
                                {designDocApplying === finding.proposal_id
                                  ? 'Applying…'
                                  : `Apply ${finding.design_doc}`}
                              </button>
                            </>
                          )
                        ) : (
                          <p style={{ fontSize: '0.85rem', opacity: 0.8 }}>
                            No replacement text was produced — update{' '}
                            <code>{finding.design_doc}</code> by hand.
                          </p>
                        )}
                      </div>
                    ))}
              </>
            ) : (
              <div className="ams-card" style={{ marginTop: '0.75rem' }}>
                <p style={{ fontSize: '0.85rem' }}>
                  No changes to propose — the app already has this feature from an earlier run. Run
                  demo/reset_s3.sh to regenerate from a clean baseline.
                </p>
              </div>
            )}
            <FileSelectionPanel selection={generated.file_selection} />
            <TokenPanel panel={generated.token_panel} />
          </>
        )}
      </StageCard>

      <StageCard
        index={2}
        title="Draft design doc (for QA)"
        locked={!canDesignDoc}
        lockedHint={designDocLockedReason}
        statusLabel={designDoc ? '✓ Drafted' : null}
        open={openStage === 'design'}
        onToggle={() => toggleStage('design')}
      >
        <div>
          <button className="ams-button" onClick={handleDraftDesignDoc} disabled={draftingDesignDoc}>
            Draft design doc
          </button>
        </div>
        {designDocError && <p style={{ color: 'var(--ams-error)' }}>{designDocError}</p>}
        {designDoc && activeTicketKey && (() => {
          const crLabel = activeLinked?.crLabel ?? activeTicketKey
          const docDate = new Date().toLocaleDateString('en-CA', {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
          })
          const blocks = parseDocBlocks(designDoc)
          const rendered: ReactNode[] = []
          let bullets: DocBlock[] = []
          const flushBullets = (key: number) => {
            if (!bullets.length) return
            rendered.push(
              <ul key={`ul-${key}`} style={{ margin: '0.3rem 0 0.7rem 1.2rem', padding: 0 }}>
                {bullets.map((bullet, index) => (
                  <li key={index} style={{ margin: '0.25rem 0' }}>
                    {renderInlineBold(bullet.text)}
                  </li>
                ))}
              </ul>
            )
            bullets = []
          }
          blocks.forEach((block, index) => {
            if (block.type === 'bullet') {
              bullets.push(block)
              return
            }
            flushBullets(index)
            if (block.type === 'heading') {
              rendered.push(
                <h4
                  key={index}
                  style={{
                    fontSize: '0.95rem',
                    margin: '1.1rem 0 0.3rem',
                    borderBottom: '1px solid var(--ams-line)',
                    paddingBottom: '0.2rem',
                  }}
                >
                  {renderInlineBold(block.text)}
                </h4>
              )
            } else {
              rendered.push(
                <p key={index} style={{ margin: '0.4rem 0' }}>
                  {renderInlineBold(block.text)}
                </p>
              )
            }
          })
          flushBullets(blocks.length)
          return (
            <>
              <div className="ams-doc">
                <div className="ams-doc-letterhead">
                  <span className="ams-doc-org">MapleSure Insurance</span>
                  <span className="ams-doc-kind">Internal Design Document</span>
                </div>
                <div className="ams-doc-meta">
                  {crLabel} · Ticket {activeTicketKey} · {docDate} · Engineering → QA hand-off
                </div>
                <div style={{ fontSize: '0.9rem' }}>{rendered}</div>
                <div className="ams-doc-label">{AI_LABEL}</div>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.6rem', flexWrap: 'wrap' }}>
                <button
                  className="ams-button-secondary"
                  onClick={() =>
                    downloadFile(
                      `${crLabel}-design-doc.html`,
                      'text/html',
                      buildDesignDocHtml(designDoc, crLabel, activeTicketKey)
                    )
                  }
                >
                  ⬇ Download document (.html)
                </button>
                <button
                  className="ams-button-secondary"
                  onClick={() =>
                    downloadFile(`${crLabel}-design-doc.md`, 'text/markdown', designDoc)
                  }
                >
                  ⬇ Download markdown (.md)
                </button>
              </div>
              {!inQa ? (
                <div
                  className="ams-card"
                  style={{
                    marginTop: '0.75rem',
                    display: 'flex',
                    gap: '0.5rem',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                  }}
                >
                  <strong style={{ fontSize: '0.9rem' }}>Hand off to QA:</strong>
                  <select
                    className="ams-input"
                    style={{ width: 'auto' }}
                    value={qaTester}
                    onChange={(event) => setQaTester(event.target.value)}
                    disabled={handingOff}
                  >
                    {TESTER_ROSTER.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                  <button className="ams-button" onClick={handleHandoffToQa} disabled={handingOff}>
                    {handingOff ? 'Handing off…' : 'Assign tester & move to QA'}
                  </button>
                  <span style={{ fontSize: '0.8rem', color: 'var(--ams-ink-soft)' }}>
                    The ticket moves to the QA column — only the tester can run the next steps.
                  </span>
                </div>
              ) : (
                <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)', marginTop: '0.6rem' }}>
                  ✓ With QA — assigned to {activeIssue?.assignee || 'the tester'}.
                </p>
              )}
              {handoffError && <p style={{ color: 'var(--ams-error)' }}>{handoffError}</p>}
            </>
          )
        })()}
      </StageCard>

      <StageCard
        index={3}
        title="Generate tests + run"
        locked={!canTest}
        lockedHint={testLockedReason}
        statusLabel={
          mutationCheck
            ? mutationCheck.tests_caught_bug
              ? '✓ Proven'
              : '⚠ Bug missed'
            : testsRun
              ? testsRun.passed
                ? '✓ Passed'
                : '✗ Failed'
              : testsGenerated
                ? 'Generated'
                : null
        }
        statusVariant={
          (mutationCheck && !mutationCheck.tests_caught_bug) || (testsRun && !testsRun.passed)
            ? 'error'
            : 'ok'
        }
        open={openStage === 'tests'}
        onToggle={() => toggleStage('tests')}
      >
        {/* Beat 1 — generate the test file and review it before anything runs. */}
        <div>
          <button className="ams-button" onClick={handleGenerateTests} disabled={generatingTests}>
            {generatingTests ? 'Generating…' : testsGenerated ? 'Regenerate tests' : 'Generate tests'}
          </button>
        </div>
        {testError && <p style={{ color: 'var(--ams-error)' }}>{testError}</p>}
        {testsGenerated && (
          <>
            <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)', marginTop: '0.75rem' }}>
              {AI_LABEL} Review the generated tests below — nothing has run yet.
            </p>
            {parseDiff(testsGenerated.diff_text).map((file) => (
              <div key={file.path} className="ams-diff-file">
                <div className="ams-diff-file-header">
                  <span>{file.path}</span>
                </div>
                <div className="ams-diff-body">
                  {file.lines.map((line, index) => (
                    <div
                      key={index}
                      className={`ams-diff-line${line.type !== 'context' ? ` ams-diff-line-${line.type}` : ''}`}
                    >
                      {line.text}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <TokenPanel panel={testsGenerated.token_panel} />

            {/* Beat 2 — run the reviewed suite; results render as a per-test
                checklist parsed from JUnit XML, raw output behind a disclosure. */}
            <div style={{ marginTop: '0.75rem' }}>
              <button className="ams-button" onClick={handleRunTests} disabled={runningTests}>
                {runningTests ? 'Running…' : testsRun ? 'Re-run tests' : 'Run tests'}
              </button>
            </div>
            {testsRun && (
              <div
                className="ams-card"
                style={{
                  marginTop: '0.75rem',
                  ...(testsRun.passed ? {} : { border: '1px solid var(--ams-error)' }),
                }}
              >
                {!testsRun.passed && (
                  <p style={{ color: 'var(--ams-error)', fontWeight: 700, marginTop: 0 }}>
                    Test run exited with code {testsRun.returncode}
                  </p>
                )}
                <RunSummaryLine run={testsRun} />
                <TestCaseTable cases={testsRun.cases} />
                <RunnerOutput output={testsRun.output} />
              </div>
            )}

            {/* Beat 3 — prove the suite bites: inject the seeded bug, watch the
                right test go red, working tree reverted server-side. */}
            {testsRun?.passed && (
              <div className="ams-card" style={{ marginTop: '0.75rem' }}>
                <strong style={{ fontSize: '0.9rem' }}>Prove the tests catch bugs</strong>
                <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)', margin: '0.4rem 0 0.6rem' }}>
                  A passing suite only counts if it fails when the code is wrong. This injects a
                  seeded bug into the generated code, re-runs the suite, and reverts the bug —
                  the repo is untouched afterwards.
                </p>
                <button className="ams-button" onClick={handleMutationCheck} disabled={mutating}>
                  {mutating ? 'Injecting bug & re-running…' : 'Inject a seeded bug & re-run'}
                </button>
                {mutationCheck && (
                  <div style={{ marginTop: '0.75rem' }}>
                    <p style={{ fontSize: '0.85rem', margin: '0 0 0.4rem' }}>
                      <strong>Injected bug:</strong> {mutationCheck.description}
                    </p>
                    {parseDiff(mutationCheck.mutation_diff).map((file) => (
                      <div key={file.path} className="ams-diff-file">
                        <div className="ams-diff-file-header">
                          <span>{file.path}</span>
                        </div>
                        <div className="ams-diff-body">
                          {file.lines.map((line, index) => (
                            <div
                              key={index}
                              className={`ams-diff-line${line.type !== 'context' ? ` ams-diff-line-${line.type}` : ''}`}
                            >
                              {line.text}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                    <p
                      style={{
                        fontWeight: 700,
                        fontSize: '0.9rem',
                        color: mutationCheck.tests_caught_bug
                          ? 'var(--ams-success)'
                          : 'var(--ams-error)',
                        margin: '0.6rem 0 0',
                      }}
                    >
                      {mutationCheck.tests_caught_bug
                        ? `✓ The suite caught the injected bug — ${
                            mutationCheck.summary.failed + mutationCheck.summary.errors
                          } test${
                            mutationCheck.summary.failed + mutationCheck.summary.errors === 1
                              ? ''
                              : 's'
                          } went red.`
                        : '⚠ The suite did NOT catch the injected bug — these tests need strengthening.'}
                    </p>
                    <TestCaseTable cases={mutationCheck.cases} />
                    <RunnerOutput output={mutationCheck.output} />
                    <p style={{ fontSize: '0.78rem', color: 'var(--ams-ink-soft)', margin: '0.6rem 0 0' }}>
                      The injected bug was reverted automatically — the working tree is back to the
                      applied change.
                    </p>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </StageCard>

      <StageCard
        index={4}
        title="Draft release notes"
        locked={!canDraftNotes}
        lockedHint={notesLockedReason}
        statusLabel={releaseNotes ? '✓ Drafted' : null}
        open={openStage === 'notes'}
        onToggle={() => toggleStage('notes')}
      >
        <div>
          <button className="ams-button" onClick={handleDraftReleaseNotes} disabled={draftingNotes}>
            Draft release notes
          </button>
        </div>
        {releaseNotes && (
          <div className="ams-card" style={{ marginTop: '0.75rem' }}>
            <strong>{AI_LABEL}</strong>
            <div style={{ whiteSpace: 'pre-wrap', fontSize: '0.9rem', marginTop: '0.5rem' }}>
              {releaseNotes}
            </div>
          </div>
        )}
        {releaseNotes && inQa && isActiveAssignee && activeIssue?.status !== 'Done' && (
          <button
            className="ams-button"
            style={{ marginTop: '0.75rem' }}
            onClick={handleMarkTicketDone}
            disabled={closingTicket}
          >
            {closingTicket ? 'Closing…' : 'QA passed — mark ticket Done'}
          </button>
        )}
      </StageCard>
      </div>
      </>
      )}

      {expandedTicket && boardIssues && (() => {
        const issue = boardIssues.find((candidate) => candidate.key === expandedTicket)
        if (!issue) return null
        const linked = TICKET_TARGETS[expandedTicket]
        return (
          <TicketModal
            issue={issue}
            crText={ticketCrText[expandedTicket] || ''}
            crLabel={linked?.crLabel ?? null}
            onClose={() => setExpandedTicket(null)}
            analysisResult={ticketAnalysis[expandedTicket]}
            analysisLoading={!!ticketAnalysisLoading[expandedTicket]}
            analysisError={ticketAnalysisError[expandedTicket]}
            onRunAnalysis={() => handleRunAnalysisForTicket(expandedTicket)}
            clarificationQuestion={ticketClarificationQuestion[expandedTicket]}
            onSubmitClarification={(answer) => handleRunAnalysisForTicket(expandedTicket, answer)}
            crossTeamImpacts={ticketCrossTeam[expandedTicket]}
            crossTeamTokenPanel={ticketCrossTeamTokens[expandedTicket]}
            crossTeamLoading={!!ticketCrossTeamLoading[expandedTicket]}
            onCheckCrossTeam={() => handleCheckCrossTeamForTicket(expandedTicket)}
            createdTickets={createdTickets}
            assigneeByApp={assigneeByApp}
            onAssigneeChange={(appName, value) =>
              setAssigneeByApp((prev) => ({ ...prev, [appName]: value }))
            }
            creatingTicketFor={creatingTicketFor}
            onCreateTicket={(impact) => handleCreateCrossTeamTicket(impact, expandedTicket)}
            assigningTicketFor={assigningTicketFor}
            onAssignTicket={handleAssignCrossTeamTicket}
            events={ticketEvents[expandedTicket] || []}
            eventsLoading={!!ticketEventsLoading[expandedTicket]}
          />
        )
      })()}
    </div>
  )
}

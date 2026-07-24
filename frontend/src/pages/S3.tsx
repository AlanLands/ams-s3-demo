import { useEffect, useState, type ReactNode } from 'react'
import { ApiError } from '../api'
import { useAuth } from '../AuthContext'
import FileSelectionPanel from '../FileSelectionPanel'
import TicketModal from '../TicketModal'
import {
  s3Api,
  type AnalyzeResponse,
  type CrossTeamImpact,
  type GenerateResponse,
  type JiraIssue,
  type QuickChatResponse,
  type TestsResponse,
  type TicketEvent,
} from '../api_s3'

const AI_LABEL = 'AI suggestion — verify with your specialist before applying.'

// The MapleSure mockapp's own Streamlit UI (mockapp/app.py) — launched
// separately from the AMS console (see demo/run_s4_endorsement.sh), same
// port .env.example documents as MOCKAPP_URL.
const MOCKAPP_URL = 'http://localhost:8501'

// Demo-only roster for assigning a ticket — mirrors the S1 engineer roster's
// first few names (s1_triage/roster_auth.py); this page doesn't fetch the
// live roster since a ticket assignee is illustrative here, not a real Jira
// user lookup (Jira Cloud needs an accountId, which this fictional roster
// doesn't have — see common/jira_client.py's assignee note).
const ASSIGNEE_ROSTER = ['Ravi Kumar', 'Elena Cruz', 'Priya Nair']

// Which CR/target a given Jira board ticket links to, so clicking it can run
// impact analysis against the right target — the AMS-098 cleanup ticket has
// no linked CR (it's a seeded example of unrelated work also on the board).
const TICKET_TARGETS: Record<string, { targetId: string | null; tierName: string; crLabel: string }> = {
  'AMS-101': { targetId: null, tierName: 'Elite', crLabel: 'CR-2026-041' },
  'AMS-102': { targetId: 'mockapp-endorsement-field-add', tierName: 'Elite', crLabel: 'CR-2026-042' },
  // The Spring Boot ClaimsPortal target (sandbox/spring-demo) — S3's proof
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

interface PersistedTicketState {
  analysis?: AnalyzeResponse
  generated?: GenerateResponse
  filePaths?: string[]
  fileReasons?: Record<string, string>
  collapsedFiles?: Record<string, boolean>
  applied?: boolean
  appliedFiles?: Record<string, boolean>
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

function TokenPanel({
  panel,
}: {
  panel: { scoped_input_tokens: number | null; naive_input_tokens_estimate?: number }
}) {
  if (panel.scoped_input_tokens == null) {
    return <p style={{ color: 'var(--ams-ink-soft)', fontSize: '0.85rem' }}>Token count unavailable for this run.</p>
  }
  const naive = panel.naive_input_tokens_estimate
  if (!naive) {
    return (
      <p style={{ color: 'var(--ams-ink-soft)', fontSize: '0.85rem' }}>
        Scoped context used {panel.scoped_input_tokens.toLocaleString()} input tokens.
      </p>
    )
  }
  const multiplier = Math.max(1, Math.round(naive / Math.max(panel.scoped_input_tokens, 1)))
  return (
    <p style={{ color: 'var(--ams-ink-soft)', fontSize: '0.85rem' }}>
      Scoped context used {panel.scoped_input_tokens.toLocaleString()} input tokens; a
      whole-app-context approach would have used ~{naive.toLocaleString()} tokens — {multiplier}x
      fewer.
    </p>
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
  open,
  onToggle,
  children,
}: {
  index: number
  title: string
  locked: boolean
  lockedHint?: string | null
  statusLabel?: string | null
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
        {statusLabel && <span className="ams-pill ams-pill-general">{statusLabel}</span>}
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
  const [perFileReply, setPerFileReply] = useState<Record<string, string>>({})
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

  const [newFilePath, setNewFilePath] = useState('')
  const [newFileInstruction, setNewFileInstruction] = useState('')
  const [addingFile, setAddingFile] = useState(false)
  const [addFileError, setAddFileError] = useState<string | null>(null)

  const [designDoc, setDesignDoc] = useState<string | null>(null)
  const [draftingDesignDoc, setDraftingDesignDoc] = useState(false)
  const [designDocError, setDesignDocError] = useState<string | null>(null)

  const [tested, setTested] = useState<TestsResponse | null>(null)
  const [testing, setTesting] = useState(false)
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
  const [ticketCrossTeam, setTicketCrossTeam] = useState<Record<string, CrossTeamImpact[]>>({})
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
    setDesignDoc(null)
    setDesignDocError(null)
    try {
      const result = await s3Api.generate(active?.tierName ?? 'Elite', active?.targetId, activeTicketKey)
      const collapsed = Object.fromEntries(result.files_changed.map((path) => [path, true]))
      setGenerated(result)
      setFilePaths(result.files_changed)
      setFileReasons(result.file_reasons || {})
      setCollapsedFiles(collapsed)
      setPerFileReply({})
      saveTicketState(activeTicketKey, {
        generated: result,
        filePaths: result.files_changed,
        fileReasons: result.file_reasons || {},
        collapsedFiles: collapsed,
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
    setPerFileReply((prev) => ({ ...prev, [path]: '' }))
    try {
      const result = await s3Api.revise(generated.proposal_id, `For ${path}: ${question}`)
      const nextGenerated = { ...generated, diff_text: result.diff_text, files_changed: result.files_changed }
      const nextFilePaths = Array.from(new Set([...filePaths, ...result.files_changed]))
      const nextFileReasons =
        result.message && result.files_changed.includes(path)
          ? { ...fileReasons, [path]: result.message }
          : fileReasons
      setGenerated(nextGenerated)
      setFilePaths(nextFilePaths)
      setFileReasons(nextFileReasons)
      setPerFileReply((prev) => ({
        ...prev,
        [path]: result.message || 'Done — see the updated diff above.',
      }))
      setPerFileQuestion((prev) => ({ ...prev, [path]: '' }))
      if (activeTicketKey) {
        saveTicketState(activeTicketKey, {
          generated: nextGenerated,
          filePaths: nextFilePaths,
          fileReasons: nextFileReasons,
        })
      }
    } catch (err) {
      setReviseError(err instanceof ApiError ? err.message : 'Revision failed.')
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
      setApplied(true)
      setAppliedFiles(nextAppliedFiles)
      saveTicketState(activeTicketKey, { applied: true, appliedFiles: nextAppliedFiles })
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.message : 'Apply failed.')
    } finally {
      setApplying(false)
    }
  }

  async function handleApplyFile(path: string) {
    if (!generated || !activeTicketKey) return
    setApplyingFile(path)
    setApplyError(null)
    try {
      await s3Api.apply(generated.proposal_id, activeTicketKey, path)
      const nextAppliedFiles = { ...appliedFiles, [path]: true }
      setAppliedFiles(nextAppliedFiles)
      saveTicketState(activeTicketKey, { appliedFiles: nextAppliedFiles })
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.message : 'Apply failed.')
    } finally {
      setApplyingFile(null)
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

  async function handleTests() {
    if (!activeTicketKey) return
    const active = TICKET_TARGETS[activeTicketKey]
    setTesting(true)
    setTestError(null)
    try {
      setTested(await s3Api.tests(active?.tierName ?? 'Elite', active?.targetId))
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : 'Test generation failed.')
    } finally {
      setTesting(false)
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
    } finally {
      setDraftingNotes(false)
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

  async function handleRunAnalysisForTicket(ticketKey: string) {
    const linked = TICKET_TARGETS[ticketKey]
    setTicketAnalysisLoading((prev) => ({ ...prev, [ticketKey]: true }))
    setTicketAnalysisError((prev) => ({ ...prev, [ticketKey]: '' }))
    try {
      let result: AnalyzeResponse
      if (linked) {
        result = await s3Api.analyze(linked.tierName, linked.targetId, ticketKey)
      } else {
        // No CR/target registered for this ticket (e.g. a cross-team ticket
        // for another application) — analyze its own text directly instead.
        const issue = (boardIssues || []).find((candidate) => candidate.key === ticketKey)
        const crText = [issue?.summary, issue?.description].filter(Boolean).join('\n\n').trim()
        if (!crText) return
        result = await s3Api.analyzeAdhoc(crText, ticketKey)
      }
      setTicketAnalysis((prev) => ({ ...prev, [ticketKey]: result }))
      saveTicketState(ticketKey, { analysis: result })
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
    setPerFileReply({})
    setPerFileQuestion({})
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
  // Union, not just diffFiles: a file can be part of the proposal (and stay
  // there for the reviewer to see) even in a run where its current diff
  // against the repo is empty.
  const orderedFilePaths = Array.from(new Set([...filePaths, ...diffFiles.map((file) => file.path)]))
  const activeLinked = activeTicketKey ? TICKET_TARGETS[activeTicketKey] : undefined
  const analysisDoneForActive = activeTicketKey ? !!ticketAnalysis[activeTicketKey] : false

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

  const canTest = canDesignDoc && !!designDoc
  const testLockedReason = canTest
    ? null
    : canDesignDoc
      ? 'Draft the design doc above before generating tests.'
      : designDocLockedReason

  const canDraftNotes = !!tested
  const notesLockedReason = canDraftNotes ? null : 'Generate and run tests first.'

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
            {['To Do', 'In Progress', 'Done'].map((status) => (
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
        statusLabel={applied ? '✓ Applied' : generated ? 'Proposed' : null}
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
                          <div className="ams-diff-ask">
                            <input
                              className="ams-input"
                              style={{ flex: 1 }}
                              placeholder={`Ask about ${path}…`}
                              value={perFileQuestion[path] || ''}
                              onChange={(event) =>
                                setPerFileQuestion((prev) => ({ ...prev, [path]: event.target.value }))
                              }
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
                          </div>
                          {perFileReply[path] && (
                            <p
                              style={{
                                fontSize: '0.85rem',
                                color: 'var(--ams-ink-soft)',
                                margin: '0.4rem 0.2rem 0',
                              }}
                            >
                              {AI_LABEL} {perFileReply[path]}
                            </p>
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
                      placeholder="Repo-relative file path, e.g. mockapp/core/claims.py"
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

                <div style={{ marginTop: '1rem' }}>
                  <button className="ams-button" onClick={handleApply} disabled={applying || applied}>
                    {applied ? '✓ Applied to repo' : applying ? 'Applying…' : 'Apply to repo'}
                  </button>
                </div>
                {applyError && <p style={{ color: 'var(--ams-error)' }}>{applyError}</p>}
                {applied && (
                  <p style={{ color: 'var(--ams-success)', fontSize: '0.85rem' }}>
                    Applied. The app now has this capability —{' '}
                    <a href={MOCKAPP_URL} target="_blank" rel="noopener noreferrer">
                      open the policy portal
                    </a>{' '}
                    to try it.
                  </p>
                )}
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
        {designDoc && (
          <div className="ams-card" style={{ marginTop: '0.75rem' }}>
            <strong>{AI_LABEL}</strong>
            <div style={{ whiteSpace: 'pre-wrap', fontSize: '0.9rem', marginTop: '0.5rem' }}>
              {designDoc}
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--ams-ink-soft)', marginTop: '0.5rem' }}>
              Hand this to QA before generating tests — the test suite below is written against it.
            </p>
          </div>
        )}
      </StageCard>

      <StageCard
        index={3}
        title="Generate tests + run"
        locked={!canTest}
        lockedHint={testLockedReason}
        statusLabel={tested ? '✓ Ran' : null}
        open={openStage === 'tests'}
        onToggle={() => toggleStage('tests')}
      >
        <div>
          <button className="ams-button" onClick={handleTests} disabled={testing}>
            Generate tests + run
          </button>
        </div>
        {testError && <p style={{ color: 'var(--ams-error)' }}>{testError}</p>}
        {tested && (
          <div className="ams-card" style={{ marginTop: '0.75rem' }}>
            <pre style={{ fontSize: '0.78rem', overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
              {tested.pytest_output}
            </pre>
          </div>
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
            crossTeamImpacts={ticketCrossTeam[expandedTicket]}
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

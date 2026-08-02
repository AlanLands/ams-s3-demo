import { useEffect, useState } from 'react'
import { ApiError } from '../../api'
import { useAuth } from '../../AuthContext'
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
  type DeploymentPlan,
  type RegressionRunResponse,
  type ReleaseAttachResponse,
  type ReleaseNoteSet,
  type ScenariosResponse,
  type ScmCheckoutResponse,
  type ScmResponse,
  type ScmState,
  type TestScenario,
  type TraceabilityResponse,
  type PostApplyResult,
  type QuickChatResponse,
  type TargetResolveResponse,
  type TestsGenerateResponse,
  type TestsRunResponse,
  type TicketEvent,
  type TokenPanel as TokenPanelData,
} from '../../api_s3'
import type { S3Stage } from './context'
import { downloadBlob, parseDiff } from './utils'

const AI_LABEL = 'AI suggestion — verify with your specialist before applying.'

// The MapleSure mockapp's own Streamlit UI (apps/policycore/app.py) — launched
// separately from the AMS console (see demo/run_mockapp.sh), same
// port/path .env.example documents as MOCKAPP_URL. Overridable at build time
// via VITE_MOCKAPP_URL (see web/.env.example) so the link still resolves when
// the portal is served from another host or behind a reverse proxy.
const MOCKAPP_URL =
  import.meta.env.VITE_MOCKAPP_URL || 'http://localhost:8501/sl_policycore'

// Where an applied change can actually be seen running, per target. Keyed by
// target id so the post-apply "go look at it" link names the app the change
// landed in — not always the mockapp portal. The ClaimsPortal target serves
// its own consoles from two Python/FastAPI services (apps/run-policy-service.sh
// :8081, apps/run-claims-service.sh :8082); CR-2026-043 changes claim intake,
// so the claims console is the one worth opening.
const TARGET_APPS: Record<string, { url: string; label: string }> = {
  'claimsportal-claims-deductible': {
    url: import.meta.env.VITE_CLAIMS_SERVICE_URL || 'http://localhost:8082/',
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

// Which CR a given Jira board ticket links to, so clicking it can run impact
// analysis against the right target — the AMS-098 cleanup ticket has no
// linked CR (it's a seeded example of unrelated work also on the board).
// Deliberately NOT a ticket -> target_id table: crFile names a bare filename
// under the repo's top-level crs/, and the console resolves it to a
// target_id server-side (POST /api/s3/target/resolve, see useEffect below
// and s3_enhancement/target_match.py) from the CR's own text — its
// `CR-YYYY-NNN:` identifier, or failing that its `Application:` header.
// Onboarding a new repo/target is then: register the Target in targets.py,
// drop its CR under crs/, and add its ticket key here with just a filename
// — no target_id to look up or keep in sync by hand.
const TICKET_CRS: Record<string, { crFile: string | null; tierName: string }> = {
  'AMS-101': { crFile: 'CR-2026-041.md', tierName: 'Elite' },
  'AMS-102': { crFile: 'CR-2026-042.md', tierName: 'Elite' },
  // The ClaimsPortal target (apps/claimsportal) — S3's proof that the
  // pipeline handles a second repo. tierName is a required placeholder like
  // AMS-102's; CR-2026-043 has no {{TIER_NAME}}.
  'AMS-103': { crFile: 'CR-2026-043.md', tierName: 'Elite' },
  // Raised on the support floor, so its CR names the application but no
  // target system: CR-2026-044's title is no registered target's
  // cr_template_path.stem, and its "Application: PolicyCore" header narrows
  // to two targets rather than one. Both deterministic tiers therefore miss
  // and target_match falls through to the AI tier -- this is the ticket that
  // exercises repo selection on stage (see the Repo selection card below).
  'AMS-104': { crFile: 'CR-2026-044.md', tierName: 'Elite' },
}

function crLabelFromFile(crFile: string | null): string {
  return crFile ? crFile.replace(/\.md$/, '') : ''
}

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
  rejectedFiles?: Record<string, string>
  postApplyFailure?: PostApplyResult | null
  scm?: ScmState | null
  fileChats?: Record<string, FileChatTurn[]>
  designDoc?: string
  designDiagram?: string
  designDiagramCaption?: string
  scenarioDraft?: ScenariosResponse
  scenarios?: TestScenario[]
  scenariosApprovedBy?: string
  traceability?: TraceabilityResponse
  testsGenerated?: TestsGenerateResponse
  testsRun?: TestsRunResponse
  regressionRun?: RegressionRunResponse
  mutationCheck?: MutationCheckResponse
  releaseNoteSet?: ReleaseNoteSet
  deploymentPlan?: DeploymentPlan
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
  }
}

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
  }
}

type S3OpenStage = 'generate' | 'design' | 'tests' | 'notes'

export function useS3Controller() {
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

  // The change's branch → commit → push state. Server-owned like rejectedFiles:
  // apply/revert/commit/push all return it, and the commit gate is computed
  // server-side from the ticket's test results, so there is no client-side
  // "tests passed" to keep in sync (or to get wrong). See s3_enhancement/scm.py.
  const [scmState, setScmState] = useState<ScmState | null>(null)
  const [scmBlockers, setScmBlockers] = useState<string[]>([])
  const [scmEvidence, setScmEvidence] = useState<ScmResponse['test_evidence']>({
    generated_suite: null,
    regression_suite: null,
  })
  const [committing, setCommitting] = useState(false)
  const [pushing, setPushing] = useState(false)
  const [scmError, setScmError] = useState<string | null>(null)
  const [scmDetail, setScmDetail] = useState<string | null>(null)

  const [newFilePath, setNewFilePath] = useState('')
  const [newFileInstruction, setNewFileInstruction] = useState('')
  const [addingFile, setAddingFile] = useState(false)
  const [addFileError, setAddFileError] = useState<string | null>(null)

  const [designDoc, setDesignDoc] = useState<string | null>(null)
  const [designDiagram, setDesignDiagram] = useState<string | null>(null)
  const [designDiagramCaption, setDesignDiagramCaption] = useState<string | null>(null)
  const [exportingDoc, setExportingDoc] = useState<string | null>(null)
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
  const [scenarioDraft, setScenarioDraft] = useState<ScenariosResponse | null>(null)
  const [scenarios, setScenarios] = useState<TestScenario[]>([])
  const [scenariosApprovedBy, setScenariosApprovedBy] = useState<string | null>(null)
  const [draftingScenarios, setDraftingScenarios] = useState(false)
  const [approvingScenarios, setApprovingScenarios] = useState(false)
  const [traceability, setTraceability] = useState<TraceabilityResponse | null>(null)
  const [buildingMatrix, setBuildingMatrix] = useState(false)
  const [regressionRun, setRegressionRun] = useState<RegressionRunResponse | null>(null)
  const [runningRegression, setRunningRegression] = useState(false)
  const [mutationCheck, setMutationCheck] = useState<MutationCheckResponse | null>(null)
  const [mutating, setMutating] = useState(false)
  const [testError, setTestError] = useState<string | null>(null)

  const [draftingNotes, setDraftingNotes] = useState(false)
  const [releaseNoteSet, setReleaseNoteSet] = useState<ReleaseNoteSet | null>(null)
  const [deploymentPlan, setDeploymentPlan] = useState<DeploymentPlan | null>(null)
  const [exportingRecord, setExportingRecord] = useState(false)
  const [attachingRecord, setAttachingRecord] = useState(false)
  const [attachResult, setAttachResult] = useState<ReleaseAttachResponse | null>(null)
  const [releaseError, setReleaseError] = useState<string | null>(null)

  const [openStage, setOpenStage] = useState<S3OpenStage | null>(null)
  void openStage

  const [checkingOut, setCheckingOut] = useState(false)
  const [checkedOut, setCheckedOut] = useState(false)
  const [checkOutResult, setCheckOutResult] = useState<ScmCheckoutResponse | null>(null)
  const [checkOutError, setCheckOutError] = useState<string | null>(null)

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
    for (const ticketKey of Object.keys(TICKET_CRS)) {
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

  // Which target each ticket's CR resolved to, server-side, and how it got
  // there — undefined means "not resolved yet" (see the effect below), null
  // means the resolve call itself failed. Everything else about a ticket's
  // linked CR (tierName, crLabel) is static and needs no round trip; only
  // the target has to come from the server, since that's the one thing this
  // console must not hardcode per ticket (see TICKET_CRS).
  //
  // The whole match is kept, not just target_id: `method`, `reasoning` and
  // `confidence` are what the Repo selection card shows, and
  // `needs_confirmation` is what gates checkout. A console that silently
  // used an AI guess would be claiming a repo nobody picked.
  const [resolvedTarget, setResolvedTarget] = useState<
    Record<string, TargetResolveResponse | null>
  >({})
  // Tickets whose AI-picked target the engineer has explicitly accepted.
  // Deterministic matches never enter this map — they have nothing to
  // confirm (see targetConfirmed below).
  const [targetConfirmed, setTargetConfirmed] = useState<Record<string, boolean>>({})

  useEffect(() => {
    let cancelled = false
    for (const [ticketKey, cr] of Object.entries(TICKET_CRS)) {
      if (!cr.crFile) continue
      s3Api
        .resolveTarget(cr.crFile, ticketKey)
        .then((result) => {
          if (cancelled) return
          setResolvedTarget((prev) => ({ ...prev, [ticketKey]: result }))
        })
        .catch(() => {
          if (cancelled) return
          setResolvedTarget((prev) => ({ ...prev, [ticketKey]: null }))
        })
    }
    return () => {
      cancelled = true
    }
  }, [])

  function getLinked(
    ticketKey: string | null | undefined
  ): { targetId: string | null; tierName: string; crLabel: string } | undefined {
    if (!ticketKey) return undefined
    const cr = TICKET_CRS[ticketKey]
    if (!cr) return undefined
    return {
      targetId: cr.crFile ? resolvedTarget[ticketKey]?.target_id ?? null : null,
      tierName: cr.tierName,
      crLabel: crLabelFromFile(cr.crFile),
    }
  }

  async function handleCheckOut() {
    if (!activeTicketKey) return
    const targetId = getLinked(activeTicketKey)?.targetId
    if (!targetId) return
    setCheckingOut(true)
    setCheckedOut(false)
    setCheckOutError(null)
    setCheckOutResult(null)
    const startedAt = Date.now()
    try {
      const result = await s3Api.scmCheckout(activeTicketKey, targetId)
      if (result.mode === 'simulated') {
        // Preserve the original ~10s pacing for the fully-fake path — this
        // beat is a deliberate "watch it happen" moment on stage. Live mode
        // resolves as soon as the real response arrives.
        const elapsed = Date.now() - startedAt
        await new Promise((resolve) => setTimeout(resolve, Math.max(0, 10000 - elapsed)))
      }
      setCheckOutResult(result)
      setCheckedOut(true)
    } catch (err) {
      setCheckOutError(err instanceof ApiError ? err.message : 'Check out failed.')
    } finally {
      setCheckingOut(false)
    }
  }

  async function handleGenerate() {
    if (!activeTicketKey) return
    const active = getLinked(activeTicketKey)
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
      const result = await s3Api.apply(
        generated.proposal_id,
        activeTicketKey,
        undefined,
        getLinked(activeTicketKey)?.targetId,
      )
      const nextAppliedFiles = { ...appliedFiles }
      for (const path of result.applied_files) nextAppliedFiles[path] = true
      const failure = result.post_apply && !result.post_apply.ok ? result.post_apply : null
      setApplied(true)
      setAppliedFiles(nextAppliedFiles)
      setRejectedFiles(result.rejected_files)
      setPostApplyFailure(failure)
      setFixCrashError(null)
      setScmState(result.scm ?? null)
      saveTicketState(activeTicketKey, {
        applied: true,
        appliedFiles: nextAppliedFiles,
        rejectedFiles: result.rejected_files,
        postApplyFailure: failure,
        scm: result.scm ?? null,
      })
      // The commit gate reads the ticket's test results, which may already exist
      // (a presenter can take a green regression baseline before Apply), so the
      // panel asks for them rather than assuming an empty gate.
      void refreshScm(generated.proposal_id, activeTicketKey)
      void runDesignSync(generated.proposal_id, result.applied_files, activeTicketKey)
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.message : 'Apply failed.')
    } finally {
      setApplying(false)
    }
  }

  // Pulls the branch state and the server-computed commit gate. Called after
  // Apply and after each test beat, because the gate's inputs are the test
  // results and they change under the panel.
  async function refreshScm(proposalId: string, ticketKey: string) {
    try {
      const result = await s3Api.scmState(proposalId, ticketKey)
      setScmState(result.scm)
      setScmBlockers(result.commit_blockers)
      setScmEvidence(result.test_evidence)
      saveTicketState(ticketKey, { scm: result.scm })
    } catch {
      // Read-only refresh of a panel that is already on screen — leave what is
      // showing rather than blanking it on a transient failure.
    }
  }

  async function handleCommit() {
    if (!generated || !activeTicketKey) return
    setCommitting(true)
    setScmError(null)
    setScmDetail(null)
    try {
      const result = await s3Api.scmCommit(
        generated.proposal_id,
        activeTicketKey,
        getLinked(activeTicketKey)?.targetId,
      )
      setScmState(result.scm)
      setScmBlockers(result.commit_blockers)
      setScmEvidence(result.test_evidence)
      saveTicketState(activeTicketKey, { scm: result.scm })
    } catch (err) {
      // A 409 here is the gate refusing, and its message is the reason — show it
      // verbatim rather than replacing it with "Commit failed".
      setScmError(err instanceof ApiError ? err.message : 'Commit failed.')
    } finally {
      setCommitting(false)
    }
  }

  async function handlePush() {
    if (!generated || !activeTicketKey) return
    setPushing(true)
    setScmError(null)
    setScmDetail(null)
    try {
      const result = await s3Api.scmPush(generated.proposal_id, activeTicketKey)
      setScmState(result.scm)
      setScmDetail(result.detail ?? null)
      saveTicketState(activeTicketKey, { scm: result.scm })
    } catch (err) {
      setScmError(err instanceof ApiError ? err.message : 'Push failed.')
    } finally {
      setPushing(false)
    }
  }

  // Deliberately fire-and-forget, after Apply has already been recorded as
  // succeeded: a doc check that is slow, unreachable or broken must never be
  // able to fail the apply beat. The endpoint itself answers checked:false
  // rather than erroring, so this catch is only for transport failures.
  async function runDesignSync(proposalId: string, appliedPaths: string[], ticketKey: string) {
    const active = getLinked(ticketKey)
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
      const result = await s3Api.apply(
        generated.proposal_id,
        activeTicketKey,
        path,
        getLinked(activeTicketKey)?.targetId,
      )
      const nextAppliedFiles = { ...appliedFiles, [path]: true }
      setAppliedFiles(nextAppliedFiles)
      setRejectedFiles(result.rejected_files)
      setScmState(result.scm ?? null)
      saveTicketState(activeTicketKey, {
        appliedFiles: nextAppliedFiles,
        rejectedFiles: result.rejected_files,
        scm: result.scm ?? null,
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
      setScmState(result.scm ?? null)
      saveTicketState(activeTicketKey, { appliedFiles: nextAppliedFiles, scm: result.scm ?? null })
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
      // Reverting everything abandons the branch server-side; keep showing it in
      // that state rather than hiding it, so "the branch was cut and thrown
      // away" stays visible instead of looking like it never happened.
      setScmState(result.scm ?? null)
      setScmDetail(null)
      setScmError(null)
      saveTicketState(activeTicketKey, {
        applied: false,
        appliedFiles: {},
        postApplyFailure: null,
        scm: result.scm ?? null,
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

  async function handleDraftScenarios() {
    if (!activeTicketKey) return
    const active = getLinked(activeTicketKey)
    setDraftingScenarios(true)
    setTestError(null)
    try {
      const result = await s3Api.testsScenarios(
        active?.tierName ?? 'Elite',
        active?.targetId,
        activeTicketKey
      )
      setScenarioDraft(result)
      setScenarios(result.scenarios)
      // A fresh draft is not an approved plan, and anything derived from the
      // old one is now stale.
      setScenariosApprovedBy(null)
      setTraceability(null)
      saveTicketState(activeTicketKey, {
        scenarioDraft: result,
        scenarios: result.scenarios,
        scenariosApprovedBy: undefined,
        traceability: undefined,
      })
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : 'Scenario drafting failed.')
    } finally {
      setDraftingScenarios(false)
    }
  }

  function handleScenariosChange(next: TestScenario[]) {
    if (!activeTicketKey) return
    setScenarios(next)
    // Editing after approval withdraws the approval — the signature was on
    // the previous list, not this one.
    setScenariosApprovedBy(null)
    saveTicketState(activeTicketKey, { scenarios: next, scenariosApprovedBy: undefined })
  }

  async function handleApproveScenarios() {
    if (!activeTicketKey) return
    const active = getLinked(activeTicketKey)
    setApprovingScenarios(true)
    setTestError(null)
    try {
      const result = await s3Api.testsScenariosApprove(
        active?.tierName ?? 'Elite',
        scenarios,
        active?.targetId,
        activeTicketKey
      )
      setScenariosApprovedBy(result.approved_by)
      setScenarioDraft((current) =>
        current ? { ...current, uncovered_criteria: result.uncovered_criteria } : current
      )
      saveTicketState(activeTicketKey, { scenariosApprovedBy: result.approved_by })
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : 'Could not approve the plan.')
    } finally {
      setApprovingScenarios(false)
    }
  }

  async function handleBuildTraceability() {
    if (!activeTicketKey) return
    const active = getLinked(activeTicketKey)
    setBuildingMatrix(true)
    setTestError(null)
    try {
      const result = await s3Api.testsTraceability(
        active?.tierName ?? 'Elite',
        scenarios,
        testsRun?.cases ?? [],
        regressionRun?.cases ?? [],
        active?.targetId,
        activeTicketKey
      )
      setTraceability(result)
      saveTicketState(activeTicketKey, { traceability: result })
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : 'Could not build the matrix.')
    } finally {
      setBuildingMatrix(false)
    }
  }

  // PDF is rendered server-side (headless Chromium via Playwright). A
  // machine without that browser installed answers 503, which is not an
  // error worth surfacing — the browser in front of the user can print the
  // same document to PDF itself, so fall back to that instead.
  async function handleExportDesignDoc(format: 'pdf' | 'html') {
    if (!activeTicketKey) return
    const active = getLinked(activeTicketKey)
    setExportingDoc(format)
    setDesignDocError(null)
    try {
      const blob = await s3Api.designDocDocument(
        active?.tierName ?? 'Elite',
        format,
        active?.targetId,
        activeTicketKey,
        (ticketCrossTeam[activeTicketKey] ?? []).map((impact) => impact.app_name)
      )
      downloadBlob(`${getLinked(activeTicketKey)?.crLabel ?? 'design'}-design-doc.${format}`, blob)
    } catch (err) {
      if (format === 'pdf' && err instanceof ApiError && err.status === 503) {
        printDesignDoc()
        return
      }
      setDesignDocError(err instanceof ApiError ? err.message : 'Could not export the document.')
    } finally {
      setExportingDoc(null)
    }
  }

  // Fallback path: open the already-rendered document in its own window and
  // let the browser print it. Uses the same HTML the server would have sent.
  async function printDesignDoc() {
    if (!activeTicketKey) return
    const active = getLinked(activeTicketKey)
    try {
      const blob = await s3Api.designDocDocument(
        active?.tierName ?? 'Elite',
        'html',
        active?.targetId,
        activeTicketKey,
        (ticketCrossTeam[activeTicketKey] ?? []).map((impact) => impact.app_name)
      )
      const url = URL.createObjectURL(blob)
      const printWindow = window.open(url, '_blank')
      if (!printWindow) {
        setDesignDocError('Allow pop-ups for this site to print the document.')
        return
      }
      printWindow.addEventListener('load', () => printWindow.print())
    } catch (err) {
      setDesignDocError(err instanceof ApiError ? err.message : 'Could not open the document.')
    }
  }

  async function handleGenerateTests() {
    if (!activeTicketKey) return
    const active = getLinked(activeTicketKey)
    setGeneratingTests(true)
    setTestError(null)
    try {
      const result = await s3Api.testsGenerate(
        active?.tierName ?? 'Elite',
        active?.targetId,
        activeTicketKey,
        scenarios.length ? scenarios : null
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
    const active = getLinked(activeTicketKey)
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
      // This run is the commit gate's input, so the source-control panel has to
      // hear about it — otherwise the gate stays closed on screen after the very
      // run that opened it.
      if (generated) void refreshScm(generated.proposal_id, activeTicketKey)
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : 'Test run failed.')
    } finally {
      setRunningTests(false)
    }
  }

  // Independent of generate/run: the regression suite predates the CR, so it
  // is runnable at any point. Presenters take a green baseline before Apply
  // and re-run it after — the pair is the "we broke nothing" evidence.
  async function handleRunRegression() {
    if (!activeTicketKey) return
    const active = getLinked(activeTicketKey)
    setRunningRegression(true)
    setTestError(null)
    try {
      const result = await s3Api.testsRegression(
        active?.tierName ?? 'Elite',
        active?.targetId,
        activeTicketKey
      )
      setRegressionRun(result)
      saveTicketState(activeTicketKey, { regressionRun: result })
      if (generated) void refreshScm(generated.proposal_id, activeTicketKey)
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : 'Regression run failed.')
    } finally {
      setRunningRegression(false)
    }
  }

  async function handleMutationCheck() {
    if (!activeTicketKey) return
    const active = getLinked(activeTicketKey)
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
    const active = getLinked(activeTicketKey)
    setDraftingDesignDoc(true)
    setDesignDocError(null)
    try {
      const result = await s3Api.designDoc(
        active?.tierName ?? 'Elite',
        active?.targetId,
        activeTicketKey,
        (ticketCrossTeam[activeTicketKey] ?? []).map((impact) => impact.app_name)
      )
      setDesignDoc(result.design_doc)
      setDesignDiagram(result.diagram_svg ?? null)
      setDesignDiagramCaption(result.diagram_caption ?? null)
      saveTicketState(activeTicketKey, {
        designDoc: result.design_doc,
        designDiagram: result.diagram_svg,
        designDiagramCaption: result.diagram_caption,
      })
    } catch (err) {
      setDesignDocError(err instanceof ApiError ? err.message : 'Design doc drafting failed.')
    } finally {
      setDraftingDesignDoc(false)
    }
  }

  async function handleDraftReleaseNotes() {
    if (!activeTicketKey) return
    const active = getLinked(activeTicketKey)
    setDraftingNotes(true)
    setReleaseError(null)
    try {
      const result = await s3Api.releaseNoteSet(
        active?.tierName ?? 'Elite',
        active?.targetId,
        activeTicketKey,
        (ticketCrossTeam[activeTicketKey] ?? []).map((impact) => impact.app_name),
        generated?.proposal_id ?? null,
      )
      setReleaseNoteSet(result.notes)
      setDeploymentPlan(result.plan)
      saveTicketState(activeTicketKey, {
        releaseNoteSet: result.notes,
        deploymentPlan: result.plan,
      })
    } catch (err) {
      setReleaseError(err instanceof ApiError ? err.message : 'Could not draft release notes.')
    } finally {
      setDraftingNotes(false)
    }
  }

  // Everything the record needs that only this browser knows. Approvals are
  // deliberately absent — the server reads those from its own event log
  // rather than taking the client's word for who signed what.
  function releaseRecordPayload(format: 'pdf' | 'html') {
    const active = activeTicketKey ? getLinked(activeTicketKey) : undefined
    return {
      tier_name: active?.tierName ?? 'Elite',
      target_id: active?.targetId ?? null,
      ticket_number: activeTicketKey,
      downstream_apps: (ticketCrossTeam[activeTicketKey ?? ''] ?? []).map(
        (impact) => impact.app_name
      ),
      format,
      scenarios,
      generated_cases: testsRun?.cases ?? [],
      regression_cases: regressionRun?.cases ?? [],
      mutation: mutationCheck
        ? {
            caught: mutationCheck.tests_caught_bug,
            total: mutationCheck.summary.total,
            failed: mutationCheck.summary.failed + mutationCheck.summary.errors,
          }
        : null,
      applied_files: Object.keys(appliedFiles).filter((path) => appliedFiles[path]),
      // Lets the record pin the deployment plan to the branch and commit this
      // change went through. Only the id is sent — the server reads the branch
      // state itself, so the record cannot be told about a commit nobody made.
      proposal_id: generated?.proposal_id ?? null,
    }
  }

  async function handleDownloadRecord() {
    if (!activeTicketKey) return
    setExportingRecord(true)
    setReleaseError(null)
    try {
      const blob = await s3Api.releaseRecord(releaseRecordPayload('pdf'))
      const label = getLinked(activeTicketKey)?.crLabel ?? 'release'
      downloadBlob(`${label}-release-record.pdf`, blob)
    } catch (err) {
      setReleaseError(err instanceof ApiError ? err.message : 'Could not build the record.')
    } finally {
      setExportingRecord(false)
    }
  }

  async function handleAttachRecord() {
    if (!activeTicketKey) return
    setAttachingRecord(true)
    setReleaseError(null)
    try {
      setAttachResult(await s3Api.releaseRecordAttach(releaseRecordPayload('pdf')))
    } catch (err) {
      setReleaseError(err instanceof ApiError ? err.message : 'Could not attach the record.')
    } finally {
      setAttachingRecord(false)
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
    const linked = getLinked(ticketKey)
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
    const linked = getLinked(ticketKey)
    // A CR that had to be matched by the AI tier named no target system of
    // its own, so there is no repo to scope an analysis to yet — /analyze
    // would have to pick one first and then present file selection from it,
    // which is the answer this beat is supposed to be working towards. Those
    // tickets analyze their text directly instead (no target, no file
    // selection), and the repo is chosen afterwards. Derived from the
    // resolution rather than a per-ticket flag, so a new ambiguous CR gets
    // this automatically — see TICKET_CRS on why there is no lookup table.
    const crNamesTarget = resolvedTarget[ticketKey]?.method !== 'ai'
    const targetScoped = !!linked?.targetId && crNamesTarget
    setTicketAnalysisLoading((prev) => ({ ...prev, [ticketKey]: true }))
    setTicketAnalysisError((prev) => ({ ...prev, [ticketKey]: '' }))
    try {
      let result: AnalyzeResponse
      const pendingQuestion = ticketClarificationQuestion[ticketKey]
      if (targetScoped && linked) {
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
        // Either no CR/target registered for this ticket at all (e.g. a
        // cross-team ticket for another application), or a CR that names no
        // target system (see crNamesTarget above) — analyze the text
        // directly, with no repo scoping it.
        let crText: string
        if (pendingQuestion) {
          // A clarifying question is outstanding — this call carries the
          // engineer's answer, not the original ticket text again (the
          // server keeps the transcript server-side).
          crText = (clarificationAnswer || '').trim()
          if (!crText) return
        } else if (TICKET_CRS[ticketKey]?.crFile) {
          // There *is* a CR, it just doesn't say which repo it's for. Read
          // it rather than falling back to the ticket's summary, so the
          // analysis and the resolver both work from the same document.
          const crFile = TICKET_CRS[ticketKey].crFile as string
          crText = (await s3Api.crFile(crFile)).cr_text.trim()
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
    const linked = getLinked(ticketKey)
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
        (issue) => issue.assignee === identity?.name && TICKET_CRS[issue.key]
      )
      return mine ? mine.key : null
    })
  }, [isEngineer, boardIssues, identity?.name])

  useEffect(() => {
    if (!isEngineer || !activeTicketKey) return
    loadDependencies(activeTicketKey)
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
    setDesignDiagram(persisted.designDiagram ?? null)
    setDesignDiagramCaption(persisted.designDiagramCaption ?? null)
    setScenarioDraft(persisted.scenarioDraft ?? null)
    setScenarios(persisted.scenarios ?? [])
    setScenariosApprovedBy(persisted.scenariosApprovedBy ?? null)
    setTraceability(persisted.traceability ?? null)
    setTestsGenerated(persisted.testsGenerated ?? null)
    setTestsRun(persisted.testsRun ?? null)
    setRegressionRun(persisted.regressionRun ?? null)
    setMutationCheck(persisted.mutationCheck ?? null)
    setReleaseNoteSet(persisted.releaseNoteSet ?? null)
    setDeploymentPlan(persisted.deploymentPlan ?? null)
    setAttachResult(null)
    setReleaseError(null)
    setHandoffError(null)
    setScmState(persisted.scm ?? null)
    setScmBlockers([])
    setScmEvidence({ generated_suite: null, regression_suite: null })
    setScmError(null)
    setScmDetail(null)
    // The persisted branch is what to render immediately; the gate is not
    // persisted at all, because it is a function of the ticket's test results
    // and a stale "ready to commit" is exactly the wrong thing to show.
    if (persisted.generated?.proposal_id && persisted.scm) {
      void refreshScm(persisted.generated.proposal_id, activeTicketKey)
    }
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
  const activeLinked = activeTicketKey ? getLinked(activeTicketKey) : undefined
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

  // The active ticket's repo resolution. `undefined` while the mount-time
  // resolve call is still in flight, `null` if it failed outright — the card
  // distinguishes the two, since "still looking" and "couldn't tell" are very
  // different things to show someone.
  const activeMatch = activeTicketKey ? resolvedTarget[activeTicketKey] : undefined
  const matchPending = activeTicketKey ? !(activeTicketKey in resolvedTarget) : false
  // A deterministic match needs no sign-off — tiers 1 and 2 matched the CR's
  // own identifier or application header structurally, and never guessed.
  // Every AI pick does, deliberately stricter than the server's
  // `needs_confirmation` (which trusts a high-confidence guess outright):
  // the confidence string is itself model output, so gating a human review on
  // it means the model decides when it gets reviewed. "A model chose the
  // repo" is the reviewable event here, not "a model admitted doubt".
  const targetConfirmationRequired = activeMatch?.method === 'ai'
  const targetAccepted =
    !!activeMatch?.resolved &&
    (!targetConfirmationRequired || !!(activeTicketKey && targetConfirmed[activeTicketKey]))

  // Checkout needs a target to branch for, so it stays locked until the repo
  // is both resolved and (when the AI guessed) accepted by a human — and
  // until the analysis that justifies doing the work at all has run.
  // These strings name the *stage* that owns the blocking action, not a
  // direction. They used to say "above" when every step was one long scrolling
  // page; each step is now its own route, so "above" pointed at nothing. Only
  // say "above" where the thing really is higher up the same stage.
  const checkOutLockedReason = !activeTicketKey
    ? 'Select a ticket assigned to you on the Board stage.'
    : !analysisDoneForActive
      ? 'Open the ticket on the Board stage and run AI impact analysis first.'
      : matchPending
        ? 'Identifying which repo this ticket belongs to…'
        : !activeMatch?.resolved
          ? "This ticket's CR didn't resolve to a repo this console can automate."
          : targetConfirmationRequired && !targetAccepted
            ? // Repo confirmation sits on this same stage, just above checkout.
              'Confirm the repo above before checking out.'
            : null

  const generateLockedReason = !activeTicketKey
    ? 'Select a ticket assigned to you on the Board stage.'
    : // Generate writes against the resolved target, so an AI pick nobody
      // accepted must not reach it either — not just checkout.
      targetConfirmationRequired && !targetAccepted
      ? 'Confirm the repo on the Target selection stage before generating.'
      : !analysisDoneForActive
        ? 'Open the ticket on the Board stage and run AI impact analysis first.'
        : openDependencies.length > 0
          ? `Waiting on ${openDependencies.length} other team${openDependencies.length > 1 ? 's' : ''} to finish their tickets.`
          : null
  const canGenerate = generateLockedReason === null

  const canDesignDoc = generated !== null && (generated.diff_text.trim() === '' || applied)
  const designDocLockedReason = canDesignDoc
    ? null
    : 'Apply the proposed change on the "Generate the change" stage before drafting a design doc.'

  // Tests belong to QA: the ticket must be handed off (status QA) and the
  // logged-in user must be the assigned tester — the developer who wrote the
  // change doesn't get to verify it themselves.
  const canTest = canDesignDoc && !!designDoc && inQa && isActiveAssignee
  const testLockedReason = canTest
    ? null
    : !canDesignDoc
      ? designDocLockedReason
      : !designDoc
        ? 'Draft the design doc on the "Draft design doc (for QA)" stage before generating tests.'
        : !inQa
          ? 'Hand the ticket off to QA on the "Draft design doc (for QA)" stage — the assigned tester runs this step.'
          : `With QA — only ${activeIssue?.assignee || 'the assigned tester'} can generate and run tests.`

  const canDraftNotes = !!testsRun && (!inQa || isActiveAssignee)
  const notesLockedReason = canDraftNotes
    ? null
    : testsRun
      ? `With QA — only ${activeIssue?.assignee || 'the assigned tester'} can draft release notes.`
      : 'Generate and run tests first.'

  const crLabel = activeLinked?.crLabel ?? null
  // Absolute paths, not bare segments. These feed <Link to={stage.path}> from two
  // different depths: StageRail renders in the /s3 layout element, StageNav
  // renders inside the child stage element. A relative `to="target"` therefore
  // resolves to /s3/target from the rail but /s3/board/target from the nav —
  // which matches no route and silently blanks the page. Absolute paths resolve
  // identically from both, so do not "tidy" the /s3 prefix away.
  const stages: S3Stage[] = [
    { id: 'board', title: 'Board', path: '/s3/board', locked: false, lockedReason: null, done: analysisDoneForActive, statusLabel: analysisDoneForActive ? 'Impact analyzed' : null },
    { id: 'target', title: 'Target selection', path: '/s3/target', locked: !isEngineer, lockedReason: isEngineer ? null : 'Only engineers select and check out target repos.', done: checkedOut, statusLabel: checkedOut ? 'Checked out' : null },
    {
      id: 'generate',
      title: 'Generate the change',
      path: '/s3/generate',
      locked: !canGenerate && !generated,
      lockedReason: generateLockedReason,
      done: applied,
      statusLabel: applied && postApplyFailure ? '⚠ Applied — app broken' : applied ? '✓ Applied' : generated ? 'Proposed' : null,
      statusVariant: applied && postApplyFailure ? 'error' : 'ok',
    },
    { id: 'design-doc', title: 'Draft design doc (for QA)', path: '/s3/design-doc', locked: !canDesignDoc, lockedReason: designDocLockedReason, done: !!designDoc, statusLabel: designDoc ? '✓ Drafted' : null },
    {
      id: 'tests',
      title: 'Generate tests + run',
      path: '/s3/tests',
      locked: !canTest,
      lockedReason: testLockedReason,
      done: !!mutationCheck || !!testsRun,
      statusLabel: regressionRun && !regressionRun.passed ? '✗ Regression' : mutationCheck ? (mutationCheck.tests_caught_bug ? '✓ Proven' : '⚠ Bug missed') : testsRun ? (testsRun.passed ? '✓ Passed' : '✗ Failed') : testsGenerated ? 'Generated' : null,
      statusVariant: (mutationCheck && !mutationCheck.tests_caught_bug) || (testsRun && !testsRun.passed) || (regressionRun && !regressionRun.passed) ? 'error' : 'ok',
    },
    { id: 'release', title: 'Draft release notes', path: '/s3/release', locked: !canDraftNotes, lockedReason: notesLockedReason, done: !!releaseNoteSet, statusLabel: releaseNoteSet ? '✓ Drafted' : null },
  ]



  return {
    AI_LABEL,
    identity,
    isManager,
    isEngineer,
    generated,
    setGenerated,
    generating,
    setGenerating,
    generateError,
    setGenerateError,
    perFileQuestion,
    setPerFileQuestion,
    perFileChat,
    setPerFileChat,
    revisingFile,
    setRevisingFile,
    reviseError,
    setReviseError,
    filePaths,
    setFilePaths,
    collapsedFiles,
    setCollapsedFiles,
    fileReasons,
    setFileReasons,
    applied,
    setApplied,
    applying,
    setApplying,
    applyError,
    setApplyError,
    appliedFiles,
    setAppliedFiles,
    applyingFile,
    setApplyingFile,
    rejectedFiles,
    setRejectedFiles,
    rejectingFile,
    setRejectingFile,
    rejectPromptFor,
    setRejectPromptFor,
    rejectReason,
    setRejectReason,
    revertingFile,
    reverting,
    setRevertingFile,
    setReverting,
    postApplyFailure,
    setPostApplyFailure,
    designSync,
    setDesignSync,
    designDoc,
    designDocApplying,
    setDesignDocApplying,
    setDesignDoc,
    designDocApplied,
    setDesignDocApplied,
    fixingCrash,
    setFixingCrash,
    fixCrashError,
    setFixCrashError,
    scmState,
    setScmState,
    scmBlockers,
    setScmBlockers,
    scmEvidence,
    setScmEvidence,
    committing,
    setCommitting,
    pushing,
    setPushing,
    scmError,
    setScmError,
    scmDetail,
    setScmDetail,
    newFilePath,
    setNewFilePath,
    newFileInstruction,
    setNewFileInstruction,
    addingFile,
    setAddingFile,
    addFileError,
    setAddFileError,
    designDiagram,
    setDesignDiagram,
    designDiagramCaption,
    setDesignDiagramCaption,
    exportingDoc,
    setExportingDoc,
    qaTester,
    setQaTester,
    TESTER_ROSTER,
    handingOff,
    setHandingOff,
    handoffError,
    setHandoffError,
    closingTicket,
    setClosingTicket,
    draftingDesignDoc,
    setDraftingDesignDoc,
    designDocError,
    setDesignDocError,
    testsGenerated,
    setTestsGenerated,
    generatingTests,
    setGeneratingTests,
    testsRun,
    setTestsRun,
    runningTests,
    setRunningTests,
    scenarioDraft,
    setScenarioDraft,
    scenarios,
    setScenarios,
    scenariosApprovedBy,
    setScenariosApprovedBy,
    draftingScenarios,
    setDraftingScenarios,
    approvingScenarios,
    setApprovingScenarios,
    traceability,
    setTraceability,
    buildingMatrix,
    setBuildingMatrix,
    regressionRun,
    setRegressionRun,
    runningRegression,
    setRunningRegression,
    mutationCheck,
    setMutationCheck,
    mutating,
    setMutating,
    testError,
    setTestError,
    draftingNotes,
    setDraftingNotes,
    releaseNoteSet,
    setReleaseNoteSet,
    deploymentPlan,
    setDeploymentPlan,
    exportingRecord,
    setExportingRecord,
    attachingRecord,
    setAttachingRecord,
    attachResult,
    setAttachResult,
    releaseError,
    setReleaseError,
    openStage,
    setOpenStage,
    checkingOut,
    setCheckingOut,
    checkedOut,
    setCheckedOut,
    checkOutResult,
    setCheckOutResult,
    checkOutError,
    setCheckOutError,
    quickChatMessages,
    setQuickChatMessages,
    quickChatInput,
    setQuickChatInput,
    quickChatSending,
    setQuickChatSending,
    quickChatError,
    setQuickChatError,
    quickChatResult,
    setQuickChatResult,
    creatingTicketFor,
    setCreatingTicketFor,
    assigningTicketFor,
    setAssigningTicketFor,
    createdTickets,
    setCreatedTickets,
    assigneeByApp,
    setAssigneeByApp,
    boardIssues,
    setBoardIssues,
    boardError,
    setBoardError,
    boardLoading,
    setBoardLoading,
    boardFilter,
    setBoardFilter,
    boardStatusFilter,
    setBoardStatusFilter,
    boardAssignee,
    setBoardAssignee,
    assigningBoardTicket,
    setAssigningBoardTicket,
    activeTicketKey,
    setActiveTicketKey,
    expandedTicket,
    setExpandedTicket,
    ticketAnalysis,
    setTicketAnalysis,
    ticketAnalysisLoading,
    setTicketAnalysisLoading,
    ticketAnalysisError,
    setTicketAnalysisError,
    handleRunAnalysisForTicket,
    ticketClarificationQuestion,
    setTicketClarificationQuestion,
    ticketCrossTeam,
    setTicketCrossTeam,
    ticketCrossTeamTokens,
    setTicketCrossTeamTokens,
    ticketCrossTeamLoading,
    setTicketCrossTeamLoading,
    ticketCrText,
    setTicketCrText,
    ticketEvents,
    setTicketEvents,
    ticketEventsLoading,
    setTicketEventsLoading,
    dependencies,
    setDependencies,
    dependenciesLoading,
    setDependenciesLoading,
    markingDone,
    setMarkingDone,
    screenshotBefore,
    setScreenshotBefore,
    screenshotAfter,
    setScreenshotAfter,
    crLabel,
    stages,
    resolvedTarget,
    setResolvedTarget,
    targetConfirmed,
    setTargetConfirmed,
    getLinked,
    handleCheckOut,
    handleGenerate,
    handleAskAboutFile,
    handleApply,
    refreshScm,
    runDesignSync,
    handleCommit,
    handlePush,
    handleApplyDesignDoc,
    handleFixCrash,
    handleApplyFile,
    handleRejectFile,
    handleClearRejection,
    handleRevertFile,
    handleRevertAll,
    handleAddFile,
    handleDraftScenarios,
    handleScenariosChange,
    handleApproveScenarios,
    handleBuildTraceability,
    handleExportDesignDoc,
    printDesignDoc,
    handleGenerateTests,
    handleRunTests,
    handleRunRegression,
    handleMutationCheck,
    handleDraftDesignDoc,
    handleDraftReleaseNotes,
    releaseRecordPayload,
    handleDownloadRecord,
    handleAttachRecord,
    handleHandoffToQa,
    loadTicketEvents,
    handleMarkTicketDone,
    handleQuickChatSend,
    handleQuickChatReset,
    handleCreateCrossTeamTicket,
    handleAssignCrossTeamTicket,
    ASSIGNEE_ROSTER,
    handleLoadBoard,
    handleAssignBoardTicket,
    handleTicketClick,
    handleCheckCrossTeamForTicket,
    loadDependencies,
    handleMarkDone,
    openDependencies,
    diffFiles,
    diffByPath,
    orderedFilePaths,
    activeLinked,
    targetApp,
    analysisDoneForActive,
    activeIssue,
    inQa,
    isActiveAssignee,
    activeMatch,
    matchPending,
    targetConfirmationRequired,
    targetAccepted,
    checkOutLockedReason,
    generateLockedReason,
    canGenerate,
    canDesignDoc,
    designDocLockedReason,
    canTest,
    testLockedReason,
    canDraftNotes,
    notesLockedReason
  }
}

export type S3Controller = ReturnType<typeof useS3Controller>

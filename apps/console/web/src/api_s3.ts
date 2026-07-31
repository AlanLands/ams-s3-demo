// Thin fetch wrappers over the FastAPI backend for S3 — Enhancement Delivery.
// Mirrors the api/routers/s3.py response shapes exactly — no client-side
// business logic, same "thin view" convention as api.ts's s1Api/s2Api.

import { ApiError, request } from './api'

export interface SubsystemScreen {
  in_scope: string[]
  screened_out: string[]
  scores: Record<string, number>
}

export interface FileSelection {
  candidate_pool_size: number
  candidate_pool_by_language: Record<string, number>
  selected_files: string[]
  subsystem_screen: SubsystemScreen
}

export interface CrResponse {
  tier_name: string
  cr_text: string
}

export interface EffortEstimate {
  hours_class: string
  priority_equivalent: string
  reasoning: string
}

export interface TargetRepo {
  id: string
  name: string | null
  reasoning: string
  confidence: string
}

export interface RoutedApplication {
  app_id: string
  display_name: string
  business_service: string
  jira_project_key: string
  component_team: string
  tech_stack: string
  // Empty for applications this console can route to but has no code for.
  repo_path: string
}

// How a ticket reached its application. 'ci' and 'business_service' are
// deterministic CMDB lookups with no model call; 'unrouted' means the ticket
// carried no usable application context and the AI repo-match tier should run
// instead (see s3_enhancement/routing.py).
export type RouteMethod = 'ci' | 'business_service' | 'unrouted'

export interface RouteDecision {
  method: RouteMethod
  routed: boolean
  // The ticket field value that produced the match, for display.
  matched_on: string
  needs_ai_fallback: boolean
  // Deliberately separate from `routed`: an application can have a known
  // owning team and still have no repo S3 can generate against, in which case
  // the ticket is routed correctly and automation stays off.
  automation_available: boolean
  application: RoutedApplication | null
  suggested_assignee: string
  candidate_targets: { target_id: string; display_name: string }[]
}

export type TargetResolveMethod = 'cr_id' | 'application_header' | 'ai' | 'unresolved'

export interface TargetResolveResponse {
  method: TargetResolveMethod
  resolved: boolean
  needs_confirmation: boolean
  confidence: string | null
  reasoning: string
  target_id: string | null
  display_name: string | null
}

export interface ApplicationsResponse {
  applications: (RoutedApplication & {
    ci_names: string[]
    automation_available: boolean
  })[]
}

export interface AnalyzeResponse {
  label: string
  impact_analysis: string
  // One sentence per gap the model had to fill in rather than ask about
  // (see s3_enhancement/analyze.py's ImpactAnalysis) — empty when the CR
  // left nothing unspecified.
  assumptions: string[]
  effort_estimate: EffortEstimate
  // Both absent for analyze-adhoc's ad-hoc tickets — those have no in-console
  // target/codebase to select files from (see s3Api.analyzeAdhoc).
  file_selection?: FileSelection
  token_panel?: TokenPanel
  // Ad-hoc tickets only — the AI's best guess at which connected GitLab repo
  // this CR is for, once confident enough to stop asking (see
  // AdhocAnalyzeResponse.target_repo and analyze-adhoc's clarification gate).
  target_repo?: TargetRepo | null
  // How the ticket reached its application, when it carried CI context.
  routing?: RouteDecision
}

// Raw wire shape of POST /analyze — unlike AnalyzeResponse (used for
// already-resolved state storage once a clarification round is done, if
// any), this can also come back as a pending question (see analyze.py's
// check_cr_gaps: a specific missing detail like an unstated default gets
// asked about instead of silently reported as an assumption).
export interface AnalyzeApiResponse {
  label: string
  needs_clarification: boolean
  // Present only when needs_clarification is true.
  question?: string
  // Present only when needs_clarification is false.
  impact_analysis?: string
  assumptions?: string[]
  effort_estimate?: EffortEstimate
  file_selection?: FileSelection
  token_panel?: TokenPanel
}

export interface TokenPanel {
  scoped_input_tokens: number | null
  scoped_output_tokens: number | null
  // True when counts are reconstructed from a replay recording (chars/4
  // heuristic), not provider-reported usage — the UI marks them "~".
  estimated?: boolean
  naive_input_tokens_estimate?: number
}

export interface GenerateResponse {
  label: string
  tier_name: string
  proposal_id: string
  diff_text: string
  files_changed: string[]
  file_reasons: Record<string, string>
  used_replay: boolean
  file_selection: FileSelection
  token_panel: TokenPanel
}

export interface ReviseResponse {
  label: string
  proposal_id: string
  diff_text: string
  files_changed: string[]
  message: string | null
  token_panel: Pick<TokenPanel, 'scoped_input_tokens' | 'scoped_output_tokens'>
}

export interface PostApplyStep {
  command: string
  returncode: number
  output_tail: string
}

export interface PostApplyResult {
  ok: boolean
  steps: PostApplyStep[]
}

// The source-control flow around Apply: branch → commit → push. Modelled, never
// executed — `simulated` is always true, and the release record reports the
// un-run pipeline as something this release did not evidence. See
// s3_enhancement/scm.py before changing any of this.
export interface ScmCommit {
  sha: string
  message: string
  files: string[]
  committed_at: string
}

export interface ScmState {
  proposal_id: string
  branch: string
  base: string
  ticket: string
  created_at: string
  staged_files: string[]
  commit: ScmCommit | null
  pushed_at: string | null
  pipeline_id: string
  abandoned_at: string | null
  status: 'open' | 'applied' | 'committed' | 'pushed' | 'abandoned'
  simulated: boolean
  // The git commands a real integration would have issued, in order.
  transcript: string[]
}

export interface ScmSuiteEvidence {
  passed: boolean
  detail: string
  ts: string
}

export interface ScmResponse {
  proposal_id: string
  scm: ScmState | null
  // Why the branch may not be committed yet, in the words to show the user.
  // Empty means the gate is open. Computed server-side from the ticket's event
  // log, never from anything this client asserts.
  commit_blockers: string[]
  test_evidence: {
    generated_suite: ScmSuiteEvidence | null
    regression_suite: ScmSuiteEvidence | null
  }
  detail?: string
}

export interface ScmCheckoutResponse {
  mode: 'simulated' | 'live'
  branch: string
  base: string
  // Null in simulated mode — there is no real commit to point a sha at.
  sha: string | null
  created: boolean | null
  already_current: boolean | null
  // Files that were already modified before this checkout, live mode only —
  // informational, never blocks the checkout (see s3_enhancement/scm_live.py).
  dirty_files: string[]
  detail: string
}

export interface ApplyResponse {
  proposal_id: string
  applied_files: string[]
  post_apply?: PostApplyResult | null
  // `{path: reason}` for files the developer turned down — excluded from an
  // apply-all. Returned on every apply so the console's per-file state stays
  // in sync with the server's, rather than being tracked only client-side.
  rejected_files: Record<string, string>
  // Files this proposal has written and can still put back.
  revertable_files: string[]
  // The feature branch apply opened before writing anything.
  scm?: ScmState | null
}

export interface RejectResponse {
  proposal_id: string
  rejected_files: Record<string, string>
}

export interface RevertResponse {
  proposal_id: string
  reverted_files: string[]
  post_apply?: PostApplyResult | null
  revertable_files: string[]
  // Null when the proposal never went through the source-control flow.
  // Reverting every applied file abandons the branch rather than rewinding it.
  scm?: ScmState | null
}

export interface DesignDocFinding {
  subsystem: string
  design_doc: string
  applied_files: string[]
  still_accurate: boolean
  reason: string
  // Present only when the doc needs updating AND a replacement was produced —
  // it addresses an ordinary staged proposal, applied via the same apply().
  proposal_id: string
  diff_text: string
}

export interface DesignSyncResponse {
  label: string
  checked: boolean
  unavailable_reason: string
  affected_subsystems: { subsystem: string; design_doc: string; applied_files: string[] }[]
  findings: DesignDocFinding[]
}

export interface AddFileResponse {
  label: string
  proposal_id: string
  diff_text: string
  files_changed: string[]
  message: string | null
  token_panel: Pick<TokenPanel, 'scoped_input_tokens' | 'scoped_output_tokens'>
}

export interface TestsResponse {
  label: string
  diff_text: string
  files_changed: string[]
  used_replay: boolean
  pytest_output: string
  returncode?: number
  passed?: boolean
  token_panel: TokenPanel
}

export interface TestsGenerateResponse {
  label: string
  diff_text: string
  files_changed: string[]
  used_replay: boolean
  token_panel: TokenPanel
}

export interface TestCaseResult {
  name: string
  classname: string
  description: string
  status: 'passed' | 'failed' | 'error' | 'skipped'
  time_s: number
  message: string | null
}

export interface TestRunSummary {
  total: number
  passed: number
  failed: number
  errors: number
  skipped: number
}

export interface TestsRunResponse {
  label: string
  passed: boolean
  returncode: number
  output: string
  duration_s: number
  summary: TestRunSummary
  cases: TestCaseResult[]
}

// One planned check, before any test code exists. Editable by the tester —
// the console treats this as a draft document, not a server-owned record.
export interface TestScenario {
  id: string
  title: string
  kind: 'positive' | 'negative' | 'boundary' | 'regression'
  acceptance_criteria: string[]
  preconditions: string
  test_data: string
  steps: string[]
  expected: string
}

export interface AcceptanceCriterion {
  id: string
  text: string
  is_regression: boolean
}

export interface ScenariosResponse {
  label: string
  scenarios: TestScenario[]
  criteria: AcceptanceCriterion[]
  uncovered_criteria: string[]
  token_panel: TokenPanel
}

export interface ScenarioApprovalResponse {
  scenarios: TestScenario[]
  uncovered_criteria: string[]
  approved_by: string
}

export type TraceStatus = 'passed' | 'failed' | 'not_automated' | 'no_scenario' | 'not_run'

export interface TraceabilityRow {
  criterion_id: string
  criterion_text: string
  is_regression: boolean
  scenario_ids: string[]
  test_names: string[]
  status: TraceStatus
  covered_by: 'generated' | 'regression' | ''
}

export interface TraceabilityResponse {
  rows: TraceabilityRow[]
  summary: Record<TraceStatus | 'total', number>
}

// The target app's checked-in, pre-existing suite. No `label` — nothing here
// is AI output, and labelling a human-authored regression run as an AI
// suggestion would be a lie the rest of this console is careful not to tell.
export interface RegressionRunResponse extends Omit<TestsRunResponse, 'label'> {
  suite_paths: string[]
}

// The "prove the tests catch bugs" beat: a seeded bug is injected, the suite
// re-run, and the working tree reverted server-side before this returns.
export interface MutationCheckResponse extends TestsRunResponse {
  description: string
  file: string
  mutation_diff: string
  tests_caught_bug: boolean
  reverted: boolean
}

export interface ReleaseNotesResponse {
  label: string
  release_notes: string
}

export interface DesignDocResponse {
  label: string
  design_doc: string
  // Inline SVG change map, derived server-side from the changed-file set —
  // see s3_enhancement/diagram.py. Not model output.
  diagram_svg: string
  diagram_caption: string
  changed_files: string[]
}

export interface ReleaseNoteSet {
  changelog: string
  ops_note: string
  whats_new: string
}

export interface PlanStep {
  order: number
  kind: 'deploy' | 'migrate' | 'verify' | 'rollback'
  title: string
  detail: string
  command: string
}

// Derived from the change's own service graph — see s3_enhancement/release.py.
// No model call, so it arrives with the notes rather than behind its own button.
export interface DeploymentPlan {
  steps: PlanStep[]
  rollback: PlanStep[]
  service_order: string[]
  order_reason: string
}

export interface ReleaseNotesResponse2 {
  label: string
  notes: ReleaseNoteSet
  plan: DeploymentPlan
  token_panel: TokenPanel
}

export interface ReleaseAttachResponse {
  attached: boolean
  simulated: boolean
  filename: string
  size_bytes: number
  detail: string
}

export interface HarnessStatus {
  tier_name: string
  harness: string
  used_replay: boolean
  duration_s?: number
  status?: 'ok' | 'failed'
  error?: string
  [key: string]: unknown
}

export interface HarnessResponse {
  label: string
  status: HarnessStatus
  diff_text: string
  session_log_tail?: string
}

export interface GitlabProject {
  id: number
  name: string
  name_with_namespace: string
  last_activity_at: string
  web_url?: string
  default_branch?: string
}

export interface GitlabScopeResponse {
  repo_size: number
  files_reached_llm: number
  selected_files: string[]
}

export interface RepoMatch {
  id: string
  name: string | null
  reasoning: string
}

export interface SuggestedProject extends RepoMatch {
  confidence: string
}

export interface GitlabScopeAutoResponse extends Partial<GitlabScopeResponse> {
  label: string
  needs_clarification: boolean
  // Present in both the clarification-needed and confirmed-scope responses —
  // a confidence below 'high' means the developer should confirm this is the
  // right repo before file discovery/codegen scopes against it.
  suggested_project: SuggestedProject
  alternates: RepoMatch[]
  // Present only when needs_clarification is true.
  question?: string
}

export interface CrossTeamImpact {
  app_name: string
  reason: string
  suggested_summary: string
}

export interface CrossTeamImpactResponse {
  label: string
  impacts: CrossTeamImpact[]
  token_panel: TokenPanel
}

export interface CrossTeamTicketResponse {
  label: string
  app_name: string
  issue: JiraIssue
}

export interface JiraIssue {
  key: string
  id: string
  self?: string
  summary: string | null
  status: string | null
  issue_type: string | null
  assignee?: string | null
  description?: string | null
  // S3's two intake flavors — a direct business change request, or a ticket
  // derived from a problem record (repeated incidents -> a permanent-fix
  // problem record -> this ticket). Both converge on the identical
  // analyze/codegen/test/docgen flow; this is presentational only.
  origin?: 'business_cr' | 'problem_record'
  // Present only when origin is 'problem_record'.
  problem_id?: string
  // ServiceNow application context, when the ticket arrived with it. Drives
  // deterministic routing; absent means the AI repo-match tier decides.
  ci?: string
  business_service?: string
}

export interface JiraBoardResponse {
  project_key: string
  issues: JiraIssue[]
}

export interface TicketEvent {
  ts: string
  ticket_number: string
  actor: 'ai' | 'human' | 'system'
  action: string
  detail: string
}

export interface ScreenshotResponse {
  stage: 'before' | 'after'
  namespace: string
  image_base64: string
}

export interface AdhocAnalyzeResponse {
  label: string
  needs_clarification: boolean
  // Present only when needs_clarification is true — either about the CR
  // text itself or, once that's clear, about which connected GitLab repo
  // this is for (see api/routers/s3.py's analyze_adhoc for both gates).
  question?: string
  // Present only when needs_clarification is false.
  impact_analysis?: string
  assumptions?: string[]
  effort_estimate?: EffortEstimate
  // AI's best guess at the target repo once confident enough to stop
  // asking — null when no GitLab connection was available to check against,
  // and skipped entirely when `routing` already settled it deterministically.
  target_repo?: TargetRepo | null
  // Deterministic CI routing, run before the AI repo match.
  routing?: RouteDecision
}

export interface QuickChatResponse {
  label: string
  needs_clarification: boolean
  question?: string
  impact_analysis?: string
  effort_estimate?: EffortEstimate
  code_change_warranted?: boolean
  suggested_cr_summary?: string
}

export const s3Api = {
  // Changes whenever demo/reset_s3.sh (or equivalent) clears the server's
  // ticket-events log between rehearsals — used to invalidate the per-ticket
  // analysis/proposal state this console caches client-side (see S3.tsx's
  // saveTicketState), so a reset doesn't leave stale results on screen.
  resetMarker: () => request<{ marker: string }>('/api/s3/reset-marker'),
  cr: (tierName: string, targetId?: string | null) =>
    request<CrResponse>(
      `/api/s3/cr?tier_name=${encodeURIComponent(tierName)}` +
        (targetId ? `&target_id=${encodeURIComponent(targetId)}` : '')
    ),
  // A CR with a specific missing detail (e.g. an unstated field default)
  // comes back with needs_clarification: true and a follow-up question
  // instead of an analysis; resubmit with the engineer's answer as
  // `clarificationAnswer` (server keeps the transcript, same as
  // analyzeAdhoc below). `resetClarification` clears that server-side
  // history before this call.
  analyze: (
    tierName: string,
    targetId?: string | null,
    ticketNumber?: string,
    clarificationAnswer?: string,
    resetClarification = false
  ) =>
    request<AnalyzeApiResponse>('/api/s3/analyze', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
        clarification_answer: clarificationAnswer ?? null,
        reset_clarification: resetClarification,
      }),
    }),
  // For a ticket with no linked CR/target in this console (e.g. a cross-team
  // ticket for another application) — runs off the ticket's own text instead
  // of one of the two pinned CR templates, so there's no file_selection. A
  // vague ticket comes back with needs_clarification: true and a follow-up
  // question instead of an analysis; resubmit with the engineer's answer as
  // `crText` (server keeps the transcript, same as quickImpactChat below).
  // `resetClarification` clears that server-side history before this call.
  analyzeAdhoc: (
    crText: string,
    ticketNumber?: string,
    resetClarification = false,
    application?: { ci?: string; businessService?: string }
  ) =>
    request<AdhocAnalyzeResponse>('/api/s3/analyze-adhoc', {
      method: 'POST',
      body: JSON.stringify({
        cr_text: crText,
        ticket_number: ticketNumber ?? null,
        reset_clarification: resetClarification,
        ci: application?.ci ?? null,
        business_service: application?.businessService ?? null,
      }),
    }),
  // Deterministic tier only — resolves a ticket's CI to its owning team, Jira
  // project and repo with no model call. `needs_ai_fallback` in the response
  // means the ticket carried no usable CI and analyzeAdhoc's repo-match gate
  // should decide instead.
  route: (ci?: string, businessService?: string, ticketNumber?: string) =>
    request<RouteDecision>('/api/s3/route', {
      method: 'POST',
      body: JSON.stringify({
        ci: ci ?? null,
        business_service: businessService ?? null,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  // Resolves which registered target a ticket's CR belongs to, from the CR's
  // own text -- crFile names a bare filename under the repo's top-level
  // crs/ (the server reads it), so onboarding a new repo/target never means
  // hand-editing a ticket-key -> target_id table in this file.
  resolveTarget: (crFile: string, ticketNumber?: string) =>
    request<TargetResolveResponse>('/api/s3/target/resolve', {
      method: 'POST',
      body: JSON.stringify({
        cr_file: crFile,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  applications: () => request<ApplicationsResponse>('/api/s3/applications'),
  generate: (tierName: string, targetId?: string | null, ticketNumber?: string) =>
    request<GenerateResponse>('/api/s3/generate', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  revise: (proposalId: string, instruction: string) =>
    request<ReviseResponse>('/api/s3/revise', {
      method: 'POST',
      body: JSON.stringify({ proposal_id: proposalId, instruction }),
    }),
  // targetId names the feature branch apply opens before it writes anything.
  apply: (
    proposalId: string,
    ticketNumber?: string,
    filePath?: string,
    targetId?: string | null,
  ) =>
    request<ApplyResponse>('/api/s3/apply', {
      method: 'POST',
      body: JSON.stringify({
        proposal_id: proposalId,
        file_path: filePath ?? null,
        ticket_number: ticketNumber ?? null,
        target_id: targetId ?? null,
      }),
    }),
  // --- the source-control flow around Apply ---------------------------------
  // Commit and push are simulated: nothing here runs git or contacts a
  // remote. The commit gate lives on the server and reads the ticket's own
  // test results, so there is deliberately no "tests passed" flag to send
  // from here. Checkout is the exception — real when the server has
  // SCM_MODE=live set (branch creation only; see s3_enhancement/scm_live.py),
  // simulated otherwise. The server decides and reports which in `mode`.
  scmCheckout: (ticketNumber: string, targetId: string) =>
    request<ScmCheckoutResponse>('/api/s3/scm/checkout', {
      method: 'POST',
      body: JSON.stringify({ ticket_number: ticketNumber, target_id: targetId }),
    }),
  scmState: (proposalId: string, ticketNumber?: string) =>
    request<ScmResponse>(
      `/api/s3/scm?proposal_id=${encodeURIComponent(proposalId)}` +
        (ticketNumber ? `&ticket_number=${encodeURIComponent(ticketNumber)}` : ''),
    ),
  scmCommit: (
    proposalId: string,
    ticketNumber: string,
    targetId?: string | null,
    message?: string,
  ) =>
    request<ScmResponse>('/api/s3/scm/commit', {
      method: 'POST',
      body: JSON.stringify({
        proposal_id: proposalId,
        ticket_number: ticketNumber,
        target_id: targetId ?? null,
        message: message ?? null,
      }),
    }),
  scmPush: (proposalId: string, ticketNumber?: string) =>
    request<ScmResponse>('/api/s3/scm/push', {
      method: 'POST',
      body: JSON.stringify({
        proposal_id: proposalId,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  // Turn one file down, with an optional reason. Recorded to the ticket's
  // audit trail and enforced: apply-all skips it afterwards.
  reject: (proposalId: string, filePath: string, reason: string, ticketNumber?: string) =>
    request<RejectResponse>('/api/s3/reject', {
      method: 'POST',
      body: JSON.stringify({
        proposal_id: proposalId,
        file_path: filePath,
        reason,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  clearRejection: (proposalId: string, filePath: string, ticketNumber?: string) =>
    request<RejectResponse>('/api/s3/reject/clear', {
      method: 'POST',
      body: JSON.stringify({
        proposal_id: proposalId,
        file_path: filePath,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  // Put the working tree back as it was before this proposal was applied.
  // Omit filePath to revert everything it applied.
  revert: (proposalId: string, ticketNumber?: string, filePath?: string) =>
    request<RevertResponse>('/api/s3/revert', {
      method: 'POST',
      body: JSON.stringify({
        proposal_id: proposalId,
        file_path: filePath ?? null,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  designSync: (
    proposalId: string,
    appliedFiles: string[],
    ticketNumber?: string,
    targetId?: string,
  ) =>
    request<DesignSyncResponse>('/api/s3/design-sync', {
      method: 'POST',
      body: JSON.stringify({
        proposal_id: proposalId,
        applied_files: appliedFiles,
        ticket_number: ticketNumber ?? null,
        target_id: targetId ?? null,
      }),
    }),
  addFile: (proposalId: string, filePath: string, instruction: string, ticketNumber?: string) =>
    request<AddFileResponse>('/api/s3/add-file', {
      method: 'POST',
      body: JSON.stringify({
        proposal_id: proposalId,
        file_path: filePath,
        instruction,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  designDoc: (
    tierName: string,
    targetId?: string | null,
    ticketNumber?: string,
    downstreamApps?: string[]
  ) =>
    request<DesignDocResponse>('/api/s3/design-doc', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
        downstream_apps: downstreamApps ?? [],
      }),
    }),
  // Returns a file, not JSON, so it bypasses `request` — which parses every
  // response as JSON and would choke on PDF bytes. Errors still surface as
  // ApiError so the 503 "no chromium" fallback can be caught by status.
  designDocDocument: async (
    tierName: string,
    format: 'pdf' | 'html',
    targetId?: string | null,
    ticketNumber?: string,
    downstreamApps?: string[]
  ): Promise<Blob> => {
    const response = await fetch('/api/s3/design-doc/document', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
        downstream_apps: downstreamApps ?? [],
        format,
      }),
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new ApiError(response.status, body.detail ?? response.statusText)
    }
    return response.blob()
  },
  tests: (tierName: string, targetId?: string | null) =>
    request<TestsResponse>('/api/s3/tests', {
      method: 'POST',
      body: JSON.stringify({ tier_name: tierName, target_id: targetId ?? null }),
    }),
  testsScenarios: (tierName: string, targetId?: string | null, ticketNumber?: string) =>
    request<ScenariosResponse>('/api/s3/tests/scenarios', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  testsScenariosApprove: (
    tierName: string,
    scenarios: TestScenario[],
    targetId?: string | null,
    ticketNumber?: string
  ) =>
    request<ScenarioApprovalResponse>('/api/s3/tests/scenarios/approve', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
        scenarios,
      }),
    }),
  testsTraceability: (
    tierName: string,
    scenarios: TestScenario[],
    generatedCases: TestCaseResult[],
    regressionCases: TestCaseResult[],
    targetId?: string | null,
    ticketNumber?: string
  ) =>
    request<TraceabilityResponse>('/api/s3/tests/traceability', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
        scenarios,
        generated_cases: generatedCases,
        regression_cases: regressionCases,
      }),
    }),
  testsGenerate: (
    tierName: string,
    targetId?: string | null,
    ticketNumber?: string,
    scenarios?: TestScenario[] | null
  ) =>
    request<TestsGenerateResponse>('/api/s3/tests/generate', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
        scenarios: scenarios ?? null,
      }),
    }),
  testsRun: (tierName: string, targetId?: string | null, ticketNumber?: string) =>
    request<TestsRunResponse>('/api/s3/tests/run', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  testsRegression: (tierName: string, targetId?: string | null, ticketNumber?: string) =>
    request<RegressionRunResponse>('/api/s3/tests/regression', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  testsMutation: (tierName: string, targetId?: string | null, ticketNumber?: string) =>
    request<MutationCheckResponse>('/api/s3/tests/mutation', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  // proposalId lets the returned deployment plan name the branch and commit the
  // change went through, instead of leaving "deploy the change" to the reader.
  releaseNoteSet: (
    tierName: string,
    targetId?: string | null,
    ticketNumber?: string,
    downstreamApps?: string[],
    proposalId?: string | null,
  ) =>
    request<ReleaseNotesResponse2>('/api/s3/release/notes', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
        downstream_apps: downstreamApps ?? [],
        proposal_id: proposalId ?? null,
      }),
    }),
  releaseRecordAttach: (body: Record<string, unknown>) =>
    request<ReleaseAttachResponse>('/api/s3/release/attach', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  // File download, so it bypasses `request` for the same reason the design
  // doc export does — `request` parses every response as JSON.
  releaseRecord: async (body: Record<string, unknown>): Promise<Blob> => {
    const response = await fetch('/api/s3/release/record', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}))
      throw new ApiError(response.status, errorBody.detail ?? response.statusText)
    }
    return response.blob()
  },
  releaseNotes: (tierName: string, targetId?: string | null) =>
    request<ReleaseNotesResponse>('/api/s3/release-notes', {
      method: 'POST',
      body: JSON.stringify({ tier_name: tierName, target_id: targetId ?? null }),
    }),
  harnessLatest: () => request<HarnessResponse>('/api/s3/harness/latest'),
  gitlabProjects: () => request<GitlabProject[]>('/api/s3/gitlab/projects'),
  gitlabScope: (projectId: number | string, tierName: string) =>
    request<GitlabScopeResponse>(`/api/s3/gitlab/projects/${projectId}/scope`, {
      method: 'POST',
      body: JSON.stringify({ tier_name: tierName }),
    }),
  // A low/medium-confidence repo match comes back with needs_clarification:
  // true and a "is this the right repo?" question instead of a scoped
  // result; resubmit with `confirmedProjectId` set (from suggested_project.id
  // or a chosen alternate) to skip straight to scoping. Exactly one of
  // `tierName` (a pinned CR template) or `crText` (an ad-hoc ticket's own
  // text, no target linked in this console) should be given — same split as
  // analyze vs. analyzeAdhoc above.
  gitlabScopeAuto: (options: {
    tierName?: string
    crText?: string
    ticketNumber?: string
    confirmedProjectId?: string
  }) =>
    request<GitlabScopeAutoResponse>('/api/s3/gitlab/scope-auto', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: options.tierName ?? null,
        cr_text: options.crText ?? null,
        ticket_number: options.ticketNumber ?? null,
        confirmed_project_id: options.confirmedProjectId ?? null,
      }),
    }),
  quickImpactChat: (message: string, reset = false) =>
    request<QuickChatResponse>('/api/s3/chat/quick-impact', {
      method: 'POST',
      body: JSON.stringify({ message, reset }),
    }),
  crossTeamImpact: (tierName: string, targetId?: string | null, ticketNumber?: string) =>
    request<CrossTeamImpactResponse>('/api/s3/impact/cross-team', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  createCrossTeamTicket: (
    appName: string,
    summary: string,
    description: string,
    primaryTicketKey: string,
    assignee?: string
  ) =>
    request<CrossTeamTicketResponse>('/api/s3/jira/cross-team-ticket', {
      method: 'POST',
      body: JSON.stringify({
        app_name: appName,
        summary,
        description,
        primary_ticket_key: primaryTicketKey,
        assignee,
      }),
    }),
  assignTicket: (key: string, assignee: string) =>
    request<{ label: string; issue: JiraIssue }>('/api/s3/jira/assign-ticket', {
      method: 'POST',
      body: JSON.stringify({ key, assignee }),
    }),
  setTicketStatus: (key: string, status: string) =>
    request<{ label: string; issue: JiraIssue }>('/api/s3/jira/ticket-status', {
      method: 'POST',
      body: JSON.stringify({ key, status }),
    }),
  jiraDependencies: (primaryTicketKey: string) =>
    request<{ primary_ticket_key: string; dependencies: JiraIssue[] }>(
      `/api/s3/jira/dependencies?primary_ticket_key=${encodeURIComponent(primaryTicketKey)}`
    ),
  ticketEvents: (ticketNumber: string) =>
    request<{ ticket_number: string; events: TicketEvent[] }>(
      `/api/s3/ticket-events?ticket_number=${encodeURIComponent(ticketNumber)}`
    ),
  jiraBoard: () => request<JiraBoardResponse>('/api/s3/jira/board'),
  screenshot: (stage: 'before' | 'after') =>
    request<ScreenshotResponse>(`/api/s3/screenshots/${stage}`),
}

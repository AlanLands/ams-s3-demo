// Thin fetch wrappers over the FastAPI backend for S3 — Enhancement Delivery.
// Mirrors the api/routers/s3.py response shapes exactly — no client-side
// business logic, same "thin view" convention as api.ts's s1Api/s2Api.

import { request } from './api'

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

export interface AnalyzeResponse {
  label: string
  impact_analysis: string
  effort_estimate: EffortEstimate
  // Absent for analyze-adhoc's ad-hoc tickets — those have no in-console
  // target/codebase to select files from (see s3Api.analyzeAdhoc).
  file_selection?: FileSelection
}

export interface TokenPanel {
  scoped_input_tokens: number | null
  scoped_output_tokens: number | null
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

export interface ApplyResponse {
  proposal_id: string
  applied_files: string[]
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
  token_panel: TokenPanel
}

export interface ReleaseNotesResponse {
  label: string
  release_notes: string
}

export interface DesignDocResponse {
  label: string
  design_doc: string
}

export interface HarnessStatus {
  tier_name: string
  harness: string
  used_replay: boolean
  duration_s: number
  [key: string]: unknown
}

export interface HarnessResponse {
  label: string
  status: HarnessStatus
  diff_text: string
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

export interface GitlabScopeAutoResponse extends GitlabScopeResponse {
  label: string
  suggested_project: SuggestedProject
  alternates: RepoMatch[]
}

export interface CrossTeamImpact {
  app_name: string
  reason: string
  suggested_summary: string
}

export interface CrossTeamImpactResponse {
  label: string
  impacts: CrossTeamImpact[]
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
  analyze: (tierName: string, targetId?: string | null, ticketNumber?: string) =>
    request<AnalyzeResponse>('/api/s3/analyze', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  // For a ticket with no linked CR/target in this console (e.g. a cross-team
  // ticket for another application) — runs off the ticket's own text instead
  // of one of the two pinned CR templates, so there's no file_selection.
  analyzeAdhoc: (crText: string, ticketNumber?: string) =>
    request<AnalyzeResponse>('/api/s3/analyze-adhoc', {
      method: 'POST',
      body: JSON.stringify({ cr_text: crText, ticket_number: ticketNumber ?? null }),
    }),
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
  apply: (proposalId: string, ticketNumber?: string, filePath?: string) =>
    request<ApplyResponse>('/api/s3/apply', {
      method: 'POST',
      body: JSON.stringify({
        proposal_id: proposalId,
        file_path: filePath ?? null,
        ticket_number: ticketNumber ?? null,
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
  designDoc: (tierName: string, targetId?: string | null, ticketNumber?: string) =>
    request<DesignDocResponse>('/api/s3/design-doc', {
      method: 'POST',
      body: JSON.stringify({
        tier_name: tierName,
        target_id: targetId ?? null,
        ticket_number: ticketNumber ?? null,
      }),
    }),
  tests: (tierName: string, targetId?: string | null) =>
    request<TestsResponse>('/api/s3/tests', {
      method: 'POST',
      body: JSON.stringify({ tier_name: tierName, target_id: targetId ?? null }),
    }),
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
  gitlabScopeAuto: (tierName: string) =>
    request<GitlabScopeAutoResponse>('/api/s3/gitlab/scope-auto', {
      method: 'POST',
      body: JSON.stringify({ tier_name: tierName }),
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

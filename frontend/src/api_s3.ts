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
  file_selection: FileSelection
}

export interface TokenPanel {
  scoped_input_tokens: number | null
  scoped_output_tokens: number | null
  naive_input_tokens_estimate?: number
}

export interface GenerateResponse {
  label: string
  tier_name: string
  diff_text: string
  files_changed: string[]
  used_replay: boolean
  file_selection: FileSelection
  token_panel: TokenPanel
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

export const s3Api = {
  cr: (tierName: string) =>
    request<CrResponse>(`/api/s3/cr?tier_name=${encodeURIComponent(tierName)}`),
  analyze: (tierName: string) =>
    request<AnalyzeResponse>('/api/s3/analyze', {
      method: 'POST',
      body: JSON.stringify({ tier_name: tierName }),
    }),
  generate: (tierName: string) =>
    request<GenerateResponse>('/api/s3/generate', {
      method: 'POST',
      body: JSON.stringify({ tier_name: tierName }),
    }),
  tests: (tierName: string) =>
    request<TestsResponse>('/api/s3/tests', {
      method: 'POST',
      body: JSON.stringify({ tier_name: tierName }),
    }),
  releaseNotes: (tierName: string) =>
    request<ReleaseNotesResponse>('/api/s3/release-notes', {
      method: 'POST',
      body: JSON.stringify({ tier_name: tierName }),
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
}

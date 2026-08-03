// Thin fetch wrappers over the /api/admin router — the presenter's housekeeping
// surface (reset, services, logs, repo onboarding). Mirrors the frozen contract
// in ADMIN_API_CONTRACT.md exactly, same "thin view" convention as api.ts and
// api_s3.ts: no client-side business logic, no derived state, no defaults that
// would let the UI claim something the server did not say.
//
// Every route here is manager-only server-side; a non-manager gets 403. The
// route guard in App.tsx is a convenience, not the enforcement.

import { request } from './api'

export interface AdminService {
  id: string
  label: string
  port: number
  // Re-checked TCP connect on localhost:port at request time — not a cached
  // "we started it once" flag, which is why the UI can trust it after an action.
  up: boolean
  command: string
}

export interface AdminTarget {
  target_id: string
  display_name: string
  repo: string
  cr: string
  discovered: boolean
  has_recording: boolean
}

export interface AdminStateCounts {
  staged_proposals: number
  ticket_events: number
  llm_cache_entries: number
  generated_test_files: string[]
}

export interface AdminStatus {
  branch: string
  is_default_branch: boolean
  dirty_file_count: number
  // The gate the UI must honour: false means a source-restoring reset would
  // discard uncommitted work and the server will answer 409.
  reset_safe: boolean
  reset_blocked_reason: string | null
  services: AdminService[]
  targets: AdminTarget[]
  state: AdminStateCounts
}

// No "everything" scope by design — each reset is an explicit act.
export type ResetScope =
  | 'policycore'
  | 'claimsportal'
  | 'enroldirect'
  | 'tickets'
  | 'logs'
  | 'proposals'
  | 'caches'

export interface ResetPreview {
  scope: ResetScope
  restores: string[]
  deletes: string[]
  // Files this scope would revert that currently have uncommitted changes —
  // i.e. the work that would actually be lost.
  dirty: string[]
}

export interface ResetResult {
  scope: ResetScope
  ran: string[]
  detail: string
  simulated: boolean
}

export type ServiceAction = 'start' | 'stop' | 'restart'

export interface ServiceActionResult {
  id: string
  action: ServiceAction
  // False when the console could not do it itself. `command` is then the thing
  // to run by hand — it must be shown, not swallowed into a generic error.
  ok: boolean
  detail: string
  command: string
}

export interface OnboardRequest {
  name: string
  display_name: string
  target_id: string
  cache_namespace: string
  cr: string
  core_files: string[]
  codegen_allowlist: string[]
  testgen_allowlist: string[]
  regression_paths: string[]
  post_apply_command: string[]
  dry_run: boolean
}

export interface OnboardResult {
  ok: boolean
  // Both are null on the terminal rejection path — an unsafe repo name leaves
  // no path to report and no manifest to have built. Rendering has to handle
  // that rather than printing "null" at the operator.
  manifest_path: string | null
  manifest: Record<string, unknown> | null
  // False for a dry run. A written manifest still needs a console restart
  // before it is registered — that arrives in `warnings`.
  written: boolean
  warnings: string[]
  errors: string[]
}

export interface LogFile {
  path: string
  bytes: number
  lines: number
}

export interface LogsResponse {
  files: LogFile[]
}

export interface LogsDeleteResult {
  deleted: string[]
  bytes_freed: number
}

export const adminApi = {
  status: () => request<AdminStatus>('/api/admin/status'),
  resetPreview: (scope: ResetScope) =>
    request<ResetPreview>(`/api/admin/reset/${scope}/preview`),
  reset: (scope: ResetScope) =>
    request<ResetResult>('/api/admin/reset', {
      method: 'POST',
      body: JSON.stringify({ scope, confirm: true }),
    }),
  serviceAction: (id: string, action: ServiceAction) =>
    request<ServiceActionResult>(`/api/admin/services/${id}/${action}`, { method: 'POST' }),
  onboardRepo: (payload: OnboardRequest) =>
    request<OnboardResult>('/api/admin/repos/onboard', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  logs: () => request<LogsResponse>('/api/admin/logs'),
  clearLogs: () => request<LogsDeleteResult>('/api/admin/logs', { method: 'DELETE' }),
}

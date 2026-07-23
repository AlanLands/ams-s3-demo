// Thin fetch wrappers over the FastAPI backend. Mirrors api/auth.py and
// api/routers/s1.py's response shapes exactly — no client-side business
// logic, same "thin view" convention the Streamlit files followed.

import type { TimelineEvent } from './Timeline'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, body.detail ?? response.statusText)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export interface Identity {
  name: string
  role: 'engineer' | 'manager'
  group: string | null
}

export const authApi = {
  roster: () => request<string[]>('/api/auth/roster'),
  login: (name: string, passcode: string) =>
    request<Identity>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ name, passcode }),
    }),
  logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),
  me: () => request<Identity>('/api/auth/me'),
}

export interface Incident {
  number: string
  application: string
  category: string
  subcategory: string
  priority: string
  short_description: string
  description: string
  sla_breached: boolean
  [key: string]: unknown
}

export interface TeamBandwidthRow {
  engineer: string
  open_tickets: number
  weighted_bandwidth: number
}

export interface MyQueue {
  engineer: string
  group: string | null
  assigned_count: number
  weighted_bandwidth: number
  sla_at_risk: number
  incidents: Incident[]
  team_bandwidth: TeamBandwidthRow[]
}

export interface ManagerRollup {
  open_all_groups: number
  sla_at_risk_all_groups: number
  groups: { group: string; team_bandwidth: TeamBandwidthRow[] }[]
}

export interface TriageStageDetail {
  ai_category: string
  ai_priority: string
  final_category: string
  final_priority: string
  reasoning: string
  rule_match: {
    rule_name: string
    suggested_category: string
    suggested_priority: string
    why: string
  } | null
  agreement: 'agree' | 'deviation' | 'ai_only'
  deviating_fields: string[]
}

export interface PipelineResult {
  status: 'quality_gate_failed' | 'needs_arbitration' | 'completed'
  quality_gate: {
    label: string
    investigable: boolean
    score: number
    reasoning: string
    missing_info: string[]
  }
  triage?: TriageStageDetail
  routing?: { assignment_group: string; citation: string }
  engineer_assignment?: { engineer: string; weighted_bandwidth: number }
  similar_incidents?: {
    signals: { incident_number: string; similarity_score: number; resolution_notes: string }[]
  }
  resolution?: {
    label: string
    resolution_steps: string
    work_note: string
    requestor_email: string
  }
}

export interface BacklogEntry {
  cluster_id: string
  representative_description: string
  size: number
  breach_count: number
  breach_rate: number
  top_application: string
  ai_summary: string | null
  ai_summary_error: string | null
  label: string
}

export interface Backlog {
  recurring_clusters: number
  total_linked_incidents: number
  total_sla_breaches: number
  entries: BacklogEntry[]
}

export interface ClusterSummary {
  cluster_id: string
  incident_numbers: string[]
  representative_description: string
  size: number
}

export interface ClusterDetail {
  cluster: ClusterSummary
  breach_count: number
  breach_rate: number
  top_application: string
}

export interface ClusterPipeline {
  status: 'completed' | 'unavailable'
  error?: string
  label?: string
  problem_ticket?: {
    problem_id: string
    summary: string
    affected_incidents: string[]
    mode: string
    is_pre_existing: boolean
  }
  rca?: {
    narrative: string
    cited_problem_id: string
    cited_known_error_id: string
  }
  fix_recommendation?: {
    ranked_options: string[]
    impact_estimate: string
    maturity_caveat: string
    cited_incidents: string[][]
  }
  correlation?: {
    tiers: {
      name: string
      alerts: { ci: string; incident_count: number; summary: string }[]
    }[]
    root_cause_chain: string
  }
}

export interface ApplyFixResult {
  executed: boolean
  applied_option: string | null
  outcome: string
  approved_by: string | null
  label: string
}

export const s2Api = {
  backlog: () => request<Backlog>('/api/s2/backlog'),
  clusters: () => request<ClusterSummary[]>('/api/s2/clusters'),
  clusterDetail: (clusterId: string) => request<ClusterDetail>(`/api/s2/clusters/${clusterId}`),
  clusterPipeline: (clusterId: string) =>
    request<ClusterPipeline>(`/api/s2/clusters/${clusterId}/pipeline`),
  review: (clusterId: string, problemId: string) =>
    request<{ reviewed: boolean }>(`/api/s2/clusters/${clusterId}/review`, {
      method: 'POST',
      body: JSON.stringify({ problem_id: problemId }),
    }),
  applyFix: (clusterId: string, problemId: string, optionIndex: number) =>
    request<ApplyFixResult>(`/api/s2/clusters/${clusterId}/apply-fix`, {
      method: 'POST',
      body: JSON.stringify({ problem_id: problemId, option_index: optionIndex }),
    }),
  timeline: (problemId: string) => request<TimelineEvent[]>(`/api/s2/tickets/${problemId}/timeline`),
  createIncident: (payload: {
    application: string
    category: string
    short_description: string
    description: string
  }) => request<Record<string, unknown>>('/api/s2/incidents', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
}

export const s1Api = {
  myQueue: () => request<MyQueue>('/api/s1/queue'),
  managerRollup: () => request<ManagerRollup>('/api/s1/manager-rollup'),
  runPipeline: (number: string) =>
    request<PipelineResult>(`/api/s1/incidents/${number}/pipeline`, { method: 'POST' }),
  arbitrate: (number: string, choice: 'keep_rule' | 'accept_ai') =>
    request<PipelineResult>(`/api/s1/incidents/${number}/arbitrate`, {
      method: 'POST',
      body: JSON.stringify({ choice }),
    }),
  approve: (number: string) =>
    request<{ approved: boolean }>(`/api/s1/incidents/${number}/approve`, { method: 'POST' }),
  timeline: (number: string) =>
    request<TimelineEvent[]>(`/api/s1/incidents/${number}/timeline`),
}

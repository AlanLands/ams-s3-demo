import { useCallback, useEffect, useRef, useState } from 'react'
import { Chip } from './s3/components'
import { Banner } from './admin/primitives'
import ServicesCard from './admin/ServicesCard'
import ResetCard from './admin/ResetCard'
import LogsCard from './admin/LogsCard'
import OnboardCard from './admin/OnboardCard'
import { pluralise } from './admin/util'
import {
  adminApi,
  type AdminStatus,
  type OnboardRequest,
  type ResetScope,
  type ServiceAction,
} from '../api_admin'

const POLL_INTERVAL_MS = 15000

/**
 * Demo control — the presenter's housekeeping, which until now meant leaving
 * the console for a terminal mid-presentation.
 *
 * Reading order is by how often a job is done, not by how alarming it is:
 * run state, then the services (checked before every run), then reset (twice a
 * day), then logs, then onboarding (rarely, and never during a demo). Severity
 * is expressed in how hard a control is to fire, not in where it sits.
 *
 * This component owns every *mutating* call so that one place can re-read the
 * status afterwards and announce the result; the children own their own reads
 * (reset previews, the log inventory, onboarding dry runs), which change
 * nothing and need no coordination.
 */
export default function Admin() {
  const [status, setStatus] = useState<AdminStatus | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [announcement, setAnnouncement] = useState('')
  // Bumped after every mutation so the children holding their own reads (the
  // log inventory) re-fetch instead of describing a world that has moved on.
  const [refreshKey, setRefreshKey] = useState(0)
  // A ref, not state: the poll only needs to *read* it, and making it state
  // would re-arm the interval on every action.
  const busyRef = useRef(false)

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const next = await adminApi.status()
      setStatus(next)
      setCheckedAt(new Date())
      setLoadError(null)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error))
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Service state is the one thing here that changes without the console doing
  // it — a target app can die on its own. Poll quietly, skip while a mutation
  // is in flight (its own refresh is more current), and skip on a hidden tab.
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'visible' || busyRef.current) return
      void refresh(true)
    }, POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [refresh])

  const runMutation = useCallback(
    async <T,>(work: () => Promise<T>, describe: (result: T) => string): Promise<T> => {
      busyRef.current = true
      setAnnouncement('')
      try {
        const result = await work()
        setAnnouncement(describe(result))
        setRefreshKey((previous) => previous + 1)
        await refresh(true)
        return result
      } finally {
        busyRef.current = false
      }
    },
    [refresh]
  )

  const handleServiceAction = useCallback(
    (id: string, action: ServiceAction) =>
      runMutation(
        () => adminApi.serviceAction(id, action),
        // The server re-checks the port after acting, so its own wording is the
        // only claim worth repeating. Nothing here upgrades a failure.
        (result) =>
          result.ok
            ? `${result.id}: ${result.detail}`
            : `${result.id}: could not ${result.action} — a manual command is shown on the row.`
      ),
    [runMutation]
  )

  const handleReset = useCallback(
    (scope: ResetScope) =>
      runMutation(
        () => adminApi.reset(scope),
        (result) => `${result.detail}${result.simulated ? ' (simulated)' : ''}`
      ),
    [runMutation]
  )

  const handleClearLogs = useCallback(
    () =>
      runMutation(
        () => adminApi.clearLogs(),
        (result) => `Cleared ${pluralise(result.deleted.length, 'log file')}.`
      ),
    [runMutation]
  )

  const handleOnboard = useCallback(
    (payload: OnboardRequest) =>
      runMutation(
        () => adminApi.onboardRepo(payload),
        (result) =>
          result.written
            ? `Manifest written to ${result.manifest_path ?? 'disk'}. Not active until the console restarts.`
            : 'Manifest not written — see the errors on the form.'
      ),
    [runMutation]
  )

  return (
    <div className="ams-admin-page">
      <span className="ams-eyebrow">MapleSure Insurance · AMS Console · Admin</span>
      <div className="ams-admin-head">
        <div>
          <h1 className="ams-admin-title">Environment control</h1>
          <p className="ams-s3-summary">
            Reset environment state, clear logs, run the target applications, and register a
            new repo — without leaving the console for a terminal.
          </p>
        </div>
        <div className="ams-admin-row-actions">
          <span className="ams-admin-count-badge">
            {checkedAt ? `Checked ${checkedAt.toLocaleTimeString()}` : 'Not checked yet'}
          </span>
          <button
            type="button"
            className="ams-button-secondary ams-button-compact"
            onClick={() => void refresh()}
            disabled={loading}
          >
            {loading ? 'Checking…' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* One live region for the whole page. Every mutation reports through it,
          so a keyboard or screen-reader user hears the outcome even when the
          visible result lands in a card they are not focused on. */}
      <div role="status" aria-live="polite" className="ams-admin-live">
        {announcement}
      </div>

      {loadError && (
        <Banner tone="danger" title="Could not read the admin status">
          <p className="ams-admin-banner-body">{loadError}</p>
          <p className="ams-admin-banner-body">
            Nothing on this page is safe to act on until this succeeds.
          </p>
        </Banner>
      )}

      {loading && !status && <p className="ams-muted">Loading…</p>}

      {status && (
        <>
          <div className="ams-card ams-admin-section">
            <div className="ams-admin-context">
              <Chip tone={status.reset_safe ? 'pass' : 'warn'}>
                {status.reset_safe ? 'Source reset available' : 'Source reset blocked'}
              </Chip>
              <span className="ams-admin-branch">
                Branch <code>{status.branch}</code>
              </span>
              {status.is_default_branch ? (
                <Chip tone="neutral">Default branch</Chip>
              ) : (
                <Chip tone="warn">Not the default branch</Chip>
              )}
            </div>
            <p className="ams-field-hint">
              Resets restore from this branch's HEAD, so what a reset returns you to is
              whatever this branch has committed.
            </p>
            <div className="ams-metric-row ams-admin-strip">
              <div className="ams-metric-tile">
                <div className="ams-metric-label">Uncommitted files</div>
                <div className="ams-metric-value">{status.dirty_file_count}</div>
              </div>
              <div className="ams-metric-tile">
                <div className="ams-metric-label">Staged proposals</div>
                <div className="ams-metric-value">{status.state.staged_proposals}</div>
              </div>
              <div className="ams-metric-tile">
                <div className="ams-metric-label">Ticket events</div>
                <div className="ams-metric-value">{status.state.ticket_events}</div>
              </div>
              <div className="ams-metric-tile">
                <div className="ams-metric-label">Cached responses</div>
                <div className="ams-metric-value">{status.state.llm_cache_entries}</div>
              </div>
              <div className="ams-metric-tile">
                <div className="ams-metric-label">Generated tests</div>
                <div className="ams-metric-value">
                  {status.state.generated_test_files.length}
                </div>
              </div>
            </div>
            {status.state.generated_test_files.length > 0 && (
              <details className="ams-admin-details">
                <summary>
                  Generated test files ({status.state.generated_test_files.length})
                </summary>
                <ul className="ams-admin-files">
                  {status.state.generated_test_files.map((path) => (
                    <li key={path}>{path}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>

          <ServicesCard services={status.services} onAction={handleServiceAction} />
          <ResetCard status={status} onReset={handleReset} />
          <LogsCard refreshKey={refreshKey} onClear={handleClearLogs} />
          <OnboardCard targets={status.targets} onWrite={handleOnboard} />
        </>
      )}
    </div>
  )
}

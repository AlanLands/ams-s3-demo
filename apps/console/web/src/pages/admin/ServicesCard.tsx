import { useState } from 'react'
import { Chip } from '../s3/components'
import { AdminSection, Banner, CopyableCommand } from './primitives'
import type { AdminService, ServiceAction, ServiceActionResult } from '../../api_admin'

interface Outcome {
  result?: ServiceActionResult
  error?: string
}

/**
 * The target applications, and the controls for them.
 *
 * Placed above the reset section on purpose: "is EnrolDirect actually up?" is
 * the question a presenter asks every few minutes, and reset is the one they
 * ask twice a day. Frequency, not severity, decides reading order — severity
 * decides how hard the control is to fire.
 *
 * The row's own up/down chip is the authority, not the last action's wording:
 * the endpoint re-checks the port after acting, and the parent refetches
 * status, so a "Started" that did not take shows as still down within the same
 * render. Where the server says `ok: false`, the fallback command is rendered
 * verbatim and copyable rather than dressed up as an error.
 */
export default function ServicesCard({
  services,
  onAction,
}: {
  services: AdminService[]
  onAction: (id: string, action: ServiceAction) => Promise<ServiceActionResult>
}) {
  const [pending, setPending] = useState<string | null>(null)
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({})

  const upCount = services.filter((service) => service.up).length

  async function run(service: AdminService, action: ServiceAction) {
    setPending(`${service.id}:${action}`)
    setOutcomes((previous) => ({ ...previous, [service.id]: {} }))
    try {
      const result = await onAction(service.id, action)
      setOutcomes((previous) => ({ ...previous, [service.id]: { result } }))
    } catch (error) {
      setOutcomes((previous) => ({
        ...previous,
        [service.id]: { error: error instanceof Error ? error.message : String(error) },
      }))
    } finally {
      setPending(null)
    }
  }

  return (
    <AdminSection
      title="Target applications"
      description={
        <>
          The applications S3 runs its user stories against. State is a live port
          check on this host, re-taken after every action — not a memory of what
          was last started.
        </>
      }
      actions={
        <span className="ams-admin-count-badge">
          {upCount} of {services.length} up
        </span>
      }
    >
      <div className="ams-admin-list">
        {services.length === 0 && <p className="ams-muted">No target applications registered.</p>}
        {services.map((service) => {
          const outcome = outcomes[service.id] ?? {}
          const busy = pending?.startsWith(`${service.id}:`) ?? false
          return (
            <div className="ams-admin-row" key={service.id}>
              <div className="ams-admin-row-main">
                <div className="ams-admin-row-title">
                  {service.label}
                  <Chip tone={service.up ? 'pass' : 'neutral'}>
                    {service.up ? 'Up' : 'Not running'}
                  </Chip>
                </div>
                <p className="ams-admin-row-detail">
                  Port {service.port} · <code>{service.id}</code>
                </p>
                {outcome.result && (
                  <Banner
                    tone={outcome.result.ok ? 'good' : 'warn'}
                    title={
                      outcome.result.ok
                        ? `${outcome.result.action} succeeded`
                        : `The console could not ${outcome.result.action} this service`
                    }
                  >
                    <p className="ams-admin-banner-body">{outcome.result.detail}</p>
                    {!outcome.result.ok && outcome.result.command && (
                      <>
                        <p className="ams-admin-banner-body">Run this by hand instead:</p>
                        <CopyableCommand command={outcome.result.command} />
                      </>
                    )}
                  </Banner>
                )}
                {outcome.error && (
                  <Banner tone="danger" title="Request failed">
                    <p className="ams-admin-banner-body">{outcome.error}</p>
                  </Banner>
                )}
              </div>
              {/* Only the actions that mean something in the current state: a
                  "Stop" on a service that is already down is a button whose
                  only possible outcome is a confusing message. */}
              <div className="ams-admin-row-actions">
                {service.up ? (
                  <>
                    <button
                      type="button"
                      className="ams-button-secondary ams-button-compact"
                      disabled={busy}
                      onClick={() => run(service, 'restart')}
                    >
                      {pending === `${service.id}:restart` ? 'Restarting…' : 'Restart'}
                    </button>
                    <button
                      type="button"
                      className="ams-button-secondary ams-button-compact"
                      disabled={busy}
                      onClick={() => run(service, 'stop')}
                    >
                      {pending === `${service.id}:stop` ? 'Stopping…' : 'Stop'}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="ams-button ams-button-compact"
                    disabled={busy}
                    onClick={() => run(service, 'start')}
                  >
                    {pending === `${service.id}:start` ? 'Starting…' : 'Start'}
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </AdminSection>
  )
}

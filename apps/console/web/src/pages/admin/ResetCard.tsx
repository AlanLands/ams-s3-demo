import { useCallback, useEffect, useState } from 'react'
import { Chip } from '../s3/components'
import { AdminSection, Banner, ConfirmDialog, PathList } from './primitives'
import { pluralise } from './util'
import { adminApi, type AdminStatus, type ResetPreview, type ResetScope } from '../../api_admin'

interface ScopeCopy {
  scope: ResetScope
  title: string
  detail: string
}

// Source-restoring scopes. These are the ones `reset_safe` gates, because they
// put files back and any uncommitted edit to those files goes with them.
const SOURCE_SCOPES: ScopeCopy[] = [
  {
    scope: 'policycore',
    title: 'PolicyCore source',
    detail: 'Puts the MapleSure portal target app back to the baseline the story starts from.',
  },
  {
    scope: 'claimsportal',
    title: 'ClaimsPortal source',
    detail: 'Puts both ClaimsPortal services back to the baseline the story starts from.',
  },
  {
    scope: 'enroldirect',
    title: 'EnrolDirect source',
    detail: 'Puts the enrolment channel back to the baseline the story starts from.',
  },
]

// Delete-only scopes: generated state, no source restored, so they stay
// available even when a source reset is blocked.
const STATE_SCOPES: ScopeCopy[] = [
  {
    scope: 'tickets',
    title: 'Ticket board',
    detail: 'Returns every ticket to its first version by clearing the recorded events.',
  },
  {
    scope: 'proposals',
    title: 'Staged proposals',
    detail: 'Clears what S3 has generated but not applied, including the modelled branch state.',
  },
  {
    scope: 'caches',
    title: 'Model response cache',
    detail: 'Clears cached model responses. Check the preview before running this offline.',
  },
]

/**
 * Reset.
 *
 * Every scope is one row with one control, and that control opens a review
 * dialog — it never resets. Reaching the destructive act requires reading the
 * preview it opens on and then typing the scope name, which is the difference
 * between a deliberate reset and a mis-click during a demo.
 *
 * The preview is fetched when the dialog opens rather than eagerly for all
 * seven scopes: seven git-status walks on page load is a slow first paint for
 * information nobody has asked for yet. What matters is that it is on screen
 * *before* the confirm can be typed, and `ConfirmDialog` enforces that with
 * `ready`.
 */
export default function ResetCard({
  status,
  onReset,
}: {
  status: AdminStatus
  onReset: (scope: ResetScope) => Promise<unknown>
}) {
  const [openScope, setOpenScope] = useState<ResetScope | null>(null)
  const [previews, setPreviews] = useState<Partial<Record<ResetScope, ResetPreview>>>({})
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [resetError, setResetError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const loadPreview = useCallback(async (scope: ResetScope) => {
    setPreviewError(null)
    try {
      const preview = await adminApi.resetPreview(scope)
      setPreviews((previous) => ({ ...previous, [scope]: preview }))
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : String(error))
    }
  }, [])

  useEffect(() => {
    if (openScope) void loadPreview(openScope)
  }, [openScope, loadPreview])

  const isSourceScope = (scope: ResetScope) =>
    SOURCE_SCOPES.some((entry) => entry.scope === scope)

  function renderRow(entry: ScopeCopy) {
    const preview = previews[entry.scope]
    const blocked = isSourceScope(entry.scope) && !status.reset_safe
    return (
      <div className="ams-admin-row" key={entry.scope}>
        <div className="ams-admin-row-main">
          <div className="ams-admin-row-title">
            {entry.title}
            {blocked && <Chip tone="warn">Blocked</Chip>}
            {preview && preview.dirty.length > 0 && (
              <Chip tone="fail">
                {pluralise(preview.dirty.length, 'file')} with uncommitted changes
              </Chip>
            )}
            {preview && preview.dirty.length === 0 && <Chip tone="pass">Nothing uncommitted</Chip>}
          </div>
          <p className="ams-admin-row-detail">{entry.detail}</p>
        </div>
        <div className="ams-admin-row-actions">
          <button
            type="button"
            className="ams-button-secondary ams-button-compact"
            onClick={() => {
              setResetError(null)
              setOpenScope(entry.scope)
            }}
          >
            Review and reset…
          </button>
        </div>
      </div>
    )
  }

  const openCopy = openScope
    ? [...SOURCE_SCOPES, ...STATE_SCOPES].find((entry) => entry.scope === openScope)
    : undefined
  const openPreview = openScope ? previews[openScope] : undefined
  const openBlocked = openScope !== null && isSourceScope(openScope) && !status.reset_safe

  return (
    <AdminSection
      title="Reset environment state"
      tone="danger"
      description={
        <>
          Each scope is separate and explicit — there is no "reset everything".
          Nothing runs until you have read what it changes and typed the scope
          name.
        </>
      }
    >
      {!status.reset_safe && (
        <Banner tone="warn" title="Source resets are unavailable right now">
          <p className="ams-admin-banner-body">
            {status.reset_blocked_reason ??
              'The working tree has uncommitted changes that a reset would discard.'}
          </p>
          <p className="ams-admin-banner-body">
            The generated-state scopes below are unaffected — they delete state this
            console produced, and restore no source.
          </p>
        </Banner>
      )}

      <h3 className="ams-admin-group-title">Restore target app source</h3>
      <div className="ams-admin-list">{SOURCE_SCOPES.map(renderRow)}</div>

      <h3 className="ams-admin-group-title">Clear generated state</h3>
      <div className="ams-admin-list">{STATE_SCOPES.map(renderRow)}</div>
      <p className="ams-field-hint">
        Log files are listed and cleared in the Logs section below.
      </p>

      {openScope && openCopy && (
        <ConfirmDialog
          title={`Reset: ${openCopy.title}`}
          subtitle={
            <>
              Scope <code>{openScope}</code> · branch <code>{status.branch}</code>
            </>
          }
          confirmWord={openScope}
          confirmLabel={`Reset ${openCopy.title.toLowerCase()}`}
          ready={!!openPreview}
          busy={busy}
          blockedReason={
            openBlocked
              ? (status.reset_blocked_reason ??
                'This reset restores source and the working tree has uncommitted changes.')
              : null
          }
          error={resetError}
          onClose={() => {
            setOpenScope(null)
            setResetError(null)
          }}
          onConfirm={async () => {
            setBusy(true)
            setResetError(null)
            try {
              await onReset(openScope)
              // Drop the cached preview: it described the state that has just
              // stopped being true, and leaving it would show a stale dirty
              // count on the row behind the dialog.
              setPreviews((previous) => ({ ...previous, [openScope]: undefined }))
              setOpenScope(null)
            } catch (error) {
              setResetError(error instanceof Error ? error.message : String(error))
            } finally {
              setBusy(false)
            }
          }}
        >
          <p className="ams-admin-banner-body">{openCopy.detail}</p>
          {previewError && (
            <Banner tone="danger" title="Could not load the preview">
              <p className="ams-admin-banner-body">{previewError}</p>
            </Banner>
          )}
          {!openPreview && !previewError && <p className="ams-muted">Loading the preview…</p>}
          {openPreview && (
            <>
              {openPreview.dirty.length > 0 && (
                <Banner
                  tone="danger"
                  title={`${pluralise(openPreview.dirty.length, 'file')} with uncommitted changes would be discarded`}
                >
                  <p className="ams-admin-banner-body">
                    These are edits that exist nowhere else. There is no undo from this
                    console.
                  </p>
                </Banner>
              )}
              <PathList
                label="Uncommitted — would be discarded"
                paths={openPreview.dirty}
                tone="danger"
              />
              <PathList
                label="Restored to baseline"
                paths={openPreview.restores}
                emptyLabel="Nothing is restored — this scope only deletes."
              />
              <PathList
                label="Deleted"
                paths={openPreview.deletes}
                emptyLabel="Nothing is deleted."
              />
            </>
          )}
        </ConfirmDialog>
      )}
    </AdminSection>
  )
}

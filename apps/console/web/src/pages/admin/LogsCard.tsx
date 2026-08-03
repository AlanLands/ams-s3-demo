import { useCallback, useEffect, useState } from 'react'
import { AdminSection, Banner, ConfirmDialog } from './primitives'
import { formatBytes, pluralise } from './util'
import { adminApi, type LogFile, type LogsDeleteResult } from '../../api_admin'

/**
 * Logs.
 *
 * The inventory is the preview here — path, size and line count per file is
 * strictly more than the reset preview's bare path list, so the confirm dialog
 * shows the same table rather than a second, weaker description of the same
 * files. One job, one control, one thing to read before it fires.
 *
 * `refreshKey` bumps whenever the page runs any other mutation, because a reset
 * of the ticket board deletes a file listed here and a stale row would offer to
 * delete something already gone.
 */
export default function LogsCard({
  refreshKey,
  onClear,
}: {
  refreshKey: number
  onClear: () => Promise<LogsDeleteResult>
}) {
  const [files, setFiles] = useState<LogFile[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [clearError, setClearError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<LogsDeleteResult | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const response = await adminApi.logs()
      setFiles(response.files)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  const totalBytes = (files ?? []).reduce((sum, file) => sum + file.bytes, 0)
  const empty = files !== null && files.length === 0

  const table = (
    <table className="ams-admin-table">
      <caption className="ams-admin-table-caption">
        Log files on disk, newest inventory taken on load.
      </caption>
      <thead>
        <tr>
          <th scope="col">File</th>
          <th scope="col" className="ams-admin-num">
            Lines
          </th>
          <th scope="col" className="ams-admin-num">
            Size
          </th>
        </tr>
      </thead>
      <tbody>
        {(files ?? []).map((file) => (
          <tr key={file.path}>
            <td>
              <code>{file.path}</code>
            </td>
            <td className="ams-admin-num">{file.lines.toLocaleString()}</td>
            <td className="ams-admin-num">{formatBytes(file.bytes)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )

  return (
    <AdminSection
      title="Logs"
      tone="danger"
      description="What the console and the pipeline have written to disk this session."
      actions={
        <button
          type="button"
          className="ams-button-secondary ams-button-compact"
          onClick={() => void load()}
        >
          Recount
        </button>
      }
    >
      {error && (
        <Banner tone="danger" title="Could not list the log files">
          <p className="ams-admin-banner-body">{error}</p>
        </Banner>
      )}
      {lastResult && (
        <Banner
          tone="good"
          title={`Cleared ${pluralise(lastResult.deleted.length, 'log file')}`}
        >
          <p className="ams-admin-banner-body">
            {formatBytes(lastResult.bytes_freed)} freed.
          </p>
        </Banner>
      )}
      {files === null && !error && <p className="ams-muted">Loading…</p>}
      {empty && <p className="ams-muted">No log files on disk.</p>}
      {files !== null && files.length > 0 && (
        <>
          <div className="ams-admin-tablewrap">{table}</div>
          <div className="ams-admin-row-actions ams-admin-actions-end">
            <span className="ams-admin-count-badge">
              {pluralise(files.length, 'file')} · {formatBytes(totalBytes)}
            </span>
            <button
              type="button"
              className="ams-button-secondary ams-button-compact"
              onClick={() => {
                setClearError(null)
                setConfirming(true)
              }}
            >
              Review and clear logs…
            </button>
          </div>
        </>
      )}

      {confirming && files !== null && (
        <ConfirmDialog
          title="Clear all log files"
          subtitle={`${pluralise(files.length, 'file')} · ${formatBytes(totalBytes)}`}
          confirmWord="logs"
          confirmLabel="Delete these log files"
          ready
          busy={busy}
          error={clearError}
          onClose={() => {
            setConfirming(false)
            setClearError(null)
          }}
          onConfirm={async () => {
            setBusy(true)
            setClearError(null)
            try {
              const result = await onClear()
              setLastResult(result)
              setConfirming(false)
              await load()
            } catch (deleteError) {
              setClearError(
                deleteError instanceof Error ? deleteError.message : String(deleteError)
              )
            } finally {
              setBusy(false)
            }
          }}
        >
          <p className="ams-admin-banner-body">
            Every file below is deleted. The ticket board's own history lives in one of
            these, so clearing logs can also clear the audit trail a stage is reading.
          </p>
          <div className="ams-admin-tablewrap">{table}</div>
        </ConfirmDialog>
      )}
    </AdminSection>
  )
}

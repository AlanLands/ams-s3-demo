import { StageFrame } from './components'
import { DeploymentPlanPanel, ReleaseNotes } from '../../ReleasePanel'
import { useS3 } from './context'

export default function ReleaseStage() {
  const {
    isEngineer,
    handleDraftReleaseNotes,
    draftingNotes,
    releaseNoteSet,
    releaseError,
    AI_LABEL,
    deploymentPlan,
    handleDownloadRecord,
    exportingRecord,
    handleAttachRecord,
    attachingRecord,
    attachResult,
    inQa,
    isActiveAssignee,
    activeIssue,
    handleMarkTicketDone,
    closingTicket
  } = useS3()
  const activity = draftingNotes
    ? 'Drafting release notes.'
    : exportingRecord
      ? 'Building release record.'
      : attachingRecord
        ? 'Attaching release record.'
        : releaseNoteSet
          ? 'Release notes drafted.'
          : releaseError ?? ''
  const draftButtonLabel = draftingNotes
    ? 'Drafting…'
    : releaseNoteSet
      ? 'Re-draft release notes'
      : 'Draft release notes'
  const attachStatusColor = attachResult?.attached
    ? 'var(--ams-success)'
    : 'var(--ams-warning)'
  const canMarkTicketDone =
    releaseNoteSet &&
    inQa &&
    isActiveAssignee &&
    activeIssue?.status !== 'Done'
  const releaseNotesCard = releaseNoteSet ? (
    <div
      className="ams-card"
      style={{
        marginTop: '0.75rem',
      }}
    >
      <strong
        style={{
          fontSize: 'var(--ams-text-sm)',
        }}
      >
        Release notes — three audiences
      </strong>
      <p
        style={{
          fontSize: 'var(--ams-text-xs)',
          color: 'var(--ams-ink-soft)',
          margin: '0.3rem 0 0.6rem',
        }}
      >
        {AI_LABEL}
      </p>
      <ReleaseNotes notes={releaseNoteSet} />
    </div>
  ) : null
  const deploymentPlanCard = deploymentPlan ? (
    <div
      className="ams-card"
      style={{
        marginTop: '0.75rem',
      }}
    >
      <strong
        style={{
          fontSize: 'var(--ams-text-sm)',
        }}
      >
        Deployment &amp; rollback
      </strong>
      <div
        style={{
          marginTop: '0.5rem',
        }}
      >
        <DeploymentPlanPanel plan={deploymentPlan} />
      </div>
    </div>
  ) : null
  const releaseRecordCard = releaseNoteSet ? (
    <div
      className="ams-card"
      style={{
        marginTop: '0.75rem',
      }}
    >
      <strong
        style={{
          fontSize: 'var(--ams-text-sm)',
        }}
      >
        Release record
      </strong>
      <p
        style={{
          fontSize: 'var(--ams-text-sm)',
          color: 'var(--ams-ink-soft)',
          margin: '0.4rem 0 0.6rem',
        }}
      >
        One document with what shipped, the change map, the acceptance-criteria matrix,
        every test run, the approvals from this ticket's own timeline, and the deployment
        plan. Anything the pipeline could not evidence is listed in it explicitly.
      </p>
      <div
        style={{
          display: 'flex',
          gap: '0.5rem',
          flexWrap: 'wrap',
        }}
      >
        <button
          className="ams-button"
          onClick={handleDownloadRecord}
          disabled={exportingRecord}
        >
          {exportingRecord ? 'Building…' : '⬇ Download release record (PDF)'}
        </button>
        <button
          className="ams-button-secondary"
          onClick={handleAttachRecord}
          disabled={attachingRecord}
        >
          {attachingRecord ? 'Attaching…' : 'Attach to ticket'}
        </button>
      </div>
      {attachResult && (
        <p
          style={{
            fontSize: 'var(--ams-text-sm)',
            marginTop: '0.6rem',
            color: attachStatusColor,
          }}
        >
          {attachResult.attached ? '✓ ' : '○ '}
          {attachResult.detail}
        </p>
      )}
    </div>
  ) : null

  return (
    <StageFrame stageId="release" title="Draft release notes" activity={activity}>
      {isEngineer ? (
    <>
        <div>
          <button className="ams-button" onClick={handleDraftReleaseNotes} disabled={draftingNotes}>
            {draftButtonLabel}
          </button>
        </div>
        {releaseError && <p style={{ color: 'var(--ams-error)' }}>{releaseError}</p>}
        {releaseNotesCard}
        {deploymentPlanCard}
        {releaseRecordCard}
        {canMarkTicketDone && (
          <button
            className="ams-button"
            style={{ marginTop: '0.75rem' }}
            onClick={handleMarkTicketDone}
            disabled={closingTicket}
          >
            {closingTicket ? 'Closing…' : 'QA passed — mark ticket Done'}
          </button>
        )}
    </>
  ) : (
    <p className="ams-muted">Release notes are drafted after QA evidence is available.</p>
  )}
    </StageFrame>
  )
}

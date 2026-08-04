import { useState } from 'react'
import { ArtifactSummary, Chip, Modal, StageFrame } from './components'
import { DeploymentPlanPanel, ReleaseNotes } from '../../ReleasePanel'
import { useS3 } from './context'

// Which artifact body is open, if any. The stage itself shows only that each
// artifact exists and what shape it is — the reading happens in the dialog.
type OpenArtifact = 'notes' | 'plan' | null

export default function ReleaseStage() {
  const {
    isTester,
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
  const [openArtifact, setOpenArtifact] = useState<OpenArtifact>(null)
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
  const canMarkTicketDone =
    releaseNoteSet &&
    inQa &&
    isActiveAssignee &&
    activeIssue?.status !== 'Done'
  const releaseNotesCard = releaseNoteSet ? (
    <ArtifactSummary
      title="Release notes"
      chips={<Chip>3 audiences</Chip>}
      detail="One note each for the customer, whoever runs the app, and the help page."
      actions={
        <button className="ams-button-secondary" onClick={() => setOpenArtifact('notes')}>
          View release notes
        </button>
      }
    />
  ) : null
  const deploymentPlanCard = deploymentPlan ? (
    <ArtifactSummary
      title="Deployment & rollback"
      chips={
        <Chip>
          {deploymentPlan.steps.length} deploy · {deploymentPlan.rollback.length} rollback
        </Chip>
      }
      detail="Derived from the change's own service graph — not drafted by a model."
      actions={
        <button className="ams-button-secondary" onClick={() => setOpenArtifact('plan')}>
          View plan
        </button>
      }
    />
  ) : null
  const releaseRecordCard = releaseNoteSet ? (
    <ArtifactSummary
      title="Release record"
      detail={
        <>
          What shipped, the change map, the acceptance-criteria matrix, every test run, this
          ticket's approvals, and the deployment plan — including anything the pipeline could
          not evidence.
          {attachResult && (
            <span
              style={{
                display: 'block',
                marginTop: '0.4rem',
                color: attachResult.attached ? 'var(--ams-success)' : 'var(--ams-warning)',
              }}
            >
              {attachResult.attached ? '✓ ' : '○ '}
              {attachResult.detail}
            </span>
          )}
        </>
      }
      actions={
        <>
          <button
            className="ams-button"
            onClick={() => handleDownloadRecord('pdf')}
            disabled={exportingRecord}
          >
            {exportingRecord ? 'Building…' : '⬇ Download (PDF)'}
          </button>
          <button
            className="ams-button-secondary"
            onClick={() => handleDownloadRecord('docx')}
            disabled={exportingRecord}
          >
            ⬇ Word
          </button>
          <button
            className="ams-button-secondary"
            onClick={handleAttachRecord}
            disabled={attachingRecord}
          >
            {attachingRecord ? 'Attaching…' : 'Attach to ticket'}
          </button>
        </>
      }
    />
  ) : null

  return (
    <StageFrame stageId="release" title="Draft release notes" activity={activity}>
      {/* The tester drafts this, straight after the run whose results it
          cites. `canDraftNotes` still requires those results to exist. */}
      {isTester ? (
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
        {openArtifact === 'notes' && releaseNoteSet && (
          <Modal
            title="Release notes"
            subtitle={AI_LABEL}
            onClose={() => setOpenArtifact(null)}
          >
            <ReleaseNotes notes={releaseNoteSet} />
          </Modal>
        )}
        {openArtifact === 'plan' && deploymentPlan && (
          <Modal
            title="Deployment & rollback"
            subtitle="Deploy order, migration and verification — derived, not drafted."
            onClose={() => setOpenArtifact(null)}
          >
            <DeploymentPlanPanel plan={deploymentPlan} />
          </Modal>
        )}
    </>
  ) : (
    <p className="ams-muted">Release notes are drafted after QA evidence is available.</p>
  )}
    </StageFrame>
  )
}

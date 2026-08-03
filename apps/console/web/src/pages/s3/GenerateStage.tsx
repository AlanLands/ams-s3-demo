import { useState } from 'react'
import { ArtifactSummary, Chip, DiffView, Modal, StageFrame } from './components'
import FileSelectionPanel from '../../FileSelectionPanel'
import TokenPanel from '../../TokenPanel'
import { ScmPanel } from '../../ScmPanel'
import { useS3 } from './context'

// Only the genuinely secondary detail moves off this stage. The per-file diff,
// the Q&A thread and every apply/reject control stay exactly where they were —
// reviewing the change file by file *is* the main flow here, and hiding it
// behind a click would be decluttering the one screen that is meant to be busy.
// What moves: how the AI picked the files, the crash dump behind a failed
// migration, and the proposed design-doc rewrite.
type OpenArtifact = { kind: 'selection' | 'crash' | 'docsync'; id?: string } | null

export default function GenerateStage() {
  const {
    isEngineer,
    dependenciesLoading,
    openDependencies,
    identity,
    handleMarkDone,
    markingDone,
    activeTicketKey,
    activeLinked,
    handleGenerate,
    generating,
    generateError,
    generated,
    AI_LABEL,
    orderedFilePaths,
    diffByPath,
    collapsedFiles,
    setCollapsedFiles,
    fileReasons,
    rejectedFiles,
    handleClearRejection,
    rejectingFile,
    perFileChat,
    revisingFile,
    perFileQuestion,
    setPerFileQuestion,
    handleAskAboutFile,
    applied,
    handleApplyFile,
    handleApply,
    appliedFiles,
    applyingFile,
    applying,
    handleRevertFile,
    revertingFile,
    reverting,
    setRejectPromptFor,
    setRejectReason,
    rejectPromptFor,
    rejectReason,
    handleRejectFile,
    reviseError,
    newFilePath,
    setNewFilePath,
    addingFile,
    newFileInstruction,
    setNewFileInstruction,
    handleAddFile,
    addFileError,
    handleRevertAll,
    applyError,
    postApplyFailure,
    handleFixCrash,
    fixingCrash,
    fixCrashError,
    scmState,
    scmBlockers,
    scmEvidence,
    committing,
    pushing,
    scmError,
    scmDetail,
    handleCommit,
    handlePush,
    targetApp,
    designSync,
    designDocApplied,
    designDocApplying,
    handleApplyDesignDoc
  } = useS3()
  const [openArtifact, setOpenArtifact] = useState<OpenArtifact>(null)
  const closeArtifact = () => setOpenArtifact(null)
  const failedSteps = postApplyFailure?.steps.filter((step) => step.returncode !== 0) ?? []
  const activity = generating ? 'Generating the change.' : applying ? 'Applying the proposal.' : applied ? (postApplyFailure ? 'Applied, but the app crashed on migration.' : 'Applied to repo.') : generateError ?? ''

  return (
    <StageFrame stageId="generate" title="Generate the change" activity={activity}>
      {isEngineer ? (
    <>
      {/* Codegen */}
      <div>
      {!dependenciesLoading && openDependencies.length > 0 && (
        <div
          className="ams-card"
          style={{ marginBottom: '1rem', borderLeft: '3px solid var(--ams-warning)' }}
        >
          <strong>Waiting on {openDependencies.length} other team{openDependencies.length > 1 ? 's' : ''}</strong>
          <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0.6rem' }}>
            Someone (logged in as that team) marks their ticket Done, then it clears here —
            no need to reload as {identity?.name}.
          </p>
          {openDependencies.map((dep) => (
            <div
              key={dep.key}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '0.3rem 0',
              }}
            >
              <span style={{ fontSize: 'var(--ams-text-sm)' }}>
                {dep.key} — {dep.summary} <span style={{ color: 'var(--ams-ink-soft)' }}>({dep.status})</span>
              </span>
              <button
                className="ams-button-secondary"
                onClick={() => handleMarkDone(dep.key)}
                disabled={markingDone === dep.key}
              >
                {markingDone === dep.key ? 'Marking…' : 'Mark as Done'}
              </button>
            </div>
          ))}
        </div>
      )}
      <p style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)', marginTop: '1.5rem' }}>
        {activeTicketKey ? (
          <>
            Generating for <strong>{activeLinked?.crLabel}</strong> ({activeTicketKey}) — click a
            ticket on the board above to switch.
          </>
        ) : (
          'No ticket assigned to you with a linked CR yet — once one is, pick it up here.'
        )}
      </p>

        <div>
          <button className="ams-button" onClick={handleGenerate} disabled={generating}>
            Generate the change
          </button>
        </div>
        {generateError && <p style={{ color: 'var(--ams-error)' }}>{generateError}</p>}
        {generated && (
          <>
            {generated.diff_text.trim() ? (
              <>
                <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', marginTop: '0.75rem' }}>
                  {AI_LABEL} Nothing has been written to the repo yet — ask a question about any file
                  below, or apply once you've reviewed the diff.
                </p>
                {orderedFilePaths.map((path) => {
                  const file = diffByPath.get(path)
                  const collapsed = collapsedFiles[path] ?? true
                  return (
                    <div key={path} className="ams-diff-file">
                      <div
                        className="ams-diff-file-header"
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          cursor: 'pointer',
                          ...(collapsed
                            ? { borderRadius: 6, borderBottom: '1px solid var(--ams-line)' }
                            : {}),
                        }}
                        onClick={() =>
                          setCollapsedFiles((prev) => ({ ...prev, [path]: !collapsed }))
                        }
                      >
                        <span>{path}</span>
                        <span style={{ fontWeight: 400, fontSize: 'var(--ams-text-xs)' }}>
                          {collapsed ? '▸ Show diff' : '▾ Hide diff'}
                        </span>
                      </div>
                      {fileReasons[path] && (
                        <p
                          style={{
                            fontSize: 'var(--ams-text-xs)',
                            fontStyle: 'italic',
                            color: 'var(--ams-ink-soft)',
                            margin: '0.4rem 0.7rem',
                          }}
                        >
                          {fileReasons[path]}
                        </p>
                      )}
                      {path in rejectedFiles && (
                        <div
                          style={{
                            display: 'flex',
                            gap: '0.5rem',
                            alignItems: 'center',
                            flexWrap: 'wrap',
                            margin: '0.4rem 0.7rem',
                            fontSize: 'var(--ams-text-xs)',
                          }}
                        >
                          <span className="ams-pill ams-pill-preview">Rejected</span>
                          <span style={{ color: 'var(--ams-ink-soft)' }}>
                            {rejectedFiles[path]
                              ? rejectedFiles[path]
                              : 'No reason given. Excluded from Apply.'}
                          </span>
                          <button
                            className="ams-button-secondary"
                            onClick={() => handleClearRejection(path)}
                            disabled={rejectingFile === path}
                          >
                            {rejectingFile === path ? 'Undoing…' : 'Undo reject'}
                          </button>
                        </div>
                      )}
                      {!collapsed && (
                        <>
                          <div className="ams-diff-body">
                            {file ? (
                              file.lines.map((line, index) => (
                                <div
                                  key={index}
                                  className={`ams-diff-line${line.type !== 'context' ? ` ams-diff-line-${line.type}` : ''}`}
                                >
                                  {line.text}
                                </div>
                              ))
                            ) : (
                              <div
                                className="ams-diff-line"
                                style={{ color: 'var(--ams-ink-soft)', fontStyle: 'italic' }}
                              >
                                No pending changes to this file right now.
                              </div>
                            )}
                          </div>
                          {((perFileChat[path] || []).length > 0 || revisingFile === path) && (
                            <div
                              className="ams-chat-thread"
                              style={{ margin: '0.5rem 0.7rem 0.2rem' }}
                            >
                              {(perFileChat[path] || []).map((turn, index) => (
                                <div
                                  key={index}
                                  className="ams-chat-bubble"
                                  data-role={turn.role}
                                  style={{
                                    fontSize: 'var(--ams-text-sm)',
                                    margin: '0.3rem 0',
                                    padding: '0.5rem 0.75rem',
                                    borderRadius: 6,
                                    maxWidth: '80%',
                                    // Replies carry deliberate line breaks (e.g. the
                                    // "no code was changed" note) — don't collapse them.
                                    whiteSpace: 'pre-wrap',
                                    marginLeft: turn.role === 'user' ? 'auto' : 0,
                                    background:
                                      turn.role === 'user' ? 'var(--ams-accent)' : 'var(--ams-surface)',
                                    color: turn.role === 'user' ? '#fff' : 'inherit',
                                    border:
                                      turn.role === 'assistant' ? '1px solid var(--ams-line)' : 'none',
                                  }}
                                >
                                  {turn.text}
                                </div>
                              ))}
                              {revisingFile === path && (
                                <div
                                  className="ams-chat-bubble"
                                  data-role="assistant"
                                  style={{
                                    fontSize: 'var(--ams-text-sm)',
                                    margin: '0.3rem 0',
                                    padding: '0.5rem 0.75rem',
                                    borderRadius: 6,
                                    maxWidth: '80%',
                                    background: 'var(--ams-surface)',
                                    border: '1px solid var(--ams-line)',
                                    color: 'var(--ams-ink-soft)',
                                    fontStyle: 'italic',
                                  }}
                                >
                                  Thinking…
                                </div>
                              )}
                              <p
                                style={{
                                  fontSize: 'var(--ams-text-xs)',
                                  color: 'var(--ams-ink-soft)',
                                  margin: '0.15rem 0 0',
                                }}
                              >
                                {AI_LABEL}
                              </p>
                            </div>
                          )}
                          <div className="ams-diff-ask">
                            <input
                              className="ams-input"
                              style={{ flex: 1 }}
                              placeholder={`Ask about ${path}…`}
                              value={perFileQuestion[path] || ''}
                              onChange={(event) =>
                                setPerFileQuestion((prev) => ({ ...prev, [path]: event.target.value }))
                              }
                              onKeyDown={(event) => {
                                if (event.key === 'Enter') handleAskAboutFile(path)
                              }}
                              disabled={revisingFile === path || applied}
                            />
                            <button
                              className="ams-button-secondary"
                              onClick={() => handleAskAboutFile(path)}
                              disabled={
                                revisingFile === path || applied || !(perFileQuestion[path] || '').trim()
                              }
                            >
                              {revisingFile === path ? 'Asking…' : 'Ask'}
                            </button>
                            {!(path in rejectedFiles) && (
                              <button
                                className="ams-button-secondary"
                                onClick={() => handleApplyFile(path)}
                                disabled={applied || appliedFiles[path] || applyingFile === path}
                              >
                                {appliedFiles[path]
                                  ? '✓ Applied'
                                  : applyingFile === path
                                    ? 'Applying…'
                                    : 'Apply this file'}
                              </button>
                            )}
                            {/* Revert is offered only for a file actually
                                written to the tree — there is nothing to put
                                back otherwise. */}
                            {appliedFiles[path] && (
                              <button
                                className="ams-button-secondary"
                                onClick={() => handleRevertFile(path)}
                                disabled={revertingFile === path}
                              >
                                {revertingFile === path ? 'Reverting…' : 'Revert this file'}
                              </button>
                            )}
                            {!appliedFiles[path] && !applied && !(path in rejectedFiles) && (
                              <button
                                className="ams-button-secondary"
                                onClick={() => {
                                  setRejectPromptFor(path)
                                  setRejectReason('')
                                }}
                                disabled={rejectingFile === path || rejectPromptFor === path}
                              >
                                Reject
                              </button>
                            )}
                          </div>
                          {rejectPromptFor === path && (
                            <div className="ams-diff-ask">
                              <input
                                className="ams-input"
                                style={{ flex: 1 }}
                                placeholder={`Why reject ${path}? (optional)`}
                                value={rejectReason}
                                onChange={(event) => setRejectReason(event.target.value)}
                                onKeyDown={(event) => {
                                  if (event.key === 'Enter') handleRejectFile(path)
                                }}
                                autoFocus
                              />
                              <button
                                className="ams-button-secondary"
                                onClick={() => handleRejectFile(path)}
                                disabled={rejectingFile === path}
                              >
                                {rejectingFile === path ? 'Rejecting…' : 'Confirm reject'}
                              </button>
                              <button
                                className="ams-button-secondary"
                                onClick={() => setRejectPromptFor(null)}
                                disabled={rejectingFile === path}
                              >
                                Cancel
                              </button>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )
                })}
                {reviseError && (
                  <p style={{ color: 'var(--ams-error)', marginTop: '0.5rem' }}>{reviseError}</p>
                )}

                <div className="ams-card" style={{ marginTop: '1rem' }}>
                  <p style={{ fontSize: 'var(--ams-text-sm)', marginBottom: '0.5rem' }}>
                    Realize another file needs a change too, outside the files listed above? Add it
                    here — it joins the same reviewed diff, nothing is written to the repo until you
                    apply.
                  </p>
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <input
                      className="ams-input"
                      style={{ flex: '1 1 240px' }}
                      placeholder="Repo-relative file path, e.g. repos/policycore/core/claims.py"
                      value={newFilePath}
                      onChange={(event) => setNewFilePath(event.target.value)}
                      disabled={addingFile || applied}
                    />
                    <input
                      className="ams-input"
                      style={{ flex: '2 1 320px' }}
                      placeholder="What change does this file need?"
                      value={newFileInstruction}
                      onChange={(event) => setNewFileInstruction(event.target.value)}
                      disabled={addingFile || applied}
                    />
                    <button
                      className="ams-button-secondary"
                      onClick={handleAddFile}
                      disabled={addingFile || applied || !newFilePath.trim() || !newFileInstruction.trim()}
                    >
                      {addingFile ? 'Adding…' : 'Add to proposal'}
                    </button>
                  </div>
                  {addFileError && (
                    <p style={{ color: 'var(--ams-error)', marginTop: '0.5rem' }}>{addFileError}</p>
                  )}
                </div>

                <div
                  style={{
                    marginTop: '1rem',
                    display: 'flex',
                    gap: '0.5rem',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                  }}
                >
                  <button className="ams-button" onClick={handleApply} disabled={applying || applied}>
                    {applied ? '✓ Applied to repo' : applying ? 'Applying…' : 'Apply to repo'}
                  </button>
                  {/* Undo for a change already written to the working tree.
                      Before this existed the only way back was a full demo
                      reset, which discards every other beat's state too. */}
                  {(applied || Object.keys(appliedFiles).length > 0) && (
                    <button
                      className="ams-button-secondary"
                      onClick={handleRevertAll}
                      disabled={reverting}
                    >
                      {reverting ? 'Reverting…' : 'Revert all'}
                    </button>
                  )}
                  {Object.keys(rejectedFiles).length > 0 && !applied && (
                    <span style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>
                      {Object.keys(rejectedFiles).length} rejected file
                      {Object.keys(rejectedFiles).length === 1 ? '' : 's'} will be skipped.
                    </span>
                  )}
                </div>
                {applyError && <p style={{ color: 'var(--ams-error)' }}>{applyError}</p>}
                {applied && postApplyFailure && (
                  <div
                    className="ams-card"
                    style={{ marginTop: '0.75rem', border: '1px solid var(--ams-error)' }}
                  >
                    <p style={{ color: 'var(--ams-error)', fontWeight: 700, marginTop: 0 }}>
                      Applied, but the app crashed on migration
                    </p>
                    <p style={{ fontSize: 'var(--ams-text-sm)' }}>
                      The change was written to the repo, but the post-apply step that rebuilds the
                      app against it failed — the portal is likely broken until this is fixed.
                    </p>
                    {/* Which command failed stays on screen; the output tail —
                        a stack trace nobody reads from the back of a room —
                        opens on request. */}
                    {failedSteps.map((step) => (
                      <p
                        key={step.command}
                        style={{ fontSize: 'var(--ams-text-xs)', margin: '0.3rem 0 0' }}
                      >
                        <code>{step.command}</code> exited with code {step.returncode}
                      </p>
                    ))}
                    <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                      <button className="ams-button" onClick={handleFixCrash} disabled={fixingCrash}>
                        {fixingCrash ? 'Fixing…' : 'Fix with AI'}
                      </button>
                      {failedSteps.length > 0 && (
                        <button
                          className="ams-button-secondary"
                          onClick={() => setOpenArtifact({ kind: 'crash' })}
                        >
                          View failure output
                        </button>
                      )}
                      <span style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>
                        Sends the crash back to the model for a revised proposal — or run
                        demo/reset_s3.sh to roll back.
                      </span>
                    </div>
                    {fixCrashError && (
                      <p style={{ color: 'var(--ams-error)', marginBottom: 0 }}>{fixCrashError}</p>
                    )}
                  </div>
                )}
                {/* Branch -> commit -> push around the apply. Shown as soon as a
                    branch exists, including after a revert abandoned it, so the
                    flow is visible rather than implied. Modelled, never executed
                    -- see s3_enhancement/scm.py and ScmPanel.tsx. */}
                {scmState && (
                  <ScmPanel
                    state={scmState}
                    blockers={scmBlockers}
                    evidence={scmEvidence}
                    committing={committing}
                    pushing={pushing}
                    error={scmError}
                    detail={scmDetail}
                    onCommit={handleCommit}
                    onPush={handlePush}
                  />
                )}
                {applied && !postApplyFailure && (
                  <p style={{ color: 'var(--ams-success)', fontSize: 'var(--ams-text-sm)' }}>
                    Applied. The app now has this capability —{' '}
                    <a href={targetApp.url} target="_blank" rel="noopener noreferrer">
                      {targetApp.label}
                    </a>{' '}
                    to try it.
                  </p>
                )}
                {applied &&
                  designSync?.findings
                    .filter((finding) => !finding.still_accurate)
                    .map((finding) => (
                      <div
                        key={finding.design_doc}
                        className="ams-card"
                        style={{ marginTop: '0.75rem' }}
                      >
                        <p style={{ fontSize: 'var(--ams-text-xs)', margin: 0, opacity: 0.7 }}>
                          {designSync.label}
                        </p>
                        <p style={{ fontSize: 'var(--ams-text-sm)', marginTop: '0.4rem' }}>
                          This change touched <code>{finding.subsystem}</code>, and its design
                          document no longer describes it accurately: {finding.reason} That
                          document&rsquo;s scope keywords decide whether this subsystem is
                          considered relevant to future change requests, so leaving it stale
                          causes retrieval mistakes later.
                        </p>
                        {finding.proposal_id ? (
                          designDocApplied[finding.proposal_id] ? (
                            <p
                              style={{ color: 'var(--ams-success)', fontSize: 'var(--ams-text-sm)' }}
                            >
                              Applied — <code>{finding.design_doc}</code> now matches the code.
                            </p>
                          ) : (
                            // The proposed rewrite is a diff of a *document*,
                            // not of the change under review — read it if you
                            // want it, but it should not push the apply button
                            // off the bottom of the stage.
                            <div
                              style={{
                                display: 'flex',
                                gap: '0.5rem',
                                flexWrap: 'wrap',
                                marginTop: '0.6rem',
                              }}
                            >
                              <button
                                type="button"
                                className="ams-button"
                                disabled={designDocApplying === finding.proposal_id}
                                onClick={() => void handleApplyDesignDoc(finding)}
                              >
                                {designDocApplying === finding.proposal_id
                                  ? 'Applying…'
                                  : `Apply ${finding.design_doc}`}
                              </button>
                              <button
                                type="button"
                                className="ams-button-secondary"
                                onClick={() =>
                                  setOpenArtifact({ kind: 'docsync', id: finding.proposal_id ?? '' })
                                }
                              >
                                View proposed update
                              </button>
                            </div>
                          )
                        ) : (
                          <p style={{ fontSize: 'var(--ams-text-sm)', opacity: 0.8 }}>
                            No replacement text was produced — update{' '}
                            <code>{finding.design_doc}</code> by hand.
                          </p>
                        )}
                      </div>
                    ))}
              </>
            ) : (
              <div className="ams-card" style={{ marginTop: '0.75rem' }}>
                <p style={{ fontSize: 'var(--ams-text-sm)' }}>
                  No changes to propose — the app already has this feature from an earlier run. Run
                  demo/reset_s3.sh to regenerate from a clean baseline.
                </p>
              </div>
            )}
            {/* The subsystem screen, the score bars and the screened-out decoy
                bank answer "how did it decide where to look" — a good question,
                and a whole card of it under every generated change. */}
            <ArtifactSummary
              title="How the AI picked these files"
              chips={
                <Chip>
                  {generated.file_selection.selected_files.length} of{' '}
                  {generated.file_selection.candidate_pool_size} files
                </Chip>
              }
              detail="Subsystem screen, relevance scores, and everything ruled out as not part of this change."
              actions={
                <button
                  className="ams-button-secondary"
                  onClick={() => setOpenArtifact({ kind: 'selection' })}
                >
                  View file selection
                </button>
              }
            />
            <TokenPanel panel={generated.token_panel} />
          </>
        )}
      </div>
      {openArtifact?.kind === 'selection' && generated && (
        <Modal
          title="How the AI picked these files"
          subtitle="Which part of the repo this change was matched to, and what was screened out."
          onClose={closeArtifact}
        >
          <FileSelectionPanel selection={generated.file_selection} />
        </Modal>
      )}
      {openArtifact?.kind === 'crash' && postApplyFailure && (
        <Modal
          title="Post-apply failure output"
          subtitle="The step that rebuilds the app against the applied change did not succeed."
          size="lg"
          onClose={closeArtifact}
        >
          {failedSteps.map((step) => (
            <div key={step.command} style={{ marginTop: '0.5rem' }}>
              <p style={{ fontSize: 'var(--ams-text-xs)', margin: 0 }}>
                <code>{step.command}</code> exited with code {step.returncode}:
              </p>
              <pre style={{ fontSize: 'var(--ams-text-xs)', overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
                {step.output_tail}
              </pre>
            </div>
          ))}
        </Modal>
      )}
      {openArtifact?.kind === 'docsync' &&
        (() => {
          const finding = designSync?.findings.find(
            (candidate) => candidate.proposal_id === openArtifact.id
          )
          if (!finding) return null
          return (
            <Modal
              title={`Proposed update — ${finding.design_doc}`}
              subtitle={`Keeps ${finding.subsystem}'s design document in step with the code that just changed.`}
              size="lg"
              onClose={closeArtifact}
            >
              <DiffView diffText={finding.diff_text} />
            </Modal>
          )
        })()}
    </>
  ) : (
    <p className="ams-muted">Only engineers generate and apply code changes.</p>
  )}
    </StageFrame>
  )
}

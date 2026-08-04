import { useState, type ReactNode } from 'react'
import { ArtifactSummary, Chip, Modal, StageFrame } from './components'
import { parseDocBlocks, renderInlineBold, downloadFile, type DocBlock } from './utils'
import { useS3 } from './context'

// Unchanged markdown-ish rendering, lifted out of the JSX so the stage body can
// stay readable now that the document opens in a dialog rather than inline.
function renderDocBody(blocks: DocBlock[]): ReactNode[] {
  const rendered: ReactNode[] = []
  let bullets: DocBlock[] = []
  const flushBullets = (key: number) => {
    if (!bullets.length) return
    rendered.push(
      <ul key={`ul-${key}`} style={{ margin: '0.3rem 0 0.7rem 1.2rem', padding: 0 }}>
        {bullets.map((bullet, index) => (
          <li key={index} style={{ margin: '0.25rem 0' }}>
            {renderInlineBold(bullet.text)}
          </li>
        ))}
      </ul>
    )
    bullets = []
  }
  blocks.forEach((block, index) => {
    if (block.type === 'bullet') {
      bullets.push(block)
      return
    }
    flushBullets(index)
    if (block.type === 'heading') {
      rendered.push(
        <h4
          key={index}
          style={{
            fontSize: 'var(--ams-text-sm)',
            margin: '1.1rem 0 0.3rem',
            borderBottom: '1px solid var(--ams-line)',
            paddingBottom: '0.2rem',
          }}
        >
          {renderInlineBold(block.text)}
        </h4>
      )
    } else {
      rendered.push(
        <p key={index} style={{ margin: '0.4rem 0' }}>
          {renderInlineBold(block.text)}
        </p>
      )
    }
  })
  flushBullets(blocks.length)
  return rendered
}

export default function DesignDocStage() {
  const {
    isEngineer,
    isTester,
    handleDraftDesignDoc,
    draftingDesignDoc,
    designDocError,
    designDoc,
    activeTicketKey,
    activeLinked,
    designDiagram,
    designDiagramCaption,
    AI_LABEL,
    handleExportDesignDoc,
    exportingDoc,
    inQa,
    qaTester,
    setQaTester,
    handingOff,
    TESTER_ROSTER,
    handleHandoffToQa,
    activeIssue,
    handoffError
  } = useS3()
  const [docOpen, setDocOpen] = useState(false)
  const activity = draftingDesignDoc ? 'Drafting the design document.' : handingOff ? 'Handing off to QA.' : designDoc ? 'Design document drafted.' : designDocError ?? ''

  return (
    <StageFrame stageId="design-doc" title="Draft design doc (for QA)" activity={activity}>
      {/* Both see the document — it is the hand-off artefact, and the
          tester needs to read what they are testing against. Only the
          engineer drafts it (below); the hand-off control self-gates on
          `!inQa`, so a tester holding a QA ticket sees the assignment
          line rather than the controls. */}
      {isEngineer || isTester ? (
    <>
        {isEngineer && (
          <div>
            <button className="ams-button" onClick={handleDraftDesignDoc} disabled={draftingDesignDoc}>
              Draft design doc
            </button>
          </div>
        )}
        {designDocError && <p style={{ color: 'var(--ams-error)' }}>{designDocError}</p>}
        {designDoc && activeTicketKey && (() => {
          const storyLabel = activeLinked?.storyLabel ?? activeTicketKey
          const docDate = new Date().toLocaleDateString('en-CA', {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
          })
          const blocks = parseDocBlocks(designDoc)
          const body = renderDocBody(blocks)
          const sectionCount = blocks.filter((block) => block.type === 'heading').length
          return (
            <>
              {/* The document itself is the artifact, not the flow: the stage
                  says it exists, how big it is and what it covers, and opens
                  it on request. */}
              <ArtifactSummary
                title="Design document"
                chips={
                  <>
                    <Chip>
                      {sectionCount} section{sectionCount === 1 ? '' : 's'}
                    </Chip>
                    {designDiagram && <Chip>Change map</Chip>}
                  </>
                }
                detail={`${storyLabel} · Ticket ${activeTicketKey} · Engineering → QA hand-off`}
                actions={
                  <>
                    <button className="ams-button-secondary" onClick={() => setDocOpen(true)}>
                      View document
                    </button>
                    {/* Word sits beside the PDF rather than in the modal with
                        the other formats: it is the format the client asked
                        for by name on the 2026-08-03 walkthrough. */}
                    <button
                      className="ams-button-secondary"
                      onClick={() => handleExportDesignDoc('docx')}
                      disabled={exportingDoc !== null}
                    >
                      {exportingDoc === 'docx' ? 'Building…' : '⬇ Word'}
                    </button>
                    <button
                      className="ams-button"
                      onClick={() => handleExportDesignDoc('pdf')}
                      disabled={exportingDoc !== null}
                    >
                      {exportingDoc === 'pdf' ? 'Rendering…' : '⬇ Download PDF'}
                    </button>
                  </>
                }
              />
              {docOpen && (
                <Modal
                  title="Design document"
                  subtitle={`${storyLabel} · Ticket ${activeTicketKey} · ${docDate} · Engineering → QA hand-off`}
                  size="lg"
                  onClose={() => setDocOpen(false)}
                >
                  <div className="ams-doc">
                    <div className="ams-doc-letterhead">
                      <span className="ams-doc-org">MapleSure Insurance</span>
                      <span className="ams-doc-kind">Internal Design Document</span>
                    </div>
                    <div className="ams-doc-meta">
                      {storyLabel} · Ticket {activeTicketKey} · {docDate} · Engineering → QA hand-off
                    </div>
                    {designDiagram && (
                      <figure className="ams-doc-figure">
                        <div className="ams-doc-figure-title">Change map</div>
                        {/* Server-rendered SVG built from the changed-file set — no
                            model output reaches this, so there is nothing here a
                            prompt could have injected. */}
                        <div
                          className="ams-doc-diagram"
                          dangerouslySetInnerHTML={{ __html: designDiagram }}
                        />
                        {/* The server's caption, not a fixed string: it only
                            claims the parts this particular diagram contains. */}
                        <figcaption className="ams-doc-figcaption">{designDiagramCaption}</figcaption>
                      </figure>
                    )}
                    <div className="ams-doc-body" style={{ fontSize: 'var(--ams-text-sm)' }}>
                      {body}
                    </div>
                    <div className="ams-doc-label">{AI_LABEL}</div>
                  </div>
                  {/* The secondary export formats live with the document they
                      export; the PDF button stays out on the stage because it
                      is the one people actually ask for. */}
                  <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.9rem', flexWrap: 'wrap' }}>
                    <button
                      className="ams-button-secondary"
                      onClick={() => handleExportDesignDoc('html')}
                      disabled={exportingDoc !== null}
                    >
                      {exportingDoc === 'html' ? 'Rendering…' : '⬇ Download document (.html)'}
                    </button>
                    <button
                      className="ams-button-secondary"
                      onClick={() =>
                        downloadFile(`${storyLabel}-design-doc.md`, 'text/markdown', designDoc)
                      }
                    >
                      ⬇ Download markdown (.md)
                    </button>
                  </div>
                </Modal>
              )}
              {!inQa ? (
                <div
                  className="ams-card"
                  style={{
                    marginTop: '0.75rem',
                    display: 'flex',
                    gap: '0.5rem',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                  }}
                >
                  <strong style={{ fontSize: 'var(--ams-text-sm)' }}>Hand off to QA:</strong>
                  <select
                    className="ams-input"
                    style={{ width: 'auto' }}
                    value={qaTester}
                    onChange={(event) => setQaTester(event.target.value)}
                    disabled={handingOff}
                  >
                    {TESTER_ROSTER.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                  <button className="ams-button" onClick={handleHandoffToQa} disabled={handingOff}>
                    {handingOff ? 'Handing off…' : 'Assign tester & move to QA'}
                  </button>
                  <span style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>
                    The ticket moves to the QA column — only the tester can run the next steps.
                  </span>
                </div>
              ) : (
                <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', marginTop: '0.6rem' }}>
                  ✓ With QA — assigned to {activeIssue?.assignee || 'the tester'}.
                </p>
              )}
              {handoffError && <p style={{ color: 'var(--ams-error)' }}>{handoffError}</p>}
            </>
          )
        })()}
    </>
  ) : (
    <p className="ams-muted">Only engineers draft the QA design document.</p>
  )}
    </StageFrame>
  )
}

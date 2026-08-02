import type { ReactNode } from 'react'
import { StageFrame } from './components'
import { parseDocBlocks, renderInlineBold, downloadFile, type DocBlock } from './utils'
import { useS3 } from './context'

export default function DesignDocStage() {
  const {
    isEngineer,
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
  const activity = draftingDesignDoc ? 'Drafting the design document.' : handingOff ? 'Handing off to QA.' : designDoc ? 'Design document drafted.' : designDocError ?? ''

  return (
    <StageFrame stageId="design-doc" title="Draft design doc (for QA)" activity={activity}>
      {isEngineer ? (
    <>
        <div>
          <button className="ams-button" onClick={handleDraftDesignDoc} disabled={draftingDesignDoc}>
            Draft design doc
          </button>
        </div>
        {designDocError && <p style={{ color: 'var(--ams-error)' }}>{designDocError}</p>}
        {designDoc && activeTicketKey && (() => {
          const crLabel = activeLinked?.crLabel ?? activeTicketKey
          const docDate = new Date().toLocaleDateString('en-CA', {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
          })
          const blocks = parseDocBlocks(designDoc)
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
          return (
            <>
              <div className="ams-doc">
                <div className="ams-doc-letterhead">
                  <span className="ams-doc-org">MapleSure Insurance</span>
                  <span className="ams-doc-kind">Internal Design Document</span>
                </div>
                <div className="ams-doc-meta">
                  {crLabel} · Ticket {activeTicketKey} · {docDate} · Engineering → QA hand-off
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
                <div style={{ fontSize: 'var(--ams-text-sm)' }}>{rendered}</div>
                <div className="ams-doc-label">{AI_LABEL}</div>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.6rem', flexWrap: 'wrap' }}>
                <button
                  className="ams-button"
                  onClick={() => handleExportDesignDoc('pdf')}
                  disabled={exportingDoc !== null}
                >
                  {exportingDoc === 'pdf' ? 'Rendering…' : '⬇ Download PDF'}
                </button>
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
                    downloadFile(`${crLabel}-design-doc.md`, 'text/markdown', designDoc)
                  }
                >
                  ⬇ Download markdown (.md)
                </button>
              </div>
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

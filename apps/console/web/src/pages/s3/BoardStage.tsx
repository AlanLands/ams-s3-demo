import { Chip, Modal, StageFrame } from './components'
import { useS3 } from './context'

export default function BoardStage() {
  const {
    isManager,
    quickChatMessages,
    quickChatInput,
    setQuickChatInput,
    quickChatSending,
    handleQuickChatSend,
    quickChatResult,
    handleQuickChatReset,
    quickChatError,
    boardLoading,
    boardError,
    boardIssues,
    expandedTicket,
    handleTicketClick,
    boardAssignee,
    ASSIGNEE_ROSTER,
    setBoardAssignee,
    handleAssignBoardTicket,
    handleUnassignBoardTicket,
    handleOpenReassign,
    reassignTicket,
    setReassignTicket,
    assigningBoardTicket,
    worksTickets,
    identity,
    boardFilter,
    boardStatusFilter,
    setBoardFilter,
    setBoardStatusFilter,
    activeTicketKey,
    analysisDoneForActive,
    screenshotBefore,
    screenshotAfter
  } = useS3()
  const activity = quickChatSending ? 'Asking quick question.' : assigningBoardTicket ? 'Assigning ticket.' : analysisDoneForActive ? 'Impact analysis is available.' : ''

  return (
    <StageFrame stageId="board" title="Board" activity={activity}>
      {(
    <>
      {isManager && (
      <>
      <div id="quick-question" className="ams-card" style={{ marginBottom: '1.25rem' }}>
        <strong>Quick question</strong>
        <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0.6rem' }}>
          Ask about a hypothetical change before there's a formal user story — e.g. "how much would it
          cost if I just changed a text field on the amendment form?" Asks a clarifying
          question or two if it needs more detail, then sizes it.
        </p>
        {quickChatMessages.length > 0 && (
          <div className="ams-chat-thread" style={{ marginBottom: '0.6rem' }}>
            {quickChatMessages.map((turn, index) => (
              <div
                key={index}
                className="ams-chat-bubble"
                data-role={turn.role}
                style={{
                  fontSize: 'var(--ams-text-sm)',
                  margin: '0.3rem 0',
                  padding: '0.5rem 0.75rem',
                  borderRadius: 'var(--ams-radius-md)',
                  maxWidth: '80%',
                  marginLeft: turn.role === 'user' ? 'auto' : 0,
                  background: turn.role === 'user' ? 'var(--ams-accent)' : 'var(--ams-surface)',
                  color: turn.role === 'user' ? '#fff' : 'inherit',
                  border: turn.role === 'assistant' ? '1px solid var(--ams-line)' : 'none',
                }}
              >
                {turn.text}
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            className="ams-input"
            style={{ flex: 1 }}
            placeholder="Ask a quick question…"
            value={quickChatInput}
            onChange={(event) => setQuickChatInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !quickChatSending) handleQuickChatSend()
            }}
            disabled={quickChatSending}
          />
          <button
            className="ams-button"
            onClick={handleQuickChatSend}
            disabled={quickChatSending || !quickChatInput.trim()}
          >
            {quickChatSending ? 'Asking…' : 'Ask'}
          </button>
          {(quickChatMessages.length > 0 || quickChatResult) && (
            <button className="ams-button-secondary" onClick={handleQuickChatReset}>
              New question
            </button>
          )}
        </div>
        {quickChatError && <p style={{ color: 'var(--ams-error)' }}>{quickChatError}</p>}
        {quickChatResult && (
          <div className="ams-card" style={{ marginTop: '0.75rem' }}>
            <strong>{quickChatResult.label}</strong>
            <div style={{ whiteSpace: 'pre-wrap', fontSize: 'var(--ams-text-sm)', marginTop: '0.5rem' }}>
              {quickChatResult.impact_analysis}
            </div>
            {quickChatResult.effort_estimate && (
              <div style={{ display: 'flex', gap: '2rem', marginTop: '0.75rem' }}>
                <div>
                  <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)' }}>Effort</div>
                  <div style={{ fontWeight: 600 }}>
                    {quickChatResult.effort_estimate.hours_class}
                  </div>
                </div>
                <div>
                  <div style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-xs)' }}>
                    Priority-equivalent
                  </div>
                  <div style={{ fontWeight: 600 }}>
                    {quickChatResult.effort_estimate.priority_equivalent}
                  </div>
                </div>
                <div style={{ fontSize: 'var(--ams-text-sm)', flex: 1 }}>
                  {quickChatResult.effort_estimate.reasoning}
                </div>
              </div>
            )}
            {quickChatResult.code_change_warranted && (
              <p style={{ fontSize: 'var(--ams-text-sm)', marginTop: '0.5rem' }}>
                A concrete code change looks warranted:{' '}
                <strong>{quickChatResult.suggested_story_summary}</strong>
              </p>
            )}
          </div>
        )}
      </div>

      <div id="ticket-dashboard" className="ams-card">
        <strong>Ticket dashboard</strong>
        <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0.6rem' }}>
          Assign an open ticket to an engineer — once assigned, they'll see it on their own
          Jira board the next time they log in.
        </p>
        {boardLoading && (
          <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)' }}>Loading…</p>
        )}
        {boardError && <p style={{ color: 'var(--ams-error)' }}>{boardError}</p>}
        {boardIssues && (
          <div className="ams-dashboard-list">
            {boardIssues.map((issue) => (
              <div
                key={issue.key}
                className={`ams-dashboard-row${expandedTicket === issue.key ? ' ams-dashboard-row-selected' : ''}`}
              >
                <div
                  role="button"
                  tabIndex={0}
                  className="ams-dashboard-row-main"
                  onClick={() => handleTicketClick(issue.key)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      if (event.key === ' ') event.preventDefault()
                      handleTicketClick(issue.key)
                    }
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{issue.key}</span>
                  <span style={{ color: 'var(--ams-ink-soft)' }}>{issue.summary}</span>
                  <span className="ams-pill ams-pill-general">{issue.status || 'To Do'}</span>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexShrink: 0 }}>
                  {issue.assignee ? (
                    // Assigned: the name stays plain text on the row — a
                    // board of dropdowns is unreadable, and reassignment is
                    // rare enough that it belongs behind a deliberate step.
                    // The picker lives in the dialog below.
                    <>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: 'var(--ams-text-sm)' }}>
                        <span className="ams-avatar" title={issue.assignee}>
                          {issue.assignee.trim().charAt(0).toUpperCase()}
                        </span>
                        {issue.assignee}
                      </span>
                      <button
                        className="ams-button-secondary"
                        onClick={() => handleOpenReassign(issue.key, issue.assignee)}
                        disabled={assigningBoardTicket === issue.key}
                        aria-label={`Reassign ${issue.key}, currently assigned to ${issue.assignee}`}
                      >
                        {assigningBoardTicket === issue.key ? 'Saving…' : 'Reassign'}
                      </button>
                    </>
                  ) : (
                    <>
                      <select
                        className="ams-select"
                        style={{ width: 'auto' }}
                        aria-label={`Assignee for ${issue.key}`}
                        value={boardAssignee[issue.key] || ASSIGNEE_ROSTER[0]}
                        onChange={(event) =>
                          setBoardAssignee((prev) => ({ ...prev, [issue.key]: event.target.value }))
                        }
                      >
                        {ASSIGNEE_ROSTER.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </select>
                      <button
                        className="ams-button-secondary"
                        onClick={() => handleAssignBoardTicket(issue.key)}
                        disabled={assigningBoardTicket === issue.key}
                      >
                        {assigningBoardTicket === issue.key ? 'Assigning…' : 'Assign'}
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Reassign / unassign. A dialog rather than an inline picker so the
          board keeps reading as a list of names, and so changing an existing
          assignment is a decision the manager has to open, confirm, and can
          back out of. Rendered only under isManager, like the controls that
          open it — the server is what actually enforces who may assign. */}
      {reassignTicket && (() => {
        const issue = (boardIssues || []).find((candidate) => candidate.key === reassignTicket)
        if (!issue) return null
        const inFlight = assigningBoardTicket === issue.key
        const picked = boardAssignee[issue.key] || ASSIGNEE_ROSTER[0]
        return (
          <Modal
            title={`Reassign ${issue.key}`}
            subtitle={issue.summary || undefined}
            onClose={() => setReassignTicket(null)}
          >
            <p style={{ fontSize: 'var(--ams-text-sm)', margin: '0 0 0.6rem' }}>
              Currently assigned to <Chip>{issue.assignee || 'nobody'}</Chip>
            </p>
            <label
              style={{ display: 'block', fontSize: 'var(--ams-text-sm)', marginBottom: '0.3rem' }}
              htmlFor="reassign-picker"
            >
              Reassign to
            </label>
            <select
              id="reassign-picker"
              className="ams-select"
              style={{ width: 'auto' }}
              value={picked}
              disabled={inFlight}
              onChange={(event) =>
                setBoardAssignee((prev) => ({ ...prev, [issue.key]: event.target.value }))
              }
            >
              {ASSIGNEE_ROSTER.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem', flexWrap: 'wrap' }}>
              <button
                className="ams-button"
                onClick={() => handleAssignBoardTicket(issue.key)}
                disabled={inFlight || picked === issue.assignee}
              >
                {inFlight ? 'Saving…' : 'Reassign'}
              </button>
              {/* Back to the manager's own queue, where it shows up
                  unassigned with an Assign control again. */}
              <button
                className="ams-button-secondary"
                onClick={() => handleUnassignBoardTicket(issue.key)}
                disabled={inFlight || !issue.assignee}
              >
                Unassign
              </button>
              <button
                className="ams-button-secondary"
                onClick={() => setReassignTicket(null)}
                disabled={inFlight}
              >
                Cancel
              </button>
            </div>
          </Modal>
        )
      })()}
      </>
      )}

      {/* Engineers and testers each see the queue assigned to them; the
          manager sees the whole board above instead. */}
      {worksTickets && (
      <>
      {/* Jira board */}
      <div id="board" className="ams-card" style={{ marginBottom: '1.25rem' }}>
        <strong>Jira board</strong>
        <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0.6rem' }}>
          Showing tickets assigned to {identity?.name}.
        </p>
        {boardLoading && (
          <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)' }}>Loading…</p>
        )}
        {boardError && <p style={{ color: 'var(--ams-error)' }}>{boardError}</p>}
        {boardIssues && (() => {
          const mine = boardIssues.filter((issue) => issue.assignee === identity?.name)
          const openCount = mine.filter((issue) => issue.status !== 'Done').length
          const doneCount = mine.filter((issue) => issue.status === 'Done').length
          const query = boardFilter.trim().toLowerCase()
          const visibleIssues = mine.filter((issue) => {
            const matchesQuery =
              !query ||
              issue.key.toLowerCase().includes(query) ||
              (issue.summary || '').toLowerCase().includes(query)
            const matchesStatus =
              boardStatusFilter === 'all' ||
              (boardStatusFilter === 'done' ? issue.status === 'Done' : issue.status !== 'Done')
            return matchesQuery && matchesStatus
          })
          return (
          <>
          <div className="ams-board-toolbar" style={{ marginTop: '0.75rem' }}>
            <input
              className="ams-input ams-board-search"
              placeholder="Filter by key or summary…"
              value={boardFilter}
              onChange={(event) => setBoardFilter(event.target.value)}
            />
            <div className="ams-board-counts">
              <button
                className={`ams-board-count${boardStatusFilter === 'open' ? ' ams-board-count-active' : ''}`}
                onClick={() => setBoardStatusFilter(boardStatusFilter === 'open' ? 'all' : 'open')}
              >
                Open <span className="ams-board-count-value">{openCount}</span>
              </button>
              <button
                className={`ams-board-count${boardStatusFilter === 'done' ? ' ams-board-count-active' : ''}`}
                onClick={() => setBoardStatusFilter(boardStatusFilter === 'done' ? 'all' : 'done')}
              >
                Done <span className="ams-board-count-value">{doneCount}</span>
              </button>
            </div>
          </div>
          {mine.length === 0 && (
            <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)' }}>
              Nothing assigned to you yet — check back once a manager assigns you a ticket.
            </p>
          )}
          <div className="ams-board">
            {['To Do', 'In Progress', 'QA', 'Done'].map((status) => (
              <div key={status} className="ams-board-column">
                <div style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)', marginBottom: '0.4rem' }}>
                  {status}
                </div>
                {visibleIssues
                  .filter((issue) => (issue.status || 'To Do') === status)
                  .map((issue) => (
                    <div
                      key={issue.key}
                      className={`ams-ticket-card${
                        issue.key === expandedTicket || issue.key === activeTicketKey
                          ? ' ams-ticket-card-selected'
                          : ''
                      }`}
                      role="button"
                      tabIndex={0}
                      style={{ cursor: 'pointer' }}
                      onClick={() => handleTicketClick(issue.key)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          if (event.key === ' ') event.preventDefault()
                          handleTicketClick(issue.key)
                        }
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          gap: '0.5rem',
                          // The avatar is fixed-width; without this the key/avatar
                          // row cannot wrap and spills out of a narrow lane.
                          flexWrap: 'wrap',
                        }}
                      >
                        <span style={{ fontWeight: 600, minWidth: 0 }}>{issue.key}</span>
                        {issue.assignee && (
                          <span className="ams-avatar" title={issue.assignee}>
                            {issue.assignee.trim().charAt(0).toUpperCase()}
                          </span>
                        )}
                      </div>
                      <div style={{ marginTop: '0.25rem' }}>{issue.summary}</div>
                      {issue.origin === 'problem_record' && (
                        <span
                          className="ams-pill ams-pill-preview"
                          style={{ marginTop: '0.4rem', display: 'inline-block' }}
                          title={issue.problem_id ? `Derived from ${issue.problem_id}` : undefined}
                        >
                          From problem record
                        </span>
                      )}
                    </div>
                  ))}
              </div>
            ))}
          </div>
          </>
          )
        })()}
        {(screenshotBefore || screenshotAfter) && (
          <div style={{ display: 'flex', gap: '1rem', marginTop: '0.75rem' }}>
            {screenshotBefore && (
              <div>
                <div style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>Before</div>
                <img
                  src={`data:image/png;base64,${screenshotBefore}`}
                  alt="Amendment form before the change"
                  style={{ maxWidth: 220, border: '1px solid var(--ams-line)', borderRadius: 'var(--ams-radius-sm)' }}
                />
              </div>
            )}
            {screenshotAfter && (
              <div>
                <div style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>After</div>
                <img
                  src={`data:image/png;base64,${screenshotAfter}`}
                  alt="Amendment form after the change"
                  style={{ maxWidth: 220, border: '1px solid var(--ams-line)', borderRadius: 'var(--ams-radius-sm)' }}
                />
              </div>
            )}
          </div>
        )}
      </div>

      </>
      )}
    </>
  )}
    </StageFrame>
  )
}

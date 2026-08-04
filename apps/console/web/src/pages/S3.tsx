import { Outlet } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import TicketModal from '../TicketModal'
import StageRail from './s3/StageRail'
import { useS3Controller } from './s3/useS3Controller'

export default function S3() {
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  const controller = useS3Controller()
  const {
    activeTicketKey,
    storyLabel,
    stages,
    expandedTicket,
    boardIssues,
    ticketCrText,
    ticketAnalysis,
    ticketAnalysisLoading,
    ticketAnalysisError,
    ticketClarificationQuestion,
    ticketCrossTeam,
    ticketCrossTeamTokens,
    ticketCrossTeamLoading,
    createdTickets,
    assigneeByApp,
    creatingTicketFor,
    assigningTicketFor,
    ticketEvents,
    ticketEventsLoading,
    getLinked,
    setExpandedTicket,
    handleRunAnalysisForTicket,
    handleCheckCrossTeamForTicket,
    setAssigneeByApp,
    handleCreateCrossTeamTicket,
    handleAssignCrossTeamTicket,
  } = controller

  useEffect(() => {
    setSlot(document.getElementById('ams-sidebar-slot'))
  }, [])

  return (
    <div className="ams-s3-page">
      {slot && createPortal(<StageRail activeTicketKey={activeTicketKey} storyLabel={storyLabel} stages={stages} />, slot)}
      {/* Scenario context only — one line, and the page's h1 is the stage
          heading inside StageFrame. This used to be an eyebrow plus a 2rem h1
          plus a two-line summary, identical on all seven stages: ~150px of
          chrome above the fold that said the same thing every time, pushing the
          actual work down. It was redundant three ways over — the topbar reads
          "MapleSure AMS Console", the sidebar carries "S3 · Enhancement /
          Enhancement Delivery", and the Home tile already describes the
          pipeline in the same words the summary did. */}
      <span className="ams-eyebrow">S3 · Enhancement Delivery</span>
      <div className="ams-s3-layout">
        <div className="ams-s3-stage-panel">
          {/* The active route is the only stage consumer, so memoizing this context would add bookkeeping without avoiding a render. */}
          <Outlet context={controller} />
        </div>
      </div>

      {expandedTicket && boardIssues && (() => {
        const issue = boardIssues.find((candidate) => candidate.key === expandedTicket)
        if (!issue) return null
        const linked = getLinked(expandedTicket)
        return (
          <TicketModal
            issue={issue}
            storyText={ticketCrText[expandedTicket] || ''}
            storyLabel={linked?.storyLabel ?? null}
            onClose={() => setExpandedTicket(null)}
            analysisResult={ticketAnalysis[expandedTicket]}
            analysisLoading={!!ticketAnalysisLoading[expandedTicket]}
            analysisError={ticketAnalysisError[expandedTicket]}
            onRunAnalysis={() => handleRunAnalysisForTicket(expandedTicket)}
            clarificationQuestion={ticketClarificationQuestion[expandedTicket]}
            onSubmitClarification={(answer) => handleRunAnalysisForTicket(expandedTicket, answer)}
            crossTeamImpacts={ticketCrossTeam[expandedTicket]}
            crossTeamTokenPanel={ticketCrossTeamTokens[expandedTicket]}
            crossTeamLoading={!!ticketCrossTeamLoading[expandedTicket]}
            onCheckCrossTeam={() => handleCheckCrossTeamForTicket(expandedTicket)}
            createdTickets={createdTickets}
            assigneeByApp={assigneeByApp}
            onAssigneeChange={(appName, value) =>
              setAssigneeByApp((prev) => ({ ...prev, [appName]: value }))
            }
            creatingTicketFor={creatingTicketFor}
            onCreateTicket={(impact) => handleCreateCrossTeamTicket(impact, expandedTicket)}
            assigningTicketFor={assigningTicketFor}
            onAssignTicket={handleAssignCrossTeamTicket}
            events={ticketEvents[expandedTicket] || []}
            eventsLoading={!!ticketEventsLoading[expandedTicket]}
          />
        )
      })()}
    </div>
  )
}

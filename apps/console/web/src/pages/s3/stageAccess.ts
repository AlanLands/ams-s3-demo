// Which pipeline stages each console role sees.
//
// One map, consumed by both the stage rail (useS3Controller, which filters what
// it renders) and the router (App.tsx, which redirects a typed-in URL). Two
// lists would drift, and the failure mode is the worse direction: a stage
// hidden from the nav but still reachable by URL looks like a permissions bug
// to anyone who finds it.
//
// This is presentation, not authorization. It declutters each persona's view of
// a pipeline they all share — it is not a security boundary, and the API does
// not enforce it. Anything that must actually be prevented belongs server-side,
// the way the commit gate reads its test results off the ticket event log and
// the release record takes approvals from `common/ticket_events.py` rather than
// from anything the client posts.

export type ConsoleRole = 'manager' | 'engineer' | 'tester'

export type S3StageId = 'board' | 'target' | 'generate' | 'design-doc' | 'tests' | 'release'

// Board is deliberately in every list: it is the shared surface where the work
// is routed and handed over, and it is where each role lands.
export const STAGES_BY_ROLE: Record<ConsoleRole, readonly S3StageId[]> = {
  // The manager routes the work and signs off the outcome. Generated code and
  // a test run are the engineer's and the tester's evidence respectively —
  // showing them here invites approving a diff nobody asked them to read.
  manager: ['board', 'release'],
  // The developer builds and hands over. They draft the design doc because it
  // *is* the hand-off artefact; they do not drive the test bench, which is the
  // independent check on their own change.
  engineer: ['board', 'target', 'generate', 'design-doc'],
  // The tester reads the hand-off and runs the bench. No Generate stage: a
  // tester who can regenerate the change under test is not an independent
  // check of it.
  tester: ['board', 'design-doc', 'tests'],
}

const DEFAULT_ROLE: ConsoleRole = 'engineer'

function normaliseRole(role: string | null | undefined): ConsoleRole {
  return role === 'manager' || role === 'tester' || role === 'engineer' ? role : DEFAULT_ROLE
}

export function stagesForRole(role: string | null | undefined): readonly S3StageId[] {
  return STAGES_BY_ROLE[normaliseRole(role)]
}

export function canSeeStage(role: string | null | undefined, stageId: S3StageId): boolean {
  return stagesForRole(role).includes(stageId)
}

// Where to send someone who asks for a stage their role does not have. Board
// rather than the app root: they are still in the middle of this pipeline, and
// bouncing them out of it entirely reads as an error rather than a redirect.
export function fallbackStagePath(): string {
  return '/s3/board'
}

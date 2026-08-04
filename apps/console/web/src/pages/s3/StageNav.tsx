import { Link } from 'react-router-dom'
import { useS3, type S3Stage } from './context'

export default function StageNav({ stageId }: { stageId: S3Stage['id'] }) {
  const { stages } = useS3()
  const index = stages.findIndex((stage) => stage.id === stageId)
  const previous = index > 0 ? stages[index - 1] : null
  const next = index >= 0 && index < stages.length - 1 ? stages[index + 1] : null

  return (
    <nav className="ams-stage-nav" aria-label="Stage navigation">
      {/* Three cases, not two. A previous stage that exists but is locked stays
          on screen as a disabled control, because its presence is information —
          the step is there, you just cannot go back to it yet. On the first
          stage there is no previous stage at all, and rendering a dead
          "← Previous" invents a step that does not exist; the empty <span>
          holds the flex row so "Next" stays right-aligned instead of jumping to
          the left edge on stage one. */}
      {!previous ? (
        <span />
      ) : previous.locked ? (
        <span className="ams-button-secondary ams-stage-nav-disabled" aria-disabled="true">
          ← {previous.title}
        </span>
      ) : (
        <Link className="ams-button-secondary" to={previous.path}>
          ← {previous.title}
        </Link>
      )}
      {next && !next.locked ? (
        <Link className="ams-button" to={next.path}>
          {next.title} →
        </Link>
      ) : (
        <span className="ams-button ams-stage-nav-disabled" aria-disabled="true">
          {next?.title ?? 'Next'} →
        </span>
      )}
    </nav>
  )
}

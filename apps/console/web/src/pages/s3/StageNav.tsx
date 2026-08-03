import { Link } from 'react-router-dom'
import { useS3, type S3Stage } from './context'

export default function StageNav({ stageId }: { stageId: S3Stage['id'] }) {
  const { stages } = useS3()
  const index = stages.findIndex((stage) => stage.id === stageId)
  const previous = index > 0 ? stages[index - 1] : null
  const next = index >= 0 && index < stages.length - 1 ? stages[index + 1] : null

  return (
    <nav className="ams-stage-nav" aria-label="Stage navigation">
      {previous && !previous.locked ? (
        <Link className="ams-button-secondary" to={previous.path}>
          ← {previous.title}
        </Link>
      ) : (
        <span className="ams-button-secondary ams-stage-nav-disabled" aria-disabled="true">
          ← {previous?.title ?? 'Previous'}
        </span>
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

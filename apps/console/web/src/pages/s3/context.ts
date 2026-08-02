import { useOutletContext } from 'react-router-dom'
import type { S3Controller } from './useS3Controller'

export interface S3Stage {
  id: 'board' | 'target' | 'generate' | 'design-doc' | 'tests' | 'release'
  title: string
  path: string
  locked: boolean
  lockedReason: string | null
  done: boolean
  statusLabel: string | null
  statusVariant?: 'ok' | 'error'
}

export type S3OutletContext = S3Controller

export function useS3() {
  return useOutletContext<S3OutletContext>()
}

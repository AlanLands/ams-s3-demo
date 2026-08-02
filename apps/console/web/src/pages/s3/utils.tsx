import type { ReactNode } from 'react'

// --- Design-document rendering/download helpers ------------------------------
// The drafted design doc is a real hand-off artifact, so it renders as an
// actual document (letterhead, headings, lists) and downloads as a file —
// not a raw text dump in a card.

export interface DocBlock {
  type: 'heading' | 'bullet' | 'paragraph'
  text: string
}

export function parseDocBlocks(text: string): DocBlock[] {
  const blocks: DocBlock[] = []
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const boldHeading = line.match(/^\*\*(.+?)\*\*:?\s*$/)
    if (boldHeading) {
      blocks.push({ type: 'heading', text: boldHeading[1].replace(/:$/, '') })
      continue
    }
    const hashHeading = line.match(/^#{1,4}\s+(.*)$/)
    if (hashHeading) {
      blocks.push({ type: 'heading', text: hashHeading[1] })
      continue
    }
    if (/^\d+\.\s+[A-Za-z][A-Za-z /&-]{1,40}:?$/.test(line)) {
      blocks.push({ type: 'heading', text: line.replace(/:$/, '') })
      continue
    }
    if (/^[-*•]\s+/.test(line)) {
      blocks.push({ type: 'bullet', text: line.replace(/^[-*•]\s+/, '') })
      continue
    }
    blocks.push({ type: 'paragraph', text: line })
  }
  return blocks
}

export function renderInlineBold(text: string): ReactNode[] {
  return text
    .split(/\*\*(.+?)\*\*/g)
    .map((part, index) => (index % 2 === 1 ? <strong key={index}>{part}</strong> : part))
}

export function downloadFile(filename: string, mime: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

interface DiffLine {
  type: 'add' | 'del' | 'meta' | 'context'
  text: string
}

interface DiffFile {
  path: string
  lines: DiffLine[]
}

// Splits codegen.py's unified-diff output (difflib.unified_diff with
// fromfile="a/<path>", tofile="b/<path>") into one section per file, so the
// UI can show "which file, what changed, ask a question about it" instead of
// one undifferentiated block of text.
export function parseDiff(diffText: string): DiffFile[] {
  const files: DiffFile[] = []
  let current: DiffFile | null = null
  for (const line of diffText.split('\n')) {
    if (line.startsWith('+++ ')) {
      current = { path: line.slice(4).trim().replace(/^b\//, ''), lines: [] }
      files.push(current)
      continue
    }
    if (line.startsWith('--- ') || !current) continue
    if (line.startsWith('@@')) current.lines.push({ type: 'meta', text: line })
    else if (line.startsWith('+')) current.lines.push({ type: 'add', text: line })
    else if (line.startsWith('-')) current.lines.push({ type: 'del', text: line })
    else current.lines.push({ type: 'context', text: line })
  }
  return files
}



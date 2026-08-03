// Formatting helpers for the admin page. Kept out of the component files so
// oxlint's react/only-export-components rule stays quiet (a module that mixes
// components with plain exports breaks fast refresh).

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function pluralise(count: number, singular: string, plural?: string): string {
  return `${count} ${count === 1 ? singular : (plural ?? `${singular}s`)}`
}

// One line per entry, blanks dropped — the textarea convention the onboarding
// form uses for every list field. Trailing whitespace is stripped because a
// path with a stray space is a path that will not resolve on the server.
export function linesToList(value: string): string[] {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

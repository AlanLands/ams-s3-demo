// Shared between every beat that reports scoped-vs-naive token usage
// (Generate, Generate tests, Impact analysis, Cross-team impact) — one
// rendering so "how much smaller was this than sending the whole app"
// reads identically everywhere it shows up, instead of drifting per page.
export default function TokenPanel({
  panel,
}: {
  panel: {
    scoped_input_tokens: number | null
    naive_input_tokens_estimate?: number
    estimated?: boolean
  }
}) {
  if (panel.scoped_input_tokens == null) {
    return <p style={{ color: 'var(--ams-ink-soft)', fontSize: '0.85rem' }}>Token count unavailable for this run.</p>
  }
  // "~" + suffix when the numbers are reconstructed from a replay recording
  // (chars/4 heuristic) rather than provider-reported usage.
  const approx = panel.estimated ? '~' : ''
  const estimatedNote = panel.estimated ? ' (estimated from the recorded run)' : ''
  const naive = panel.naive_input_tokens_estimate
  if (!naive) {
    return (
      <p style={{ color: 'var(--ams-ink-soft)', fontSize: '0.85rem' }}>
        Scoped context used {approx}{panel.scoped_input_tokens.toLocaleString()} input tokens
        {estimatedNote}.
      </p>
    )
  }
  const multiplier = Math.max(1, Math.round(naive / Math.max(panel.scoped_input_tokens, 1)))
  return (
    <p style={{ color: 'var(--ams-ink-soft)', fontSize: '0.85rem' }}>
      Scoped context used {approx}{panel.scoped_input_tokens.toLocaleString()} input tokens
      {estimatedNote}; a whole-app-context approach would have used ~{naive.toLocaleString()}
      {' '}tokens — {multiplier}x fewer.
    </p>
  )
}

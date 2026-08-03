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
    return <p style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-sm)' }}>Token count unavailable for this run.</p>
  }
  // "~" + suffix when the numbers are reconstructed from a replay recording
  // (chars/4 heuristic) rather than provider-reported usage.
  const approx = panel.estimated ? '~' : ''
  const estimatedNote = panel.estimated ? ' (estimated from the recorded run)' : ''
  const naive = panel.naive_input_tokens_estimate
  if (!naive) {
    return (
      <p style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-sm)' }}>
        Scoped context used {approx}{panel.scoped_input_tokens.toLocaleString()} input tokens
        {estimatedNote}.
      </p>
    )
  }
  const ratio = naive / Math.max(panel.scoped_input_tokens, 1)
  // Below ~1.05x the two prompts are the same size: scoping picked (nearly)
  // every file, so there was nothing to save. Claiming a multiplier here
  // would be dressing up a no-op — say so instead. The old code floored the
  // multiplier at 1x, which rendered exactly that case as "1x fewer".
  if (ratio < 1.05) {
    return (
      <p style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-sm)' }}>
        Scoped context used {approx}{panel.scoped_input_tokens.toLocaleString()} input tokens
        {estimatedNote} — no saving over whole-app context here, since this change needed
        essentially every file in the app.
      </p>
    )
  }
  // One decimal below 10x: "3.4x" is a defensible reading of a chars/4
  // estimate, "3x" quietly rounds a third of the saving away.
  const multiplier = ratio < 10 ? ratio.toFixed(1) : Math.round(ratio).toString()
  return (
    <p style={{ color: 'var(--ams-ink-soft)', fontSize: 'var(--ams-text-sm)' }}>
      Scoped context used {approx}{panel.scoped_input_tokens.toLocaleString()} input tokens
      {estimatedNote}; a whole-app-context approach would have used ~{naive.toLocaleString()}
      {' '}tokens — {multiplier}x more.
    </p>
  )
}

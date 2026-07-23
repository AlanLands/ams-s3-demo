import { useEffect, useState } from 'react'
import { ApiError } from '../api'
import {
  s3Api,
  type AnalyzeResponse,
  type FileSelection,
  type GenerateResponse,
  type GitlabProject,
  type GitlabScopeAutoResponse,
  type GitlabScopeResponse,
  type HarnessResponse,
  type TestsResponse,
} from '../api_s3'

const AI_LABEL = 'AI suggestion — verify with your specialist before applying.'

function FileSelectionPanel({ selection }: { selection: FileSelection }) {
  return (
    <div className="ams-card" style={{ marginTop: '0.75rem' }}>
      <div style={{ display: 'flex', gap: '2rem' }}>
        <div>
          <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>Files in this app</div>
          <div style={{ fontWeight: 700 }}>{selection.candidate_pool_size}</div>
        </div>
        <div>
          <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>
            Files used for this change
          </div>
          <div style={{ fontWeight: 700 }}>{selection.selected_files.length}</div>
        </div>
      </div>
      <details style={{ marginTop: '0.5rem' }}>
        <summary>Selected source files</summary>
        <ul style={{ fontSize: '0.85rem' }}>
          {selection.selected_files.map((path) => (
            <li key={path}>{path}</li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function TokenPanel({
  panel,
}: {
  panel: { scoped_input_tokens: number | null; naive_input_tokens_estimate?: number }
}) {
  if (panel.scoped_input_tokens == null) {
    return <p style={{ color: 'var(--ams-ink-soft)', fontSize: '0.85rem' }}>Token count unavailable for this run.</p>
  }
  const naive = panel.naive_input_tokens_estimate
  if (!naive) {
    return (
      <p style={{ color: 'var(--ams-ink-soft)', fontSize: '0.85rem' }}>
        Scoped context used {panel.scoped_input_tokens.toLocaleString()} input tokens.
      </p>
    )
  }
  const multiplier = Math.max(1, Math.round(naive / Math.max(panel.scoped_input_tokens, 1)))
  return (
    <p style={{ color: 'var(--ams-ink-soft)', fontSize: '0.85rem' }}>
      Scoped context used {panel.scoped_input_tokens.toLocaleString()} input tokens; a
      whole-app-context approach would have used ~{naive.toLocaleString()} tokens — {multiplier}x
      fewer.
    </p>
  )
}

export default function S3() {
  const [tierName, setTierName] = useState('Elite')
  const [crText, setCrText] = useState('')
  const [crError, setCrError] = useState<string | null>(null)

  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)

  const [generated, setGenerated] = useState<GenerateResponse | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)

  const [tested, setTested] = useState<TestsResponse | null>(null)
  const [testing, setTesting] = useState(false)
  const [testError, setTestError] = useState<string | null>(null)

  const [harness, setHarness] = useState<HarnessResponse | null>(null)
  const [harnessError, setHarnessError] = useState<string | null>(null)
  const [harnessReviewed, setHarnessReviewed] = useState(false)

  const [releaseNotes, setReleaseNotes] = useState<string | null>(null)
  const [draftingNotes, setDraftingNotes] = useState(false)

  const [projects, setProjects] = useState<GitlabProject[] | null>(null)
  const [projectsError, setProjectsError] = useState<string | null>(null)
  const [selectedProject, setSelectedProject] = useState<string>('')
  const [gitlabScope, setGitlabScope] = useState<GitlabScopeResponse | null>(null)
  const [gitlabError, setGitlabError] = useState<string | null>(null)
  const [scoping, setScoping] = useState(false)

  const [autoScope, setAutoScope] = useState<GitlabScopeAutoResponse | null>(null)
  const [autoScopeError, setAutoScopeError] = useState<string | null>(null)
  const [autoScoping, setAutoScoping] = useState(false)

  const [checkingOut, setCheckingOut] = useState(false)
  const [checkedOut, setCheckedOut] = useState(false)

  function handleCheckOut() {
    setCheckingOut(true)
    setCheckedOut(false)
    setTimeout(() => {
      setCheckingOut(false)
      setCheckedOut(true)
    }, 10000)
  }

  useEffect(() => {
    s3Api
      .cr(tierName)
      .then((data) => {
        setCrText(data.cr_text)
        setCrError(null)
      })
      .catch((err) => setCrError(err instanceof ApiError ? err.message : 'Invalid tier name.'))
  }, [tierName])

  async function handleAnalyze() {
    setAnalyzing(true)
    setAnalyzeError(null)
    try {
      setAnalysis(await s3Api.analyze(tierName))
    } catch (err) {
      setAnalyzeError(err instanceof ApiError ? err.message : 'Analysis unavailable.')
    } finally {
      setAnalyzing(false)
    }
  }

  async function handleGenerate() {
    setGenerating(true)
    setGenerateError(null)
    try {
      setGenerated(await s3Api.generate(tierName))
    } catch (err) {
      setGenerateError(err instanceof ApiError ? err.message : 'Code generation failed.')
    } finally {
      setGenerating(false)
    }
  }

  async function handleTests() {
    setTesting(true)
    setTestError(null)
    try {
      setTested(await s3Api.tests(tierName))
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : 'Test generation failed.')
    } finally {
      setTesting(false)
    }
  }

  async function handleLoadHarness() {
    setHarnessError(null)
    try {
      setHarness(await s3Api.harnessLatest())
      setHarnessReviewed(false)
    } catch (err) {
      setHarnessError(
        err instanceof ApiError ? err.message : 'No harness run found yet — run demo/run_s3_harness.sh first.'
      )
    }
  }

  async function handleDraftReleaseNotes() {
    setDraftingNotes(true)
    try {
      const result = await s3Api.releaseNotes(tierName)
      setReleaseNotes(result.release_notes)
    } finally {
      setDraftingNotes(false)
    }
  }

  async function handleListProjects() {
    setProjectsError(null)
    try {
      const rows = await s3Api.gitlabProjects()
      setProjects(rows)
      if (rows.length > 0) setSelectedProject(String(rows[0].id))
    } catch (err) {
      setProjectsError(err instanceof ApiError ? err.message : 'Could not reach GitLab.')
    }
  }

  async function handleScopeRepo() {
    if (!selectedProject) return
    setScoping(true)
    setGitlabError(null)
    try {
      setGitlabScope(await s3Api.gitlabScope(selectedProject, tierName))
    } catch (err) {
      setGitlabError(err instanceof ApiError ? err.message : 'GitLab scoping failed.')
    } finally {
      setScoping(false)
    }
  }

  async function handleAutoDetectRepo() {
    setAutoScoping(true)
    setAutoScopeError(null)
    try {
      setAutoScope(await s3Api.gitlabScopeAuto(tierName))
    } catch (err) {
      setAutoScopeError(err instanceof ApiError ? err.message : 'Could not auto-detect a repo.')
    } finally {
      setAutoScoping(false)
    }
  }

  const harnessPending = harness !== null && !harnessReviewed

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '2rem 1.5rem' }}>
      <span className="ams-eyebrow">
        MapleSure Insurance · AMS Console · S3
      </span>
      <h1 style={{ fontSize: '1.7rem', margin: '0.6rem 0 0.3rem' }}>Enhancement Delivery</h1>
      <p style={{ color: 'var(--ams-ink-soft)', maxWidth: '70ch', marginBottom: '1.5rem' }}>
        Live CR intake, AI-assisted code generation, generated tests, and release notes.
      </p>

      <div className="ams-card" style={{ marginBottom: '1.25rem' }}>
        <strong>Step 0 · Check out the repo</strong>
        <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)', margin: '0.3rem 0 0.6rem' }}>
          Visual representation only — this demo works against the repo already on
          disk; no real git operation runs here.
        </p>
        <button
          className="ams-button"
          onClick={handleCheckOut}
          disabled={checkingOut}
        >
          {checkingOut ? 'Checking out…' : 'Check out mockapp'}
        </button>
        {checkedOut && !checkingOut && (
          <p style={{ fontSize: '0.85rem', marginTop: '0.5rem' }}>
            ✓ Checked out <code>mockapp</code> @ <code>main</code> (<code>a3f9c21</code>)
          </p>
        )}
      </div>

      <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.3rem' }}>
        What should we call the new top tier?
      </label>
      <p style={{ fontSize: '0.8rem', color: 'var(--ams-ink-soft)', margin: '0 0 0.4rem' }}>
        Ask the client for a name — whatever's typed here is what shows up in the
        generated code below, live.
      </p>
      <input
        className="ams-input"
        value={tierName}
        onChange={(event) => setTierName(event.target.value)}
        style={{ maxWidth: 320 }}
      />
      {crError && <p style={{ color: 'var(--ams-error)', fontSize: '0.85rem' }}>{crError}</p>}

      <h3 style={{ fontSize: '0.95rem', marginTop: '1rem' }}>CR-2026-041</h3>
      <div className="ams-card" style={{ marginBottom: '1.25rem' }}>
        <div style={{ whiteSpace: 'pre-wrap', fontSize: '0.85rem' }}>{crText}</div>
      </div>

      {/* Impact analysis */}
      <button className="ams-button" onClick={handleAnalyze} disabled={analyzing}>
        Run AI impact analysis
      </button>
      {analyzeError && <p style={{ color: 'var(--ams-error)' }}>{analyzeError}</p>}
      {analysis && (
        <div className="ams-card" style={{ marginTop: '0.75rem' }}>
          <strong>{analysis.label}</strong>
          <div style={{ whiteSpace: 'pre-wrap', fontSize: '0.9rem', marginTop: '0.5rem' }}>
            {analysis.impact_analysis}
          </div>
          <div style={{ display: 'flex', gap: '2rem', marginTop: '0.75rem' }}>
            <div>
              <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>Effort</div>
              <div style={{ fontWeight: 700 }}>{analysis.effort_estimate.hours_class}</div>
            </div>
            <div>
              <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>
                Priority-equivalent
              </div>
              <div style={{ fontWeight: 700 }}>{analysis.effort_estimate.priority_equivalent}</div>
            </div>
            <div style={{ fontSize: '0.85rem', flex: 1 }}>{analysis.effort_estimate.reasoning}</div>
          </div>
        </div>
      )}
      {analysis && <FileSelectionPanel selection={analysis.file_selection} />}

      {/* Codegen */}
      <div style={{ marginTop: '1.5rem' }}>
        <button className="ams-button" onClick={handleGenerate} disabled={generating}>
          Generate the change
        </button>
      </div>
      {generateError && <p style={{ color: 'var(--ams-error)' }}>{generateError}</p>}
      {generated && (
        <>
          <div className="ams-card" style={{ marginTop: '0.75rem' }}>
            {generated.diff_text.trim() ? (
              <>
                <pre style={{ fontSize: '0.8rem', overflowX: 'auto' }}>{generated.diff_text}</pre>
                <p style={{ color: 'var(--ams-success)', fontSize: '0.85rem' }}>
                  The app now has this capability. Open the policy portal to try it.
                </p>
              </>
            ) : (
              <p style={{ fontSize: '0.85rem' }}>
                No changes to apply — the app already has this feature from an earlier run. Run
                demo/reset_s3.sh to regenerate from a clean baseline.
              </p>
            )}
          </div>
          <FileSelectionPanel selection={generated.file_selection} />
          <TokenPanel panel={generated.token_panel} />
        </>
      )}

      {/* Testgen */}
      <div style={{ marginTop: '1.5rem' }}>
        <button className="ams-button" onClick={handleTests} disabled={testing}>
          Generate tests + run
        </button>
      </div>
      {testError && <p style={{ color: 'var(--ams-error)' }}>{testError}</p>}
      {tested && (
        <div className="ams-card" style={{ marginTop: '0.75rem' }}>
          <pre style={{ fontSize: '0.78rem', overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
            {tested.pytest_output}
          </pre>
        </div>
      )}

      {/* Live harness */}
      <div style={{ marginTop: '2rem', borderTop: '1px solid var(--ams-line)', paddingTop: '1.5rem' }}>
        <h3 style={{ fontSize: '1rem' }}>
          Live agent-harness codegen (money-shot beat, runs in a separate terminal)
        </h3>
        <p style={{ color: 'var(--ams-ink-soft)', fontSize: '0.88rem' }}>
          Run <code>demo/run_s3_harness.sh</code> in a second terminal pane — a real coding-agent
          CLI edits mockapp and writes/runs the tests live, on camera. Load the result here for
          human review before release notes can be drafted.
        </p>
        <button className="ams-button" onClick={handleLoadHarness}>
          Load latest harness run
        </button>
        {harnessError && <p style={{ color: 'var(--ams-error)' }}>{harnessError}</p>}
        {harness && (
          <div className="ams-card" style={{ marginTop: '0.75rem' }}>
            <strong>{harness.label}</strong>
            <div style={{ display: 'flex', gap: '2rem', margin: '0.5rem 0' }}>
              <div>
                <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>Harness</div>
                <div style={{ fontWeight: 700 }}>{harness.status.harness}</div>
              </div>
              <div>
                <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>
                  Replay used
                </div>
                <div style={{ fontWeight: 700 }}>{String(harness.status.used_replay)}</div>
              </div>
              <div>
                <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>Duration</div>
                <div style={{ fontWeight: 700 }}>{harness.status.duration_s.toFixed(1)}s</div>
              </div>
            </div>
            <pre style={{ fontSize: '0.8rem', overflowX: 'auto' }}>{harness.diff_text}</pre>
            <label style={{ fontSize: '0.85rem' }}>
              <input
                type="checkbox"
                checked={harnessReviewed}
                onChange={(event) => setHarnessReviewed(event.target.checked)}
              />{' '}
              I've reviewed this AI-generated change
            </label>
          </div>
        )}
      </div>

      {/* Release notes */}
      <div style={{ marginTop: '1.5rem' }}>
        <button className="ams-button" onClick={handleDraftReleaseNotes} disabled={draftingNotes || harnessPending}>
          Draft release notes
        </button>
        {harnessPending && (
          <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)' }}>
            Review and confirm the harness change above before drafting release notes.
          </p>
        )}
      </div>
      {releaseNotes && (
        <div className="ams-card" style={{ marginTop: '0.75rem' }}>
          <strong>{AI_LABEL}</strong>
          <div style={{ whiteSpace: 'pre-wrap', fontSize: '0.9rem', marginTop: '0.5rem' }}>
            {releaseNotes}
          </div>
        </div>
      )}

      {/* GitLab panel */}
      <div style={{ marginTop: '2rem', borderTop: '1px solid var(--ams-line)', paddingTop: '1.5rem' }}>
        <h3 style={{ fontSize: '1rem' }}>Connect your GitLab</h3>
        <p style={{ color: 'var(--ams-ink-soft)', fontSize: '0.88rem' }}>
          Proves this scales to your real GitLab org, not just the MapleSure demo app —
          read-only, and only ever scopes down to a handful of files per repo before anything
          reaches an LLM prompt, no matter how many repos or how large any one of them is. Does
          not write anything back to GitLab.
        </p>
        <button className="ams-button" onClick={handleListProjects}>
          List my GitLab repos
        </button>
        {projectsError && <p style={{ color: 'var(--ams-error)' }}>{projectsError}</p>}
        {projects && (
          <>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem', marginTop: '0.75rem' }}>
              <tbody>
                {projects.map((project) => (
                  <tr key={project.id} style={{ borderTop: '1px solid var(--ams-line)' }}>
                    <td style={{ padding: '0.3rem 0' }}>
                      {project.name_with_namespace || project.name}
                    </td>
                    <td style={{ textAlign: 'right', color: 'var(--ams-ink-soft)' }}>
                      {project.last_activity_at}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <label style={{ display: 'block', fontSize: '0.85rem', margin: '0.75rem 0 0.3rem' }}>
              Target repo for this CR
            </label>
            <select
              className="ams-select"
              value={selectedProject}
              onChange={(event) => setSelectedProject(event.target.value)}
              style={{ maxWidth: 480 }}
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name_with_namespace || project.name} (#{project.id})
                </option>
              ))}
            </select>
            <div style={{ marginTop: '0.5rem' }}>
              <button className="ams-button" onClick={handleScopeRepo} disabled={scoping}>
                Scope files for this repo
              </button>
            </div>
            {gitlabError && <p style={{ color: 'var(--ams-error)' }}>{gitlabError}</p>}
            {gitlabScope && (
              <div className="ams-card" style={{ marginTop: '0.75rem' }}>
                <div style={{ display: 'flex', gap: '2rem' }}>
                  <div>
                    <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>
                      Files in this repo
                    </div>
                    <div style={{ fontWeight: 700 }}>{gitlabScope.repo_size}</div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>
                      Files that reached the LLM
                    </div>
                    <div style={{ fontWeight: 700 }}>{gitlabScope.files_reached_llm}</div>
                  </div>
                </div>
                <p style={{ fontSize: '0.85rem', marginTop: '0.5rem' }}>
                  Only {gitlabScope.files_reached_llm} of {gitlabScope.repo_size} files were ever
                  fetched and scored for this change — the rest of the repo, and every other repo
                  in your org, was never read.
                </p>
              </div>
            )}

            <div style={{ marginTop: '1.25rem', borderTop: '1px dashed var(--ams-line)', paddingTop: '1rem' }}>
              <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.3rem' }}>
                Not sure which repo? Let AI pick.
              </label>
              <button className="ams-button" onClick={handleAutoDetectRepo} disabled={autoScoping}>
                Auto-detect repo for this CR
              </button>
              {autoScopeError && <p style={{ color: 'var(--ams-error)' }}>{autoScopeError}</p>}
              {autoScope && (
                <div className="ams-card" style={{ marginTop: '0.75rem' }}>
                  <strong>{autoScope.label}</strong>
                  <p style={{ fontSize: '0.9rem', marginTop: '0.5rem' }}>
                    Best match: <strong>{autoScope.suggested_project.name}</strong>{' '}
                    (#{autoScope.suggested_project.id}) — {autoScope.suggested_project.confidence}{' '}
                    confidence
                  </p>
                  <p style={{ fontSize: '0.85rem', color: 'var(--ams-ink-soft)' }}>
                    {autoScope.suggested_project.reasoning}
                  </p>
                  {autoScope.alternates.length > 0 && (
                    <details style={{ marginTop: '0.4rem' }}>
                      <summary style={{ fontSize: '0.85rem' }}>Other plausible repos</summary>
                      <ul style={{ fontSize: '0.85rem' }}>
                        {autoScope.alternates.map((alt) => (
                          <li key={alt.id}>
                            {alt.name} (#{alt.id}) — {alt.reasoning}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  <div style={{ display: 'flex', gap: '2rem', marginTop: '0.75rem' }}>
                    <div>
                      <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>
                        Files in this repo
                      </div>
                      <div style={{ fontWeight: 700 }}>{autoScope.repo_size}</div>
                    </div>
                    <div>
                      <div style={{ color: 'var(--ams-ink-soft)', fontSize: '0.8rem' }}>
                        Files that reached the LLM
                      </div>
                      <div style={{ fontWeight: 700 }}>{autoScope.files_reached_llm}</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

import { StageFrame, TestCaseTable, RunSummaryLine, RunnerOutput } from './components'
import { parseDiff } from './utils'
import TokenPanel from '../../TokenPanel'
import ScenarioPlan, { TraceabilityMatrix } from '../../TestPlanPanel'
import { useS3 } from './context'

export default function TestsStage() {
  const {
    isEngineer,
    scenarios,
    scenarioDraft,
    handleDraftScenarios,
    draftingScenarios,
    scenariosApprovedBy,
    handleScenariosChange,
    handleApproveScenarios,
    approvingScenarios,
    handleGenerateTests,
    generatingTests,
    testsGenerated,
    testError,
    AI_LABEL,
    handleRunTests,
    runningTests,
    testsRun,
    handleRunRegression,
    runningRegression,
    regressionRun,
    handleMutationCheck,
    mutating,
    mutationCheck,
    handleBuildTraceability,
    buildingMatrix,
    traceability
  } = useS3()
  const activity = draftingScenarios ? 'Drafting test scenarios.' : generatingTests ? 'Generating tests.' : runningTests ? 'Running tests.' : runningRegression ? 'Running regression suite.' : mutating ? 'Injecting seeded bug and rerunning tests.' : testsRun ? 'Test results are available.' : testError ?? ''

  return (
    <StageFrame stageId="tests" title="Generate tests + run" activity={activity}>
      {isEngineer ? (
    <>
        {/* Beat 1 — the test plan, in prose, before any test code exists. The
            tester edits it; what they approve is what gets generated. */}
        <div className="ams-card">
          <strong style={{ fontSize: 'var(--ams-text-sm)' }}>Test plan — scenarios first</strong>
          <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.4rem 0 0.6rem' }}>
            What will be checked, traced to the CR's acceptance criteria, before a line of test
            code is written. Edit, delete or add scenarios — the approved list is what the
            generated suite is written against.
          </p>
          <button
            className={scenarioDraft ? 'ams-button-secondary' : 'ams-button'}
            onClick={handleDraftScenarios}
            disabled={draftingScenarios}
          >
            {draftingScenarios
              ? 'Drafting…'
              : scenarioDraft
                ? 'Re-draft scenarios'
                : 'Draft test scenarios'}
          </button>
          {scenarioDraft && (
            <div style={{ marginTop: '0.75rem' }}>
              <ScenarioPlan
                scenarios={scenarios}
                criteria={scenarioDraft.criteria}
                uncovered={scenarioDraft.criteria
                  .filter(
                    (criterion) =>
                      !scenarios.some((scenario) =>
                        scenario.acceptance_criteria.includes(criterion.id)
                      )
                  )
                  .map((criterion) => criterion.id)}
                approvedBy={scenariosApprovedBy}
                onChange={handleScenariosChange}
                onApprove={handleApproveScenarios}
                approving={approvingScenarios}
              />
              <TokenPanel panel={scenarioDraft.token_panel} />
            </div>
          )}
        </div>

        {/* Beat 2 — generate the test file and review it before anything runs. */}
        <div style={{ marginTop: '0.75rem' }}>
          <button className="ams-button" onClick={handleGenerateTests} disabled={generatingTests}>
            {generatingTests ? 'Generating…' : testsGenerated ? 'Regenerate tests' : 'Generate tests'}
          </button>
          {scenariosApprovedBy && (
            <span style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)', marginLeft: '0.6rem' }}>
              Generating against {scenarios.length} approved scenario
              {scenarios.length === 1 ? '' : 's'}.
            </span>
          )}
        </div>
        {testError && <p style={{ color: 'var(--ams-error)' }}>{testError}</p>}
        {testsGenerated && (
          <>
            <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', marginTop: '0.75rem' }}>
              {AI_LABEL} Review the generated tests below — nothing has run yet.
            </p>
            {parseDiff(testsGenerated.diff_text).map((file) => (
              <div key={file.path} className="ams-diff-file">
                <div className="ams-diff-file-header">
                  <span>{file.path}</span>
                </div>
                <div className="ams-diff-body">
                  {file.lines.map((line, index) => (
                    <div
                      key={index}
                      className={`ams-diff-line${line.type !== 'context' ? ` ams-diff-line-${line.type}` : ''}`}
                    >
                      {line.text}
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <TokenPanel panel={testsGenerated.token_panel} />

            {/* Beat 3 — run the reviewed suite; results render as a per-test
                checklist parsed from JUnit XML, raw output behind a disclosure. */}
            <div style={{ marginTop: '0.75rem' }}>
              <button className="ams-button" onClick={handleRunTests} disabled={runningTests}>
                {runningTests ? 'Running…' : testsRun ? 'Re-run tests' : 'Run tests'}
              </button>
            </div>
            {testsRun && (
              <div
                className="ams-card"
                style={{
                  marginTop: '0.75rem',
                  ...(testsRun.passed ? {} : { border: '1px solid var(--ams-error)' }),
                }}
              >
                {!testsRun.passed && (
                  <p style={{ color: 'var(--ams-error)', fontWeight: 700, marginTop: 0 }}>
                    Test run exited with code {testsRun.returncode}
                  </p>
                )}
                <RunSummaryLine run={testsRun} />
                <TestCaseTable cases={testsRun.cases} />
                <RunnerOutput output={testsRun.output} />
              </div>
            )}

            {/* Beat 4 — the other half of "did it work": the app's own
                checked-in suite, which the AI never wrote and cannot edit.
                New tests passing says the CR did what it claimed; these
                passing says it cost nothing that already worked.

                Deliberately not gated on the generated run: this suite
                predates the change, so it is runnable at any point — the
                endpoint needs neither generated code nor generated tests. */}
            <div className="ams-card" style={{ marginTop: '0.75rem' }}>
              <strong style={{ fontSize: 'var(--ams-text-sm)' }}>Regression — the pre-existing suite</strong>
              <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.4rem 0 0.6rem' }}>
                Checked into the repo before this change request, authored by a human, and named
                by no allowlist the pipeline can write to. Every CR here ends with “existing
                flows are unaffected” — this is the part that checks it.
              </p>
              <button
                className="ams-button-secondary"
                onClick={handleRunRegression}
                disabled={runningRegression}
              >
                {runningRegression
                  ? 'Running…'
                  : regressionRun
                    ? 'Re-run regression suite'
                    : 'Run regression suite'}
              </button>
              {regressionRun && (
                <div style={{ marginTop: '0.75rem' }}>
                  <p
                    style={{
                      fontWeight: 700,
                      fontSize: 'var(--ams-text-sm)',
                      margin: '0 0 0.2rem',
                      color: regressionRun.passed ? 'var(--ams-success)' : 'var(--ams-error)',
                    }}
                  >
                    {regressionRun.passed
                      ? `✓ ${regressionRun.summary.total} pre-existing test${
                          regressionRun.summary.total === 1 ? '' : 's'
                        } still pass — no regression.`
                      : `✗ This change broke ${
                          regressionRun.summary.failed + regressionRun.summary.errors
                        } pre-existing test${
                          regressionRun.summary.failed + regressionRun.summary.errors === 1
                            ? ''
                            : 's'
                        }.`}
                  </p>
                  <RunSummaryLine run={regressionRun} />
                  <p
                    style={{
                      fontSize: 'var(--ams-text-xs)',
                      color: 'var(--ams-ink-soft)',
                      fontFamily: 'ui-monospace, monospace',
                      margin: '0.2rem 0 0',
                    }}
                  >
                    {regressionRun.suite_paths.join(' ')}
                  </p>
                  <TestCaseTable cases={regressionRun.cases} />
                  <RunnerOutput output={regressionRun.output} />
                </div>
              )}
            </div>

            {/* Beat 5 — prove the suite bites: inject the seeded bug, watch the
                right test go red, working tree reverted server-side. */}
            {testsRun?.passed && (
              <div className="ams-card" style={{ marginTop: '0.75rem' }}>
                <strong style={{ fontSize: 'var(--ams-text-sm)' }}>Prove the tests catch bugs</strong>
                <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.4rem 0 0.6rem' }}>
                  A passing suite only counts if it fails when the code is wrong. This injects a
                  seeded bug into the generated code, re-runs the suite, and reverts the bug —
                  the repo is untouched afterwards.
                </p>
                <button className="ams-button" onClick={handleMutationCheck} disabled={mutating}>
                  {mutating ? 'Injecting bug & re-running…' : 'Inject a seeded bug & re-run'}
                </button>
                {mutationCheck && (
                  <div style={{ marginTop: '0.75rem' }}>
                    <p style={{ fontSize: 'var(--ams-text-sm)', margin: '0 0 0.4rem' }}>
                      <strong>Injected bug:</strong> {mutationCheck.description}
                    </p>
                    {parseDiff(mutationCheck.mutation_diff).map((file) => (
                      <div key={file.path} className="ams-diff-file">
                        <div className="ams-diff-file-header">
                          <span>{file.path}</span>
                        </div>
                        <div className="ams-diff-body">
                          {file.lines.map((line, index) => (
                            <div
                              key={index}
                              className={`ams-diff-line${line.type !== 'context' ? ` ams-diff-line-${line.type}` : ''}`}
                            >
                              {line.text}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                    <p
                      style={{
                        fontWeight: 700,
                        fontSize: 'var(--ams-text-sm)',
                        color: mutationCheck.tests_caught_bug
                          ? 'var(--ams-success)'
                          : 'var(--ams-error)',
                        margin: '0.6rem 0 0',
                      }}
                    >
                      {mutationCheck.tests_caught_bug
                        ? `✓ The suite caught the injected bug — ${
                            mutationCheck.summary.failed + mutationCheck.summary.errors
                          } test${
                            mutationCheck.summary.failed + mutationCheck.summary.errors === 1
                              ? ''
                              : 's'
                          } went red.`
                        : '⚠ The suite did NOT catch the injected bug — these tests need strengthening.'}
                    </p>
                    <TestCaseTable cases={mutationCheck.cases} />
                    <RunnerOutput output={mutationCheck.output} />
                    <p style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)', margin: '0.6rem 0 0' }}>
                      The injected bug was reverted automatically — the working tree is back to the
                      applied change.
                    </p>
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {/* Beat 6 — the closing artifact: every acceptance criterion, what was
            planned for it, what actually ran, and the result. Outside the
            testsGenerated block because a criterion with no automated test is
            exactly what this is here to show. */}
        {scenarioDraft && (
          <div className="ams-card" style={{ marginTop: '0.75rem' }}>
            <strong style={{ fontSize: 'var(--ams-text-sm)' }}>Traceability — criteria to evidence</strong>
            <p style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-ink-soft)', margin: '0.4rem 0 0.6rem' }}>
              One row per acceptance criterion in the CR, joined to the approved scenarios and to
              the tests that actually ran. This is the artifact an auditor asks for.
            </p>
            <button
              className="ams-button-secondary"
              onClick={handleBuildTraceability}
              disabled={buildingMatrix || !scenarios.length}
            >
              {buildingMatrix
                ? 'Building…'
                : traceability
                  ? 'Rebuild matrix'
                  : 'Build traceability matrix'}
            </button>
            {!testsRun && (
              <span style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)', marginLeft: '0.6rem' }}>
                Runs above are optional — without them the matrix reports coverage, not results.
              </span>
            )}
            {traceability && (
              <div style={{ marginTop: '0.75rem' }}>
                <TraceabilityMatrix matrix={traceability} />
              </div>
            )}
          </div>
        )}
    </>
  ) : (
    <p className="ams-muted">Only the assigned QA tester runs this stage.</p>
  )}
    </StageFrame>
  )
}

import { useState } from 'react'
import {
  ArtifactSummary,
  Chip,
  DiffView,
  Modal,
  RunSummaryLine,
  RunnerOutput,
  StageFrame,
  TestCaseTable,
} from './components'
import { parseDiff } from './utils'
import TokenPanel from '../../TokenPanel'
import ScenarioPlan, { TraceabilityMatrix } from '../../TestPlanPanel'
import { ScmPanel } from '../../ScmPanel'
import { useS3 } from './context'

// The six beats each produce a body — a scenario table, a diff, three test
// checklists, a matrix — and stacking all six on one screen is what the exec
// review called "a lot of data". Each beat now keeps its button and its verdict
// on the stage, and opens its body here.
type OpenArtifact =
  | 'scenarios'
  | 'generated'
  | 'testrun'
  | 'regression'
  | 'mutation'
  | 'traceability'
  | null

export default function TestsStage() {
  const {
    scmState,
    scmBlockers,
    scmEvidence,
    committing,
    pushing,
    scmError,
    scmDetail,
    handleCommit,
    handlePush,
    isTester,
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
  const [openArtifact, setOpenArtifact] = useState<OpenArtifact>(null)
  const close = () => setOpenArtifact(null)
  const activity = draftingScenarios ? 'Drafting test scenarios.' : generatingTests ? 'Generating tests.' : runningTests ? 'Running tests.' : runningRegression ? 'Running regression suite.' : mutating ? 'Injecting seeded bug and rerunning tests.' : testsRun ? 'Test results are available.' : testError ?? ''

  const generatedFileCount = testsGenerated ? parseDiff(testsGenerated.diff_text).length : 0
  const regressionBroken = regressionRun
    ? regressionRun.summary.failed + regressionRun.summary.errors
    : 0
  const mutationCaught = mutationCheck
    ? mutationCheck.summary.failed + mutationCheck.summary.errors
    : 0

  return (
    <StageFrame stageId="tests" title="Generate tests + run" activity={activity}>
      {/* The tester runs this stage. `canTest` additionally requires the
          ticket to be in QA and this person to be its assignee, so a
          second tester sees the stage but not the controls. */}
      {isTester ? (
    <>
        {/* Beat 1 — the test plan, in prose, before any test code exists. The
            tester edits it; what they approve is what gets generated. The
            editing and the approval both live in the dialog — same component,
            same handlers, just not spread across the stage. */}
        <div className="ams-card">
          <strong style={{ fontSize: 'var(--ams-text-sm)' }}>Test plan — scenarios first</strong>
          <p className="ams-stage-note">
            What will be checked, traced to the user story's acceptance criteria, before a line of test
            code is written. Edit, delete or add scenarios — the approved list is what the
            generated suite is written against.
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
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
              <>
                <button className="ams-button-secondary" onClick={() => setOpenArtifact('scenarios')}>
                  Review {scenarios.length} scenario{scenarios.length === 1 ? '' : 's'}
                </button>
                {/* The approval stays on the stage, not inside the review
                    dialog. The exec review asked for the *artifacts* to move
                    behind a click and the *functionality* to stay in the main
                    flow, and it asked separately for the human-in-the-loop
                    gates to be visible rather than implied. An approval that
                    only exists two clicks deep reads as an automatic step. */}
                <button
                  className="ams-button"
                  onClick={handleApproveScenarios}
                  disabled={approvingScenarios}
                >
                  {approvingScenarios
                    ? 'Approving…'
                    : scenariosApprovedBy
                      ? 'Re-approve plan'
                      : 'Approve test plan'}
                </button>
                {scenariosApprovedBy ? (
                  <Chip tone="pass">Approved by {scenariosApprovedBy}</Chip>
                ) : (
                  <Chip tone="warn">Not approved yet</Chip>
                )}
              </>
            )}
          </div>
          {scenarioDraft && (
            <div style={{ marginTop: '0.5rem' }}>
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
            <ArtifactSummary
              title="Generated test suite"
              chips={
                <Chip>
                  {generatedFileCount} file{generatedFileCount === 1 ? '' : 's'}
                </Chip>
              }
              detail={`${AI_LABEL} Nothing has run yet — review it before you do.`}
              actions={
                <button className="ams-button-secondary" onClick={() => setOpenArtifact('generated')}>
                  View generated tests
                </button>
              }
            />
            <div style={{ marginTop: '0.5rem' }}>
              <TokenPanel panel={testsGenerated.token_panel} />
            </div>

            {/* Beat 3 — run the reviewed suite; results render as a per-test
                checklist parsed from JUnit XML, raw output behind a disclosure. */}
            <div style={{ marginTop: '0.75rem' }}>
              <button className="ams-button" onClick={handleRunTests} disabled={runningTests}>
                {runningTests ? 'Running…' : testsRun ? 'Re-run tests' : 'Run tests'}
              </button>
            </div>
            {testsRun && (
              <ArtifactSummary
                title="Test run"
                chips={
                  testsRun.passed ? (
                    <Chip tone="pass">{testsRun.summary.passed} passed</Chip>
                  ) : (
                    <>
                      <Chip tone="fail">
                        {testsRun.summary.failed + testsRun.summary.errors} failed
                      </Chip>
                      <Chip>exit code {testsRun.returncode}</Chip>
                    </>
                  )
                }
                detail={<RunSummaryLine run={testsRun} />}
                actions={
                  <button className="ams-button-secondary" onClick={() => setOpenArtifact('testrun')}>
                    View {testsRun.cases.length} result
                    {testsRun.cases.length === 1 ? '' : 's'}
                  </button>
                }
              />
            )}

            {/* Beat 4 — the other half of "did it work": the app's own
                checked-in suite, which the AI never wrote and cannot edit.
                New tests passing says the user story did what it claimed; these
                passing says it cost nothing that already worked.

                Deliberately not gated on the generated run: this suite
                predates the change, so it is runnable at any point — the
                endpoint needs neither generated code nor generated tests. */}
            <div className="ams-card" style={{ marginTop: '0.75rem' }}>
              <strong style={{ fontSize: 'var(--ams-text-sm)' }}>Regression — the pre-existing suite</strong>
              <p className="ams-stage-note">
                Checked into the repo before this change, authored by a human, and named
                by no allowlist the pipeline can write to. Every user story here ends with “existing
                flows are unaffected” — this is the part that checks it.
              </p>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
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
                  <button
                    className="ams-button-secondary"
                    onClick={() => setOpenArtifact('regression')}
                  >
                    View {regressionRun.cases.length} result
                    {regressionRun.cases.length === 1 ? '' : 's'}
                  </button>
                )}
              </div>
              {/* The verdict is the point of this beat, so it stays on the
                  stage — only the per-test checklist and the runner dump move. */}
              {regressionRun && (
                <div style={{ marginTop: '0.6rem' }}>
                  <p
                    style={{
                      fontWeight: 700,
                      fontSize: 'var(--ams-text-sm)',
                      margin: '0 0 0.2rem',
                      maxWidth: '68ch',
                      color: regressionRun.passed ? 'var(--ams-success)' : 'var(--ams-error)',
                    }}
                  >
                    {regressionRun.passed
                      ? `✓ ${regressionRun.summary.total} pre-existing test${
                          regressionRun.summary.total === 1 ? '' : 's'
                        } still pass — no regression.`
                      : `✗ This change broke ${regressionBroken} pre-existing test${
                          regressionBroken === 1 ? '' : 's'
                        }.`}
                  </p>
                  <RunSummaryLine run={regressionRun} />
                </div>
              )}
            </div>

            {/* Beat 5 — prove the suite bites: inject the seeded bug, watch the
                right test go red, working tree reverted server-side. */}
            {testsRun?.passed && (
              <div className="ams-card" style={{ marginTop: '0.75rem' }}>
                <strong style={{ fontSize: 'var(--ams-text-sm)' }}>Prove the tests catch bugs</strong>
                <p className="ams-stage-note">
                  A passing suite only counts if it fails when the code is wrong. This injects a
                  seeded bug into the generated code, re-runs the suite, and reverts the bug —
                  the repo is untouched afterwards.
                </p>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                  <button className="ams-button" onClick={handleMutationCheck} disabled={mutating}>
                    {mutating ? 'Injecting bug & re-running…' : 'Inject a seeded bug & re-run'}
                  </button>
                  {mutationCheck && (
                    <button
                      className="ams-button-secondary"
                      onClick={() => setOpenArtifact('mutation')}
                    >
                      View the injected bug & results
                    </button>
                  )}
                </div>
                {mutationCheck && (
                  <p
                    style={{
                      fontWeight: 700,
                      fontSize: 'var(--ams-text-sm)',
                      maxWidth: '68ch',
                      color: mutationCheck.tests_caught_bug
                        ? 'var(--ams-success)'
                        : 'var(--ams-error)',
                      margin: '0.6rem 0 0',
                    }}
                  >
                    {mutationCheck.tests_caught_bug
                      ? `✓ The suite caught the injected bug — ${mutationCaught} test${
                          mutationCaught === 1 ? '' : 's'
                        } went red.`
                      : '⚠ The suite did NOT catch the injected bug — these tests need strengthening.'}
                  </p>
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
            <p className="ams-stage-note">
              One row per acceptance criterion in the user story, joined to the approved scenarios and to
              the tests that actually ran. This is the artifact an auditor asks for.
            </p>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
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
              {traceability && (
                <>
                  <button
                    className="ams-button-secondary"
                    onClick={() => setOpenArtifact('traceability')}
                  >
                    View matrix
                  </button>
                  <Chip
                    tone={
                      traceability.summary.passed === traceability.summary.total ? 'pass' : 'warn'
                    }
                  >
                    {traceability.summary.passed}/{traceability.summary.total} criteria evidenced
                  </Chip>
                </>
              )}
              {!testsRun && (
                <span style={{ fontSize: 'var(--ams-text-xs)', color: 'var(--ams-ink-soft)' }}>
                  Runs above are optional — without them the matrix reports coverage, not results.
                </span>
              )}
            </div>
          </div>
        )}

        {openArtifact === 'scenarios' && scenarioDraft && (
          <Modal
            title="Test plan — scenarios"
            subtitle="Edit, delete or add scenarios. The approved list is what the generated suite is written against."
            size="lg"
            onClose={close}
          >
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
          </Modal>
        )}
        {openArtifact === 'generated' && testsGenerated && (
          <Modal
            title="Generated test suite"
            subtitle={`${AI_LABEL} Nothing has been run yet.`}
            size="lg"
            onClose={close}
          >
            <DiffView diffText={testsGenerated.diff_text} />
          </Modal>
        )}
        {openArtifact === 'testrun' && testsRun && (
          <Modal title="Test run results" size="lg" onClose={close}>
            {!testsRun.passed && (
              <p style={{ color: 'var(--ams-error)', fontWeight: 700, marginTop: 0 }}>
                Test run exited with code {testsRun.returncode}
              </p>
            )}
            {/* Leads the modal deliberately. Below this sit four identical
                AttributeErrors that read as "the AI generated broken tests";
                this is the one line that says they are not. */}
            {testsRun.unapplied_change_hint && (
              <div
                className="ams-card"
                style={{
                  borderLeft: '3px solid var(--ams-warning)',
                  marginBottom: '0.75rem',
                  fontSize: 'var(--ams-text-sm)',
                }}
              >
                <strong>⚠ The change may not be applied</strong>
                <p style={{ margin: '0.3rem 0 0' }}>{testsRun.unapplied_change_hint}</p>
              </div>
            )}
            <RunSummaryLine run={testsRun} />
            <TestCaseTable cases={testsRun.cases} />
            <RunnerOutput output={testsRun.output} />
          </Modal>
        )}
        {openArtifact === 'regression' && regressionRun && (
          <Modal
            title="Regression suite results"
            subtitle={regressionRun.suite_paths.join(' ')}
            size="lg"
            onClose={close}
          >
            <RunSummaryLine run={regressionRun} />
            <TestCaseTable cases={regressionRun.cases} />
            <RunnerOutput output={regressionRun.output} />
          </Modal>
        )}
        {openArtifact === 'mutation' && mutationCheck && (
          <Modal title="Seeded bug — did the suite catch it?" size="lg" onClose={close}>
            <p style={{ fontSize: 'var(--ams-text-sm)', margin: '0 0 0.6rem' }}>
              <strong>Injected bug:</strong> {mutationCheck.description}
            </p>
            <DiffView diffText={mutationCheck.mutation_diff} />
            <TestCaseTable cases={mutationCheck.cases} />
            <RunnerOutput output={mutationCheck.output} />
            <p className="ams-sheet-note">
              The injected bug was reverted automatically — the working tree is back to the
              applied change.
            </p>
          </Modal>
        )}
        {openArtifact === 'traceability' && traceability && (
          <Modal
            title="Traceability — criteria to evidence"
            subtitle="One row per acceptance criterion, joined to the approved scenarios and the tests that ran."
            size="lg"
            onClose={close}
          >
            <TraceabilityMatrix matrix={traceability} />
          </Modal>
        )}

        {/* The commit gate is the test run, so the branch closes out here
            rather than back on the engineer's stage — they see the same panel
            read-only. Blockers still come from the ticket's event log
            server-side (scm.commit_blockers), never from anything posted from
            this page. */}
        {scmState && (
          <ScmPanel
            state={scmState}
            blockers={scmBlockers}
            evidence={scmEvidence}
            committing={committing}
            pushing={pushing}
            error={scmError}
            detail={scmDetail}
            onCommit={handleCommit}
            onPush={handlePush}
          />
        )}
    </>
  ) : (
    <p className="ams-muted">Only the assigned QA tester runs this stage.</p>
  )}
    </StageFrame>
  )
}

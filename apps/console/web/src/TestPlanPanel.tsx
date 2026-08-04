import { useState } from 'react'
import type {
  AcceptanceCriterion,
  TestScenario,
  TraceabilityResponse,
  TraceStatus,
} from './api_s3'

const KINDS: TestScenario['kind'][] = ['positive', 'negative', 'boundary', 'regression']

const KIND_HINT: Record<TestScenario['kind'], string> = {
  positive: 'Happy path — the change doing what the user story asked for.',
  negative: 'Invalid, missing or out-of-range input.',
  boundary: 'Values at, just below and just above a threshold the story names.',
  regression: 'Existing behaviour that must survive the change.',
}

function blankScenario(nextIndex: number): TestScenario {
  return {
    id: `TS-${String(nextIndex).padStart(2, '0')}`,
    title: '',
    kind: 'positive',
    acceptance_criteria: [],
    preconditions: '',
    test_data: '',
    steps: [],
    expected: '',
  }
}

function ScenarioEditor({
  scenario,
  criteria,
  onSave,
  onCancel,
}: {
  scenario: TestScenario
  criteria: AcceptanceCriterion[]
  onSave: (next: TestScenario) => void
  onCancel: () => void
}) {
  const [draft, setDraft] = useState<TestScenario>(scenario)
  const set = (patch: Partial<TestScenario>) => setDraft({ ...draft, ...patch })

  function toggleCriterion(id: string) {
    const has = draft.acceptance_criteria.includes(id)
    set({
      acceptance_criteria: has
        ? draft.acceptance_criteria.filter((ref) => ref !== id)
        : [...draft.acceptance_criteria, id],
    })
  }

  return (
    <div className="ams-scenario-editor">
      <div className="ams-scenario-editor-row">
        <label>Title</label>
        <input
          className="ams-input"
          value={draft.title}
          onChange={(event) => set({ title: event.target.value })}
          placeholder="What this scenario checks"
        />
      </div>
      <div className="ams-scenario-editor-row">
        <label>Type</label>
        <div>
          <select
            className="ams-select"
            value={draft.kind}
            onChange={(event) => set({ kind: event.target.value as TestScenario['kind'] })}
          >
            {KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
          <div className="ams-scenario-hint">{KIND_HINT[draft.kind]}</div>
        </div>
      </div>
      <div className="ams-scenario-editor-row">
        <label>Covers</label>
        <div className="ams-scenario-ac-picker">
          {criteria.length === 0 && (
            <span className="ams-scenario-hint">This ticket states no acceptance criteria.</span>
          )}
          {criteria.map((criterion) => (
            <button
              key={criterion.id}
              type="button"
              title={criterion.text}
              className={`ams-ac-toggle${
                draft.acceptance_criteria.includes(criterion.id) ? ' ams-ac-toggle-on' : ''
              }`}
              onClick={() => toggleCriterion(criterion.id)}
            >
              {criterion.id}
            </button>
          ))}
        </div>
      </div>
      <div className="ams-scenario-editor-row">
        <label>Preconditions</label>
        <input
          className="ams-input"
          value={draft.preconditions}
          onChange={(event) => set({ preconditions: event.target.value })}
        />
      </div>
      <div className="ams-scenario-editor-row">
        <label>Test data</label>
        <input
          className="ams-input"
          value={draft.test_data}
          onChange={(event) => set({ test_data: event.target.value })}
        />
      </div>
      <div className="ams-scenario-editor-row">
        <label>Steps</label>
        <textarea
          className="ams-input"
          rows={3}
          value={draft.steps.join('\n')}
          onChange={(event) =>
            set({ steps: event.target.value.split('\n').filter((step) => step.trim()) })
          }
          placeholder="One step per line"
        />
      </div>
      <div className="ams-scenario-editor-row">
        <label>Expected</label>
        <input
          className="ams-input"
          value={draft.expected}
          onChange={(event) => set({ expected: event.target.value })}
          placeholder="The single observable outcome"
        />
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
        <button className="ams-button-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button className="ams-button" onClick={() => onSave(draft)}>
          Save scenario
        </button>
      </div>
    </div>
  )
}

/**
 * The test plan: what will be checked, in prose, before any test code exists.
 *
 * Editable on purpose. A plan the tester can only read is a plan they can
 * only rubber-stamp — the review that matters here ("did the AI understand
 * the requirement?") needs somewhere to put the answer when it's no.
 */
export default function ScenarioPlan({
  scenarios,
  criteria,
  uncovered,
  approvedBy,
  onChange,
  onApprove,
  approving,
}: {
  scenarios: TestScenario[]
  criteria: AcceptanceCriterion[]
  uncovered: string[]
  approvedBy: string | null
  onChange: (next: TestScenario[]) => void
  onApprove: () => void
  approving: boolean
}) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  function replace(id: string, next: TestScenario) {
    onChange(scenarios.map((scenario) => (scenario.id === id ? next : scenario)))
    setEditingId(null)
  }

  function remove(id: string) {
    onChange(scenarios.filter((scenario) => scenario.id !== id))
    if (editingId === id) setEditingId(null)
  }

  function add() {
    const next = blankScenario(scenarios.length + 1)
    onChange([...scenarios, next])
    setEditingId(next.id)
  }

  return (
    <div>
      <div className="ams-scenario-coverage">
        {criteria.map((criterion) => {
          const covered = !uncovered.includes(criterion.id)
          return (
            <span
              key={criterion.id}
              title={criterion.text}
              className={`ams-ac-chip${covered ? '' : ' ams-ac-chip-gap'}`}
            >
              {covered ? '✓' : '!'} {criterion.id}
            </span>
          )
        })}
      </div>
      {uncovered.length > 0 && (
        <p className="ams-scenario-gap-note">
          No scenario covers {uncovered.join(', ')} — add one before approving, or approve
          knowingly and the gap is recorded against the ticket.
        </p>
      )}

      <table className="ams-scenario-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Type</th>
            <th>Scenario</th>
            <th>Covers</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {scenarios.map((scenario) => (
            <tr key={scenario.id} className={editingId === scenario.id ? 'ams-scenario-editing' : ''}>
              <td className="ams-scenario-id">{scenario.id}</td>
              <td>
                <span className={`ams-kind ams-kind-${scenario.kind}`}>{scenario.kind}</span>
              </td>
              <td>
                {editingId === scenario.id ? (
                  <ScenarioEditor
                    scenario={scenario}
                    criteria={criteria}
                    onSave={(next) => replace(scenario.id, next)}
                    onCancel={() => setEditingId(null)}
                  />
                ) : (
                  <>
                    <button
                      className="ams-scenario-title"
                      onClick={() =>
                        setExpandedId(expandedId === scenario.id ? null : scenario.id)
                      }
                    >
                      {scenario.title || <em>(untitled)</em>}
                    </button>
                    <div className="ams-scenario-expected">Expected: {scenario.expected}</div>
                    {expandedId === scenario.id && (
                      <dl className="ams-scenario-detail">
                        <dt>Preconditions</dt>
                        <dd>{scenario.preconditions || '—'}</dd>
                        <dt>Test data</dt>
                        <dd>{scenario.test_data || '—'}</dd>
                        <dt>Steps</dt>
                        <dd>
                          <ol>
                            {scenario.steps.map((step, index) => (
                              <li key={index}>{step}</li>
                            ))}
                          </ol>
                        </dd>
                      </dl>
                    )}
                  </>
                )}
              </td>
              <td className="ams-scenario-acs">
                {scenario.acceptance_criteria.join(', ') || '—'}
              </td>
              <td className="ams-scenario-actions">
                {editingId !== scenario.id && (
                  <>
                    <button className="ams-modal-link" onClick={() => setEditingId(scenario.id)}>
                      Edit
                    </button>
                    <button className="ams-modal-link" onClick={() => remove(scenario.id)}>
                      Delete
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginTop: '0.6rem' }}>
        <button className="ams-button-secondary" onClick={add}>
          Add scenario
        </button>
        <button className="ams-button" onClick={onApprove} disabled={approving}>
          {approving ? 'Approving…' : approvedBy ? 'Re-approve plan' : 'Approve test plan'}
        </button>
        {approvedBy && (
          <span style={{ fontSize: 'var(--ams-text-sm)', color: 'var(--ams-success)' }}>
            ✓ Approved by {approvedBy}
          </span>
        )}
      </div>
    </div>
  )
}

const STATUS_LABEL: Record<TraceStatus, string> = {
  passed: 'Evidenced',
  failed: 'Failing',
  not_automated: 'No automated test',
  no_scenario: 'No scenario',
  not_run: 'Not run yet',
}

export function TraceabilityMatrix({ matrix }: { matrix: TraceabilityResponse }) {
  const gaps = matrix.summary.not_automated + matrix.summary.no_scenario
  return (
    <div>
      <p className="ams-trace-headline">
        <strong
          style={{
            color:
              matrix.summary.failed || gaps ? 'var(--ams-warning)' : 'var(--ams-success)',
          }}
        >
          {matrix.summary.passed}/{matrix.summary.total} acceptance criteria evidenced by a
          passing test
        </strong>
        {gaps > 0 && (
          <span style={{ color: 'var(--ams-ink-soft)' }}>
            {' '}
            · {gaps} with no automated coverage
          </span>
        )}
      </p>
      <table className="ams-trace-table">
        <thead>
          <tr>
            <th>Criterion</th>
            <th>Scenarios</th>
            <th>Automated test</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {matrix.rows.map((row) => (
            <tr key={row.criterion_id}>
              <td>
                <div className="ams-trace-ac">{row.criterion_id}</div>
                <div className="ams-trace-text">{row.criterion_text}</div>
              </td>
              <td className="ams-trace-scenarios">{row.scenario_ids.join(', ') || '—'}</td>
              <td className="ams-trace-tests">
                {row.test_names.length ? (
                  row.test_names.map((name) => <div key={name}>{name}</div>)
                ) : (
                  <span style={{ color: 'var(--ams-ink-soft)' }}>—</span>
                )}
                {row.covered_by === 'regression' && (
                  <div className="ams-trace-source">pre-existing suite</div>
                )}
              </td>
              <td>
                <span className={`ams-trace-status ams-trace-status-${row.status}`}>
                  {STATUS_LABEL[row.status]}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="ams-trace-footnote">
        Criteria and their wording come from the user story; the scenario column is the approved plan;
        results come from the runs above. Only the scenario-to-test link is inferred, and only
        claimed when one test is a clear match — an unmatched row means “not proven here”, not
        “not tested”.
      </p>
    </div>
  )
}

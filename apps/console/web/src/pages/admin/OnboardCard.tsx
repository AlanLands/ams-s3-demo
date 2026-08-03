import { useId, useMemo, useState, type ReactNode } from 'react'
import { Chip } from '../s3/components'
import { AdminSection, Banner } from './primitives'
import { linesToList } from './util'
import { adminApi, type AdminTarget, type OnboardRequest, type OnboardResult } from '../../api_admin'

interface FormState {
  name: string
  display_name: string
  target_id: string
  cache_namespace: string
  story: string
  core_files: string
  codegen_allowlist: string
  testgen_allowlist: string
  regression_paths: string
  post_apply_command: string
}

const EMPTY_FORM: FormState = {
  name: '',
  display_name: '',
  target_id: '',
  cache_namespace: '',
  story: '',
  core_files: '',
  codegen_allowlist: '',
  testgen_allowlist: '',
  regression_paths: '',
  post_apply_command: '',
}

// The server is the authority on this — it rejects a name that is not a safe
// single path segment. Checking it here too turns a round-trip into an inline
// message under the field that caused it.
const SAFE_NAME = /^[a-z0-9][a-z0-9_-]*$/

function buildPayload(form: FormState, dryRun: boolean): OnboardRequest {
  return {
    name: form.name.trim(),
    display_name: form.display_name.trim(),
    target_id: form.target_id.trim(),
    cache_namespace: form.cache_namespace.trim(),
    story: form.story.trim(),
    core_files: linesToList(form.core_files),
    codegen_allowlist: linesToList(form.codegen_allowlist),
    testgen_allowlist: linesToList(form.testgen_allowlist),
    regression_paths: linesToList(form.regression_paths),
    post_apply_command: linesToList(form.post_apply_command),
    dry_run: dryRun,
  }
}

function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string
  hint?: ReactNode
  error?: string | null
  children: (ids: { inputId: string; describedBy: string | undefined }) => ReactNode
}) {
  const inputId = useId()
  const hintId = useId()
  const errorId = useId()
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ')
  return (
    <div className="ams-field">
      <label className="ams-field-label" htmlFor={inputId}>
        {label}
      </label>
      {children({ inputId, describedBy: describedBy || undefined })}
      {hint && (
        <p className="ams-field-hint" id={hintId}>
          {hint}
        </p>
      )}
      {error && (
        <p className="ams-field-error" id={errorId}>
          <span aria-hidden="true">! </span>
          {error}
        </p>
      )}
    </div>
  )
}

/**
 * Onboard a new repo.
 *
 * Two-step by construction: the only thing the form's primary control does is
 * a `dry_run: true` validation, and writing stays disabled until that comes
 * back clean. Editing any field after a preview invalidates it — otherwise you
 * could review manifest A and write manifest B, which is exactly the class of
 * mistake a dry run exists to prevent.
 *
 * A written manifest is registered at import, so it is not live until the
 * console restarts. That arrives from the server in `warnings` and is rendered
 * as a warning banner, never folded into the success line.
 */
export default function OnboardCard({
  targets,
  onWrite,
}: {
  targets: AdminTarget[]
  onWrite: (payload: OnboardRequest) => Promise<OnboardResult>
}) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [namespaceTouched, setNamespaceTouched] = useState(false)
  const [preview, setPreview] = useState<OnboardResult | null>(null)
  const [previewSignature, setPreviewSignature] = useState<string | null>(null)
  const [written, setWritten] = useState<OnboardResult | null>(null)
  const [busy, setBusy] = useState<'preview' | 'write' | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)

  const signature = useMemo(() => JSON.stringify(buildPayload(form, true)), [form])
  const stale = preview !== null && previewSignature !== signature

  const nameError =
    form.name.trim() && !SAFE_NAME.test(form.name.trim())
      ? 'Lower-case letters, digits, dash and underscore only — it becomes a directory name.'
      : null
  const targetIdClash = targets.some((target) => target.target_id === form.target_id.trim())
  const targetIdError = targetIdClash
    ? 'Already registered. Target ids and cache namespaces must be unique, or a run replays the wrong recording.'
    : null

  const required = [form.name, form.display_name, form.target_id, form.cache_namespace, form.story]
  const complete = required.every((value) => value.trim().length > 0)
  const canPreview = complete && !nameError && !targetIdClash && busy === null
  const canWrite =
    preview !== null &&
    !stale &&
    preview.ok &&
    preview.errors.length === 0 &&
    busy === null &&
    written === null

  function update(patch: Partial<FormState>) {
    setForm((previous) => {
      const next = { ...previous, ...patch }
      // The three shipped targets all derive one from the other by swapping
      // dashes for underscores. Deriving it saves the commonest typo in the
      // form, and stops the moment the field is edited by hand.
      if (patch.target_id !== undefined && !namespaceTouched) {
        next.cache_namespace = patch.target_id.trim().replace(/-/g, '_')
      }
      return next
    })
    setWritten(null)
  }

  async function runPreview() {
    setBusy('preview')
    setRequestError(null)
    try {
      const result = await adminApi.onboardRepo(buildPayload(form, true))
      setPreview(result)
      setPreviewSignature(signature)
    } catch (error) {
      setPreview(null)
      setPreviewSignature(null)
      setRequestError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  async function runWrite() {
    setBusy('write')
    setRequestError(null)
    try {
      const result = await onWrite(buildPayload(form, false))
      // A refused write comes back 200 with ok:false and errors, not as a throw.
      // Treating it as the new preview is right — it is the server's latest
      // verdict on this exact payload — but it is not a write, and recording it
      // as one would put a "Manifest written" banner on a manifest that isn't.
      setPreview(result)
      setPreviewSignature(signature)
      if (result.written) setWritten(result)
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  return (
    <AdminSection
      title="Onboard a repo"
      description={
        <>
          Describes a new S3 target and writes its{' '}
          <code>repos/&lt;name&gt;/.s3targets.json</code> manifest. Nothing is written
          until a dry run comes back clean.
        </>
      }
    >
      <details className="ams-admin-details">
        <summary>Already registered ({targets.length})</summary>
        <ul className="ams-admin-targets">
          {targets.map((target) => (
            <li key={target.target_id}>
              <code>{target.target_id}</code> · {target.display_name}
              <span className="ams-admin-target-chips">
                <Chip tone={target.has_recording ? 'pass' : 'warn'}>
                  {target.has_recording ? 'Recording' : 'No recording'}
                </Chip>
                {target.discovered && <Chip tone="neutral">Discovered</Chip>}
              </span>
            </li>
          ))}
          {targets.length === 0 && <li className="ams-muted">None.</li>}
        </ul>
      </details>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (canPreview) void runPreview()
        }}
      >
        <div className="ams-admin-form-grid">
          <Field
            label="Repo name"
            hint={
              form.name.trim()
                ? `Manifest goes to repos/${form.name.trim()}/.s3targets.json`
                : 'One path segment — becomes the folder under repos/.'
            }
            error={nameError}
          >
            {({ inputId, describedBy }) => (
              <input
                id={inputId}
                aria-describedby={describedBy}
                className="ams-input"
                value={form.name}
                onChange={(event) => update({ name: event.target.value })}
                placeholder="samplebenefits"
                autoComplete="off"
                spellCheck={false}
              />
            )}
          </Field>

          <Field label="Display name" hint="Shown in the console wherever the target is named.">
            {({ inputId, describedBy }) => (
              <input
                id={inputId}
                aria-describedby={describedBy}
                className="ams-input"
                value={form.display_name}
                onChange={(event) => update({ display_name: event.target.value })}
                placeholder="SampleBenefits — annual limit"
                autoComplete="off"
              />
            )}
          </Field>

          <Field
            label="Target id"
            hint="Folded into the branch name shown on stage, so it is not internal."
            error={targetIdError}
          >
            {({ inputId, describedBy }) => (
              <input
                id={inputId}
                aria-describedby={describedBy}
                className="ams-input"
                value={form.target_id}
                onChange={(event) => update({ target_id: event.target.value })}
                placeholder="samplebenefits-annual-limit"
                autoComplete="off"
                spellCheck={false}
              />
            )}
          </Field>

          <Field
            label="Cache namespace"
            hint="Names the replay recording on disk. Derived from the target id until you edit it."
          >
            {({ inputId, describedBy }) => (
              <input
                id={inputId}
                aria-describedby={describedBy}
                className="ams-input"
                value={form.cache_namespace}
                onChange={(event) => {
                  setNamespaceTouched(true)
                  update({ cache_namespace: event.target.value })
                }}
                placeholder="samplebenefits_annual_limit"
                autoComplete="off"
                spellCheck={false}
              />
            )}
          </Field>
        </div>

        <Field label="User story path" hint="Repo-relative path to the user story this target runs.">
          {({ inputId, describedBy }) => (
            <input
              id={inputId}
              aria-describedby={describedBy}
              className="ams-input"
              value={form.story}
              onChange={(event) => update({ story: event.target.value })}
              placeholder="stories/US-2026-050.md"
              autoComplete="off"
              spellCheck={false}
            />
          )}
        </Field>

        <div className="ams-admin-form-grid">
          <Field label="Core files" hint="One path per line. What the relevance screen must find.">
            {({ inputId, describedBy }) => (
              <textarea
                id={inputId}
                aria-describedby={describedBy}
                className="ams-textarea"
                rows={4}
                value={form.core_files}
                onChange={(event) => update({ core_files: event.target.value })}
                spellCheck={false}
              />
            )}
          </Field>

          <Field
            label="Codegen allowlist"
            hint="One path per line. Files the model may edit — a subset of the core files."
          >
            {({ inputId, describedBy }) => (
              <textarea
                id={inputId}
                aria-describedby={describedBy}
                className="ams-textarea"
                rows={4}
                value={form.codegen_allowlist}
                onChange={(event) => update({ codegen_allowlist: event.target.value })}
                spellCheck={false}
              />
            )}
          </Field>

          <Field label="Testgen allowlist" hint="One path per line. Where generated tests may land.">
            {({ inputId, describedBy }) => (
              <textarea
                id={inputId}
                aria-describedby={describedBy}
                className="ams-textarea"
                rows={4}
                value={form.testgen_allowlist}
                onChange={(event) => update({ testgen_allowlist: event.target.value })}
                spellCheck={false}
              />
            )}
          </Field>

          <Field
            label="Regression suite paths"
            hint="One path per line. Human-authored, and nothing generated may write here."
          >
            {({ inputId, describedBy }) => (
              <textarea
                id={inputId}
                aria-describedby={describedBy}
                className="ams-textarea"
                rows={4}
                value={form.regression_paths}
                onChange={(event) => update({ regression_paths: event.target.value })}
                spellCheck={false}
              />
            )}
          </Field>
        </div>

        <Field
          label="Post-apply command"
          hint="One argument per line, or leave empty. Becomes the migration step in the deployment plan."
        >
          {({ inputId, describedBy }) => (
            <textarea
              id={inputId}
              aria-describedby={describedBy}
              className="ams-textarea"
              rows={3}
              value={form.post_apply_command}
              onChange={(event) => update({ post_apply_command: event.target.value })}
              spellCheck={false}
            />
          )}
        </Field>

        <div className="ams-admin-row-actions ams-admin-actions-end">
          <button
            type="button"
            className="ams-button-secondary ams-button-compact"
            onClick={() => {
              setForm(EMPTY_FORM)
              setNamespaceTouched(false)
              setPreview(null)
              setPreviewSignature(null)
              setWritten(null)
              setRequestError(null)
            }}
          >
            Clear form
          </button>
          {/* Preview is the secondary weight and Write the primary, even though
              Write starts disabled: the primary marks the goal of the form, and
              a disabled one says plainly that the dry run is what unlocks it.
              Red is reserved for the reset controls — spending it on a file
              create would devalue it where it matters. */}
          <button type="submit" className="ams-button-secondary" disabled={!canPreview}>
            {busy === 'preview' ? 'Validating…' : 'Preview manifest'}
          </button>
          <button
            type="button"
            className="ams-button"
            disabled={!canWrite}
            onClick={() => void runWrite()}
          >
            {busy === 'write' ? 'Writing…' : 'Write manifest'}
          </button>
        </div>
        {!complete && (
          <p className="ams-field-hint">
            Name, display name, target id, cache namespace and user story path are all required
            before a dry run.
          </p>
        )}
      </form>

      {requestError && (
        <Banner tone="danger" title="The request failed">
          <p className="ams-admin-banner-body">{requestError}</p>
        </Banner>
      )}

      {stale && (
        <Banner tone="warn" title="Preview is out of date">
          <p className="ams-admin-banner-body">
            The form changed after this dry run. Preview again before writing.
          </p>
        </Banner>
      )}

      {preview && (
        <div className="ams-admin-preview">
          {preview.errors.length > 0 && (
            <Banner tone="danger" title="Rejected — nothing was written">
              <ul className="ams-admin-banner-list">
                {preview.errors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </Banner>
          )}
          {preview.warnings.length > 0 && (
            <Banner tone="warn" title="Warnings">
              <ul className="ams-admin-banner-list">
                {preview.warnings.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </Banner>
          )}
          {written?.written ? (
            <Banner tone="good" title="Manifest written">
              <p className="ams-admin-banner-body">
                Written to <code>{written.manifest_path}</code>. Targets are registered at
                import, so this one is <strong>not active yet</strong> — restart the
                console, then check it appears under "Already registered" above.
              </p>
            </Banner>
          ) : preview.errors.length > 0 ? null : (
            /* Only claim "dry run" when it was one — the rejection banner above
               has already said what happened on a refused write. */
            preview.manifest_path && (
              <Banner tone="info" title="Dry run — nothing written">
                <p className="ams-admin-banner-body">
                  This is what would land at <code>{preview.manifest_path}</code>.
                </p>
              </Banner>
            )
          )}
          {/* Null when the name was rejected outright — there was never a
              manifest to show, and an empty code block would suggest there was. */}
          {preview.manifest && (
            <pre className="ams-admin-json">{JSON.stringify(preview.manifest, null, 2)}</pre>
          )}
        </div>
      )}
    </AdminSection>
  )
}

# `repos/` — the target repositories S3 works against

Every application S3 operates on lives here, one directory per repository.
This is the drop folder: **add a repo directory with a `.s3targets.json`
manifest and S3 registers it at next start — no code edit, no redeploy.**

`apps/` is deliberately *not* this folder. It holds the console and the launch
scripts — the tooling. A repo in here is something S3 changes; an app in
`apps/` is something that does the changing.

## Onboarding a new repository

1. Drop the source in as `repos/<name>/`.
2. Add its change requests to the top-level `crs/` folder. A CR file placed
   there is picked up on the board automatically and lands unassigned, which
   routes it to the manager to assign.
3. Add `repos/<name>/.s3targets.json` declaring what that repo contributes.
4. Put the repo's human-authored regression suite in the top-level `tests/`,
   **not** under `repos/<name>/`. Anything ending `.py` under a repo root
   joins the codegen candidate pool, which would let the pipeline write to the
   one independent check that a CR broke nothing.

That is the whole procedure.

## Manifest

One repo may declare several targets — PolicyCore has two, one per CR.

```json
{
  "targets": [
    {
      "target_id": "samplebenefits-annual-limit",
      "display_name": "SampleBenefits — annual limit lookup",
      "cache_namespace": "samplebenefits_annual_limit",
      "cr": "crs/CR-2026-050.md",
      "core_files": ["repos/samplebenefits/service.py"],
      "codegen_allowlist": ["repos/samplebenefits/service.py"],
      "testgen_allowlist": ["tests/test_s3_samplebenefits.py"],
      "regression_paths": ["tests/test_regression_samplebenefits.py"],
      "post_apply_command": ["{python}", "-m", "repos.samplebenefits.seed"],
      "mutations": [
        {
          "rel_path": "repos/samplebenefits/service.py",
          "old_snippet": "if amount <= limit:",
          "new_snippet": "if amount < limit:",
          "description": "Weakened the boundary check."
        }
      ]
    }
  ]
}
```

| Key | Required | Meaning |
|---|---|---|
| `target_id` | yes | Registry-unique. Folded into the branch name at Step 0, so it is on screen. |
| `cache_namespace` | yes | Registry-unique, non-empty. Becomes the replay recording's filename — rename it and the recording is a miss. |
| `display_name` | no | Shown in the console's target picker. Defaults to `target_id`. |
| `cr` | no | Repo-relative path to the CR this target implements. |
| `core_files` | no | Files relevance must always recall into the prompt. |
| `codegen_allowlist` | no | The blast radius. A path listed here is created if it does not exist yet — that is how a CR adds a new module. |
| `testgen_allowlist` | no | Where the generated suite is written. Must never name a regression suite. |
| `regression_paths` | no | The human-authored suite. The pipeline is forbidden to write here. |
| `post_apply_command` | no | Migration/refresh step after apply. `{python}` is replaced with the running interpreter. |
| `mutations` | no | Seeded bugs for the "prove the tests catch it" beat. `old_snippet` must appear **verbatim in the generated code**, so re-check it after every re-record. |

A manifest that exists but cannot be parsed **raises at import**. It is not
skipped — a repo shipping a manifest is asking to be registered, and silently
ignoring a typo presents as "S3 didn't pick up my repo" with nothing to look
at.

## Every repo carries `ARCHITECTURE.md` and `DESIGN.md`

Each application here documents itself with the same pair, at its own root:

| File | Answers |
|---|---|
| `ARCHITECTURE.md` | **What it is** — purpose, context, components, data model, runtime, and where to look for what |
| `DESIGN.md` | **Why it is shaped that way** — decisions, load-bearing rules, trade-offs, deliberate non-goals |
| `README.md` | How to run it, plus the application-knowledge sections (users, DR, business impact, escalation) |

**These are the read-this-first pair**, for a person or a tool. Anything
answering questions about an application should read them before reading its
source — they carry the intent and the invariants that source alone does not.
A new repo dropped in here should ship both.

One rule if you add them to a new target: a `DESIGN.md` at the **repo root** is
documentation of the application, and `relevance.py` deliberately skips it when
collecting subsystem design docs — a repo is not a subsystem of itself.
`DESIGN.md` in a *subdirectory* is a different thing entirely: it declares a
subsystem, its "## Scope keywords" section is scored against the CR, and it
therefore moves the relevance funnel. Do not put subsystem-shaped scope
keywords in a root-level design doc expecting them to be inert; they are inert
because of the path, not the content.

## What a dropped-in repo gets, and what it doesn't

It gets relevance scoping, CR→target routing, the propose/apply/revert cycle,
the regression beat and the mutation beat.

It does **not** get a committed replay recording — there is nothing to record
against until its CR has been run once, so its first codegen run is a live
call that records itself for every run after. And it does not get a bespoke
structural validator: the three built-in targets carry hand-written file-set
validators in `codegen.py` tuned to their own CR's shape, while a discovered
target uses the generic one. Both are honest defaults.

## One thing that is not a `mv`

`relevance.py::_document()` folds each file's path into the text it scores, so
a repo's directory path is a *scoring input*. Renaming or moving a repo
changes every embedding, reshuffles which files the funnel selects, and
desyncs that selection from the committed recordings in
`s3_enhancement/cache/` — which carry these paths both as file keys and inside
the generated code's own `import` statements. Moving a repo is a path rewrite
across code *and* recordings, done together, then re-verified propose → apply
→ revert per target.

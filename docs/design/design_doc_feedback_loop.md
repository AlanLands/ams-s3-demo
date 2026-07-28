# Close the DESIGN.md feedback loop

**Status: built 2026-07-27** (`s3_enhancement/design_sync.py`, `POST
/api/s3/design-sync`, 16 tests in `tests/test_s3_design_sync.py`). Raised
earlier the same day while documenting the relevance funnel. See "As built"
below for what shipped and what deliberately did not.

## The gap

Stage-1 subsystem screening (`s3_enhancement/relevance.py::screen_subsystems`)
scores each subsystem's `DESIGN.md` "## Scope keywords" section against the CR
text. Those docs decide which subsystems are even *opened*.

**Nothing in the codebase ever writes a `DESIGN.md`.** Verified 2026-07-27:
every reference is a read (`rglob`, `read_text`,
`discover_subsystem_design_docs`). `apply` writes only the proposal's own
files. The `/s3/design-doc` beat drafts a *design document for the CR* as a
downloadable deliverable — it does not update the subsystem docs that drive
screening.

So: code changes on every CR, the docs that gate retrieval never do. Over many
CRs the declared scope drifts from what the subsystem actually contains, and
the gate quietly decays.

## Why it matters more than it looks

The failure mode is **asymmetric and silent**:

- A subsystem wrongly screened **in** just costs tokens. Visible, harmless.
- A subsystem wrongly screened **out** is invisible. Its files are never
  opened, so no downstream check can notice they were missing.
  `verify_core_recall()` will not catch it — that only validates the declared
  core files of the target you already selected.

There is currently no recall check at the subsystem level at all.

## Scope note — why this is not a demo problem

In today's corpus, `DESIGN.md` files exist **only** for the six decoy
`mockapp/systems/legacy_java_platform/*` subsystems. All three demo CRs change
code in `mockapp/core/` and `sandbox/spring-demo/`, neither of which sits under
a documented subsystem. Nothing would need updating on stage. The gap is real
in production, moot in the demo.

## Sketch of the fix

Add a step that treats the design doc as part of the change surface:

1. After codegen produces a diff, ask whether the change alters any
   subsystem's declared scope (new capability, new vocabulary, moved
   responsibility).
2. If so, propose a `DESIGN.md` edit **alongside** the code diff — same
   review-and-apply flow, same "AI suggestion" labelling, developer approves
   or rejects it like any other file.
3. Minimum viable version if step 2 is too much: surface a staleness warning
   when an applied change touches files under a subsystem whose `DESIGN.md`
   has not been modified in N CRs.

## As built

The open question above — same proposal or separate — turned out to be settled
by a constraint rather than taste, and the rest followed from two rules.

**Separate proposal, forced.** `codegen.py::_validate_file_set` requires the
model's returned file set to match what the relevance funnel selected, and the
committed replay recordings encode that exact set. Adding `DESIGN.md` to the
code proposal desyncs every recording and kills the beat with `LLMError:
codegen returned unexpected file set` — in replay, offline, no live fallback
(CLAUDE.md's "file paths are load-bearing"). So a flagged doc is staged as its
own proposal via the new `codegen.stage_files_as_proposal()` seam, and rides
the existing diff review and `apply_change()` path unchanged. No second apply
mechanism exists.

**Two stages, cheap gate first.** `find_affected_subsystems()` is pure path
arithmetic — no file reads, no provider call — and returns empty unless an
applied file sits under a `DESIGN.md`-bearing directory. Only then does
`review_design_doc()` ask the model whether the doc survived the change. A
test asserts all three demo CRs produce zero impacts, so the feature makes no
provider call at all during a demo.

**Fails soft, by requirement.** It runs straight after Apply, the most
load-bearing beat. `complete()` ignores `LLM_MODE`, so a cold cache with no
reachable provider raises. Every provider call is caught and degraded to
`checked: false` with a reason; the endpoint returns 200, never 5xx. Verified
end to end: offline → `checked: false`, apply still succeeded.

**No new button.** Per the standing UI rule, the console calls `/design-sync`
automatically once Apply succeeds, fire-and-forget, and renders a card in the
existing post-apply area only when something is stale. The developer never
clicks anything to get the check.

**Content-hash cached, not pinned.** No fixed `cache_key` — the input is a real
diff against a real doc and varies per change, same reasoning as
`repo_match.suggest_target_repo`. A pinned key would serve one recorded verdict
forever.

### What deliberately did not ship

- **No committed replay recording.** This beat has never been recorded, so the
  first live invocation makes a real provider call. Harmless today because no
  demo CR reaches it — but it means the feature is **unexercised on stage** and
  should not be demoed without recording it first.
- **No staleness-warning fallback** (step 3 of the original sketch). The full
  review supersedes it; revisit only if provider cost becomes a concern.
- **No subsystem-level recall check.** The asymmetric silent-failure problem
  described above is *mitigated* by keeping docs current, not solved. A
  wrongly screened-out subsystem is still invisible. That remains open.

### Worth knowing before extending it

The UI path is genuinely untested against a real end-to-end run, because no
current CR touches a documented subsystem. To exercise it you would need a CR
that changes a file under `mockapp/systems/legacy_java_platform/*` — all of
which are decoys today.

## Why it is worth doing beyond correctness

It converts the current weakness into the strongest form of the
differentiation argument against GitLab Duo (see
`docs/S3_RANKING_VS_DUO.html`). Today the honest pitch is "your architecture
docs are a control surface." With this closed, it becomes "your architecture
docs are a control surface that the system keeps current" — a maintained
control rather than a wiki page that rots. That is a materially stronger claim
in a governed-change conversation.

## Related

- `docs/S3_RANKING_VS_DUO.html` / `.pdf` — the funnel and the Duo comparison
- `docs/S3_REPO_SELECTION.html` / `.pdf` — repo matching and what is/isn't measured
- `s3_enhancement/relevance.py` — `screen_subsystems`, `discover_subsystem_design_docs`
- `tools/verify_s3_live.py::check_design_doc_gate_screens_all_legacy_subsystems`

# S3 — Enhancement Delivery (15 min)

> **Read first — two things this file predates.**
>
> 1. **The console is the React app on :5173**, not Streamlit. Where the notes
>    below say "Streamlit console" or "back in Streamlit" for the *driver*
>    surface, read "the console at :5173". `demo/run_s3.sh`'s Streamlit view
>    still exists as a legacy fallback. The MapleSure PolicyCore portal on
>    :8501/sl_policycore genuinely *is* Streamlit — that one is not a slip.
> 2. **Artifacts open in a pop-up.** Release notes, the deployment plan, the
>    design doc, the scenario table, the test checklists, the mutation diff and
>    the traceability matrix no longer stack down the page. Each stage shows
>    the button, a one-line verdict, a summary chip, and a **View…** button
>    that opens the body in a modal. Never say "scroll down to see the release
>    notes" — press View, read, close.
>
> Vocabulary: this is Group Retirement Services, not P&C. PolicyCore speaks
> **amendment** (not endorsement), **plan tier** (not coverage tier),
> **contribution** (not premium), **plan sponsor** (not policyholder).
> CR-2026-041 is **"Plan Tier Upgrade Option"**.

**Pain**: even small change requests carry disproportionate overhead — impact
analysis, the actual change, tests, and documentation are all manual, slow steps
that compound across a large application portfolio.

**Architecture note (approved exception)**: S3 runs codegen **live-primary** with a
recorded replay as a silent safety net — the deliberate inverse of CLAUDE.md's
cached-primary rule, chosen knowingly for this scenario only. Tests, the app, and
the before/after are always genuinely live; only the generative beats carry the net.

**Option C, second instance of the same approved exception**: beat 4 (codegen +
test loop) can additionally run through a **live agent harness** (Claude Code or
Codex CLI, headless, in a visible second terminal) instead of the console's
`codegen.py`/`testgen.py` pipeline — see `s3_enhancement/harness.py` and
`demo/run_s3_harness.sh`. This is the Tier-2 story: not a bespoke prompt wrapper,
but an off-the-shelf agent harness doing autonomous delivery against the real repo,
live. Beats 1-2 and 7 stay on the governed `common/llm.py` pipeline unchanged —
that split *is* the talk track (see below). The unmodified `codegen.py`/`testgen.py`
pipeline remains available as a deep fallback (rung 3) via the existing console
buttons if the harness beat is skipped or fails.

**Demo beat** (`apps/run-console.sh` for the driver console on :5173; the
MapleSure PolicyCore portal opens separately on :8501/sl_policycore as "the
client's app"; a second terminal pane runs `run_s3_harness.sh` for beat 4 if
using the harness path):
0. *(optional, 30 seconds, lands well)* Show the board itself. **AMS-1045 is
   sitting there unassigned and nobody seeded it** — dropping
   `crs/CR-2026-045.md` into the repo opened its own ticket, keyed off the CR
   id, deliberately unassigned so it routes to a manager. Assign it as
   **Manager / 9000**, then press **Reassign** and change your mind:
   assignment is a manager decision, reversible, and enforced server-side —
   an engineer's session cannot call the endpoint at all.
1. Show the MapleSure PolicyCore portal: contracts, claims, plan sponsor,
   monthly contribution. **No tier-upgrade feature exists.** (live, zero risk)
2. Open CR-2026-041 and ask the audience to **pick the new top tier's name** — the
   controlled free variable. It only ever lands in string labels, it cannot break
   the run, and it proves nothing is canned.
3. AI impact analysis + effort estimate (~40h-class / P4-equivalent) over the real
   codebase. (live LLM call, read-only)
   Use the transparency panel here — press **View file selection** to open it.
   This app is a small modern Python plan/claims app (11 files) sitting in
   front of a 50-file legacy Java estate
   (`repos/policycore/systems/legacy_platform/`), mirroring the kind of heterogeneous
   stack the client runs in AMS — a real system underneath, not a slide. The
   candidate pool for this CR is **58 files**; the funnel picks four.
   Selection runs in two stages, live: first the AI reads each
   subsystem's `DESIGN.md` (billing, underwriting, risk, settlement, audit,
   reporting, plus PolicyCore's own `enrolment` — open one on screen) and
   screens out any subsystem whose declared scope doesn't match the CR, before
   a single one of that subsystem's Java files is even opened. Point at the
   subsystem screen in the panel — for this CR **all seven subsystems screen
   out** at that stage. Only what survives goes on to file-level scoring
   against the CR text, which is what actually picks the handful of Python
   files that affect the tier-upgrade path. The token-count panel then
   shows the real scoped prompt size versus a naive whole-app-context
   baseline live, so the scaling story is measured rather than asserted.
4. **Money shot.** Either: (a) the console pipeline generates the change and it
   streams on screen, then the validated files apply to the repo; or (b) switch to
   the second terminal pane and press Enter on `run_s3_harness.sh` — the agent
   harness reads the CR and `repos/policycore/CLAUDE.md`'s contract, edits the files itself,
   and narrates what it's doing live. Either way, back in the console, click "Load
   latest harness run" (harness path only) and check "I've reviewed this AI-generated
   change" before beat 7 unlocks.
5. AI-generated tests run **live in pytest** and pass green — the harness runs its
   own pytest pass, and the console independently reruns pytest too before
   accepting the beat. (always genuinely live)
6. The MapleSure PolicyCore portal now has the plan-tier upgrade flow — click it,
   move a contract up a tier, **the monthly contribution recalculates**. (always
   genuinely live)
7. AI release notes + doc blurb, shown with the mandatory label:
   *"AI suggestion — verify with your specialist before applying."* Press
   **View** to open them; three audience-specific notes (client, ops, user
   guide), not one blob.

**Say explicitly at beat 4**: "The AI is writing this change right now against the
real codebase — and a developer reviews everything before it ships. What you'll see
next is the generated tests actually executing." Human-in-the-loop framing stays
mandatory even though generation is genuinely live. If running the harness path,
add: "This isn't a script we wrote to call an API — this is an off-the-shelf coding
agent doing real autonomous delivery against our codebase, the same product
experience your own developers would get."

**Talk track for the harness beat, in order** (lands the access-tier ask):
"governed AI tooling we built" (beats 1-3, 7) → "off-the-shelf agent harness doing
autonomous delivery" (beat 4, harness path) → "in your environment this is GitLab
Duo today, an approved agent harness tomorrow." If asked how this scales past one
small demo app: the naive single-prompt-full-file-dump pattern (what `codegen.py`
does) would blow context windows and rate limits past a handful of files — the
agent harness *is* the answer, since it reads only what it needs instead of
dumping a whole codebase into one prompt. Say this if asked, don't volunteer it.

**Fallback ladder** (rehearse until automatic):
*Codegen pipeline path (the console):*
1. Live call fails or generates invalid code → **auto-replay kicks in silently** —
   same streaming UI, audience sees nothing. Carry on.
2. Something still looks wrong → rerun the beat with `LLM_MODE=replay` set (~10s).
3. Total loss → narrate from screenshots captured during rehearsal, or from
   `demo/DEMO_TEST_GUIDE.md`. (`docs/design/img/s3/` no longer exists; there
   is no committed screenshot set — capture your own before demo day.)

*Harness path (second terminal, `run_s3_harness.sh`):* the default invocation
(no flags) replays the rehearsed recording — deterministic, offline, cannot
fail live. `--live` is the opt-in that actually runs the agent CLI; unlike the
pipeline's silent auto-replay, a `--live` failure is a **visible terminal
moment** — the presenter decides live, not the code:
1. `demo/run_s3_harness.sh --live Elite` fails (touched an unexpected file,
   tests red, timeout, crash) → visible FAIL banner in the terminal. Presenter
   narrates it as a live check working as designed, then:
2. Rerun in the same pane without `--live`: `demo/run_s3_harness.sh Elite`
   (~10s, replays the rehearsed recording, still runs a real live pytest pass).
3. Still not right, or short on time → abandon the harness beat entirely and use
   the console's "Generate the change" / "Generate tests + run" buttons — today's
   unmodified pipeline, zero new code, zero new risk.

**Rehearsal gate (hard rule)**: `python -m tools.verify_s3_live --gate 10` — codegen
must pass **live ≥ 9/10 consecutive cycles** before demo day, otherwise present the
whole scenario in `LLM_MODE=replay` without hesitation. Log every rehearsal run.
If presenting the harness path, rehearse it to the same ≥9/10 bar (`--gate` extended
to the harness path — see `tools/verify_s3_live.py`) and pre-authenticate/pre-trust
both `claude` and `codex` CLIs on the actual presenter machine well before demo day —
first-run auth/trust prompts will break headless mode live. **Decision point**: if
the harness beat isn't rehearsed to that bar by demo day, present S3 on the
console pipeline only (rung 3) — it's fully proven and zero-risk on its own.

**Demo-day prep, in order**:
1. **Confirm `demo/reset_s3.sh` actually runs** — watch it print its success
   line, don't assume. It restores PolicyCore with `git checkout HEAD --
   repos/policycore/...`, so it only works while HEAD carries those paths: if a
   target has just been moved and the move is uncommitted, it dies on `error:
   pathspec ... did not match any file(s) known to git` and stops before
   reseeding, before wiping `.cache/llm` and before clearing the ticket
   timeline — which would leave steps 2–3 operating on an un-reset tree.
   Committing the move is the fix. The ClaimsPortal and EnrolDirect resets `cp`
   from `.baseline/` and never depend on HEAD. `/admin` reports the condition
   as `reset_blocked_reason` rather than failing halfway.
2. Morning of: `demo/reset_s3.sh`, then re-record the replay cache against the exact
   repo state — `python -c "from s3_enhancement.warm_cache import record; record()"`.
3. `demo/reset_s3.sh` again so the app starts featureless (record leaves the
   generated feature applied).
4. `python -m tools.verify_s3_live --skip-live` — all seven architecture checks green.
   (Its `reset_s3.sh` check is the automated version of step 1 — if it goes
   red, commit the move rather than editing the check.)
5. `demo/warm_s3_cache.sh` last, after the final reset.

*(A step here used to hand off to S4 by running
`python -m s4_knowledge.make_snapshot`. S4 is not part of this repo — the
five other scenarios were split out on 2026-07-23 and are built elsewhere.
There is no S4 hand-off to prepare.)*

**Metric/value**: collapses a change-request cycle that normally spans analysis,
dev, test-writing, and doc updates into one continuous, reviewable flow.

**Roadmap**: the demo CR itself is intentionally small/contained, but the scoped
file-selection and token-count panels are the real answer to "how does this scale" —
point at the 58-file candidate pool (11 real Python app files + the 50-file
legacy Java platform and its design docs), and the scoped-vs-naive numbers, if
asked. What's still roadmap, not built: the design-doc gate + TF-IDF selection
is tuned for this one CR/app, not yet tuned across a large multi-CR backlog or
a much bigger real codebase.

**If asked "how do you add another application to this?"** — this is now a
real answer, not a roadmap one. Drop the repo into `repos/`, put its CRs in
the top-level `crs/`, and add a `repos/<name>/.s3targets.json` manifest
declaring what the pipeline may read and write. The target registers itself at
next start; the CR opens its own ticket, unassigned, for a manager to route.
The manifest is required because `codegen_allowlist`, `core_files` and the
seeded-bug mutations are *decisions*, not things inferable from source — and a
broken manifest raises at import rather than being silently skipped. There is
a validate-and-write form of this on the manager's `/admin` panel
("Onboard a repo"), which is honest that a written manifest needs a console
restart to take effect. See `repos/README.md`.

**If asked — "how does this work on [mainframe / .NET / other stack]?"** Don't
volunteer this, answer if asked. Today's demo is deliberately one stack (modern
Python, with a legacy Java estate alongside it for the scaling story above) —
don't imply every stack is already built. The honest answer: the retrieval and
generation approach generalizes (read the relevant scope, generate a scoped
change, validate, test), but each stack needs its own integration attempt —
different repo/checkout tooling, different test runner, different
static-analysis/validation hooks. For mainframe specifically: there are
established tools in that space (IBM's zAdviser, Broadcom, and notably Zowe —
the open framework for exposing z/OS to modern tooling/APIs) that this kind of
approach would sit on top of, the same way this demo sits on GitLab for
Python/Java. We haven't built or rehearsed a mainframe integration; we'd want a
short discovery pass with the client's mainframe team — what checkout/build
tooling they already run, what a "test pass" means in their environment, any
data-masking/access constraints — before committing to a timeline. Land the
point, don't over-promise: "we've thought through what this takes for other
stacks, not just this one app" is the message, not a live demo of it.

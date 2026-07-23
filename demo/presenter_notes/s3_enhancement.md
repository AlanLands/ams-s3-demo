# S3 — Enhancement Delivery (15 min)

**Pain**: even small change requests carry disproportionate overhead — impact
analysis, the actual change, tests, and documentation are all manual, slow steps
that compound across a large application portfolio.

**Architecture note (approved exception)**: S3 runs codegen **live-primary** with a
recorded replay as a silent safety net — the deliberate inverse of CLAUDE.md's
cached-primary rule, chosen knowingly for this scenario only. Tests, the app, and
the before/after are always genuinely live; only the generative beats carry the net.

**Option C, second instance of the same approved exception**: beat 4 (codegen +
test loop) can additionally run through a **live agent harness** (Claude Code or
Codex CLI, headless, in a visible second terminal) instead of the Streamlit
`codegen.py`/`testgen.py` pipeline — see `s3_enhancement/harness.py` and
`demo/run_s3_harness.sh`. This is the Tier-2 story: not a bespoke prompt wrapper,
but an off-the-shelf agent harness doing autonomous delivery against the real repo,
live. Beats 1-2 and 7 stay on the governed `common/llm.py` pipeline unchanged —
that split *is* the talk track (see below). The unmodified `codegen.py`/`testgen.py`
pipeline remains available as a deep fallback (rung 3) via the existing Streamlit
buttons if the harness beat is skipped or fails.

**Demo beat** (`demo/run_s3.sh` for the driver console; the MapleSure app opens
separately as "the client's app"; a second terminal pane runs `run_s3_harness.sh`
for beat 4 if using the harness path):
1. Show the MapleSure portal: policies, claims. **No coverage-upgrade feature
   exists.** (live, zero risk)
2. Open CR-2026-041 and ask the audience to **pick the new top tier's name** — the
   controlled free variable. It only ever lands in string labels, it cannot break
   the run, and it proves nothing is canned.
3. AI impact analysis + effort estimate (~40h-class / P4-equivalent) over the real
   codebase. (live LLM call, read-only)
   Use the transparency panel here: this app is a small ~6-file modern Python
   policy/claims app sitting in front of a ~50-file legacy Java estate
   (`mockapp/systems/legacy_java_platform/`), mirroring the kind of heterogeneous
   stack the client runs in AMS — a real system underneath, not a slide.
   Selection runs in two stages, live: first the AI reads each legacy
   subsystem's `DESIGN.md` (billing, underwriting, risk, settlement, audit,
   reporting — open one on screen) and screens out any subsystem whose
   declared scope doesn't match the CR, before a single one of that
   subsystem's Java files is even opened. Point at the "Subsystem design-doc
   screening" expander in the panel — for this CR all 6 legacy subsystems
   screen out at that stage. Only what survives goes on to file-level scoring
   against the CR text, which is what actually picks the handful of Python
   files that affect the coverage-upgrade path. The token-count panel then
   shows the real scoped prompt size versus a naive whole-app-context
   baseline live, so the scaling story is measured rather than asserted. The
   "API usage by beat" bar chart at the bottom of the page (beat 7) makes the
   same point beat-by-beat: real token totals for analysis, generate, test, and
   document, not one aggregate number.
4. **Money shot.** Either: (a) the Streamlit pipeline generates the change and it
   streams on screen, then the validated files apply to the repo; or (b) switch to
   the second terminal pane and press Enter on `run_s3_harness.sh` — the agent
   harness reads the CR and `mockapp/CLAUDE.md`'s contract, edits the files itself,
   and narrates what it's doing live. Either way, back in Streamlit, click "Load
   latest harness run" (harness path only) and check "I've reviewed this AI-generated
   change" before beat 7 unlocks.
5. AI-generated tests run **live in pytest** and pass green — the harness runs its
   own pytest pass, and the Streamlit console independently reruns pytest too before
   accepting the beat. (always genuinely live)
6. The MapleSure app now has the Upgrade Coverage flow — click it, upgrade a
   policy, premium recalculates. (always genuinely live)
7. AI release notes + doc blurb, shown with the mandatory label:
   *"AI suggestion — verify with your specialist before applying."*

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
*Codegen pipeline path (Streamlit):*
1. Live call fails or generates invalid code → **auto-replay kicks in silently** —
   same streaming UI, audience sees nothing. Carry on.
2. Something still looks wrong → rerun the beat with `LLM_MODE=replay` set (~10s).
3. Total loss → screenshots in `docs/design/img/s3/` (capture during rehearsal).

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
   the Streamlit "Generate the change" / "Generate tests + run" buttons — today's
   unmodified pipeline, zero new code, zero new risk.

**Rehearsal gate (hard rule)**: `python -m tools.verify_s3_live --gate 10` — codegen
must pass **live ≥ 9/10 consecutive cycles** before demo day, otherwise present the
whole scenario in `LLM_MODE=replay` without hesitation. Log every rehearsal run.
If presenting the harness path, rehearse it to the same ≥9/10 bar (`--gate` extended
to the harness path — see `tools/verify_s3_live.py`) and pre-authenticate/pre-trust
both `claude` and `codex` CLIs on the actual presenter machine well before demo day —
first-run auth/trust prompts will break headless mode live. **Decision point**: if
the harness beat isn't rehearsed to that bar by demo day, present S3 on the
Streamlit pipeline only (rung 3) — it's fully proven and zero-risk on its own.

**Demo-day prep, in order**:
1. Morning of: `demo/reset_s3.sh`, then re-record the replay cache against the exact
   repo state — `python -c "from s3_enhancement.warm_cache import record; record()"`.
2. `demo/reset_s3.sh` again so the app starts featureless (record leaves the
   generated feature applied).
3. `python -m tools.verify_s3_live --skip-live` — all seven architecture checks green.
4. **After** S3's live run succeeds in the room and before S4 starts:
   `python -m s4_knowledge.make_snapshot` — S4 reverse-engineers the app *with* the
   feature the audience just watched appear. Never run reset_s3.sh between S3 and S4.

**Metric/value**: collapses a change-request cycle that normally spans analysis,
dev, test-writing, and doc updates into one continuous, reviewable flow.

**Roadmap**: the demo CR itself is intentionally small/contained, but the scoped
file-selection and token-count panels are the real answer to "how does this scale" —
point at the ~56-file estate (6 real Python app files + the ~50-file legacy Java
platform), the scoped-vs-naive numbers, and the per-beat token bar chart if asked.
What's still roadmap, not built: the design-doc gate + TF-IDF selection is tuned
for this one CR/app, not yet
tuned across a large multi-CR backlog or a much bigger real codebase.

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

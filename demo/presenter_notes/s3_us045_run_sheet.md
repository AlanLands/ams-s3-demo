# S3 — US-2026-045 run sheet (15 min)

The timed script for the **EnrolDirect prospect-access** walkthrough, written
against Seetha's direction on the 2026-08-03 review call.

> `s3_enhancement.md` in this folder is the *other* scenario — PolicyCore's plan-tier
> upgrade (US-2026-041). It predates this walkthrough and scripts a different story,
> a different app and a different money shot. Rehearse from **this** file; keep that
> one for its fallback ladder and its "how does this scale / other stacks" answers,
> which still apply.

---

## The one instruction the whole run hangs off

Seetha asked for this four separate times, in different words each time:

> *"we have to show one slide — not one slide, one tab — what this ask is and then
> what AI is expected to do… so that when we are talking through, you can correlate:
> hey look, as I mentioned in the scenario description, AI is expected to do this;
> look, this is what it is doing."*

So **beat 0 is not the console**. It is `docs/S3_SCENARIO_OVERVIEW.pdf`, open in its
own browser tab before you share your screen. Every console beat afterwards is a
callback to a numbered step on that page. Her reasoning, verbatim: the audience is
senior, largely non-technical, *"and they didn't see this interface before"* —
without the setup, *"that experience will be lost."*

The second half of the same instruction is **reconcile as you go**: after each stage,
say what just happened against what you promised on the overview. Not one summary at
the end.

---

## Before you present

| | |
|---|---|
| Reset | `demo/reset_s3.sh` — watch for its success line, don't assume |
| Warm | `demo/warm_s3_cache.sh` **last**, after the final reset |
| Processes | `apps/run-console.sh` (:5173 — *not* :8000), `apps/run-enroldirect.sh` (:8083) |
| Tabs open, in this order | 1 · `docs/S3_SCENARIO_OVERVIEW.pdf` 2 · EnrolDirect :8083 3 · console :5173 |
| Logins | Ravi Kumar **1001** (engineer) · Priya Nair **1003** (tester) · Manager **9000** |

Console stages are role-gated: the engineer sees Board / Target selection / Generate
the change / Draft design doc; the tester sees Board / Draft design doc / Generate
tests + run / Draft release notes. You will log out and back in once, between beat 7
and beat 8 — rehearse that switch so it is not dead air.

---

## The run

### 0 · Scenario overview — 3:00 · *the PDF tab, not the console*

The PDF is nine pages; **beat 0 uses only the first three.** Page 1 is the ground:
what S3 — enhancement delivery — is, why the insurer is invented, what EnrolDirect
does, and the estate row showing the sponsor and PolicyCore behind the rule and
DocumentHub / NightlyBatch / IntegrationBridge in front of it. Page 2: the change
itself — members and guests get in today, prospects are refused, the change adds one
rule. Page 3: the five stages, each with what AI does, where a person signs off, and
the impact.

**Page 1 is not optional.** Without it the demo reads as a code exercise, and beat 3's
cross-team result has nothing to land against — call back to that estate row when the
analysis names DocumentHub.

Pages 4–8 are one page per stage — impact analysis, target selection, code generation,
test, release — each showing how that stage actually works. **Do not walk these on the
day.** They are there to answer a question without you leaving the demo, and to hand
out afterwards. Page 9 is what the run gives you, in numbers.

Rebuild it with `python -m tools.render_scenario_overview` after editing the copy in
that script — the diagrams are generated, and the build fails if any label outgrows
its box or a page overflows.

Land the sentence Seetha herself scripted: *"currently only existing members versus
guests have the ability to enrol electronically, but not for the prospects, and the
change is required to extend this capability to prospects — that is the change, all
about."*

Do not open the console until this page is done.

### 1 · The application, refusing — 1:00 · *EnrolDirect tab*

Select the prospect. The refusal comes back in red. *"This is what the application
does today."* Nothing else on this screen — you come back to it at beat 9.

### 2 · The board — 1:00 · *console, Ravi Kumar / 1001*

AMS-1045 sitting in To Do. Open it: business objective, target member type,
acceptance criteria — **the client's own user story**, not something we wrote. Say
that nobody seeded this ticket; dropping the story into the repo opened it and put it
on the owning engineer's board.

### 3 · Impact analysis — 3:00 · **the beat with the most in it**

Press it, then narrate over the run:

- *Callback:* "step 1 on the overview — AI-assisted requirement analysis." It reads
  the user story **and** the source code together.
- It comes back with **clarifying questions**. Answer one on screen. This is the
  human gate on step 1 — nothing proceeds until a person answers.
- **Say the ticket moved by itself.** It was in To Do; running the analysis moved it
  to In Progress. Seetha: *"don't lose that opportunity."*
- **Cross-team impact is in the result, not behind a button** (changed after her
  objection). Five downstream systems are inventoried; **one — DocumentHub — actually
  has to change code**, and the others are named with the reason they don't. Land
  that distinction: the estate map is not the ticket list.
- Impacted components, effort and priority are on screen. *Callback:* step 2.

Then **consolidate before moving on**: "so AI has read the story, read the code,
asked what it needed, sized it, and told us which other team we owe work to."

### 4 · Target selection → Generate the change — 1:30

Repo resolves from the story; check out. Then generate. Say clearly: this is a
**feature branch**, nothing is applied to the repository yet, and nothing is
committed.

### 5 · The diff and the peer review — 2:30 · **Seetha called this "very important"**

Pick a **small, light** change — not the biggest file.

> *"green is the added one, red is the removed one — just mention it, and this is how
> AI code is written, now we need to validate."*

Then do the human-in-the-loop live: **ask the AI why it made that change**, on screen,
and read the answer out. Her point is that the audience needs to see that peer review
still exists when AI writes the code.

Mention — do not demonstrate — that reject is there and returns an alternative
proposal. She was explicit: *"don't struggle to create that rejection option also."*

Then apply. **Do not walk through what the code does.** Her framing: *"the point is
not to explain what is written in the code, but to give a glimpse of how AI can create
the change and compile all the code changes in one place for the deployment"* — the
people at the top have no code understanding.

### 6 · Apply → the app restarts → it works — 1:00

Apply to the repo. The console restarts the target app itself. Back to the EnrolDirect
tab: same prospect, now admitted. *Callback:* the red from beat 1, now green.

If the restart reports it could not be done, say so and reload manually — the banner
tells the truth about which code is running, don't talk over it.

### 7 · Design doc → hand to QA — 0:30

Generate, View, close. Interface logic, affected modules, suggested QA focus. Move the
ticket to QA. Log out.

### 8 · QA — 2:30 · *console, Priya Nair / 1003*

Order matters here, and it is the point:

1. **Scenarios first** — positive, boundary, negative, regression. Open one: preconditions
   and test data. The tester can edit or add. **Approve the test plan** — *before any
   test code exists*. That is the human gate on step 4.
2. **Generate tests + run.** Live pytest.
3. **The seeded bug fails, for real** — not mocked. Show the error.
4. **Regression suite** — the checked-in, human-authored suite AI is not allowed to write
   to. Members and guests keep working, unchanged, alongside the new prospect path.
   *(27 tests as of 2026-08-04 — check the number on the day rather than quoting this.)*
5. **Traceability matrix.** Some rows are deliberately **not automated**. Seetha asked
   for the reasoning to be voiced: not everything can be automated — mainframe
   dependencies, cross-system dependencies — so those rows are accommodated as manual
   test spaces.

### 9 · Commit, push, release — 1:00

Commit and push is gated on the tests actually having passed. Release note, deployment
plan, rollback criteria, commit reference.

**Do not open CI/CD.** *"I don't want to go to that SDLC pipeline again."* If asked, the
answer is one sentence: a YAML file is already configured on the target branch, and
pushing triggers it automatically.

Board → **Done**. *"That concludes the enhancement."*

---

## Optional beat — the QA-fail round trip

Built and merged (`cc396f0`): QA fails the ticket, it goes **back to In Progress**, and
the developer it returns to is derived from the ticket's own assignee history.

Seetha asked for it — *"in real-time in project, in a few cases we will be going across
this symbol and back and forth also"* — and then released you from it in the same
breath: *"you can amend that way, but it's overall good; in interest of time, let's
continue."*

It costs about two minutes you do not have. **Default: leave it out**, and mention in one
sentence at beat 8 that a QA failure hands the ticket straight back to the developer who
built it. Run it only if you have finished beat 9 inside 13 minutes in rehearsal.

---

## Timing

The 2026-08-03 walkthrough ran **over 15 minutes with no interruptions**, and the slot is
~15. Seetha: *"it takes so long to walk through this scenario — it will take more than 15
minutes unless somebody interrupts you."*

The budget above totals 17:00 including the overview, which grew to 3:00 when the
orientation page went in front of it. Something has to give. Cut in this order:

1. The optional QA-fail beat (already out).
2. Beat 5 down to 1:30 — one diff, one question to the AI, apply.
3. Beat 3 down to 2:30 — answer the clarifying question, name the cross-team result, skip
   the effort/priority detail.

**Do not cut beat 0.** It was the single most repeated ask on the call, and every callback
in the run depends on it.

---

## Risks on the day

- **Too many enabled controls on the in-progress card.** Her words: *"there could be
  chances we'll be clicking somewhere and the system would break."* Re-running impact
  analysis on a ticket past To Do now asks for confirmation first — but it still needs a
  reset to recover if you confirm. Don't.
- **A cold cache makes live calls mid-run.** `warm_s3_cache.sh` is per-beat and per-target
  now and prints loudly on failure — read that output, don't assume a warm cache.
- **The clarifying-question beat needs an answer typed.** Know what you are going to type
  before you are on screen.

---

## Still open against her feedback

- **Word export of the design doc** — asked for, with a document template: table of
  contents, version number, header/footer and a logo. Today it is PDF only. Not on the
  critical path for this run sheet. Note the branding constraint: her answer to "should we
  use client names" was *"we can mimic and mock-up"* — build it as **MapleSure**, not
  client branding.
- **Retitling the release document "Change Request"** — she asked; held by the project
  owner on 2026-08-03. Do not apply without asking.
- **Highlighting which AI skills were used**, somewhere around impact analysis. Raised for
  the development scenario; not built here.
- **Q&A with the client closes 6 August 2026.** Anything needing clarification goes before
  then.

# S3 Pipeline — How It Works, Start to Finish

Every beat below runs in this order, on one ticket. Three "who" tracks matter
throughout: **System** (deterministic, no LLM call — table lookups, derived
documents, git-shaped state machines), **AI** (a model call, always reviewed
before anything is trusted), and **Human** (a developer, then a tester —
the ticket hands off between them partway through, and the tester's stages
are physically locked until that hand-off happens).

```
 PHASE 1 · INTAKE
 ┌─────────────────────────────────────────────────────────────┐
 │ 1. Ticket opens                              [System]        │
 │    ↓ CI → application → owning team → repo, by table lookup. │
 │      No model call. Nothing to confirm.                      │
 │                                                                │
 │ 2. Impact analysis + effort estimate         [AI + Developer] │
 │    ↓ A vague ticket gets a clarifying question first (max 2   │
 │      turns), not a confident guess.                           │
 └─────────────────────────────────────────────────────────────┘
                                ↓
 PHASE 2 · BUILD                                  (Developer)
 ┌─────────────────────────────────────────────────────────────┐
 │ 3. Generate code                             [AI]             │
 │    ↓ Scoped by the relevance funnel — only files it selected   │
 │      go to the model. Token panel shows scoped vs. naive cost. │
 │                                                                │
 │ 4. Review file-by-file: Ask / Apply / Reject [Developer]       │
 │    ↓ A rejection records a reason to the ticket's audit trail  │
 │      and is excluded from Apply.                               │
 │                                                                │
 │ 5. Apply                                     [Developer]        │
 │    ↓ The target app's running state changes for real.          │
 │      (Revert, per-file or all, stays available from here on.)  │
 │                                                                │
 │ 5b. Branch → commit → push                  [System, modelled] │
 │    ↓ Commit is gated server-side on the ticket's own test       │
 │      results — the console can't just assert "tests passed."   │
 │      Nothing here runs git for real (see Section 4).           │
 └─────────────────────────────────────────────────────────────┘
                                ↓
                    ═══ HAND-OFF: Developer → Tester ═══
              (ticket moves to the QA column; developer is now
               locked out of the test stage below)
                                ↓
 PHASE 3 · VERIFY                                   (Tester)
 ┌─────────────────────────────────────────────────────────────┐
 │ 6b. Design doc: change map + PDF             [System + AI]      │
 │    ↓ The change-map diagram is derived (no LLM) from the        │
 │      changed-file set; the narrative around it is drafted.      │
 │                                                                  │
 │ 7. Draft test scenarios → tester approves    [AI + Tester]      │
 │    ↓ QA reviews *what will be checked*, in prose traced to the  │
 │      CR's acceptance criteria, before any test code exists.     │
 │                                                                  │
 │ 8. Generate tests → run → mutation-proof     [AI + System]      │
 │    ↓ A seeded bug proves the generated suite actually catches   │
 │      a regression, not just that it exists.                     │
 │                                                                  │
 │ 9. Run the regression suite                  [System]           │
 │    ↓ Human-authored, pre-existing, and the pipeline can          │
 │      physically never write to it. Still green → the CR cost    │
 │      nothing that already worked.                                │
 │                                                                  │
 │ 10. Build the traceability matrix            [System]            │
 │    ↓ Every acceptance criterion, the scenarios planned for it,   │
 │      the tests that ran, and the result — derived, not drafted.  │
 │                                                                  │
 │ 11. Design-doc drift check                   [System]            │
 │    ↓ Runs automatically after Apply — not by remembering to      │
 │      press a button.                                              │
 └─────────────────────────────────────────────────────────────┘
                                ↓
 PHASE 4 · SHIP                                      (Tester)
 ┌─────────────────────────────────────────────────────────────┐
 │ 12. Release notes (3 audiences) + deploy plan [AI + System]      │
 │    ↓ One note per reader (client / ops / user guide). The       │
 │      deploy order is derived from the change's own service      │
 │      graph — callee before caller — not drafted.                 │
 │                                                                  │
 │ 13. Release record → attach to ticket → Done  [System]           │
 │    ↓ Everything the run proved, in one PDF — including its       │
 │      "Not evidenced by this release" block, deliberately.        │
 └─────────────────────────────────────────────────────────────┘
```

---

## 1. Phase 1 — Intake

**Ticket routing (beat 1)** never calls a model. A ticket carrying a
ServiceNow Configuration Item resolves to an application, its owning team,
and its repo by a deterministic table lookup (`s3_enhancement/routing.py`,
`applications.py`). If the CI is missing or unknown, routing falls back to
an AI repo-match step that carries its own confidence gate — but the
deterministic path runs first specifically because it can't hallucinate.
Some applications route successfully to a team with **no** registered
repo — that's the point: the ticket still reaches the right owner, and the
console says plainly it has no code to generate against, rather than
pretending otherwise.

**Impact analysis + effort estimate (beat 2)** is the first real model call.
A CR with genuine ambiguity gets a clarifying question — capped at two
turns — before the pipeline commits to an estimate, so "confident but wrong"
isn't the failure mode.

## 2. Phase 2 — Build (developer-owned)

**Codegen (beat 3)** never sees the whole repo. A relevance funnel scores
every candidate file against the CR text and sends only what's relevant —
the token panel shows the real savings against "paste the whole app in."

**Review (beat 4)** is deliberately per-file, not all-or-nothing: Ask a
question about one file, Apply it, or Reject it with a reason that's
recorded to the ticket's audit trail and excluded from what actually lands.

**Apply (beat 5)** is the only beat that writes to the real target
application — everything before it is a staged proposal a human can still
undo in full.

**Source control (beat 5b)** models branch → commit → push as an explicit
state machine, not a shortcut. The commit gate reads the ticket's own
test-result history server-side — the console can never itself assert
"tests passed" to unlock a commit. Nothing here runs git or contacts a
remote; see Section 4 for why that's a deliberate constraint, not a gap.

## 3. Phase 3 — Verify (hands off to the tester)

This is the phase where the ticket **changes hands**. Once the developer
drafts the design doc and assigns a tester, the ticket moves to the QA
column and the developer is locked out of everything from here on — the
same person can't grade their own homework.

- **Design doc (6b)**: the change-map diagram (which files, which layer,
  which service, the cross-service call arrow) is **derived** from the
  changed-file set — no model call, so it can never be confidently wrong.
  The narrative text around it is drafted.
- **Test scenarios (7)**: the AI proposes a plan traced to the CR's own
  acceptance criteria, in prose, *before* any test code exists — the tester
  can edit it, and the edited version is what actually gets built against.
- **Generate + run tests, mutation-proof (8)**: a deliberately seeded bug
  must make the generated suite fail, then gets reverted — proof the tests
  do something, not just that they exist.
- **Regression suite (9)**: a suite that predates this CR, human-authored,
  and appears on **no** target's generation allowlist — the pipeline is
  structurally unable to write to it. It staying green is a checked result.
- **Traceability matrix (10)**: criterion → scenario → test → result,
  derived. An ambiguous scenario-to-test pairing renders as "no automated
  test" rather than a guess — the tool reports gaps instead of hiding them.
- **Drift check (11)**: runs automatically right after Apply, not on a
  button press someone has to remember.

## 4. Phase 4 — Ship

**Release notes + deployment plan (12)**: three separate notes (client,
ops, user guide) for three different readers, and a deploy order **derived**
from the change's own service graph — e.g. on the ClaimsPortal CR,
`policy_service` before `claims_service`, because `claims_service` calls it,
with the reasoning stated, not just the order.

**Release record (13)**: assembled from what the run actually produced, not
a template filled in optimistically. Its "Not evidenced by this release"
block is the load-bearing part — a release document that only lists
successes is marketing, not evidence. Attaching it to the ticket is honest
about the demo default: in replay mode there's no real Jira to attach to,
so the beat records the intent and says the upload was simulated; a real
Jira connection uploads for real.

---

## 5. The one thing modelled, not executed: source control

Beat 5b's branch → commit → push flow is **simulated end to end** — no
`git` subprocess, no real branch, no real remote. This is a deliberate
property of the demo, not an unfinished feature: the target apps live
inside this same repo, and the reset scripts restore their pre-CR baseline
from `HEAD` — a real commit would put the CR into `HEAD`, and resets would
start restoring the change instead of the baseline. The point of the beat
is the *shape* a real integration would have — branch before edit, commit
gated on green tests, push handing off to a pipeline — because that shape
is what a reviewer actually asks about when they see an AI editing code.
Every branch state (no branch, applied-but-uncommitted,
committed-but-unpushed, abandoned, pushed-but-simulated) has its own line in
the release record's "Not evidenced" block, so a modelled push can never
read as a deployment that happened.

---

## 6. Where a run can stop early

Not every ticket makes it through all 13 beats:

- **No CI / unknown CI** → routes through the AI fallback instead of the
  table lookup, with its own confirmation gate.
- **Application has no registered repo** → routing succeeds, generation
  never starts. The console says so.
- **Rejected files** → excluded from Apply, but the rest of the proposal
  can still land.
- **Commit blocked** → the gate names the missing test result rather than
  silently refusing.
- **PDF rendering unavailable** (no Chromium) → the design-doc/release-record
  PDF buttons degrade to the browser's own print-to-PDF rather than failing.

Every one of these is a documented, deliberate branch — not a caught
exception papering over a gap.

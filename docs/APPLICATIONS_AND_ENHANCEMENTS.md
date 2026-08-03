# PolicyCore, ClaimsPortal & EnrolDirect — What They Are, What's Changing, How It's Tested

For a team that needs the business/functional picture — what each application
does today, what small enhancement is being added to it, how that enhancement
gets proven correct before it ships, and what "everything is running" looks
like in practice.

All data in every application below is **synthetic** — a fictional insurer
("MapleSure Insurance"), fictional plan sponsors, no real client data anywhere.
The domain is group retirement and group benefits: a **plan sponsor** (an
employer) holds a **group contract**, **plan members** enrol under it, a change
to an in-force contract is an **amendment**, and what the sponsor pays is a
**contribution**.

---

## The applications

The three target applications live under `repos/` — the folder holding
everything the AI pipeline *changes*. The console lives under `apps/`, with the
launch scripts: the tooling that *does* the changing.

| Application | Port | Role |
|---|---|---|
| **AMS Console** (`apps/console/`) | 8000 (API) + 5173 (UI) | The console the change is driven from — a developer opens a ticket here, an AI drafts the change, a reviewer approves it file by file, and it's applied to one of the three apps below. Managers also get an `/admin` page for resets, logs, and starting/stopping the apps. |
| **PolicyCore** (`repos/policycore/`) | 8501 (path `/sl_policycore`) | The plan-administration portal — see below. Target of US-2026-041 and US-2026-042. |
| **policy-service** (`repos/claimsportal/`) | 8081 | Half of ClaimsPortal — serves group contract records. |
| **claims-service** (`repos/claimsportal/`) | 8082 | Half of ClaimsPortal — claims intake. Target of US-2026-043. |
| **EnrolDirect** (`repos/enroldirect/`) | 8083 | The online enrolment channel — who may self-serve, and what they can reach. Target of US-2026-045. |

**All 6 up looks like this** (health-check pass, in this exact order — start
policy-service before claims-service, since claims-service calls it):

```
Console       :8000  ->  200
Console UI    :5173  ->  200
PolicyCore    :8501/sl_policycore  ->  200
policy-service:8081  ->  {"status": "ok"}
claims-service:8082  ->  {"status": "ok"}
EnrolDirect   :8083  ->  200
```

> **The screenshots in this document are out of date.** The PolicyCore ones
> predate the 2026-08-03 group-retirement reskin and still show the earlier
> property & casualty wording — "Premium", "Coverage Tier", "Endorsement",
> Auto/Home/Life products, individual policyholders — against an older seed.
> The ClaimsPortal ones show individual holder names rather than today's plan
> sponsors. Every figure in the tables below comes from the current seed data
> and the current code, and is the one to trust where the two disagree.
> Re-capture is outstanding.

![PolicyCore's contract list](screenshots/policycore-list.jpg)
*PolicyCore (`:8501/sl_policycore`) — the contract list every enhancement below builds on.*

![policy-service's Contracts Team console](screenshots/policyservice-list.jpg)
*policy-service (`:8081`) — half of ClaimsPortal.*

![claims-service's Claims Team console](screenshots/claimsservice-console.jpg)
*claims-service (`:8082`) — the other half, validates against policy-service.*

There is no screenshot of EnrolDirect yet; its six-screen console is described
in `repos/enroldirect/README.md` and in `docs/ENROLDIRECT_APP.pdf`.

---

## PolicyCore — the plan administration portal

**What it is today**: the app plan sponsors and support engineers use to
manage active group contracts. Three things it already does:

- **Contract list & detail** — view a plan sponsor's group contract, its
  product type, contribution, and status.
- **Claim submission** — file a claim against a group contract.
- **Amendment requests** — request a change to an in-force group contract
  (e.g. updating plan details or the sponsor's information on file) through a
  5-field form: amendment type, requested change, effective date, contact
  phone, contact email.

Two small enhancements are being added to it.

### Enhancement 1 — Plan-Tier Upgrade Option (US-2026-041)

**The problem**: a plan sponsor who wants to move to a higher plan tier
(e.g. Standard → Premium → a new top tier) has no self-service way to do it —
today that requires a manual back-office process.

**What's being added**: an upgrade control directly on the contract detail
view. Selecting a higher tier recalculates the contribution automatically and
saves it — no downgrades in this change, and every existing flow (contract
list, plan-member roster, claim submission) keeps working unchanged.

**Worked example** — group contract `POL-10001` (Northwind Logistics Ltd.,
Health), monthly contribution $4,820.50 at the "Standard" tier, with the
generated multipliers Standard ×1.0, Premium ×1.25, Elite ×1.5:

| Action | Result |
|---|---|
| Before the user story | No tier concept exists at all — the contract just has a contribution. |
| Upgrade to "Premium" (×1.25) | Contribution recalculates to **$6,025.63** |
| Upgrade "Premium" → "Premium" again (same tier) | Rejected — no same-tier "upgrades" |
| Downgrade "Premium" → "Standard" | Rejected — this user story is upgrades only |
| Upgrade an unknown contract number | Rejected with a clear "not found" error |

The audience picks the *top* tier's name live, so "Elite" above is whatever
they choose; Standard and Premium are fixed.

![Before: no plan tier](screenshots/cr041-before.jpg)
*Before — just a contribution, no tier concept. (Pre-reskin screenshot: reads "Premium", an older seed, and an individual holder.)*

![After: Premium tier, recalculated contribution](screenshots/cr041-after.jpg)
*After — the tier is now shown and the contribution has been recalculated. (Pre-reskin screenshot; the figures are from the older seed, not the ones in the table above.)*

**How it's tested**:
- A generated test suite proves the logic in the table above — including
  both rejection cases, not just the happy path.
- A separate, pre-existing regression suite (written by hand, not by the
  tool that made this change) re-runs and proves contract list, contract
  detail, and claim submission still work exactly as before.
- A deliberately seeded bug (weakening the downgrade check) is injected to
  prove the generated tests would actually catch a real regression, not just
  pass by coincidence — then the bug is reverted.

### Enhancement 2 — Amendment Priority Field (US-2026-042)

**The problem**: support engineers currently have no way to tell which
submitted amendment requests are time-sensitive versus routine — urgent
and routine requests sit in the same unsorted queue.

**What's being added**: a 6th field on the amendment request form,
"Priority," with exactly two choices — "Standard" or "Urgent" — defaulting
to "Standard." A plan sponsor who doesn't touch the new field gets the exact
same behavior as before this change.

**Worked example** — a plan sponsor requests an address change on
`POL-10001` (Northwind Logistics Ltd.):

| Field | Before the user story | After the user story |
|---|---|---|
| Amendment type | "Address Change" | "Address Change" |
| Requested change | "Update mailing address" | "Update mailing address" |
| Effective date | 2026-07-30 | 2026-07-30 |
| Contact phone / email | (unchanged) | (unchanged) |
| Priority | *(field doesn't exist)* | **"Urgent"** *(or left blank → defaults to "Standard")* |

![Before: 5-field form, no Priority](screenshots/cr042-before.jpg)
*Before — Amendment type, requested change, effective date, contact phone, contact email. No Priority. (Pre-reskin screenshot: the form is still labelled "Endorsement".)*

![After: Priority field set to Urgent](screenshots/cr042-after.jpg)
*After — the 6th field, ready to submit as "Urgent." (Pre-reskin screenshot.)*

Submitting the form without touching the new field behaves exactly as it did
before this user story — that's the acceptance bar, not just "the field works."

**How it's tested**: the same three-part approach as Enhancement 1 —
generated tests for the new field's behavior (defaults correctly, persists
the chosen value, both choices work), the pre-existing regression suite
proving nothing else broke, and a seeded-bug check (flipping the default to
"Urgent") proving the tests would catch it if the default silently changed.

---

## ClaimsPortal — claims intake and contract lookup

**What it is today**: two connected pieces —

- **Contract lookup** (`policy-service`) serves group contract records
  (contract number, plan sponsor, benefit, status, annual maximum).
- **Claims intake** (`claims-service`) accepts a submitted benefit claim and
  validates it against the contract lookup piece over a live request: the
  contract must exist, be active, and the claim amount must not exceed the
  contract's annual maximum.

ClaimsPortal kept its own vocabulary through the group-retirement reskin, on
purpose: **claim**, **deductible** and **annual maximum** are already the right
words for group health, dental and disability benefits. Its API field names
(`policyNumber`, `holderName`, …) are a published contract that US-2026-043 and
the committed AI recording depend on by exact name, so they keep their original
spelling even where the prose says "group contract" and "plan sponsor".

### Enhancement 3 — Claims Deductible Handling (US-2026-043)

**The problem**: contracts carry no deductible today, so a claim for less
than what the plan member would owe out of pocket anyway is accepted and
routed to an adjuster — wasted handling time for a claim that was never
going to pay out. Accepted claims also don't record a payable amount for
downstream settlement.

**What's being added**: each policy gains a deductible amount. A claim at or
below the policy's deductible is now rejected as below-deductible instead of
accepted. An accepted claim records a **payable amount** — the claim amount
minus the deductible, never negative. The decision precedence is checked in
this order: non-active policy status first, then over the coverage limit,
then at-or-below the deductible, otherwise accepted. Every existing flow
(policy list/detail, claim submission, claim list) keeps working unchanged.

**Worked example** — real values from the seeded data:

| Group contract | Annual maximum | Deductible (new) | Claim amount | Before the user story | After the user story |
|---|---|---|---|---|---|
| `MS-1004` (Talus Software Co., Critical Illness) | $10,000 | $100 | **$80** | ACCEPTED | **REJECTED_BELOW_DEDUCTIBLE** |
| `MS-1001` (Northwind Logistics Ltd., Health) | $25,000 | $500 | **$1,200** | ACCEPTED | ACCEPTED — **payableAmount $700** |
| `MS-1004` | $10,000 | $100 | $99,000 | REJECTED_OVER_LIMIT | REJECTED_OVER_LIMIT *(unchanged)* |
| `MS-1003` (Quill & Fenwick LLP, lapsed contract) | $15,000 | $500 | $500 | REJECTED_POLICY_LAPSED | REJECTED_POLICY_LAPSED *(unchanged — status still wins)* |

The $80-on-MS-1004 row is the clearest "before/after" moment: identical
claim, identical policy, and the only thing that changed is that it's now
correctly rejected instead of silently costing adjuster time on a claim that
was never going to pay out.

![Before: $80 claim on MS-1004 accepted](screenshots/cr043-before.jpg)
*Before — the $80 claim on MS-1004 (and the earlier $1,200 on MS-1001) both ACCEPTED.*

![After: same $80 claim now rejected](screenshots/cr043-after.jpg)
*After — same claim, now REJECTED_BELOW_DEDUCTIBLE; the $1,200 claim still ACCEPTED, now with payableAmount.*

US-2026-043 explicitly forbids changing either team's HTML console, so the
policy-service UI looks identical before and after — the proof is in the raw
API response, not the page:

![Raw API response showing the new deductible field](screenshots/cr043-deductible-json.jpg)
*`GET /api/policies/MS-1004` — `deductible` is now in the response, even though the console page above renders unchanged.*

**How it's tested**: the same three-part approach again —
- Generated tests cover every branch of the decision: accepted, rejected for
  being at/below the deductible, rejected for being over the limit (even if
  also above the deductible), rejected for a non-active policy (which takes
  precedence over both amount checks), and that the payable amount floors at
  zero rather than going negative.
- A pre-existing regression suite proves the policy lookup piece still
  returns every field the claims side depends on, unchanged, even though the
  policy record just gained a new field.
- A seeded bug (weakening the deductible boundary check so a claim for
  exactly the deductible amount is wrongly accepted) proves the generated
  tests would catch it.

---

## EnrolDirect — the online enrolment channel

**What it is today**: the self-serve channel a plan member uses to join or
change benefits. Two things it already does:

- **An access gate** — `POST /api/eligibility/check` decides whether someone
  may use the channel at all, in three steps: the group contract is active,
  the applicant's category resolves to an access preference, and the plan
  sponsor has enabled that preference. A decision carries its reasons, not
  just a yes or no.
- **An analysis surface** — `/api/analysis/*` counts, across the whole book,
  which contracts enable which preference and who that admits. Every figure is
  computed from the seeded directory by ordinary code, not drafted by an AI.

Access is governed by two preferences the plan sponsor agrees at contract
inception: *Online Enrolment — Member* (people already holding an active
benefit) and *Online Enrolment — Guest* (people with none). EnrolDirect
enforces them; PolicyCore owns them.

### Enhancement 4 — Prospect Member Eligibility Check (US-2026-045)

**The problem**: there is a third population neither preference was written
for. A **prospect** is someone the plan sponsor has already accepted onto the
contract roster who has not taken up any coverage — on the roster, holding no
active benefit. Treating them as a guest (a stranger to the contract) is
uncomfortable; treating them as a member (someone with coverage to change) is
inaccurate. Because nothing decides, the gate resolves *no* preference for
them and refuses them at step 2. That refusal is not a decision anyone took —
it is the narrower option in force by default.

**What's being added**: the classification is settled. A prospect is checked
against the **Guest** preference, which the impact analysis recommended as the
narrower grant, and the decision records which policy resolved them. Every
existing refusal code keeps its current meaning, and members and guests resolve
exactly as they do now.

**This one is different from the other three**, and that is the point of
including it: its baseline is a *removal*, not a missing feature. The
checked-in state is the moment after the analysis and before the gate acts on
it. The AI has to read the analysis to understand what the change is —
`impact.py` is given to it as context but is explicitly off the list of files
it may edit, and a run that comes back having modified it fails loudly.

**Worked example** — the classification bites twice, in opposite directions:

| Where | What the classification decides | Which option grants more |
|---|---|---|
| At the gate | How many prospects are admitted at all | Member |
| At the catalogue | How much of the benefit catalogue those admitted can reach, since member-only plans attach to existing coverage | Member |

Both effects are measured separately, and catalogue reach is only counted for
prospects the gate would actually admit — a plan you cannot reach because you
were refused at the door is already counted as a denial, and counting it twice
would inflate the gap. The recommendation reports its own cost: the prospects
it denies that the alternative would have admitted.

**How it's tested**: the same three-part approach, with the regression suite
carrying more weight than usual. `tests/test_regression_enroldirect.py`
asserts the gate's *ordering* (a lapsed contract must still deny a prospect
regardless of the policy), that the prospect decision never moves a member's or
a guest's outcome, and that the two options genuinely disagree — none of which
a type checker or an endpoint smoke test can see.

---

## The testing approach, in one place

Every enhancement above — regardless of which application it touches — is
proven with the same three-part discipline before it's considered done:

1. **Generated tests**, scoped to exactly the new behavior, reviewed before
   they're run.
2. **A pre-existing, human-authored regression suite** the tool making the
   change is never allowed to write to — so "the rest of the app still
   works" is a result that was actually checked, not a promise.
3. **A seeded-bug check** — a real, specific bug is deliberately introduced
   and the generated suite must catch it (then the bug is reverted). This is
   what proves the tests do something, rather than just existing.

Only after all three pass does the enhancement get release notes and a
release record documenting exactly what was — and wasn't — proven.

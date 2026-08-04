# DocumentHub — MapleSure's enrolment document service

> **Start with [`ARCHITECTURE.md`](ARCHITECTURE.md), then [`DESIGN.md`](DESIGN.md).**
> Those two are the orientation pair for this application — what it is and how
> it is put together, then why it is shaped that way. Read them before reading
> the source, and before answering questions about this application. This file
> covers how to run it and the application-knowledge sections (users, disaster
> recovery, business impact, escalation).

The service that produces the confirmation pack a person receives after an
enrolment is accepted — the letter and the enclosures.

Runs on nothing but the venv (FastAPI + uvicorn, already pinned). It holds its
enrolment feed in-process and calls no other service, so a locked-down sandbox
can host it and it starts alone:

```
apps/run-documenthub.sh     # http://localhost:8084/
```

The app lives under `repos/` (everything S3 *changes*); its launch script lives
under `apps/` with the rest of the tooling (everything that *does the
changing*). A manager can also start and stop it from the console's `/admin`
panel without a terminal.

Port comes from `DOCUMENTHUB_PORT` in `.env`, defaulting to 8084 — 8083 belongs
to EnrolDirect and 8501 to PolicyCore. (8081 and 8082 were ClaimsPortal's two
services; that target was retired on 2026-08-04 and the ports are free.)

## What it does

It receives accepted enrolments from EnrolDirect and produces one confirmation
pack each. A pack is a letter in five parts (salutation, opening, relationship,
next steps, closing) plus a set of physical enclosures.

There is no single letter with placeholders. There is a small catalogue of
**audiences** — whole worded packs, each written for a recipient in a
particular relationship with the plan sponsor — and the service picks one:

| Audience | Written for | Notable enclosure |
|---|---|---|
| `MEMBER_PACK` | Someone already holding coverage under the contract | — |
| `GUEST_PACK` | Someone with no place on the sponsor's roster, enrolling under a sponsor-agreed exception | Identity confirmation form |

`wording.audience_for` makes that choice and is the only place in the service
that does. See `DESIGN.md` for why that is enforced rather than merely
preferred.

### The selection audit

`GET /api/audit/selection-inputs` answers "is this batch right?" — a question
no individual pack can answer, because each one reads as correct on its own.

It compares what a pack *claims* about its recipient (`assumesNoMemberRecord`,
declared on the wording) against what the sponsor's roster says
(`onRoster`, carried on the feed). Neither fact comes from the selection rule,
which is the whole point: a rule cannot audit itself.

### The record that does not fit

The seeded feed contains five enrolments. Four are the two combinations this
service has always received. The fifth — `ENR-20260804-005`, Aditi Varma — is
on the sponsor's roster *and* was admitted under guest access.

That combination has no wording, so it falls through to the guest pack. Ask for
it today:

```
curl localhost:8084/api/packs/ENR-20260804-005
```

and the letter tells a person listed on their own sponsor's roster that we hold
no member record for them, and encloses a form asking them to prove who they
are. Nothing fails. Nothing is logged. The audit endpoint reports
`contradictionCount: 1`.

This is not hypothetical: it is what EnrolDirect starts sending the day
US-2026-045 ships.

## Tests

The checked-in regression suite is `tests/test_regression_documenthub.py`, at
the repo root rather than under this directory — anything ending `.py` under a
target root joins the codegen candidate pool, and a suite the pipeline can
rewrite is not an independent check of anything.

```
pytest tests/test_regression_documenthub.py
```

Every assertion in it holds **before and after** US-2026-046. It pins the two
existing audiences' prose and enclosures field by field, pins the four
historical records' audiences, and asserts the audit derives its verdict from
the packs' declared premise. It deliberately does *not* assert that the
contradiction count is zero — that is the thing the user story changes.

## The UI

`static/index.html`, vanilla HTML/CSS/JS with no build step. It lists the
feed, renders the selected pack as it would read, and shows the selection
audit as a table with the contradicting row flagged.

## S3 target — US-2026-046

Registered by `.s3targets.json` rather than by hand in
`s3_enhancement/targets.py`. It is the first target in this repo to arrive that
way, and that is deliberate: DocumentHub was identified by the cross-team
impact check on US-2026-045 as the one other team owed work, and was then
dropped into `repos/` and picked up with no code edit.

| | |
|---|---|
| Target id | `documenthub-rostered-guest-wording` |
| Cache namespace | `documenthub_rostered_guest_wording` |
| Story | `stories/US-2026-046.md` |
| Blast radius | `wording.py`, `enclosures.py`, `packs.py` |
| Read-only core files | `feed.py`, `main.py` |
| Reset | `demo/reset_s3_documenthub.sh` |

The baseline is committed in place at `.baseline/`, holding the three
`codegen_allowlist` files. Restoring from git would depend on this directory
being committed at the baseline state rather than at whatever a rehearsal last
applied.

**No committed replay recording yet.** A manifest-registered target has nothing
to record against until its story has been run once, so the first codegen run
is a live call that records itself. See the note at the end of `DESIGN.md`
about re-verifying the mutation snippet afterwards.

## Data

Fictional. `MapleSure Insurance` is the demo insurer; the sponsors, contract
numbers, plans and recipients are invented, and nothing here derives from a
real roster or a real document.

---

# Application knowledge

> Sections marked **Illustrative** are representative of a group-benefits
> estate of this shape, not measurements. This application has no measured
> RPO/RTO, no financial impact study and no on-call rota behind it. Replace
> them with SME input before treating them as authoritative. All names and
> contacts are fictional.

## 1. What it does

Produces the documents a member receives at the end of an enrolment. It is a
pure downstream consumer: it does not decide who may enrol, does not decide
what they may enrol in, and cannot correct either. It is told an enrolment
happened and produces the paperwork.

The judgement it *does* make is editorial — which of several whole worded packs
a recipient should receive. That judgement is invisible in normal operation,
because a pack sent to the wrong audience is grammatical, correctly spelled,
carries the right name and the right plan, and is still the wrong document.

**The failure mode is a correct-looking letter.** Nothing throws, nothing is
logged, and the first signal is a telephone call from someone asking why they
have been asked to prove who they are. That property drives most of the design
decisions in `DESIGN.md`, and it is why the service carries an audit endpoint
whose inputs the selection rule cannot see.

## 2. Intended users

| User type | Relationship |
|---|---|
| Plan member / enrolling applicant | **Primary — the recipient.** Never touches the service; receives its output on paper |
| Plan administration | Owns the enclosure sets; fields the calls when a pack is wrong |
| Communications | Owns the prose in `wording.py`; reviews on its own schedule |
| Print vendor | Consumes packs and enclosure codes; out of scope for this repo |
| Application support / maintenance | Explaining why a specific recipient got a specific pack |
| Audit & compliance | What was stated to whom, and on what premise |

**Its output is customer-facing and physical.** A wrong paragraph can be
reissued by email; a wrong enclosure has already asked a real person to
complete and return a real form, and withdrawing that costs a call each.

## 3. Disaster recovery — *Illustrative*

**Tier 3 — Business Operational. RTO 8 hours, RPO 4 hours.** Not member-facing
in the interactive sense: an outage delays confirmation packs rather than
blocking anyone from enrolling. It becomes materially worse during an
open-enrolment window, when pack volume is concentrated.

| Item | Method | Frequency |
|---|---|---|
| Enrolment feed | Seeded in-process — no persistent store to back up | On start |
| Generated packs | Computed on request, never stored (see below) | — |
| Wording and enclosure sets | Version-controlled with the deployment | Every change |
| Source and release artefacts | Version control + artefact repository | Every commit / build |

**Nothing here survives a restart, and nothing is supposed to.** The
application must run in a locked-down sandbox, so a datastore is a dependency
it cannot take. Packs are recomputed from the feed, which makes recovery
provision-deploy-start — and means a wording correction reaches every
not-yet-printed pack without a migration.

## 4. Business impact — *Illustrative*

| Dimension | Assessment |
|---|---|
| Financial | Low direct. No money moves through this service |
| Regulatory | **Moderate.** Its output is a written statement to a member about their coverage and about what MapleSure holds on them |
| Reputational | **Moderate to high.** A wrong pack is a customer-visible error in writing, retained by the recipient |
| Operational | Moderate. Wrong packs generate inbound calls to plan administration at roughly one per pack |

The asymmetry worth noting: the service's *availability* impact is low — packs
delayed by a few hours harm nobody — while its *correctness* impact is high,
and correctness failures do not announce themselves. Monitoring shaped around
uptime would report this service as healthy throughout the exact incident it
is most likely to cause.

## 5. Organisation and escalation — *Illustrative sample*

| Level | Group | Responsibility |
|---|---|---|
| L1 | Service Desk L1 | Intake; "I received the wrong letter" reports |
| L2 | App Support — DocumentHub | Runtime behaviour; explaining a specific pack |
| L3 | App Support — DocumentHub (engineering) | Selection rule and wording changes |
| Business | Plan administration | Owns enclosure sets; approves who receives what |
| Business | Communications | Owns the prose |

Escalation note: a "wrong letter" report is routed to L2, but the decision
about what the letter *should* say is never L2's. Wording and enclosure
changes need plan administration and Communications, on their own review
schedules — which is why those two concerns are separate modules rather than
one.

## 6. Testing

| Layer | Where |
|---|---|
| Regression (human-authored, independent) | `tests/test_regression_documenthub.py` |
| Generated (S3, per user story) | `tests/test_s3_rostered_guest_wording.py` |

The regression suite is never written to by the pipeline — that assertion is
made structurally in `tests/test_s3_testrun.py`, and it is the only independent
evidence that a generated change broke nothing.

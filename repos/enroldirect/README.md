# EnrolDirect — MapleSure's online enrolment channel

> **Start with [`ARCHITECTURE.md`](ARCHITECTURE.md), then [`DESIGN.md`](DESIGN.md).**
> Those two are the orientation pair for this application — what it is and how
> it is put together, then why it is shaped that way. Read them before reading
> the source, and before answering questions about this application. This file
> covers how to run it and the application-knowledge sections (users, disaster
> recovery, business impact, escalation).

The self-serve channel a plan member uses to join or change benefits, plus the
analysis surface that answers who is allowed to use it and what happens if that
answer changes.

Runs on nothing but the venv (FastAPI + uvicorn, already pinned). It seeds its
own contracts and applicants in-process and calls no other service, so a
locked-down sandbox can host it and it starts alone:

```
apps/run-enroldirect.sh     # http://localhost:8083/
```

The app lives under `repos/` (everything S3 *changes*); its launch script
lives under `apps/` with the rest of the tooling (everything that *does the
changing*). A manager can also start and stop it from the console's `/admin`
panel without a terminal.

Port comes from `ENROLDIRECT_PORT` in `.env`, defaulting to 8083 — 8081 and
8082 belong to ClaimsPortal's two services, 8501 to PolicyCore.

## What it does

Access to the channel is gated by two **access preferences** the plan sponsor
agrees at contract inception, and which live on the contract record in
PolicyCore:

| Preference | Written for |
|---|---|
| `Online Enrolment - Member` | People already holding an active benefit under the contract |
| `Online Enrolment - Guest` | People with no active benefit — retiree continuations, spousal transfers, sponsor-agreed exceptions |

EnrolDirect **enforces** those preferences; PolicyCore **owns** them. That split
is why a change to what a preference means is a change to a shared contract
between two systems rather than a local edit.

### The gate

`POST /api/eligibility/check` runs three gates, in this order:

1. **Contract is active.** A lapsed contract keeps whatever preferences it was
   configured with, so this runs first. Reversing it with step 3 would let
   stale configuration grant access, and no category-level test would notice.
2. **The applicant's category resolves to a preference.**
3. **The sponsor enabled that preference.**

Decisions carry their reasons, not just a boolean. A denial that cannot say
which gate closed becomes a support ticket.

### Enrolling

`POST /api/enrolments` is what someone came to the channel to do. It runs four
checks and records the outcome either way:

1. The access gate above — **reused, not reimplemented**. An enrolment path
   with its own copy of the access rules is how a channel ends up admitting
   someone the gate would have turned away.
2. The plan is on that applicant's contract.
3. The plan is open to their *effective* category (see `memberOnly` below).
4. The plan is sold at the requested tier.

A refusal is a `200` carrying a `REFUSED` record, not a 4xx — the applicant
asked a valid question and got a valid, recorded answer. Refusals are kept, not
discarded: "how many failed" is a number nobody can act on, "how many failed
because the plan needed existing coverage" changes a decision.

State is in-process and resettable (`POST /api/enrolments/reset`). Nothing
survives a restart and nothing is supposed to.

### The classification bites twice

`benefits.py` marks some plans `memberOnly` — they attach to existing coverage,
so there is nothing for them to attach to for someone holding none. That means
the prospect question decides **two** things, not one:

| | Effect | Direction |
|---|---|---|
| At the gate | How many prospects get in at all | Member option admits *more* |
| At the catalogue | How much of the catalogue those admitted reach | Member option reaches *more* |

Both effects favour the member option in the seed, but they are separate
measurements and `impact.catalogue_reach()` counts them separately. It counts
reach only for prospects the gate *would* admit under that option — a plan you
cannot reach because you were refused at the door is already counted as a
denial, and counting it twice would inflate the gap.

### The third population

Applicants come in three categories, and only two of them were anticipated:

| Category | On the roster? | Active benefit? | Has a preference? |
|---|---|---|---|
| `MEMBER` | yes | yes | yes — Member |
| `GUEST` | no | no | yes — Guest |
| `PROSPECT` | **yes** | **no** | **no** |

A prospect is someone the sponsor has already accepted onto the roster who has
not taken up coverage. Treating them as a guest (a stranger to the contract) is
uncomfortable; treating them as a member (someone with coverage to change) is
inaccurate. Neither preference was written for them.

Nothing decides which preference they are checked against, so
`eligibility.preference_for_category` returns `None` for them and the gate
refuses them at step 2. That refusal is the current behaviour, not a decision
— **US-2026-045** (`stories/US-2026-045.md`), "Prospect Member Eligibility Check
For Online Enrolment", is the change that settles it. It is written the way
the business asked the question: a business objective, the target member type,
and given-when-then acceptance criteria for an eligible and an ineligible
prospect, with the rules the determination is built from underneath. Its
technical criteria did not move when it was reframed on 2026-08-03, so the
committed recording still replays.

## The analysis surface

`/api/analysis/*` exists because "should prospects be members or guests?" could
not be answered from the two options' descriptions. It depended on how the
preferences were actually configured across the book, and nobody had counted.

| Endpoint | Answers |
|---|---|
| `/api/analysis/consumers` | Which systems read or write these preferences, and in which direction |
| `/api/analysis/preference-usage` | Which contracts enable which preference; headcount per category |
| `/api/analysis/prospect-impact` | Both policies' grant counts, catalogue reach, every applicant they disagree about, and a recommendation |

Two things about it are deliberate:

- **Every figure is computed** by pure functions in `impact.py` from the seeded
  directory. No model call, so no cache key, nothing to warm, and nothing that
  can be confidently wrong the way generated prose can. Same reasoning as
  `s3_enhancement/diagram.py` and `acceptance.py`.

  It *models* the gate's rules (`impact._would_grant`) rather than calling the
  gate, because the gate implements neither option yet. That duplication is
  the cost of analysing a change before making it, and it is pinned rather
  than trusted: the regression suite asserts the model agrees with the real
  gate for the two categories the gate does classify.
- **`notEvidencedByThisAnalysis` is load-bearing.** Regulatory exposure,
  support load, unlisted downstream subscribers and what a prospect was told
  they could do are all real consequences that configuration data cannot size.
  They are named rather than dropped, and the recommendation reports its own
  cost — the prospects it denies who the alternative would admit. An analysis
  that lists only supporting numbers is advocacy. Same rule as
  `release.unproven_claims()`.

The consumer inventory is **declared, not discovered** — this app cannot see
the other systems' code. It is the analysis's stated input and it is wrong the
moment a consumer appears without the table being updated, which is why the
risk list and the UI both say so.

## Not the same thing as `repos/policycore/enrolment/`

Two enrolment modules, two different questions. They compose; they do not
overlap, and neither imports the other.

| | Question | Owns |
|---|---|---|
| `policycore/enrolment/` | *When* may this person join? | Waiting periods, eligibility dates, life events, dependant age-out |
| `enroldirect/` | May this person use the **online channel** at all? | Access preferences, applicant categories, the enrolment gate |

Someone can be eligible to join (PolicyCore) and still have no online access
(EnrolDirect), or the reverse. Merging them would produce a single function
that answers two questions and can only report one reason.

## Tests

`tests/test_regression_enroldirect.py` — checked in, human-authored, outside
this target root on purpose (anything ending `.py` under a target root joins
the codegen candidate pool). It protects the gate *ordering*, the promise that
the prospect policy never moves a member's or guest's outcome, and the fact
that the two policies genuinely disagree — none of which a type checker or an
endpoint smoke test can see.

```
python -m pytest tests/test_regression_enroldirect.py
```

## The UI

Six screens, served from `static/index.html` (self-contained, no build step):
**Overview** (estate counts, both comparison figures, the recommendation and
its cost), **Enrol**, **Access check**, **Contracts & plans**, **Preference
analysis**, **Audit log**.

Chart colour follows the *policy* and is identical in every figure — never
reassigned by rank within one chart — and every bar carries its value directly,
so identity never depends on colour alone. The pair is validated against the
light surface (CVD ΔE 24.7, normal-vision ΔE 33.6, both ≥ 3:1 contrast).

## S3 target — US-2026-045

EnrolDirect is registered in `s3_enhancement/applications.py` (so a ticket
naming it routes to the right team deterministically) **and** as an S3 target,
`enroldirect-prospect-access`, against `stories/US-2026-045.md`.

Checked-in source is the **pre-user story baseline**: the analysis is done, the gate is
not changed, and a prospect is refused because no preference resolves for them.
A pristine copy lives in `.baseline/` and `demo/reset_s3_enroldirect.sh`
restores it by copying that snapshot back — not with `git checkout`, so it is
unaffected by the uncommitted `apps/` → `repos/` move that currently breaks the
two PolicyCore resets. A manager can run the same reset from the console's
`/admin` panel. `.baseline/` is excluded from the codegen corpus by
`relevance._EXCLUDED_DIR_NAMES`, which is why the snapshot can sit inside the
target root at all — nothing else `.py` may.

`impact.py` is in the target's `core_files` but deliberately **not** in its
`codegen_allowlist`: the model has to read the analysis to understand the
change and must not edit it. That is why this target carries its own
`_validate_enroldirect_file_set` — core recall over the editable core files
only, plus a loud failure if a read-only file comes back modified.

`tests/test_regression_enroldirect.py` is named by no allowlist and must pass
**before and after** the user story. Every assertion in it is an invariant: it asserts
no prospect's gate outcome except on a lapsed contract, because that is the
one prospect denial the classification cannot reach.

## Brief

`docs/ENROLDIRECT_APP.pdf` (source: `docs/ENROLDIRECT_APP.html`) — a six-page
brief covering what the app does, the two-bite analysis, the dependency map,
what the tests protect, and what the app deliberately is not. Hand-authored
print CSS rendered with headless Chrome, per the house pipeline; re-render with:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="docs/ENROLDIRECT_APP.pdf" "file://$PWD/docs/ENROLDIRECT_APP.html"
```

## Data

All synthetic. Plan sponsors are fictional employers, every applicant name is
invented, and nothing here derives from a real roster.

---

# Application knowledge

> Sections marked **Illustrative** are representative of a group-benefits
> estate of this shape, not measurements. This application has no measured
> RPO/RTO, no financial impact study and no on-call rota behind it. Replace
> them with SME input before treating them as authoritative. All names and
> contacts are fictional.

## 1. What it does

The self-serve channel a plan member uses to join or change benefits without
going through a call centre, plus the analysis surface that answers *who is
allowed to use it*.

Access is governed by two **access preferences** the plan sponsor agrees at
contract inception: one written for people already holding an active benefit,
one for people with no active benefit who still have reason to enrol — retiree
continuations, spousal transfers, sponsor-agreed exceptions.

**The ownership split is load-bearing.** PolicyCore *owns* those preferences;
they live on the contract record. EnrolDirect *enforces* them. A change to what
a preference means is therefore a change to a contract between two systems, not
a local edit — which is why the population question this app exists to answer
needed an impact analysis before anyone wrote code.

The eligibility check runs three gates in a fixed order:

1. **Is the contract active?** A lapsed contract retains whatever preferences it
   was configured with, so this runs first — otherwise stale configuration could
   grant access, and no category-level test would notice.
2. **Does the applicant's category resolve to a preference?**
3. **Did the sponsor enable that preference?**

Every decision carries its reasons, not just a boolean. A denial that cannot say
which gate closed becomes a support ticket — and those reasons are
customer-visible copy, not internal diagnostics.

Enrolment reuses that same gate rather than reimplementing it, then confirms the
plan is on the applicant's contract and open to their category. The outcome is
recorded either way, so refusals are auditable.

Self-contained: it holds its own applicant and contract data and calls no other
service at runtime.

## 2. Intended users

| User type | Relationship |
|---|---|
| Plan member (employee) | **Primary — the self-serve end user.** The only one of the three applications whose primary user is outside the organisation |
| Prospect / non-active applicant | Retiree continuations, spousal transfers, sponsor-agreed exceptions |
| Plan sponsor (employer HR) | Sets the access preferences that gate the channel — via PolicyCore, not here |
| Contracts / policy administration team | Owns the preference configuration this app enforces |
| Application support / maintenance | Runtime behaviour; explaining why a specific applicant was refused |
| Operations | Run procedures, routine checks, restarts |
| Business analyst / product | Access policy and its population impact |
| Audit & compliance | Access decisions and the reasons recorded with them |

**Member-facing.** This raises its availability profile above the other two
applications and makes its refusal messages customer-visible copy.

## 3. Disaster recovery — *Illustrative*

**Tier 2 — Business Critical. RTO 4 hours, RPO 1 hour.** Member-facing: an
outage is externally visible, and it is time-boxed by the enrolment period —
an outage during an open-enrolment window is materially worse than the same
outage outside one.

| Item | Method | Frequency |
|---|---|---|
| Applicant and contract data | Seeded in-process — no persistent store to back up | On start |
| Enrolment log | In-process and non-persistent by design (see below) | — |
| Application configuration | Version-controlled with the deployment | Every change |
| Source and release artefacts | Version control + artefact repository | Every commit / build |

**Nothing here survives a restart, and nothing is supposed to.** The application
must run in a locked-down sandbox, so a datastore is a dependency it cannot
take. That makes recovery unusually simple — provision, deploy, start — and it
makes the enrolment log unsuitable as the audit record of last resort. If
enrolment outcomes must survive an incident, they need to be shipped somewhere
durable; that is a gap, not a design feature.

Recovery outline:

1. Assess scope.
2. Provision host; restore runtime from the pinned dependency manifest.
3. Apply environment configuration (`ENROLDIRECT_PORT`).
4. Start; verify with `tests/test_regression_enroldirect.py` and one
   eligibility check plus one enrolment end to end.
5. Confirm member-facing messaging with the business owner.

**Known gaps.** No durable record of enrolment outcomes (above). The procedure
is not rehearsed, so the RTO is an estimate.

## 4. Business impact — *Illustrative*

**Process supported:** member self-service enrolment and benefit changes.
**Business owner:** Member Experience.

| Outage duration | Impact |
|---|---|
| 0–4 hours | Members redirected to the call centre |
| 4–24 hours | Call centre volume spike; enrolment abandonment |
| > 24 hours | Enrolment window may be missed entirely — coverage gaps with contractual consequences |

**Financial.** Displacing members to the call centre substitutes a low-cost
channel with a high-cost one. A missed enrolment window can mean a coverage gap
the sponsor's contract does not permit.

**Customer and reputational.** The only member-facing system of the three.
Outages are externally visible and concentrated in enrolment periods, when
attention is highest. A refusal a member cannot get an explanation for converts
directly into a complaint — which is why the decision carries its reasons.

**Regulatory and contractual.** Enrolment windows are contractual. Access
decisions and their recorded reasons are the evidence trail if a refusal is
disputed.

**Peak periods.** Annual open enrolment, defined per sponsor — severe. Change
freezes should cover every active enrolment window.

## 5. Organisation and escalation — *Illustrative sample*

| Level | Role | Responsibility | Response target | Contact |
|---|---|---|---|---|
| L1 | Service Desk | Triage, known-error lookup, restart per runbook | 15 min | servicedesk@maplesure.example · x4100 |
| L2 | Application Support — Group Benefits | Diagnosis, explain a specific refusal, coordinate restore | 30 min (Sev 1) | ams-groupbenefits@maplesure.example · x4210 |
| L3 | Engineering — Benefits Platform | Code defects, DR execution, gate changes | 1 hour (Sev 1) | benefits-platform@maplesure.example · x4315 |
| L4 | Service Owner | Business decisions, member communication, invoke DR | 2 hours | s.maiti@maplesure.example |

| Severity | Definition | Example |
|---|---|---|
| Sev 1 | Channel unavailable, **or any outage during an open-enrolment window** | Application down; gate refusing every applicant |
| Sev 2 | Major function degraded, workaround exists | Enrolment failing for one category; reasons not rendering |
| Sev 3 | Minor function impaired | Display defect; wording issue in a non-refusal screen |
| Sev 4 | Cosmetic or informational | Label wording |

Note the Sev 1 definition is deliberately wider here than for the other two
applications: timing, not just scope, determines severity.

| Role | Name | Contact |
|---|---|---|
| Service Owner — Group Benefits | Sudipta Maiti | s.maiti@maplesure.example |
| Business Owner — Member Experience | Daniel Okonkwo | d.okonkwo@maplesure.example |
| Application Support Lead | AMS — Group Benefits | ams-groupbenefits@maplesure.example |
| Engineering Lead | Benefits Platform Engineering | benefits-platform@maplesure.example |
| Infrastructure / Hosting | Platform Operations | platform-ops@maplesure.example |

**Vendors.** No third party holds an operational dependency. The runtime is
open-source and pinned — this application runs on nothing but the virtual
environment, which is what lets a locked-down sandbox host it. *(Confirm with
Procurement before publishing.)*

**Support model.** L1 24×7; L2 business hours plus on-call, extended to cover
open-enrolment windows; L3 on-call. Weekly rotation. Hard freeze during every
active enrolment window. Quarterly service review.

## 6. Testing

| Level | Where | Covers |
|---|---|---|
| Unit | `tests/test_unit_enroldirect.py` | Gate ordering, preference vocabulary, applicant data-integrity rules, every decision carries a reason |
| Regression | `tests/test_regression_enroldirect.py` | Access-gate outcomes and enrolment refusals, asserted over HTTP |

Both live outside this directory deliberately: no automated process may write
to them, which is what makes them an independent check.

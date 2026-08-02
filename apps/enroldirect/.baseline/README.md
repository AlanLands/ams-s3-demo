# EnrolDirect — MapleSure's online enrolment channel

The self-serve channel a plan member uses to join or change benefits, plus the
analysis surface that answers who is allowed to use it and what happens if that
answer changes.

Runs on nothing but the venv (FastAPI + uvicorn, already pinned). It seeds its
own contracts and applicants in-process and calls no other service, so a
locked-down sandbox can host it and it starts alone:

```
apps/run-enroldirect.sh     # http://localhost:8083/
```

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
— **CR-2026-045** (`crs/CR-2026-045.md`) is the change that settles it.

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

## Not the same thing as `apps/policycore/enrolment/`

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

## S3 target — CR-2026-045

EnrolDirect is registered in `s3_enhancement/applications.py` (so a ticket
naming it routes to the right team deterministically) **and** as an S3 target,
`enroldirect-prospect-access`, against `crs/CR-2026-045.md`.

Checked-in source is the **pre-CR baseline**: the analysis is done, the gate is
not changed, and a prospect is refused because no preference resolves for them.
A pristine copy lives in `.baseline/` and `demo/reset_s3_enroldirect.sh`
restores it. `.baseline/` is excluded from the codegen corpus by
`relevance._EXCLUDED_DIR_NAMES`, which is why the snapshot can sit inside the
target root at all — nothing else `.py` may.

`tests/test_regression_enroldirect.py` is named by no allowlist and must pass
**before and after** the CR. Every assertion in it is an invariant: it asserts
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

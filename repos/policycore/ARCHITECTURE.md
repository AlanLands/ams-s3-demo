# PolicyCore — Architecture

**Read this first.** This is the orientation document for PolicyCore: what it
is, what it owns, how it is put together, and where to look for what. Read
[`DESIGN.md`](DESIGN.md) next for *why* it is shaped this way, and
[`README.md`](README.md) for how to run it and for the application-knowledge
sections (users, DR, business impact, escalation).

---

## 1. What this application is

The system of record for MapleSure's **group benefits** book.

An employer — the **plan sponsor** — holds a **group contract**. That sponsor's
employees enrol under it as **plan members**, optionally covering dependants.
Members incur **claims**; contracts are changed by **amendments**.

PolicyCore owns that structure. It is the authority for contract data across
the estate: when another application needs to know what a contract says, this
is where the answer comes from.

**Domain vocabulary is group retirement / group benefits, not property &
casualty.** Plan sponsor (not policyholder), contribution (not premium), plan
tier (not coverage tier), amendment (not endorsement). Getting this wrong in
new code is the most common review comment.

## 2. Context — how it sits in the estate

```
                    ┌──────────────────────────┐
                    │       PolicyCore         │
   plan admin ─────▶│  contracts · members     │
                    │  claims · amendments     │
                    │  enrolment eligibility   │
                    └───────────┬──────────────┘
                                │ owns the access preferences
                                │ (contract data, not a call)
                                ▼
                        ┌───────────────┐
                        │  EnrolDirect  │  enforces them
                        └───────────────┘
```

- **PolicyCore makes no outbound calls.** It reads and writes its own database
  and nothing else. There is no network egress in the request path.
- **EnrolDirect depends on it conceptually, not at runtime.** PolicyCore owns
  the two online-enrolment access preferences; EnrolDirect enforces them. Today
  they travel as contract data, not over an API. A change to what a preference
  *means* is a change to a contract between two systems.
- **ClaimsPortal is a separate estate** with its own contract service. It does
  not read this database.

## 3. Components

| Path | Responsibility |
|---|---|
| `app.py` | The Streamlit portal — every screen, and the only place UI concerns live |
| `core/models.py` | The four record dataclasses. No logic, no persistence |
| `core/db.py` | SQLite schema, storage and queries. The only module that touches the database |
| `core/claims.py` | Claim submission — number generation, timestamp, default status |
| `core/amendments.py` | Amendment submission — same shape as claims |
| `core/seed.py` | Synthetic seed data. Constructs records **positionally** |
| `enrolment/eligibility.py` | *When* someone may join — waiting periods, life events, windows |
| `enrolment/dependants.py` | Dependant coverage rules |
| `enrolment/DESIGN.md` | The enrolment subsystem's own design notes |
| `static/marketing.html` | Public-facing marketing page. Not part of the application logic |
| `systems/legacy_platform/` | **Not part of this application** — see §7 |

**The layering rule:** `app.py` → `core/*` → `core/db.py`. Business logic never
lives in `app.py`, and `core/` modules carry no Streamlit or CLI concerns. A
`core/` module that imports Streamlit is a bug.

## 4. Data model

```
Policy (group contract)          PlanMember
  policy_number  ◀───────────────  policy_number
  sponsor_name                     member_id
  product_type                     member_name
  contribution                     dependents
  start_date                       enrolled_on
  status                           status
  plan_tier
       ▲                                 ▲
       │                                 │
    Claim                            (member_id)
      claim_number                       │
      policy_number ─────────────────────┘
      claim_type / amount / status / filed_at / notes

    Amendment
      amendment_number
      policy_number ────▶ Policy
      amendment_type / requested_change
      effective_date / contact_phone / contact_email / filed_at
```

**Field order is a contract, not a detail.** `core/seed.py` constructs records
with **positional** arguments. Every field added to a dataclass must go **last
and carry a default**, or seeding breaks — and it breaks at reseed time, far
from the edit that caused it. `tests/test_unit_policycore.py` pins this.

Products written: Group Life, Health, Dental, Disability, Critical Illness.
Contract status: Active | Lapsed | Terminated.

## 5. Key behaviours

**Plan tiers are ordered.** Standard → Premium → Plus. A tier change
recalculates the sponsor's monthly contribution as
`contribution / old_multiplier × new_multiplier`, rounds to 2 decimals, and
persists it. Downgrades, same-tier changes and unknown tiers are refused with a
`ValueError` — the refusal wording is a fixed contract other scenarios cite
verbatim.

**Amendments are requests, not edits.** Filing an amendment records a
*requested* change with an effective date and a contact route. It does not
mutate the contract. The effective date is contractual — a missed one is a
breach, not a delay.

**Claims are a state machine.** Submitted → Under Review → Approved | Denied.

**Enrolment eligibility answers *when*, not *whether the channel is open*.**
Those are different questions owned by different applications; they compose and
do not overlap. See EnrolDirect for the second one.

## 6. Runtime

| Concern | How |
|---|---|
| Process | Single Streamlit process, server-rendered, no client build |
| Storage | Local SQLite at `data/mockapp.db`, created and seeded by `core/seed.py` |
| Configuration | `PORT` and `STREAMLIT_BASE_URL_PATH` from the repo-root `.env` |
| Base path | Served under `/sl_policycore/` so it can share a host behind a proxy — **the bare port root 404s by design** |
| External dependencies | None in the request path |

State is local to the instance. A second worker would serve inconsistent state.

## 7. What is *not* part of this application

**`systems/legacy_platform/` documents a separate legacy estate that this
portal does not call into.** Its own `ARCHITECTURE.md` says so in its opening
paragraph. It exists so the S3 relevance screen has a realistic corpus to rule
out.

Do not list it as this application's supporting documentation, and do not
follow it when tracing a fault. A previously generated knowledge document made
exactly this mistake, citing its subsystem design notes as PolicyCore's own —
which implies a dependency that does not exist and sends a support engineer to
the wrong place during an incident.

If it must be referenced, reference it as a *related system with no runtime
dependency*.

## 8. Where to look for what

| Question | Start at |
|---|---|
| What does a record hold? | `core/models.py` |
| How is it stored / queried? | `core/db.py` |
| How is a claim / amendment created? | `core/claims.py`, `core/amendments.py` |
| What does a screen do? | `app.py` |
| Can this person enrol yet? | `enrolment/eligibility.py` |
| May they use the *online* channel? | EnrolDirect, not here |
| What must never break? | `tests/test_regression_policycore.py` |

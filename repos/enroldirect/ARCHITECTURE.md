# EnrolDirect — Architecture

**Read this first.** Orientation for EnrolDirect: what it is, how the access
gate is built, and where to look for what. Read [`DESIGN.md`](DESIGN.md) next
for *why*, and [`README.md`](README.md) for how to run it plus the
application-knowledge sections (users, DR, business impact, escalation).

---

## 1. What this application is

The **online self-serve enrolment channel** — where a plan member joins or
changes benefits without going through a call centre — plus the analysis
surface that answers *who is allowed to use it*.

It is the only member-facing application in the estate. Its refusal messages
are customer-visible copy, not internal diagnostics.

## 2. Context

```
   PolicyCore                         EnrolDirect
   ──────────                         ───────────
   OWNS the two access      ────▶     ENFORCES them
   preferences on the                 (three-gate check)
   contract record                          │
                                             ▼
                              plan member / prospect / guest
```

- **PolicyCore owns the preferences. EnrolDirect enforces them.** A change to
  what a preference *means* is a change to a contract between two systems, not
  a local edit. That is why the population question this app exists to answer
  needed an impact analysis before anyone wrote code.
- **No runtime call.** Today the preferences arrive as contract data.
  EnrolDirect calls no other service and holds its own applicant and contract
  data in-process. It starts alone, on nothing but the virtual environment.

## 3. The two access preferences

A group contract does not simply "have online enrolment". The plan sponsor
agrees at inception *who* may self-serve:

| Preference | Written for |
|---|---|
| `Online Enrolment - Member` | People already holding an active benefit under the contract |
| `Online Enrolment - Guest` | People with no active benefit who still have reason to enrol — retiree continuations, spousal transfers, sponsor-agreed exceptions |

Both are held **as data, not as branching**, so a sponsor-specific variation is
a configuration edit rather than a code change.

The preference strings are the **integration contract** with PolicyCore. They
arrive verbatim on the contract record. Renaming one here without renaming it
there silently disables the gate it controls — because an unknown preference is
absent, and absent means *not granted*.

## 4. Applicant categories

| Category | Meaning |
|---|---|
| `MEMBER` | On the roster, holding at least one active benefit |
| `GUEST` | Not on the roster; enrolling under a sponsor-agreed exception |
| `PROSPECT` | **On the roster, holding no active benefit yet** |

**The prospect is the whole point of this application.** Neither preference was
written for them. A prospect is not a halfway state on the way to becoming a
member — it is a population the sponsor has already accepted onto the roster
but who has not taken up coverage. Treating them as a `GUEST` (a stranger to
the contract) is uncomfortable; treating them as a `MEMBER` (someone with
coverage to change) is inaccurate.

Category is **derived upstream** by plan administration. EnrolDirect is told
what someone is; it does not decide.

Two combinations are rejected at construction as upstream data faults: a
`MEMBER` with no active benefit (that is a prospect, mislabelled) and a
`PROSPECT` with one (that is a member, not yet promoted). Both would grant or
deny the wrong access silently.

## 5. The gate — three checks, in this order

```
1. Is the contract ACTIVE?          ──no──▶ refused
        │ yes
2. Does the category resolve
   to a preference?                 ──no──▶ refused
        │ yes
3. Did the sponsor enable it?       ──no──▶ refused
        │ yes
      GRANTED
```

**The order is load-bearing, not incidental.** A lapsed contract keeps whatever
preferences it was configured with. If the preference check ran first, stale
configuration on a dead contract could grant access — and no category-level
test would notice, because every category would still behave correctly.
`tests/test_unit_enroldirect.py` and the regression suite both pin the ordering.

**Every decision carries its reasons, not just a boolean.** A denial that
cannot say which gate closed becomes a support ticket, and — for the
unclassified prospect — precisely the denial a service desk gets asked to
explain.

`authorisingPreference` is recorded separately from `requiredPreference`: the
one that actually opened the gate, not the one the category nominally belongs
to. Downstream consumers word confirmations and reconcile on it, so it must be
the preference that did the work.

## 6. Enrolment reuses the gate

Enrolment runs the **same** access check — reused, not reimplemented — then
additionally confirms the plan is on the applicant's contract and open to their
category. The outcome is recorded either way, so refusals are auditable.

An enrolment path with its own copy of the access rules is how a channel ends
up admitting someone the gate would have turned away.

## 7. Components

| Path | Responsibility |
|---|---|
| `main.py` | HTTP endpoints and the console |
| `eligibility.py` | The three-gate access check — the heart of the application |
| `preferences.py` | The two preference strings and the vocabulary contract with PolicyCore |
| `applicants.py` | Applicant categories and the data-integrity rules |
| `directory.py` | Seeded contracts and applicants |
| `enrolments.py` | Enrolment execution and the in-process log |
| `benefits.py` | Plan/benefit definitions and category openness |
| `impact.py` | **Read-only analysis surface** — see below |
| `static/` | The member-facing console |
| `.baseline/` | Pristine snapshot used by the reset script |

**`impact.py` is analysis, not enforcement.** It models the gate's rules
against the seeded directory to *size* an option the gate does not implement,
and recommends one. It is read-only with respect to behaviour: acting on its
recommendation is a change to the gate, which has not been made. It recomputes
from whatever the configuration currently says rather than asserting a stored
conclusion — which is what makes it an analysis surface rather than a document.

## 8. Runtime

| Concern | How |
|---|---|
| Process | Single FastAPI/uvicorn process |
| Storage | **None.** Contracts and applicants seeded in-process; the enrolment log is in-memory |
| Configuration | `ENROLDIRECT_PORT` from the repo-root `.env` (default 8083) |
| External dependencies | **None** — runs on nothing but the virtual environment |

Nothing survives a restart, and nothing is supposed to. See `DESIGN.md` §6 for
why, and what it costs.

## 9. Where to look for what

| Question | Start at |
|---|---|
| May this person use the channel? | `eligibility.py` |
| What are the preferences called? | `preferences.py` |
| What is a prospect? | `applicants.py` |
| Why was this applicant refused? | The `reasons` on the decision |
| How many people does the open question affect? | `impact.py` |
| When may someone join at all? | PolicyCore's `enrolment/`, not here |
| What must never break? | `tests/test_regression_enroldirect.py` |

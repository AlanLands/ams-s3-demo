# ClaimsPortal — Architecture

**Read this first.** Orientation for ClaimsPortal: what it is, how the two
services fit together, and where to look for what. Read
[`DESIGN.md`](DESIGN.md) next for *why*, and [`README.md`](README.md) for how
to run it plus the application-knowledge sections (users, DR, business impact,
escalation).

---

## 1. What this application is

Two cooperating services that take a **benefit claim** from submission to an
accept/reject decision, validating it against the **group contract** it is
filed under.

They are separate processes with separate team consoles, and that separation is
the point: claim intake and contract data are owned by different teams, and the
system reflects the org chart rather than hiding it.

## 2. Context

```
   Contracts Team                          Claims Team
        │                                       │
        ▼                                       ▼
  ┌──────────────┐    GET /api/policies   ┌──────────────┐
  │ policy_
  │ service      │◀───────────────────────│ claims_      │
  │              │    (POLICY_SERVICE_URL)│ service      │
  │ :8081        │───────────────────────▶│ :8082        │
  └──────────────┘    contract record     └──────────────┘
   authority on                            adjudicates,
   contract terms                          records outcome
```

**The dependency runs one way and it is operationally load-bearing.**

- `claims_service` has a **hard runtime dependency** on `policy_service`.
- `policy_service` has **no dependency** on `claims_service`.

Therefore:

- **Start `policy_service` first.** Starting `claims_service` alone yields a
  service that answers on its port but fails every validation — which presents
  as a data fault rather than an ordering one, and costs an hour to diagnose.
- If `policy_service` is down, claim validation stops while contract lookup
  keeps working. Capacity planning and DR treat the pair as **one unit**.

`claims_service` finds `policy_service` through the `POLICY_SERVICE_URL`
environment variable, never a hard-coded address, so the pair deploys to any
host or port pairing.

## 3. Components

| Path | Responsibility |
|---|---|
| `policy_service/main.py` | Contract endpoints and the Contracts Team console |
| `policy_service/policy.py` | The `Policy` record — the published contract shape |
| `policy_service/static/` | Contracts Team console (plain HTML/JS, no build step) |
| `claims_service/main.py` | Claim endpoints, adjudication, and the Claims Team console |
| `claims_service/claim.py` | The `Claim` record |
| `claims_service/policy_client.py` | The **only** module that talks to `policy_service` |
| `claims_service/static/` | Claims Team console |
| `.baseline/` | Pristine pre-change snapshot used by the reset script |

**All cross-service traffic goes through `policy_client.py`.** One module owns
the URL, the timeout, and the error semantics. A second place issuing HTTP to
`policy_service` is how those three drift apart.

## 4. Data model

```
Policy  (policy_service — the authority)     Claim  (claims_service)
  policyNumber  ◀───────────────────────────   policyNumber
  holderName                                   id
  product                                      holderName   (copied at intake)
  status                                       memberId
  annualMaximum                                serviceType / amount
                                               description / status
                                               submittedAt
```

`PolicyView` in `policy_client.py` is the **subset** of a contract that claim
intake needs. It is intentionally narrower than `Policy`: the claims side
should not acquire a dependency on contract fields it does not use.

**Field names are a published API contract.** `policyNumber`, `holderName`,
`annualMaximum` and the rest keep their exact spelling. In prose the thing they
carry is a *group contract*; in the wire format the names do not change.

## 5. The adjudication flow

1. The Claims Team console fetches its contract dropdown **live** from
   `policy_service` (via `GET /api/claims/policy-directory`), so an adjudicator
   can only file against a contract that exists.
2. On submission, `claims_service` calls `policy_service` for the contract.
3. It applies the benefit rules — contract status and annual maximum among them.
4. It returns **ACCEPTED** or **REJECTED** with the reason, and records the
   outcome either way.

**Two failure modes are deliberately distinct:**

| Situation | Response | Meaning |
|---|---|---|
| Contract not found (404) | `find_policy` returns `None` | A routine rejection |
| Contract service unavailable | raises | An incident |

Collapsing these would let an outage present as a batch of legitimately
rejected claims. `tests/test_unit_claimsportal.py` pins the distinction.

## 6. Runtime

| Concern | How |
|---|---|
| Processes | Two independent FastAPI/uvicorn processes |
| Storage | In-memory. Contract data is seeded at start; claims accumulate in-process |
| Configuration | `POLICY_SERVICE_PORT`, `CLAIMS_SERVICE_PORT`, `POLICY_SERVICE_URL` from the repo-root `.env` |
| Consoles | Served from each service's own `static/` — plain HTML/JS, no build step |
| External dependencies | None beyond each other |

Nothing persists across a restart. See `DESIGN.md` §5 for why, and what that
costs.

## 7. Where to look for what

| Question | Start at |
|---|---|
| What does a contract hold? | `policy_service/policy.py` |
| What does a claim hold? | `claims_service/claim.py` |
| How is a claim adjudicated? | `claims_service/main.py` |
| How does claims reach policy? | `claims_service/policy_client.py` — and nowhere else |
| Why did this claim get rejected? | The recorded reason on the outcome |
| What must never break? | `tests/test_regression_claimsportal.py` |

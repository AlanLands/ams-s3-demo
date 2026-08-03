# ClaimsPortal — Design

Why this application is shaped the way it is. Read
[`ARCHITECTURE.md`](ARCHITECTURE.md) first for *what* it is;
[`README.md`](README.md) carries the operational picture.

## Scope keywords

Benefit claim intake, claim adjudication, accept reject decision, deductible,
annual maximum, group contract lookup, contract status validation, claims team
console, contracts team console, service to service REST call, claim
submission, adjudication reason, provider settlement.

---

## 1. Design intent

The system exists to answer one question reliably: **may this claim be paid
under this contract?** Everything else is in service of making that answer
correct, explainable, and attributable.

Three commitments follow:

1. **The contract is the authority.** Adjudication never guesses at contract
   terms; it asks the service that owns them.
2. **Every decision carries its reason.** An accept/reject without a reason is
   a support ticket and, if disputed, an unanswerable one.
3. **An outage must never look like a rejection.** These are different events
   with different remedies, and conflating them is a business incident.

## 2. Why two services and not one

Claim intake and contract data are owned by **different teams** with different
change cadences, different review requirements, and different consoles. A
single service would put both teams in the same deployment.

The split makes the ownership boundary explicit and forces the contract between
them to be a real interface rather than a shared function call. The cost — a
network hop and a start-order dependency — is accepted deliberately.

**The dependency direction is the design.** `claims_service` depends on
`policy_service`; never the reverse. The authority for contract data does not
know about the things that consume it. That keeps the contracts side
independently deployable and independently available.

## 3. One client module, one set of semantics

**All traffic to `policy_service` goes through `claims_service/policy_client.py`.**

That module owns three things that must not diverge:

- **The base URL**, from `POLICY_SERVICE_URL`.
- **The timeout.**
- **The error semantics** — see §4.

A second place issuing HTTP to `policy_service` is how a timeout gets set in one
path and not another, and how a 404 gets handled one way here and another way
there. One module, one behaviour.

**`PolicyView` is deliberately narrower than `Policy`.** The claims side reads
only the contract fields it actually uses. Widening it to mirror the full
contract record would create a dependency on fields that adjudication does not
need, and every future contract field would become a claims-side concern.

## 4. Missing contract vs. unavailable service

This is the most important behavioural decision in the application:

```python
404          → None    # this contract does not exist  — a routine rejection
5xx / error  → raise   # the contract service is down  — an incident
```

They are separate outcomes because they have separate remedies. A missing
contract means the adjudicator picked wrong or the data is stale — a normal
business path. A service outage means claims cannot be adjudicated at all.

Collapse them, and an outage produces a batch of claims marked rejected: they
look adjudicated, they carry a plausible reason, and nobody re-examines them
once the service comes back. That is a business incident that hides itself.

`tests/test_unit_claimsportal.py` asserts both branches for exactly this reason.

## 5. In-memory storage, and what it costs

Contract data is seeded at start; claims accumulate in-process. Nothing
survives a restart.

The constraint is the same one that governs the estate: it must run in a
locked-down sandbox with no cloud-managed services and no Docker requirement. A
database is a dependency this cannot take.

**The cost is real and must be documented rather than glossed:** the claim log
is not durable, so it cannot serve as the audit record of last resort. If claim
outcomes must survive an incident, they need shipping somewhere durable. That
is a gap in the current design, not a feature of it.

Contract data is different — it is rehydrated from the source of record on
restore, so it needs no independent backup.

## 6. Configuration over literals

`POLICY_SERVICE_URL` exists so the pair can move host or port without a code
change. It is the estate's only genuine outbound service URL, and it is the
reason ClaimsPortal can be deployed to a different port block than the one it
was developed on.

**Known constraint:** the variable is read at **module import**, so it must be
set before the process starts. The launch scripts source `.env` before exec'ing
uvicorn, so this holds in practice — but setting it after import silently does
nothing. Documented by a test rather than left to be rediscovered at 2am.

## 7. The published API contract

Module, endpoint and field names (`policy_service`, `/api/policies`,
`policyNumber`, `holderName`, `annualMaximum`) are a **published contract**.
Consumers depend on them by exact spelling.

When the rest of the estate moved to group-retirement vocabulary, this repo was
deliberately skipped. Two reasons: **claim**, **deductible** and **annual
maximum** are already correct terms for group health, dental and disability
benefits; and renaming a published wire format to improve internal prose is a
breaking change with no user-facing benefit.

In prose, the thing `policyNumber` identifies is a *group contract*. The wire
name stays.

## 8. Deliberate non-goals

| Not done | Why |
|---|---|
| Single merged service | The ownership boundary is real and should be visible |
| Persistent claim store | Sandbox constraint; the cost is documented, not hidden |
| `policy_service` calling `claims_service` | The authority must not depend on its consumers |
| Renaming the wire format | Published contract; the current terms are already correct |
| Retry/circuit-breaker in the client | Would blur the outage/rejection distinction §4 protects |

## 9. What must not regress

`tests/test_regression_claimsportal.py` is human-authored, lives outside this
directory, and **no automated process may write to it**. A suite that a change
can rewrite is not evidence the change was safe.

Anything added must pass **before and after** every change, and must stay
outside this directory.

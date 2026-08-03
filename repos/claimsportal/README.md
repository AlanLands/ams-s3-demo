# MapleSure ClaimsPortal (two services)

> **S3 target**: this repo doubles as the S3 pipeline's second enhancement
> target — "ClaimsPortal", CR-2026-043 (`crs/CR-2026-043.md`), registered as
> `claimsportal-claims-deductible` in `s3_enhancement/targets.py` and linked to
> Jira ticket AMS-103 in the AMS console. The checked-in source is the
> **pre-CR baseline** (mirrored in `.baseline/`); the AI pipeline adds the
> deductible feature live (or from the committed replay cache), generates
> `tests/test_s3_claims_deductible.py`, and proves it with `pytest`. Reset
> between rehearsals with `demo/reset_s3_claimsportal.sh`, which copies
> `.baseline/` back over the source — it does not use `git checkout`, so it is
> unaffected by the uncommitted `apps/` → `repos/` move that currently breaks
> the two PolicyCore resets. A manager can run the same thing from the
> console's `/admin` panel.

It lives under `repos/` because that is where every repository S3 _changes_
lives; `apps/` holds the console and the launch scripts. See
[`../README.md`](../README.md) for the drop-folder contract.

Two small FastAPI applications that exercise service-to-service communication
over REST. All data is synthetic — no real client data.

| Service          | Port | Role                                                                | Team UI                                         |
| ---------------- | ---- | ------------------------------------------------------------------- | ----------------------------------------------- |
| `policy_service` | 8081 | Serves MapleSure group contracts from an in-memory list             | Contracts Team console — http://localhost:8081/ |
| `claims_service` | 8082 | Accepts benefit claims and validates them by calling policy_service | Claims Team console — http://localhost:8082/    |

Each service serves its team's web console from its own `static/` directory
(plain HTML/JS, no build step). The Contracts Team console lists and filters
group contracts; the Claims Team console submits claims via a form whose
contract dropdown is fetched live from policy_service (through
`GET /api/claims/policy-directory`), and shows each claim's ACCEPTED/REJECTED
outcome.

Naming note: the module, endpoint, and field names below (`policy_service`,
`/api/policies`, `policyNumber`, …) are a published API contract that
CR-2026-043 and the committed codegen recording depend on by exact name, so
they keep their original spelling. In prose the thing they carry is a **group
contract**.

The 2026-08-03 group-retirement reskin (endorsement → amendment, premium →
contribution, coverage tier → plan tier) applied to PolicyCore and skipped
this repo on purpose. **Claim**, **deductible** and **annual maximum** are
already the right words for group health, dental and disability benefits, and
renaming the API contract on top of that would desync the committed recording.

## Run

In two terminals — Policy-Service first, since Claims-Service validates
against it. The launch scripts live with the rest of the tooling, under
`apps/`, and read their ports from `.env`:

```bash
apps/run-policy-service.sh    # from the repo root
apps/run-claims-service.sh
```

## Worked example

```bash
# 1. List group contracts (policy_service)
curl http://localhost:8081/api/policies

# 2. Submit a valid claim (claims_service calls policy_service to validate)
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-1001", "amount": 1200, "description": "Physiotherapy - 12 sessions"}'
# -> 201 ACCEPTED

# 3. Claim over the annual maximum
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-1004", "amount": 99999, "description": "Critical illness lump sum"}'
# -> 201 REJECTED_OVER_LIMIT

# 4. Claim on a lapsed contract
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-1003", "amount": 500, "description": "Massage therapy - 5 sessions"}'
# -> 201 REJECTED_POLICY_LAPSED

# 5. Unknown contract
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-9999", "amount": 100, "description": "?"}'
# -> 422 error

# 6. List submitted benefit claims
curl http://localhost:8082/api/claims
```

Health checks: `http://localhost:8081/health`, `http://localhost:8082/health`.

The policy_service URL used by claims_service can be overridden with the
`POLICY_SERVICE_URL` environment variable (defaults to `http://localhost:8081`).

---

# Application knowledge

> Sections marked **Illustrative** are representative of a group-benefits
> estate of this shape, not measurements. These services have no measured
> RPO/RTO, no financial impact study and no on-call rota behind them. Replace
> them with SME input before treating them as authoritative. All names and
> contacts are fictional.

## 1. What it does

Two cooperating services that take a benefit claim from submission to an
accept/reject decision. They are separate processes with separate team
consoles, and the split is the point: claim intake and contract data are owned
by different teams.

The flow: the Claims Team console fetches its contract dropdown live from
Policy-Service, so an adjudicator can only file against a contract that exists.
On submission, Claims-Service calls Policy-Service for the contract, applies
the benefit rules — annual maximum and contract status among them — and
returns **ACCEPTED** or **REJECTED** with the reason.

Claims-Service reaches Policy-Service through `POLICY_SERVICE_URL`, never a
hard-coded address, so the pair deploys to any host or port pairing.

**The dependency direction is operationally load-bearing.** Claims-Service has
a hard runtime dependency on Policy-Service; the reverse is not true. If
Policy-Service is down, claim validation stops while contract lookup keeps
working. Start Policy-Service first — starting Claims-Service alone yields a
service that answers but fails every validation, which presents as a data fault
rather than an ordering one.

The client also distinguishes **"this contract does not exist"** (a routine
rejection) from **"the contract service is unavailable"** (an incident).
Collapsing the two would let an outage present as a batch of rejected claims.

## 2. Intended users

| User type | Relationship |
|---|---|
| Claims adjudicator | **Primary.** Files and reviews claims via the Claims Team console |
| Contracts / policy administration team | **Primary.** Maintains contract records via the Contracts Team console |
| Plan member (employee) | Subject of a claim; not a direct user |
| Application support / maintenance | Runtime behaviour, and inter-service faults specifically |
| Operations | Run procedures, service start ordering, restarts |
| Business analyst / product | Adjudication rules and their outcomes |
| Audit & compliance | Accept/reject decisions and the reasons recorded with them |

**Internal-facing.** Both consoles are used by MapleSure staff. Assume
authenticated internal network access; both carry claim and contract data.

## 3. Disaster recovery — *Illustrative*

| Service | Tier | RTO | RPO | Rationale |
|---|---|---|---|---|
| Policy-Service | Tier 2 — Business Critical | 4 hours | 15 min | Claims-Service depends on it; its outage is functionally a ClaimsPortal outage |
| Claims-Service | Tier 3 — Business Operational | 8 hours | 1 hour | Claim intake can be queued or handled manually for a working day |

| Item | Method | Frequency |
|---|---|---|
| Contract data | Rehydrated from the source of record on restore — no independent backup | On deploy |
| Application configuration | Version-controlled with the deployment | Every change |
| Source and release artefacts | Version control + artefact repository | Every commit / build |

Recovery outline:

1. Assess scope.
2. Provision host; restore runtime from the pinned dependency manifest.
3. Apply environment configuration — in particular `POLICY_SERVICE_URL`, which
   is what lets the pair be repointed without a rebuild.
4. **Start Policy-Service before Claims-Service** (see above).
5. Verify: run `tests/test_regression_claimsportal.py`; confirm the contract
   dropdown populates and one claim adjudicates end to end.
6. Notify the business owner.

**Known gaps.** Contract data has no independent backup — recovery depends on
the upstream source of record being available. Start ordering is a documented
manual step rather than an enforced dependency. The procedure is not rehearsed,
so the RTO figures are estimates.

## 4. Business impact — *Illustrative*

**Process supported:** benefit claim intake and adjudication against contract
terms. **Business owner:** Claims Operations.

| Outage duration | Impact |
|---|---|
| 0–4 hours | Adjudication pauses; claims queue |
| 4–24 hours | Claim settlement SLA at risk; manual adjudication begins |
| > 24 hours | Backlog exceeds manual capacity; provider payment delays; complaint volume rises |

**Financial.** Delayed settlement carries interest exposure and
provider-relationship cost.

**Regulatory and contractual.** Group contracts carry service standards agreed
with sponsors. The accept/reject decision and its recorded reason are the
evidence trail if a rejection is disputed.

**Operational.** Policy-Service's availability effectively sets ClaimsPortal's.
Capacity planning must treat the pair as one unit, not two services.

**Peak periods.** Plan year start, and any period following a benefit change
that drives claim volume.

## 5. Organisation and escalation — *Illustrative sample*

| Level | Role | Responsibility | Response target | Contact |
|---|---|---|---|---|
| L1 | Service Desk | Triage, known-error lookup, restart per runbook | 15 min | servicedesk@maplesure.example · x4100 |
| L2 | Application Support — Group Benefits | Diagnosis, configuration fixes, coordinate restore | 30 min (Sev 1) | ams-groupbenefits@maplesure.example · x4210 |
| L3 | Engineering — Benefits Platform | Code defects, DR execution | 1 hour (Sev 1) | benefits-platform@maplesure.example · x4315 |
| L4 | Service Owner | Business decisions, external communication, invoke DR | 2 hours | s.maiti@maplesure.example |

| Severity | Definition | Example |
|---|---|---|
| Sev 1 | Either service unavailable | Policy-Service down — all validation fails |
| Sev 2 | Major function degraded, workaround exists | Claim validation intermittent; dropdown not populating |
| Sev 3 | Minor function impaired | Console display defect; filter wrong |
| Sev 4 | Cosmetic or informational | Label wording |

| Role | Name | Contact |
|---|---|---|
| Service Owner — Group Benefits | Sudipta Maiti | s.maiti@maplesure.example |
| Business Owner — Claims Operations | Priya Raghunathan | p.raghunathan@maplesure.example |
| Application Support Lead | AMS — Group Benefits | ams-groupbenefits@maplesure.example |
| Engineering Lead | Benefits Platform Engineering | benefits-platform@maplesure.example |
| Infrastructure / Hosting | Platform Operations | platform-ops@maplesure.example |

**Vendors.** No third party holds an operational dependency. The runtime is
open-source and pinned — no managed service, licence key or vendor support
contract in the request path. *(Confirm with Procurement before publishing.)*

**Support model.** L1 24×7; L2 business hours plus on-call; L3 on-call. Weekly
rotation. Freeze during plan year start. Quarterly service review.

## 6. Testing

| Level | Where | Covers |
|---|---|---|
| Unit | `tests/test_unit_claimsportal.py` | Service URL from configuration; missing contract vs. service outage |
| Regression | `tests/test_regression_claimsportal.py` | Claim adjudication against contract data, across both services |

Both live outside this directory deliberately: no automated process may write
to them, which is what makes them an independent check.

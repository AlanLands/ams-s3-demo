# PolicyCore — MapleSure's group benefits plan administration portal

> **Start with [`ARCHITECTURE.md`](ARCHITECTURE.md), then [`DESIGN.md`](DESIGN.md).**
> Those two are the orientation pair for this application — what it is and how
> it is put together, then why it is shaped that way. Read them before reading
> the source, and before answering questions about this application. This file
> covers how to run it and the application-knowledge sections (users, disaster
> recovery, business impact, escalation).

The system of record for the group benefits book: group contracts, the plan
members enrolled under them, the claims filed against them, and the amendments
requested to them. Python / Streamlit / SQLite.

```bash
apps/run-policycore.sh    # http://localhost:8501/sl_policycore
```

Served under a base path so it can share a host behind a reverse proxy — the
bare port root 404s by design. The path comes from `STREAMLIT_BASE_URL_PATH`
in the repo-root `.env` and must stay in step with `MOCKAPP_URL` and the
console's `VITE_MOCKAPP_URL`.

It lives under `repos/` because that is where every repository S3 operates on
lives; `apps/` holds the console and the launch scripts. See
[`../README.md`](../README.md) for the drop-folder contract.

> **S3 target.** This repo is the pipeline's first enhancement target, twice
> over: CR-2026-041 (plan tier upgrade, `mockapp-coverage-upgrade`) and
> CR-2026-042 (amendment priority, `mockapp-endorsement-field-add`). The
> checked-in source is the pre-CR baseline. Reset with `demo/reset_s3.sh` and
> `demo/reset_s3_endorsement.sh`, or from the console's `/admin` panel.
>
> `AGENTS.md` and `CLAUDE.md` in this directory are the agent-harness prompt
> contract for CR-2026-041, not general documentation. They are pinned, and
> they must stay in sync with each other.

## Layout

| Path | Holds |
|---|---|
| `app.py` | The Streamlit portal — every screen |
| `core/models.py` | The four record dataclasses |
| `core/db.py` | SQLite storage, schema and queries |
| `core/claims.py` | Claim submission logic |
| `core/amendments.py` | Amendment submission logic |
| `core/seed.py` | Synthetic seed data |
| `enrolment/` | Enrolment eligibility and dependant rules, with its own `DESIGN.md` |
| `systems/legacy_platform/` | **Not part of this application** — see below |
| `static/marketing.html` | Public-facing marketing page |

**`systems/legacy_platform/` documents a separate legacy estate that this
portal does not call into.** Its own `ARCHITECTURE.md` says so in its opening
paragraph. It is present so the S3 relevance screen has a realistic corpus to
rule out, and it must not be listed as this application's supporting
documentation — doing so implies a dependency that does not exist and sends a
support engineer to the wrong subsystem.

---

# Application knowledge

> Sections marked **Illustrative** are representative of a group-benefits
> estate of this shape, not measurements. This application has no measured
> RPO/RTO, no financial impact study and no on-call rota behind it. Replace
> them with SME input before treating them as authoritative. All names and
> contacts are fictional.

## 1. What it does

An employer — the **plan sponsor** — holds a **group contract**. That sponsor's
employees enrol under it as **plan members**, optionally covering dependants.
PolicyCore owns that structure and the operations over it.

| Record | Represents |
|---|---|
| Group contract | The sponsor's agreement: contribution, product type, plan tier, status |
| Plan member | An employee enrolled under a contract, with a dependant count |
| Claim | A benefit claim filed against a contract by a member |
| Amendment | A requested change to an in-force contract, with an effective date |

Capabilities:

- **Contract administration** — list and filter the book, open a contract and
  review its attributes, see the enrolled member roster.
- **Plan tier management** — contracts sit on an ordered tier (Standard →
  Premium → Plus). A tier change recalculates the sponsor's monthly
  contribution by the ratio of the two tiers' multipliers and persists it.
  Downgrades, same-tier changes and unknown tiers are refused with an error.
- **Claim intake** — a claim is filed against a contract with a service type,
  amount and notes, then moves Submitted → Under Review → Approved/Denied.
- **Amendment requests** — a change to an in-force contract (plan tier change,
  dependant add, address change) is *filed with an effective date and contact
  details* rather than applied directly. The effective date is contractual.
- **Enrolment eligibility** — waiting periods, life events and enrolment
  windows, owned by `enrolment/`. This answers *when* someone may join. It
  composes with, and does not overlap, EnrolDirect's question of *whether the
  online channel is open to them*.

Products written: Group Life, Health, Dental, Disability, Critical Illness.

Data persists to a local SQLite database. Server-rendered; no client build.

## 2. Intended users

| User type | Relationship to this application |
|---|---|
| Plan administrator / benefits admin | **Primary.** Daily contract and member administration |
| Contracts / policy administration team | Maintains contract records, tiers and the access preferences EnrolDirect enforces |
| Claims adjudicator | Files and reviews claims filed against contracts |
| Plan sponsor (employer HR) | Represented, not a direct user — served through their administrator |
| Plan member (employee) | Represented as a record; not a user of this portal |
| Application support / maintenance | Runtime behaviour and incident diagnosis |
| Operations | Run procedures, routine checks, restarts |
| Business analyst / product | Capability and data-model review |
| Audit & compliance | The amendment trail and its effective dates |

**Internal-facing.** Every user is MapleSure staff acting on behalf of sponsors
and members. Assume authenticated internal network access. Every screen carries
personal and benefits information.

## 3. Disaster recovery — *Illustrative*

**Tier 2 — Business Critical. RTO 4 hours, RPO 15 minutes.** This is the system
of record: an outage halts contract and amendment administration, and data loss
beyond one transaction window is unacceptable.

| Item | Method | Frequency | Retention |
|---|---|---|---|
| SQLite relational store | Full backup + transaction log shipping | Full nightly, logs every 15 min | 35 days daily, 13 months monthly |
| Application configuration | Version-controlled with the deployment | Every change | Full repository history |
| Source and release artefacts | Version control + artefact repository | Every commit / build | Indefinite |

Recovery outline:

1. Assess scope — single service, single host, or site.
2. Provision host; restore runtime from the pinned dependency manifest.
3. Restore the database from the latest full backup plus logs to the last
   consistent point.
4. Apply the target environment's configuration (port, base path, service URLs).
5. Start and verify: run `tests/test_regression_policycore.py` and
   `tests/test_regression_policycore_enrolment.py`; confirm one end-to-end
   contract lookup, claim submission and amendment filing.
6. Reconcile transactions between the RPO point and the failure from source
   documents.
7. Notify the business owner.

**Known gaps.** The procedure is documented but not rehearsed, so the RTO above
is an estimate rather than an observation. Restoring a database created before
the 2026-08-03 vocabulary change requires dropping the legacy `endorsements`
table first — a foreign key from it to `policies` otherwise makes the restore
fail in a way that cannot be recovered without deleting the database file.

## 4. Business impact — *Illustrative*

**Process supported:** group contract administration, plan tier changes,
amendment handling, member roster maintenance.
**Business owner:** Plan Administration (Group Benefits Operations).

| Outage duration | Impact |
|---|---|
| 0–4 hours | Contract changes queue. No member-visible effect. |
| 4–24 hours | Amendment SLAs breached; tier changes risk missing their effective dates. |
| > 24 hours | Contribution billing accuracy at risk; regulatory reporting delayed. |

**Financial.** A missed tier change means the sponsor is billed at the wrong
contribution, and correcting it is retroactive across their whole roster.

**Regulatory and contractual.** Amendment effective dates are contractual, not
advisory — a missed effective date is a breach, not a delay. The amendment
trail is the evidence if a change is disputed.

**Operational.** PolicyCore owns the access preferences EnrolDirect enforces,
so a configuration error here surfaces as an access decision there. The two
systems share a contract; they do not share a database.

**Peak periods.** Month-end and quarter-end (contribution billing, amendment
effective dates) and plan year start (new contracts, tier changes taking
effect). Change freezes should cover both.

## 5. Organisation and escalation — *Illustrative sample*

| Level | Role | Responsibility | Response target | Contact |
|---|---|---|---|---|
| L1 | Service Desk | Triage, known-error lookup, restart per runbook | 15 min | servicedesk@maplesure.example · x4100 |
| L2 | Application Support — Group Benefits | Diagnosis, configuration and data fixes, coordinate restore | 30 min (Sev 1) | ams-groupbenefits@maplesure.example · x4210 |
| L3 | Engineering — Benefits Platform | Code defects, DR execution, structural change | 1 hour (Sev 1) | benefits-platform@maplesure.example · x4315 |
| L4 | Service Owner | Business decisions, external communication, invoke DR | 2 hours | s.maiti@maplesure.example |

| Severity | Definition | Example |
|---|---|---|
| Sev 1 | Portal unavailable, or contract data unreadable | Database corrupt; portal will not start |
| Sev 2 | Major function degraded, workaround exists | Amendment filing failing; tier change rejected incorrectly |
| Sev 3 | Minor function impaired | Roster filter wrong; display defect |
| Sev 4 | Cosmetic or informational | Label wording |

| Role | Name | Contact |
|---|---|---|
| Service Owner — Group Benefits | Sudipta Maiti | s.maiti@maplesure.example |
| Business Owner — Plan Administration | Marie-Claude Tremblay | mc.tremblay@maplesure.example |
| Application Support Lead | AMS — Group Benefits | ams-groupbenefits@maplesure.example |
| Engineering Lead | Benefits Platform Engineering | benefits-platform@maplesure.example |
| Database Administration | Data Services | data-services@maplesure.example |

**Vendors.** No third party holds an operational dependency. The runtime is
open-source and pinned in the dependency manifest — no managed service, licence
key or vendor support contract sits in the request path. *(Confirm with
Procurement before publishing; this is an architectural observation, not a
contract review.)*

**Support model.** L1 24×7; L2 business hours plus on-call; L3 on-call. Weekly
rotation. Configuration changes are standard; code changes normal. Freeze
during month-end and plan year start. Quarterly service review with the
business owner above.

## 6. Testing

| Level | Where | Covers |
|---|---|---|
| Unit | `tests/test_unit_policycore.py` | The record field-order contract seed data depends on |
| Regression | `tests/test_regression_policycore.py` | Contract list/detail, member roster, claim submission and listing |
| Regression | `tests/test_regression_policycore_enrolment.py` | Enrolment eligibility rules |

Both regression suites are human-authored and live outside this directory
deliberately: no automated process may write to them, which is what makes them
an independent check that a change broke nothing.

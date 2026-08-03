# Application Knowledge — Source Content

Source material for the Application Knowledge Document. Covers the three
MapleSure Insurance applications in this estate: **PolicyCore**,
**ClaimsPortal** and **EnrolDirect**.

> **Editor's note — delete this block before publishing.**
>
> Sections 1, 2 and the data models are **factual**: they were written from the
> source and are accurate as of 2026-08-03. Sections 3 (disaster recovery),
> 4 (business impact) and 5 (organisation and escalation) are **illustrative
> samples**. These applications have no measured RPO/RTO, no financial impact
> study and no on-call rota behind them — the figures are representative of a
> group-benefits estate of this shape, not observations. Replace them with SME
> input before the document is treated as authoritative, or mark them
> `[Assumed — pending SME confirmation]` in the published version.
>
> All names, contacts and organisational units below are fictional. MapleSure
> Insurance is a fictional insurer.

## How this maps to the knowledge document

| Knowledge doc section | Content below |
|---|---|
| 1.0 Introduction, 2.1 System Overview | §1 Application working in brief |
| 1.1 Intended Audience, 2.3 Application Audience | §2 Intended users |
| 2.7 Business Impact Analysis | §4 Business impact |
| 2.4 Business / 2.5 Vendor / 2.6 System Contacts | §5 Organisation |
| 1.2 Supporting Documentation | §6 — read this one, the current draft is wrong |
| 2.26 Testing (Project Phase) | §7 Testing |

---

# 1. Application working in brief

## 1.1 PolicyCore — group benefits plan administration portal

The system of record for MapleSure's group benefits book. An employer (the
**plan sponsor**) holds a **group contract**; that sponsor's employees enrol
under it as **plan members**, optionally covering dependants.

PolicyCore owns four record types and the operations over them:

| Record | What it represents |
|---|---|
| Group contract | The sponsor's agreement — contribution, product type, plan tier, status |
| Plan member | An employee enrolled under a contract, with a dependant count |
| Claim | A benefit claim filed against a contract by a member |
| Amendment | A requested change to an in-force contract, with an effective date |

Core capabilities:

- **Contract administration** — list and filter the book, open a contract and
  see its attributes, review the enrolled member roster.
- **Plan tier management** — contracts sit on an ordered tier (Standard →
  Premium → Plus). A tier change recalculates the sponsor's monthly
  contribution by the ratio of the two tiers' multipliers and persists the new
  figure. Downgrades, same-tier changes and unknown tiers are refused.
- **Claim intake** — a claim is filed against a contract with a service type,
  amount and notes, and moves through Submitted → Under Review →
  Approved/Denied.
- **Amendment requests** — a change to an in-force contract (plan tier change,
  dependant add, address change) is filed with an effective date and contact
  details rather than applied directly.

Data persists to a local relational store. The portal is a server-rendered web
application; there is no separate client build.

**Product types written:** Group Life, Health, Dental, Disability, Critical
Illness.

## 1.2 ClaimsPortal — claims adjudication against contract data

Two cooperating services that together take a benefit claim from submission to
an accept/reject decision. They are separate processes with separate team
consoles, and the split is the point: claim intake and contract data are owned
by different teams.

| Service | Role | Console |
|---|---|---|
| Policy-Service | Serves group contract records — the authority on what a contract covers | Contracts Team console |
| Claims-Service | Accepts claims and validates each one by calling Policy-Service | Claims Team console |

The flow: the Claims Team console fetches its contract dropdown live from
Policy-Service, so an adjudicator can only file against a contract that
actually exists. On submission Claims-Service calls Policy-Service for the
contract, applies the benefit rules — deductible and annual maximum among them
— and returns an **ACCEPTED** or **REJECTED** outcome with its reason.

Claims-Service reaches Policy-Service through a configured base URL, never a
hard-coded address, so the pair can be deployed to any host or port pairing.

**Operational consequence worth documenting:** Claims-Service has a hard
runtime dependency on Policy-Service. If Policy-Service is down, claim
validation stops; contract lookup alone continues to work.

## 1.3 EnrolDirect — online enrolment channel

The self-serve channel a plan member uses to join or change benefits without
going through a call centre, plus the analysis surface that answers *who is
allowed to use it*.

Access is governed by two **access preferences** that the plan sponsor agrees
at contract inception:

| Preference | Written for |
|---|---|
| Online Enrolment – Member | People already holding an active benefit under the contract |
| Online Enrolment – Guest | People with no active benefit — retiree continuations, spousal transfers, sponsor-agreed exceptions |

**The ownership split is load-bearing:** PolicyCore *owns* those preferences
(they live on the contract record); EnrolDirect *enforces* them. A change to
what a preference means is therefore a change to a contract between two
systems, not a local edit.

An eligibility check runs three gates in a fixed order:

1. **Is the contract active?** A lapsed contract retains whatever preferences
   it was configured with, so this must run first — otherwise stale
   configuration could grant access.
2. **Does the applicant's category resolve to a preference?**
3. **Did the sponsor enable that preference?**

Every decision carries its reason, not just a boolean — a denial that cannot
say which gate closed becomes a support ticket.

Enrolment itself reuses that same gate rather than reimplementing it, then
additionally confirms the plan is on the applicant's contract and open to
their category. The outcome is recorded either way, so refusals are auditable.

EnrolDirect is self-contained: it holds its own applicant and contract data and
calls no other service at runtime.

---

# 2. Intended users

## 2.1 By application

| User type | PolicyCore | ClaimsPortal | EnrolDirect |
|---|---|---|---|
| Plan administrator / benefits admin | Primary — daily contract and member administration | — | — |
| Claims adjudicator | Files and reviews claims | Primary — Claims Team console | — |
| Contracts / policy administration team | Maintains contract records and tiers | Primary — Contracts Team console | Owns the preference configuration consumed here |
| Plan member (employee) | Indirect — represented, not a user | Indirect — subject of a claim | **Primary — the self-serve end user** |
| Prospect / non-active applicant | — | — | Retiree continuations, spousal transfers, sponsor-agreed exceptions |
| Plan sponsor (employer HR) | Reviewed via their administrator | — | Sets the access preferences that gate the channel |
| Application support / maintenance | Runtime behaviour, incident diagnosis | Runtime behaviour, inter-service faults | Runtime behaviour, gate decisions |
| Operations | Run procedures, routine checks, restarts | Same, plus service-dependency ordering | Same |
| Business analyst / product | Capability and data review | Adjudication rules | Access policy and its population impact |
| Audit & compliance | Amendment trail | Accept/reject decisions and reasons | Access decisions and their recorded reasons |

## 2.2 Access characteristics

- **PolicyCore and ClaimsPortal are internal-facing.** Users are MapleSure
  staff acting on behalf of sponsors and members. Assume authenticated internal
  network access.
- **EnrolDirect is member-facing.** It is the only one of the three whose
  primary user is outside the organisation, which raises its availability
  profile and makes its refusal messages customer-visible copy rather than
  internal diagnostics.
- Contract data is visible in all three. Treat every screen as carrying
  personal and benefits information.

---

# 3. Disaster recovery plan

> **Illustrative — no measured RPO/RTO exists for these applications.**
> Figures below are representative targets for a group-benefits estate of this
> shape and require SME confirmation.

## 3.1 Recovery objectives (proposed)

| Application | Tier | RTO | RPO | Rationale |
|---|---|---|---|---|
| PolicyCore | Tier 2 – Business Critical | 4 hours | 15 minutes | System of record. Outage halts contract and amendment administration; data loss is unacceptable beyond one transaction window. |
| ClaimsPortal – Policy-Service | Tier 2 – Business Critical | 4 hours | 15 minutes | Claims-Service depends on it; its outage is functionally a ClaimsPortal outage. |
| ClaimsPortal – Claims-Service | Tier 3 – Business Operational | 8 hours | 1 hour | Claim intake can be queued or handled manually for a working day. |
| EnrolDirect | Tier 2 – Business Critical | 4 hours | 1 hour | Member-facing. Outage during an open-enrolment window is externally visible and time-boxed by the enrolment period. |

## 3.2 Backup approach

| Item | Method | Frequency | Retention |
|---|---|---|---|
| PolicyCore relational store | Full backup + transaction log shipping | Full nightly, logs every 15 min | 35 days daily, 13 months monthly |
| ClaimsPortal contract data | Rehydrated from source of record on restore — no independent backup | On deploy | N/A |
| Application configuration | Version-controlled with the deployment | Every change | Full repository history |
| Application source and release artefacts | Version control + artefact repository | Every commit / build | Indefinite |

Configuration is held in environment variables rather than in code, so a
recovered instance is repointed by changing its environment — no rebuild is
required to move an application between hosts or port assignments.

## 3.3 Recovery procedure (outline)

1. **Assess** — confirm scope: single service, single host, or site.
2. **Restore infrastructure** — provision host, restore runtime and
   dependencies from the pinned dependency manifest.
3. **Restore data** — PolicyCore's store from the most recent full backup plus
   logs to the last consistent point.
4. **Restore configuration** — apply the environment configuration for the
   target environment (service URLs, ports, allowed origins).
5. **Start in dependency order** — Policy-Service before Claims-Service.
   Starting Claims-Service first yields a service that answers but fails every
   validation, which presents as a data fault rather than an ordering one.
6. **Verify** — run the regression suite for each application; confirm
   cross-service calls resolve; confirm one end-to-end transaction per app.
7. **Reconcile** — identify transactions between the RPO point and the failure;
   re-key from source documents.
8. **Communicate** — notify business owner and, for EnrolDirect, confirm
   member-facing messaging.

## 3.4 Failback and testing

- **DR test cadence:** semi-annual, alternating tabletop and live failover.
- **Last test:** *[Fill in — none performed]*
- **Failback:** during a scheduled maintenance window once primary is stable
  for 24 hours, replaying any transactions written to the DR instance.

## 3.5 Known gaps

Stating these is more useful than an unblemished plan:

- No independent backup of ClaimsPortal contract data — recovery depends on
  the upstream source of record being available.
- Recovery procedure is documented but **not yet rehearsed**; the RTO figures
  above are estimates, not observations.
- Service start ordering is currently a documented manual step rather than an
  enforced dependency.

---

# 4. Business impact

> **Illustrative — no financial impact study has been performed.** Volumes and
> costs are representative and require business-owner confirmation.

## 4.1 Business processes supported

| Application | Process | Business owner |
|---|---|---|
| PolicyCore | Group contract administration, plan tier changes, amendment handling, member roster maintenance | Group Benefits Operations |
| ClaimsPortal | Benefit claim intake and adjudication against contract terms | Claims Operations |
| EnrolDirect | Member self-service enrolment and benefit changes | Member Experience |

## 4.2 Impact of unavailability

| Application | 0–4 hours | 4–24 hours | > 24 hours |
|---|---|---|---|
| PolicyCore | Contract changes queue; no member-visible effect | Amendment SLAs breached; tier changes miss effective dates | Contribution billing accuracy at risk; regulatory reporting delayed |
| ClaimsPortal | Adjudication pauses; claims queue | Claim settlement SLA at risk; manual adjudication begins | Backlog exceeds manual capacity; provider payment delays; complaint volume rises |
| EnrolDirect | Members redirected to call centre | Call centre volume spike; enrolment abandonment | Enrolment window may be missed entirely — coverage gaps with contractual consequences |

## 4.3 Impact dimensions

**Financial.** Delayed claim settlement carries interest exposure and
provider-relationship cost. Contribution mis-billing following a missed tier
change requires retroactive correction across the sponsor's whole roster.
EnrolDirect displacing members to the call centre substitutes a low-cost
channel with a high-cost one.

**Regulatory and contractual.** Group contracts carry service standards agreed
with sponsors. Amendment effective dates and enrolment windows are
contractual — a missed effective date is a breach, not a delay. Access
decisions and their reasons are the evidence trail if a refusal is disputed.

**Customer and reputational.** EnrolDirect is the only member-facing system of
the three; its outages are externally visible and concentrated in enrolment
periods when attention is highest. A refusal a member cannot get an explanation
for converts directly into a complaint.

**Operational.** ClaimsPortal's inter-service dependency means Policy-Service's
availability effectively sets ClaimsPortal's. Capacity planning must treat the
pair as one unit.

## 4.4 Peak periods

| Period | Driver | Applications affected |
|---|---|---|
| Annual open enrolment | Sponsor-defined enrolment windows | EnrolDirect (severe), PolicyCore (elevated) |
| Month-end / quarter-end | Contribution billing, amendment effective dates | PolicyCore |
| Plan year start | New contracts, tier changes taking effect | All three |

Change freezes should cover open-enrolment windows and month-end for the
applications listed.

---

# 5. Organisation details

> **Sample.** Names, teams and contacts are fictional and illustrative.

## 5.1 Escalation matrix

| Level | Role | Responsibility | Response target | Contact |
|---|---|---|---|---|
| L1 | Service Desk | Triage, known-error lookup, restart per runbook | 15 min | servicedesk@maplesure.example · x4100 |
| L2 | Application Support — Group Benefits | Diagnosis, configuration and data fixes, coordinate restore | 30 min (Sev 1) | ams-groupbenefits@maplesure.example · x4210 |
| L3 | Engineering — Benefits Platform | Code defects, DR execution, structural change | 1 hour (Sev 1) | benefits-platform@maplesure.example · x4315 |
| L4 | Service Owner | Business decisions, external communication, invoke DR | 2 hours | See §5.3 |

## 5.2 Severity definitions

| Severity | Definition | Example | Notify |
|---|---|---|---|
| Sev 1 | Application unavailable, or member-facing function down | EnrolDirect down during open enrolment; Policy-Service down | L2 + L3 + Service Owner immediately |
| Sev 2 | Major function degraded, workaround exists | Amendment filing failing; claim validation intermittent | L2, L3 within 1 hour |
| Sev 3 | Minor function impaired, limited users | Roster filter incorrect; console display defect | L2 during business hours |
| Sev 4 | Cosmetic or informational | Label wording, formatting | Backlog |

## 5.3 Contacts

**Business contacts**

| Role | Name | Area | Contact |
|---|---|---|---|
| Service Owner — Group Benefits | Sudipta Maiti | All three applications | s.maiti@maplesure.example |
| Business Owner — Claims Operations | Priya Raghunathan | ClaimsPortal | p.raghunathan@maplesure.example |
| Business Owner — Member Experience | Daniel Okonkwo | EnrolDirect | d.okonkwo@maplesure.example |
| Business Owner — Plan Administration | Marie-Claude Tremblay | PolicyCore | mc.tremblay@maplesure.example |

**System contacts**

| Role | Team | Contact |
|---|---|---|
| Application Support Lead | AMS — Group Benefits | ams-groupbenefits@maplesure.example |
| Engineering Lead | Benefits Platform Engineering | benefits-platform@maplesure.example |
| Infrastructure / Hosting | Platform Operations | platform-ops@maplesure.example |
| Database Administration | Data Services | data-services@maplesure.example |
| Information Security | Security Operations | secops@maplesure.example |

**Vendor contacts**

No third-party vendor holds an operational dependency in these applications.
The runtime is open-source and pinned in the dependency manifest; there is no
managed service, licence key, or vendor support contract in the request path.
*[Confirm with Procurement before publishing — this is an architectural
observation, not a contract review.]*

## 5.4 Support model

| Aspect | Detail |
|---|---|
| Support hours | L1 24×7; L2 business hours + on-call; L3 on-call |
| On-call rota | Weekly rotation within each team |
| Change process | Standard change for configuration; normal change for code; freeze during open enrolment and month-end |
| Review cadence | Quarterly service review with the business owners named above |

---

# 6. Supporting documentation — correction

The current draft's §1.2 lists these as the applications' supporting
documentation:

- `systems/legacy_platform/ARCHITECTURE.md`
- `systems/legacy_platform/audit/DESIGN.md`
- `systems/legacy_platform/billing/DESIGN.md`
- …and the reporting, risk, settlement and underwriting design notes

**These do not describe any of the three applications.** They document a
separate legacy platform that the portal does not call into — its own
architecture overview says so in its opening paragraph. Listing them as
supporting documentation for PolicyCore implies a dependency that does not
exist, and would send a support engineer to the wrong subsystem during an
incident.

The correct supporting documentation set:

| Document | Location | Owner |
|---|---|---|
| PolicyCore — data models and record structure | `repos/policycore/core/models.py` | Benefits Platform Engineering |
| ClaimsPortal — service overview and API contract | `repos/claimsportal/README.md` | Benefits Platform Engineering |
| EnrolDirect — access model, gates and enrolment rules | `repos/enroldirect/README.md` | Benefits Platform Engineering |
| Application hosting — ports, base paths, configuration | `apps/README.md` and `.env.example` | Platform Operations |
| Deployment and runbook | `deploy/aws/README.md` | Platform Operations |

If the legacy platform documentation is to be referenced at all, it belongs in
a "related systems — no runtime dependency" note, not in the supporting
documentation table.

---

# 7. Testing

Replaces the current draft's §2.26, which reports Unit as `[Fill in]` and
Integration as "Not present". Both are now inaccurate.

| Level | Framework | Where it runs | Coverage / criteria |
|---|---|---|---|
| Unit | pytest | `tests/test_unit_*.py` — local and CI | Access-gate logic, record field contracts, inter-service client behaviour. 37 cases across the three applications. |
| Integration | pytest + FastAPI TestClient | `tests/test_regression_*.py` | End-to-end flows per application, asserted over HTTP against the running app rather than by calling functions directly. |
| Regression | pytest | `tests/test_regression_*.py` | Human-authored invariant suites, one per application. Must pass **before and after** every change. |
| End-to-end | Manual | Local / deployed instance | Contract administration, claim adjudication, and enrolment journeys. |
| UAT | *[Fill in — SME input required]* | *[Fill in]* | *[Fill in]* |

## 7.1 The regression suites are deliberately independent

One property is worth stating in the published document because it is unusual
and it is the reason the other numbers can be trusted:

**No automated process may write to the regression suites.** They are
checked-in and human-authored, they live outside every application's own
directory, and an automated test check asserts they are never named as a
generation target. If a change could rewrite the suite that verifies it, the
suite verifies nothing.

The same rule governs the unit suites added alongside them.

## 7.2 What the suites assert

| Suite | Application | Focus |
|---|---|---|
| `test_unit_enroldirect.py` | EnrolDirect | Gate ordering, preference vocabulary, applicant data-integrity rules, every decision carries a reason |
| `test_unit_policycore.py` | PolicyCore | Record field-order contract that seed data depends on |
| `test_unit_claimsportal.py` | ClaimsPortal | Service URL resolved from configuration, missing contract vs. service outage distinguished |
| `test_regression_policycore.py` | PolicyCore | Contract list/detail, member roster, claim submission and listing |
| `test_regression_policycore_enrolment.py` | PolicyCore | Enrolment eligibility rules |
| `test_regression_claimsportal.py` | ClaimsPortal | Claim adjudication against contract data across both services |
| `test_regression_enroldirect.py` | EnrolDirect | Access-gate outcomes and enrolment refusals, over HTTP |

## 7.3 Notable design point for the document

ClaimsPortal's client distinguishes **"this contract does not exist"** (a
routine rejection) from **"the contract service is unavailable"** (an
incident). Collapsing the two would let an outage present as a batch of
rejected claims — a support-relevant behaviour, and one the unit suite pins
explicitly.

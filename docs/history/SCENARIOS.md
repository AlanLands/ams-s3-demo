# Scenario → Capability Decomposition

> **Historical.** This is the original six-scenario scope from the `sixFold`
> tabletop demo, kept for background only — see `docs/history/README.md`. This
> repository builds S3 (Enhancement Delivery) alone, its targets now live under
> `repos/`, and the S3 vocabulary has since been reskinned for group retirement
> (amendment, plan tier, contribution, plan sponsor). Nothing below has been
> updated to match, deliberately: it is a record of what was decided then, not a
> statement of what is true now.
>
> Three references to named individuals and one to a named organisation were
> replaced with role descriptions on 2026-08-03 (CLAUDE.md hard rule #2 — no
> real names in any document that can be shared). Nothing else in the historical
> content was altered.

Scope definition for the 90-minute demo: each scenario broken into discrete
capabilities, the demo beat that proves it, its data source, and build effort.
Effort: **S** ≤ ½ day · **M** ~1 day · **L** ~2 days (one person, AI-assisted build).

Priority key: **CORE** = must land for the demo · **PLUS** = show if time allows ·
**TALK** = roadmap slide / walkthrough only, not built.

---

## S1 — Incident Triage & Resolution

| # | Capability | Demo beat | Data | Effort | Priority |
|---|-----------|-----------|------|--------|----------|
| 1.0 | **Data-quality gate** (differentiator — beyond the ask; an existing prompt from the team was available) | Incoming incident scored: investigable or not → auto-drafted mail to requestor asking for specifics | incidents.csv | S | CORE |
| 1.1 | Two-level triage: **rule-based first** (editable per-app rules as text) **+ AI** category/priority | Rules fire visibly, then AI assigns priority with reasoning; client can edit rules live | incidents.csv | M | CORE |
| 1.2 | Assignment-group routing | AI routes to correct group, citing the rule/precedent (today: manual L1 dispatch) | incidents.csv | S | CORE |
| 1.3 | Similar-incident retrieval | "Seen 4 times before — here's what fixed it" with links | incidents.csv | M | CORE |
| 1.4 | RAG resolution + ticket update draft — **labeled "AI suggestion, verify with specialist"; engineer reviews & sends (human-in-loop)** | AI drafts resolution steps + work-note + requestor email; support engineer approves (flow ends at resolved; client closes) | incidents.csv + KB | M | CORE |
| 1.5 | Chatbot mode over incident history | Ask free questions against the corpus (alongside auto-draft mode) | incidents.csv | S | PLUS |
| 1.6 | Misroute detection on the backlog | Scan queue, flag wrongly-assigned tickets | incidents.csv | S | PLUS |

## S2 — Problem & Root Cause

| # | Capability | Demo beat | Data | Effort | Priority |
|---|-----------|-----------|------|--------|----------|
| 2.1 | Recurring-cluster detection | 6-mo data in → "these 17 incidents are one problem" (seeded pattern found) | incidents.csv | M | CORE |
| 2.2 | Problem-ticket initiation — **ServiceNow toggle** | Auto-drafted problem record; "REST API open → auto-created in ServiceNow, else guided manual" shown as a feature switch (a team member was confirming API availability) | derived | S | CORE |
| 2.3 | RCA narrative | AI RCA surfaces the pre-existing problem record + temporary workaround (seeded) | incidents.csv | M | CORE |
| 2.4 | Permanent-fix recommendation | Ranked fix options with impact estimate. **Talk track up front: fix quality matures after ~6 months of system learning** — sets expectations before the client asks | derived | S | CORE |
| 2.5 | Monthly proactive sweep | Ranked problem backlog across whole corpus | incidents.csv | M | PLUS |

## S3 — Enhancement Delivery (MapleSure mock app)

| # | Capability | Demo beat | Data | Effort | Priority |
|---|-----------|-----------|------|--------|----------|
| 3.0 | MapleSure policy/claims app (prereq, shared with S4) | Working small UI: view policies, submit claim | synthetic | L | CORE |
| 3.1 | AI-assisted requirement analysis | CR text ("add tier-upgrade option") → impact analysis on the codebase | CR doc | S | CORE |
| 3.2 | Code generation | AI writes the change; new button/flow appears that wasn't there before | mockapp repo | M | CORE |
| 3.3 | Test generation + run | AI-written tests execute green live | mockapp repo | M | CORE |
| 3.4 | Docs + release notes | Auto-updated docs and release note | mockapp repo | S | CORE |
| 3.5 | Effort estimate on intake | AI sizes the CR (~40h-class, P4-equivalent) before work starts | CR doc | S | PLUS |

## S4 — Knowledge & Onboarding (MapleSure with docs stripped)

| # | Capability | Demo beat | Data | Effort | Priority |
|---|-----------|-----------|------|--------|----------|
| 4.1 | Reverse-engineering / code understanding | Point AI at undocumented code → overview, module map, data flow | mockapp (stripped) | M | CORE |
| 4.2 | Documentation & runbook generation | Generated README/runbooks appear, SME-reviewable | same | S | CORE |
| 4.3 | Talk-to-code onboarding | Zero-knowledge person asks questions, finds a planted bug/problem | same | M | CORE |
| 4.4 | Architecture diagram generation | Auto-generated current-state diagram | same | S | PLUS |

## S5 — Proactive & Predictive Ops

| # | Capability | Demo beat | Data | Effort | Priority |
|---|-----------|-----------|------|--------|----------|
| 5.0 | Synthetic log generator (prereq) | T−1h incident window: warnings buried in noise (Splunk/Dynatrace-ish shape; swap real dump in later) | generated logs | M | CORE |
| 5.1 | Early-warning detection | AI scans the window → surfaces the buried warnings nobody noticed | logs | M | CORE |
| 5.2 | Predictive alert | "Memory climbing — likely failure, raising P2" alert fired to the team | logs | S | CORE |
| 5.3 | Self-healing simulation | Known repeated fix (service restart) auto-executed **with approval gate**; service comes back | scripted | M | CORE |
| 5.4 | Full autonomous self-healing | Roadmap: same chain, no human gate, guardrails | — | — | TALK |

## S6 — Governance & Reporting

| # | Capability | Demo beat | Data | Effort | Priority |
|---|-----------|-----------|------|--------|----------|
| 6.1 | SLA dashboard | Live dashboard over incidents.csv incl. seeded breaches (client sample as style reference) | incidents.csv | M | CORE |
| 6.2 | AI narrative reporting | AI writes the month's story: what changed, why, actions | incidents.csv | S | CORE |
| 6.3 | Breach forensics | Click a breach → causal chain ("misroute cost 40 min") | incidents.csv | S | PLUS |
| 6.4 | Improvement cadence | S2 sweep output feeds a tracked improvement backlog | derived | S | PLUS |

---

## Cross-cutting prerequisites

| # | Item | Serves | Effort |
|---|------|--------|--------|
| X.1 | incidents.csv generator, ~50 ServiceNow-shape fields, seeded patterns (SEEDS.md) | S1, S2, S6 | M |
| X.2 | KB / known-error articles pack (file-upload pattern, following a prior engagement's command-centre approach) | S1, S4 | S |
| X.3 | LLM wrapper (Anthropic/OpenAI switchable, response caching) | all | S |
| X.4 | Demo runner + reset scripts per scenario | all | S |

**CORE total: ~13–15 person-days** → feasible in 7 days with 3–4 builders working
parallel workstreams (A: data/backend S1-S2-S6 · B: mockapp S3-S4 · C: S5 + dashboard).

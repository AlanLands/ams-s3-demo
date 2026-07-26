# 7-Day Build Plan — demo ~Wed 22 Jul 2026 (90 min, live, all six scenarios)

Workstreams: **A** data/backend (S1, S2, S6) · **B** MapleSure app (S3, S4) ·
**C** predictive ops + dashboard (S5, S6 UI) · **P** presentation/demo flow.
Owners TBD — target 3–4 builders (Alan, Vimal, Karthik, +1).

## Day 0 — Tue 15 Jul (tonight/tomorrow)
- [x] Call with Vinay/CIBC command-center team — done 14 Jul late; verdict "doable in a
      week with 4 motivated people"; his condition: **real token budget, no limits**
- [ ] **Alan: draft plan to Seetha by tomorrow MORNING** (owed from the CIBC call —
      workstream split, one dedicated person per scenario, milestones; this file is the base)
- [ ] Repo created from this seed (CLAUDE.md, SCENARIOS.md, BUILD_PLAN.md at root)
- [ ] Personal API credits bought (OpenAI primary per leadership steer + Anthropic
      backup) — keep receipts; escalate token budget beyond $5–10 (Vinay burned ~$250)
- [ ] `common/llm.py` wrapper + `.env.example` working end-to-end (one prompt round-trip)
- [ ] Set up recurring evening sync w/ Vinay (TCS IDs, generic "AMS" subject) + WhatsApp group
- [ ] Collect from Vinay: data-quality prompt, triage prompts, S4 code-understanding prompts
- [ ] Karthik/Vimal: shortlist Kaggle ITSM/incident datasets (leadership prefers real
      datasets over pure LLM generation; enrich with LLM after)
- [ ] Seetha to ask client: ServiceNow REST API open? monitoring tools? dump includes resolutions?
- [ ] RFP document lands → check scope against SCENARIOS.md, adjust priorities

## Day 1 — Wed 16 Jul
- [ ] **A:** incidents.csv generator v1 (~50 fields, ServiceNow shape) + SEEDS.md
- [ ] **A:** verify seeded clusters are findable (quick clustering sanity check)
- [ ] **B:** MapleSure app skeleton (policies list, claim submit, SQLite)
- [ ] **C:** log-generator spec: T−1h window, buried warnings, noise profile

## Day 2 — Thu 17 Jul
- [ ] **A:** S1 pipeline: classify → route → similar-incident retrieval → resolution draft
- [ ] **B:** MapleSure complete + seeded with data; snapshot "docs-stripped" copy for S4
- [ ] **C:** log generator v1 + S5 early-warning detection
- [ ] Chase: sandbox status, client 6-mo dump, Splunk/Dynatrace dump, sample dashboard

## Day 3 — Fri 18 Jul
- [ ] **A:** S2 pipeline: cluster detection → problem ticket → RCA (finds seeded record) → fix rec
- [ ] **B:** S3 flow scripted: CR → AI analysis → codegen → tests green → docs/release note
- [ ] **C:** S5 predictive alert + self-heal simulation (approval gate + service restart)

## Day 4 — Sat 19 Jul
- [ ] **A/C:** S6 dashboard (SLA view over incidents.csv, seeded breaches) + AI narrative
- [ ] **B:** S4 flow: reverse-engineer stripped app → docs/runbooks → talk-to-code finds planted bug
- [ ] Real client data arrived? → swap into generators, re-verify seeds still demo cleanly

## Day 5 — Sun 20 Jul
- [ ] All six happy paths runnable via `demo/run_sX` + `demo/reset_sX`
- [ ] Cache/pin LLM outputs on must-land beats; live-call fallback tested
- [ ] Presenter notes per scenario (1 page each: pain → demo → roles → metric → roadmap)

## Day 6 — Mon 21 Jul
- [ ] **Full 90-minute dry run** with Seetha/BRM — timed, on the machine that will present
- [ ] Fix list from dry run only — no new features
- [ ] If TCS sandbox arrived: port + re-test there; else confirm laptop-demo logistics

## Day 7 — Tue 22 Jul (day before / demo day)
- [ ] Second timed run-through; reset everything; screenshots as backup for every beat
- [ ] Backup plan ready: if live fails, each scenario has a recorded/screenshot fallback

## Suggested 90-minute flow
Intro & approach (5) → S1 (12) → S2 (12) → S6 (10, closes the S1/S2 data story) →
S3 (15) → S4 (12) → S5 (14) → roadmap: from demo to production, environment &
governance asks (7) → Q&A buffer (3).
Rationale: S1→S2→S6 is one continuous data narrative; S3→S4 is one app narrative;
S5 is the finale with the self-heal moment.

## Standing risks
| Risk | Mitigation |
|---|---|
| Client dump arrives late/thin (no resolution notes) | Synthetic-first design; dump is a bonus, not a dependency |
| Sandbox never lands before demo | Demo from laptop is the plan of record until told otherwise |
| Live LLM flakiness in the room | Cached outputs on critical beats + screenshot fallback deck |
| Scope creep after RFP lands | SCENARIOS.md priorities: CORE unchanged, adjust PLUS only |
| Team availability (Bhaskaran laptop, Karthik time) | CORE is sized for 3 builders; PLUS items are the buffer |

# S3 Demo Test Guide

A hands-on script for running (and testing) all three S3 change-request
scenarios end to end. Use this to rehearse before presenting, or just to
verify the pipeline still works after a change.

This repo has **one pipeline, three CR scenarios** riding on it:

| # | Ticket | CR | Target app | Language | What the AI adds |
|---|--------|----|-----------|---------|--------------------|
| 1 | AMS-101 | CR-2026-041 | MapleSure mockapp (policy portal) | Python | A new top coverage tier (audience picks the name) |
| 2 | AMS-102 | CR-2026-042 | MapleSure mockapp (same app) | Python | A "Priority" field on the endorsement request form |
| 3 | AMS-103 | CR-2026-043 | ClaimsPortal (`sandbox/spring-demo`) | Java / Spring Boot | Per-policy deductible handling, across two microservices |

All three run through the same AMS console (FastAPI + React, `api/` +
`frontend/`) — the ticket you click just determines which registered
`target_id` the pipeline analyzes/codegens against (see
`s3_enhancement/targets.py` and `frontend/src/pages/S3.tsx`'s
`TICKET_TARGETS` map).

---

## 0. One-time setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in ANTHROPIC_API_KEY or OPENAI_API_KEY
cd frontend && npm install && cd ..
```

Sanity check the test suite before doing anything else:

```bash
python -m pytest tests/ -q   # expect all green (194 passed as of this writing)
```

`.env` defaults to `LLM_MODE=replay`, so every generative step below works
**offline with zero API key** — it plays back a committed recording instead
of calling a live provider. Set `LLM_MODE=live` (or per-call) only if you
specifically want to test the real API path.

### Known fix already applied

`demo/reset_s4_endorsement.sh` (CR-2026-042 reset) depends on a git tag,
`s3-endorsement-baseline`, marking the pre-CR-042 commit. That tag had never
been created, so the script would fail with `FAIL: git tag
's3-endorsement-baseline' does not exist`. Verified the working tree was
already at the correct pristine state (no Priority field, no
`tests/test_s3_endorsement_priority.py`) and created the tag locally
(`git tag s3-endorsement-baseline`) pointing at the current commit. It's a
local-only tag, not pushed — flagging it here since it wasn't previously
part of the documented setup.

### Login roster (all scenarios)

Every console login uses **name + passcode** (`1001 + position in the
roster`; scheme documented in `s1_triage/roster_auth.py`):

| Name | Passcode | Used as |
|---|---|---|
| Ravi Kumar | 1001 | Developer (CR-2026-041, CR-2026-043) |
| Elena Cruz | 1002 | Developer (CR-2026-042 assignee option) |
| Priya Nair | 1003 | Tester / QA hand-off |
| Tom Becker | 1004 | Tester / QA hand-off (alt) |
| Manager | 9000 | Manager rollup view |

---

## Scenario 1 — CR-2026-041: Coverage-Upgrade Option (AMS-101)

The flagship demo beat: audience picks the new tier's name live.

**Reset:**
```bash
demo/reset_s3.sh
```

**Run (3 terminals):**
```bash
# terminal 1 — API
uvicorn api.main:app --port 8000

# terminal 2 — console
cd frontend && npm run dev

# terminal 3 — the client's app (Streamlit view of MapleSure mockapp)
demo/run_s4_endorsement.sh    # despite the name, this just serves mockapp/app.py on :8501
```

**Steps:**
1. Open `http://localhost:8501` — the MapleSure portal. Show policies/claims.
   No coverage-upgrade option exists yet.
2. Open `http://localhost:5173`, log in as **Ravi Kumar / 1001**.
3. Open ticket **AMS-101**. Ask an audience member to name the new top tier
   (e.g. "Elite") — it's a free variable, only ever lands in string labels.
4. Run impact analysis — expect a ~40h-class effort estimate and a
   file-selection panel showing the scoped Python files (not the whole
   ~50-file legacy Java estate alongside it).
5. Generate the change, review the diff, Apply.
6. Generate tests + run — expect a green pytest run
   (`tests/test_s3_coverage_upgrade.py` gets created).
7. Back in the mockapp Streamlit view (:8501, refresh), open a policy →
   confirm the new tier is selectable and premium recalculates.
8. Generate release notes (labeled *"AI suggestion — verify with your
   specialist before applying."*).

**Reset between rehearsals:** `demo/reset_s3.sh` again.

---

## Scenario 2 — CR-2026-042: Endorsement Priority Field (AMS-102)

Same app, second independent CR — proves the pipeline isn't hardcoded to
one change.

**Reset:**
```bash
demo/reset_s4_endorsement.sh
```

**Run:** same 3 terminals as Scenario 1 (API :8000, console :5173, mockapp
Streamlit :8501 via `demo/run_s4_endorsement.sh`).

**Steps:**
1. On :8501, show the "Request a Policy Endorsement" form — 5 fields, no
   Priority.
2. Log in to the console (:5173) and open ticket **AMS-102**.
3. Run impact analysis — file-selection panel should scope to the
   endorsement form/model files only.
4. Generate the change (adds a "Priority" field: Standard/Urgent, defaults
   Standard), review diff, Apply.
5. Generate tests + run — expect
   `tests/test_s3_endorsement_priority.py` green.
6. On :8501 (refresh), submit an endorsement — Priority field now present,
   defaults to Standard, existing submit flow unaffected.

**Reset between rehearsals:** `demo/reset_s4_endorsement.sh`.

---

## Scenario 3 — CR-2026-043: Claims Deductible Handling (AMS-103, ClaimsPortal)

Second repo, second language — the pipeline speaks Java/Maven, not just
Python/pytest.

**Reset:**
```bash
demo/reset_s3.sh              # shared out/, ticket events, .cache/llm
demo/reset_s3_springdemo.sh   # ClaimsPortal back to pre-CR baseline
```

**Run (3 terminals):**
```bash
# terminal 1 — API
uvicorn api.main:app --port 8000

# terminal 2 — console
cd frontend && npm run dev

# terminal 3 — the two Spring Boot services (builds automatically)
demo/run_s3_springdemo.sh
```
Confirms Maven/Java are on PATH — verified `mvn` and `java` are available
in this environment.

**Steps:**
1. Policy Team console `http://localhost:8081` and Claims Team console
   `http://localhost:8082`. Submit an **$80 claim on MS-1004** → ACCEPTED
   (no deductible logic yet — this exact claim gets rejected later).
2. Log in to the console (:5173) as **Ravi Kumar / 1001**, open **AMS-103**.
   File-selection panel shows a Java-only pool (8 files, 0 Python).
3. Impact analysis — should name `Policy.java`, `PolicyClient`/`PolicyView`,
   and a new `ClaimRules` class.
4. Generate — diff spans **both** services (policy gains `deductible`,
   claims gains the consuming field, plus a new `ClaimRules.java`). Apply.
5. Draft the design doc (downloadable .html/.md), then hand off to a tester
   — pick **Priya Nair (1003)** or **Tom Becker (1004)**. Ticket moves to
   the QA column; the developer is now locked out of the test step.
6. Log out, log back in as the tester, open AMS-103 from the QA column, run
   "Generate tests + run" — expect `ClaimRulesTest.java` (JUnit 5), and the
   test output is **Maven**, not pytest. 5 tests green.
7. Restart the services to pick up the change:
   ```bash
   # Ctrl-C terminal 3, then:
   demo/run_s3_springdemo.sh   # rebuilds automatically
   ```
   Resubmit the same $80 claim on MS-1004 → **REJECTED_BELOW_DEDUCTIBLE**.
   Submit a $1,200 claim on MS-1001 → ACCEPTED with **payableAmount 700**.
8. Generate release notes (still as the tester), then mark the ticket
   **Done**.

**Reset between rehearsals:**
```bash
demo/reset_s3_springdemo.sh
demo/reset_s3.sh
```

---

## Cache warm-up (do right before presenting live)

```bash
demo/reset_s3.sh
demo/warm_s3_cache.sh
```

Warms the fixed-key narrative drafts so the first live click doesn't pay
full LLM latency. Note `.cache/llm` is shared across scenarios — a reset
wipes everyone's warmed cache, so warm it last, after your final reset.

## Automated pre-demo check

```bash
python -m pytest tests/ -q               # full suite, offline
python -m tools.verify_s3_live --skip-live   # architecture checks, no live calls
python -m tools.verify_s3_live --gate 10     # rehearsal gate: live codegen must pass 9/10+ before demo day
```

## Fallback ladder (all three scenarios)

1. Live call fails or generates invalid code → replay kicks in silently
   (same UI, nothing visibly different).
2. Still wrong → rerun the beat with `LLM_MODE=replay` set explicitly.
3. Total loss → fall back to narrating from screenshots (capture during
   rehearsal) or from this document.

## Full talk-track / presenter framing

For the "why," the risk framing, and word-for-word talk track (not just the
click-path), see:
- `demo/presenter_notes/s3_enhancement.md` — CR-2026-041 narrative
- `demo/presenter_notes/s3_springdemo_beat.md` — CR-2026-043 narrative

CR-2026-042 has no separate presenter-notes file yet — it's the newest
scenario; this guide's Scenario 2 section above is the only script for it
today.

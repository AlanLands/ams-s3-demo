# S3 Demo Test Guide

A hands-on script for running (and testing) all four S3 change-request
scenarios end to end. Use this to rehearse before presenting, or just to
verify the pipeline still works after a change.

This repo has **one pipeline, four CR scenarios** riding on it:

| # | Ticket | CR | Target repo | Language | What the AI adds |
|---|--------|----|-----------|---------|--------------------|
| 1 | AMS-101 | CR-2026-041 — Plan Tier Upgrade Option | PolicyCore (`repos/policycore`) | Python / Streamlit | A new top plan tier (audience picks the name) |
| 2 | AMS-102 | CR-2026-042 — Amendment Priority Field | PolicyCore (same repo) | Python / Streamlit | A "Priority" field on the contract-amendment request form |
| 3 | AMS-103 | CR-2026-043 — Benefit Claim Deductible Handling | ClaimsPortal (`repos/claimsportal`) | Python / FastAPI | Per-policy deductible handling, across two services |
| 4 | **AMS-1045** | CR-2026-045 — Prospect Member Eligibility Check For Online Enrolment | EnrolDirect (`repos/enroldirect`) | Python / FastAPI | Prospect classification at the online enrolment gate |

**AMS-1045 is not seeded by anything.** A `.md` dropped into the top-level
`crs/` opens a board ticket by itself, keyed deterministically off the CR id
(`CR-2026-045` → `AMS-1045`, in the AMS-1000+ band so it cannot collide with
the hand-seeded AMS-100..999 tickets), and it lands **unassigned** so the
manager routes it. See `s3_enhancement/cr_intake.py`. The scenario below can
still be driven straight from `target_id`, but you no longer have to.

All four run through the same AMS console (FastAPI + React, `apps/console/api/` +
`apps/console/web/`) — the ticket you click determines which registered
`target_id` the pipeline analyzes/codegens against (see
`s3_enhancement/targets.py`; for a CR-derived ticket the resolved target is
recorded on the ticket at intake, and `POST /s3/target/resolve` is the retry).

### Two folders

`repos/` holds the target repositories S3 **changes**; `apps/` holds the
console and the launch scripts — the tooling that **does the changing**.
Imports follow: `repos.policycore.*`, `apps.console.api.main:app`. A directory
dropped into `repos/` with a `.s3targets.json` manifest registers itself at
next start; the contract is in `repos/README.md`.

### The console shows artifacts in a pop-up

Release notes, deployment plan, design doc, scenario table, test checklists,
mutation diff and traceability matrix no longer render inline down the page.
Each stage shows the button, a one-line verdict, a summary chip, and a
**View…** button that opens the body in a modal. Every "then read the release
notes" step below means *press View, read, close* — **not** scroll.

---

## 0. One-time setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in ANTHROPIC_API_KEY or OPENAI_API_KEY
cd apps/console/web && npm install && cd ../../..
```

Sanity check the test suite before doing anything else:

```bash
python -m pytest tests/ -q   # expect all green (679 passed as of 2026-08-03)
```

`.env` defaults to `LLM_MODE=replay`, so every generative step below works
**offline with zero API key** — it plays back a committed recording instead
of calling a live provider. Set `LLM_MODE=live` (or per-call) only if you
specifically want to test the real API path.

---

## 0a. Am I at baseline? — the checks, and what they print

Run this before every rehearsal. It is the fastest way to know whether the
last run was reverted properly, and it needs nothing running. All of it is
read-only. **Every command below was run on 2026-08-03 and the output shown is
what it actually printed at baseline.**

```bash
# --- CR-2026-041, PolicyCore plan tier ---------------------------------
# tiers.py and the generated suite are CREATED by the CR: absent = baseline.
ls repos/policycore/core/tiers.py tests/test_s3_tier_upgrade.py
#   ls: repos/policycore/core/tiers.py: No such file or directory
#   ls: tests/test_s3_tier_upgrade.py: No such file or directory
grep -c "upgrade_tier\|PLAN_TIERS" repos/policycore/app.py
#   0        <- baseline. Non-zero means the CR is applied.

# --- CR-2026-042, amendment Priority field -----------------------------
grep -c priority repos/policycore/core/amendments.py
#   0        <- baseline. The CR adds `priority: str = "Standard"`.
ls tests/test_s3_amendment_priority.py
#   ls: tests/test_s3_amendment_priority.py: No such file or directory
# The "Request a Contract Amendment" form has 5 fields before the CR, 6 after:
awk '/st.form\("submit_amendment_form"/,/form_submit_button/' repos/policycore/app.py \
  | grep -cE 'st\.(selectbox|text_area|date_input|text_input)'
#   5        <- baseline (amendment type, requested change, effective date,
#                contact phone, contact email). 6 after the CR adds Priority.

# --- CR-2026-043, ClaimsPortal deductible ------------------------------
ls repos/claimsportal/claims_service/claim_rules.py tests/test_s3_claims_deductible.py
#   ls: repos/claimsportal/claims_service/claim_rules.py: No such file or directory
#   ls: tests/test_s3_claims_deductible.py: No such file or directory
grep -c deductible repos/claimsportal/policy_service/policy.py
#   0        <- baseline.

# --- CR-2026-045, EnrolDirect prospect access --------------------------
ls tests/test_s3_prospect_access.py
#   ls: tests/test_s3_prospect_access.py: No such file or directory
grep -c PROSPECT repos/enroldirect/eligibility.py
#   0        <- baseline. The gate imports MEMBER and GUEST only; a prospect
#                resolves to no preference at all and is refused.
```

> **Why these paths and not the old ones.** `core/coverage.py` and
> `core/endorsements.py` no longer exist. The 2026-08-03 GRS reskin renamed
> `core/coverage.py` → `core/tiers.py` (`COVERAGE_TIERS` → `PLAN_TIERS`,
> `upgrade_coverage` → `upgrade_tier`) and `core/endorsements.py` →
> `core/amendments.py` (`Endorsement` → `Amendment`, table `endorsements` →
> `amendments`, id prefix `END-` → `AMD-`). Any check still asserting on the
> old filenames passes vacuously and tells you nothing.

### The same checks against the running apps

Two of the four have a live before/after you can show, no console needed.

```bash
# ClaimsPortal (:8081) — no deductible field on any policy at baseline:
curl -s localhost:8081/api/policies | python3 -m json.tool | grep -c deductible
#   0        <- baseline. Policies carry policyNumber, holderName, product,
#                status, annualMaximum. MS-1001 and MS-1004 are the two the
#                demo uses.

# EnrolDirect (:8083) — a prospect is refused at the gate at baseline:
curl -s -X POST localhost:8083/api/eligibility/check \
  -H 'Content-Type: application/json' \
  -d '{"applicantId":"AP-4003","contractNumber":"MS-2001"}'
#   {"granted": false, ..., "category": "PROSPECT",
#    "requiredPreference": null, "authorisingPreference": null,
#    "reasons": ["Applicant category PROSPECT has no online enrolment
#                 preference and cannot be granted access."]}
#
# ...while a member on the same contract is granted:
curl -s -X POST localhost:8083/api/eligibility/check \
  -H 'Content-Type: application/json' \
  -d '{"applicantId":"AP-4001","contractNumber":"MS-2001"}'
#   {"granted": true, ..., "category": "MEMBER",
#    "authorisingPreference": "Online Enrolment - Member",
#    "reasons": ["Granted under 'Online Enrolment - Member'."]}
```

AP-4003 (Devon Achebe) is a PROSPECT on MS-2001; AP-4001 (Rowan Iqbal) is a
MEMBER on the same contract. `GET localhost:8083/api/applicants` lists all
twelve if you want a different pair.

### What each CR changes on screen

| CR | App | Before | After |
|---|---|---|---|
| CR-2026-041 | PolicyCore :8501/sl_policycore | A contract shows Plan Sponsor, Monthly Contribution, plan tier. No way to move a contract up a tier. | The audience-named top tier is selectable and the monthly contribution recalculates. `core/tiers.py` exists. |
| CR-2026-042 | PolicyCore :8501/sl_policycore | "Request a Contract Amendment" form: **5 fields** — Amendment type, Describe the requested change, Effective date, Contact phone, Contact email. | **6 fields** — a Priority selector (Standard/Urgent) defaulting to Standard. Existing submit flow unchanged. |
| CR-2026-043 | ClaimsPortal :8081 / :8082 | An **$80 claim on MS-1004 is ACCEPTED**. Policies carry no deductible. | Same $80 claim → **REJECTED_BELOW_DEDUCTIBLE**. A $1,200 claim on MS-1001 → ACCEPTED with **payableAmount 700**. |
| CR-2026-045 | EnrolDirect :8083 | Prospect AP-4003 → `granted: false`, "category PROSPECT has no online enrolment preference". | Prospect resolves through the module-level policy to the **Guest** preference; the decision names it, and the benefit catalogue filters on the same effective category. |

Note ClaimsPortal deliberately keeps `claim`, `deductible`, `annual maximum`,
`policyNumber`, `holderName`, `decide`, `payable` and
`REJECTED_BELOW_DEDUCTIBLE`. That is correct group-benefits
health/dental/disability vocabulary, and its API contract is frozen on purpose
— renaming any of it desyncs the committed recording. The GRS reskin was
PolicyCore only.

---

### Known fixes already applied *(historical — kept for context)*

> Written in 2026-07, before the `apps/` → `repos/` move and before the GRS
> reskin. The names below are the names things had **at the time**; today's
> equivalents are noted in brackets. Nothing here is an outstanding action.

1. `demo/reset_s3_endorsement.sh` (CR-2026-042 reset) depended on a git tag,
   `s3-endorsement-baseline`, marking the pre-CR-042 commit. That tag had
   never been created, so the script would fail with `FAIL: git tag
   's3-endorsement-baseline' does not exist`.

   *Superseded.* The script no longer uses that tag at all — it restores from
   `HEAD`, because the tag predates both this layout and the amendments table.
   The tag still exists and deliberately keeps its old spelling; renaming it
   would be a replay miss.
2. Bigger gap: the pre-CR-042 baseline itself was incomplete.
   `mockapp/core/endorsements.py` [today `repos/policycore/core/amendments.py`]
   was committed for CR-2026-042, but the scaffold it depends on — the
   `Endorsement` model [`Amendment`], the `endorsements` table [`amendments`],
   and the "Request a Policy Endorsement" form in `mockapp/app.py` [today
   "Request a Contract Amendment" in `repos/policycore/app.py`] — was never
   added. The module didn't even import
   (`ImportError: cannot import name 'insert_endorsement'`), and there was
   no form to show as the "before" state. The committed codegen replay
   recording also silently built the *entire* feature from scratch
   (with priority baked in from the start) rather than adding one field to
   an existing form, so even the replay path wouldn't have shown a real
   before/after.

   Fixed by adding the missing scaffold (matching exactly what the CR's own
   codegen prompt in `s3_enhancement/codegen.py::build_amendment_prompt`
   already assumed it would be adding a field *to*), re-recording both the
   codegen and testgen fixed-key replay caches
   (`s3_enhancement/cache/s3_codegen__endorsement_field_add.json` and
   `s3_testgen__endorsement_field_add.json`) against the corrected baseline,
   and moving `s3-endorsement-baseline` to tag the fixing commit
   (`git tag -f s3-endorsement-baseline`). Verified the full propose →
   apply → generate-tests → pytest cycle end to end via replay (no live
   API calls) — commit `7693e51`.

   Those two recording filenames still carry `endorsement_field_add` today,
   and must: `cache_namespace` *is* the recording's filename. It, the two
   `target_id`s (`mockapp-coverage-upgrade`, `mockapp-endorsement-field-add`)
   and the git tag are cache identity, not display strings, and were left
   spelled the old way on purpose through the GRS reskin.

   One known cosmetic issue remains: the live model's "complete file
   replacement" style drops blank lines and docstrings across the whole
   file, not just the lines it's actually changing, so the diff shown in
   the console is noisier than a hand-written patch would be (same
   characteristic likely applies to CR-2026-041's diffs too — not new to
   this fix). Functionally harmless; flagging so it isn't mistaken for a
   demo bug if a presenter reviews the diff closely on stage.

### Login roster (all scenarios)

Every console login uses **name + passcode** (`1001 + position in the
roster`; scheme documented in `common/roster.py`):

| Name | Passcode | Used as |
|---|---|---|
| Ravi Kumar | 1001 | Developer (CR-2026-041, CR-2026-043) |
| Elena Cruz | 1002 | Developer (CR-2026-042 assignee option) |
| Priya Nair | 1003 | Tester / QA hand-off |
| Tom Becker | 1004 | Tester / QA hand-off (alt) |
| Manager | 9000 | Manager rollup view. **The only login that can assign/reassign a ticket or open `/admin`** — both enforced server-side by `require_manager`, not hidden in the UI. |

---

## ⚠ Before you rely on any "Reset:" step below

`demo/reset_s3.sh` and `demo/reset_s3_endorsement.sh` **fail today.** They
restore PolicyCore with `git checkout HEAD -- repos/policycore/...`, but HEAD
still has those files under `apps/policycore/` — the `repos/` move is
uncommitted. Both die on:

```text
error: pathspec 'repos/policycore/app.py' did not match any file(s) known to git
```

and stop there, so nothing downstream in the script runs either: no reseed, no
`.cache/llm` wipe, no ticket-timeline clear. Verify read-only:

```bash
git cat-file -e HEAD:repos/policycore/app.py 2>/dev/null && echo "in HEAD" || echo "NOT in HEAD"
git cat-file -e HEAD:apps/policycore/app.py  2>/dev/null && echo "in HEAD" || echo "NOT in HEAD"
```

**Committing the `repos/` move fixes it** — the scripts themselves are correct.
`demo/reset_s3_claimsportal.sh` and `demo/reset_s3_enroldirect.sh` are
**unaffected**: they restore by `cp` from the in-repo `.baseline/` snapshots and
never touch git. The admin panel already reports the block as
`reset_blocked_reason` and greys out the PolicyCore reset.

**Do not work around it by checking out `apps/policycore/` instead.** That
content is *pre-reskin* — endorsement, coverage tier, premium, policyholder —
so it would undo the GRS rename along with the CR. Undo a PolicyCore CR with
the console's **Revert all**, which restores from the per-proposal backups
under `s3_enhancement/out/`, then clear the rest by hand
(`rm -f repos/policycore/core/tiers.py tests/test_s3_tier_upgrade.py
tests/test_s3_amendment_priority.py`, reseed, `rm -rf s3_enhancement/out/*
.cache/llm`). Either way, **use section 0a to confirm you are actually at
baseline** rather than trusting a reset that did not run.

---

## Scenario 1 — CR-2026-041: Plan Tier Upgrade Option (AMS-101)

The flagship demo beat: audience picks the new tier's name live.

**Reset:**
```bash
demo/reset_s3.sh     # see the warning above — broken until the repos/ move is committed
```

**Run (3 terminals):**
```bash
# terminal 1 — API
uvicorn apps.console.api.main:app --port 8000

# terminal 2 — console
cd apps/console/web && npm run dev

# terminal 3 — the client's app (Streamlit view of PolicyCore)
demo/run_mockapp.sh           # repos/policycore/app.py on :8501/sl_policycore
```

**Steps:**
1. Open `http://localhost:8501/sl_policycore` — the MapleSure PolicyCore
   portal. Show contracts and claims: Plan Sponsor, Monthly Contribution,
   plan tier. No tier-upgrade option exists yet. (The portal serves under a
   base path so all the apps can share a host; override it with
   `STREAMLIT_BASE_URL_PATH` in `.env`.)
2. Open `http://localhost:5173`, log in as **Ravi Kumar / 1001**.
3. Open ticket **AMS-101**. Ask an audience member to name the new top tier
   (e.g. "Elite") — it's a free variable, only ever lands in string labels.
4. Run impact analysis — expect a ~40h-class effort estimate and a
   file-selection panel scoping to a handful of Python files out of a
   **58-file candidate pool** (11 modern Python app files plus a 50-file
   legacy Java estate and its design docs). Open **View file selection** to
   show the subsystem screen: all seven subsystems — the six legacy platform
   ones plus `repos/policycore/enrolment` — screen out before a single Java
   file is opened.
5. Generate the change, review the diff, Apply.
6. Generate tests + run — expect a green pytest run
   (`tests/test_s3_tier_upgrade.py` gets created).
7. Back in the PolicyCore Streamlit view (:8501/sl_policycore, refresh), open a
   contract → confirm the new plan tier is selectable and the monthly
   contribution recalculates.
8. Draft release notes and press **View** to open them in the pop-up (labeled
   *"AI suggestion — verify with your specialist before applying."*). Three
   audience-specific notes — client, ops, user guide.

**Reset between rehearsals:** `demo/reset_s3.sh` again.

---

## Scenario 2 — CR-2026-042: Amendment Priority Field (AMS-102)

Same app, second independent CR — proves the pipeline isn't hardcoded to
one change.

**Reset:**
```bash
demo/reset_s3_endorsement.sh   # see the warning above — broken until the repos/ move is committed
```

> The script keeps its old filename on purpose (teammates invoke it by name);
> only its contents changed at the GRS reskin. It now restores
> `repos/policycore/core/amendments.py` and removes
> `tests/test_s3_amendment_priority.py`.

**Run:** same 3 terminals as Scenario 1 (API :8000, console :5173, PolicyCore
Streamlit :8501/sl_policycore via `demo/run_mockapp.sh`).

**Steps:**
1. On :8501/sl_policycore, open a contract and scroll to **"Request a Contract
   Amendment"** — 5 fields (Amendment type, Describe the requested change,
   Effective date, Contact phone, Contact email), no Priority.
2. Log in to the console (:5173) and open ticket **AMS-102**.
3. Run impact analysis — file-selection panel should scope to the
   amendment form/model files only (`core/amendments.py`, `core/models.py`,
   `core/db.py`, `app.py`).
4. Generate the change (adds a "Priority" field: Standard/Urgent, defaults
   Standard), review diff, Apply.
5. Generate tests + run — expect
   `tests/test_s3_amendment_priority.py` green. The seeded-bug check flips the
   default from `"Standard"` to `"Urgent"` and the suite must catch it.
6. On :8501/sl_policycore (refresh), submit an amendment — Priority field now
   present as a 6th field, defaults to Standard, existing submit flow
   unaffected.

**Reset between rehearsals:** `demo/reset_s3_endorsement.sh`.

---

## Scenario 3 — CR-2026-043: Benefit Claim Deductible Handling (AMS-103, ClaimsPortal)

Second repo, second language *until 2026-07-30* — ClaimsPortal was rebuilt
to Python/FastAPI so it runs on nothing but the venv. Same
pipeline, same pytest-based test/regression path as the other scenarios;
what this beat now proves is a second independent repo/target, not a second
language.

ClaimsPortal keeps `claim`, `deductible` and `annual maximum` — correct
group-benefits vocabulary, and the GRS reskin deliberately left it alone. Its
API contract (`policyNumber`, `decide`, `payable`,
`REJECTED_BELOW_DEDUCTIBLE`) is frozen: renaming any of it desyncs the
committed recording.

**Reset:**
```bash
demo/reset_s3_claimsportal.sh   # ClaimsPortal back to pre-CR baseline (works — cp from .baseline/)
demo/reset_s3.sh                # shared out/, ticket events, .cache/llm (broken — see warning above)
```

**Run (3 terminals):**
```bash
# terminal 1 — API
uvicorn apps.console.api.main:app --port 8000

# terminal 2 — console
cd apps/console/web && npm run dev

# terminal 3 — the two Python/FastAPI services
demo/run_s3_claimsportal.sh
```

**Steps:**
1. Contracts Team console `http://localhost:8081` and Claims Team console
   `http://localhost:8082`. Submit an **$80 claim on MS-1004** → ACCEPTED
   (no deductible logic yet — this exact claim gets rejected later).
2. Log in to the console (:5173) as **Ravi Kumar / 1001**, open **AMS-103**.
   File-selection panel shows the ClaimsPortal-scoped pool (5 files, all
   Python).
3. Impact analysis — should name `policy.py`, `policy_client.py`'s
   `PolicyView`, and a new `claim_rules` module.
4. Generate — diff spans **both** services (policy gains `deductible`,
   claims gains the consuming field, plus a new `claim_rules.py`). Apply.
5. Draft the design doc — press **View design doc** to open it in the pop-up
   (downloadable .html/.md/.pdf), then hand off to a tester
   — pick **Priya Nair (1003)** or **Tom Becker (1004)**. Ticket moves to
   the QA column; the developer is now locked out of the test step.
6. Log out, log back in as the tester, open AMS-103 from the QA column, run
   "Generate tests + run" — expect `tests/test_s3_claims_deductible.py`,
   same pytest runner as the other scenarios. All green.
7. Restart the services to pick up the change:
   ```bash
   # Ctrl-C terminal 3, then:
   demo/run_s3_claimsportal.sh
   ```
   Resubmit the same $80 claim on MS-1004 → **REJECTED_BELOW_DEDUCTIBLE**.
   Submit a $1,200 claim on MS-1001 → ACCEPTED with **payableAmount 700**.
8. Draft release notes (still as the tester), open them in the pop-up, then
   mark the ticket **Done**.

**Reset between rehearsals:**
```bash
demo/reset_s3_claimsportal.sh   # works
demo/reset_s3.sh                # broken until the repos/ move is committed
```

---

## Scenario 4 — CR-2026-045: Prospect Member Eligibility Check (AMS-1045, EnrolDirect)

Third repo, and the one whose **baseline is a removal** — which is what makes
it different. The checked-in source is the state *after* the impact analysis
and *before* the gate acts on it: `eligibility.preference_for_category` returns
`None` for a prospect, so they are refused. The CR settles the classification.

Two other things are worth pointing at during this beat:

- **Nobody seeded this ticket.** AMS-1045 opened itself from
  `crs/CR-2026-045.md` and landed unassigned. Show it on the board before you
  start, then assign it as **Manager / 9000**.
- **`impact.py` is in `core_files` but deliberately NOT in
  `codegen_allowlist`.** The model must *read* the analysis to understand the
  change and must not edit it. This target has its own file-set validator
  (`_validate_enroldirect_file_set`) that fails loudly if a read-only file
  comes back modified.

**Reset:**
```bash
demo/reset_s3_enroldirect.sh   # works — cp from repos/enroldirect/.baseline/
```

**Run (3 terminals):**
```bash
# terminal 1 — API
uvicorn apps.console.api.main:app --port 8000

# terminal 2 — console
cd apps/console/web && npm run dev

# terminal 3 — EnrolDirect
apps/run-enroldirect.sh        # :8083
```

**Steps:**
1. Open `http://localhost:8083`. Check a **member** (AP-4001, Rowan Iqbal, on
   MS-2001) → granted under "Online Enrolment - Member". Check a **prospect**
   (AP-4003, Devon Achebe, same contract) → refused, reason: *"Applicant
   category PROSPECT has no online enrolment preference and cannot be granted
   access."* That refusal is nobody's decision — it is the omission the CR
   exists to close.
2. Log in to the console (:5173) as **Manager / 9000**, show **AMS-1045**
   unassigned on the board, assign it to an engineer. Press **Reassign** to
   show the decision is reversible.
3. Log in as that engineer and open AMS-1045. File-selection panel scopes to
   the EnrolDirect pool (**8 candidate files**).
4. Impact analysis — the CR's own analysis is already in the repo
   (`impact.py`, `/api/analysis/*`), and it recommended Guest as the narrower
   grant. The pipeline reads it; it does not redo it.
5. Generate — the prospect policy lands as a single module-level value in
   `applicants.py`, `preference_for_category` resolves a prospect through it,
   and a new `effective_category` carries it past the gate. Apply.
6. Generate tests + run — expect `tests/test_s3_prospect_access.py` green,
   plus `tests/test_regression_enroldirect.py` still green (the independent
   check that this CR broke nothing).
7. Restart EnrolDirect and re-check AP-4003 → now granted, with the decision
   naming the Guest preference that admitted them and the policy that resolved
   it. The benefit catalogue filters on the same effective category, so the
   catalogue and the gate cannot disagree about the same person.

**Reset between rehearsals:** `demo/reset_s3_enroldirect.sh`.

---

## Cache warm-up (do right before presenting live)

```bash
demo/reset_s3.sh
demo/warm_s3_cache.sh
```

Warms the fixed-key narrative drafts so the first live click doesn't pay
full LLM latency. Note `.cache/llm` is shared across scenarios — a reset
wipes everyone's warmed cache, so warm it last, after your final reset.

> While `reset_s3.sh` is broken it never reaches its `rm -rf .cache/llm`, so
> the cache survives and this ordering does not bite. Do not rely on that —
> it changes the moment the `repos/` move is committed.

## Automated pre-demo check

```bash
python -m pytest tests/ -q               # full suite, offline (679 tests)
python -m tools.verify_s3_live --skip-live   # architecture checks, no live calls
python -m tools.verify_s3_live --gate 10     # rehearsal gate: live codegen must pass 9/10+ before demo day
```

The `--skip-live` gate includes a "`reset_s3.sh` restores baseline in <10s"
check, which fails today for the pathspec reason above. That is the gate
working.

## Fallback ladder (all scenarios)

1. Live call fails or generates invalid code → replay kicks in silently
   (same UI, nothing visibly different).
2. Still wrong → rerun the beat with `LLM_MODE=replay` set explicitly.
3. Total loss → fall back to narrating from screenshots (capture during
   rehearsal) or from this document.

## Full talk-track / presenter framing

For the "why," the risk framing, and word-for-word talk track (not just the
click-path), see:
- `demo/presenter_notes/s3_enhancement.md` — CR-2026-041 narrative
- `demo/presenter_notes/s3_claimsportal_beat.md` — CR-2026-043 narrative

CR-2026-042 and CR-2026-045 have no separate presenter-notes file; this
guide's Scenario 2 and Scenario 4 sections are the only scripts for them
today.

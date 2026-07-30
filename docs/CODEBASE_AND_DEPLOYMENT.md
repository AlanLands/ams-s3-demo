# S3 (Enhancement) — Codebase & Deployment Overview

For the team building the other scenarios (S1, S2, S4, S5, S6) in a separate
effort. Covers what's in this repo, how it's laid out, and the current state
of its deployment story — including what changed today to close a real
dev-mode/production-mode gap.

**This repo is standalone.** It was split out from the original six-scenario
`sixFold` AMS demo repo on 2026-07-23 and trimmed to just what S3 needs. The
other five scenarios are being built elsewhere; nothing here assumes or
depends on that work, and this doc doesn't speak for how those repos are
structured — ask their owners for that.

---

## 1. What S3 does, in one paragraph

A small change-request pipeline: a developer opens a ticket in a console, an
AI drafts a code change scoped to just the relevant files, a human reviews it
file-by-file before anything is applied, a separate AI-generated test suite
plus a human-authored regression suite prove it, and the loop ends with
release notes and a release record. It's demonstrated against three real CRs
(coverage-tier upgrade, an endorsement form field, claims deductible
handling) across two target applications.

---

## 2. Repository layout

| Path | What it is |
|---|---|
| `apps/` | The 4 running applications — see `apps/README.md` for the full map. Everything else below is tooling, not an app. |
| `s3_enhancement/` | The AI pipeline itself: relevance scoring, codegen/testgen, test running, design docs, release notes, the deployment plan. One module per beat (`analyze.py`, `codegen.py`, `testgen.py`, `release.py`, etc.) |
| `common/` | Shared clients used across the pipeline: `llm.py` (provider-agnostic LLM client with the replay-cache mechanism), `jira_client.py` / `ticket_events.py` (the mocked Jira board), `gitlab_client.py`, `servicenow_client.py`, `roster.py` (the shared login roster), `vectorstore.py` (ChromaDB) |
| `demo/` | Presenter-facing run/reset scripts and rehearsal docs |
| `deploy/aws/` | The production deployment path — EC2 + systemd + nginx + Bedrock IAM (Section 5 below) |
| `tests/` | Both the pipeline's own tests and the target apps' checked-in regression suites |
| `docs/` | Hand-off documents — this one, `APPLICATIONS_AND_ENHANCEMENTS.md` (business/functional view), `DEMO_STEPS.md` / `DEMO_TEST_GUIDE.md` (rehearsal scripts) |

### The four applications (also in `apps/README.md`)

| # | Application | Port | Tech |
|---|---|---|---|
| 1 | AMS Console | 8000 (API) + 5173 (UI) | FastAPI + React |
| 2 | PolicyCore | 8501 | Python / Streamlit / SQLite |
| 3 | policy-service (ClaimsPortal) | 8081 | Python / FastAPI |
| 4 | claims-service (ClaimsPortal) | 8082 | Python / FastAPI |

All Python end to end — no JVM, no Maven, no Docker anywhere in this repo.
ClaimsPortal (apps 3+4) was Java/Spring Boot until 2026-07-30; it's been
rewritten in Python for exactly the reason this doc exists — the target
sandbox this eventually deploys to can't run a JVM.

---

## 3. Local rehearsal vs. production — two different things

**`apps/run-*.sh` (local rehearsal only):** `streamlit run`, `uvicorn ... --port`
with a single process, `npm run dev` (Vite's dev server). This is what a
presenter runs on their own laptop to rehearse — it is **not** how this gets
deployed. There's no process supervision, no reverse proxy, no built frontend
bundle, and the Vite dev server in particular is explicitly a development
tool, not something to expose publicly.

**`deploy/aws/` (production path):** systemd units (one per app, all bound to
`127.0.0.1`, restart-on-failure, no `--reload`), nginx as the single public
entry point (port 80 only), the React app pre-built to static files, and LLM
calls routed through AWS Bedrock with IAM-based auth instead of an API key in
`.env`. This is the path to use for any real (non-laptop) deployment.

If your scenario needs to go from "runs on my machine" to "runs on a shared
instance," `deploy/aws/` is a working, tested pattern you're welcome to copy
from — systemd unit shape, the nginx path-prefix routing trick (Section 5),
and the AWS access request template in `deploy/aws/README.md` Part 0 all
generalize beyond this specific app.

---

## 4. What changed today — closing the dev-mode/production-mode gap

`deploy/aws/` already existed (systemd + nginx + a documented AWS setup
process) but had drifted out of sync with this repo twice: once when the four
apps moved under `apps/` (2026-07-28), and once when ClaimsPortal was
rewritten from Java to Python (2026-07-30). Fixed today, each verified rather
than assumed:

- **`bootstrap.sh` built the frontend from a path that no longer
  exists** (`frontend/`, pre-restructure) — fixed to `apps/console/web/`.
- **PolicyCore's Streamlit unit had a real, confirmed bug**: it set
  `--server.baseUrlPath mockapp`, but nginx proxies it at
  `/apps/policycore/` — a mismatch the unit file's own comment says would
  cause "the page loads blank behind the proxy." Fixed to match.
- **ClaimsPortal had no systemd units at all.** They were lost/never
  committed per this repo's own `CLAUDE.md`, and predated the Java→Python
  rewrite regardless. Added `ams-s3-policy-service.service` and
  `ams-s3-claims-service.service`, matching the existing units' pattern
  (localhost-bound, single worker, no `--reload`, restart-on-failure).
- **Added nginx routing for both new services** at
  `/apps/claimsportal/policy/` and `/apps/claimsportal/claims/`. Since
  path-prefix proxying only works if the app's own static JS uses relative
  fetch paths, also changed both services' static consoles from
  `fetch("/api/...")` to `fetch("api/...")` — a one-character-per-call fix,
  verified both via `curl` and in a real browser against a local nginx
  instance before and after the path prefix.
- **Renamed the PolicyCore unit** from `ams-s3-mockapp` to
  `ams-s3-policycore` for consistency with the rest of this repo (the
  "mockapp" name predates the `apps/` restructure).

**Verification, not assertion:** installed nginx locally (`brew install
nginx`), ran the actual `deploy/aws/nginx.conf` (config-tested with `nginx
-t`, then live on a local port) against the real running services, confirmed
both static consoles and their APIs work correctly through the path prefix —
including a real browser session, not just `curl`. Full pytest suite (529
tests) green throughout.

**Not yet done / out of scope of today's fix:** none of this has been run
against an actual EC2 instance — the fixes are verified locally (config
syntax, live proxy behavior, matching file paths) but a real AWS deploy would
still be the first true end-to-end test. `deploy/aws/README.md`'s Part 0–E
walkthrough is otherwise unchanged and should still be followed in order.

---

## 5. If you're deploying something similar

Two patterns from `deploy/aws/` worth reusing regardless of tech stack:

1. **One public entry point, everything else localhost-only.** Every app
   process binds `127.0.0.1`; nginx is the only thing with a public port, and
   the security group only opens 80 (and 22 for admin) to a specific IP.
2. **Path-prefix proxying works if — and only if — the backend's own
   asset/API references are relative, not root-absolute.** A single-page app
   or static console written with `fetch("/api/...")` will always resolve
   against the domain root and can never be proxied under a path prefix
   without breaking. Writing it as `fetch("api/...")` (relative) instead
   costs nothing locally and makes it work under any prefix nginx puts it
   behind later. Worth deciding early — retrofitting it later means auditing
   every fetch/asset call, same as had to happen here today.

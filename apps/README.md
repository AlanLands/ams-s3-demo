# apps/ — the console, and the scripts that start everything

Everything in here is **tooling**: the AMS console the presenter drives, plus
one launch script per running process. Nothing in here is a target of the S3
pipeline any more.

The split is the point, and it is load-bearing:

| | Holds | S3's relationship to it |
|---|---|---|
| `repos/` | The target repositories — PolicyCore, ClaimsPortal, EnrolDirect | Something S3 **changes** |
| `apps/` | The console, and the launch scripts | Something that **does the changing** |

See [`../repos/README.md`](../repos/README.md) for the target repositories and
how to onboard a new one. The rest of the tooling sits at the root:
`s3_enhancement/` is the AI pipeline, `common/` the shared clients, `demo/` the
presenter scripts.

Each process starts with one script and owns one port. Start them in the order
below; only the middle two depend on each other.

| # | Process | Start with | Port | What it is |
|---|---|---|---|---|
| 1 | **Console** | `apps/run-console.sh` | 8000 + **5173** | The AMS console the presenter drives. FastAPI backend + React UI, both from this folder (`console/`). Open **:5173**. |
| 2 | **PolicyCore** | `apps/run-policycore.sh` | 8501 | The client's plan-administration portal (`repos/policycore/`, Python/Streamlit/SQLite). The window the audience watches change. Open **:8501/sl_policycore** — see below. |
| 3 | **Policy-Service** | `apps/run-policy-service.sh` | 8081 | ClaimsPortal's contracts side (`repos/claimsportal/policy_service/`). Start before Claims-Service. |
| 4 | **Claims-Service** | `apps/run-claims-service.sh` | 8082 | ClaimsPortal's claims side (`repos/claimsportal/claims_service/`). Target of CR-2026-043. |
| 5 | **EnrolDirect** | `apps/run-enroldirect.sh` | 8083 | The online enrolment channel and its access-preference analysis (`repos/enroldirect/`). Target of CR-2026-045. |

Only the console lives here as source. Scripts 2–5 launch code out of `repos/`
— they are here because starting the applications is a tooling job, not because the
apps they start are.

You do **not** need all five for every beat. The PolicyCore CRs (CR-2026-041,
CR-2026-042) need 1 and 2. CR-2026-043 needs 1, 3 and 4. CR-2026-045 needs 1
and 5, and EnrolDirect runs on nothing but the venv.

A manager can also see and control 2–5 from the console's **admin panel**
(`/admin`, see below) without a terminal. The console is deliberately not on
that list — it cannot restart the process serving the request.

## Ports and paths come from `.env`

None of the launch scripts hard-codes a host, port, or path — each sources the
repo-root `.env` (see `.env.example`) and falls back to the value it used
before, so a plain `localhost` run needs nothing set:

| Variable | Used by | Default |
|---|---|---|
| `STREAMLIT_BASE_URL_PATH` | PolicyCore (also `demo/run_mockapp.sh`) | `sl_policycore` |
| `POLICY_SERVICE_PORT` | Policy-Service | `8081` |
| `CLAIMS_SERVICE_PORT` | Claims-Service | `8082` |
| `POLICY_SERVICE_URL` | Claims-Service → Policy-Service lookups | `http://localhost:8081` |
| `ENROLDIRECT_PORT` | EnrolDirect | `8083` |

**PolicyCore serves under a base path**, at
`http://localhost:8501/sl_policycore` rather than the bare port root, so all
the apps can share a host behind a reverse proxy. `apps/run-policycore.sh` and
`demo/run_mockapp.sh` start the same portal and must pass the same path.

The console's React UI can't read that file — Vite bakes its config in at
build time. Its equivalents (`VITE_API_BASE_URL`, `VITE_MOCKAPP_URL`,
`VITE_CLAIMS_SERVICE_URL`) live in `console/web/.env.example`; copy it to
`.env.local` and re-run `npm run build` after any change.

## The admin panel — `/admin`, manager only

`console/api/routers/admin.py` over `s3_enhancement/admin_ops.py`, UI at
`console/web/src/pages/Admin.tsx`. Four jobs, all of which otherwise need a
terminal: reset environment state, clear logs, see and control the target apps above,
and onboard a repo by writing its `.s3targets.json`.

Every route depends on `require_manager`, so it is invisible to an engineer or
a tester. Its honest limits are part of the design, not gaps:

- **Source-restoring resets refuse while the tree is dirty** (409). Each scope
  previews exactly what it would restore, what it would delete, and which of
  those paths are currently modified, before it will run.
- **There is no "reset everything" scope.** Seven explicit scopes —
  `policycore`, `claimsportal`, `enroldirect`, `tickets`, `logs`, `proposals`,
  `caches` — and you name one.
- **No service id for the console.** Naming it is a 400, not an attempt.
- **Service status is a plain TCP connect** to the port — no `ps`, no `lsof` —
  so it works on a locked-down host.
- **A written manifest needs a console restart** before the target registers.

The `policycore` and `enroldirect`/`claimsportal` reset scopes shell out to the
`demo/reset_s3*.sh` scripts, so what holds for those scripts holds for the
panel.

### The PolicyCore resets depend on HEAD

`demo/reset_s3.sh` and `demo/reset_s3_endorsement.sh` restore source with
`git checkout HEAD -- repos/…`, so **HEAD must already carry the paths they
name**. Move a target and the resets stop working until the move is committed —
`git checkout` fails on paths HEAD has never seen. That is the durable rule;
commit the move and they run again. The admin panel checks the condition up
front (`admin_ops.head_missing_paths`) and reports a named
`reset_blocked_reason` rather than surfacing a raw git error out of a button —
keep that check, because the situation recurs on every target move.

The ClaimsPortal and EnrolDirect resets restore by copying from their
committed `.baseline/` snapshots, so they never depend on HEAD at all.

## How these map to the walkthrough

The console treats each application as a **ServiceNow application** with an
owning team, so a ticket carrying a Configuration Item routes to the right
place before any AI step runs (`s3_enhancement/applications.py`):

| Repo | CI / application name | Owning team | Automatable |
|---|---|---|---|
| `repos/policycore/` | PolicyCore | App Support — PolicyCore | yes (CR-2026-041, CR-2026-042) |
| `repos/claimsportal/` | ClaimsPortal | App Support — ClaimsPortal | yes (CR-2026-043) |
| `repos/enroldirect/` | EnrolDirect | App Support — PolicyCore | yes (CR-2026-045) |
| — | BillingGateway | App Support — BillingGateway | no — routes only, no repo here |
| — | DocumentHub | App Support — DocumentHub | no — routes only, no repo here |

The last two exist on purpose: they show a ticket reaching the correct team
for an application this console has no code for, instead of the console
pretending it can generate a fix.

EnrolDirect was a third kind of row until CR-2026-045: the console had its code
but no registered target, so it carried an empty `repo_path` and reported
`automation_available=False`. Both halves exist now. The property still answers
"can we act on this ticket" rather than "is the source on disk", and
`RouteDecision.automation_available` still requires a repo *and* a registered
target — remove either and this row goes back to routing-only rather than to a
beat that fails when a presenter clicks it.

## Layout notes that aren't obvious

- **`console/web/`** was `frontend/`; **`console/api/`** was `api/`. The
  console runs as `uvicorn apps.console.api.main:app`.
- The target repos moved out of here on 2026-08-03: `apps/policycore` →
  `repos/policycore`, `apps/claimsportal` → `repos/claimsportal`,
  `apps/enroldirect` → `repos/enroldirect`. Their Python packages moved with
  them, so imports are `repos.policycore.core.db` and so on.
- That move was **not** a `mv`. `s3_enhancement/relevance.py` folds each
  file's path into the text it scores, and the committed replay caches in
  `s3_enhancement/cache/` contain these exact paths — both as file keys and
  inside the generated code's own `import` statements. It took a rewrite
  across code, docs and recordings together (128 files), and no live re-record
  was needed. Two traps that pass a `grep` and break at run time: paths built
  as split literals (`REPO_ROOT / "apps" / "policycore"`) are invisible to an
  `apps/policycore` search, and unusual extensions (`.env.example`,
  `deploy/aws/*.service`) fall out of an extension allowlist. Both bit on the
  first pass.
- One directory *inside* a target root was renamed earlier the same way:
  `policycore/systems/legacy_java_platform/` → `legacy_platform/` on
  2026-07-31, dropping a stack name this project no longer uses. Those 50 decoy
  files are 50 of PolicyCore's 58-file candidate pool, so it was a real risk,
  not a cosmetic edit. It was safe only because it was verified rather than
  assumed: the candidate pool and the selected file set came back
  byte-identical for both PolicyCore CRs, and codegen/testgen still replayed
  from cache. `.cache/vectordb` had to be deleted first — the embedding index
  is keyed by path and `demo/reset_s3.sh` clears only `.cache/llm`, so a stale
  index would have hidden any drift. Verify the same way, or don't do it.

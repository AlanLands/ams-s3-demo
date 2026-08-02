# apps/ — the five applications the demo runs

Everything in here is a *running application*. Nothing in here is S3 tooling —
the AI pipeline itself lives in `s3_enhancement/`, shared clients in `common/`,
and the presenter scripts in `demo/`.

Each app starts with one script and owns one port. Start them in the order
below; only the last two depend on each other.

| # | Application | Start with | Port | What it is |
|---|---|---|---|---|
| 1 | **Console** | `apps/run-console.sh` | 8000 + **5173** | The AMS console the presenter drives. FastAPI backend + React UI. Open **:5173**. |
| 2 | **PolicyCore** | `apps/run-policycore.sh` | 8501 | The client's policy-administration portal (Python/Streamlit/SQLite). The window the audience watches change. Open **:8501/sl_policycore** — see below. |
| 3 | **Policy-Service** | `apps/run-policy-service.sh` | 8081 | ClaimsPortal's policy side (Python/FastAPI). Start before Claims-Service. |
| 4 | **Claims-Service** | `apps/run-claims-service.sh` | 8082 | ClaimsPortal's claims side (Python/FastAPI). Target of CR-2026-043. |
| 5 | **EnrolDirect** | `apps/run-enroldirect.sh` | 8083 | The online enrolment channel and its access-preference analysis (Python/FastAPI). Target of CR-2026-045. |

You do **not** need all five for every beat. The mockapp CRs (CR-2026-041,
CR-2026-042) need apps 1 and 2. CR-2026-043 needs apps 1, 3 and 4. CR-2026-045
needs apps 1 and 5, and EnrolDirect runs on nothing but the venv.

## Ports and paths come from `.env`

None of the four scripts hard-codes a host, port, or path any more — each
sources the repo-root `.env` (see `.env.example`) and falls back to the value
it used before, so a plain `localhost` run needs nothing set:

| Variable | Used by | Default |
|---|---|---|
| `STREAMLIT_BASE_URL_PATH` | PolicyCore (also `demo/run_mockapp.sh`) | `sl_policycore` |
| `POLICY_SERVICE_PORT` | Policy-Service | `8081` |
| `CLAIMS_SERVICE_PORT` | Claims-Service | `8082` |
| `POLICY_SERVICE_URL` | Claims-Service → Policy-Service lookups | `http://localhost:8081` |
| `ENROLDIRECT_PORT` | EnrolDirect | `8083` |

The one behavior change: **PolicyCore now serves under a base path**, at
`http://localhost:8501/sl_policycore` rather than the bare port root, so all
four apps can share a host behind a reverse proxy. `apps/run-policycore.sh`
and `demo/run_mockapp.sh` start the same portal and must pass the same path.

The console's React UI can't read that file — Vite bakes its config in at
build time. Its equivalents (`VITE_API_BASE_URL`, `VITE_MOCKAPP_URL`,
`VITE_CLAIMS_SERVICE_URL`) live in `apps/console/web/.env.example`; copy it to
`.env.local` and re-run `npm run build` after any change.

## How these map to the demo's story

The console treats each app as a **ServiceNow application** with an owning
team, so a ticket carrying a Configuration Item routes to the right place
before any AI step runs (`s3_enhancement/applications.py`):

| Folder here | CI / application name | Owning team | Automatable |
|---|---|---|---|
| `policycore/` | PolicyCore | App Support — PolicyCore | yes (CR-2026-041, CR-2026-042) |
| `claimsportal/` | ClaimsPortal | App Support — ClaimsPortal | yes (CR-2026-043) |
| — | BillingGateway | App Support — BillingGateway | no — routes only, no repo here |
| — | DocumentHub | App Support — DocumentHub | no — routes only, no repo here |

The last two exist on purpose: they show a ticket reaching the correct team
for an application this console has no code for, instead of the console
pretending it can generate a fix.

| `enroldirect/` | EnrolDirect | App Support — PolicyCore | **yes** — `enroldirect-prospect-access` (CR-2026-045) |

EnrolDirect was the third kind of row until CR-2026-045: the console had its
code but no registered target, so it carried an empty `repo_path` and reported
`automation_available=False`. Both halves exist now. The property still
answers "can we act on this ticket" rather than "is the source on disk", and
`RouteDecision.automation_available` still requires a repo *and* a registered
target — remove either and this row goes back to routing-only rather than to a
beat that fails when a presenter clicks it.

## Layout notes that aren't obvious

- **`claimsportal/` is one folder holding two services** because S3 treats it
  as a single change target — CR-2026-043 edits files in both. Splitting the
  directories would split the target. They still start as two processes, via
  the two scripts above.
- **`claimsportal/.baseline/`** is the pre-CR snapshot of the Python sources,
  restored by `demo/reset_s3_claimsportal.sh`. It is not run.
- **`claimsportal/policy_service/`, `claimsportal/claims_service/`** are
  Python/FastAPI services run under uvicorn, so the demo needs no extra
  runtime beyond the venv. Their directories use underscores because they are
  real Python packages (`apps.claimsportal.policy_service`).
- **`console/web/`** was `frontend/`; **`console/api/`** was `api/`;
  **`policycore/`** was `mockapp/`. The Python package moved with the folder,
  so imports are `apps.policycore.core.db`, and the console runs as
  `uvicorn apps.console.api.main:app`.
- Do not rename these directories. `s3_enhancement/relevance.py` folds each
  file's path into the text it scores, and the committed replay caches in
  `s3_enhancement/cache/` contain these exact paths — a rename desyncs them and
  the codegen beat fails with "codegen returned unexpected file set". Moving a
  target is a path-rewrite across code *and* caches, not a `mv`.
- One directory *inside* a target root has been renamed since:
  `policycore/systems/legacy_java_platform/` → `legacy_platform/` on
  2026-07-31, dropping a stack name the demo no longer uses. Those 50 decoy
  files are 50 of PolicyCore's 56-file candidate pool, so this was a real
  risk, not a cosmetic edit. It was safe only because it was verified rather
  than assumed: the candidate pool and the selected file set came back
  byte-identical for both PolicyCore CRs, and codegen/testgen still replayed
  from cache for all three targets. `.cache/vectordb` had to be deleted
  first — the embedding index is keyed by path and `demo/reset_s3.sh` clears
  only `.cache/llm`, so a stale index would have hidden any drift. Verify the
  same way, or don't do it.

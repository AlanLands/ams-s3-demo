# apps/ — the four applications the demo runs

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

You do **not** need all four for every beat. The mockapp CRs (CR-2026-041,
CR-2026-042) need apps 1 and 2. CR-2026-043 needs apps 1, 3 and 4.

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

## Layout notes that aren't obvious

- **`claimsportal/` is one folder holding two services** because S3 treats it
  as a single change target — CR-2026-043 edits files in both. Splitting the
  directories would split the target. They still start as two processes, via
  the two scripts above.
- **`claimsportal/.baseline/`** is the pre-CR snapshot of the Python sources,
  restored by `demo/reset_s3_springdemo.sh`. It is not run.
- **`claimsportal/policy_service/`, `claimsportal/claims_service/`** were
  `policy-service/`, `claims-service/` (Java/Spring Boot) — rebuilt in Python
  (FastAPI/uvicorn) so the demo runs without a JVM. Renamed hyphen→underscore
  because they're now real Python packages (`apps.claimsportal.policy_service`).
  This is the one sanctioned exception to "do not rename these directories"
  below: the rewrite already required a fresh replay-cache recording, so the
  rename rode along with it instead of desyncing a working cache.
- **`console/web/`** was `frontend/`; **`console/api/`** was `api/`;
  **`policycore/`** was `mockapp/`. The Python package moved with the folder,
  so imports are `apps.policycore.core.db`, and the console runs as
  `uvicorn apps.console.api.main:app`.
- Do not rename these directories. `s3_enhancement/relevance.py` folds each
  file's path into the text it scores, and the committed replay caches in
  `s3_enhancement/cache/` contain these exact paths — a rename desyncs them and
  the codegen beat fails with "codegen returned unexpected file set". Moving a
  target is a path-rewrite across code *and* caches, not a `mv`.

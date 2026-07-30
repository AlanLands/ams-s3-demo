# apps/ — the four applications the demo runs

Everything in here is a *running application*. Nothing in here is S3 tooling —
the AI pipeline itself lives in `s3_enhancement/`, shared clients in `common/`,
and the presenter scripts in `demo/`.

Each app starts with one script and owns one port. Start them in the order
below; only the last two depend on each other.

| # | Application | Start with | Port | What it is |
|---|---|---|---|---|
| 1 | **Console** | `apps/run-console.sh` | 8000 + **5173** | The AMS console the presenter drives. FastAPI backend + React UI. Open **:5173**. |
| 2 | **PolicyCore** | `apps/run-policycore.sh` | 8501 | The client's policy-administration portal (Python/Streamlit/SQLite). The window the audience watches change. |
| 3 | **Policy-Service** | `apps/run-policy-service.sh` | 8081 | ClaimsPortal's policy side (Python/FastAPI). Start before Claims-Service. |
| 4 | **Claims-Service** | `apps/run-claims-service.sh` | 8082 | ClaimsPortal's claims side (Python/FastAPI). Target of CR-2026-043. |

You do **not** need all four for every beat. The mockapp CRs (CR-2026-041,
CR-2026-042) need apps 1 and 2. CR-2026-043 needs apps 1, 3 and 4.

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

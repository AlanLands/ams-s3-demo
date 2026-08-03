# MapleSure ClaimsPortal (two services)

> **S3 target**: this repo doubles as the S3 pipeline's second enhancement
> target — "ClaimsPortal", CR-2026-043 (`crs/CR-2026-043.md`), registered as
> `claimsportal-claims-deductible` in `s3_enhancement/targets.py` and linked to
> Jira ticket AMS-103 in the AMS console. The checked-in source is the
> **pre-CR baseline** (mirrored in `.baseline/`); the AI pipeline adds the
> deductible feature live (or from the committed replay cache), generates
> `tests/test_s3_claims_deductible.py`, and proves it with `pytest`. Reset
> between rehearsals with `demo/reset_s3_claimsportal.sh`, which copies
> `.baseline/` back over the source — it does not use `git checkout`, so it is
> unaffected by the uncommitted `apps/` → `repos/` move that currently breaks
> the two PolicyCore resets. A manager can run the same thing from the
> console's `/admin` panel.

It lives under `repos/` because that is where every repository S3 _changes_
lives; `apps/` holds the console and the launch scripts. See
[`../README.md`](../README.md) for the drop-folder contract.

Two small FastAPI applications that exercise service-to-service communication
over REST. All data is synthetic — no real client data.

| Service          | Port | Role                                                                | Team UI                                         |
| ---------------- | ---- | ------------------------------------------------------------------- | ----------------------------------------------- |
| `policy_service` | 8081 | Serves MapleSure group contracts from an in-memory list             | Contracts Team console — http://localhost:8081/ |
| `claims_service` | 8082 | Accepts benefit claims and validates them by calling policy_service | Claims Team console — http://localhost:8082/    |

Each service serves its team's web console from its own `static/` directory
(plain HTML/JS, no build step). The Contracts Team console lists and filters
group contracts; the Claims Team console submits claims via a form whose
contract dropdown is fetched live from policy_service (through
`GET /api/claims/policy-directory`), and shows each claim's ACCEPTED/REJECTED
outcome.

Naming note: the module, endpoint, and field names below (`policy_service`,
`/api/policies`, `policyNumber`, …) are a published API contract that
CR-2026-043 and the committed codegen recording depend on by exact name, so
they keep their original spelling. In prose the thing they carry is a **group
contract**.

The 2026-08-03 group-retirement reskin (endorsement → amendment, premium →
contribution, coverage tier → plan tier) applied to PolicyCore and skipped
this repo on purpose. **Claim**, **deductible** and **annual maximum** are
already the right words for group health, dental and disability benefits, and
renaming the API contract on top of that would desync the committed recording.

## Run

In two terminals — Policy-Service first, since Claims-Service validates
against it. The launch scripts live with the rest of the tooling, under
`apps/`, and read their ports from `.env`:

```bash
apps/run-policy-service.sh    # from the repo root
apps/run-claims-service.sh
```

## Worked example

```bash
# 1. List group contracts (policy_service)
curl http://localhost:8081/api/policies

# 2. Submit a valid claim (claims_service calls policy_service to validate)
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-1001", "amount": 1200, "description": "Physiotherapy - 12 sessions"}'
# -> 201 ACCEPTED

# 3. Claim over the annual maximum
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-1004", "amount": 99999, "description": "Critical illness lump sum"}'
# -> 201 REJECTED_OVER_LIMIT

# 4. Claim on a lapsed contract
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-1003", "amount": 500, "description": "Massage therapy - 5 sessions"}'
# -> 201 REJECTED_POLICY_LAPSED

# 5. Unknown contract
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-9999", "amount": 100, "description": "?"}'
# -> 422 error

# 6. List submitted benefit claims
curl http://localhost:8082/api/claims
```

Health checks: `http://localhost:8081/health`, `http://localhost:8082/health`.

The policy_service URL used by claims_service can be overridden with the
`POLICY_SERVICE_URL` environment variable (defaults to `http://localhost:8081`).

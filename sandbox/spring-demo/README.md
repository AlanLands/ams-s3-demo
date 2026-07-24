# MapleSure Spring Boot Demo (two services)

> **S3 target**: this app doubles as the S3 pipeline's second enhancement
> target — "ClaimsPortal", CR-2026-043 (`crs/CR-2026-043.md`), registered as
> `springdemo-claims-deductible` in `s3_enhancement/targets.py` and linked to
> Jira ticket AMS-103 in the AMS console. The checked-in source is the
> **pre-CR baseline** (mirrored in `.baseline/`); the AI pipeline adds the
> deductible feature live (or from the committed replay cache), generates
> `ClaimRulesTest.java`, and proves it with `mvn test`. Reset between
> rehearsals with `demo/reset_s3_springdemo.sh`.

Two small Spring Boot 3 (Java 21) applications that demo service-to-service
communication over REST. All data is synthetic — no real client data.

| Service | Port | Role | Team UI |
|---|---|---|---|
| `policy-service` | 8081 | Serves MapleSure policies from an in-memory list | Policy Team console — http://localhost:8081/ |
| `claims-service` | 8082 | Accepts claims and validates them by calling policy-service | Claims Team console — http://localhost:8082/ |

Each service serves its team's web console from `src/main/resources/static/`
(plain HTML/JS, no build step). The Policy Team console lists and filters
policies; the Claims Team console submits claims via a form whose policy
dropdown is fetched live from policy-service (through
`GET /api/claims/policy-directory`), and shows each claim's ACCEPTED/REJECTED
outcome.

## Run

In two terminals (or use `./run-demo.sh` to start both):

```bash
cd policy-service && mvn spring-boot:run
cd claims-service && mvn spring-boot:run
```

## Demo script

```bash
# 1. List policies (policy-service)
curl http://localhost:8081/api/policies

# 2. Submit a valid claim (claims-service calls policy-service to validate)
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-1001", "amount": 1200, "description": "Windshield damage"}'
# -> 201 ACCEPTED

# 3. Claim over the coverage limit
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-1004", "amount": 99999, "description": "Lost luggage"}'
# -> 201 REJECTED_OVER_LIMIT

# 4. Claim on a lapsed policy
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-1003", "amount": 500, "description": "Fender bender"}'
# -> 201 REJECTED_POLICY_LAPSED

# 5. Unknown policy
curl -X POST http://localhost:8082/api/claims \
  -H 'Content-Type: application/json' \
  -d '{"policyNumber": "MS-9999", "amount": 100, "description": "?"}'
# -> 422 error

# 6. List submitted claims
curl http://localhost:8082/api/claims
```

Health checks: `http://localhost:8081/actuator/health`, `http://localhost:8082/actuator/health`.

The policy-service URL used by claims-service can be overridden with the
`POLICY_SERVICE_URL` environment variable (defaults to `http://localhost:8081`).

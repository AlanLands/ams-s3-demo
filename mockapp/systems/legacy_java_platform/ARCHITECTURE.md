# MapleSure Legacy Platform — Architecture Overview

This directory documents the legacy Java estate that sits behind MapleSure's
policy and claims operations. The modern policy/claims portal
(`mockapp/app.py`, `mockapp/core/`) is a newer Python front-end layered on top
of this platform; it owns policy records, coverage tiers, and claim intake
directly and does not call into these subsystems.

## Subsystems

| Subsystem     | Package                              | Owns                                   | Design doc |
|---------------|---------------------------------------|-----------------------------------------|------------|
| Billing       | `com.maplesure.legacy.billing`        | Invoice ledger reconciliation, rate registration | `billing/DESIGN.md` |
| Underwriting  | `com.maplesure.legacy.underwriting`   | Applicant risk-band scoring at intake  | `underwriting/DESIGN.md` |
| Risk          | `com.maplesure.legacy.risk`           | Portfolio-level risk factor normalization | `risk/DESIGN.md` |
| Settlement    | `com.maplesure.legacy.settlement`     | Claim payout settlement calculations   | `settlement/DESIGN.md` |
| Audit         | `com.maplesure.legacy.audit`          | Regulatory audit trail recording       | `audit/DESIGN.md` |
| Reporting     | `com.maplesure.legacy.reporting`      | Scheduled batch reporting extracts     | `reporting/DESIGN.md` |

## Change-request routing

Each subsystem's design doc states what it owns and, just as importantly, what
it does **not** own. Change requests are routed to a subsystem only if the
request touches something in its "owns" list. A change to policy coverage
tiers, premiums, or the policy/claims portal itself does not touch any of the
six subsystems above — it belongs entirely to `mockapp/core/` — so an impact
analysis over this platform should read as "not relevant" across the board for
that class of change.

## Maintenance note

This platform predates the current AMS engagement and has no dedicated team;
support is handled ticket-by-ticket by whichever AMS engineer is assigned. Full
reverse-engineered runbooks are out of scope here — see the S4 knowledge
scenario for that exercise on the newer Python layer.

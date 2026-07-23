# Billing Subsystem — Design Notes

## Scope keywords

invoice ledger, ledger reconciliation, billing rate registration, remittance
posting, account balance, rate lookup table

## Overview

Reconciles the invoice ledger against recorded billing rates. Runs as a
scheduled batch process against the legacy data store; not called
synchronously from the front-end portal.

## Owns

- Invoice ledger reconciliation
- Per-account billing rate registration and lookup
- Rounding/normalization of reconciled amounts

## Does not own

- Anything on the front-end portal — that layer is a separate, modern
  codebase this subsystem has no dependency on
- Claim payouts — see the Settlement subsystem

## Components

`BillingHandler01`–`BillingHandler09` (`com.maplesure.legacy.billing`) —
each handler is a scaled reconciliation unit for a ledger partition; sized
this way for historical throughput reasons, not one-handler-per-feature.

## Notes

Front-end change requests generally do not touch this subsystem — its
reconciliation logic reads a settled ledger, it does not participate in
front-end request handling.

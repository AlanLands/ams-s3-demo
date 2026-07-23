# Underwriting Subsystem — Design Notes

## Scope keywords

applicant scoring, risk band assignment, intake screening, entry rate table,
eligibility check

## Overview

Scores incoming applicants into risk bands at intake time, ahead of
front-end record creation. Operates upstream of the front-end portal — by
the time a record exists there, underwriting has already run.

## Owns

- Applicant risk-band scoring at intake
- Entry-rate registration and lookup used in that scoring

## Does not own

- Anything on the front-end portal once a record has been created there
- Any process that runs after intake — this subsystem is intake-only

## Components

`UnderwritingHandler01`–`UnderwritingHandler09`
(`com.maplesure.legacy.underwriting`) — each handler scores one applicant
segment; the split is historical, not a current organizing principle.

## Notes

A front-end change request that only affects records after they already
exist there is a post-intake change and does not re-trigger this subsystem.

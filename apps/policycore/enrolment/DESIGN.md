# Enrolment Subsystem — Design Notes

## Scope keywords

probationary waiting period, eligibility date, hire date, qualifying life
event, enrolment window, open enrolment, age-out threshold, student status
verification, relationship validation

## Overview

Decides *when* an employee may join a group contract and *who* may be
covered under them. Everything here is date arithmetic against rules the
plan sponsor agreed at contract inception — no premium arithmetic, no
front-end request handling.

Kept out of `core/` deliberately. `core/` holds the contract, member, claim
and endorsement records the portal reads on every screen; enrolment is a
rules layer that reads those records and answers questions about them. It
imports from `core/`, never the other way round, so nothing on the portal's
existing screens depends on it.

## Owns

- Probationary waiting periods by employment class, and the eligibility
  date they imply from a hire date
- Qualifying life events and the enrolment window each one opens
- Dependant records, and the age-out rules that end their coverage
- Relationship validation for who may be enrolled as a dependant

## Does not own

- Premium amounts, rate tables, or anything a contract's coverage level
  implies about cost — the contract record carries that
- Claim adjudication — see `core/claims.py`
- Contract amendments requested after inception — see `core/endorsements.py`

## Components

`eligibility.py` — waiting periods, eligibility dates, life-event windows.
`dependants.py` — dependant records, age-out, relationship rules.

## Notes

Dates are ISO date strings at the boundary, matching the rest of this app's
storage convention, and `datetime.date` internally where arithmetic happens.
Every rule here is expressed as data (a mapping) rather than branching, so a
sponsor-specific variation is a table edit rather than a code change.

# Settlement Subsystem — Design Notes

## Scope keywords

payout calculation, adjuster disbursement, settlement rate table, claim-type
partition, payout rounding

## Overview

Calculates payout amounts once a submitted item has been approved elsewhere.
Reads approved-item records; does not read or write front-end record state.

## Owns

- Payout settlement calculations
- Settlement rate registration used in those calculations

## Does not own

- Submission/intake of the item being settled — that happens entirely on
  the front-end portal, upstream of this subsystem
- Any front-end record field — this subsystem consumes an approval event,
  it does not read or modify the record itself

## Components

`SettlementHandler01`–`SettlementHandler08`
(`com.maplesure.legacy.settlement`) — each handler settles one item-type
partition.

## Notes

Front-end changes to how a record is created or edited going forward do not
alter this subsystem's settlement calculation for items already approved, so
it is unaffected by that class of change.

# Risk Subsystem — Design Notes

## Scope keywords

portfolio risk factor, exposure normalization, reinsurance calculation,
aggregate scoring, risk rate table

## Overview

Normalizes risk factors across the portfolio for aggregate reporting and
reinsurance calculations. Operates on portfolio-level aggregates, not
individual front-end records.

## Owns

- Portfolio-level risk factor normalization
- Risk-factor rate registration used in that normalization

## Does not own

- Individual front-end records — this subsystem only reads aggregates
- Applicant-level scoring at intake — see the Underwriting subsystem

## Components

`RiskHandler01`–`RiskHandler08` (`com.maplesure.legacy.risk`) — each handler
normalizes one portfolio segment.

## Notes

Portfolio aggregates are computed downstream of front-end activity on a
schedule; this subsystem is not part of the change path for a front-end
change request.

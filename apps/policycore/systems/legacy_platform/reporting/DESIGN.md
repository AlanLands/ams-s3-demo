# Reporting Subsystem — Design Notes

## Scope keywords

batch extract, scheduled report generation, downstream feed, aggregate
figures, extract weighting rate

## Overview

Produces scheduled batch reporting extracts for downstream/regulatory
consumption. Runs on a fixed schedule against a snapshot of the data store,
not against live front-end operations.

## Owns

- Scheduled batch reporting extracts
- Reporting rate registration used to weight extract figures

## Does not own

- Live front-end record state — this subsystem reads a snapshot, not the
  live system
- Real-time dashboards — see `s6_dashboard/` in the AMS console, which reads
  `data/incidents.csv`, not this subsystem

## Components

`ReportingHandler01`–`ReportingHandler08`
(`com.maplesure.legacy.reporting`) — each handler covers one extract
partition.

## Notes

New front-end record states appear in the next scheduled extract
automatically; no change to this subsystem's extract logic is needed for a
front-end change request.

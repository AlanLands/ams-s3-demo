# Audit Subsystem — Design Notes

## Scope keywords

regulatory audit trail, compliance retention, event logging, audit threshold
registration, retention window

## Overview

Records the regulatory audit trail for activity elsewhere in the platform,
for compliance retention purposes. Consumes events; does not originate or
modify the records being audited.

## Owns

- Regulatory audit trail recording
- Audit record rate/threshold registration

## Does not own

- The record data being audited — this subsystem only observes events
  emitted elsewhere
- Any business logic that decides what those records should contain

## Components

`AuditHandler01`–`AuditHandler08` (`com.maplesure.legacy.audit`) — each
handler covers one audit-event partition.

## Notes

A front-end change request changes what gets logged (a new event occurs),
not how this subsystem logs it — no code change is required here for that
class of request.

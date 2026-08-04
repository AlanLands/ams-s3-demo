# DocumentHub — architecture

## What it is

The document generation service for MapleSure's group benefits estate. Its one
job in this demo is the **enrolment confirmation pack**: the letter and the
enclosures a person receives once an enrolment has been accepted.

It is a *downstream* system. It does not decide who may enrol, does not decide
what they may enrol in, and cannot correct either. It is told that an enrolment
happened and produces the document that goes with it.

## Context

```
PolicyCore ──(contract + access preferences)──> EnrolDirect
                                                     │
                                          accepted enrolment
                                          (incl. authorising
                                           preference, onRoster)
                                                     ▼
                                                DocumentHub ──> print vendor
```

EnrolDirect is the only upstream. The print vendor is the only downstream, and
it is out of scope for this repo — packs are returned over HTTP and nothing is
actually printed.

## Components

| File | Responsibility |
|---|---|
| `feed.py` | The enrolment feed contract, plus a seeded day of records. Owned by EnrolDirect; **read-only to this service.** |
| `wording.py` | The audience catalogue, the worded pack per audience, and `audience_for` — the single place an audience is chosen. |
| `enclosures.py` | The enclosure set per audience, and the print vendor's enclosure codes. |
| `packs.py` | Assembly. Resolves an audience, fills templates from the record, returns a `Pack`. Makes no decisions. |
| `main.py` | FastAPI surface — packs, and the selection audit. |
| `static/index.html` | Operator console. Vanilla HTML/CSS/JS, no build step. |

## Data model

`feed.EnrolmentRecord` is the only input type. Two of its fields drive
behaviour and they are **independent**:

- `authorisingPreference` — the access preference that opened the gate, one of
  two verbatim strings from PolicyCore.
- `onRoster` — whether the plan sponsor lists this person on the contract
  roster.

`wording.Wording` is one audience's pack: five prose fields, a description, and
`assumesNoMemberRecord` — a declared statement of the premise the pack is
written on, used by the audit to check packs against the feed.

`packs.Pack` is a rendered pack: the filled prose plus the resolved enclosure
codes, tagged with the audience that produced it.

## Runtime

FastAPI on uvicorn, port 8084 by default (`DOCUMENTHUB_PORT`). No database, no
broker, no build step — the feed is an in-process literal. It runs on the venv
alone, which is what lets a locked-down host serve it.

Start it with `apps/run-documenthub.sh`.

## Where to look for what

- **"Why did this person get this letter?"** → `wording.audience_for`. It is
  the only answer; nothing else selects.
- **"What does this letter say?"** → `wording.WORDING`.
- **"What was in the envelope?"** → `enclosures.ENCLOSURES`.
- **"Is the batch right?"** → `GET /api/audit/selection-inputs`. Reads the
  facts the selection rule does *not* use, which is the only way a rule can be
  audited.
- **"Why is it shaped this way?"** → `DESIGN.md`.

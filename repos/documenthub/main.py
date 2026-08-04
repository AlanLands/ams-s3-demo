"""DocumentHub — MapleSure's enrolment document service.

Produces the confirmation pack a person receives after an enrolment is
accepted. It consumes the enrolment feed from EnrolDirect (`feed.py`), selects
an audience (`wording.py`), and assembles the pack (`packs.py`).

The endpoints below are split along the same line the modules are:

**Packs** (`/api/packs/...`) is the runtime — the documents this service would
actually print today, for the feed it actually holds.

**Audit** (`/api/audit/...`) reports on the selection rule rather than on any
one document: which audiences exist, how a batch distributes across them, and
which records the rule reached a decision about on grounds it cannot fully
see. That last one is not a health check. It is the question "are we confident
every one of these is the right document", asked of the whole batch at once,
which is not answerable by reading any single pack — each one looks fine.

Runs on nothing but the venv (FastAPI + uvicorn, already pinned), so a
locked-down sandbox can host it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from repos.documenthub import enclosures, feed, packs, wording

app = FastAPI(title="documenthub")

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _record_payload(record: feed.EnrolmentRecord) -> dict[str, object]:
    return {
        "recordId": record.recordId,
        "applicantId": record.applicantId,
        "fullName": record.fullName,
        "contractNumber": record.contractNumber,
        "sponsorName": record.sponsorName,
        "planCode": record.planCode,
        "planName": record.planName,
        "planTier": record.planTier,
        "effectiveDate": record.effectiveDate,
        "authorisingPreference": record.authorisingPreference,
        "onRoster": record.onRoster,
    }


@app.get("/api/records")
def list_records() -> list[dict[str, object]]:
    return [_record_payload(r) for r in feed.all_records()]


@app.get("/api/records/{record_id}")
def get_record(record_id: str) -> dict[str, object]:
    record = feed.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="enrolment record not found")
    return _record_payload(record)


@app.get("/api/packs")
def list_packs() -> list[dict[str, object]]:
    """Every pack today's feed would produce."""
    return [packs.build_pack(r).as_dict() for r in feed.all_records()]


@app.get("/api/packs/{record_id}")
def get_pack(record_id: str) -> dict[str, object]:
    """The confirmation pack for one enrolment record."""
    record = feed.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="enrolment record not found")
    pack = packs.build_pack(record)
    return {**pack.as_dict(), "bodyText": pack.body_text()}


@app.get("/api/audit/audiences")
def audit_audiences() -> dict[str, object]:
    """The audience catalogue and how today's feed distributes across it."""
    return {
        "audiences": wording.audience_catalogue(),
        "breakdown": packs.audience_breakdown(feed.all_records()),
        "enclosuresByAudience": {
            audience: [
                {"code": code, "title": enclosures.enclosure_title(code)}
                for code in enclosures.enclosures_for(audience)
            ]
            for audience in wording.ALL_AUDIENCES
        },
    }


@app.get("/api/audit/selection-inputs")
def audit_selection_inputs() -> dict[str, object]:
    """Every record, the audience selected for it, and the facts about it.

    Reports the facts the feed carries alongside the decision, rather than only
    the ones the selection rule happens to read. That asymmetry is the point: a
    rule can only be audited against information it does not use, and a report
    limited to the rule's own inputs can never show it a case it is blind to.

    `contradictsRoster` is that comparison made explicit: the selected pack
    claims MapleSure holds no member record for this person
    (`Wording.assumesNoMemberRecord`), while the sponsor lists them on its own
    roster. Both halves are facts stated by someone other than the selection
    rule — one by Communications when the pack was worded, one by the sponsor —
    so the check survives a change to how audiences are chosen. Phrasing it
    instead as "the audience matches the roster" would hard-code the assumption
    that a rostered person always receives the member pack, which is exactly
    the assumption under review.

    It is computed here rather than in `wording.py` on purpose. This is an
    observation about the rule; making it part of the rule would be a change to
    what documents people receive, and that is a decision for plan
    administration, not for an audit endpoint.
    """
    rows = []
    for record in feed.all_records():
        audience = wording.audience_for(record)
        claims_no_record = wording.wording_for(audience).assumesNoMemberRecord
        rows.append(
            {
                "recordId": record.recordId,
                "fullName": record.fullName,
                "sponsorName": record.sponsorName,
                "authorisingPreference": record.authorisingPreference,
                "onRoster": record.onRoster,
                "audience": audience,
                "packAssumesNoMemberRecord": claims_no_record,
                "contradictsRoster": record.onRoster and claims_no_record,
            }
        )
    return {
        "records": rows,
        "contradictionCount": sum(1 for row in rows if row["contradictsRoster"]),
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")

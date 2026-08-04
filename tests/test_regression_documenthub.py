"""Pre-existing regression suite for DocumentHub's confirmation packs.

Checked in, human-authored, and named by no target's testgen or codegen
allowlist. It lives in `tests/` rather than under `repos/documenthub/` for the
same reason the other three suites do: anything ending `.py` under a target
root joins the codegen candidate pool, and a suite the pipeline can rewrite is
not an independent check of anything.

**Every assertion here holds before and after US-2026-046.** That is the rule
for these suites — they are invariants, not assertions about the change under
test. The user story adds a third audience for rostered applicants admitted
under guest access, so nothing here asserts which audience that combination
resolves to, nor how many audiences exist. What it asserts instead is the
ground the story must not move:

1. The two existing audiences keep their exact prose and their exact
   enclosure sets, field by field, pinned as literal values. This is the
   story's central promise — it adds a case rather than re-wording the
   existing ones — and a comparison against anything the story also changes
   would prove nothing.
2. The four historical records keep the packs they get today, named record by
   named record. Those are the two combinations DocumentHub has always
   received, and if the story moved one of them it has escaped the population
   it was scoped to.
3. Selection happens in exactly one place. `packs.build_pack` must agree with
   `wording.audience_for` for every record in the feed, so a call site that
   grew its own copy of the rule shows up here rather than in a document.
4. A pack that claims MapleSure holds no member record is never sent to
   someone the sponsor lists on its roster. Stated in terms of the claim
   rather than the audience, so it survives the story adding one — and it is
   the one assertion here that is *false today* for one seeded record, which
   is why it is written as a property of the audit endpoint's count rather
   than as a pass/fail on the baseline. See its own docstring.
5. Structural integrity: every audience has wording and enclosures, no
   template references a field the feed does not carry, and the feed rejects
   an unknown preference.

Assertions go through HTTP where the console does and through the modules
directly where the invariant is structural. Nothing here asserts the *absence*
of a field.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from repos.documenthub import enclosures, feed, packs, wording
from repos.documenthub.main import app

client = TestClient(app)


# --------------------------------------------------------------------------
# 1. The two existing audiences are pinned, field by field.
#
# Literal expected values rather than a comparison against the module's own
# constants — a test that reads WORDING to check WORDING passes no matter what
# the story does to it.
# --------------------------------------------------------------------------

MEMBER_PACK_FIELDS = {
    "salutation": "Dear {fullName},",
    "opening": (
        "Your enrolment in {planName} ({planTier}) under your group "
        "benefits plan with {sponsorName} is confirmed, effective "
        "{effectiveDate}."
    ),
    "relationship": (
        "This plan has been added alongside the benefits you already hold "
        "under group contract {contractNumber}. Your existing coverage is "
        "unaffected and continues without interruption."
    ),
    "nextSteps": (
        "Your updated benefits card will arrive within ten business days. "
        "You can review your full coverage at any time through the member "
        "portal using your existing sign-in."
    ),
    "closing": (
        "If anything above does not match what you selected, contact your "
        "plan administrator at {sponsorName} before the effective date."
    ),
}

GUEST_PACK_FIELDS = {
    "salutation": "Dear {fullName},",
    "opening": (
        "Your enrolment in {planName} ({planTier}) is confirmed, effective "
        "{effectiveDate}."
    ),
    "relationship": (
        "You are enrolling under an arrangement agreed by {sponsorName} "
        "rather than as a listed member of group contract "
        "{contractNumber}. Because we hold no member record for you, we "
        "need you to confirm your identity and contact details before "
        "coverage can be used."
    ),
    "nextSteps": (
        "Complete and return the enclosed identity confirmation form "
        "within thirty days. Your benefits card will be issued once it has "
        "been received and checked."
    ),
    "closing": (
        "If you believe you should already be listed on this contract, "
        "contact your plan administrator at {sponsorName} — do not return "
        "the enclosed form."
    ),
}


@pytest.mark.parametrize(
    "audience,expected",
    [
        (wording.AUDIENCE_MEMBER, MEMBER_PACK_FIELDS),
        (wording.AUDIENCE_GUEST, GUEST_PACK_FIELDS),
    ],
)
def test_existing_audience_wording_is_unchanged(audience, expected):
    words = wording.wording_for(audience)

    for field, value in expected.items():
        assert getattr(words, field) == value, f"{audience}.{field} was re-worded"


def test_existing_audience_premises_are_unchanged():
    """The member pack claims we hold a record; the guest pack claims we do not.

    These two flags are what the audit endpoint checks packs against. Flipping
    one would make every contradiction disappear without a single document
    improving, which is the most attractive wrong way to close this story.
    """
    assert wording.wording_for(wording.AUDIENCE_MEMBER).assumesNoMemberRecord is False
    assert wording.wording_for(wording.AUDIENCE_GUEST).assumesNoMemberRecord is True


def test_existing_audience_enclosures_are_unchanged():
    assert enclosures.enclosures_for(wording.AUDIENCE_MEMBER) == (
        enclosures.BENEFIT_SUMMARY,
        enclosures.CLAIMS_GUIDE,
        enclosures.PRIVACY_NOTICE,
    )
    assert enclosures.enclosures_for(wording.AUDIENCE_GUEST) == (
        enclosures.BENEFIT_SUMMARY,
        enclosures.CLAIMS_GUIDE,
        enclosures.IDENTITY_FORM,
        enclosures.PRIVACY_NOTICE,
    )


# --------------------------------------------------------------------------
# 2. The historical records keep the packs they get today.
#
# ENR-20260804-005 is deliberately absent: it is the rostered guest-access
# record the story is about, and pinning its audience either way would make
# this suite an assertion about the change under test.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "record_id,expected_audience",
    [
        ("ENR-20260804-001", wording.AUDIENCE_MEMBER),
        ("ENR-20260804-002", wording.AUDIENCE_MEMBER),
        ("ENR-20260804-003", wording.AUDIENCE_GUEST),
        ("ENR-20260804-004", wording.AUDIENCE_GUEST),
    ],
)
def test_historical_records_keep_their_audience(record_id, expected_audience):
    response = client.get(f"/api/packs/{record_id}")

    assert response.status_code == 200
    assert response.json()["audience"] == expected_audience


def test_a_members_pack_never_asks_them_to_prove_who_they_are():
    """The identity form is the enclosure with a phone call attached."""
    for record in feed.all_records():
        if record.authorisingPreference != feed.MEMBER_ACCESS:
            continue
        pack = packs.build_pack(record)
        codes = [code for code in pack.enclosures]
        assert enclosures.IDENTITY_FORM not in codes, (
            f"{record.recordId} ({record.fullName}) is enrolled as a member and "
            f"is being asked to confirm their identity"
        )


# --------------------------------------------------------------------------
# 3. Selection happens in exactly one place.
# --------------------------------------------------------------------------

def test_assembly_never_second_guesses_the_selection_rule():
    """`build_pack` must resolve its audience through `wording.audience_for`.

    Asserted as agreement across the whole feed rather than by inspecting the
    call: the failure this guards against is a call site growing its own copy
    of the rule, and a copy that agrees on every record is not yet a bug.
    """
    for record in feed.all_records():
        assert packs.build_pack(record).audience == wording.audience_for(record)


def test_the_batch_breakdown_covers_every_audience_and_sums_to_the_feed():
    """Every known audience appears, including any with a count of zero.

    Wording that exists but is never selected is the interesting case — it
    means a pack was written for a recipient the rule cannot reach — and
    dropping empty keys would hide precisely that.
    """
    breakdown = packs.audience_breakdown(feed.all_records())

    assert set(breakdown) == set(wording.ALL_AUDIENCES)
    assert sum(breakdown.values()) == len(feed.all_records())


# --------------------------------------------------------------------------
# 4. The claim a pack makes is checked against the roster, not against the rule.
# --------------------------------------------------------------------------

def test_the_audit_reports_contradictions_from_the_packs_own_premise():
    """The audit must derive its verdict from `assumesNoMemberRecord`.

    This is the independent check on the selection rule, so it may not be
    rewritten in terms of that rule. Pinned by construction: a record that is
    on the roster and receives a pack claiming no member record must be
    reported as contradicting, whatever audience the rule chose for it.

    Deliberately *not* asserted: that the contradiction count is zero. It is 1
    today — that is the defect US-2026-046 exists to fix — and asserting zero
    would make this suite fail before the story and pass after, which is the
    definition of an assertion about the change under test.
    """
    audit = client.get("/api/audit/selection-inputs").json()

    for row in audit["records"]:
        expected = row["onRoster"] and row["packAssumesNoMemberRecord"]
        assert row["contradictsRoster"] is expected, row["recordId"]

    assert audit["contradictionCount"] == sum(
        1 for row in audit["records"] if row["contradictsRoster"]
    )


def test_nobody_off_the_roster_is_reported_as_contradicting_it():
    """A non-rostered guest receiving the guest pack is correct, not a defect.

    The count must not inflate itself by flagging the audience this service was
    built for — that would make the audit useless at exactly the moment it is
    being used to decide whether the story worked.
    """
    audit = client.get("/api/audit/selection-inputs").json()

    for row in audit["records"]:
        if not row["onRoster"]:
            assert row["contradictsRoster"] is False, row["recordId"]


# --------------------------------------------------------------------------
# 5. Structural integrity.
# --------------------------------------------------------------------------

def test_every_audience_has_wording_and_enclosures():
    """Adding an audience without one or the other is the partial-edit failure.

    Ranges over `ALL_AUDIENCES` rather than a fixed list, so it covers the
    audience the story adds without asserting that it exists.
    """
    for audience in wording.ALL_AUDIENCES:
        words = wording.wording_for(audience)
        assert words.audience == audience
        assert words.description.strip()
        assert isinstance(words.assumesNoMemberRecord, bool)
        assert enclosures.enclosures_for(audience), audience


def test_every_pack_renders_with_no_placeholder_left_behind():
    """A template naming a field the feed lacks prints the brace literally."""
    for record in feed.all_records():
        pack = packs.build_pack(record)
        body = pack.body_text()
        assert "{" not in body and "}" not in body, pack.recordId
        assert record.fullName in body


def test_an_unknown_audience_raises_rather_than_defaulting():
    with pytest.raises(KeyError):
        wording.wording_for("NO_SUCH_PACK")
    with pytest.raises(KeyError):
        enclosures.enclosures_for("NO_SUCH_PACK")


def test_the_feed_rejects_a_preference_this_service_does_not_know():
    """An unknown preference means EnrolDirect shipped a change we were not
    told about. Producing *some* document anyway is how a member receives a
    guest's pack."""
    with pytest.raises(ValueError, match="unknown authorising preference"):
        feed.EnrolmentRecord(
            recordId="ENR-TEST",
            applicantId="APP-TEST",
            fullName="Test Person",
            contractNumber="GC-40017",
            sponsorName="Boreal Freight Cooperative",
            planCode="EHC-BASE",
            planName="Extended Health Base",
            planTier="Standard",
            effectiveDate="2026-10-01",
            authorisingPreference="Online Enrolment - Something New",
            onRoster=True,
        )


def test_unknown_record_is_a_404_not_an_empty_pack():
    assert client.get("/api/packs/ENR-NOPE").status_code == 404
    assert client.get("/api/records/ENR-NOPE").status_code == 404


def test_health_endpoint_reports_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

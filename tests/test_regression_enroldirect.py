"""Pre-existing regression suite for the EnrolDirect enrolment access gate.

Checked in, human-authored, and named by no target's testgen or codegen
allowlist. It lives in `tests/` rather than under `repos/enroldirect/` for the
same reason the other two suites do: anything ending `.py` under a target root
joins the codegen candidate pool, and a suite the pipeline can rewrite is not
an independent check of anything.

**Every assertion here holds before and after US-2026-045.** That is the rule
for these suites — they are invariants, not assertions about the change under
test. The user story settles how a prospect is classified at the gate, so nothing here
asserts a prospect's gate outcome. What it asserts instead is the ground the
user story must not move:

1. The contract gate runs before the preference gate. A lapsed contract keeps
   whatever preferences it was configured with, so reversing those two would
   let stale configuration grant access, and every category-level assertion
   would still pass.
2. Members and guests reach exactly the outcomes they reach today, named
   applicant by named applicant. This is the promise the reclassification
   makes to every other consumer of these preferences: if it moved a member's
   outcome, the change would not be contained to the population it was scoped
   to. Asserted as absolute values rather than as a comparison, because a
   comparison of two things the user story changes together proves nothing.
3. The gate's decision for a classified category matches what the contract
   configuration says it should be. `impact.py` models the gate's rules
   against that same configuration to size an option the gate does not
   implement; this pins the model to the rules it claims to mirror, so the two
   cannot drift apart in either direction.
4. The analysis keeps reporting a disagreement in both directions. If it ever
   reported one column, or none, the comparison feeding the recommendation
   would have quietly stopped working.
5. Nothing the gate refuses can be enrolled, by any route.

Assertions go through HTTP and read fields off JSON rather than constructing
decisions directly, so adding a field to the decision payload is not a
regression. Nothing here asserts the *absence* of a field.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from repos.enroldirect.main import app

client = TestClient(app)

# Fields every consumer of a decision reads. Deliberately does not include
# fields the user story may add — this is a floor, not a schema.
DECISION_FIELDS = [
    "granted",
    "applicantId",
    "contractNumber",
    "category",
    "requiredPreference",
    "authorisingPreference",
    "reasons",
]

MEMBER_ACCESS = "Online Enrolment - Member"
GUEST_ACCESS = "Online Enrolment - Guest"

PREFERENCE_FOR_CATEGORY = {"MEMBER": MEMBER_ACCESS, "GUEST": GUEST_ACCESS}


def check(applicant_id: str) -> dict:
    response = client.post(
        "/api/eligibility/check", json={"applicantId": applicant_id}
    )
    assert response.status_code == 200, response.text
    return response.json()


def contracts_by_number() -> dict[str, dict]:
    return {c["contractNumber"]: c for c in client.get("/api/contracts").json()}


def test_contract_directory_lists_all_seeded_contracts():
    response = client.get("/api/contracts")

    assert response.status_code == 200
    contracts = response.json()
    assert [c["contractNumber"] for c in contracts] == [
        "MS-2001",
        "MS-2002",
        "MS-2003",
        "MS-2004",
        "MS-2005",
    ]


def test_every_decision_exposes_the_fields_consumers_read():
    decision = check("AP-4001")

    for field in DECISION_FIELDS:
        assert field in decision, f"decision lost field {field}"


def test_member_and_guest_outcomes_are_exactly_what_they_are_today():
    """The population the user story is not scoped to must not move.

    Absolute expected values, not a before/after comparison — every one of
    these must read the same on both sides of the change.
    """
    expected = {
        # (granted, authorising preference)
        "AP-4001": (True, MEMBER_ACCESS),  # member on MS-2001, both enabled
        "AP-4002": (True, GUEST_ACCESS),  # guest on MS-2001, both enabled
        "AP-4004": (True, MEMBER_ACCESS),  # member on MS-2002, member only
        "AP-4007": (True, GUEST_ACCESS),  # guest on MS-2003, guest only
        "AP-4009": (False, None),  # member on MS-2004, neither enabled
        "AP-4011": (False, None),  # member on MS-2005, LAPSED
    }
    for applicant_id, (granted, authorising) in expected.items():
        decision = check(applicant_id)

        assert decision["granted"] is granted, applicant_id
        assert decision["authorisingPreference"] == authorising, applicant_id


def test_gate_matches_the_contract_configuration_for_classified_categories():
    """The gate and the analysis's model of it must agree.

    `impact.py` cannot call the gate to size an option the gate does not
    implement, so it models the rules against contract configuration instead.
    This asserts that model *is* the gate's behaviour wherever the gate has an
    opinion — the two are only allowed to differ on the population whose
    classification is still open.
    """
    contracts = contracts_by_number()
    applicants = client.get("/api/applicants").json()

    for applicant in applicants:
        category = applicant["category"]
        if category not in PREFERENCE_FOR_CATEGORY:
            continue
        contract = contracts[applicant["contractNumber"]]
        expected = (
            contract["status"] == "ACTIVE"
            and PREFERENCE_FOR_CATEGORY[category] in contract["enabledPreferences"]
        )

        decision = check(applicant["applicantId"])

        assert decision["granted"] is expected, (
            f"{applicant['applicantId']} ({category}) on "
            f"{contract['contractNumber']}: gate disagrees with configuration"
        )


def test_contract_offering_no_online_enrolment_denies_every_category():
    """MS-2004 enables neither preference, so no classification can open it."""
    member = check("AP-4009")
    prospect = check("AP-4010")

    assert member["granted"] is False
    assert prospect["granted"] is False
    assert member["authorisingPreference"] is None
    assert prospect["authorisingPreference"] is None


def test_lapsed_contract_denies_despite_both_preferences_being_configured():
    """The contract gate must run before the preference gate.

    MS-2005 is LAPSED and still carries both preferences. If these two gates
    were reordered this member would be granted access on stale configuration,
    and no category-level assertion in this file would catch it.
    """
    decision = check("AP-4011")

    assert decision["granted"] is False
    assert decision["authorisingPreference"] is None
    assert any("LAPSED" in reason for reason in decision["reasons"])


def test_lapsed_contract_denies_a_prospect_under_any_classification():
    """The one prospect assertion that is safe to make.

    AP-4012 is on the LAPSED MS-2005. The contract gate runs first, so this
    denial cannot be reached by any answer to the classification question —
    it is an invariant, where every other prospect outcome is the subject of
    the change.
    """
    decision = check("AP-4012")

    assert decision["granted"] is False
    assert decision["authorisingPreference"] is None


def test_unknown_applicant_is_a_404():
    response = client.post("/api/eligibility/check", json={"applicantId": "AP-9999"})

    assert response.status_code == 404


def test_impact_analysis_reports_disagreements_it_can_demonstrate():
    impact = client.get("/api/analysis/prospect-impact").json()

    assert impact["prospectCount"] == 6
    assert impact["disagreementCount"] == len(impact["disagreements"])
    assert impact["disagreementCount"] > 0
    # Both directions must appear, or the seed has stopped exercising the
    # tension the analysis exists to report.
    granted_only_by = {d["grantedOnlyBy"] for d in impact["disagreements"]}
    assert granted_only_by == {"MEMBER", "GUEST"}


def test_impact_analysis_disagreement_runs_both_ways_on_named_contracts():
    """The comparison reads contract configuration rather than preferring one
    option globally. AP-4005 sits on MS-2002 (member access only) and AP-4008
    on MS-2003 (guest access only), so they must disagree in opposite
    directions."""
    impact = client.get("/api/analysis/prospect-impact").json()
    by_applicant = {d["applicantId"]: d for d in impact["disagreements"]}

    assert by_applicant["AP-4005"]["grantedOnlyBy"] == "MEMBER"
    assert by_applicant["AP-4008"]["grantedOnlyBy"] == "GUEST"


def test_impact_analysis_states_what_it_does_not_establish():
    """The honesty clause. An analysis reporting only supporting numbers is
    advocacy, and this endpoint feeds a recommendation to a decision owner."""
    impact = client.get("/api/analysis/prospect-impact").json()

    assert impact["notEvidencedByThisAnalysis"]
    assert impact["recommendation"]["costOfThisChoice"]
    assert impact["recommendation"]["decisionOwner"]


def test_consumer_inventory_names_the_enforcing_system_and_its_direction():
    consumers = client.get("/api/analysis/consumers").json()

    by_relation = {c["relation"] for c in consumers}
    assert {"upstream", "enforcing", "downstream"} <= by_relation
    enforcing = [c for c in consumers if c["relation"] == "enforcing"]
    assert [c["application"] for c in enforcing] == ["EnrolDirect"]


def test_consumer_inventory_separates_being_affected_from_having_work():
    """Being affected and having work to do are different questions.

    Three downstream systems consume the authorising preference; exactly one
    has to write code. NightlyBatch's totals move between buckets it already
    has and IntegrationBridge carries an existing field with an existing
    value — both keep working untouched. DocumentHub has to word a pack for a
    recipient neither of its existing packs was written for.

    This is pinned rather than left to prose because the cross-team check
    raises a real ticket on a real team's board per entry, and the failure
    mode is silent: collapsing the two questions turns a one-repo user story
    into a multi-team programme that nobody notices is fictional until three
    teams have triaged it. It holds before and after US-2026-045 — the user
    story changes the gate, not the estate around it.
    """
    consumers = client.get("/api/analysis/consumers").json()
    by_app = {c["application"]: c for c in consumers}

    # Every consumer answers the question, and gives its reason either way. A
    # blank rationale on a `False` is indistinguishable from an omission.
    for consumer in consumers:
        assert isinstance(consumer["changeRequired"], bool)
        assert consumer["changeRationale"].strip()

    assert by_app["DocumentHub"]["changeRequired"] is True
    assert by_app["NightlyBatch"]["changeRequired"] is False
    assert by_app["IntegrationBridge"]["changeRequired"] is False
    assert by_app["PolicyCore"]["changeRequired"] is False


def test_the_analysis_sizes_the_downstream_document_consequence():
    """The DocumentHub effect is a number, not an adjective.

    It rides on `/api/analysis/prospect-impact` rather than an endpoint of its
    own, deliberately: a downstream consequence served separately is one a
    reader can finish the analysis without having seen.

    Both options are reported, not just the recommended one. An analysis that
    only priced the option it advocates would be advocacy — the same rule that
    governs `catalogueReach` and `notEvidencedByThisAnalysis`. Asserted before
    and after the user story because `impact.py` sizes options the gate does
    not implement, and must keep doing so once one is adopted.
    """
    document = client.get("/api/analysis/prospect-impact").json()["documentImpact"]

    assert document["consumer"] == "DocumentHub"
    assert set(document["perOption"]) == {"MEMBER", "GUEST"}
    for option in document["perOption"].values():
        assert isinstance(option["packsRequiringNewWording"], int)
        assert option["consequenceIfUnchanged"].strip()

    # The headline figure must be the recommended option's, not the larger of
    # the two — quoting whichever number is bigger is how a sizing becomes a
    # sales pitch.
    recommended = document["recommendedOption"]
    assert document["packsUnderRecommendedOption"] == (
        document["perOption"][recommended]["packsRequiringNewWording"]
    )

    # The rule it assumes about DocumentHub is stated as an assumption. This
    # app cannot see that code, and a consequence derived from an unverifiable
    # premise has to say so.
    assert document["assumption"].strip()


def test_only_one_other_team_is_owed_work_by_this_change():
    """The cross-team ticket list is exactly [DocumentHub].

    EnrolDirect is `changeRequired` too — the change is its own — so this also
    pins that the enforcing system is excluded. A change cannot be cross-team
    with itself, and letting it through would put this story's own work on
    another team's board.
    """
    from repos.enroldirect import impact

    owed = impact.other_teams_requiring_change()

    assert [entry["application"] for entry in owed] == ["DocumentHub"]
    assert all(entry["changeRationale"].strip() for entry in owed)


def test_health_endpoint_reports_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --------------------------------------------------------------------------
# Benefit catalogue and enrolment.
#
# The enrolment path must reuse the access gate rather than reimplementing it.
# These assert the observable consequence of that: nothing the gate refuses can
# be enrolled, by any route.
# --------------------------------------------------------------------------


def enrol(applicant_id: str, plan_code: str, tier: str) -> dict:
    response = client.post(
        "/api/enrolments",
        json={
            "applicantId": applicant_id,
            "planCode": plan_code,
            "coverageTier": tier,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def setup_function() -> None:
    """Each test starts from an empty enrolment log.

    The store is process-global, so without this the audit-log assertions would
    depend on which tests ran before them.
    """
    client.post("/api/enrolments/reset")


def test_member_enrols_in_an_open_plan():
    record = enrol("AP-4001", "PL-1001", "Family")

    assert record["status"] == "SUBMITTED"
    assert record["monthlyPremium"] == 214.0
    assert record["authorisingPreference"] == MEMBER_ACCESS
    assert record["reference"].startswith("ENR-")


def test_guest_cannot_enrol_in_a_member_only_plan():
    """The classification's second bite: past the gate, at the catalogue."""
    record = enrol("AP-4002", "PL-1003", "Single")

    assert record["status"] == "REFUSED"
    assert record["refusalCode"] == "PLAN_REQUIRES_EXISTING_COVERAGE"


def test_enrolment_cannot_bypass_a_closed_channel():
    """A lapsed contract must refuse at the enrolment path too, not just the
    access endpoint — the gate is reused, so this can never diverge."""
    record = enrol("AP-4011", "PL-5001", "Single")

    assert record["status"] == "REFUSED"
    assert record["refusalCode"] == "NO_CHANNEL_ACCESS"


def test_enrolment_refusal_matches_the_gate_for_every_applicant():
    """The enrolment path may add refusals; it may never add an admission.

    Whatever the gate says about someone, the enrolment path must not be more
    permissive. This holds across the user story because it is stated relative to the
    gate rather than against a fixed list of outcomes.
    """
    for applicant in client.get("/api/applicants").json():
        applicant_id = applicant["applicantId"]
        plans = client.get(f"/api/contracts/{applicant['contractNumber']}/plans").json()
        if not plans:
            continue
        plan = plans[0]
        record = enrol(applicant_id, plan["planCode"], plan["offeredTiers"][0])

        if not check(applicant_id)["granted"]:
            assert record["status"] == "REFUSED", applicant_id
            assert record["refusalCode"] == "NO_CHANNEL_ACCESS", applicant_id


def test_plan_not_on_the_contract_is_refused():
    record = enrol("AP-4001", "PL-3001", "Single")

    assert record["status"] == "REFUSED"
    assert record["refusalCode"] == "PLAN_NOT_ON_CONTRACT"


def test_tier_the_plan_is_not_sold_at_is_refused():
    # PL-1003 is offered at Single and Family only.
    record = enrol("AP-4001", "PL-1003", "Couple")

    assert record["status"] == "REFUSED"
    assert record["refusalCode"] == "TIER_NOT_OFFERED"


def test_refused_attempts_are_recorded_not_discarded():
    enrol("AP-4001", "PL-1001", "Single")
    enrol("AP-4001", "PL-3001", "Single")  # wrong contract

    summary = client.get("/api/enrolments/summary").json()
    assert summary["totalAttempts"] == 2
    assert summary["submitted"] == 1
    assert summary["refused"] == 1
    assert summary["refusalsByCode"]["PLAN_NOT_ON_CONTRACT"] == 1


def test_audit_log_returns_newest_first():
    first = enrol("AP-4001", "PL-1001", "Single")
    second = enrol("AP-4001", "PL-1002", "Single")

    log = client.get("/api/enrolments").json()
    assert [r["reference"] for r in log] == [second["reference"], first["reference"]]


def test_catalogue_marks_unavailable_plans_rather_than_hiding_them():
    """A plan that silently vanishes generates the support call."""
    catalogue = client.get("/api/applicants/AP-4002/plans").json()

    codes = {p["planCode"] for p in catalogue["plans"]}
    assert "PL-1003" in codes, "member-only plan was hidden instead of marked"
    member_only = next(p for p in catalogue["plans"] if p["planCode"] == "PL-1003")
    assert member_only["available"] is False
    assert member_only["unavailableReason"]


def test_catalogue_reach_only_counts_prospects_the_analysis_admits():
    """Otherwise a prospect refused at the door would be counted twice."""
    impact = client.get("/api/analysis/prospect-impact").json()
    reach = impact["catalogueReach"]

    for option in impact["options"]:
        assert (
            reach[option["option"]]["prospectsAdmitted"] == option["prospectsGranted"]
        ), option["option"]


def test_unknown_plan_on_the_catalogue_endpoint_is_a_404():
    assert client.get("/api/contracts/MS-9999/plans").status_code == 404

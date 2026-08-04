"""Regression suite for the enrolment subsystem.

Lives in tests/ rather than under repos/policycore/ for the reason CLAUDE.md
gives: anything ending .py under a target root joins the codegen candidate
pool, and a test file in there would be scored against every user story.

These are invariants, not assertions about any user story under test — they must
pass identically before and after US-2026-041 and US-2026-042, neither of
which touches this subsystem.
"""

from __future__ import annotations

from datetime import date

from repos.policycore.enrolment.dependants import (
    CHILD_AGE_OUT,
    STUDENT_AGE_OUT,
    Dependant,
    age_on,
    coverage_ends_on,
    covered_dependants,
    is_covered,
    rejection_reason,
)
from repos.policycore.enrolment.eligibility import (
    eligibility_date,
    enrolment_window_closes,
    has_served_waiting_period,
    is_window_open,
    may_enrol,
    waiting_period_days,
)


# --- waiting periods ---------------------------------------------------------


def test_waiting_period_comes_from_the_negotiated_table():
    assert waiting_period_days("Full-Time") == 30
    assert waiting_period_days("Contract") == 180
    assert waiting_period_days("Executive") == 0


def test_unknown_employment_class_does_not_block_enrolment():
    """An unlisted class is a gap in sponsor-negotiated data, not a reason to
    refuse someone — it must not raise or silently bar them."""
    assert waiting_period_days("Apprentice") == 0
    assert has_served_waiting_period("2026-01-01", "Apprentice", "2026-01-01")


def test_eligibility_date_is_hire_date_plus_the_waiting_period():
    assert eligibility_date("2026-01-01", "Full-Time") == date(2026, 1, 31)


def test_coverage_starts_on_the_eligibility_date_not_the_day_after():
    assert has_served_waiting_period("2026-01-01", "Full-Time", "2026-01-31")
    assert not has_served_waiting_period("2026-01-01", "Full-Time", "2026-01-30")


# --- life-event windows ------------------------------------------------------


def test_qualifying_event_opens_a_window_that_closes():
    assert enrolment_window_closes("Marriage", "2026-03-01") == date(2026, 4, 1)
    assert is_window_open("Marriage", "2026-03-01", "2026-03-15")
    assert not is_window_open("Marriage", "2026-03-01", "2026-04-02")


def test_window_is_closed_before_the_event_itself():
    assert not is_window_open("Birth", "2026-03-10", "2026-03-09")


def test_non_qualifying_event_has_no_window_and_does_not_raise():
    assert enrolment_window_closes("Bought A Dog", "2026-03-01") is None
    assert not is_window_open("Bought A Dog", "2026-03-01", "2026-03-02")


# --- both gates together -----------------------------------------------------


def test_may_enrol_needs_the_waiting_period_regardless_of_open_enrolment():
    assert not may_enrol("2026-01-01", "Contract", "2026-02-01", open_enrolment=True)


def test_may_enrol_past_the_waiting_period_needs_a_reason_to_join_now():
    served = {"hire_date": "2026-01-01", "employment_class": "Full-Time", "as_of": "2026-06-01"}
    assert not may_enrol(**served)
    assert may_enrol(**served, open_enrolment=True)
    assert may_enrol(**served, life_event="Marriage", event_date="2026-05-20")
    assert not may_enrol(**served, life_event="Marriage", event_date="2026-01-02")


# --- dependant age-out -------------------------------------------------------


def test_age_on_is_birthday_aware():
    assert age_on("2000-06-15", "2026-06-14") == 25
    assert age_on("2000-06-15", "2026-06-15") == 26


def _child(**overrides) -> Dependant:
    base = {
        "dependant_id": "DEP-1",
        "member_id": "PM-1",
        "full_name": "Sam Okonkwo",
        "relationship": "Child",
        "date_of_birth": "2005-04-17",
    }
    return Dependant(**{**base, **overrides})


def test_child_coverage_runs_to_the_end_of_the_age_out_month():
    """Mid-month removal is the rule this is written to avoid."""
    assert coverage_ends_on(_child()) == date(2005 + CHILD_AGE_OUT, 4, 30)


def test_student_status_extends_the_age_out():
    assert coverage_ends_on(_child(full_time_student=True)) == date(
        2005 + STUDENT_AGE_OUT, 4, 30
    )


def test_certified_disability_removes_the_age_out_entirely():
    assert coverage_ends_on(_child(disabled_certified=True)) is None
    assert is_covered(_child(disabled_certified=True), "2099-01-01")


def test_a_spouse_does_not_age_out():
    spouse = _child(relationship="Spouse", date_of_birth="1970-01-01")
    assert coverage_ends_on(spouse) is None
    assert is_covered(spouse, "2099-01-01")


def test_leap_day_birthday_does_not_raise_in_a_non_leap_threshold_year():
    """29 Feb + 21 years lands on a non-leap year; settling on the 28th is
    the deliberate choice over raising one date in four."""
    leapling = _child(date_of_birth="2004-02-29")
    assert coverage_ends_on(leapling) == date(2025, 2, 28)


def test_covered_dependants_filters_and_preserves_order():
    aged_out = _child(dependant_id="DEP-1", date_of_birth="1990-01-01")
    current = _child(dependant_id="DEP-2", date_of_birth="2015-01-01")
    assert covered_dependants([aged_out, current], "2026-01-01") == [current]


# --- relationship rules ------------------------------------------------------


def test_ineligible_relationship_is_rejected_with_a_reason():
    reason = rejection_reason(_child(relationship="Cousin"), [])
    assert reason is not None and "Cousin" in reason


def test_only_one_spouse_per_member():
    existing = [_child(dependant_id="DEP-1", relationship="Spouse")]
    second = _child(dependant_id="DEP-2", relationship="Spouse")
    assert rejection_reason(second, existing) is not None
    # The same record re-submitted is an edit, not a duplicate.
    assert rejection_reason(existing[0], existing) is None


def test_a_second_child_is_fine():
    existing = [_child(dependant_id="DEP-1")]
    assert rejection_reason(_child(dependant_id="DEP-2"), existing) is None

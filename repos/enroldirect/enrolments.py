"""Submitting an enrolment, and the record it leaves behind.

The gate says whether someone may use the channel. This is what they came to
the channel to do: pick a plan and a coverage tier, and be enrolled in it.

Four checks run, and every one of them can refuse:

1. The access gate (`eligibility.check_eligibility`) — reused, not
   reimplemented. An enrolment path with its own copy of the access rules is
   how a channel ends up admitting someone the gate would have turned away.
2. The plan exists on that applicant's contract.
3. The plan is open to the applicant's category — a member-only
   top-up has nothing to attach to for someone holding no coverage.
4. The plan is sold at the requested tier.

Every attempt is recorded whether or not it succeeded, and the record carries
the preference that authorised it. That is the audit trail: months later, "why
was this person enrolled under guest access?" has to be answerable from the
record rather than reconstructed from what the configuration happens to say
today. It is also the count NightlyBatch reconciles on, so a refusal that
never reached a preference is stored with none rather than with a guess.

State is in-process and resettable (`reset()`), matching how the rest of this
app seeds its data — the demo has to run in a locked-down sandbox, so a
datastore is a dependency it cannot take. Nothing here persists across a
restart, and nothing is supposed to.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from repos.enroldirect import benefits, directory
from repos.enroldirect.eligibility import check_eligibility

SUBMITTED = "SUBMITTED"
REFUSED = "REFUSED"

# Refusal codes. Strings rather than an enum so they survive the JSON boundary
# unchanged and a consumer can switch on them without importing this module.
REFUSED_NO_ACCESS = "NO_CHANNEL_ACCESS"
REFUSED_UNKNOWN_PLAN = "PLAN_NOT_ON_CONTRACT"
REFUSED_MEMBER_ONLY = "PLAN_REQUIRES_EXISTING_COVERAGE"
REFUSED_TIER_NOT_OFFERED = "TIER_NOT_OFFERED"


@dataclass(frozen=True)
class EnrolmentRecord:
    """One enrolment attempt, successful or not.

    Refusals are recorded, not discarded. A channel that only logs its
    successes cannot tell you how many people it turned away or why, which is
    exactly the number the prospect classification decision needs.
    """

    reference: str
    applicantId: str
    fullName: str
    contractNumber: str
    planCode: str | None
    planName: str | None
    coverageTier: str | None
    monthlyPremium: float | None
    status: str
    refusalCode: str | None
    category: str
    authorisingPreference: str | None
    submittedAt: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


_records: list[EnrolmentRecord] = []
_counter = itertools.count(1)


def reset() -> None:
    """Clear every recorded enrolment and restart the reference sequence.

    Exposed so a rehearsal can be run twice without restarting the process.
    The counter resets with the records — a reference number that kept
    climbing across a reset would imply history the store no longer holds.
    """
    global _counter
    _records.clear()
    _counter = itertools.count(1)


def all_records() -> list[EnrolmentRecord]:
    """Every attempt, newest first — the order an audit log is read in."""
    return list(reversed(_records))


def _next_reference() -> str:
    return f"ENR-{next(_counter):06d}"


def submit(
    applicant_id: str,
    plan_code: str,
    coverage_tier: str,
) -> EnrolmentRecord:
    """Run the four checks and record the outcome.

    Raises `LookupError` for an unknown applicant or an applicant on a contract
    the directory does not hold — those are caller or data faults, not
    refusals, and recording them as refusals would put a fault in the
    applicant's enrolment history where it would later read as a decision
    about them.
    """
    applicant = directory.get_applicant(applicant_id)
    if applicant is None:
        raise LookupError(f"unknown applicant {applicant_id!r}")
    contract = directory.get_contract(applicant.contractNumber)
    if contract is None:
        raise LookupError(
            f"applicant {applicant_id} references unknown contract "
            f"{applicant.contractNumber}"
        )

    decision = check_eligibility(applicant, contract)
    plan = benefits.get_plan(plan_code)

    def record(
        status: str,
        refusal: str | None,
        reasons: list[str],
        *,
        tier: str | None = None,
        premium: float | None = None,
    ) -> EnrolmentRecord:
        entry = EnrolmentRecord(
            reference=_next_reference(),
            applicantId=applicant.applicantId,
            fullName=applicant.fullName,
            contractNumber=applicant.contractNumber,
            planCode=plan.planCode if plan else plan_code,
            planName=plan.name if plan else None,
            coverageTier=tier,
            monthlyPremium=premium,
            status=status,
            refusalCode=refusal,
            category=applicant.category,
            authorisingPreference=decision.authorisingPreference,
            submittedAt=datetime.now(UTC).isoformat(timespec="seconds"),
            reasons=reasons,
        )
        _records.append(entry)
        return entry

    # 1 — the access gate, reused rather than reimplemented.
    if not decision.granted:
        return record(REFUSED, REFUSED_NO_ACCESS, list(decision.reasons))

    # 2 — the plan is on this contract.
    if plan is None or plan.contractNumber != applicant.contractNumber:
        return record(
            REFUSED,
            REFUSED_UNKNOWN_PLAN,
            [
                f"Plan {plan_code} is not offered under contract "
                f"{applicant.contractNumber}."
            ],
        )

    # 3 — the plan is open to this applicant's category.
    if plan.memberOnly and applicant.category != "MEMBER":
        return record(
            REFUSED,
            REFUSED_MEMBER_ONLY,
            [
                f"'{plan.name}' attaches to existing coverage under the "
                f"contract and is open to members only.",
                f"This applicant is categorised {applicant.category}.",
            ],
        )

    # 4 — the plan is sold at the requested tier.
    premium = plan.premium_for(coverage_tier)
    if premium is None:
        offered = ", ".join(plan.offeredTiers) or "none"
        return record(
            REFUSED,
            REFUSED_TIER_NOT_OFFERED,
            [f"'{plan.name}' is not sold at {coverage_tier} tier (offered: {offered})."],
            tier=coverage_tier,
        )

    return record(
        SUBMITTED,
        None,
        [
            f"Access granted under '{decision.authorisingPreference}'.",
            f"Enrolled in '{plan.name}' at {coverage_tier} tier.",
        ],
        tier=coverage_tier,
        premium=premium,
    )


def summary() -> dict[str, object]:
    """Counts for the dashboard, and the refusal breakdown behind them.

    The refusal codes are reported alongside the totals on purpose. "How many
    enrolments failed" is a number nobody can act on; "how many failed because
    the plan needed existing coverage" is a number that changes a decision.
    """
    submitted = [r for r in _records if r.status == SUBMITTED]
    refused = [r for r in _records if r.status == REFUSED]
    by_code: dict[str, int] = {}
    for entry in refused:
        if entry.refusalCode:
            by_code[entry.refusalCode] = by_code.get(entry.refusalCode, 0) + 1
    return {
        "totalAttempts": len(_records),
        "submitted": len(submitted),
        "refused": len(refused),
        "refusalsByCode": by_code,
        "monthlyPremiumEnrolled": round(
            sum(r.monthlyPremium or 0.0 for r in submitted), 2
        ),
        "byAuthorisingPreference": _count_by_preference(submitted),
    }


def _count_by_preference(entries: list[EnrolmentRecord]) -> dict[str, int]:
    """Successful enrolments per authorising preference.

    This is the figure NightlyBatch reconciles on, and the one a prospect
    reclassification moves volume between without changing the total — see
    `impact.CONSUMERS`.
    """
    counts: dict[str, int] = {}
    for entry in entries:
        key = entry.authorisingPreference or "—"
        counts[key] = counts.get(key, 0) + 1
    return counts

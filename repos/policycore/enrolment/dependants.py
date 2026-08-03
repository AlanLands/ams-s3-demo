"""Who may be covered under a plan member, and until when.

`core/models.py` already says members "optionally cover dependents", but
nothing modelled them — this is that record, plus the two rules that decide
whether it is still in force:

- **Age-out.** A child's coverage ends at the contract's age-out threshold,
  extended while they remain a verified full-time student, and removed
  entirely where a disability was certified before the standard threshold.
- **Relationship.** Only certain relationships may be enrolled at all, and a
  member may hold at most one spouse record.

Age is computed against the contract's own threshold rather than a birthday
anniversary alone, because coverage runs to the end of the month in which
the threshold is reached — dropping someone mid-month is the kind of thing
that generates a complaint call rather than a saving.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Relationships a sponsor's contract permits as dependants. "Spouse" covers
# common-law partners; MapleSure's contracts do not distinguish them.
ELIGIBLE_RELATIONSHIPS: frozenset[str] = frozenset(
    {"Spouse", "Child", "Stepchild", "Adopted Child"}
)

# Relationships limited to one live record per member.
_SINGLETON_RELATIONSHIPS: frozenset[str] = frozenset({"Spouse"})

CHILD_AGE_OUT = 21
STUDENT_AGE_OUT = 26

_CHILD_RELATIONSHIPS: frozenset[str] = frozenset({"Child", "Stepchild", "Adopted Child"})


@dataclass
class Dependant:
    """A person covered under a plan member's enrolment.

    `member_id` ties back to `core.models.PlanMember`. `disabled_certified`
    records that a disability was certified *before* the standard age-out —
    certification afterwards does not reinstate coverage, so this is a fact
    about the past, not a current status flag.
    """

    dependant_id: str
    member_id: str
    full_name: str
    relationship: str  # one of ELIGIBLE_RELATIONSHIPS
    date_of_birth: str  # ISO date string, e.g. "2009-04-17"
    full_time_student: bool = False
    disabled_certified: bool = False


def _parse(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _end_of_month(value: date) -> date:
    """Last day of `value`'s month. Coverage runs to month end, so age-out
    never lands mid-month."""
    if value.month == 12:
        return value.replace(day=31)
    return value.replace(month=value.month + 1, day=1) - timedelta(days=1)


def age_on(date_of_birth: str | date, as_of: str | date) -> int:
    """Whole years old on `as_of`, birthday-aware."""
    born, ref = _parse(date_of_birth), _parse(as_of)
    return ref.year - born.year - ((ref.month, ref.day) < (born.month, born.day))


def age_out_threshold(dependant: Dependant) -> int | None:
    """The age this dependant's coverage ends at, or None if it does not
    age out (a spouse, or a certified disability)."""
    if dependant.relationship not in _CHILD_RELATIONSHIPS:
        return None
    if dependant.disabled_certified:
        return None
    return STUDENT_AGE_OUT if dependant.full_time_student else CHILD_AGE_OUT


def coverage_ends_on(dependant: Dependant) -> date | None:
    """Last day of coverage, or None where coverage does not age out."""
    threshold = age_out_threshold(dependant)
    if threshold is None:
        return None
    born = _parse(dependant.date_of_birth)
    try:
        birthday = born.replace(year=born.year + threshold)
    except ValueError:
        # 29 February: the threshold birthday falls in a non-leap year, so
        # settle on the 28th rather than raising on one date in four years.
        birthday = born.replace(year=born.year + threshold, day=28)
    return _end_of_month(birthday)


def is_covered(dependant: Dependant, as_of: str | date) -> bool:
    """Whether this dependant's coverage is still in force on `as_of`."""
    ends = coverage_ends_on(dependant)
    if ends is None:
        return True
    return _parse(as_of) <= ends


def relationship_is_eligible(relationship: str) -> bool:
    return relationship in ELIGIBLE_RELATIONSHIPS


def rejection_reason(dependant: Dependant, existing: list[Dependant]) -> str | None:
    """Why this dependant cannot be enrolled, or None if they can.

    Returns the reason rather than raising: the enrolment screen shows it to
    the administrator, who is usually one correction away from a valid
    record.
    """
    if not relationship_is_eligible(dependant.relationship):
        return f"{dependant.relationship!r} is not an eligible dependant relationship"
    if dependant.relationship in _SINGLETON_RELATIONSHIPS:
        clash = [
            other
            for other in existing
            if other.member_id == dependant.member_id
            and other.relationship == dependant.relationship
            and other.dependant_id != dependant.dependant_id
        ]
        if clash:
            return f"this member already has a {dependant.relationship.lower()} on record"
    return None


def covered_dependants(dependants: list[Dependant], as_of: str | date) -> list[Dependant]:
    """Those still in force on `as_of`, in the order given."""
    return [dependant for dependant in dependants if is_covered(dependant, as_of)]

"""When an employee may join a group contract.

Two independent gates decide that, and both have to be open:

1. A **probationary waiting period** runs from the hire date. Its length is
   agreed per employment class at contract inception — full-time staff
   typically wait less than contract staff, because the sponsor is carrying
   more turnover risk on the latter.
2. Outside the annual open-enrolment window, joining needs a **qualifying
   life event**, and each event opens a window of its own that closes
   whether or not the member acted on it.

Both are expressed as data (`WAITING_PERIOD_DAYS`, `QUALIFYING_EVENTS`)
rather than branching, so a sponsor-specific variation is a table edit.

No contribution arithmetic lives here — eligibility answers "may they join",
not "what does it cost".
"""

from __future__ import annotations

from datetime import date, timedelta

# Probationary period by employment class, in days, as agreed at contract
# inception. A class absent from this table has no probationary period —
# that is the sponsor having negotiated immediate coverage, not a lookup
# failure, so it must not raise.
WAITING_PERIOD_DAYS: dict[str, int] = {
    "Full-Time": 30,
    "Part-Time": 90,
    "Contract": 180,
    "Seasonal": 180,
    "Executive": 0,
}

# How long each qualifying life event keeps enrolment open, in days from the
# event. These are the sponsor-agreed windows, not statutory minimums.
QUALIFYING_EVENTS: dict[str, int] = {
    "Marriage": 31,
    "Birth": 31,
    "Adoption": 31,
    "Divorce": 31,
    "Spousal Coverage Loss": 60,
    "Relocation": 31,
}

_DEFAULT_WAITING_PERIOD_DAYS = 0


def _parse(value: str | date) -> date:
    """Accept either an ISO date string (this app's storage convention) or a
    `date`, so callers holding a record field don't each re-parse."""
    return value if isinstance(value, date) else date.fromisoformat(value)


def waiting_period_days(employment_class: str) -> int:
    """Probationary days for an employment class.

    An unrecognised class returns the no-waiting-period default rather than
    raising: this table is sponsor-negotiated data, and a class nobody
    listed should not block an enrolment that is otherwise in order.
    """
    return WAITING_PERIOD_DAYS.get(employment_class, _DEFAULT_WAITING_PERIOD_DAYS)


def eligibility_date(hire_date: str | date, employment_class: str) -> date:
    """The first day this employee may be covered."""
    return _parse(hire_date) + timedelta(days=waiting_period_days(employment_class))


def has_served_waiting_period(
    hire_date: str | date, employment_class: str, as_of: str | date
) -> bool:
    """Whether the probationary period is behind them on `as_of`.

    Inclusive of the eligibility date itself — coverage starts *on* it, not
    the day after.
    """
    return _parse(as_of) >= eligibility_date(hire_date, employment_class)


def enrolment_window_days(life_event: str) -> int | None:
    """Days a life event keeps enrolment open, or None if it is not a
    qualifying event under this contract."""
    return QUALIFYING_EVENTS.get(life_event)


def enrolment_window_closes(life_event: str, event_date: str | date) -> date | None:
    """Last day enrolment stays open for this event, or None if the event
    does not qualify."""
    days = enrolment_window_days(life_event)
    if days is None:
        return None
    return _parse(event_date) + timedelta(days=days)


def is_window_open(life_event: str, event_date: str | date, as_of: str | date) -> bool:
    """Whether `as_of` still falls inside the event's enrolment window.

    A non-qualifying event has no window, so this is False rather than an
    error — "you cannot enrol on the strength of that" is an answer.
    """
    closes = enrolment_window_closes(life_event, event_date)
    if closes is None:
        return False
    return _parse(event_date) <= _parse(as_of) <= closes


def may_enrol(
    hire_date: str | date,
    employment_class: str,
    as_of: str | date,
    *,
    life_event: str | None = None,
    event_date: str | date | None = None,
    open_enrolment: bool = False,
) -> bool:
    """Both gates, together — the question the enrolment screen actually asks.

    The waiting period is unconditional. Past it, the member still needs a
    reason to be joining *now*: either open enrolment is running, or a
    qualifying life event's window is open.
    """
    if not has_served_waiting_period(hire_date, employment_class, as_of):
        return False
    if open_enrolment:
        return True
    if life_event is None or event_date is None:
        return False
    return is_window_open(life_event, event_date, as_of)

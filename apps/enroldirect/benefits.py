"""The benefit plans an applicant can actually enrol in, once the gate lets
them through.

The access gate in `eligibility.py` answers whether someone may use the
self-serve channel at all. It does not answer what they will find when they
get there, and those are different questions with different answers — which
matters more than it sounds.

`memberOnly` is why. Some plans are open only to people already holding
coverage under the contract: a top-up on an existing benefit has nothing to
attach to otherwise. So the prospect classification bites **twice**. Once at
the gate, deciding whether they get in at all, and again here, deciding how
much of the catalogue they can see once they do. An analysis that only counted
the first would understate the difference between the two policies, and the
second effect runs the opposite way from the first — treating prospects as
guests admits fewer of them, but the ones it admits reach a smaller catalogue
too.

Premiums are per-tier monthly amounts in CAD. They are synthetic and round;
nothing here is a rate table anyone should quote from.
"""

from __future__ import annotations

from dataclasses import dataclass

# Coverage tiers, cheapest first. Ordering is load-bearing for display and for
# the "cheapest tier" default on the enrolment form, so it lives here rather
# than being re-sorted by each caller.
SINGLE = "Single"
COUPLE = "Couple"
FAMILY = "Family"

COVERAGE_TIERS: tuple[str, ...] = (SINGLE, COUPLE, FAMILY)


@dataclass(frozen=True)
class BenefitPlan:
    """One plan offered under one group contract.

    `memberOnly` marks a plan that requires existing coverage under the
    contract to attach to. A guest — or a prospect being treated as one —
    cannot enrol in it, and the enrolment attempt has to say why rather than
    hiding the plan, because "I can see it but cannot pick it" generates a
    support call that "it is not listed" does not answer either.
    """

    planCode: str
    contractNumber: str
    name: str
    category: str  # "Health" | "Dental" | "Vision" | "Life" | "Disability"
    memberOnly: bool
    monthlyPremium: dict[str, float]

    def premium_for(self, tier: str) -> float | None:
        """The monthly premium for a tier, or None if the plan does not offer it.

        Not every plan is sold at every tier — single-life products have no
        family rate — so an absent tier is a real configuration, not a lookup
        failure, and returning None lets the caller say so precisely.
        """
        return self.monthlyPremium.get(tier)

    @property
    def offeredTiers(self) -> tuple[str, ...]:
        """Tiers this plan is sold at, in the canonical cheapest-first order."""
        return tuple(t for t in COVERAGE_TIERS if t in self.monthlyPremium)


PLANS: list[BenefitPlan] = [
    # MS-2001 — Northwind Logistics. Full catalogue, both preferences enabled.
    BenefitPlan(
        planCode="PL-1001",
        contractNumber="MS-2001",
        name="Extended Health Care",
        category="Health",
        memberOnly=False,
        monthlyPremium={SINGLE: 82.0, COUPLE: 148.0, FAMILY: 214.0},
    ),
    BenefitPlan(
        planCode="PL-1002",
        contractNumber="MS-2001",
        name="Dental Care",
        category="Dental",
        memberOnly=False,
        monthlyPremium={SINGLE: 46.0, COUPLE: 84.0, FAMILY: 122.0},
    ),
    BenefitPlan(
        planCode="PL-1003",
        contractNumber="MS-2001",
        name="Health Care Spending Top-Up",
        category="Health",
        memberOnly=True,  # attaches to an existing health benefit
        monthlyPremium={SINGLE: 25.0, FAMILY: 60.0},
    ),
    # MS-2002 — Cedarline. Member access only, and a member-only top-up, so a
    # prospect admitted here as a member reaches the whole catalogue.
    BenefitPlan(
        planCode="PL-2001",
        contractNumber="MS-2002",
        name="Extended Health Care",
        category="Health",
        memberOnly=False,
        monthlyPremium={SINGLE: 91.0, COUPLE: 164.0, FAMILY: 238.0},
    ),
    BenefitPlan(
        planCode="PL-2002",
        contractNumber="MS-2002",
        name="Vision Care",
        category="Vision",
        memberOnly=True,
        monthlyPremium={SINGLE: 18.0, FAMILY: 41.0},
    ),
    # MS-2003 — Quill & Fenwick. Guest access only.
    BenefitPlan(
        planCode="PL-3001",
        contractNumber="MS-2003",
        name="Extended Health Care",
        category="Health",
        memberOnly=False,
        monthlyPremium={SINGLE: 77.0, COUPLE: 139.0, FAMILY: 201.0},
    ),
    BenefitPlan(
        planCode="PL-3002",
        contractNumber="MS-2003",
        name="Group Life — 1x Salary",
        category="Life",
        memberOnly=False,
        monthlyPremium={SINGLE: 12.0},
    ),
    BenefitPlan(
        planCode="PL-3003",
        contractNumber="MS-2003",
        name="Long-Term Disability",
        category="Disability",
        memberOnly=True,
        monthlyPremium={SINGLE: 34.0},
    ),
    # MS-2004 — Talus. Plans exist, but no online enrolment preference is
    # enabled, so nobody reaches them through this channel. That separation is
    # deliberate: a plan catalogue and a channel are configured independently,
    # and conflating them would hide the case from the analysis.
    BenefitPlan(
        planCode="PL-4001",
        contractNumber="MS-2004",
        name="Extended Health Care",
        category="Health",
        memberOnly=False,
        monthlyPremium={SINGLE: 88.0, COUPLE: 159.0, FAMILY: 230.0},
    ),
    # MS-2005 — Harbourline, lapsed contract.
    BenefitPlan(
        planCode="PL-5001",
        contractNumber="MS-2005",
        name="Extended Health Care",
        category="Health",
        memberOnly=False,
        monthlyPremium={SINGLE: 79.0, COUPLE: 143.0, FAMILY: 207.0},
    ),
]

PLANS_BY_CODE: dict[str, BenefitPlan] = {p.planCode: p for p in PLANS}


def get_plan(plan_code: str) -> BenefitPlan | None:
    return PLANS_BY_CODE.get(plan_code)


def plans_for_contract(contract_number: str) -> list[BenefitPlan]:
    return [p for p in PLANS if p.contractNumber == contract_number]


def plans_open_to(contract_number: str, effective_category: str) -> list[BenefitPlan]:
    """The plans a given effective category may enrol in on this contract.

    `effective_category` is MEMBER or GUEST — the category the applicant is
    being *treated as*, which for a prospect depends on the policy in force.
    Resolving that upstream and passing the result keeps the prospect question
    in one place instead of leaking a third branch into the catalogue.
    """
    if effective_category == "MEMBER":
        return plans_for_contract(contract_number)
    return [p for p in plans_for_contract(contract_number) if not p.memberOnly]

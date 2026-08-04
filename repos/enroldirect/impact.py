"""What changes if prospects are classified one way rather than the other.

This module is the analysis surface the enrolment access question needed
before anyone changed the gate. It exists because the honest answer to "should
prospects be treated as members or as guests?" was not available from either
option's description — it depended on how the preferences were actually
configured across the book, and nobody had counted.

So it counts. `prospect_impact()` evaluates the entire seeded directory under
both options and reports where they disagree, which applicants those are, and
on which contracts. The recommendation it returns carries the evidence that
produced it and an explicit statement of what that evidence does *not*
establish.

It evaluates the options rather than executing them, because the gate does not
implement either one — a prospect resolves to no preference and is refused
(`eligibility.preference_for_category`). `_would_grant` therefore models the
gate's rules against contract configuration instead of calling it. That
duplication is the cost of analysing a change before making it, and it is
pinned rather than trusted: the regression suite asserts `_would_grant` agrees
with `check_eligibility` for the two categories the gate *does* classify, so
the model cannot drift away from the rules it claims to mirror.

That last part is deliberate, and it matches `s3_enhancement/release.py`'s
"Not evidenced by this release" block. An analysis that reports only the
numbers supporting its recommendation is advocacy. The consequences that are
real but unquantifiable from configuration data — regulatory exposure, support
load, what a prospect believes they signed up for — are named rather than
silently dropped, because they are the ones most likely to decide the answer.

Nothing in here calls a model. Every figure is a pure function of the seeded
directory and the eligibility rules, so it cannot be confidently wrong the way
generated prose can.
"""

from __future__ import annotations

from dataclasses import dataclass

from repos.enroldirect import benefits, directory
from repos.enroldirect.applicants import ALL_CATEGORIES, CATEGORY_DESCRIPTION, PROSPECT
from repos.enroldirect.eligibility import ACTIVE
from repos.enroldirect.preferences import (
    ALL_PREFERENCES,
    GUEST_ACCESS,
    MEMBER_ACCESS,
    PREFERENCE_PURPOSE,
)

# The two ways a prospect could be classified, named here because they are
# this analysis's subject and nothing else in the app knows about them. They
# are the only two options: a third would mean a new preference in PolicyCore,
# which is a far larger change than the one being sized. Their values are also
# the effective category each option would produce, which is what
# `benefits.plans_open_to` filters on.
TREAT_AS_MEMBER = "MEMBER"
TREAT_AS_GUEST = "GUEST"

PROSPECT_OPTIONS: tuple[str, ...] = (TREAT_AS_MEMBER, TREAT_AS_GUEST)

# The option this analysis recommends. A constant rather than something
# derived from the counts: a recommendation that flipped with the seed data
# would be a fitting exercise, not a policy. What the counts do is size its
# cost, which `_recommendation` reports whether or not it flatters the answer.
RECOMMENDED_OPTION = TREAT_AS_GUEST


@dataclass(frozen=True)
class Consumer:
    """One system in the estate that reads or writes the access preferences.

    `relation` is "upstream" for systems that decide what the preferences say,
    "enforcing" for the one that gates on them, and "downstream" for systems
    whose behaviour changes because of a decision already made. Recording the
    direction is what turns a list of application names into a dependency map:
    a downstream consumer cannot be consulted about a change, only notified of
    one, and those need different conversations.

    `changeRequired` is a second, independent axis and the more useful one:
    being affected is not the same as having work to do. A system that reads
    the authorising preference as a *value* keeps working unchanged when a
    population is reclassified — its numbers move between buckets it already
    has. A system that has to *author behaviour* per preference has a case it
    has never handled, and that is a code change someone must make.

    Collapsing the two is how a one-repo change turns into a five-team
    programme on a slide. `changeRationale` carries the reason either way, so a
    "no" is auditable rather than an omission.
    """

    application: str
    relation: str
    owningTeam: str
    purpose: str
    accessBehaviour: str
    changeRequired: bool
    changeRationale: str


# The estate as it consumes these preferences. Declared rather than
# discovered: EnrolDirect has no visibility into the other systems' code, so
# claiming to have derived this by inspection would be a lie. It is the
# analysis's stated input, and it is wrong the moment a new consumer appears
# without this table being updated — which is why the risk list says so.
CONSUMERS: tuple[Consumer, ...] = (
    Consumer(
        application="PolicyCore",
        relation="upstream",
        owningTeam="App Support — PolicyCore",
        purpose="Holds the contract record and the preferences enabled on it.",
        accessBehaviour=(
            "Plan administrators set the preferences per contract at inception "
            "and on amendment. Source of truth; changes here propagate."
        ),
        changeRequired=False,
        changeRationale=(
            "Upstream of the decision. The two preferences keep their present "
            "meaning and no new one is stored, so nothing it holds changes. "
            "Adding a per-sponsor prospect policy later would change that, "
            "which is why the user story rules that out explicitly."
        ),
    ),
    Consumer(
        application="EnrolDirect",
        relation="enforcing",
        owningTeam="App Support — PolicyCore",
        purpose="Gates the self-serve enrolment channel on the preferences.",
        accessBehaviour=(
            "Reads the contract's enabled preferences and grants or denies each "
            "enrolment attempt. The only system that turns a preference into an "
            "access outcome."
        ),
        changeRequired=True,
        changeRationale=(
            "This system. The change under analysis is its own — it is listed "
            "for completeness of the map, not as another team's work."
        ),
    ),
    Consumer(
        application="DocumentHub",
        relation="downstream",
        owningTeam="App Support — DocumentHub",
        purpose="Produces the enrolment confirmation pack.",
        accessBehaviour=(
            "Selects the wording and the enclosures from the preference that "
            "authorised the enrolment, so a prospect admitted as a guest "
            "receives guest wording."
        ),
        changeRequired=True,
        changeRationale=(
            "The one consumer that has to author behaviour rather than carry a "
            "value. Its wording is written per authorising preference, and a "
            "prospect admitted under guest access is a recipient neither of "
            "the existing packs was written for: the guest pack addresses "
            "someone with no place on the roster, which a prospect has. That "
            "is a new case, and a new case is a code change."
        ),
    ),
    Consumer(
        application="NightlyBatch",
        relation="downstream",
        owningTeam="Batch Ops",
        purpose="Reconciles the day's enrolments to the plan administration ledger.",
        accessBehaviour=(
            "Counts enrolments by authorising preference. Reclassifying a "
            "population moves volume between its member and guest totals "
            "without changing the overall figure."
        ),
        changeRequired=False,
        changeRationale=(
            "Affected, but with nothing to change. It aggregates by whatever "
            "preference the record carries, and both buckets already exist. "
            "Its member and guest totals move; the reconciliation it performs "
            "and the overall figure it reconciles to do not. Worth a heads-up "
            "to Batch Ops before the first run, not a ticket."
        ),
    ),
    Consumer(
        application="IntegrationBridge",
        relation="downstream",
        owningTeam="Integration Support",
        purpose="Publishes enrolment events to subscribing systems.",
        accessBehaviour=(
            "Carries the authorising preference on each event. Subscribers "
            "filtering on it will see a reclassified population appear on a "
            "different stream than before."
        ),
        changeRequired=False,
        changeRationale=(
            "Affected, but with nothing to change. It passes the authorising "
            "preference through as data on an existing field; no new value "
            "appears and no schema moves. The risk it carries is a "
            "subscriber's, and subscribers are the declared-list gap named in "
            "`UNQUANTIFIED_CONSEQUENCES` — not work for this team."
        ),
    ),
)

# Consequences that are real but not computable from configuration data. Kept
# beside the numbers on purpose — see this module's docstring.
UNQUANTIFIED_CONSEQUENCES: tuple[str, ...] = (
    "Regulatory position. Whether a prospect admitted under member access has "
    "been represented as a plan member is a compliance question, and no count "
    "of contracts answers it.",
    "Support load. Denied prospects contact the service desk; admitted "
    "prospects reaching member screens with no coverage to display also "
    "contact the service desk. The seed cannot say which is the larger volume.",
    "Downstream subscriber behaviour. The consumers above are a declared list, "
    "not a discovered one. A subscriber filtering on the authorising "
    "preference that nobody recorded here will change behaviour unannounced.",
    "Prospect expectation. What the sponsor told these people they would be "
    "able to do is not in the contract record.",
)

# Risks the analysis raises regardless of which policy is chosen.
STANDING_RISKS: tuple[str, ...] = (
    "A contract carrying a preference this app does not recognise is treated "
    "as not having it, which denies rather than grants — safe, but silent. See "
    "`preferences.unknown_preferences`.",
    "The contract gate runs before the preference gate, so a lapsed contract's "
    "stale preferences cannot grant access. Reordering those two gates would "
    "reintroduce that hole without failing any category-level test.",
    "Prospects are refused at the gate today because no preference resolves "
    "for them. That is the current behaviour, not a decision — every day it "
    "stands is a day the narrower option is in force by default rather than "
    "by choice.",
    "Whichever option is adopted would be a single value for the whole book. "
    "Any per-sponsor variation would need it to become contract data, which is "
    "a PolicyCore change, not an EnrolDirect one.",
)


def preference_usage() -> list[dict[str, object]]:
    """How each preference is actually configured across the seeded book.

    The question the analysis opened with — which contracts rely on which
    preference — answered by counting rather than by asking the teams.
    """
    usage: list[dict[str, object]] = []
    for preference in ALL_PREFERENCES:
        enabled_on = [
            c.contractNumber
            for c in directory.CONTRACTS
            if preference in c.enabledPreferences
        ]
        usage.append(
            {
                "preference": preference,
                "purpose": PREFERENCE_PURPOSE[preference],
                "enabledOnContracts": enabled_on,
                "contractCount": len(enabled_on),
            }
        )
    return usage


def category_population() -> list[dict[str, object]]:
    """Headcount per applicant category, with the unclassified one named."""
    return [
        {
            "category": category,
            "description": CATEGORY_DESCRIPTION[category],
            "applicantCount": sum(
                1 for a in directory.APPLICANTS if a.category == category
            ),
            "classifiedByAPreference": category != PROSPECT,
        }
        for category in ALL_CATEGORIES
    ]


def required_preference_for(option: str) -> str:
    """The preference a prospect would be checked against under one option."""
    return MEMBER_ACCESS if option == TREAT_AS_MEMBER else GUEST_ACCESS


def _would_grant(contract: directory.GroupContract, option: str) -> bool:
    """Whether the gate would admit a prospect on this contract under `option`.

    Models `check_eligibility`'s first two gates in the order the gate runs
    them: the contract has to be active before its preferences are read at all,
    because a lapsed contract keeps whatever it was configured with. Reversing
    those two here would overstate both options equally and hide it.
    """
    if contract.status != ACTIVE:
        return False
    return required_preference_for(option) in contract.enabledPreferences


def _decide_all(option: str) -> dict[str, bool]:
    """Every prospect's outcome under one option, keyed by applicant id."""
    outcomes: dict[str, bool] = {}
    for applicant in directory.prospects():
        contract = directory.get_contract(applicant.contractNumber)
        if contract is None:
            # An applicant on a contract the directory does not hold is an
            # upstream integrity fault. Recording it as a denial would bury it
            # in the totals as though it were an outcome of the option.
            raise ValueError(
                f"applicant {applicant.applicantId} references unknown contract "
                f"{applicant.contractNumber}"
            )
        outcomes[applicant.applicantId] = _would_grant(contract, option)
    return outcomes


def catalogue_reach() -> dict[str, object]:
    """How much of the benefit catalogue each policy opens to prospects.

    The second place the classification would bite, and it runs the *opposite*
    way from the gate. Treating prospects as guests admits fewer of them, but
    each one it admits also reaches a smaller catalogue, because member-only plans
    attach to coverage a prospect does not hold. Reporting only the gate counts
    would understate the gap between the two policies.

    Reach is counted only for prospects the gate would admit under that option
    — a plan you cannot reach because you were refused at the door is already
    counted as a denial, and counting it twice would inflate the difference
    this analysis exists to size honestly.
    """
    per_option: dict[str, dict[str, int]] = {}
    for option in PROSPECT_OPTIONS:
        admitted = 0
        reachable = 0
        member_only_blocked = 0
        for applicant in directory.prospects():
            contract = directory.get_contract(applicant.contractNumber)
            if contract is None or not _would_grant(contract, option):
                continue
            admitted += 1
            # The option value is the effective category it would produce.
            on_contract = benefits.plans_for_contract(applicant.contractNumber)
            open_to_them = benefits.plans_open_to(applicant.contractNumber, option)
            reachable += len(open_to_them)
            member_only_blocked += len(on_contract) - len(open_to_them)
        per_option[option] = {
            "prospectsAdmitted": admitted,
            "planOpeningsReachable": reachable,
            "planOpeningsBlockedAsMemberOnly": member_only_blocked,
        }
    return per_option


def document_impact() -> dict[str, object]:
    """What each option does to the confirmation pack a prospect receives.

    The third place the classification bites, and the first one that lands on
    another team. The gate decides who gets in; the catalogue decides what they
    can reach; this decides what MapleSure then says to them in writing.

    It is computable from data already on hand, which is why it is here rather
    than in the model's prose. DocumentHub words a pack from the *authorising
    preference*, and a prospect is by definition on the sponsor's roster
    (`applicants.CATEGORY_DESCRIPTION[PROSPECT]`). So every prospect admitted
    under the Guest preference is a rostered person carrying guest
    authorisation — a combination DocumentHub has never received, because the
    gate refuses prospects today and the two facts have therefore always moved
    together. Counting the admissions counts the packs.

    What that produces is not an error: DocumentHub selects the guest pack,
    which states that MapleSure holds no member record for the recipient and
    encloses an identity confirmation form. Sent to someone the sponsor lists
    on its own roster, both are false, and withdrawing the request costs plan
    administration a telephone call each.

    Treating prospects as members has the mirror problem and it is reported
    too: the member pack refers to existing coverage, and a prospect holds
    none. Reporting only the recommended option's cost would be advocacy — see
    this module's docstring.

    Nothing here reaches DocumentHub to check. `wordedFor` is what this
    analysis asserts a pack would be selected on, from a documented
    integration contract, and it is named as an assumption rather than as a
    finding.
    """
    per_option: dict[str, dict[str, object]] = {}
    for option in PROSPECT_OPTIONS:
        admitted = sum(1 for granted in _decide_all(option).values() if granted)
        if option == TREAT_AS_GUEST:
            consequence = (
                "The guest pack states that no member record is held and "
                "encloses an identity confirmation form. Every recipient is on "
                "the sponsor's roster, so both are false and the form has to be "
                "withdrawn by hand."
            )
        else:
            consequence = (
                "The member pack refers to coverage the recipient already "
                "holds under the contract. A prospect holds none, so the "
                "paragraph describes benefits that do not exist."
            )
        per_option[option] = {
            "packsRequiringNewWording": admitted,
            "wordedFor": required_preference_for(option),
            "consequenceIfUnchanged": consequence,
        }

    return {
        "consumer": "DocumentHub",
        "owningTeam": "App Support — DocumentHub",
        "whyAffected": (
            "It selects confirmation-pack wording from the authorising "
            "preference alone. Prospects are on the roster, so admitting them "
            "under either preference produces a recipient neither existing "
            "pack was written for."
        ),
        "perOption": per_option,
        "recommendedOption": RECOMMENDED_OPTION,
        "packsUnderRecommendedOption": per_option[RECOMMENDED_OPTION][
            "packsRequiringNewWording"
        ],
        "changeRequiredOf": (
            "A third worded pack and enclosure set for a rostered applicant "
            "admitted under guest access. It is DocumentHub's change to make, "
            "not this app's — nothing here can word a document."
        ),
        "assumption": (
            "That DocumentHub still selects wording on the authorising "
            "preference alone. This app has no visibility into its code; the "
            "rule is taken from the integration contract, and it is the one "
            "thing here that could be out of date without anyone noticing."
        ),
    }


def prospect_impact() -> dict[str, object]:
    """Compare treating prospects as members against treating them as guests.

    Returns both policies' grant counts, the applicants they disagree about,
    and a recommendation stating the evidence behind it and the ground it does
    not cover.
    """
    as_member = _decide_all(TREAT_AS_MEMBER)
    as_guest = _decide_all(TREAT_AS_GUEST)

    disagreements = []
    for applicant in directory.prospects():
        member_granted = as_member[applicant.applicantId]
        guest_granted = as_guest[applicant.applicantId]
        if member_granted == guest_granted:
            continue
        contract = directory.get_contract(applicant.contractNumber)
        assert contract is not None  # _decide_all already raised otherwise
        disagreements.append(
            {
                "applicantId": applicant.applicantId,
                "contractNumber": applicant.contractNumber,
                "sponsorName": contract.sponsorName,
                "enabledPreferences": list(contract.enabledPreferences),
                "grantedIfTreatedAsMember": member_granted,
                "grantedIfTreatedAsGuest": guest_granted,
                "grantedOnlyBy": TREAT_AS_MEMBER if member_granted else TREAT_AS_GUEST,
            }
        )

    total = len(directory.prospects())
    member_grants = sum(1 for granted in as_member.values() if granted)
    guest_grants = sum(1 for granted in as_guest.values() if granted)

    return {
        "prospectCount": total,
        "options": [
            {
                "option": TREAT_AS_MEMBER,
                "requiresPreference": MEMBER_ACCESS,
                "prospectsGranted": member_grants,
                "prospectsDenied": total - member_grants,
                "impacts": [
                    "Immediate access to the member-facing enrolment journey.",
                    "Member-only screens are exposed to people holding no coverage.",
                    "Confirmation packs and enrolment events carry member wording.",
                ],
            },
            {
                "option": TREAT_AS_GUEST,
                "requiresPreference": GUEST_ACCESS,
                "prospectsGranted": guest_grants,
                "prospectsDenied": total - guest_grants,
                "impacts": [
                    "Consistent with how the estate already handles people "
                    "holding no active benefit.",
                    "Narrower access; some member-facing functions stay closed.",
                    "Prospects on member-only contracts are denied entirely.",
                ],
            },
        ],
        "disagreements": disagreements,
        "disagreementCount": len(disagreements),
        "catalogueReach": catalogue_reach(),
        # Folded into the main analysis rather than served on its own endpoint:
        # a downstream consequence reported separately is a consequence a
        # reader can finish the analysis without having seen.
        "documentImpact": document_impact(),
        "recommendation": _recommendation(member_grants, guest_grants, disagreements),
        "notEvidencedByThisAnalysis": list(UNQUANTIFIED_CONSEQUENCES),
        "standingRisks": list(STANDING_RISKS),
    }


def _recommendation(
    member_grants: int, guest_grants: int, disagreements: list[dict[str, object]]
) -> dict[str, object]:
    """State the recommended option and the reasoning that produced it.

    The recommendation is `RECOMMENDED_OPTION`; this function explains it
    rather than re-deriving it (see that constant). What the counts do is size
    its cost, and that is reported whether or not it flatters the answer.
    """
    denied_by_recommended = [
        d for d in disagreements if d["grantedOnlyBy"] != RECOMMENDED_OPTION
    ]
    return {
        "option": RECOMMENDED_OPTION,
        "implemented": False,
        "rationale": (
            "Guest is the narrower grant. A prospect holds no active benefit, "
            "so the member-facing screens have nothing of theirs to show, and "
            "widening access later is easier to justify than withdrawing it. "
            "It also matches how the rest of the estate already treats people "
            "with no coverage under the contract."
        ),
        "costOfThisChoice": (
            f"{len(denied_by_recommended)} of the seeded prospects would be denied "
            f"under the recommended option but granted under the alternative "
            f"— all of them on contracts whose sponsor enabled member access "
            f"only. Those sponsors have to enable guest access for their "
            f"prospects to self-serve."
        ),
        "grantCounts": {
            TREAT_AS_MEMBER: member_grants,
            TREAT_AS_GUEST: guest_grants,
        },
        "decisionOwner": (
            "Plan administration, jointly with compliance. This analysis sizes "
            "the options; it does not have standing to choose between them."
        ),
    }


def consumers() -> list[dict[str, object]]:
    """The declared application inventory, as plain dicts for the API."""
    return [
        {
            "application": c.application,
            "relation": c.relation,
            "owningTeam": c.owningTeam,
            "purpose": c.purpose,
            "accessBehaviour": c.accessBehaviour,
            "changeRequired": c.changeRequired,
            "changeRationale": c.changeRationale,
        }
        for c in CONSUMERS
    ]


def other_teams_requiring_change() -> list[dict[str, object]]:
    """The consumers that owe someone else work, which is a shorter list.

    The cross-team check reads this rather than `consumers()`. The distinction
    it draws is the whole point (see `Consumer.changeRequired`): every entry
    here is a ticket another team has to accept, so an entry added carelessly
    costs a real conversation with a real team.

    EnrolDirect is excluded because it is the system the change is *in* — a
    change cannot be cross-team with itself, and including it would put the
    story's own work on another team's board.
    """
    return [
        entry
        for entry in consumers()
        if entry["changeRequired"] and entry["application"] != "EnrolDirect"
    ]

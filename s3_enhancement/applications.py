"""Application context — the ServiceNow CI a ticket names, resolved to the
Jira project, repo, and component team that own it.

S3's existing routing (`repo_match.py`) asks an LLM to guess the target repo
from CR free-text against the caller's GitLab project list. That is the right
answer when nothing better exists, but it is a guess, and it runs on every
ticket — including the ones where the client's CMDB already states the answer.

This module is the deterministic tier that runs first. A ticket carrying a
Configuration Item ("ClaimsPortal", "Claims Portal", "claims-portal") resolves
by table lookup to exactly one `Application`: its Jira project key, its repo,
its component team, and its tech stack. No model call, no confidence score,
nothing to confirm. `repo_match` stays as the fallback for tickets that arrive
with no CI or a CI this registry has never heard of.

Two things this deliberately encodes:

- **Not every routable application is automatable.** `BILLING_GATEWAY` and
  `DOCUMENT_HUB` are real routing destinations with real owning teams, and no
  registered S3 target. Routing them succeeds and reports
  `automation_available=False` — the ticket reaches the correct team without
  the console pretending it can generate code for a repo it does not have.
  Answering "which team owns this" and "can we act on it" as two separate
  questions is the point; conflating them is how automation gets pointed at
  the wrong repo.

- **A CI identifies an application, not a change.** `apps/policycore/` hosts two
  registered targets (CR-2026-041 and CR-2026-042); both belong to the one
  `POLICY_CORE` application. So routing narrows a ticket to an application and
  its candidate targets, and the CR text picks which change within it — a CI
  can never select a CR, because ServiceNow does not know CRs exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from common.constants import ASSIGNMENT_GROUPS

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Application:
    """One application in the client's estate, as ServiceNow would describe it.

    `ci_names` holds every CI/CMDB spelling that should resolve here — real
    CMDBs are not consistent about spacing or casing, and a routing table that
    only matches one exact string silently falls through to the LLM tier for
    the other spellings, which looks like the deterministic path "not working".
    Matching is normalization-based (see `_normalize`), so listing the common
    variants is belt-and-braces, not the mechanism.
    """

    app_id: str
    display_name: str
    business_service: str
    ci_names: tuple[str, ...]
    jira_project_key: str
    component_team: str  # must be one of common.constants.ASSIGNMENT_GROUPS
    tech_stack: str
    # Repo the application's code lives in, relative to the repo root. Empty
    # for applications this console can route to but not act on.
    repo_path: str = ""

    @property
    def automation_available(self) -> bool:
        """Whether S3 can generate code for this application, as opposed to
        merely routing a ticket to the team that owns it."""
        return bool(self.repo_path)

    @property
    def repo_root(self) -> Path | None:
        return REPO_ROOT / self.repo_path if self.repo_path else None


_REGISTRY: dict[str, Application] = {}
_BY_CI: dict[str, str] = {}  # normalized ci name -> app_id


def _normalize(value: str) -> str:
    """Fold a CI/business-service string to its comparison key.

    Case, spaces, hyphens and underscores all vary between CMDB entries for
    what is the same application ("ClaimsPortal", "Claims Portal",
    "claims-portal"), and none of that variation carries meaning.
    """
    return "".join(ch for ch in value.lower() if ch.isalnum())


def register_application(application: Application) -> None:
    """Register an application. Raises on a duplicate app_id, a CI name already
    claimed by another application, or a component team that isn't a real
    assignment group — a routing table that quietly points at a team nobody is
    on is worse than one that fails at import.
    """
    if application.app_id in _REGISTRY:
        raise ValueError(f"app_id {application.app_id!r} is already registered")
    if application.component_team not in ASSIGNMENT_GROUPS:
        raise ValueError(
            f"component_team {application.component_team!r} is not a known "
            f"assignment group (see common/constants.py)"
        )
    for ci_name in application.ci_names:
        key = _normalize(ci_name)
        if key in _BY_CI and _BY_CI[key] != application.app_id:
            raise ValueError(
                f"CI name {ci_name!r} is already routed to application "
                f"{_BY_CI[key]!r}"
            )
    _REGISTRY[application.app_id] = application
    for ci_name in application.ci_names:
        _BY_CI[_normalize(ci_name)] = application.app_id


POLICY_CORE_ID = "policycore"
CLAIMS_PORTAL_ID = "claimsportal"

POLICY_CORE = Application(
    app_id=POLICY_CORE_ID,
    display_name="PolicyCore",
    business_service="Policy Administration",
    ci_names=(
        "PolicyCore",
        "Policy Core",
        "PolicyCore Web",
        "PolicyCore API",
        "MapleSure Policy Admin",
    ),
    jira_project_key="AMS",
    component_team="App Support — PolicyCore",
    tech_stack="Python / FastAPI + SQLite",
    repo_path="apps/policycore",
)
register_application(POLICY_CORE)

CLAIMS_PORTAL = Application(
    app_id=CLAIMS_PORTAL_ID,
    display_name="ClaimsPortal",
    business_service="Claims Management",
    ci_names=(
        "ClaimsPortal",
        "Claims Portal",
        "ClaimsPortal API",
        "Claims Service",
    ),
    jira_project_key="AMS",
    component_team="App Support — ClaimsPortal",
    tech_stack="Java 17 / Spring Boot",
    repo_path="apps/claimsportal",
)
register_application(CLAIMS_PORTAL)

# Routable, not automatable — see module docstring. These exist so the routing
# beat can demonstrate the boundary: the ticket reaches the right team, and the
# console says plainly that it has no repo to generate against.
BILLING_GATEWAY = Application(
    app_id="billinggateway",
    display_name="BillingGateway",
    business_service="Premium Billing",
    ci_names=("BillingGateway", "Billing Gateway", "BillingGateway API"),
    jira_project_key="AMS",
    component_team="App Support — BillingGateway",
    tech_stack=".NET 8",
)
register_application(BILLING_GATEWAY)

DOCUMENT_HUB = Application(
    app_id="documenthub",
    display_name="DocumentHub",
    business_service="Document Management",
    ci_names=("DocumentHub", "Document Hub", "DocumentHub Storage"),
    jira_project_key="AMS",
    component_team="App Support — DocumentHub",
    tech_stack="React / Node",
)
register_application(DOCUMENT_HUB)


def all_applications() -> tuple[Application, ...]:
    return tuple(_REGISTRY.values())


def get_application(app_id: str) -> Application:
    return _REGISTRY[app_id]


def route_by_ci(ci: str | None) -> Application | None:
    """Resolve a ServiceNow CI to its application, or None if unroutable.

    None means "the deterministic tier has no answer" — an absent CI and an
    unrecognised CI are the same outcome for the caller, which is to fall back
    to `repo_match`'s LLM suggestion. Callers must not treat None as an error.
    """
    if not ci or not ci.strip():
        return None
    app_id = _BY_CI.get(_normalize(ci))
    return _REGISTRY[app_id] if app_id else None


def route_by_business_service(business_service: str | None) -> Application | None:
    """Resolve by business service — the coarser CMDB field, used only when a
    ticket carries no CI. Returns None if the service maps to more than one
    application, since a coarse field must never silently pick a winner."""
    if not business_service or not business_service.strip():
        return None
    key = _normalize(business_service)
    matches = [
        app for app in _REGISTRY.values() if _normalize(app.business_service) == key
    ]
    return matches[0] if len(matches) == 1 else None

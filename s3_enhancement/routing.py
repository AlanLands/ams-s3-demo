"""Ticket -> application routing: the decision, and how it was reached.

Wraps `applications.route_by_ci` in the thing callers actually need — not just
"which application", but *how confidently we know*, *who owns it*, and *whether
automation may proceed*. Those are three separate answers and the demo depends
on keeping them separate:

- A ticket with a CI routes deterministically. There is no model call and
  nothing for the developer to confirm; the CMDB already stated the answer.
- A ticket with no CI, or a CI this registry doesn't know, comes back
  `needs_ai_fallback=True`. The caller then runs the existing
  `repo_match.suggest_target_repo` LLM path, which carries its own confidence
  gate and asks the developer to confirm anything below "high".
- A ticket that routes to an application with no registered target is routed
  *successfully* and is still not automatable. It reaches the right team; S3
  simply has no repo to generate against.

Nothing here calls an LLM. That is the point: this is the tier that runs first
precisely because it cannot hallucinate, and folding the fallback in here would
make the deterministic path's cost and failure modes indistinguishable from the
model's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from common.roster import ENGINEERS_BY_GROUP, is_tester
from s3_enhancement import targets
from s3_enhancement.applications import (
    Application,
    route_by_business_service,
    route_by_ci,
)

RouteMethod = Literal["ci", "business_service", "unrouted"]


@dataclass(frozen=True)
class RouteDecision:
    """One routing outcome, carrying its own provenance.

    `method` is what the console shows the audience — "routed by CI" and
    "AI-matched by description" are very different claims to make in front of
    a client, and a decision object that can't tell them apart will eventually
    be rendered as though it could.
    """

    method: RouteMethod
    application: Application | None = None
    # The ticket field value that produced the match ("ClaimsPortal"), for
    # display. Empty when nothing matched.
    matched_on: str = ""
    candidate_target_ids: tuple[str, ...] = ()

    @property
    def routed(self) -> bool:
        return self.application is not None

    @property
    def needs_ai_fallback(self) -> bool:
        """Whether the caller should fall back to `repo_match`'s LLM suggestion.

        True exactly when the deterministic tier had no answer — an absent CI
        and an unknown CI are the same outcome here.
        """
        return self.application is None

    @property
    def automation_available(self) -> bool:
        """Whether S3 can generate code, as opposed to merely routing.

        Both conditions must hold: the application declares a repo, *and* at
        least one target is registered against it. An application with a repo
        but no target is routable and not yet automatable — that gap is real
        (a repo nobody has recorded a user story for) and must not read as automatable.
        """
        return (
            self.application is not None
            and self.application.automation_available
            and bool(self.candidate_target_ids)
        )

    @property
    def component_team(self) -> str:
        return self.application.component_team if self.application else ""

    @property
    def suggested_assignee(self) -> str:
        """First engineer on the owning team's roster.

        A suggestion for the developer to accept, never an auto-assignment —
        the console still posts it through `/s3/jira/assign-ticket`, which is a
        human action. Returns "" when unrouted.
        """
        if not self.application:
            return ""
        roster = ENGINEERS_BY_GROUP.get(self.application.component_team, [])
        # Skip testers: this suggests who *builds* the change, and a group whose
        # first member tests rather than builds would otherwise hand the work to
        # someone whose console has no Generate stage.
        buildable = [name for name in roster if not is_tester(name)]
        return buildable[0] if buildable else ""


def route_ticket(
    *, ci: str | None = None, business_service: str | None = None
) -> RouteDecision:
    """Resolve a ticket's application from its ServiceNow context fields.

    CI is tried first and business service only as a fallback, because CI is
    the precise field: a business service can span several applications, and
    `route_by_business_service` deliberately declines to guess when it does.
    """
    application = route_by_ci(ci)
    if application is not None:
        return RouteDecision(
            method="ci",
            application=application,
            matched_on=(ci or "").strip(),
            candidate_target_ids=tuple(
                t.target_id for t in targets.targets_for_application(application.app_id)
            ),
        )

    application = route_by_business_service(business_service)
    if application is not None:
        return RouteDecision(
            method="business_service",
            application=application,
            matched_on=(business_service or "").strip(),
            candidate_target_ids=tuple(
                t.target_id for t in targets.targets_for_application(application.app_id)
            ),
        )

    return RouteDecision(method="unrouted")

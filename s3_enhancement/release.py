"""Deployment plan and release record — the closing artifacts of a change.

Two things live here, both assembled from facts rather than drafted:

`build_deployment_plan()` answers "how does this get shipped, and how do we
put it back". Deploy order comes out of the change map's service graph: if
claims-service calls policy-service and the user story adds a field to the policy
API, deploying claims first gives you a window where it reads a field that
does not exist yet. That ordering is derivable, so it is derived — a model
asked the same question would usually be right, which is worse than always
being right, because nobody checks the usual case.

`build_release_record()` collects what actually happened into one bundle:
what shipped, the evidence it was tested, who approved it, how to roll it
back, and the notes that go out with it. Nothing in it is new information —
the console showed all of it during the run — but it existed only as browser
state and a scattered event log, so the moment the demo ended it was gone.
The record is the thing you attach to the ticket.

The only model-authored content in the record is the release notes and the
design doc's prose; everything structural is computed. The rendered document
labels the AI-drafted parts rather than presenting the whole thing as
machine-verified.

Both artifacts take the change's source-control state (s3_enhancement/scm.py)
when it exists, which pins the plan to a named branch and commit instead of
"deploy the change". That state is *simulated* — no git ran — so
`unproven_claims()` says so in the record rather than letting a modelled push
read as a deployment that happened.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime

from s3_enhancement.acceptance import Criterion
from s3_enhancement.diagram import ChangeMap
from s3_enhancement.docgen import ReleaseNoteSet
from s3_enhancement.scm import BranchState
from s3_enhancement.targets import Target
from s3_enhancement.traceability import Matrix

StepKind = str  # "merge" | "deploy" | "migrate" | "verify" | "rollback"


@dataclass(frozen=True)
class PlanStep:
    order: int
    kind: StepKind
    title: str
    detail: str
    command: str = ""

    def to_dict(self) -> dict:
        return {
            "order": self.order,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "command": self.command,
        }


@dataclass
class DeploymentPlan:
    steps: list[PlanStep]
    rollback: list[PlanStep]
    service_order: list[str]
    # Why the services are in this order, when the order is not arbitrary.
    order_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "steps": [step.to_dict() for step in self.steps],
            "rollback": [step.to_dict() for step in self.rollback],
            "service_order": self.service_order,
            "order_reason": self.order_reason,
        }


def _render_command(command: tuple[str, ...]) -> str:
    """A target's declared command as you would type it.

    `{python}` is the placeholder the apply endpoint substitutes at run time
    (see Target.post_apply_command); the plan is read by a human, so it shows
    the interpreter that would actually run.
    """
    return " ".join(sys.executable if part == "{python}" else part for part in command)


def _deploy_order(change_map: ChangeMap) -> tuple[list[str], str]:
    """Services in the order they must be deployed, callee before caller.

    A crossing is recorded as (caller, callee). The caller depends on the
    callee's new shape, so the callee ships first — deploy the other way round
    and there is a window where the caller reads a field the callee has not
    got yet. With no crossings the order is whatever the change map found,
    and the plan says so rather than implying a constraint that isn't there.
    """
    services = list(change_map.services)
    if not change_map.crossings:
        return services, ""

    ordered: list[str] = []
    callees = {callee for _, callee in change_map.crossings}
    for service in services:
        if service in callees and service not in ordered:
            ordered.append(service)
    for service in services:
        if service not in ordered:
            ordered.append(service)

    caller, callee = change_map.crossings[0]
    reason = (
        f"{callee} first: {caller} calls it over HTTP and this change touches "
        f"both, so deploying {caller} first leaves it reading a response shape "
        f"{callee} has not shipped yet."
    )
    return ordered, reason


def build_deployment_plan(
    target: Target,
    change_map: ChangeMap,
    *,
    applied_files: list[str] | None = None,
    branch: BranchState | None = None,
) -> DeploymentPlan:
    """The ordered steps to ship this change, and the ones to undo it.

    `branch`, when the change went through the source-control flow (see
    s3_enhancement/scm.py), pins the plan to a specific commit instead of
    leaving "deploy the change" to the reader's imagination. Derived like every
    other step here — no LLM.
    """
    service_order, order_reason = _deploy_order(change_map)
    files = applied_files if applied_files is not None else [n.rel_path for n in change_map.nodes]

    steps: list[PlanStep] = []
    if branch is not None:
        steps.append(
            PlanStep(
                order=1,
                kind="merge",
                title=f"Merge {branch.branch} into {branch.base}",
                detail=(
                    (
                        f"The change was committed as {branch.commit.sha} "
                        f"(“{branch.commit.message}”) on {branch.branch}, cut from "
                        f"{branch.base}. Everything below deploys that commit."
                    )
                    if branch.commit
                    else (
                        f"{branch.branch} was cut from {branch.base} and the files were "
                        "applied to it, but nothing was committed — there is no commit "
                        "for the steps below to deploy."
                    )
                ),
                command=f"git merge --no-ff {branch.branch}",
            )
        )
    for service in service_order:
        in_service = [node for node in change_map.nodes if node.service == service]
        names = ", ".join(sorted({node.filename for node in in_service}))
        steps.append(
            PlanStep(
                order=len(steps) + 1,
                kind="deploy",
                title=f"Deploy {service}",
                detail=f"{len(in_service)} changed file(s): {names}" if names else "No changes.",
            )
        )

    if target.post_apply_command:
        steps.append(
            PlanStep(
                order=len(steps) + 1,
                kind="migrate",
                title="Run the schema/data migration",
                detail=(
                    "This change touches persisted state, so the application's "
                    "own migration step must run before the new code serves "
                    "traffic."
                ),
                command=_render_command(target.post_apply_command),
            )
        )

    if target.has_regression_suite:
        steps.append(
            PlanStep(
                order=len(steps) + 1,
                kind="verify",
                title="Re-run the pre-existing regression suite",
                detail=(
                    "The same suite that gated the change, now against the "
                    "deployed build. It is the fastest signal that the release "
                    "broke something that already worked."
                ),
                command=(
                    _render_command(target.regression_command)
                    if target.regression_command
                    else f"python -m pytest {' '.join(target.regression_paths)}"
                ),
            )
        )

    rollback = [
        PlanStep(
            order=1,
            kind="rollback",
            title="Restore the previous build",
            detail=(
                f"Redeploy the prior release of {', '.join(reversed(service_order)) or 'the app'} "
                "— reverse of the deploy order above, so the caller stops "
                "depending on the new shape before the callee loses it. In this "
                f"console the equivalent is Revert all, which puts the {len(files)} "
                "applied file(s) back."
            ),
        )
    ]
    if branch is not None and branch.commit is not None:
        rollback.append(
            PlanStep(
                order=len(rollback) + 1,
                kind="rollback",
                title=f"Revert {branch.commit.sha} on {branch.base}",
                detail=(
                    "A revert commit rather than a history rewrite: the commit has "
                    f"already been merged, so {branch.base} has to move forward to "
                    "undo it. Rewriting a shared branch is a second incident, not a "
                    "rollback."
                ),
                command=f"git revert --no-edit {branch.commit.sha}",
            )
        )
    if target.post_apply_command:
        rollback.append(
            PlanStep(
                order=len(rollback) + 1,
                kind="rollback",
                title="Re-run the migration against the restored code",
                detail=(
                    "The migration step is written to be re-runnable; running it "
                    "after the revert returns the schema to what the restored "
                    "build expects."
                ),
                command=_render_command(target.post_apply_command),
            )
        )
    if target.has_regression_suite:
        rollback.append(
            PlanStep(
                order=len(rollback) + 1,
                kind="rollback",
                title="Confirm the rollback with the regression suite",
                detail="A rollback nobody verified is a second untested change.",
                command=(
                    _render_command(target.regression_command)
                    if target.regression_command
                    else f"python -m pytest {' '.join(target.regression_paths)}"
                ),
            )
        )

    return DeploymentPlan(
        steps=steps,
        rollback=rollback,
        service_order=service_order,
        order_reason=order_reason,
    )


# --- the release record -----------------------------------------------------


@dataclass(frozen=True)
class SuiteEvidence:
    """One test run's headline, as it appears in the record."""

    name: str
    passed: bool
    total: int
    passed_count: int
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "total": self.total,
            "passed_count": self.passed_count,
            "note": self.note,
        }


@dataclass
class ReleaseRecord:
    story_label: str
    ticket_key: str
    released_by: str
    generated_at: datetime
    changed_files: list[str]
    criteria: list[Criterion]
    matrix: Matrix | None
    evidence: list[SuiteEvidence]
    approvals: list[dict]
    plan: DeploymentPlan
    notes: ReleaseNoteSet | None
    diagram_svg: str = ""
    diagram_caption: str = ""
    unproven: list[str] = field(default_factory=list)
    # The branch/commit/push this change went through, when it went through one.
    # None means it was applied to the working tree without the source-control
    # flow, which `unproven_claims()` reports as a gap.
    branch: BranchState | None = None

    def to_dict(self) -> dict:
        return {
            "story_label": self.story_label,
            "ticket_key": self.ticket_key,
            "released_by": self.released_by,
            "generated_at": self.generated_at.isoformat(timespec="seconds"),
            "changed_files": self.changed_files,
            "matrix": self.matrix.to_dict() if self.matrix else None,
            "evidence": [item.to_dict() for item in self.evidence],
            "approvals": self.approvals,
            "plan": self.plan.to_dict(),
            "notes": self.notes.to_dict() if self.notes else None,
            "unproven": self.unproven,
            "branch": self.branch.to_dict() if self.branch else None,
        }


# Actions that represent a person deciding something, as opposed to the
# pipeline reporting something. The record's approvals section is about
# accountability, so it carries these and not the AI's own steps.
HUMAN_ACTIONS = (
    "test_scenarios_approved",
    "design_doc_exported",
    "file_applied",
    "files_applied",
    "file_rejected",
    "change_applied",
    "change_committed",
    "handoff_to_qa",
    "ticket_done",
    "release_record_attached",
)


def collect_approvals(events: list[dict]) -> list[dict]:
    """The human decisions in a ticket's event log, oldest first.

    Read from the server-side log rather than from whatever the browser still
    has in memory: the log is the only copy that survives a reload, a
    different operator picking the ticket up, and the demo being over.
    """
    approvals = []
    for event in events:
        if event.get("actor") != "human":
            continue
        approvals.append(
            {
                "ts": event.get("ts", ""),
                "action": str(event.get("action", "")).replace("_", " "),
                "detail": event.get("detail", ""),
            }
        )
    return approvals


def unproven_claims(
    matrix: Matrix | None,
    evidence: list[SuiteEvidence],
    branch: BranchState | None = None,
) -> list[str]:
    """What this release does *not* have evidence for.

    A release record that only lists successes is marketing. Anything the
    pipeline could not show — an uncovered criterion, a suite that never ran,
    a deployment nobody performed — is stated in the record itself, where the
    person signing it will see it.

    The source-control gaps are the newest and the most important to keep here.
    S3 models the branch → commit → push flow without running git (see
    s3_enhancement/scm.py), so the record must never let a modelled push read as
    a release that shipped. If that flow ever becomes real, these lines are what
    change — not the transcript, and not the panel.
    """
    gaps: list[str] = []
    if matrix is None:
        gaps.append("No traceability matrix was built for this release.")
    else:
        for row in matrix.rows:
            if row.status == "no_scenario":
                gaps.append(f"{row.criterion_id} has no test scenario covering it.")
            elif row.status == "not_automated":
                gaps.append(f"{row.criterion_id} was planned for but has no automated test.")
            elif row.status == "not_run":
                gaps.append(f"{row.criterion_id} has scenarios but nothing was run for it.")
            elif row.status == "failed":
                gaps.append(f"{row.criterion_id} has a failing test.")
    if not any(item.name.startswith("Regression") for item in evidence):
        gaps.append("The pre-existing regression suite was not run for this release.")
    for item in evidence:
        if not item.passed:
            gaps.append(f"{item.name} did not pass.")
    gaps.extend(_source_control_gaps(branch))
    return gaps


def _source_control_gaps(branch: BranchState | None) -> list[str]:
    """The part of "shipped" that S3 models rather than performs.

    Ordered so the biggest caveat lands last, because that is the line the
    signer's eye stops on.
    """
    if branch is None:
        return [
            "No branch or commit was recorded for this change: it was applied "
            "straight to the working tree, so there is no source-control history "
            "for it."
        ]
    gaps: list[str] = []
    if branch.abandoned_at:
        gaps.append(
            f"{branch.branch} was abandoned — every applied file was reverted, so "
            "nothing from this proposal is in the tree."
        )
    if branch.commit is None:
        gaps.append(
            f"The change was applied to {branch.branch} but never committed, so "
            "there is no commit for a pipeline to deploy."
        )
    elif not branch.pushed_at:
        gaps.append(
            f"{branch.commit.sha} was committed on {branch.branch} but not pushed; "
            "no deployment pipeline was triggered."
        )
    else:
        gaps.append(
            f"The push of {branch.branch} and pipeline {branch.pipeline_id} are "
            "simulated: this console does not contact a remote, so no build, "
            "deployment, or post-deployment verification actually ran."
        )
    return gaps

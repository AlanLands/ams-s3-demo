"""The source-control flow around Apply, modelled — never executed.

Apply writes the reviewed proposal straight into the working tree (see
`codegen.apply_change`). That is fine for a demo of *what the AI produced*, but
it skips the part every reviewer in a real shop asks about: you do not edit main.
You branch, you apply, you test, you commit, you let the pipeline deploy. This
module supplies that missing frame so the beat shows the flow, and it does so
without touching git.

**Nothing here runs git.** Not `add`, not `commit`, not `push`, not a subprocess
of any kind. The state below is a record of the decisions a real integration
would act on, plus `git_transcript()`, which renders the commands that
integration would issue. Two reasons it has to stay that way:

1. The target apps live *inside this repo*, and `demo/reset_s3*.sh` restores the
   pre-CR baseline with `git checkout HEAD -- <target files>`. A real commit
   would make HEAD carry the CR, so the reset scripts would quietly start
   restoring the change instead of the baseline — the failure would surface as
   a mystery mid-rehearsal, not as an error here.
2. A demo that pushes to a remote is a demo that can fail on stage for reasons
   that have nothing to do with the thing being demonstrated.

So every result carries `simulated=True`, the console labels it, and the release
record counts the un-run pipeline as an *unproven claim* rather than an
accomplishment (see `release.unproven_claims`). `tests/test_s3_scm.py` asserts
the no-git-writes guarantee at the source level, the same way
`tests/test_autofix_no_git_writes.py` does for the autofix loop. If S3 ever
grows a real SCM integration it belongs in a new module behind an explicit mode
flag — do not turn `simulated` into a lie in this one.

State lives at `s3_enhancement/out/{proposal_id}/scm.json`, keyed by proposal
like every other piece of apply-time state (staged files, backups, rejections),
so `rm -rf s3_enhancement/out/*` in the reset scripts clears it for free.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from common.schema import DATETIME_FMT

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO_ROOT / "s3_enhancement" / "out"

# The branch every feature branch is cut from, and the branch a real pipeline
# would merge back into. Named here rather than inline so the transcript and the
# release record cannot disagree about it.
BASE_BRANCH = "main"

# The remote a real integration would push to. Deliberately a placeholder: this
# module never contacts it, and a plausible-looking real URL in the transcript
# would invite someone to assume it did.
REMOTE = "origin"


class ScmError(RuntimeError):
    """A step was requested out of order, or its precondition was not met."""


# --- state ------------------------------------------------------------------


@dataclass(frozen=True)
class Commit:
    """A commit that would exist, had this been wired to git.

    `sha` is derived from the branch, message, and file set rather than being
    random, so the same run produces the same short sha twice — a demo that
    shows a different sha on every reload looks broken to anyone who reads
    carefully.
    """

    sha: str
    message: str
    files: tuple[str, ...]
    committed_at: str

    def to_dict(self) -> dict:
        return {
            "sha": self.sha,
            "message": self.message,
            "files": list(self.files),
            "committed_at": self.committed_at,
        }


@dataclass
class BranchState:
    proposal_id: str
    branch: str
    base: str
    ticket: str
    created_at: str
    # Files apply has written so far. Grows across per-file applies, because a
    # branch accumulates work the same way.
    staged_files: list[str] = field(default_factory=list)
    commit: Commit | None = None
    pushed_at: str | None = None
    pipeline_id: str = ""
    # Set when every applied file has been reverted: the branch existed, then
    # the work on it was thrown away. Recorded rather than deleted so the
    # ticket's history still shows the branch was cut.
    abandoned_at: str | None = None

    @property
    def status(self) -> str:
        if self.abandoned_at:
            return "abandoned"
        if self.pushed_at:
            return "pushed"
        if self.commit:
            return "committed"
        if self.staged_files:
            return "applied"
        return "open"

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "branch": self.branch,
            "base": self.base,
            "ticket": self.ticket,
            "created_at": self.created_at,
            "staged_files": list(self.staged_files),
            "commit": self.commit.to_dict() if self.commit else None,
            "pushed_at": self.pushed_at,
            "pipeline_id": self.pipeline_id,
            "abandoned_at": self.abandoned_at,
            "status": self.status,
            # Always true, on every response, by design. See the module
            # docstring — the console renders this, and the release record
            # treats an un-run pipeline as an unproven claim.
            "simulated": True,
            "transcript": git_transcript(self),
        }


def _state_path(proposal_id: str) -> Path:
    return OUT_ROOT / proposal_id / "scm.json"


def _write(state: BranchState) -> BranchState:
    path = _state_path(state.proposal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "proposal_id": state.proposal_id,
        "branch": state.branch,
        "base": state.base,
        "ticket": state.ticket,
        "created_at": state.created_at,
        "staged_files": sorted(set(state.staged_files)),
        "commit": state.commit.to_dict() if state.commit else None,
        "pushed_at": state.pushed_at,
        "pipeline_id": state.pipeline_id,
        "abandoned_at": state.abandoned_at,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return state


def state_for(proposal_id: str) -> BranchState | None:
    """The branch state for a proposal, or None if no branch was ever cut."""
    path = _state_path(proposal_id)
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    commit_raw = raw.get("commit")
    return BranchState(
        proposal_id=raw["proposal_id"],
        branch=raw["branch"],
        base=raw.get("base", BASE_BRANCH),
        ticket=raw.get("ticket", ""),
        created_at=raw.get("created_at", ""),
        staged_files=list(raw.get("staged_files") or []),
        commit=(
            Commit(
                sha=commit_raw["sha"],
                message=commit_raw["message"],
                files=tuple(commit_raw.get("files") or []),
                committed_at=commit_raw.get("committed_at", ""),
            )
            if commit_raw
            else None
        ),
        pushed_at=raw.get("pushed_at"),
        pipeline_id=raw.get("pipeline_id", ""),
        abandoned_at=raw.get("abandoned_at"),
    )


# --- naming -----------------------------------------------------------------


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_STRIP.sub("-", text.strip().lower()).strip("-")


def branch_name_for(ticket: str, target_id: str) -> str:
    """`feature/AMS-103-claimsportal-claims-deductible`.

    The ticket keeps its own casing — that is how a Jira key is written
    everywhere else, and lowercasing it makes the branch harder to match back
    to the board. The target id is already a slug by convention, so this only
    has to defend against one that isn't.
    """
    ticket_part = ticket.strip() or "no-ticket"
    slug = _slug(target_id) or "change"
    return f"feature/{ticket_part}-{slug}"


def _short_sha(branch: str, message: str, files: tuple[str, ...]) -> str:
    """A stable, obviously-fake-if-you-look 7-char sha.

    Derived, not random: the same commit rendered twice must read the same, or
    the transcript looks like it is inventing history on every refresh.
    """
    digest = hashlib.sha1(
        "\n".join([branch, message, *sorted(files)]).encode("utf-8")
    ).hexdigest()
    return digest[:7]


# --- the flow ---------------------------------------------------------------


def open_branch(proposal_id: str, ticket: str, target_id: str) -> BranchState:
    """Cut the feature branch this proposal will be applied on.

    Called by `/s3/apply` *before* the first file is written, which is the whole
    point: the branch has to exist before the edit, not be back-filled after
    it, or the flow being shown is not the flow being described.

    Idempotent — a second apply on the same proposal (per-file applies, or a
    revise-then-apply) stays on the branch it already cut. Re-opening a branch
    that was abandoned clears the abandonment: the developer reverted, changed
    their mind, and applied again.
    """
    existing = state_for(proposal_id)
    if existing is not None:
        if existing.abandoned_at:
            existing.abandoned_at = None
            return _write(existing)
        return existing
    return _write(
        BranchState(
            proposal_id=proposal_id,
            branch=branch_name_for(ticket, target_id),
            base=BASE_BRANCH,
            ticket=ticket.strip(),
            created_at=datetime.now().strftime(DATETIME_FMT),
        )
    )


def record_applied(proposal_id: str, files: list[str]) -> BranchState | None:
    """Note which files apply has written onto the branch — `git add`, modelled.

    No-op (returning None) when no branch was cut, so a caller that applies
    outside the SCM flow is not forced through it.
    """
    state = state_for(proposal_id)
    if state is None:
        return None
    state.staged_files = sorted(set(state.staged_files) | set(files))
    return _write(state)


def record_reverted(proposal_id: str, files: list[str]) -> BranchState | None:
    """Drop reverted files from the branch, abandoning it if nothing is left.

    A commit already made is deliberately *not* rewound: in a real repo the
    commit exists on the branch, and the honest equivalent of "undo" at that
    point is a revert commit or a deleted branch, not a silently rewritten
    history. Abandoning the branch says what actually happened.
    """
    state = state_for(proposal_id)
    if state is None:
        return None
    state.staged_files = sorted(set(state.staged_files) - set(files))
    if not state.staged_files:
        state.abandoned_at = datetime.now().strftime(DATETIME_FMT)
    return _write(state)


def commit_branch(proposal_id: str, message: str) -> BranchState:
    """Commit the applied work onto the branch.

    The caller is responsible for the tests-passed gate — see
    `commit_blockers()`, which reads it out of the ticket's own event log rather
    than trusting a flag from the browser. This function enforces only what it
    can see for itself: a branch exists, and it has files on it.
    """
    state = state_for(proposal_id)
    if state is None:
        raise ScmError(
            f"No branch open for proposal {proposal_id!r} — apply the change first."
        )
    if not state.staged_files:
        raise ScmError(
            f"Nothing to commit on {state.branch} — no files from proposal "
            f"{proposal_id!r} are currently applied."
        )
    if state.commit is not None:
        return state  # idempotent: a double-click must not invent a second commit
    subject = message.strip() or f"{state.ticket}: apply reviewed AI change"
    files = tuple(state.staged_files)
    state.commit = Commit(
        sha=_short_sha(state.branch, subject, files),
        message=subject,
        files=files,
        committed_at=datetime.now().strftime(DATETIME_FMT),
    )
    return _write(state)


# A target's display_name reads "<App> — <what the CR does> (<CR label>)". The
# middle clause is the only human summary of the change S3 has without asking a
# model for one, so the commit subject borrows it.
_DISPLAY_NAME_TAIL = re.compile(r"\s*\((?:CR|AMS)[-\w]*\)\s*$", re.IGNORECASE)


def summary_from_display_name(display_name: str) -> str:
    """The "what it does" clause of a target's display name, or "".

    Falls back to empty rather than guessing: an unrecognised shape should make
    the commit subject fall back to the CR label, not put a whole display name
    including the app and the CR number into the subject line.
    """
    if "—" not in display_name:
        return ""
    tail = display_name.rsplit("—", 1)[1]
    return _DISPLAY_NAME_TAIL.sub("", tail).strip()


def commit_message_for(ticket: str, cr_label: str, summary: str = "") -> str:
    """A conventional commit subject built from the ticket, not from the model.

    `AMS-103: claims deductible handling (CR-2026-043)` — the ticket key so the
    board can find it, what changed so a reader of `git log` does not have to,
    and the CR label so it ties back to the change request.

    Pure string assembly on data already on hand, so there is no cache key to
    warm and nothing to be confidently wrong about on stage — the same reasoning
    as `diagram.py` and `acceptance.py`.
    """
    head = f"{ticket.strip()}: " if ticket.strip() else ""
    summary = summary.strip()
    label = cr_label.strip()
    if summary and label:
        body = f"{summary} ({label})"
    else:
        body = summary or label or "apply reviewed AI change"
    return f"{head}{body}"


def push_branch(proposal_id: str) -> BranchState:
    """Push the branch and hand off to the pipeline — modelled, not performed.

    Refuses without a commit, because "pushed uncommitted work" is not a state
    that exists, and showing it would teach the audience something false.
    """
    state = state_for(proposal_id)
    if state is None:
        raise ScmError(
            f"No branch open for proposal {proposal_id!r} — apply the change first."
        )
    if state.commit is None:
        raise ScmError(
            f"Nothing to push on {state.branch} — commit the applied files first."
        )
    if state.pushed_at:
        return state
    state.pushed_at = datetime.now().strftime(DATETIME_FMT)
    state.pipeline_id = f"pipeline-{state.commit.sha}"
    return _write(state)


# --- gating -----------------------------------------------------------------

# Recorded by /s3/tests/run and /s3/tests/regression. Read here instead of
# accepting a "tests passed" boolean from the client, for the same reason the
# release record's approvals are read server-side: the event log is the only
# copy that survives a reload, a different operator, and the demo being over.
_GENERATED_SUITE_EVENTS = ("tests_passed", "tests_failed")
_REGRESSION_EVENTS = ("regression_passed", "regression_failed")


def _latest(events: list[dict], actions: tuple[str, ...]) -> dict | None:
    """The last event whose action is one of `actions`, or None.

    Last rather than any: a suite that failed, was fixed, and passed must read
    as passing, and one that passed and then broke must read as broken.
    """
    for event in reversed(events):
        if event.get("action") in actions:
            return event
    return None


def commit_blockers(events: list[dict]) -> list[str]:
    """Why this branch may not be committed yet, in the words the console shows.

    Empty list means the gate is open. The generated suite is a hard gate — the
    beat's claim is "committed once the tests passed", and committing without a
    test run would make that claim false. The pre-existing regression suite is
    also a hard gate when it *ran and failed*: the CR broke something that
    already worked, and that is the one result the whole regression beat exists
    to catch. A regression suite that was never run is reported as a gap in the
    release record instead (see `release.unproven_claims`), not blocked here,
    because some targets have no suite to run.
    """
    blockers: list[str] = []
    generated = _latest(events, _GENERATED_SUITE_EVENTS)
    if generated is None:
        blockers.append(
            "The generated suite has not been run against this change yet — "
            "run the tests before committing."
        )
    elif generated.get("action") == "tests_failed":
        blockers.append(
            f"The generated suite is failing ({generated.get('detail', '')}) — "
            "a red branch does not get committed."
        )
    regression = _latest(events, _REGRESSION_EVENTS)
    if regression is not None and regression.get("action") == "regression_failed":
        blockers.append(
            f"The pre-existing regression suite is failing "
            f"({regression.get('detail', '')}) — this change broke something "
            "that already worked."
        )
    return blockers


def evidence_summary(events: list[dict]) -> dict:
    """What the gate saw, so the console can show the reason and not just the verdict."""
    generated = _latest(events, _GENERATED_SUITE_EVENTS)
    regression = _latest(events, _REGRESSION_EVENTS)
    return {
        "generated_suite": (
            {
                "passed": generated.get("action") == "tests_passed",
                "detail": generated.get("detail", ""),
                "ts": generated.get("ts", ""),
            }
            if generated
            else None
        ),
        "regression_suite": (
            {
                "passed": regression.get("action") == "regression_passed",
                "detail": regression.get("detail", ""),
                "ts": regression.get("ts", ""),
            }
            if regression
            else None
        ),
    }


# --- rendering --------------------------------------------------------------


def git_transcript(state: BranchState) -> list[str]:
    """The commands a real integration would have run, in order.

    Rendered from state, so the transcript can only ever show steps that
    actually happened in the flow — it grows a line when the developer takes
    the step, never before. This is presentation, not execution: see the module
    docstring, and note that the strings below are prose for a reader, which is
    why `tests/test_s3_scm.py` checks for subprocess/argv usage rather than for
    the word "commit".
    """
    lines = [f"$ git checkout -b {state.branch} {state.base}"]
    if state.staged_files:
        for rel_path in state.staged_files:
            lines.append(f"$ git add {rel_path}")
    if state.commit:
        lines.append(f"$ git commit -m {state.commit.message!r}")
        lines.append(f"  [{state.branch} {state.commit.sha}] {len(state.commit.files)} file(s) changed")
    if state.pushed_at:
        lines.append(f"$ git push {REMOTE} {state.branch}")
        lines.append(f"  remote: pipeline {state.pipeline_id} queued for {state.branch}")
    if state.abandoned_at:
        lines.append(f"$ git branch -D {state.branch}")
        lines.append("  branch abandoned — every applied file was reverted")
    return lines

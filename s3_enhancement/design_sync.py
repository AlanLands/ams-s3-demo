"""Keep subsystem `DESIGN.md` docs in step with the code they describe.

Stage-1 relevance screening (`relevance.py::screen_subsystems`) scores each
subsystem's `DESIGN.md` "## Scope keywords" section to decide which subsystems
are even *opened* for a CR. Those docs are a retrieval control surface — but
until this module, nothing ever wrote one back. Code changed every CR; the docs
that gate retrieval never did, so the declared scope drifted from reality and
the screening gate quietly decayed.

The failure mode is asymmetric and silent: a subsystem wrongly screened *in*
merely costs tokens and is visible in the file panel, while one wrongly
screened *out* is never opened, so nothing downstream can notice it was
missing. `relevance.verify_core_recall()` will not catch it — that only checks
the declared core files of the target already chosen.

Two stages, mirroring the house pattern of a cheap deterministic gate in front
of a judgment call:

1. **Impact detection** (`find_affected_subsystems`) — pure path arithmetic, no
   LLM, always safe to run. An applied file counts as touching a subsystem when
   it lives under a directory that ships a `DESIGN.md`. When nothing matches
   (the common case, including all three of today's demo CRs) the whole feature
   is a no-op and no provider call is ever made.
2. **Doc review** (`review_design_doc`) — only for subsystems stage 1 flagged.
   Asks whether the doc's declared scope still describes the subsystem after
   this change, and if not, returns a rewritten doc.

## Why this is a separate proposal, not part of the codegen diff

Tempting to fold the doc edit into the code proposal so it is one review, one
apply. It would break the demo. `codegen.py`'s `_validate_file_set` requires
the model's returned file set to match what the relevance funnel selected, and
the committed replay recordings in `s3_enhancement/cache/` encode that exact
set. Adding `DESIGN.md` to it desyncs every recording and the beat dies with
`LLMError: codegen returned unexpected file set` — in replay, offline, with no
live fallback (see CLAUDE.md's "file paths are load-bearing" rule).

So a flagged doc is staged as its **own** proposal via
`codegen.stage_files_as_proposal()`, which means it rides the existing review
and apply path unchanged: same diff rendering, same `apply_change()`, same
per-file apply. No second apply mechanism exists.

## Failing soft is a requirement, not politeness

This runs immediately after a successful Apply, the most load-bearing beat in
the demo. `complete()` does not consult `LLM_MODE`, so with a cold cache and no
reachable provider it raises `LLMError`. Every provider call here is therefore
caught and degraded to `checked=False` with a reason — a doc-sync that cannot
run must never turn an applied change into a failed one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from common.llm import LLMError, complete, parse_json_response
from s3_enhancement import codegen, relevance
from s3_enhancement.targets import Target

REPO_ROOT = Path(__file__).resolve().parents[1]

SYSTEM_PROMPT = (
    "You are an AI assistant maintaining architecture documentation for an "
    "application-maintenance team. You keep each subsystem's design document "
    "truthful about what that subsystem owns. Return structured JSON only — no "
    "markdown fences, no prose outside the JSON."
)


@dataclass(frozen=True)
class SubsystemImpact:
    """A subsystem whose documented directory contains at least one file the
    change just modified. Produced without reading any file content."""

    subsystem: str
    design_doc: str
    applied_files: tuple[str, ...]


@dataclass(frozen=True)
class DesignDocFinding:
    """The verdict on one affected subsystem's design doc.

    `proposal_id` and `diff_text` are populated only when the doc needs an
    update *and* the model returned a replacement — they address a staged
    proposal that `codegen.apply_change()` applies like any other.
    """

    subsystem: str
    design_doc: str
    applied_files: tuple[str, ...]
    still_accurate: bool
    reason: str
    proposal_id: str = ""
    diff_text: str = ""


@dataclass(frozen=True)
class DesignSyncResult:
    checked: bool
    impacts: tuple[SubsystemImpact, ...] = ()
    findings: tuple[DesignDocFinding, ...] = ()
    unavailable_reason: str = ""

    @property
    def stale_docs(self) -> tuple[DesignDocFinding, ...]:
        return tuple(finding for finding in self.findings if not finding.still_accurate)


def find_affected_subsystems(
    applied_files: list[str] | tuple[str, ...],
    *,
    design_doc_root: Path | None = None,
) -> tuple[SubsystemImpact, ...]:
    """Which documented subsystems does this set of applied files touch?

    Pure path arithmetic against the subsystem directories
    `relevance.discover_subsystem_design_docs()` finds — no file is opened and
    no provider is called, so this is safe to run on every apply.

    A file is attributed to the **most specific** documented directory
    containing it, so a nested subsystem wins over its parent rather than both
    matching. Files outside every documented directory are attributed to
    nothing, which is why this returns empty for all three of today's demo
    CRs — `mockapp/core/` and `sandbox/spring-demo/` carry no `DESIGN.md`.
    """
    docs = relevance.discover_subsystem_design_docs(
        relevance.MOCKAPP_ROOT if design_doc_root is None else design_doc_root
    )
    if not docs:
        return ()

    # Longest prefix first so the most specific subsystem claims the file.
    subsystems = sorted(docs, key=len, reverse=True)
    hits: dict[str, list[str]] = {}
    for path in applied_files:
        for subsystem in subsystems:
            if path.startswith(f"{subsystem}/"):
                hits.setdefault(subsystem, []).append(path)
                break

    return tuple(
        SubsystemImpact(
            subsystem=subsystem,
            design_doc=f"{subsystem}/DESIGN.md",
            applied_files=tuple(sorted(hits[subsystem])),
        )
        for subsystem in sorted(hits)
    )


def build_review_prompt(impact: SubsystemImpact, doc_text: str, diff_text: str) -> str:
    files = "\n".join(f"- {path}" for path in impact.applied_files)
    return f"""A change was just applied to the `{impact.subsystem}` subsystem.

Files changed in this subsystem:
{files}

The change itself:
```diff
{diff_text}
```

That subsystem's current design document (`{impact.design_doc}`):
```markdown
{doc_text}
```

Does this design document still accurately describe the subsystem after the
change above? Consider especially whether the "## Scope keywords" section still
reflects what the subsystem does — those keywords are used to decide whether
this subsystem is even considered relevant to future change requests, so
keywords that have gone stale cause real retrieval mistakes later.

Be conservative: a change that only alters implementation detail without
changing what the subsystem owns or is about does NOT need a doc update.

Return JSON exactly matching:
{{
  "still_accurate": true or false,
  "reason": "one sentence explaining the verdict",
  "updated_doc": "the complete updated markdown document, or null if still_accurate is true"
}}

When you return an updated document, preserve its existing section structure
and heading names, and change only what the code change actually made untrue."""


def review_design_doc(
    impact: SubsystemImpact, diff_text: str, *, repo_root: Path | None = None
) -> DesignDocFinding:
    """Ask whether one subsystem's design doc survived this change intact.

    Deliberately omits a fixed `cache_key`: the input is a real diff against a
    real doc and genuinely varies per change, so `complete()`'s default
    content-hash cache is the correct behaviour here — the same reasoning as
    `repo_match.suggest_target_repo`. A fixed key would serve one recorded
    answer for every future change.

    Raises `LLMError` on a provider or parsing failure; `review_after_apply`
    is what turns that into a soft `checked=False`.
    """
    root = REPO_ROOT if repo_root is None else repo_root
    doc_text = (root / impact.design_doc).read_text(encoding="utf-8")

    response = complete(
        build_review_prompt(impact, doc_text, diff_text),
        system=SYSTEM_PROMPT,
        json_mode=True,
    )
    data = parse_json_response(response, required_keys={"still_accurate"})

    still_accurate = bool(data["still_accurate"])
    reason = str(data.get("reason", "")).strip()
    updated_doc = data.get("updated_doc")

    if still_accurate or not isinstance(updated_doc, str) or not updated_doc.strip():
        # A "needs updating" verdict with no replacement text is a finding
        # worth surfacing, just without a diff to apply — better than
        # discarding the signal or inventing a document.
        return DesignDocFinding(
            subsystem=impact.subsystem,
            design_doc=impact.design_doc,
            applied_files=impact.applied_files,
            still_accurate=still_accurate,
            reason=reason,
        )

    proposal_id, diff = codegen.stage_files_as_proposal({impact.design_doc: updated_doc})
    return DesignDocFinding(
        subsystem=impact.subsystem,
        design_doc=impact.design_doc,
        applied_files=impact.applied_files,
        still_accurate=False,
        reason=reason,
        proposal_id=proposal_id,
        diff_text=diff,
    )


def read_proposal_diff(proposal_id: str) -> str:
    """The diff of an already-applied proposal, read from the copy staging
    wrote. Recomputing it post-apply would yield nothing, because the staged
    files and the working tree now match."""
    if not proposal_id:
        return ""
    diff_path = codegen.OUT_ROOT / proposal_id / "diff.patch"
    if not diff_path.is_file():
        return ""
    return diff_path.read_text(encoding="utf-8")


def review_after_apply(
    applied_files: list[str] | tuple[str, ...],
    *,
    proposal_id: str = "",
    target: Target | None = None,
    diff_text: str | None = None,
) -> DesignSyncResult:
    """Full post-apply check: detect affected subsystems, then review each
    one's design doc.

    Never raises on a provider failure — an unreachable model degrades to
    `checked=False` with a reason, because this runs straight after Apply and
    must not be able to fail the beat that just succeeded.
    """
    design_doc_root = target.root if target is not None else None
    impacts = find_affected_subsystems(applied_files, design_doc_root=design_doc_root)
    if not impacts:
        return DesignSyncResult(checked=True)

    diff = read_proposal_diff(proposal_id) if diff_text is None else diff_text

    findings: list[DesignDocFinding] = []
    for impact in impacts:
        try:
            findings.append(review_design_doc(impact, diff))
        except (LLMError, OSError) as exc:
            return DesignSyncResult(
                checked=False,
                impacts=impacts,
                findings=tuple(findings),
                unavailable_reason=str(exc),
            )

    return DesignSyncResult(checked=True, impacts=impacts, findings=tuple(findings))

"""Auto-registration of S3 targets from the `repos/` drop folder.

The onboarding story S3 claims is "drop the repo in and add its user stories". This
module is what makes that literally true: `repos/<name>/.s3targets.json`
declares the target(s) that repo contributes, and `targets.py` registers every
one it finds at import time. No code edit, no redeploy.

**Why a manifest and not pure convention.** Most of a `Target` cannot be
inferred from a directory. `codegen_allowlist` is the blast radius a user story is
permitted to touch; `core_files` is what relevance must always recall;
`regression_paths` names the human-authored suite the pipeline is forbidden to
write to; `mutations` quote generated code verbatim. Guessing any of those
would either widen the blast radius silently or make the "the AI never touched
the independent check" claim untrue. The manifest is the smallest honest
contract — everything it declares is a decision a human has to make anyway.

**What a dropped repo does and does not get.** Discovery gives it relevance
scoping, the user story/target routing, the apply/revert cycle and the regression beat.
It does not give it a committed replay recording — there is nothing to record
against until the user story is run once — so its first codegen run is a live call that
records itself (`common/llm.py::stream_complete` degrades replay->record on a
miss). Nor does it get a bespoke structural validator: the three built-in
targets carry hand-written file-set validators in `codegen.py` keyed to their
own user story's shape, and a discovered target falls through to the generic
`_validate_file_set`. Both are honest defaults, not gaps to paper over.

The three built-in targets stay declared in `targets.py` rather than moving to
manifests, because they own exactly those bespoke validators and because other
modules import them by name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REPOS_DIR = REPO_ROOT / "repos"
MANIFEST_NAME = ".s3targets.json"


class ManifestError(ValueError):
    """A manifest exists but cannot be turned into a Target.

    Raised rather than skipped: a repo that ships a manifest is asking to be
    registered, so a typo in it must fail loudly at import. Silently ignoring
    it would present as "S3 didn't pick up my repo" with nothing to look at.
    """


def _require(data: dict[str, Any], key: str, manifest: Path) -> Any:
    if key not in data or data[key] in (None, "", [], {}):
        raise ManifestError(f"{manifest}: missing required key {key!r}")
    return data[key]


def _tuple(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key) or []
    if isinstance(value, str):
        raise ManifestError(f"{key!r} must be a list, not a string")
    return tuple(value)


def _build_target(entry: dict[str, Any], repo_dir: Path, manifest: Path):
    # Imported here, not at module scope: targets.py imports this module, so a
    # top-level import would be circular.
    from s3_enhancement.targets import Mutation, Target

    target_id = _require(entry, "target_id", manifest)
    cache_namespace = _require(entry, "cache_namespace", manifest)
    if not cache_namespace:
        # "" is reserved for the one legacy default target; a discovered
        # target taking it would collide on every cache key.
        raise ManifestError(f"{manifest}: cache_namespace must be non-empty")

    story = entry.get("story")
    story_path = (REPO_ROOT / story) if story else None
    if story_path is not None and not story_path.is_file():
        raise ManifestError(f"{manifest}: story {story!r} does not exist")

    mutations = tuple(
        Mutation(
            rel_path=m["rel_path"],
            old_snippet=m["old_snippet"],
            new_snippet=m["new_snippet"],
            description=m.get("description", ""),
        )
        for m in entry.get("mutations", [])
    )

    post_apply = tuple(entry.get("post_apply_command", []))

    return Target(
        target_id=target_id,
        source_kind="local",
        display_name=entry.get("display_name", target_id),
        application_id=entry.get("application_id", ""),
        root=repo_dir,
        story_template_path=story_path,
        story_placeholder=entry.get("story_placeholder", ""),
        core_files=_tuple(entry, "core_files"),
        never_extra=frozenset(entry.get("never_extra", [])),
        codegen_allowlist=_tuple(entry, "codegen_allowlist"),
        testgen_allowlist=_tuple(entry, "testgen_allowlist"),
        harness_expected_files=_tuple(entry, "harness_expected_files"),
        language=entry.get("language", "python"),
        post_apply_command=post_apply,
        regression_paths=_tuple(entry, "regression_paths"),
        mutations=mutations,
        cache_namespace=cache_namespace,
    )


def discover_manifest_targets() -> list:
    """Every target declared by a manifest under `repos/`, in directory order.

    Directory order (sorted) rather than filesystem order, so registration —
    and therefore any collision error — is reproducible across machines.
    """
    if not REPOS_DIR.is_dir():
        return []
    found = []
    for repo_dir in sorted(p for p in REPOS_DIR.iterdir() if p.is_dir()):
        manifest = repo_dir / MANIFEST_NAME
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{manifest}: invalid JSON — {exc}") from exc
        entries = data.get("targets")
        if not isinstance(entries, list):
            raise ManifestError(f"{manifest}: expected a top-level 'targets' list")
        for entry in entries:
            found.append(_build_target(entry, repo_dir, manifest))
    return found


def register_discovered(register, registry: dict) -> list[str]:
    """Register every manifest-declared target not already registered.

    Built-ins win: `targets.py` declares its three by hand (they carry bespoke
    codegen validators), so a manifest re-declaring one of those ids is skipped
    rather than raising. Any *other* id or namespace collision still raises
    through `register` — that is a real conflict between two dropped repos and
    must not be silently resolved.
    """
    registered: list[str] = []
    for target in discover_manifest_targets():
        if target.target_id in registry:
            continue
        register(target)
        registered.append(target.target_id)
    return registered

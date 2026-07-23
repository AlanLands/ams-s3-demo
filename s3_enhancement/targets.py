"""S3 target registry — the seam that lets S3 scale beyond one repo/one CR.

Every S3 module today (`codegen.py`, `testgen.py`, `harness.py`, `cr.py`,
`analyze.py`, `docgen.py`) is hardcoded to CR-2026-041 against `mockapp/`: file
allowlists, the CR template path, and — critically — LLM cache keys are all
fixed literals. `common/llm.py`'s `complete()`/`stream_complete()` build their
on-disk cache path from a supplied `cache_key` alone, with no hash of the actual
prompt content, so two different targets sharing a cache key would silently get
back each other's cached response, not an error. Nothing hits this today only
because nothing today varies the target.

`Target` is the unit that would need to be registered per repo in a real
30-repo estate. `register_target()` makes cache-identity collisions
unrepresentable (raises at import time) rather than merely unlikely.
`MOCKAPP_COVERAGE_UPGRADE` is today's one target, wired up to return the exact
legacy cache-key literals so the two committed replay recordings
(`s3_enhancement/cache/s3_codegen.json`, `s3_testgen.json`) and `.cache/llm`'s
existing entries stay byte-identical — this module changes no runtime
behavior for the existing demo path, only where the constants live.

What this does NOT solve: the actual codegen/testgen/harness prompts and
structural validators (exact API names, exact error wording, backward-compat
checks) are CR-2026-041-specific business logic, not generic. Onboarding a
real second target for live codegen means writing that target's own
prompt/validator pair, not just registering it here. See
s3_enhancement/DESIGN_MULTI_REPO.md for the full scope discussion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[1]

# Legacy cache-key literals, preserved verbatim so the default target's cache
# identity never changes. Keyed by beat name, not derived by formula.
_LEGACY_CACHE_KEYS: dict[str, str] = {
    "impact_analysis": "s3_impact_analysis:coverage_upgrade:v2",
    "effort_estimate": "s3_effort_estimate:coverage_upgrade:v2",
    "release_notes": "s3_release_notes:coverage_upgrade",
}
_LEGACY_STREAM_CACHE_KEYS: dict[str, str] = {
    "codegen": "s3_codegen",
    "testgen": "s3_testgen",
}


@dataclass(frozen=True)
class Target:
    """One repo/CR pairing S3 can operate against.

    `cache_namespace` is the collision-prevention key: `""` is reserved for the
    one legacy default target (see module docstring); every other target must
    register a non-empty, registry-unique namespace, enforced by
    `register_target()`.
    """

    target_id: str
    source_kind: Literal["local", "gitlab"]
    display_name: str

    # "local" source
    root: Path | None = None
    cr_template_path: Path | None = None
    cr_placeholder: str = "{{TIER_NAME}}"

    # "gitlab" source — read-only discovery/relevance preview only; live
    # codegen/apply is never run against a GitLab-hosted target (see design doc).
    project_id: str | int | None = None
    ref: str = "main"

    # relevance scoping
    core_files: tuple[str, ...] = ()
    never_extra: frozenset[str] = field(default_factory=frozenset)

    # codegen/testgen/harness contracts
    codegen_allowlist: tuple[str, ...] = ()
    testgen_allowlist: tuple[str, ...] = ()
    harness_expected_files: tuple[str, ...] = ()

    cache_namespace: str = ""

    def cache_key(self, beat: str) -> str:
        """Cache key for `common.llm.complete()`'s hash-keyed narrative cache."""
        if not self.cache_namespace:
            return _LEGACY_CACHE_KEYS[beat]
        return f"s3_{beat}:{self.cache_namespace}:v1"

    def stream_cache_key(self, beat: str) -> str:
        """Cache key for `common.llm.stream_complete()`'s literal-filename cache."""
        if not self.cache_namespace:
            return _LEGACY_STREAM_CACHE_KEYS[beat]
        return f"s3_{beat}__{self.cache_namespace}"


_REGISTRY: dict[str, Target] = {}
_NAMESPACES: dict[str, str] = {}  # cache_namespace -> target_id, for collision checks


def register_target(target: Target) -> None:
    """Register a target. Raises if its target_id or (non-empty) cache_namespace
    is already taken — collisions become unrepresentable, not just unlikely."""
    if target.target_id in _REGISTRY:
        raise ValueError(f"target_id {target.target_id!r} is already registered")
    if target.cache_namespace and target.cache_namespace in _NAMESPACES:
        raise ValueError(
            f"cache_namespace {target.cache_namespace!r} is already used by "
            f"target {_NAMESPACES[target.cache_namespace]!r}"
        )
    _REGISTRY[target.target_id] = target
    if target.cache_namespace:
        _NAMESPACES[target.cache_namespace] = target.target_id


DEFAULT_TARGET_ID = "mockapp-coverage-upgrade"

MOCKAPP_COVERAGE_UPGRADE = Target(
    target_id=DEFAULT_TARGET_ID,
    source_kind="local",
    display_name="MapleSure mockapp — coverage tier upgrade (CR-2026-041)",
    root=REPO_ROOT / "mockapp",
    cr_template_path=REPO_ROOT / "mockapp" / "crs" / "CR-2026-041.md",
    core_files=(
        "mockapp/core/models.py",
        "mockapp/core/db.py",
        "mockapp/core/coverage.py",
        "mockapp/app.py",
    ),
    never_extra=frozenset({"mockapp/core/seed.py"}),
    codegen_allowlist=(
        "mockapp/core/models.py",
        "mockapp/core/db.py",
        "mockapp/core/coverage.py",
        "mockapp/app.py",
    ),
    testgen_allowlist=("tests/test_s3_coverage_upgrade.py",),
    harness_expected_files=(
        "mockapp/core/models.py",
        "mockapp/core/db.py",
        "mockapp/core/coverage.py",
        "mockapp/app.py",
        "tests/test_s3_coverage_upgrade.py",
    ),
    cache_namespace="",
)
register_target(MOCKAPP_COVERAGE_UPGRADE)


def get_target(target_id: str | None) -> Target:
    """Resolve a target by id, defaulting to today's one demo target."""
    return _REGISTRY[target_id or DEFAULT_TARGET_ID]

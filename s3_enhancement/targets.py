"""S3 target registry — the seam that lets S3 scale beyond one repo/one CR.

Every S3 module today (`codegen.py`, `testgen.py`, `harness.py`, `cr.py`,
`analyze.py`, `docgen.py`) is hardcoded to CR-2026-041 against `apps/policycore/`: file
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

from s3_enhancement import applications

REPO_ROOT = Path(__file__).resolve().parents[1]

# Legacy cache-key literals, preserved verbatim so the default target's cache
# identity never changes. Keyed by beat name, not derived by formula.
_LEGACY_CACHE_KEYS: dict[str, str] = {
    "impact_analysis": "s3_impact_analysis:coverage_upgrade:v2",
    "effort_estimate": "s3_effort_estimate:coverage_upgrade:v2",
    "release_notes": "s3_release_notes:coverage_upgrade",
    # Added after the above three shipped — no pre-existing recording to stay
    # byte-identical with, so this literal isn't "legacy" in the same sense,
    # just following the same naming convention for the default target.
    "cross_team_impact": "s3_cross_team_impact:coverage_upgrade:v1",
    "design_doc": "s3_design_doc:coverage_upgrade:v1",
    "test_scenarios": "s3_test_scenarios:coverage_upgrade:v1",
    "release_note_set": "s3_release_note_set:coverage_upgrade:v1",
}
_LEGACY_STREAM_CACHE_KEYS: dict[str, str] = {
    "codegen": "s3_codegen",
    "testgen": "s3_testgen",
}


@dataclass(frozen=True)
class Mutation:
    """One seeded, revertible bug for the "prove the tests catch bugs" beat.

    `old_snippet` must appear verbatim in the target's *generated* code (the
    replay caches make that deterministic for the demo); the endpoint applies
    the first candidate whose snippet is present, runs the generated suite,
    and always restores the original content afterwards. A candidate whose
    snippet has drifted out of the generated code is skipped, never guessed
    at — if none match, the beat fails loudly instead of mutating blind.
    """

    rel_path: str
    old_snippet: str
    new_snippet: str
    description: str


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

    # Application (ServiceNow CI) this target's code belongs to, as an
    # `applications.Application.app_id`. Several targets can share one
    # application — a CI identifies the app, and the CR text picks the change
    # within it (see s3_enhancement/applications.py). Empty means the target
    # predates the routing registry and is reachable only by explicit
    # target_id, never by CI.
    application_id: str = ""

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

    # Language of the target's source and generated tests. Drives which
    # content validators codegen/testgen apply (ast.parse is Python-only) and
    # which test runner the /s3/tests beat uses.
    language: Literal["python", "java"] = "python"
    # Runs after any proposal file under this target's root is applied to the
    # working tree — the migration/refresh step that keeps the running app
    # consistent with just-applied code (e.g. rebuilding the mockapp SQLite
    # schema so a CR that adds a column doesn't crash the portal). The
    # literal "{python}" element is replaced with the current interpreter at
    # run time. Every new local target that owns runtime state MUST declare
    # this — the apply endpoint resolves it by root, so sibling targets on
    # the same root inherit it automatically.
    post_apply_command: tuple[str, ...] = ()
    # Test command for the /s3/tests beat. Empty means the default
    # `pytest testgen_allowlist[0]` invocation; a non-empty command runs
    # verbatim from `test_cwd` (e.g. Maven for a Java target).
    test_command: tuple[str, ...] = ()
    test_cwd: Path | None = None

    # The target app's checked-in, human-authored regression suite — the tests
    # that existed *before* this CR and must still pass after it. Deliberately
    # separate from testgen_allowlist: nothing in the S3 pipeline may write to
    # these paths, which is what makes "the pre-existing tests still pass" a
    # result rather than a promise. `regression_paths` is the pytest form;
    # `regression_command`/`regression_cwd` mirror test_command/test_cwd for a
    # target whose regression suite runs under another runner. Empty means the
    # target has no regression suite and the console hides the beat.
    regression_paths: tuple[str, ...] = ()
    regression_command: tuple[str, ...] = ()
    regression_cwd: Path | None = None

    # Seeded bugs for the /s3/tests/mutation beat, tried in declaration order
    # (see Mutation). Empty means the beat is unavailable for this target.
    mutations: tuple[Mutation, ...] = ()

    cache_namespace: str = ""

    @property
    def has_regression_suite(self) -> bool:
        return bool(self.regression_paths or self.regression_command)

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
    if target.application_id:
        try:
            applications.get_application(target.application_id)
        except KeyError:
            raise ValueError(
                f"target {target.target_id!r} names unknown application "
                f"{target.application_id!r}"
            ) from None
    _REGISTRY[target.target_id] = target
    if target.cache_namespace:
        _NAMESPACES[target.cache_namespace] = target.target_id


DEFAULT_TARGET_ID = "mockapp-coverage-upgrade"

MOCKAPP_COVERAGE_UPGRADE = Target(
    target_id=DEFAULT_TARGET_ID,
    source_kind="local",
    display_name="MapleSure mockapp — coverage tier upgrade (CR-2026-041)",
    application_id=applications.POLICY_CORE_ID,
    root=REPO_ROOT / "apps" / "policycore",
    cr_template_path=REPO_ROOT / "apps" / "policycore" / "crs" / "CR-2026-041.md",
    core_files=(
        "apps/policycore/core/models.py",
        "apps/policycore/core/db.py",
        "apps/policycore/core/coverage.py",
        "apps/policycore/app.py",
    ),
    never_extra=frozenset({"apps/policycore/core/seed.py"}),
    codegen_allowlist=(
        "apps/policycore/core/models.py",
        "apps/policycore/core/db.py",
        "apps/policycore/core/coverage.py",
        "apps/policycore/app.py",
    ),
    testgen_allowlist=("tests/test_s3_coverage_upgrade.py",),
    regression_paths=("tests/test_regression_policycore.py",),
    harness_expected_files=(
        "apps/policycore/core/models.py",
        "apps/policycore/core/db.py",
        "apps/policycore/core/coverage.py",
        "apps/policycore/app.py",
        "tests/test_s3_coverage_upgrade.py",
    ),
    post_apply_command=("{python}", "-m", "apps.policycore.core.seed"),
    mutations=(
        Mutation(
            rel_path="apps/policycore/core/coverage.py",
            old_snippet="if new_index <= old_index:",
            new_snippet="if new_index < old_index:",
            description=(
                "Weakened the same-tier/downgrade guard from `<=` to `<` — "
                "a same-tier \"upgrade\" is now silently accepted instead of "
                "raising ValueError."
            ),
        ),
    ),
    cache_namespace="",
)
register_target(MOCKAPP_COVERAGE_UPGRADE)

ENDORSEMENT_TARGET_ID = "mockapp-endorsement-field-add"

MOCKAPP_ENDORSEMENT_FIELD_ADD = Target(
    target_id=ENDORSEMENT_TARGET_ID,
    source_kind="local",
    display_name="MapleSure mockapp — endorsement priority field (CR-2026-042)",
    application_id=applications.POLICY_CORE_ID,
    root=REPO_ROOT / "apps" / "policycore",
    cr_template_path=REPO_ROOT / "apps" / "policycore" / "crs" / "CR-2026-042.md",
    cr_placeholder="",  # this CR has no audience-picked placeholder token
    core_files=(
        "apps/policycore/core/models.py",
        "apps/policycore/core/db.py",
        "apps/policycore/core/endorsements.py",
        "apps/policycore/app.py",
    ),
    never_extra=frozenset({"apps/policycore/core/seed.py"}),
    codegen_allowlist=(
        "apps/policycore/core/models.py",
        "apps/policycore/core/db.py",
        "apps/policycore/core/endorsements.py",
        "apps/policycore/app.py",
    ),
    testgen_allowlist=("tests/test_s3_endorsement_priority.py",),
    regression_paths=("tests/test_regression_policycore.py",),
    harness_expected_files=(),
    post_apply_command=("{python}", "-m", "apps.policycore.core.seed"),
    mutations=(
        Mutation(
            rel_path="apps/policycore/core/endorsements.py",
            old_snippet='priority: str = "Standard",',
            new_snippet='priority: str = "Urgent",',
            description=(
                'Flipped the default priority from "Standard" to "Urgent" — '
                "endorsements submitted without an explicit priority are now "
                "silently marked Urgent."
            ),
        ),
    ),
    cache_namespace="endorsement_field_add",
)
register_target(MOCKAPP_ENDORSEMENT_FIELD_ADD)


SPRING_TARGET_ID = "springdemo-claims-deductible"

_SPRING_ROOT = REPO_ROOT / "apps" / "claimsportal"
_SPRING_CLAIMS_SRC = "apps/claimsportal/claims-service/src/main/java/com/maplesure/claims"
_SPRING_POLICY_SRC = "apps/claimsportal/policy-service/src/main/java/com/maplesure/policy"

SPRINGDEMO_CLAIMS_DEDUCTIBLE = Target(
    target_id=SPRING_TARGET_ID,
    source_kind="local",
    display_name="ClaimsPortal (Spring Boot) — claims deductible handling (CR-2026-043)",
    application_id=applications.CLAIMS_PORTAL_ID,
    root=_SPRING_ROOT,
    cr_template_path=_SPRING_ROOT / "crs" / "CR-2026-043.md",
    cr_placeholder="",  # like CR-2026-042, no audience-picked placeholder token
    core_files=(
        f"{_SPRING_POLICY_SRC}/Policy.java",
        f"{_SPRING_POLICY_SRC}/PolicyController.java",
        f"{_SPRING_CLAIMS_SRC}/Claim.java",
        f"{_SPRING_CLAIMS_SRC}/PolicyClient.java",
        f"{_SPRING_CLAIMS_SRC}/ClaimsController.java",
        # Does not exist until the CR creates it — same idiom as
        # apps/policycore/core/coverage.py on the default target.
        f"{_SPRING_CLAIMS_SRC}/ClaimRules.java",
    ),
    codegen_allowlist=(
        f"{_SPRING_POLICY_SRC}/Policy.java",
        f"{_SPRING_POLICY_SRC}/PolicyController.java",
        f"{_SPRING_CLAIMS_SRC}/Claim.java",
        f"{_SPRING_CLAIMS_SRC}/PolicyClient.java",
        f"{_SPRING_CLAIMS_SRC}/ClaimsController.java",
        f"{_SPRING_CLAIMS_SRC}/ClaimRules.java",
    ),
    testgen_allowlist=(
        "apps/claimsportal/claims-service/src/test/java/com/maplesure/claims/"
        "ClaimRulesTest.java",
    ),
    harness_expected_files=(),
    language="java",
    test_command=("mvn", "-q", "-Dtest=ClaimRulesTest", "test"),
    test_cwd=_SPRING_ROOT / "claims-service",
    # policy-service, not claims-service: CR-2026-043 edits both, and the
    # regression risk that matters is the existing policy lookup API the
    # claims side binds to over HTTP. The generated ClaimRulesTest covers the
    # new deductible rules; this covers what was already there.
    regression_command=("mvn", "-q", "-Dtest=PolicyApiRegressionTest", "test"),
    regression_cwd=_SPRING_ROOT / "policy-service",
    mutations=(
        Mutation(
            rel_path=f"{_SPRING_CLAIMS_SRC}/ClaimRules.java",
            old_snippet="if (amount.compareTo(deductible) <= 0) {",
            new_snippet="if (amount.compareTo(deductible) < 0) {",
            description=(
                "Weakened the deductible boundary check from `<=` to `<` — "
                "a claim for exactly the deductible amount is now accepted "
                "instead of rejected below-deductible."
            ),
        ),
    ),
    cache_namespace="spring_claims_deductible",
)
register_target(SPRINGDEMO_CLAIMS_DEDUCTIBLE)


def get_target(target_id: str | None) -> Target:
    """Resolve a target by id, defaulting to today's one demo target."""
    return _REGISTRY[target_id or DEFAULT_TARGET_ID]


def all_targets() -> tuple[Target, ...]:
    """Every registered target — used by the apply endpoint to resolve which
    target's post_apply_command a just-applied file set belongs to, keyed by
    root, so the migration step runs for any current or future CR without
    the API needing to be told the target explicitly."""
    return tuple(_REGISTRY.values())


def targets_for_application(app_id: str) -> tuple[Target, ...]:
    """Every registered target belonging to one application, in registration
    order. Routing narrows a ticket to an application; this is the candidate
    set of changes S3 could run against it. Empty means the application is
    routable but has no automation (see applications.Application)."""
    return tuple(t for t in _REGISTRY.values() if t.application_id == app_id)


def post_apply_commands_for(applied_files: list[str], repo_root: Path) -> list[tuple[str, ...]]:
    """The distinct post-apply commands owed for this applied file set.

    Matched by target root (not target id): a proposal's files identify which
    local app they belong to, and every registered target rooted there
    contributes its declared post_apply_command. Sibling targets sharing a
    root therefore inherit each other's migration step — a new mockapp CR is
    covered even before its author thinks about schema drift.
    """
    commands: list[tuple[str, ...]] = []
    for target in all_targets():
        if target.root is None or not target.post_apply_command:
            continue
        try:
            prefix = target.root.relative_to(repo_root).as_posix() + "/"
        except ValueError:
            continue
        if any(path.startswith(prefix) for path in applied_files):
            if target.post_apply_command not in commands:
                commands.append(target.post_apply_command)
    return commands

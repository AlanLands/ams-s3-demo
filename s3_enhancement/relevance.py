"""File-relevance selection for S3's codegen/analysis prompts.

Scopes the LLM's context to a small, CR-relevant subset of `mockapp/`
instead of concatenating every file's full content into every prompt. This
is what lets S3 scale to a realistic ~100-file app without token usage
growing linearly with app size — the concern this module exists to answer.

Selection runs in two stages:

1. **Subsystem screening** (`screen_subsystems`): each subsystem under
   `mockapp/systems/` ships a `DESIGN.md` declaring its scope. A subsystem
   scoring below `min_score` against the CR is screened out entirely —
   none of its source files are even opened for stage 2. This is what lets
   the demo say "the AI reads the design docs first" rather than "the AI
   opened every file and scored it."
2. **File-level ranking** (`select_relevant_files`) and subsystem screening
   (`screen_subsystems`) score real prose (DESIGN.md scope keywords, file
   content) against the CR text, so both prefer real semantic embeddings
   (`common/vectorstore.py`, the shared local vector store) over TF-IDF
   bag-of-words, falling back to TF-IDF only if the embedding backend is
   unavailable. `_rank_gitlab_paths_by_cr` (the path-only GitLab pre-rank,
   below) stays TF-IDF-only on purpose: it scores bare path segments
   ("src billing export py"), not prose, and short literal path tokens are
   a poor fit for a sentence-embedding model built for natural-language
   similarity -- run only over whatever survives stage 1.

   The two backends' cosine-similarity scales differ: embedding similarity
   for topically-unrelated text still tends to sit noticeably above zero
   (empirically ~0.3-0.45 for this repo's own decoy subsystems/files against
   the real CR text), where TF-IDF's sparse cosine sits much closer to zero
   for the same pairs. Every `min_score` below is a `float | None` --
   `None` (the default) resolves to the threshold calibrated for whichever
   backend actually serves the request; an explicit value overrides that for
   either backend.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from common.gitlab_client import get_client
from common.llm import LLMError
from common.vectorstore import VectorStoreError, embed_corpus, semantic_search
from s3_enhancement import targets
from s3_enhancement.targets import Target

REPO_ROOT = Path(__file__).resolve().parents[1]
MOCKAPP_ROOT = REPO_ROOT / "mockapp"

# The files CR-2026-041 actually needs — always included as prompt context
# regardless of what the relevance scorer says, and always required back in
# the model's response (see codegen.py's _validate_file_set). This is the
# safety net that keeps the demo from ever flaking on the real files.
# mockapp/core/coverage.py does not exist until the CR creates it — it's
# still a core file, just with empty pre-CR content (mirrors how the
# original hardcoded-allowlist prompt handled a not-yet-existing file).
# Bound to the default Target so there's one source of truth across S3's
# modules (see s3_enhancement/targets.py) — value is unchanged from before.
CORE_FILES: tuple[str, ...] = targets.MOCKAPP_COVERAGE_UPGRADE.core_files

# Structurally off-limits regardless of relevance score: seed.py constructs
# Policy(...) with 6 fixed positional args (see codegen.py's
# _validate_policy_backward_compatible) and must never be an editable file,
# even though it scores highest of any candidate against the CR text (it's
# the file most densely full of Policy field names). Still counted in
# discover_mockapp_files() for an honest total-app-size figure — just never
# eligible to be selected as extra editable context.
NEVER_EXTRA: frozenset[str] = targets.MOCKAPP_COVERAGE_UPGRADE.never_extra

# "target" is Maven's build-output directory (the Spring Boot target's root
# contains two Maven services) and ".baseline" is that target's pristine
# pre-CR snapshot (demo/reset_s3_springdemo.sh restores from it) — sources
# under either must never enter the candidate pool, same reasoning as
# __pycache__ for Python.
_EXCLUDED_DIR_NAMES = {"__pycache__", "target", ".baseline"}
_SOURCE_GLOBS = ("*.py", "*.java")


@dataclass(frozen=True)
class SubsystemScreen:
    """Result of scoring each `mockapp/systems/*/DESIGN.md` against the CR,
    before any individual source file is opened for stage-2 ranking."""

    in_scope: tuple[str, ...]
    screened_out: tuple[str, ...]
    scores: dict[str, float]


@dataclass(frozen=True)
class SelectionResult:
    """Files fed to the LLM as context, plus bookkeeping for the UI's "why
    these files" panel and the scoped-vs-naive token-count comparison."""

    selected: dict[str, str]
    core_files: tuple[str, ...]
    extra_files: tuple[str, ...]
    candidate_pool_size: int
    candidate_pool_by_language: dict[str, int]
    scores: dict[str, float]
    subsystem_screen: SubsystemScreen


def discover_mockapp_files(root: Path = MOCKAPP_ROOT) -> dict[str, str]:
    """Read every .py/.java file under `root`, keyed by its path relative to
    `key_base` (matching CORE_FILES's "mockapp/..." convention for the default
    target — every entry is keyed relative to this repo's root, not to
    `root` itself, since `root` is only the glob directory).

    A local glob rather than `s4_knowledge.snapshot_reader.snapshot_files()`
    because that helper only globs `*.py` — mockapp/ now also contains Java
    decoy files under mockapp/systems/, and s4_knowledge's helper stays
    Python-only since S4 has no reason to touch Java. Empty __init__.py
    package markers are skipped, same convention as snapshot_reader.

    `root` defaults to `mockapp/` (today's one local target); a second local
    `Target` would pass its own `root` here via `discover_files_for_target`.
    For a `root` that isn't under this repo (e.g. a synthetic target rooted
    elsewhere on disk, as in tests), keys are relative to `root` itself
    instead — there's no meaningful "repo-relative" path to fall back to.
    """
    key_base = REPO_ROOT if root.is_relative_to(REPO_ROOT) else root
    files: dict[str, str] = {}
    for pattern in _SOURCE_GLOBS:
        for path in sorted(root.rglob(pattern)):
            if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
                continue
            content = path.read_text(encoding="utf-8")
            if path.name == "__init__.py" and not content.strip():
                continue
            rel = path.relative_to(key_base).as_posix()
            files[rel] = content
    return files


_GITLAB_SOURCE_EXTENSIONS = (".py", ".java", ".js", ".ts", ".go", ".rb", ".cs", ".rs")
_GITLAB_EXCLUDED_PATH_PARTS = ("node_modules/", "vendor/", "/dist/", "/build/", ".min.js")


def _looks_like_gitlab_source(path: str) -> bool:
    if not path.endswith(_GITLAB_SOURCE_EXTENSIONS):
        return False
    return not any(part in path for part in _GITLAB_EXCLUDED_PATH_PARTS)


def _rank_gitlab_paths_by_cr(cr_text: str, paths: list[str]) -> list[str]:
    """Path-only relevance pre-rank — no file content read yet. Splits each
    path into path-segment "words" (dropping `/`, `_`, `.`) so TF-IDF has
    real tokens to score instead of one opaque string per path. This is the
    step that keeps a big GitLab repo from ever costing more than a handful
    of small HTTP GETs: only the resulting shortlist gets its content
    fetched at all."""
    if not paths:
        return []
    tokenized = [path.replace("/", " ").replace("_", " ").replace(".", " ") for path in paths]
    vectors = TfidfVectorizer(stop_words="english", ngram_range=(1, 2)).fit_transform(
        [cr_text, *tokenized]
    )
    scores = cosine_similarity(vectors[0:1], vectors[1:]).flatten()
    ranked = sorted(zip(paths, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    return [path for path, _score in ranked]


def discover_gitlab_files(
    project_id: int | str,
    cr_text: str,
    *,
    ref: str = "main",
    max_candidates: int = 20,
) -> dict[str, str]:
    """GitLab-backed sibling of `discover_mockapp_files()`: produces the same
    `{path: content}` shape `select_relevant_files()` already consumes, but
    without ever pulling a whole repository into memory or a prompt.

    Two-tier funnel, same spirit as mockapp's subsystem-then-file screening:
    1. List every file path in the target repo (cheap — no content) via
       `common.gitlab_client`, then rank paths against the CR text by a
       lightweight TF-IDF pass over paths alone, keeping only the top
       `max_candidates` (default 20). This is what keeps a 20-repo GitLab
       account from ever costing more than a handful of small HTTP GETs,
       regardless of any individual repo's actual size.
    2. Fetch content for only that shortlist, then hand the result straight
       to `select_relevant_files()` (with `core_files=()`, `design_docs={}}`
       — a GitLab repo has neither mockapp's core-file contract nor its
       DESIGN.md subsystem docs) for the final content-aware ranking down
       to a handful of files that actually reach an LLM prompt.
    """
    client = get_client()
    paths = [path for path in client.list_repo_paths(project_id) if _looks_like_gitlab_source(path)]
    if not paths:
        return {}

    shortlist = _rank_gitlab_paths_by_cr(cr_text, paths)[:max_candidates]
    return client.fetch_files(project_id, shortlist, ref=ref)


def discover_files_for_target(target: Target, cr_text: str) -> dict[str, str]:
    """Dispatch discovery to the strategy matching `target.source_kind` — the
    seam that lets a caller (codegen/testgen/analyze) work against any
    registered target instead of always reading mockapp/ directly."""
    if target.source_kind == "local":
        return discover_mockapp_files(target.root)
    return discover_gitlab_files(target.project_id, cr_text, ref=target.ref)


def _document(rel_path: str, content: str) -> str:
    # The path carries real signal (subsystem name, filename) that content
    # alone loses weight on across ~100 similarly-shaped decoy files.
    return f"{rel_path} {content}"


_SCOPE_KEYWORDS_RE = re.compile(r"^## Scope keywords\s*\n(.*?)(?=\n## |\Z)", re.S | re.M)
_DESIGN_DOC_NAME = "DESIGN.md"


def discover_subsystem_design_docs(root: Path = MOCKAPP_ROOT) -> dict[str, str]:
    """Read every `DESIGN.md` under `root`, keyed by the repo-relative path of
    its parent (subsystem) directory.

    Each doc's "## Scope keywords" section (short, deliberately written in
    that subsystem's own domain vocabulary rather than the CR's) is what
    `screen_subsystems` actually scores — falling back to the whole doc if a
    design doc omits that section, since a doc without declared keywords
    should still be considered, not silently skipped.

    `root` defaults to `mockapp/` — today's one design-doc-bearing target —
    but MUST be the scoring target's own root whenever there is one (see
    `select_relevant_files`'s `design_doc_root`). Globbing mockapp/
    unconditionally meant a target rooted anywhere else (the Spring
    ClaimsPortal) got screened against mockapp's decoy subsystems, and the
    UI's "which part of the repo the AI matched this change to" panel then
    named a mockapp legacy subsystem for a change that never touched
    mockapp. A root with no design docs correctly yields `{}`, which
    `screen_subsystems` turns into an empty screen that excludes nothing.

    Keys are relative to this repo's root, matching the "mockapp/..."
    convention the rest of this module uses; for a `root` outside the repo
    (a synthetic target rooted elsewhere, as in tests) they're relative to
    `root` itself instead — same fallback as `discover_mockapp_files`.
    """
    key_base = REPO_ROOT if root.is_relative_to(REPO_ROOT) else root
    docs: dict[str, str] = {}
    for path in sorted(root.rglob(_DESIGN_DOC_NAME)):
        # Same exclusions as the source glob: a design doc inside a target's
        # pristine `.baseline/` snapshot is a copy of one already counted,
        # not a second subsystem.
        if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        rel_dir = path.parent.relative_to(key_base).as_posix()
        docs[rel_dir] = _extract_scope_keywords(path.read_text(encoding="utf-8"))
    return docs


def _extract_scope_keywords(design_doc_text: str) -> str:
    match = _SCOPE_KEYWORDS_RE.search(design_doc_text)
    return match.group(1).strip() if match else design_doc_text


# Empirically measured against this repo's own decoy subsystems: the six
# mockapp/systems/legacy_java_platform/* DESIGN.md docs top out at 0.336
# cosine similarity against the real CR-2026-041 text (settlement, the
# closest decoy) -- well above where TF-IDF's sparse cosine sits for the same
# pairs (<= 0.012). 0.45 sits with margin above that decoy ceiling; re-verify
# against test_s3_relevance.py's "screens out every legacy subsystem"
# assertion before lowering this.
_SUBSYSTEM_VECTOR_MIN_SCORE_DEFAULT = 0.45
_SUBSYSTEM_TFIDF_MIN_SCORE_DEFAULT = 0.05
_SUBSYSTEM_COLLECTION_NAME = "s3_subsystem_design_docs"


def _screen_subsystems_vector(
    cr_text: str, design_docs: dict[str, str], min_score: float
) -> SubsystemScreen:
    names = list(design_docs)
    embed_corpus(_SUBSYSTEM_COLLECTION_NAME, names, [design_docs[n] for n in names], None)
    hits = semantic_search(_SUBSYSTEM_COLLECTION_NAME, cr_text, n_results=len(names))
    scores = {hit.id: round(hit.score, 4) for hit in hits}

    in_scope = tuple(sorted(name for name in names if scores[name] >= min_score))
    screened_out = tuple(sorted(name for name in names if scores[name] < min_score))
    return SubsystemScreen(in_scope=in_scope, screened_out=screened_out, scores=scores)


def _screen_subsystems_tfidf(
    cr_text: str, design_docs: dict[str, str], min_score: float
) -> SubsystemScreen:
    names = list(design_docs)
    documents = [cr_text, *(design_docs[name] for name in names)]
    vectors = TfidfVectorizer(stop_words="english", ngram_range=(1, 2)).fit_transform(documents)
    raw_scores = cosine_similarity(vectors[0:1], vectors[1:]).flatten()
    scores = {
        name: round(float(score), 4) for name, score in zip(names, raw_scores, strict=True)
    }

    in_scope = tuple(sorted(name for name in names if scores[name] >= min_score))
    screened_out = tuple(sorted(name for name in names if scores[name] < min_score))
    return SubsystemScreen(in_scope=in_scope, screened_out=screened_out, scores=scores)


def screen_subsystems(
    cr_text: str,
    design_docs: dict[str, str],
    *,
    min_score: float | None = None,
) -> SubsystemScreen:
    """Score each subsystem's design doc against the CR text (embeddings by
    default, TF-IDF cosine similarity fallback) and split subsystems into
    in-scope vs screened-out.

    `min_score=None` (the default) picks the threshold calibrated for
    whichever backend actually serves the request — well above each
    backend's empirically measured ceiling for these decoy subsystems'
    design docs, but a genuinely low bar otherwise: a subsystem doc that
    shares real terms with the CR clears it easily, so a real signal is
    never mistaken for noise.
    """
    if not design_docs:
        return SubsystemScreen(in_scope=(), screened_out=(), scores={})

    try:
        floor = _SUBSYSTEM_VECTOR_MIN_SCORE_DEFAULT if min_score is None else min_score
        return _screen_subsystems_vector(cr_text, design_docs, floor)
    except VectorStoreError:
        floor = _SUBSYSTEM_TFIDF_MIN_SCORE_DEFAULT if min_score is None else min_score
        return _screen_subsystems_tfidf(cr_text, design_docs, floor)


# Empirically measured: this repo's one non-core, non-decoy mockapp/ file
# (mockapp/core/claims.py) scores 0.4501 embedding cosine similarity against
# CR-2026-041's real text -- domain-adjacent (both insurance/policy vocabulary)
# but not what the CR is actually about. 0.55 sits above that with margin;
# re-verify against test_s3_relevance.py's "selects only core files" assertion
# before lowering this.
_FILE_VECTOR_MIN_SCORE_DEFAULT = 0.55
_FILE_TFIDF_MIN_SCORE_DEFAULT = 0.15
_FILE_COLLECTION_NAME = "s3_file_candidates"


def _score_file_candidates(
    cr_text: str, candidates: dict[str, str], min_score: float | None
) -> tuple[dict[str, float], float]:
    """Score every candidate file against `cr_text` (embeddings by default,
    TF-IDF cosine similarity fallback). Returns the full unfiltered score map
    (used as-is for the UI's "why these files" panel) plus the floor that
    should be applied to it -- resolved here since which floor applies
    depends on which backend actually served the request."""
    if not candidates:
        return {}, 0.0

    try:
        floor = _FILE_VECTOR_MIN_SCORE_DEFAULT if min_score is None else min_score
        ids = list(candidates)
        documents = [_document(path, candidates[path]) for path in ids]
        embed_corpus(_FILE_COLLECTION_NAME, ids, documents, None)
        query_doc = _document("CR-2026-041", cr_text)
        hits = semantic_search(_FILE_COLLECTION_NAME, query_doc, n_results=len(ids))
        return {hit.id: round(hit.score, 4) for hit in hits}, floor
    except VectorStoreError:
        floor = _FILE_TFIDF_MIN_SCORE_DEFAULT if min_score is None else min_score
        candidate_paths = list(candidates)
        documents = [
            _document("CR-2026-041", cr_text),
            *(_document(path, candidates[path]) for path in candidate_paths),
        ]
        vectors = TfidfVectorizer(stop_words="english", ngram_range=(1, 2)).fit_transform(
            documents
        )
        raw_scores = cosine_similarity(vectors[0:1], vectors[1:]).flatten()
        scores = {
            path: round(float(score), 4)
            for path, score in zip(candidate_paths, raw_scores, strict=True)
        }
        return scores, floor


def select_relevant_files(
    cr_text: str,
    all_files: dict[str, str],
    *,
    core_files: tuple[str, ...] = CORE_FILES,
    max_extra: int = 4,
    min_score: float | None = None,
    design_docs: dict[str, str] | None = None,
    design_doc_root: Path | None = None,
) -> SelectionResult:
    """Screen subsystems by design doc, then rank the surviving mockapp/
    files by semantic similarity to the CR text (embeddings by default,
    TF-IDF cosine similarity fallback), returning the core files (always
    included, empty content if the file doesn't exist yet) plus up to
    `max_extra` other files scoring at or above `min_score`.

    `min_score=None` (the default) picks the threshold calibrated for
    whichever backend actually serves the request — well above the demo
    corpus's decoy ceiling for that backend but below genuinely relevant
    files, so a real signal is never mistaken for noise.

    `design_docs` defaults to whatever `discover_subsystem_design_docs()`
    finds under `design_doc_root` — passed explicitly by callers that already
    loaded it once (e.g. the UI panel) to avoid re-reading the same handful
    of small files repeatedly, or as `{}` by callers that have none at all
    (the GitLab path).

    `design_doc_root` MUST be the scoring target's own root
    (`Target.root`) whenever the caller has a target in hand; it falls back
    to `mockapp/` only for the target-less callers (tests, tools, the legacy
    Streamlit console) that are inherently scoped to mockapp. Screening a
    non-mockapp target against mockapp's subsystem docs is a reporting bug,
    not a no-op — see `discover_subsystem_design_docs`.
    """
    if design_docs is None:
        design_docs = discover_subsystem_design_docs(
            MOCKAPP_ROOT if design_doc_root is None else design_doc_root
        )
    subsystem_screen = screen_subsystems(cr_text, design_docs)
    screened_out_prefixes = tuple(f"{name}/" for name in subsystem_screen.screened_out)

    excluded = set(core_files) | NEVER_EXTRA
    candidates = {
        path: content
        for path, content in all_files.items()
        if path not in excluded and not path.startswith(screened_out_prefixes)
    }
    scores, floor = _score_file_candidates(cr_text, candidates, min_score)

    ranked_extra = sorted(
        (path for path, score in scores.items() if score >= floor),
        key=lambda path: (scores[path], path),
        reverse=True,
    )[:max_extra]

    selected: dict[str, str] = {path: all_files.get(path, "") for path in core_files}
    for path in ranked_extra:
        selected[path] = all_files[path]

    by_language = {"python": 0, "java": 0}
    for path in all_files:
        if path.endswith(".java"):
            by_language["java"] += 1
        elif path.endswith(".py"):
            by_language["python"] += 1

    return SelectionResult(
        selected=selected,
        core_files=core_files,
        extra_files=tuple(ranked_extra),
        candidate_pool_size=len(all_files),
        candidate_pool_by_language=by_language,
        scores=scores,
        subsystem_screen=subsystem_screen,
    )


def verify_core_recall(
    present_paths: Iterable[str], *, core_files: tuple[str, ...] = CORE_FILES
) -> None:
    """Raise if any required core file is missing from `present_paths`.

    Reused in two places: against a `SelectionResult` (a sanity check —
    the construction above always satisfies it by design) and, more
    meaningfully, against the LLM's actual JSON response file set in
    `codegen.py::_validate_file_set` — the thing that actually keeps this
    demo from flaking if a live model ever drops a required file.
    """
    missing = [path for path in core_files if path not in set(present_paths)]
    if missing:
        raise LLMError(f"relevance check: missing required core file(s): {sorted(missing)}")


def estimate_tokens(text: str) -> int:
    """Rough ~4-chars/token heuristic — NOT a real tokenizer. Used only for
    the illustrative naive-whole-app-context comparison; a real billed
    number always comes from the provider's own reported usage instead.
    """
    return max(1, len(text) // 4)


def naive_prompt_tokens(
    scoped_input_tokens: int | None,
    all_files: dict[str, str],
    selected: dict[str, str] | None = None,
) -> int:
    """What the same prompt would have cost with the whole app pasted in
    instead of just the selected files.

    The naive prompt is the scoped prompt with every file substituted for
    the selected ones, so it differs from what was actually billed by
    exactly the *unselected* files' contents — everything else (system
    prompt, CR text, task instructions) is identical and must not be
    dropped from one side of the comparison. Summing all file bodies alone
    was the earlier approach and it compared a full prompt against bare
    source: it undercounted the naive side by the whole prompt scaffold, so
    a target where scoping selects every file (the Spring demo's 8 of 8)
    reported the naive baseline as *cheaper* than what was actually spent.

    Falls back to summing every file when there's no scoped number to build
    on (a replay recording with no usage), which is the best available
    answer — the panel renders it as an estimate either way.
    """
    if selected is None or scoped_input_tokens is None:
        return sum(estimate_tokens(content) for content in all_files.values())
    unselected = sum(
        estimate_tokens(content) for path, content in all_files.items() if path not in selected
    )
    return scoped_input_tokens + unselected

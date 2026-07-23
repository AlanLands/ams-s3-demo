"""S1 capability 1.3 — deterministic similar-incident retrieval.

"Deterministic" here means same input -> same output, not "TF-IDF only": the
default backend is real semantic embeddings (`common/vectorstore.py`, the
shared local vector store, MiniLM run locally with no network call), falling
back to TF-IDF cosine similarity only if the embedding backend is
unavailable. Both are equally deterministic -- no randomness in either path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from common.schema import Incident
from common.vectorstore import VectorStoreError, embed_corpus, semantic_search

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, and drop English stopwords/single chars.

    Shared by the keyword-overlap scorers in resolution.py and chatbot.py so a
    stray trailing period on a short_description term (e.g. "password.") doesn't
    silently fail to match KB text that spells it "password" without one.
    """
    return {
        token
        for token in _TOKEN_RE.findall(text.lower())
        if token not in ENGLISH_STOP_WORDS and len(token) > 1
    }


@dataclass(frozen=True)
class SimilarIncident:
    incident_number: str
    similarity_score: float
    resolution_notes: str


def _document(incident: Incident) -> str:
    weighted_fields = [
        incident.application,
        incident.application,
        incident.category,
        incident.category,
        incident.subcategory,
        incident.short_description,
        incident.short_description,
        incident.description,
        incident.known_error_id,
        incident.problem_id,
    ]
    return " ".join(field for field in weighted_fields if field)


# Empirically measured against this demo's seeded clusters: cross-cluster
# incidents (different seed, same weighted-field document shape) land ~0.34-0.38
# cosine similarity -- higher than a topically-unrelated pair would, because the
# weighted fields share structural tokens across all incidents -- while real
# same-cluster matches (near-duplicate application/category/subcategory/
# known_error_id) run 1.0. 0.5 sits with margin above the cross-cluster ceiling
# and well below real matches; re-verify against SEEDS.md's seeded clusters
# (test_s1_similar_incidents.py) before lowering this.
_VECTOR_MIN_SCORE_DEFAULT = 0.5
_TFIDF_MIN_SCORE_DEFAULT = 0.05
_COLLECTION_NAME = "s1_similar_incidents"


def _rank_candidates_vector(
    incident: Incident, all_incidents: list[Incident], min_score: float
) -> list[tuple[Incident, float]]:
    """Indexes the full `all_incidents` corpus (including `incident` itself)
    rather than a self-excluded subset, then drops the self-match from the
    query results afterward. This matters for callers like S1's funnel
    metrics that call `find_similar` once per incident over the same corpus:
    the corpus embedded here is identical across every one of those calls, so
    `embed_corpus`'s content-hash cache actually hits after the first call --
    excluding a different row from the corpus on every call (as the old
    self-excluding-before-embedding approach did) would defeat that cache
    entirely, forcing a full re-embed on every single call."""
    ids = [row.number for row in all_incidents]
    documents = [_document(row) for row in all_incidents]
    embed_corpus(_COLLECTION_NAME, ids, documents, None)

    hits = semantic_search(_COLLECTION_NAME, _document(incident), n_results=len(all_incidents))
    by_number = {row.number: row for row in all_incidents}
    return [
        (by_number[hit.id], hit.score)
        for hit in hits
        if hit.id != incident.number and hit.score >= min_score
    ]


def _rank_candidates_tfidf(
    incident: Incident, candidates: list[Incident], min_score: float
) -> list[tuple[Incident, float]]:
    documents = [_document(incident), *[_document(candidate) for candidate in candidates]]
    vectors = TfidfVectorizer(stop_words="english", ngram_range=(1, 2)).fit_transform(documents)
    scores = cosine_similarity(vectors[0:1], vectors[1:]).flatten()
    return [
        (candidate, float(score))
        for candidate, score in zip(candidates, scores, strict=True)
        if score >= min_score
    ]


def find_similar(
    incident: Incident,
    all_incidents: list[Incident],
    top_n: int = 5,
    min_score: float | None = None,
) -> list[SimilarIncident]:
    """Rank prior incidents by semantic similarity (embeddings by default,
    TF-IDF cosine similarity fallback), dropping anything below `min_score`.
    Without a floor, an incident with no real precedent still returns
    `top_n` near-zero matches labeled "similar incidents" — technically the
    closest rows, but not actually similar to anything.

    `min_score=None` (the default) picks the threshold calibrated for
    whichever backend actually serves the request; pass an explicit value to
    override that for either backend.
    """
    candidates = [candidate for candidate in all_incidents if candidate.number != incident.number]
    if not candidates or top_n <= 0:
        return []

    try:
        floor = _VECTOR_MIN_SCORE_DEFAULT if min_score is None else min_score
        ranked_pairs = _rank_candidates_vector(incident, all_incidents, floor)
    except VectorStoreError:
        floor = _TFIDF_MIN_SCORE_DEFAULT if min_score is None else min_score
        ranked_pairs = _rank_candidates_tfidf(incident, candidates, floor)

    ranked = sorted(
        ranked_pairs,
        key=lambda item: (item[1], item[0].resolved_at, item[0].number),
        reverse=True,
    )
    return [
        SimilarIncident(
            incident_number=candidate.number,
            similarity_score=round(float(score), 4),
            resolution_notes=candidate.resolution_notes,
        )
        for candidate, score in ranked[:top_n]
    ]

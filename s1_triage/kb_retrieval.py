"""Chunked TF-IDF retrieval over KB/known-error articles.

Shared by resolution.py's RAG resolution draft and chatbot.py's talk-to-code
Q&A so both scenarios ground their prompts in the same retrieval quality
instead of three independent keyword scorers (the pre-2026-07-20 state).

Chunking splits each article on paragraph boundaries, carrying the article's
own title into every chunk so a chunk is self-describing on its own. A
paragraph that exceeds `max_chars` is further split with `overlap_chars` of
trailing context repeated into the next slice, so a fact sitting on a chunk
boundary is still retrievable from either side. This KB's current articles
are each one short paragraph, so today every article yields exactly one
chunk -- chunking should reflect a document's real structure, not manufacture
fragments a short article doesn't have. The mechanism holds once articles
grow past a single paragraph.

Retrieval scores chunks (not whole articles) by cosine similarity against
the query text, then re-ranks and caps how many chunks any single article can
contribute (`max_chunks_per_article`) so one long document can't crowd out
every other result -- the re-rank/dedup step a flat top-k lacks.

Scoring prefers real semantic embeddings (`common/vectorstore.py`, the shared
local vector store) over TF-IDF bag-of-words, falling back to TF-IDF only if
the embedding backend is unavailable. The two scoring scales differ --
embedding cosine similarity for topically unrelated short text still tends to
sit around 0.2-0.3 (empirically measured against this KB's own decoy
articles), well above where TF-IDF cosine sits for the same pairs -- so
`min_score`'s default is backend-dependent (`_VECTOR_MIN_SCORE_DEFAULT` /
`_TFIDF_MIN_SCORE_DEFAULT`) unless a caller passes an explicit value, which
then applies verbatim to whichever backend actually served the request.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from common.vectorstore import VectorStoreError, embed_corpus, semantic_search
from s1_triage.data_access import KbArticle

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_HEADING_RE = re.compile(r"^\s*#")


@dataclass(frozen=True)
class KbChunk:
    article_id: str
    title: str
    chunk_id: str
    text: str


def chunk_article(
    article: KbArticle, *, max_chars: int = 500, overlap_chars: int = 80
) -> list[KbChunk]:
    lines = article.text.splitlines()
    body = "\n".join(lines[1:]) if lines and _HEADING_RE.match(lines[0]) else article.text
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(body) if p.strip()]
    if not paragraphs:
        paragraphs = [article.title]

    raw_chunks: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            raw_chunks.append(paragraph)
            continue
        start = 0
        while True:
            end = start + max_chars
            raw_chunks.append(paragraph[start:end])
            if end >= len(paragraph):
                break
            start = end - overlap_chars

    return [
        KbChunk(
            article_id=article.article_id,
            title=article.title,
            chunk_id=f"{article.article_id}#{index}",
            text=text,
        )
        for index, text in enumerate(raw_chunks)
    ]


# Empirically measured (see module docstring): unrelated short chunks top out
# around 0.25-0.3 cosine similarity against a genuinely unrelated query; real
# matches on this KB's articles run 0.7+. 0.3 sits with margin above the decoy
# ceiling and well below real matches.
_VECTOR_MIN_SCORE_DEFAULT = 0.3
_TFIDF_MIN_SCORE_DEFAULT = 0.05
_COLLECTION_NAME = "s1_kb_chunks"


def _rank_chunks_vector(query_text: str, chunks: list[KbChunk], min_score: float) -> list[tuple]:
    ids = [chunk.chunk_id for chunk in chunks]
    documents = [f"{chunk.title} {chunk.text}" for chunk in chunks]
    metadatas = [{"article_id": chunk.article_id} for chunk in chunks]
    embed_corpus(_COLLECTION_NAME, ids, documents, metadatas)

    hits = semantic_search(_COLLECTION_NAME, query_text, n_results=len(chunks))
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    return [(by_id[hit.id], hit.score) for hit in hits if hit.score >= min_score]


def _rank_chunks_tfidf(query_text: str, chunks: list[KbChunk], min_score: float) -> list[tuple]:
    documents = [query_text, *[f"{chunk.title} {chunk.text}" for chunk in chunks]]
    vectors = TfidfVectorizer(stop_words="english", ngram_range=(1, 2)).fit_transform(documents)
    scores = cosine_similarity(vectors[0:1], vectors[1:]).flatten()
    return [
        (chunk, float(score))
        for chunk, score in zip(chunks, scores, strict=True)
        if score >= min_score
    ]


def select_relevant_chunks(
    query_text: str,
    kb_articles: list[KbArticle],
    *,
    top_k: int = 3,
    min_score: float | None = None,
    max_chunks_per_article: int = 2,
    max_chars: int = 500,
    overlap_chars: int = 80,
) -> list[KbChunk]:
    """Rank chunks across all articles by semantic similarity to `query_text`
    (embeddings by default, TF-IDF cosine similarity fallback), dropping
    anything below `min_score` and capping how many chunks any one article
    can contribute before moving on to the next-best match from a different
    article.

    `min_score=None` (the default) picks the threshold calibrated for
    whichever backend actually serves the request; pass an explicit value to
    override that for either backend (e.g. `min_score=0.0` to disable
    filtering entirely).
    """
    if not query_text.strip():
        return []

    chunks = [
        chunk
        for article in kb_articles
        for chunk in chunk_article(article, max_chars=max_chars, overlap_chars=overlap_chars)
    ]
    if not chunks:
        return []

    try:
        floor = _VECTOR_MIN_SCORE_DEFAULT if min_score is None else min_score
        ranked_pairs = _rank_chunks_vector(query_text, chunks, floor)
    except VectorStoreError:
        floor = _TFIDF_MIN_SCORE_DEFAULT if min_score is None else min_score
        ranked_pairs = _rank_chunks_tfidf(query_text, chunks, floor)

    ranked = sorted(ranked_pairs, key=lambda item: (item[1], item[0].chunk_id), reverse=True)

    selected: list[KbChunk] = []
    per_article: dict[str, int] = defaultdict(int)
    for chunk, _score in ranked:
        if per_article[chunk.article_id] >= max_chunks_per_article:
            continue
        selected.append(chunk)
        per_article[chunk.article_id] += 1
        if len(selected) >= top_k:
            break
    return selected

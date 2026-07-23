"""Shared local vector store (Chroma, on-disk) behind every semantic-retrieval
upgrade across S1/S2/S3/S4.

Local-first by design: the default embedding backend is Chroma's bundled ONNX
MiniLM-L6-v2 model (no API key, no network call at index/query time), so a
retrieval beat can't fail live the way a remote embeddings call could — same
"boring and reliable" bar the rest of this repo holds LLM calls to. Set
`EMBEDDING_PROVIDER=openai` to use OpenAI's `text-embedding-3-small` instead
(reuses `OPENAI_API_KEY` from `.env`).

The persistent index lives under `.cache/vectordb/` (gitignored, alongside
`.cache/llm/`) so it survives across process restarts but never gets checked
in. Every caller in this repo re-embeds its whole (small) corpus on each call
via `reset_collection` + `upsert` rather than incrementally maintaining an
index — correctness over cleverness at this corpus size (tens to low hundreds
of documents); the ONNX model is fast enough locally that this costs
milliseconds once warm.

**First run downloads the ~80MB ONNX model once** to
`~/.cache/chroma/onnx_models/` — see `demo/warm_vectorstore.sh` to pull it
down ahead of a live demo instead of depending on that download completing
live, exactly the same "cached output, live-call fallback never the reverse"
principle `CLAUDE.md` applies to LLM calls.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
VECTOR_DB_DIR = REPO_ROOT / ".cache" / "vectordb"


class VectorStoreError(RuntimeError):
    """Raised when the embedded vector store can't be built, written to, or
    queried. Every caller in this repo catches this and falls back to its
    TF-IDF/keyword implementation -- a vector-store hiccup must never be the
    reason a retrieval beat fails live."""


@dataclass(frozen=True)
class SearchHit:
    id: str
    document: str
    metadata: dict[str, Any]
    score: float  # cosine similarity, higher is better (1.0 = identical)


def _embedding_provider() -> str:
    return os.environ.get("EMBEDDING_PROVIDER", "local").strip().lower()


def _build_embedding_function():
    import chromadb.utils.embedding_functions as embedding_functions

    provider = _embedding_provider()
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise VectorStoreError("EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is not set.")
        return embedding_functions.OpenAIEmbeddingFunction(
            api_key=api_key, model_name="text-embedding-3-small"
        )
    return embedding_functions.DefaultEmbeddingFunction()


_lock = Lock()
_client = None
_embedding_fn = None


def _get_client():
    global _client
    with _lock:
        if _client is None:
            import chromadb

            VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
            _client = chromadb.PersistentClient(path=str(VECTOR_DB_DIR))
        return _client


def _get_embedding_function():
    global _embedding_fn
    with _lock:
        if _embedding_fn is None:
            _embedding_fn = _build_embedding_function()
        return _embedding_fn


def _get_collection(name: str):
    try:
        client = _get_client()
        return client.get_or_create_collection(
            name,
            embedding_function=_get_embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )
    except VectorStoreError:
        raise
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see module docstring
        raise VectorStoreError(f"vector store unavailable: {exc}") from exc


def reset_collection(name: str) -> None:
    """Drop and recreate a collection so a caller can re-embed its corpus from
    scratch on every call without accumulating stale/duplicate ids."""
    try:
        client = _get_client()
        try:
            client.delete_collection(name)
        except Exception:  # noqa: BLE001 -- collection may not exist yet
            pass
        client.get_or_create_collection(
            name,
            embedding_function=_get_embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )
    except VectorStoreError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"vector store unavailable: {exc}") from exc


def upsert(
    collection_name: str,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]] | None = None,
) -> None:
    if not ids:
        return
    collection = _get_collection(collection_name)
    try:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"vector upsert failed: {exc}") from exc


def semantic_search(
    collection_name: str,
    query_text: str,
    n_results: int = 10,
    where: dict[str, Any] | None = None,
) -> list[SearchHit]:
    collection = _get_collection(collection_name)
    try:
        count = collection.count()
        if count == 0:
            return []
        result = collection.query(
            query_texts=[query_text], n_results=min(n_results, count), where=where
        )
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"vector query failed: {exc}") from exc

    ids = result.get("ids") or [[]]
    docs = result.get("documents") or [[]]
    metas = result.get("metadatas") or [[]]
    dists = result.get("distances") or [[]]
    return [
        # Cosine space: distance = 1 - cosine_similarity.
        SearchHit(id=i, document=d or "", metadata=m or {}, score=1.0 - float(dist))
        for i, d, m, dist in zip(ids[0], docs[0], metas[0], dists[0], strict=True)
    ]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return raw embedding vectors for `texts`, bypassing the Chroma
    collection/search index entirely. For consumers that need the vectors
    themselves (e.g. S2's DBSCAN clustering) rather than a similarity search
    -- same embedding backend as `semantic_search`, just without paying for
    an index round-trip a one-shot batch-math consumer doesn't need."""
    if not texts:
        return []
    try:
        embedding_fn = _get_embedding_function()
        return [list(vector) for vector in embedding_fn(texts)]
    except VectorStoreError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"embedding failed: {exc}") from exc


_last_corpus_hash: dict[str, str] = {}
_corpus_hash_lock = Lock()


def _corpus_hash(ids: list[str], documents: list[str]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for doc_id, document in zip(ids, documents, strict=True):
        digest.update(doc_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(document.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def embed_corpus(
    collection_name: str,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]] | None,
) -> None:
    """Convenience wrapper: reset the collection, then index the whole corpus.
    The pattern every caller in this repo uses -- re-embed fresh each call
    rather than maintain an incremental index, since every corpus here is
    small enough that correctness-over-cleverness is the right call (see
    module docstring).

    Skips the reset+upsert entirely when this exact (ids, documents) pair was
    the last thing indexed into this collection -- a content hash, not a
    fixed-size cache, so it's exact rather than approximate. This matters for
    callers like S1's funnel metrics that call `find_similar` once per
    incident over the same corpus: without this, every one of those calls
    would re-embed the whole corpus from scratch.
    """
    content_hash = _corpus_hash(ids, documents)
    with _corpus_hash_lock:
        if _last_corpus_hash.get(collection_name) == content_hash:
            return

    reset_collection(collection_name)
    upsert(collection_name, ids, documents, metadatas)

    # Only recorded after a successful upsert -- a failed attempt must not
    # make the next call believe this corpus is already indexed.
    with _corpus_hash_lock:
        _last_corpus_hash[collection_name] = content_hash

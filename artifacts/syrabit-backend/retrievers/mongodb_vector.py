"""
retrievers.mongodb_vector — MongoDB Atlas Vector Search adapter.

DEPRECATION NOTICE (Task #203, 2026-05)
----------------------------------------
MongoVectorRetriever is the **legacy** Atlas $vectorSearch backend.
The AHSEC/SEBA RAG hot path (``rag.py::_fetch_chunks_semantic``) now
queries the Pinecone serverless index (``retrievers.pinecone_vector``)
as its primary vector store.  MongoVectorRetriever is kept for:

  * Emergency fallback (set PINECONE_ATLAS_FALLBACK=true, which is the
    default during the transition window).
  * Admin/diagnostic retriever toggle (``POST /admin/retriever/config
    {"active": "mongodb_vector"}``).
  * Non-chunk collections that have not been migrated to Pinecone (e.g.
    any future use-case with a separate Atlas index).

New ingestion via ``chunk_embedder.py`` no longer writes to MongoDB
``chunks.embedding`` by default when ``PINECONE_SKIP_MONGO_EMBED=true``;
existing stored embeddings remain in place (safe archive).

Once parity validation (Task #206) is complete, set:
  PINECONE_ATLAS_FALLBACK=false  — stop using Atlas $vectorSearch fallback
and the ensure_vector_index() call in server.py can be removed.

Uses the ``$vectorSearch`` aggregation stage available on MongoDB Flex
and Dedicated (M10+) tiers with Atlas Vector Search enabled.

Architecture
------------
* Each document in the configured collection must have an ``embedding``
  field containing a list[float] of exactly ``ATLAS_VS_DIMENSIONS``
  values.  All other fields are treated as filterable metadata and are
  surfaced in the ``metadata`` key of the returned match dicts (same
  contract as VectorizeRetriever so consumers are backend-agnostic).
* The Atlas Vector Search index (``ATLAS_VS_INDEX_NAME``) must be created
  in the Atlas UI (or via the Admin API) **before** this retriever can
  serve queries.  Call ``ensure_vector_index()`` on startup or from the
  admin endpoint — it's a no-op if the index already exists.
* ``numCandidates`` is set to ``top_k × 15`` (clamped to [top_k, 10 000])
  which gives Atlas VS enough scope to return high-quality cosine
  neighbours even with a subject_id filter that prunes half the corpus.

Environment variables (all optional — sensible defaults apply)
--------------------------------------------------------------
  ATLAS_VS_COLLECTION   MongoDB collection name  (default: "chunks")
  ATLAS_VS_INDEX_NAME   Atlas Search index name  (default: "vector_index")
  ATLAS_VS_DIMENSIONS   Embedding width          (default: 1024)
  ATLAS_VS_METRIC       Similarity metric        (default: "cosine")
  ATLAS_VS_FILTER_FIELDS  Comma-separated metadata fields to expose as
                          Atlas filter paths (default: "subject_id,board_id,
                          class_id,chunk_type")

Index definition (create in Atlas UI → Search → Create Index → JSON editor)
---------------------------------------------------------------------------
{
  "name": "<ATLAS_VS_INDEX_NAME>",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      {
        "type": "vector",
        "numDimensions": 1024,
        "path": "embedding",
        "similarity": "cosine"
      },
      { "type": "filter", "path": "subject_id" },
      { "type": "filter", "path": "board_id" },
      { "type": "filter", "path": "class_id" },
      { "type": "filter", "path": "chunk_type" }
    ]
  }
}
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from .base import Retriever

logger = logging.getLogger("retrievers.mongodb_vector")

_COLLECTION   = os.environ.get("ATLAS_VS_COLLECTION",   "chunks").strip() or "chunks"
_INDEX_NAME   = os.environ.get("ATLAS_VS_INDEX_NAME",   "vector_index").strip() or "vector_index"
_DIMENSIONS   = int(os.environ.get("ATLAS_VS_DIMENSIONS", "1024") or "1024")
_METRIC       = os.environ.get("ATLAS_VS_METRIC",       "cosine").strip() or "cosine"
_FILTER_PATHS = [
    f.strip() for f in
    os.environ.get("ATLAS_VS_FILTER_FIELDS", "subject_id,board_id,class_id,chunk_type").split(",")
    if f.strip()
]

_METADATA_EXCLUDE = {"_id", "embedding"}


def _collection():
    """Return the Motor collection, or raise RuntimeError if MongoDB is unavailable."""
    from deps import db
    if db is None:
        raise RuntimeError("MongoDB is not available — MongoVectorRetriever cannot serve queries")
    return db[_COLLECTION]


def _doc_to_match(doc: dict, include_values: bool = False) -> dict:
    """Convert a raw MongoDB document to the Vectorize-compatible match shape."""
    _id = str(doc.get("_id", ""))
    score = float(doc.get("score", 0.0))
    metadata = {k: v for k, v in doc.items() if k not in _METADATA_EXCLUDE and k != "score"}
    result: dict[str, Any] = {"id": _id, "score": score, "metadata": metadata}
    if include_values:
        result["values"] = doc.get("embedding", [])
    return result


class MongoVectorRetriever(Retriever):
    """Atlas Vector Search–backed retriever (``$vectorSearch`` pipeline)."""

    name = "mongodb_vector"

    @property
    def dimensions(self) -> int:
        return _DIMENSIONS

    def is_configured(self) -> bool:
        try:
            from deps import db
            return db is not None
        except Exception:
            return False

    async def query(
        self,
        vector: list[float],
        top_k: int = 10,
        metadata_filter: Optional[dict[str, Any]] = None,
        return_values: bool = False,
        return_metadata: bool = True,
    ) -> list[dict[str, Any]]:
        if not self.is_configured():
            logger.warning("MongoVectorRetriever: MongoDB not available — returning empty")
            return []

        num_candidates = min(max(top_k * 15, top_k), 10_000)

        vs_stage: dict[str, Any] = {
            "index": _INDEX_NAME,
            "path": "embedding",
            "queryVector": vector,
            "numCandidates": num_candidates,
            "limit": top_k,
        }
        if metadata_filter:
            vs_stage["filter"] = metadata_filter

        pipeline: list[dict] = [
            {"$vectorSearch": vs_stage},
            {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        ]

        if not return_values:
            pipeline.append({"$project": {"embedding": 0}})

        col = _collection()
        try:
            cursor = col.aggregate(pipeline)
            docs = await cursor.to_list(length=top_k)
        except Exception as exc:
            logger.error("MongoVectorRetriever.query failed: %s", exc)
            return []

        return [_doc_to_match(d, include_values=return_values) for d in docs]

    async def upsert(self, vectors: list[dict[str, Any]]) -> dict[str, Any]:
        """Insert-or-update chunk documents with their embeddings.

        Each input dict must match:
          { "id": str, "values": list[float], "metadata": dict }
        """
        if not vectors:
            return {"upserted": 0}
        col = _collection()
        ops = []
        try:
            from pymongo import UpdateOne
        except ImportError:
            from motor.motor_asyncio import AsyncIOMotorCollection
            UpdateOne = None

        if UpdateOne is None:
            logger.error("pymongo not installed — upsert unavailable")
            return {"upserted": 0, "errors": ["pymongo not installed"]}

        for v in vectors:
            doc = {
                "embedding": v.get("values", []),
                **(v.get("metadata") or {}),
            }
            ops.append(UpdateOne({"_id": v["id"]}, {"$set": doc}, upsert=True))

        try:
            result = await col.bulk_write(ops, ordered=False)
            total = result.upserted_count + result.modified_count
            return {"upserted": total}
        except Exception as exc:
            logger.error("MongoVectorRetriever.upsert failed: %s", exc)
            return {"upserted": 0, "errors": [str(exc)]}

    async def delete(self, ids: list[str]) -> int:
        if not ids:
            return 0
        col = _collection()
        try:
            result = await col.delete_many({"_id": {"$in": ids}})
            return result.deleted_count
        except Exception as exc:
            logger.error("MongoVectorRetriever.delete failed: %s", exc)
            return 0

    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        col = _collection()
        try:
            cursor = col.find({"_id": {"$in": ids}}, {"embedding": 0})
            docs = await cursor.to_list(length=len(ids))
            return [_doc_to_match(d) for d in docs]
        except Exception as exc:
            logger.error("MongoVectorRetriever.get_by_ids failed: %s", exc)
            return []

    async def index_info(self) -> dict[str, Any]:
        col = _collection()
        try:
            count = await col.estimated_document_count()
            return {
                "backend": "mongodb_atlas_vector_search",
                "collection": _COLLECTION,
                "index_name": _INDEX_NAME,
                "dimensions": _DIMENSIONS,
                "metric": _METRIC,
                "estimated_document_count": count,
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def index_config(self) -> dict[str, Any]:
        return {
            "name": _INDEX_NAME,
            "collection": _COLLECTION,
            "dimensions": _DIMENSIONS,
            "metric": _METRIC,
            "filter_paths": _FILTER_PATHS,
        }

    async def close(self) -> None:
        pass


async def ensure_vector_index() -> dict[str, Any]:
    """Create the Atlas Vector Search index if it does not already exist.

    Safe to call on startup — if the index already exists MongoDB returns
    an error that we silently swallow.  This function uses the raw
    ``createSearchIndexes`` command (available in motor ≥ 3.3 / pymongo
    ≥ 4.6).

    Returns a status dict for logging / admin diagnostics.
    """
    try:
        from deps import db
        if db is None:
            return {"ok": False, "reason": "MongoDB not available"}

        definition = {
            "fields": [
                {
                    "type": "vector",
                    "numDimensions": _DIMENSIONS,
                    "path": "embedding",
                    "similarity": _METRIC,
                },
                *[{"type": "filter", "path": p} for p in _FILTER_PATHS],
            ]
        }

        await db.command(
            "createSearchIndexes",
            _COLLECTION,
            indexes=[{"name": _INDEX_NAME, "type": "vectorSearch", "definition": definition}],
        )
        logger.info(
            "Atlas Vector Search index '%s' created on collection '%s'",
            _INDEX_NAME, _COLLECTION,
        )
        return {"ok": True, "created": True, "index": _INDEX_NAME, "collection": _COLLECTION}
    except Exception as exc:
        msg = str(exc)
        if "already exists" in msg.lower() or "IndexAlreadyExists" in msg:
            logger.info("Atlas VS index '%s' already exists — skipping creation", _INDEX_NAME)
            return {"ok": True, "created": False, "index": _INDEX_NAME, "note": "already exists"}
        logger.warning("ensure_vector_index failed (non-fatal): %s", exc)
        return {"ok": False, "reason": msg}

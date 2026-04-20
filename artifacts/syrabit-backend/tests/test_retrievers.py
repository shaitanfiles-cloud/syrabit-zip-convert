"""
test_retrievers — exercise the retriever interface, the Vectorize
adapter (with a stubbed `vectorize_client`), the Vertex adapter's
configuration gating, and the factory's selection precedence.

The Vertex adapter does not run any HTTP traffic in these tests —
we only assert that `is_configured()`, batching helpers, and the
factory select-by-env behaviour work without GCP credentials.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from retrievers import (
    DEFAULT_RETRIEVER,
    get_retriever,
    get_retriever_by_name,
    invalidate_retriever_cache,
    list_available_retrievers,
)
from retrievers.vectorize import VectorizeRetriever
from retrievers.vertex import VertexVectorSearchRetriever
from retrievers import factory as _factory



@pytest.fixture
def anyio_backend():
    return "asyncio"

# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_cache():
    invalidate_retriever_cache()
    yield
    invalidate_retriever_cache()


@pytest.fixture
def patched_vectorize(monkeypatch):
    """Stub every `vectorize_client.*` call so VectorizeRetriever can be
    exercised without network/account credentials."""
    import vectorize_client as vc

    state: dict[str, Any] = {
        "configured": True,
        "upsert_calls": [],
        "delete_calls": [],
        "query_calls": [],
        "get_by_ids_calls": [],
    }

    monkeypatch.setattr(vc, "VECTORIZE_DIMENSIONS", 1024, raising=True)
    monkeypatch.setattr(vc, "VECTORIZE_INDEX_NAME", "test-index", raising=True)
    monkeypatch.setattr(vc, "is_configured", lambda: state["configured"])

    async def _upsert(vectors):
        state["upsert_calls"].append(list(vectors))
        return {"upserted": len(vectors)}

    async def _query(vector, top_k=10, metadata_filter=None,
                     return_values=False, return_metadata=True):
        state["query_calls"].append({
            "top_k": top_k, "metadata_filter": metadata_filter,
            "return_values": return_values, "return_metadata": return_metadata,
        })
        return [{"id": "v1", "score": 0.9, "metadata": {"chapter_id": "c1"}}]

    async def _delete(ids):
        state["delete_calls"].append(list(ids))
        return len(ids)

    async def _get_by_ids(ids):
        state["get_by_ids_calls"].append(list(ids))
        return [{"id": i, "metadata": {}} for i in ids]

    async def _index_info():
        return {"vector_count": 42}

    async def _index_config():
        return {"dimensions": 1024, "metric": "cosine"}

    monkeypatch.setattr(vc, "upsert_vectors", _upsert)
    monkeypatch.setattr(vc, "query_vectors", _query)
    monkeypatch.setattr(vc, "delete_vectors", _delete)
    monkeypatch.setattr(vc, "get_vectors_by_ids", _get_by_ids)
    monkeypatch.setattr(vc, "get_index_info", _index_info)
    monkeypatch.setattr(vc, "get_index_config", _index_config)
    return state


# ── Factory ─────────────────────────────────────────────────────────────────

def test_default_and_listing():
    assert DEFAULT_RETRIEVER == "vectorize"
    names = list_available_retrievers()
    assert {"vectorize", "vertex"}.issubset(names)


def test_get_by_name_returns_correct_class():
    assert isinstance(get_retriever_by_name("vectorize"), VectorizeRetriever)
    assert isinstance(get_retriever_by_name("vertex"), VertexVectorSearchRetriever)


def test_get_by_name_memoises():
    a = get_retriever_by_name("vectorize")
    b = get_retriever_by_name("VECTORIZE")  # case insensitive
    assert a is b


def test_get_by_name_unknown_raises():
    with pytest.raises(ValueError):
        get_retriever_by_name("not_a_real_backend")


def test_env_override(monkeypatch):
    monkeypatch.setenv("RAG_RETRIEVER", "vertex")
    assert _factory.get_active_retriever_name() == "vertex"
    monkeypatch.setenv("RAG_RETRIEVER", "garbage")
    assert _factory.get_active_retriever_name() == DEFAULT_RETRIEVER


def test_env_default(monkeypatch):
    monkeypatch.delenv("RAG_RETRIEVER", raising=False)
    assert _factory.get_active_retriever_name() == DEFAULT_RETRIEVER


@pytest.mark.anyio
async def test_get_retriever_falls_back_to_env(monkeypatch):
    # No DB override available → factory should yield the env-default
    # without raising. Force the DB-read code path to return None.
    async def _no_override():
        return None
    monkeypatch.setattr(_factory, "_read_db_override", _no_override)
    monkeypatch.setenv("RAG_RETRIEVER", "vertex")
    r = await get_retriever()
    assert isinstance(r, VertexVectorSearchRetriever)


# ── Vectorize adapter (delegation correctness) ──────────────────────────────

@pytest.mark.anyio
async def test_vectorize_adapter_delegates(patched_vectorize):
    r = VectorizeRetriever()
    assert r.name == "vectorize"
    assert r.dimensions == 1024
    assert r.is_configured() is True

    out = await r.query([0.1] * 1024, top_k=3, metadata_filter={"subject_id": "s1"})
    assert out and out[0]["id"] == "v1"
    call = patched_vectorize["query_calls"][-1]
    assert call["top_k"] == 3
    assert call["metadata_filter"] == {"subject_id": "s1"}

    res = await r.upsert([{"id": "x", "values": [0.0] * 1024, "metadata": {}}])
    assert res == {"upserted": 1}

    n = await r.delete(["a", "b"])
    assert n == 2

    got = await r.get_by_ids(["a", "b"])
    assert {g["id"] for g in got} == {"a", "b"}

    info = await r.index_info()
    cfg = await r.index_config()
    assert info["vector_count"] == 42
    assert cfg["dimensions"] == 1024
    assert cfg["name"] == "test-index"


@pytest.mark.anyio
async def test_vectorize_unconfigured_short_circuits_via_is_configured(patched_vectorize):
    patched_vectorize["configured"] = False
    r = VectorizeRetriever()
    assert r.is_configured() is False


# ── Vertex adapter (no GCP creds — just gating + helpers) ───────────────────

def test_vertex_unconfigured_when_env_missing(monkeypatch):
    for var in (
        "VERTEX_PROJECT_ID", "VERTEX_INDEX_ID", "VERTEX_INDEX_ENDPOINT_ID",
        "VERTEX_DEPLOYED_INDEX_ID", "VERTEX_SERVICE_ACCOUNT",
    ):
        monkeypatch.delenv(var, raising=False)
    r = VertexVectorSearchRetriever()
    assert not r.is_configured()


def test_vertex_to_datapoint_strips_empties():
    r = VertexVectorSearchRetriever()
    dp = r._to_datapoint({
        "id": "v1",
        "values": [0.1, 0.2],
        "metadata": {"chapter_id": "c1", "subject_id": "", "blank": None, "level": "chapter"},
    })
    assert dp["datapointId"] == "v1"
    namespaces = {r["namespace"] for r in dp["restricts"]}
    assert namespaces == {"chapter_id", "level"}  # "" and None dropped


@pytest.mark.anyio
async def test_vertex_query_short_circuits_when_unconfigured(monkeypatch):
    for var in (
        "VERTEX_PROJECT_ID", "VERTEX_INDEX_ID", "VERTEX_INDEX_ENDPOINT_ID",
        "VERTEX_DEPLOYED_INDEX_ID", "VERTEX_SERVICE_ACCOUNT",
    ):
        monkeypatch.delenv(var, raising=False)
    r = VertexVectorSearchRetriever()
    assert await r.query([0.0] * 8) == []
    assert await r.delete(["a"]) == 0
    assert await r.get_by_ids(["a"]) == []
    upsert = await r.upsert([{"id": "x", "values": [0.0], "metadata": {}}])
    assert upsert.get("upserted") == 0
    assert "vertex_not_configured" in (upsert.get("errors") or [])


@pytest.mark.anyio
async def test_db_override_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("RAG_RETRIEVER", "vectorize")

    async def _override():
        return "vertex"
    monkeypatch.setattr(_factory, "_read_db_override", _override)
    r = await get_retriever()
    assert isinstance(r, VertexVectorSearchRetriever)


@pytest.mark.anyio
async def test_db_override_db_failure_falls_back_to_env(monkeypatch):
    """Regression: a DB hiccup must not poison the override cache."""
    monkeypatch.setenv("RAG_RETRIEVER", "vectorize")
    # Simulate a transient DB error → real factory uses the cache TTL,
    # but a failed read must clear the cache so the *next* call retries.
    invalidate_retriever_cache()
    fake_db = type("FakeDB", (), {})()
    class _Settings:
        async def find_one(self, *a, **k):
            raise RuntimeError("simulated DB outage")
    fake_db.settings = _Settings()
    import deps as _deps
    monkeypatch.setattr(_deps, "db", fake_db, raising=False)
    r1 = await get_retriever()
    assert isinstance(r1, VectorizeRetriever), "must fall back to env on DB error"
    # And the cache must NOT keep the stale empty value — confirm the
    # next call still does the right thing if the DB recovers.
    class _SettingsOK:
        async def find_one(self, *a, **k):
            return {"active": "vertex"}
    fake_db.settings = _SettingsOK()
    r2 = await get_retriever()
    assert isinstance(r2, VertexVectorSearchRetriever), "cache must allow recovery"


@pytest.mark.anyio
async def test_admin_toggle_refuses_unconfigured(monkeypatch):
    """`PUT /admin/retriever/config` must refuse switching to a backend
    whose `is_configured()` returns False."""
    from routes import admin_retriever as ar
    from fastapi import HTTPException
    # Force vertex to look unconfigured.
    invalidate_retriever_cache()
    for var in (
        "VERTEX_PROJECT_ID", "VERTEX_INDEX_ID", "VERTEX_INDEX_ENDPOINT_ID",
        "VERTEX_DEPLOYED_INDEX_ID", "VERTEX_SERVICE_ACCOUNT",
    ):
        monkeypatch.delenv(var, raising=False)
    payload = ar.RetrieverSwitchPayload(active="vertex")
    with pytest.raises(HTTPException) as exc:
        await ar.update_retriever_config(payload, _admin={"id": "admin"})
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_admin_toggle_rejects_unknown_name():
    from routes import admin_retriever as ar
    from fastapi import HTTPException
    payload = ar.RetrieverSwitchPayload(active="not_a_real_backend")
    with pytest.raises(HTTPException) as exc:
        await ar.update_retriever_config(payload, _admin={"id": "admin"})
    assert exc.value.status_code == 400


def test_vertex_url_construction_matches_google_rest_shape(monkeypatch):
    """Pin the Vertex REST URL templates so a refactor that breaks one
    of them gets caught immediately. URLs must match Google's
    documented `aiplatform.googleapis.com` shape."""
    monkeypatch.setenv("VERTEX_PROJECT_ID", "p")
    monkeypatch.setenv("VERTEX_LOCATION", "us-central1")
    monkeypatch.setenv("VERTEX_INDEX_ID", "111")
    monkeypatch.setenv("VERTEX_INDEX_ENDPOINT_ID", "222")
    monkeypatch.setenv("VERTEX_DEPLOYED_INDEX_ID", "deployed1")
    monkeypatch.setenv("VERTEX_SERVICE_ACCOUNT", '{"type":"service_account"}')
    monkeypatch.delenv("VERTEX_PUBLIC_DOMAIN_ENDPOINT", raising=False)
    r = VertexVectorSearchRetriever()
    base = "https://us-central1-aiplatform.googleapis.com/v1/projects/p/locations/us-central1"
    assert r._find_neighbors_url() == f"{base}/indexEndpoints/222:findNeighbors"
    assert r._read_datapoints_url() == f"{base}/indexEndpoints/222:readIndexDatapoints"
    assert r._upsert_url() == f"{base}/indexes/111:upsertDatapoints"
    assert r._remove_url() == f"{base}/indexes/111:removeDatapoints"


def test_vertex_url_uses_public_domain_when_set(monkeypatch):
    monkeypatch.setenv("VERTEX_PROJECT_ID", "p")
    monkeypatch.setenv("VERTEX_LOCATION", "us-central1")
    monkeypatch.setenv("VERTEX_INDEX_ID", "111")
    monkeypatch.setenv("VERTEX_INDEX_ENDPOINT_ID", "222")
    monkeypatch.setenv("VERTEX_DEPLOYED_INDEX_ID", "deployed1")
    monkeypatch.setenv("VERTEX_SERVICE_ACCOUNT", '{"type":"service_account"}')
    monkeypatch.setenv("VERTEX_PUBLIC_DOMAIN_ENDPOINT", "https://abc.us-central1-aiplatform.googleapis.com")
    r = VertexVectorSearchRetriever()
    assert r._find_neighbors_url().startswith(
        "https://abc.us-central1-aiplatform.googleapis.com/v1/projects/p/"
    )


@pytest.mark.anyio
async def test_vertex_index_config_unconfigured_returns_static_shape(monkeypatch):
    for var in (
        "VERTEX_PROJECT_ID", "VERTEX_INDEX_ID", "VERTEX_INDEX_ENDPOINT_ID",
        "VERTEX_DEPLOYED_INDEX_ID", "VERTEX_SERVICE_ACCOUNT",
    ):
        monkeypatch.delenv(var, raising=False)
    r = VertexVectorSearchRetriever()
    cfg = await r.index_config()
    assert cfg["metric"] == "cosine"
    assert cfg["dimensions"] >= 1

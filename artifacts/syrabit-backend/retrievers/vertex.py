"""
retrievers.vertex — Google Vertex AI Vector Search (Matching Engine) adapter.

Implements the `Retriever` ABC against the public REST API rather than
the heavyweight `google-cloud-aiplatform` SDK so we don't pull in a
~80MB transitive tree just for nearest-neighbour calls. Auth uses
`google-auth` (already a project dependency) to mint short-lived
access tokens from a service account.

Required environment variables (all must be set; otherwise
`is_configured()` returns False and every method short-circuits):

  VERTEX_PROJECT_ID            — GCP project that owns the index
  VERTEX_LOCATION              — e.g. ``us-central1``
  VERTEX_INDEX_ID              — numeric ID of the Index resource
  VERTEX_INDEX_ENDPOINT_ID     — numeric ID of the IndexEndpoint
  VERTEX_DEPLOYED_INDEX_ID     — string ID assigned at deploy time
  VERTEX_SERVICE_ACCOUNT       — full service-account JSON (one line)
                                 OR path to a JSON file on disk

Optional:

  VERTEX_PUBLIC_DOMAIN_ENDPOINT  — set when the IndexEndpoint is
                                  configured for public-internet access
                                  (skips the private-VPC URL form)
  VERTEX_DIMENSIONS              — defaults to 1024 to match the
                                   existing Vectorize index

The implementation deliberately stays minimal. It supports the four
operations the syllabus embedder needs (query / upsert / delete /
get_by_ids) plus index_info / index_config for the admin dashboard.
Metadata filters use the simple `restricts` form (one namespace per
key, equality only) — sufficient for our `subject_id` /
`chapter_id` / `level` filters.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

from .base import Retriever

logger = logging.getLogger("retrievers.vertex")

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_TOKEN_REFRESH_BUFFER_SEC = 60.0  # refresh ~1 min before expiry


class VertexVectorSearchRetriever(Retriever):
    name = "vertex"

    def __init__(self) -> None:
        self._project = os.environ.get("VERTEX_PROJECT_ID", "").strip()
        self._location = os.environ.get("VERTEX_LOCATION", "us-central1").strip() or "us-central1"
        self._index_id = os.environ.get("VERTEX_INDEX_ID", "").strip()
        self._endpoint_id = os.environ.get("VERTEX_INDEX_ENDPOINT_ID", "").strip()
        self._deployed_index_id = os.environ.get("VERTEX_DEPLOYED_INDEX_ID", "").strip()
        self._public_domain = os.environ.get("VERTEX_PUBLIC_DOMAIN_ENDPOINT", "").strip()
        try:
            self._dimensions = int(os.environ.get("VERTEX_DIMENSIONS", "1024"))
        except ValueError:
            self._dimensions = 1024

        self._sa_raw = os.environ.get("VERTEX_SERVICE_ACCOUNT", "").strip()
        self._creds = None
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._lock = asyncio.Lock()

    # ── ABC surface ────────────────────────────────────────────────────────

    @property
    def dimensions(self) -> int:  # type: ignore[override]
        return self._dimensions

    def is_configured(self) -> bool:
        return bool(
            self._project
            and self._index_id
            and self._endpoint_id
            and self._deployed_index_id
            and self._sa_raw
        )

    async def query(
        self,
        vector: list[float],
        top_k: int = 10,
        metadata_filter: Optional[dict[str, Any]] = None,
        return_values: bool = False,
        return_metadata: bool = True,
    ) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []
        try:
            token = await self._access_token()
        except Exception as exc:
            logger.warning("Vertex auth failed: %s", exc)
            return []

        url = self._find_neighbors_url()
        body: dict[str, Any] = {
            "deployedIndexId": self._deployed_index_id,
            "queries": [
                {
                    "datapoint": {
                        "datapointId": "query",
                        "featureVector": vector,
                    },
                    "neighborCount": top_k,
                }
            ],
        }
        if metadata_filter:
            restricts = [
                {"namespace": k, "allowList": [str(v)]}
                for k, v in metadata_filter.items()
                if v is not None and v != ""
            ]
            if restricts:
                body["queries"][0]["datapoint"]["restricts"] = restricts
        if return_values:
            body["returnFullDatapoint"] = True

        try:
            data = await self._post_json(url, token, body, timeout=15.0)
        except Exception as exc:
            logger.warning("Vertex findNeighbors failed: %s", exc)
            return []

        out: list[dict[str, Any]] = []
        for q in (data.get("nearestNeighbors") or []):
            for n in (q.get("neighbors") or []):
                dp = n.get("datapoint") or {}
                vid = dp.get("datapointId") or ""
                if not vid:
                    continue
                # Vertex returns `distance` for cosine (smaller=closer).
                # Convert to a similarity-ish score so ordering matches
                # Vectorize callers (which sort descending on score).
                dist = float(n.get("distance", 0.0))
                score = 1.0 - dist
                entry: dict[str, Any] = {"id": vid, "score": score}
                if return_metadata:
                    md: dict[str, Any] = {}
                    for r in (dp.get("restricts") or []):
                        ns = r.get("namespace")
                        vals = r.get("allowList") or []
                        if ns and vals:
                            md[ns] = vals[0]
                    # Numeric / crowding metadata if present
                    for nr in (dp.get("numericRestricts") or []):
                        ns = nr.get("namespace")
                        if ns and "valueFloat" in nr:
                            md[ns] = nr["valueFloat"]
                    if md:
                        entry["metadata"] = md
                if return_values and dp.get("featureVector"):
                    entry["values"] = list(dp["featureVector"])
                out.append(entry)
        return out

    async def upsert(self, vectors: list[dict[str, Any]]) -> dict[str, Any]:
        """Streaming upsert via `upsertDatapoints`. Vertex caps each
        request at 1000 datapoints; we batch at 100 to stay well under
        the byte-size cap (~10 MB) for 1024-dim float32 vectors with
        rich metadata."""
        if not self.is_configured():
            return {"upserted": 0, "errors": ["vertex_not_configured"]}
        if not vectors:
            return {"upserted": 0}

        try:
            token = await self._access_token()
        except Exception as exc:
            return {"upserted": 0, "errors": [f"auth: {exc}"]}

        url = self._upsert_url()
        BATCH = 100
        total = 0
        errors: list[str] = []
        for i in range(0, len(vectors), BATCH):
            batch = vectors[i : i + BATCH]
            datapoints = [self._to_datapoint(v) for v in batch]
            body = {"datapoints": datapoints}
            try:
                await self._post_json(url, token, body, timeout=30.0)
                total += len(batch)
            except Exception as exc:
                logger.warning("Vertex upsert batch %d failed: %s", i // BATCH, exc)
                errors.append(f"batch {i // BATCH}: {exc}")
        out: dict[str, Any] = {"upserted": total}
        if errors:
            out["errors"] = errors
        return out

    async def delete(self, ids: list[str]) -> int:
        if not self.is_configured() or not ids:
            return 0
        try:
            token = await self._access_token()
        except Exception:
            return 0
        url = self._remove_url()
        BATCH = 1000
        deleted = 0
        for i in range(0, len(ids), BATCH):
            batch = ids[i : i + BATCH]
            body = {"datapointIds": batch}
            try:
                await self._post_json(url, token, body, timeout=30.0)
                deleted += len(batch)
            except Exception as exc:
                logger.warning("Vertex delete batch failed: %s", exc)
        return deleted

    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        """Vertex Vector Search has no first-class `get_by_id`; we use
        `readIndexDatapoints` on the IndexEndpoint which serves the
        deployed index. Returns the full datapoint (vector + metadata)."""
        if not self.is_configured() or not ids:
            return []
        try:
            token = await self._access_token()
        except Exception:
            return []
        url = self._read_datapoints_url()
        BATCH = 100
        out: list[dict[str, Any]] = []
        for i in range(0, len(ids), BATCH):
            batch = ids[i : i + BATCH]
            body = {
                "deployedIndexId": self._deployed_index_id,
                "ids": batch,
            }
            try:
                data = await self._post_json(url, token, body, timeout=15.0)
            except Exception as exc:
                logger.warning("Vertex readIndexDatapoints failed: %s", exc)
                continue
            for dp in (data.get("datapoints") or []):
                vid = dp.get("datapointId")
                if not vid:
                    continue
                entry: dict[str, Any] = {"id": vid}
                if dp.get("featureVector"):
                    entry["values"] = list(dp["featureVector"])
                md: dict[str, Any] = {}
                for r in (dp.get("restricts") or []):
                    ns = r.get("namespace")
                    vals = r.get("allowList") or []
                    if ns and vals:
                        md[ns] = vals[0]
                if md:
                    entry["metadata"] = md
                out.append(entry)
        return out

    async def index_info(self) -> dict[str, Any]:
        if not self.is_configured():
            return {}
        try:
            token = await self._access_token()
        except Exception:
            return {}
        url = (
            f"https://{self._location}-aiplatform.googleapis.com/v1/"
            f"projects/{self._project}/locations/{self._location}/indexes/{self._index_id}"
        )
        try:
            data = await self._get_json(url, token, timeout=10.0)
        except Exception as exc:
            logger.warning("Vertex index info failed: %s", exc)
            return {}
        stats = (data.get("indexStats") or {})
        return {
            "vector_count": int(stats.get("vectorsCount", 0)) if stats else 0,
            "shards_count": int(stats.get("shardsCount", 0)) if stats else 0,
            "display_name": data.get("displayName", ""),
            "update_method": data.get("indexUpdateMethod", ""),
        }

    async def index_config(self) -> dict[str, Any]:
        if not self.is_configured():
            return {
                "name": "vertex (unconfigured)",
                "dimensions": self._dimensions,
                "metric": "cosine",
            }
        return {
            "name": f"projects/{self._project}/locations/{self._location}/indexes/{self._index_id}",
            "dimensions": self._dimensions,
            "metric": "cosine",
            "endpoint": f"projects/{self._project}/locations/{self._location}/indexEndpoints/{self._endpoint_id}",
            "deployed_index_id": self._deployed_index_id,
        }

    # ── helpers ────────────────────────────────────────────────────────────

    def _to_datapoint(self, v: dict[str, Any]) -> dict[str, Any]:
        meta = v.get("metadata") or {}
        restricts: list[dict[str, Any]] = []
        for k, val in meta.items():
            if val is None or val == "":
                continue
            if isinstance(val, (str, int, bool)):
                restricts.append({"namespace": str(k), "allowList": [str(val)]})
        dp: dict[str, Any] = {
            "datapointId": str(v["id"]),
            "featureVector": list(v["values"]),
        }
        if restricts:
            dp["restricts"] = restricts
        return dp

    def _api_host(self) -> str:
        # Public-domain endpoint variant when the IndexEndpoint was
        # deployed for public-internet access.
        if self._public_domain:
            return self._public_domain.rstrip("/")
        return f"https://{self._location}-aiplatform.googleapis.com"

    def _index_url_base(self) -> str:
        return (
            f"{self._api_host()}/v1/projects/{self._project}"
            f"/locations/{self._location}/indexes/{self._index_id}"
        )

    def _endpoint_url_base(self) -> str:
        return (
            f"{self._api_host()}/v1/projects/{self._project}"
            f"/locations/{self._location}/indexEndpoints/{self._endpoint_id}"
        )

    def _find_neighbors_url(self) -> str:
        return f"{self._endpoint_url_base()}:findNeighbors"

    def _read_datapoints_url(self) -> str:
        return f"{self._endpoint_url_base()}:readIndexDatapoints"

    def _upsert_url(self) -> str:
        return f"{self._index_url_base()}:upsertDatapoints"

    def _remove_url(self) -> str:
        return f"{self._index_url_base()}:removeDatapoints"

    async def _access_token(self) -> str:
        async with self._lock:
            now = time.monotonic()
            if self._token and now < (self._token_expiry - _TOKEN_REFRESH_BUFFER_SEC):
                return self._token
            self._token, self._token_expiry = await asyncio.to_thread(self._refresh_token)
            return self._token

    def _refresh_token(self) -> tuple[str, float]:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as _Req

        if self._creds is None:
            info = self._load_sa_info()
            self._creds = service_account.Credentials.from_service_account_info(
                info, scopes=[_SCOPE],
            )
        # google-auth refresh is sync; we call it inside `to_thread`.
        self._creds.refresh(_Req())
        # `expiry` is a naive UTC datetime; convert to monotonic-relative.
        from datetime import datetime, timezone
        if self._creds.expiry is None:
            ttl = 3600.0
        else:
            exp_utc = self._creds.expiry.replace(tzinfo=timezone.utc).timestamp()
            ttl = max(60.0, exp_utc - datetime.now(tz=timezone.utc).timestamp())
        return self._creds.token, time.monotonic() + ttl

    def _load_sa_info(self) -> dict[str, Any]:
        raw = self._sa_raw
        if raw.startswith("{"):
            return json.loads(raw)
        # Treat as a path
        with open(raw, "r", encoding="utf-8") as f:
            return json.load(f)

    async def _post_json(
        self, url: str, token: str, body: dict[str, Any], timeout: float = 15.0,
    ) -> dict[str, Any]:
        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            if not resp.content:
                return {}
            return resp.json()

    async def _get_json(self, url: str, token: str, timeout: float = 10.0) -> dict[str, Any]:
        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json() if resp.content else {}

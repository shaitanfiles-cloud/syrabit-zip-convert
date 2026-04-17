"""Centralised upsert helpers for SEO-critical Mongo collections.

Task #349: every insert/upsert into ``seo_pages`` and ``seo_topics`` must
guarantee the publish-date stamps required for Google freshness signals.
Without a single chokepoint, individual call sites have repeatedly
forgotten to write ``created_at`` / ``updated_at`` (or worse, overwritten
``created_at`` on every re-upsert), silently degrading SEO across the
site.

This mirrors the ``_upsert_pyq_html_page`` pattern from
``routes/pyq.py`` (Task #343) — same contract, same guarantees:

- ``created_at`` is written via ``$setOnInsert`` so it is stamped
  exactly once on the original insert and never overwritten on later
  upserts.
- ``updated_at`` is always refreshed via ``$set``.
- If the caller already supplied either timestamp in ``doc`` we honor
  it (useful for backfills and tests) but still ensure both fields
  exist on the resulting document.
- Callers can pass ``set_on_insert_extra`` for additional insert-only
  fields (e.g. a freshly-minted ``id`` that must not change on re-runs).
  ``created_at`` always wins if both sources supply it — the helper's
  publish-date guarantee is non-negotiable.

The two thin wrappers ``upsert_seo_page`` / ``upsert_seo_topic`` exist
so the regression test (and grep audits) can statically verify that no
caller writes to those collections directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional


async def _upsert_seo_doc(
    db_handle,
    collection_name: str,
    filt: Mapping[str, Any],
    doc: Mapping[str, Any],
    *,
    set_on_insert_extra: Optional[Mapping[str, Any]] = None,
) -> None:
    if db_handle is None:
        return

    # Timezone-aware UTC isoformat to stay consistent with the rest of
    # the backend (callers like seo_engine.py / cms_sarvam_health.py
    # already use `datetime.now(timezone.utc).isoformat()`).
    now = datetime.now(timezone.utc).isoformat()
    body = dict(doc)
    created_at = body.pop("created_at", None) or now
    updated_at = body.pop("updated_at", None) or now
    body["updated_at"] = updated_at

    set_on_insert = {"created_at": created_at}
    if set_on_insert_extra:
        for key, value in set_on_insert_extra.items():
            # The publish-date guarantee always wins. Anything else the
            # caller wants to stamp once (e.g. a stable `id`) is merged
            # in alongside.
            if key == "created_at":
                continue
            set_on_insert[key] = value

    coll = getattr(db_handle, collection_name)
    await coll.update_one(
        dict(filt),
        {"$set": body, "$setOnInsert": set_on_insert},
        upsert=True,
    )


async def upsert_seo_page(
    db_handle,
    filt: Mapping[str, Any],
    page_doc: Mapping[str, Any],
    *,
    set_on_insert_extra: Optional[Mapping[str, Any]] = None,
) -> None:
    """Upsert into ``seo_pages`` with guaranteed publish-date stamps.

    ``filt`` selects the row (e.g. ``{"id": page_id}`` or
    ``{"topic_id": ..., "page_type": ...}``); ``page_doc`` carries the
    fields to write into ``$set``. Use ``set_on_insert_extra`` to stamp
    additional insert-only fields like a freshly-minted ``id``.
    """
    return await _upsert_seo_doc(
        db_handle, "seo_pages", filt, page_doc,
        set_on_insert_extra=set_on_insert_extra,
    )


async def upsert_seo_topic(
    db_handle,
    filt: Mapping[str, Any],
    topic_doc: Mapping[str, Any],
    *,
    set_on_insert_extra: Optional[Mapping[str, Any]] = None,
) -> None:
    """Upsert into ``seo_topics`` with guaranteed publish-date stamps.

    Same contract as :func:`upsert_seo_page`. See module docstring for
    the timestamp rules.
    """
    return await _upsert_seo_doc(
        db_handle, "seo_topics", filt, topic_doc,
        set_on_insert_extra=set_on_insert_extra,
    )

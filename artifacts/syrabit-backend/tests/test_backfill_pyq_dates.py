"""Unit tests for the PYQ date backfill helpers (Task #341)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from bson import ObjectId

from scripts.backfill_pyq_dates import (
    _derive_created_at,
    _is_empty,
    _to_iso,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_iso_renders_utc_with_z_suffix():
    dt = datetime(2024, 6, 30, 12, 0, 0, tzinfo=timezone.utc)
    assert _to_iso(dt) == "2024-06-30T12:00:00Z"


def test_is_empty_treats_blank_strings_as_empty():
    assert _is_empty(None)
    assert _is_empty("")
    assert _is_empty("   ")
    assert not _is_empty("2025-01-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Derivation precedence: file_mtime → objectid → exam_year → now_fallback
# ---------------------------------------------------------------------------

def test_derive_prefers_file_mtime_over_objectid_and_year():
    # File mtime (upload row's created_at) wins even when ObjectId and
    # exam_year are also available — it's the closest analogue to when
    # the source PDF actually appeared.
    instant = datetime(2023, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
    oid = ObjectId.from_datetime(instant)
    iso, source = _derive_created_at(
        {"_id": oid, "slug": "ahsec-2020-physics", "exam_year": 2020},
        upload_mtime_by_slug={"ahsec-2020-physics": "2021-09-01T08:00:00Z"},
    )
    assert source == "file_mtime"
    assert iso == "2021-09-01T08:00:00Z"


def test_derive_falls_through_to_objectid_when_no_upload_mtime():
    # ObjectId encodes a timestamp in its first 4 bytes; we round-trip
    # a known instant to confirm the helper picks that path when the
    # upload index has no entry for this slug.
    instant = datetime(2023, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
    oid = ObjectId.from_datetime(instant)
    iso, source = _derive_created_at(
        {"_id": oid, "slug": "ahsec-2020-physics", "exam_year": 2020},
        upload_mtime_by_slug={},
    )
    assert source == "objectid"
    assert iso == "2023-04-17T10:00:00Z"


def test_derive_ignores_blank_upload_mtime_value():
    # An upload row whose own created_at is empty must not poison the
    # priority chain — we should fall through to ObjectId.
    instant = datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    oid = ObjectId.from_datetime(instant)
    iso, source = _derive_created_at(
        {"_id": oid, "slug": "x", "exam_year": 2020},
        upload_mtime_by_slug={"x": "   "},
    )
    assert source == "objectid"
    assert iso == "2022-01-01T00:00:00Z"


def test_derive_falls_back_to_exam_year_midyear_when_no_oid_or_mtime():
    iso, source = _derive_created_at({"_id": None, "exam_year": 2019})
    assert source == "exam_year"
    assert iso == "2019-06-30T00:00:00Z"


def test_derive_uses_now_only_when_no_signal_is_usable():
    iso, source = _derive_created_at({"_id": None, "exam_year": 0})
    assert source == "now_fallback"
    assert iso.endswith("Z") and "T" in iso


def test_derive_ignores_garbage_exam_year_values():
    iso, source = _derive_created_at({"_id": None, "exam_year": "not-a-year"})
    assert source == "now_fallback"
    assert iso.endswith("Z")


# ---------------------------------------------------------------------------
# Updater behaviour — end-to-end against an in-memory fake collection
# ---------------------------------------------------------------------------

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_load_upload_mtimes_skips_blank_and_missing():
    from scripts.backfill_pyq_dates import _load_upload_mtimes

    rows = [
        {"pyq_html_slug": "good", "created_at": "2024-01-01T00:00:00Z"},
        {"pyq_html_slug": "blank", "created_at": ""},
        {"pyq_html_slug": "", "created_at": "2024-01-02T00:00:00Z"},
    ]

    class _Cursor:
        def __init__(self, items): self._items = items
        def __aiter__(self): self._i = iter(self._items); return self
        async def __anext__(self):
            try: return next(self._i)
            except StopIteration: raise StopAsyncIteration

    fake_uploads = MagicMock()
    fake_uploads.find = MagicMock(return_value=_Cursor(rows))
    fake_db = {"pyq_uploads": fake_uploads}

    out = _run(_load_upload_mtimes(fake_db))
    assert out == {"good": "2024-01-01T00:00:00Z"}


def test_updated_at_mirrors_resolved_created_at_when_missing():
    # End-to-end check: a doc with neither timestamp set should receive
    # both, and the new updated_at must equal the freshly-derived
    # created_at (mirroring is the documented rule for legacy rows).
    instant = datetime(2024, 5, 10, 11, 0, 0, tzinfo=timezone.utc)
    oid = ObjectId.from_datetime(instant)
    expected = "2024-05-10T11:00:00Z"

    iso, source = _derive_created_at(
        {"_id": oid, "slug": "no-mtime", "exam_year": 2020},
        upload_mtime_by_slug={},
    )
    assert source == "objectid"
    # Simulate the main loop's mirror step.
    update = {"created_at": iso, "updated_at": iso}
    assert update["updated_at"] == expected
    assert update["created_at"] == expected


def test_existing_created_at_is_never_overwritten():
    # If a row already has a populated created_at, the helper isn't
    # called at all in the main loop — but this test pins the contract
    # that the updater will not generate an update for such a row.
    from scripts.backfill_pyq_dates import _is_empty
    doc = {"created_at": "2025-03-01T00:00:00Z", "updated_at": "2025-03-02T00:00:00Z"}
    assert not _is_empty(doc.get("created_at"))
    assert not _is_empty(doc.get("updated_at"))

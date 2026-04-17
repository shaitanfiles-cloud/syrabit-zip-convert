"""Unit tests for the PYQ date backfill helpers (Task #341)."""
from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId

from scripts.backfill_pyq_dates import _derive_created_at, _is_empty, _to_iso


def test_iso_renders_utc_with_z_suffix():
    dt = datetime(2024, 6, 30, 12, 0, 0, tzinfo=timezone.utc)
    assert _to_iso(dt) == "2024-06-30T12:00:00Z"


def test_is_empty_treats_blank_strings_as_empty():
    assert _is_empty(None)
    assert _is_empty("")
    assert _is_empty("   ")
    assert not _is_empty("2025-01-01T00:00:00Z")


def test_derive_prefers_objectid_when_available():
    # ObjectId encodes a timestamp in its first 4 bytes; we round-trip
    # a known instant to confirm the helper picks that path.
    instant = datetime(2023, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
    oid = ObjectId.from_datetime(instant)
    iso, source = _derive_created_at({"_id": oid, "exam_year": 2020})
    assert source == "objectid"
    assert iso == "2023-04-17T10:00:00Z"


def test_derive_falls_back_to_exam_year_midyear_when_no_oid():
    iso, source = _derive_created_at({"_id": None, "exam_year": 2019})
    assert source == "exam_year"
    assert iso == "2019-06-30T00:00:00Z"


def test_derive_uses_now_only_when_neither_signal_is_usable():
    iso, source = _derive_created_at({"_id": None, "exam_year": 0})
    assert source == "now_fallback"
    # Just verify the shape — the actual instant is "now".
    assert iso.endswith("Z") and "T" in iso


def test_derive_ignores_garbage_exam_year_values():
    iso, source = _derive_created_at({"_id": None, "exam_year": "not-a-year"})
    assert source == "now_fallback"
    assert iso.endswith("Z")

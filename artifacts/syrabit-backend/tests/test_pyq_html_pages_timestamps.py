"""Regression test for Task #343 — every insert into `pyq_html_pages`
must stamp `created_at` and `updated_at` so the legacy missing-publish-date
problem (Task #341) cannot silently recur.

We exercise the production helper `_upsert_pyq_html_page` directly with a
fake Mongo collection and assert:

1. A fresh insert writes both timestamps.
2. `created_at` is sent via `$setOnInsert` (so re-upserts cannot overwrite
   the original publish date).
3. `updated_at` is always refreshed via `$set`.
4. Caller-supplied timestamps are honored when present.
"""
from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

from routes import pyq as pyq_mod  # noqa: E402


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _make_fake_db() -> MagicMock:
    fake_db = MagicMock()
    fake_db.pyq_html_pages.update_one = AsyncMock(return_value=None)
    return fake_db


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_fresh_insert_stamps_both_timestamps():
    fake_db = _make_fake_db()
    page_doc = {
        "html_content": "<html></html>",
        "seo_title": "AHSEC Physics 2024",
        "subject_id": "phy",
    }

    _run(pyq_mod._upsert_pyq_html_page(fake_db, "ahsec-2024-physics", page_doc))

    fake_db.pyq_html_pages.update_one.assert_awaited_once()
    args, kwargs = fake_db.pyq_html_pages.update_one.call_args
    filt, update = args[0], args[1]

    assert filt == {"slug": "ahsec-2024-physics"}
    assert kwargs.get("upsert", False) is True

    set_payload = update["$set"]
    set_on_insert = update["$setOnInsert"]

    # Both publish-date stamps must exist on insert.
    assert "updated_at" in set_payload, "updated_at must be set on every write"
    assert "created_at" in set_on_insert, (
        "created_at must be written via $setOnInsert so the original publish "
        "date survives subsequent upserts (Task #343)"
    )

    # ISO-8601 formatted (the helper uses datetime.utcnow().isoformat()).
    assert _ISO.match(set_payload["updated_at"])
    assert _ISO.match(set_on_insert["created_at"])

    # The doc payload itself is forwarded.
    assert set_payload["seo_title"] == "AHSEC Physics 2024"
    assert set_payload["slug"] == "ahsec-2024-physics"


def test_created_at_uses_set_on_insert_not_set():
    """`created_at` must NOT appear in `$set` — otherwise re-upserting the
    same slug would overwrite the original publish date and break Google's
    freshness signals."""
    fake_db = _make_fake_db()

    _run(pyq_mod._upsert_pyq_html_page(fake_db, "slug-x", {"foo": "bar"}))

    _, args_update = fake_db.pyq_html_pages.update_one.call_args[0]
    assert "created_at" not in args_update["$set"], (
        "created_at must be in $setOnInsert, never $set, to preserve the "
        "original publish date across re-uploads"
    )


def test_caller_supplied_timestamps_are_honored():
    fake_db = _make_fake_db()
    page_doc = {
        "html_content": "<html></html>",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-06-01T12:00:00",
    }

    _run(pyq_mod._upsert_pyq_html_page(fake_db, "legacy-slug", page_doc))

    _, update = fake_db.pyq_html_pages.update_one.call_args[0]
    assert update["$set"]["updated_at"] == "2024-06-01T12:00:00"
    assert update["$setOnInsert"]["created_at"] == "2024-01-01T00:00:00"


def test_none_db_handle_is_a_noop():
    # Production code paths guard with `if db is not None`; the helper must
    # mirror that contract so unit tests / scripts without a DB don't crash.
    _run(pyq_mod._upsert_pyq_html_page(None, "slug", {"foo": "bar"}))


def test_all_production_insert_sites_route_through_helper():
    """Static guarantee: no caller in routes/pyq.py writes to
    `pyq_html_pages` via a raw `update_one` / `insert_one` — every insert
    must go through `_upsert_pyq_html_page` so timestamps are guaranteed."""
    import inspect

    src = inspect.getsource(pyq_mod)
    # Strip the helper's own body so we only audit *callers*.
    helper_src = inspect.getsource(pyq_mod._upsert_pyq_html_page)
    callers_src = src.replace(helper_src, "")

    forbidden_patterns = [
        "pyq_html_pages.update_one",
        "pyq_html_pages.insert_one",
        "pyq_html_pages.insert_many",
        "pyq_html_pages.replace_one",
    ]
    for pat in forbidden_patterns:
        assert pat not in callers_src, (
            f"Direct `{pat}` call detected in routes/pyq.py outside the "
            "_upsert_pyq_html_page helper. Route the write through the "
            "helper so created_at/updated_at are guaranteed (Task #343)."
        )

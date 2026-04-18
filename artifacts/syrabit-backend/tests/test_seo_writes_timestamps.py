"""Regression test for Task #349 — every insert/upsert into
``seo_pages`` and ``seo_topics`` must stamp ``created_at`` (via
``$setOnInsert``) and ``updated_at`` (via ``$set``) so the missing-
publish-date problem fixed for PYQs in Task #343 cannot silently recur
on the SEO collections that drive Google freshness signals.

The test exercises the production helpers ``upsert_seo_page`` /
``upsert_seo_topic`` directly with a fake Mongo collection, then runs a
static guard over the call sites under ``artifacts/syrabit-backend`` to
guarantee no module bypasses the helpers with a raw ``insert_one`` /
``update_one(..., upsert=True)`` against either collection.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

from seo_writes import upsert_seo_page, upsert_seo_topic  # noqa: E402


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _make_fake_db() -> MagicMock:
    fake_db = MagicMock()
    fake_db.seo_pages.update_one = AsyncMock(return_value=None)
    fake_db.seo_topics.update_one = AsyncMock(return_value=None)
    return fake_db


def _run(coro):
    # Task #467: use asyncio.run() so each call gets a fresh event loop.
    # Earlier tests in the suite call asyncio.run() which closes the
    # default loop, leaving asyncio.get_event_loop() to raise
    # "There is no current event loop in thread 'MainThread'".
    return asyncio.run(coro)


def test_seo_page_fresh_insert_stamps_both_timestamps():
    fake_db = _make_fake_db()
    page_doc = {"html": "<p>x</p>", "page_type": "notes", "status": "published"}

    _run(upsert_seo_page(fake_db, {"topic_slug": "physics-motion"}, page_doc))

    fake_db.seo_pages.update_one.assert_awaited_once()
    args, kwargs = fake_db.seo_pages.update_one.call_args
    filt, update = args[0], args[1]

    assert filt == {"topic_slug": "physics-motion"}
    assert kwargs.get("upsert", False) is True
    assert "updated_at" in update["$set"]
    assert "created_at" in update["$setOnInsert"]
    assert _ISO.match(update["$set"]["updated_at"])
    assert _ISO.match(update["$setOnInsert"]["created_at"])
    # Caller payload is forwarded verbatim into $set.
    assert update["$set"]["html"] == "<p>x</p>"


def test_seo_topic_fresh_insert_stamps_both_timestamps():
    fake_db = _make_fake_db()
    topic_doc = {"title": "Motion", "slug": "physics-motion", "status": "draft"}

    _run(upsert_seo_topic(fake_db, {"slug": "physics-motion"}, topic_doc))

    args, kwargs = fake_db.seo_topics.update_one.call_args
    filt, update = args[0], args[1]
    assert filt == {"slug": "physics-motion"}
    assert kwargs.get("upsert") is True
    assert "updated_at" in update["$set"]
    assert "created_at" in update["$setOnInsert"]
    assert update["$set"]["title"] == "Motion"


def test_created_at_uses_set_on_insert_not_set():
    """If `created_at` were ever written via $set we'd overwrite the
    original publish date on every re-upsert, breaking Google freshness
    signals on the affected pages — exactly the regression #349 guards."""
    fake_db = _make_fake_db()
    _run(upsert_seo_page(fake_db, {"id": "p1"}, {"foo": "bar"}))
    _, update = fake_db.seo_pages.update_one.call_args[0]
    assert "created_at" not in update["$set"]

    _run(upsert_seo_topic(fake_db, {"slug": "t1"}, {"foo": "bar"}))
    _, update = fake_db.seo_topics.update_one.call_args[0]
    assert "created_at" not in update["$set"]


def test_caller_supplied_timestamps_are_honored():
    """Backfills and tests need to be able to override the stamps."""
    fake_db = _make_fake_db()
    doc = {
        "html": "<p>x</p>",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-06-01T12:00:00",
    }
    _run(upsert_seo_page(fake_db, {"id": "p1"}, doc))
    _, update = fake_db.seo_pages.update_one.call_args[0]
    assert update["$set"]["updated_at"] == "2024-06-01T12:00:00"
    assert update["$setOnInsert"]["created_at"] == "2024-01-01T00:00:00"


def test_set_on_insert_extra_is_merged_but_cannot_override_created_at():
    """Callers (e.g. qa_engine FAQ promotion) need to stamp insert-only
    fields like a generated `id` alongside the publish date. The helper
    must merge those in, but the publish-date guarantee always wins."""
    fake_db = _make_fake_db()
    _run(upsert_seo_page(
        fake_db,
        {"topic_slug": "x", "page_type": "faq"},
        {"html": "<p>x</p>"},
        set_on_insert_extra={"id": "faq-deadbeef", "created_at": "1999-01-01"},
    ))
    _, update = fake_db.seo_pages.update_one.call_args[0]
    soi = update["$setOnInsert"]
    assert soi["id"] == "faq-deadbeef"
    # created_at from set_on_insert_extra is silently dropped — the
    # helper's stamp wins so the publish-date guarantee is uniform.
    assert soi["created_at"] != "1999-01-01"
    assert _ISO.match(soi["created_at"])


def test_none_db_handle_is_a_noop():
    # Mirror the contract from `_upsert_pyq_html_page` so unit tests and
    # one-off scripts without a DB don't crash.
    _run(upsert_seo_page(None, {"id": "p"}, {"foo": "bar"}))
    _run(upsert_seo_topic(None, {"slug": "t"}, {"foo": "bar"}))


# ---------------------------------------------------------------------------
# Static guard: every production write to seo_pages / seo_topics that can
# create a document must go through the helper. This is what stops the
# next contributor from quietly reintroducing the bug.
# ---------------------------------------------------------------------------

# Site-relative paths so the regex output is readable in failure output.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Anything that can create a document. Pure `update_one(..., {"$set":..})`
# without `upsert=True` is fine — it can only modify existing rows and
# therefore cannot regress the publish-date guarantee.
_FORBIDDEN_PATTERNS = [
    r"\bseo_pages\.insert_one\b",
    r"\bseo_pages\.insert_many\b",
    r"\bseo_pages\.replace_one\b",
    r"\bseo_topics\.insert_one\b",
    r"\bseo_topics\.insert_many\b",
    r"\bseo_topics\.replace_one\b",
]

# `update_one(..., upsert=True)` and `update_many(..., upsert=True)` are
# detected separately because the `upsert=True` argument may sit on a
# later line. We grep for the call site and then look for upsert=True
# inside the same parenthesized expression.
_UPSERT_CALL_RE = re.compile(
    r"(seo_(?:pages|topics))\.(update_one|update_many|find_one_and_update)\s*\(",
)


def _audit_files():
    """Yield (path, source) for every production .py file we should
    audit. Tests, the helper module itself, and other test fixtures are
    intentionally excluded — they're allowed to talk to Mongo directly
    or to define the helper."""
    for path in _BACKEND_ROOT.rglob("*.py"):
        rel = path.relative_to(_BACKEND_ROOT).as_posix()
        if rel.startswith("tests/"):
            continue
        if rel == "seo_writes.py":
            continue
        # Skip vendored / generated dirs we don't ship with the API.
        if rel.startswith((".venv/", "venv/", "node_modules/")):
            continue
        try:
            yield rel, path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue


def _find_upsert_violations(rel: str, src: str):
    """Return a list of "<collection>.<method>" snippets in `src` where
    the call uses `upsert=True`. Skips occurrences that are explicitly
    annotated with `# allow-direct-seo-write` for future escape hatches."""
    violations = []
    for match in _UPSERT_CALL_RE.finditer(src):
        coll, method = match.group(1), match.group(2)
        # Slice from the call's "(" to its matching ")" so we can check
        # the keyword args without false positives from later code.
        start = match.end() - 1  # position of "("
        depth = 0
        end = start
        for i in range(start, len(src)):
            ch = src[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        snippet = src[start:end + 1]
        if "upsert=True" not in snippet:
            continue
        # Optional escape hatch for legitimate raw writes (e.g. a
        # migration script that has its own timestamping).
        line_start = src.rfind("\n", 0, match.start()) + 1
        line_end = src.find("\n", match.end())
        line = src[line_start:line_end if line_end != -1 else len(src)]
        if "allow-direct-seo-write" in line:
            continue
        violations.append(f"{rel}: {coll}.{method}(... upsert=True)")
    return violations


def test_no_caller_writes_to_seo_pages_or_topics_directly():
    """Static guarantee: all insert/upsert paths into seo_pages and
    seo_topics route through the seo_writes helpers. The next time
    someone adds a raw `update_one(..., upsert=True)` to either
    collection, this test fails and points them at the helper."""
    direct_violations: list[str] = []
    upsert_violations: list[str] = []

    direct_pattern = re.compile("|".join(_FORBIDDEN_PATTERNS))

    for rel, src in _audit_files():
        for hit in direct_pattern.findall(src):
            direct_violations.append(f"{rel}: {hit}")
        upsert_violations.extend(_find_upsert_violations(rel, src))

    msg_parts = []
    if direct_violations:
        msg_parts.append(
            "Found direct insert_one/insert_many/replace_one calls into "
            "seo_pages or seo_topics:\n  " + "\n  ".join(direct_violations)
        )
    if upsert_violations:
        msg_parts.append(
            "Found update_one/update_many(..., upsert=True) calls into "
            "seo_pages or seo_topics that bypass the helper:\n  "
            + "\n  ".join(upsert_violations)
        )
    assert not msg_parts, (
        "\n".join(msg_parts)
        + "\n\nRoute every insert/upsert through "
        "`seo_writes.upsert_seo_page` / `upsert_seo_topic` so the "
        "publish-date stamps required by Google freshness signals "
        "(Task #349) are guaranteed."
    )

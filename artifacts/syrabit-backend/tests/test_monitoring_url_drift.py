"""Task #887 — gate every monitored URL the worker / deploy infra hard-codes
against the live FastAPI route table.

Why this exists
---------------
Task #877 was a 56-hour outage caused by ``synthetic-probe.ts`` hitting
``/admin/diagnostics`` (no ``/api`` prefix) while the FastAPI router
was mounted under ``prefix="/api"``. Every probe 404'd, the watchdog
stayed dark, and the only way anyone caught it was reading prod logs.

The class of bug — "a URL hard-coded outside FastAPI silently goes out
of sync with the router prefix" — applies to every monitoring surface
that lives outside ``server.py``:

* the synthetic probe in ``workers/edge-proxy/src/synthetic-probe.ts``
* the cf-block-probe in ``workers/edge-proxy/src/cf-block-probe.ts``
* Railway's restart-probe ``healthcheckPath`` in ``railway.toml``
* the Docker ``HEALTHCHECK`` in ``Dockerfile``
* anything else added in the future

This test is the CI gate. It loads the canonical manifest at
``workers/edge-proxy/monitored-urls.json`` and asserts:

1. Every entry in ``backend_paths`` corresponds to a real route in
   the live FastAPI ``app.openapi()`` schema (exact-match by default;
   set ``"match": "prefix"`` to allow path-parameter routes like
   ``/api/foo/{id}`` to satisfy a prefix entry of ``/api/foo/``).
2. Every entry in ``intentionally_external`` carries a non-empty
   ``rationale`` and a non-empty ``registered_in`` list — so a future
   reader can tell *why* the URL is allowed to skip the OpenAPI
   check, and which file pointed it that way.
3. No URL accidentally appears in both lists.

When a developer renames or removes a backend route that any of these
surfaces depend on, this test fails loudly *before* the change can
ship — the on-call no longer has to read production logs to discover
the drift.

Adding a new monitored URL
--------------------------
1. Edit ``workers/edge-proxy/monitored-urls.json`` and add the entry
   (with a one-line ``rationale``).
2. If the URL is hard-coded inside the worker, import the constant
   from ``workers/edge-proxy/src/monitored-urls.ts`` rather than
   inlining the string — the runtime probe will then refuse to start
   if the manifest is out of date, closing the second half of the
   gate.
3. Run this test (``pytest -k monitoring_url_drift``) before pushing.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest


# Repo-root-relative paths. Resolved at import time so a missing manifest
# fails the test collection step (loud) instead of silently skipping.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST_PATH = _REPO_ROOT / "workers" / "edge-proxy" / "monitored-urls.json"


def _load_manifest() -> dict[str, Any]:
    if not _MANIFEST_PATH.exists():
        pytest.fail(
            f"monitored-urls manifest not found at {_MANIFEST_PATH}. "
            "Task #887 — every backend URL/path the worker hard-codes must "
            "be registered there."
        )
    with _MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return _load_manifest()


@pytest.fixture(scope="module")
def fastapi_app():
    """Boot the live FastAPI app once for the module, with the deps stub
    installed.

    All downstream fixtures (`openapi_methods` for Task #887/#916,
    `test_client` for Task #917) depend on this so the multi-second app
    boot — LLM key diagnostic, vertex client init, route registration —
    happens exactly once per pytest session of this file.

    Mirrors the dummy-env / deps-stub setup the dump script uses, so
    these tests run in the same environment as the production drift
    check (which calls ``dump_openapi.py`` directly in CI).

    ``config.py`` requires:
      * ``JWT_SECRET`` and ``ADMIN_JWT_SECRET`` each ≥64 chars,
      * the two values to be DISTINCT (reusing one raises
        ``ADMIN_JWT_SECRET must be different from JWT_SECRET``).
    Two independent ``token_hex(48)`` calls satisfy both rules.

    We overwrite (not ``setdefault``) so a runner with stale
    placeholders inherited from a parent shell (e.g. ``JWT_SECRET=test``)
    doesn't break the gate.
    """
    import secrets as _secrets
    from config import Configurator

    Configurator.set_runtime_env("MONGO_URL", "mongodb://localhost:27017/openapi-test")
    Configurator.set_runtime_env("JWT_SECRET", _secrets.token_hex(48))
    Configurator.set_runtime_env("ADMIN_JWT_SECRET", _secrets.token_hex(48))

    from tests._deps_stub import install_deps_stub  # type: ignore[import-not-found]

    stub = install_deps_stub(force=True)
    if not hasattr(stub, "mongo_client"):
        stub.mongo_client = None  # type: ignore[attr-defined]

    import server  # noqa: WPS433  (intentional in-fixture import)

    return server.app


@pytest.fixture(scope="module")
def openapi_methods(fastapi_app) -> dict[str, set[str]]:
    """Return ``{path: {METHOD, ...}}`` for the live FastAPI app.

    Methods are uppercased so the manifest's `method` field (also
    uppercase by convention) can be checked with a plain set membership.
    Task #916 uses this richer view to verify a probe's declared verb
    actually exists on the route — `openapi_paths` below is kept as a
    derived set for tests that only need the path keys.
    """
    # OpenAPI 3.x path-item keys are lowercase verb names plus a few
    # non-verb keys (``parameters``, ``summary``, ``description``,
    # ``servers``). Whitelist the verbs we care about so a future schema
    # extension cannot accidentally turn a stray key into a "method".
    verbs = ("get", "post", "put", "patch", "delete", "options", "head")
    paths = fastapi_app.openapi().get("paths", {})
    out: dict[str, set[str]] = {}
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        out[path] = {verb.upper() for verb in verbs if verb in item}
    return out


@pytest.fixture(scope="module")
def openapi_paths(openapi_methods: dict[str, set[str]]) -> set[str]:
    """Back-compat view: just the path keys. Tests that don't care about
    the method (Task #887 string-existence gate) keep using this."""
    return set(openapi_methods.keys())


@pytest.fixture(scope="module")
def test_client(fastapi_app):
    """In-process TestClient against the live FastAPI app — Task #917.

    Reuses the same boot (and deps stub) as ``openapi_methods`` so we
    pay the start-up cost exactly once. The client is module-scoped
    because the only test using it does a read-only, idempotent loop
    over the manifest entries — there is no per-test mutation that
    would require a fresh client.
    """
    from fastapi.testclient import TestClient  # noqa: WPS433  (intentional in-fixture import)

    return TestClient(fastapi_app)


# ─── Manifest shape ────────────────────────────────────────────────────


def test_manifest_has_required_top_level_keys(manifest: dict[str, Any]) -> None:
    for key in ("backend_paths", "intentionally_external"):
        assert key in manifest, (
            f"monitored-urls.json missing required top-level key {key!r}. "
            "See Task #887 docstring at the top of this file."
        )


def test_no_url_is_both_internal_and_external(manifest: dict[str, Any]) -> None:
    backend = {entry["path"] for entry in manifest["backend_paths"]}
    external = {entry["url"] for entry in manifest["intentionally_external"]}
    overlap = backend & external
    assert not overlap, (
        f"URLs appear in both backend_paths AND intentionally_external: {sorted(overlap)}. "
        "Pick one — a path is either an internal FastAPI route or an external URL."
    )


# ─── intentionally_external — rationale must be present ────────────────


def test_external_entries_carry_rationale_and_provenance(manifest: dict[str, Any]) -> None:
    for entry in manifest["intentionally_external"]:
        url = entry.get("url", "<missing>")
        rationale = (entry.get("rationale") or "").strip()
        registered_in = entry.get("registered_in") or []

        assert rationale, (
            f"intentionally_external entry {url!r} has no rationale. "
            "Task #887 requires a one-line explanation of WHY this URL is allowed "
            "to skip the FastAPI OpenAPI check (e.g. 'public homepage served by "
            "Cloudflare Pages, not the FastAPI backend')."
        )
        assert isinstance(registered_in, list) and registered_in, (
            f"intentionally_external entry {url!r} has no registered_in list. "
            "Add at least one source-file path so future readers can find where "
            "the URL is actually used."
        )

        # Sanity-check the URL is well-formed (scheme + host) so a stray
        # path like "/api/foo" cannot sneak through the external escape
        # hatch.
        assert re.match(r"^https?://", url), (
            f"intentionally_external entry {url!r} is not an http(s) URL. "
            "Internal FastAPI paths (e.g. '/api/...') belong in backend_paths, "
            "not intentionally_external."
        )


# ─── backend_paths — must each resolve to a real OpenAPI route ────────


# Methods the manifest is allowed to declare. Limited to the verbs the
# worker is realistically going to send; OPTIONS / HEAD / TRACE are not
# probe targets and have no business in the manifest.
_ALLOWED_METHODS: frozenset[str] = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


def _entry_method(entry: dict[str, Any]) -> str:
    """Return the uppercase HTTP method declared by ``entry``.

    Defaults to ``"GET"`` when the field is absent — the overwhelming
    majority of monitored URLs are probes / cacheable reads, so requiring
    every existing entry to spell out ``"method": "GET"`` would be noise.
    """
    raw = (entry.get("method") or "GET").strip().upper()
    return raw


def _path_resolves(
    path: str,
    match: str,
    method: str,
    openapi_methods: dict[str, set[str]],
) -> bool:
    """Does ``path`` correspond to a real FastAPI route that accepts
    ``method``?

    ``exact``  — the path string must appear verbatim in the OpenAPI
                 schema *and* the path item must expose ``method``.
                 This is the strictest mode and the right default for
                 healthcheck / probe targets where the worker hits one
                 specific endpoint with one specific verb.
    ``prefix`` — the path string must be a prefix of at least one
                 OpenAPI path that itself exposes ``method``. Use this
                 for paths the worker treats as a routing prefix (e.g.
                 ``/api/content/chapters/`` is a valid prefix for
                 ``/api/content/chapters/{chapter_id}``). The
                 method-on-prefix check is intentionally weaker than the
                 exact variant: a prefix is a route family, not a
                 single endpoint, so requiring every path under the
                 prefix to support the method would be wrong (e.g.
                 ``/api/auth`` covers both GET ``/auth/me`` and POST
                 ``/auth/login``). The check still catches the Task
                 #877 / #916 failure mode of "the entire prefix has no
                 route at all that accepts this verb".

    Path-parameter segments (``{id}``) are honoured during the prefix
    comparison so the literal text up to the first ``{`` decides the
    match.
    """
    if match == "exact":
        return method in openapi_methods.get(path, set())
    if match == "prefix":
        # Compare against the literal-prefix portion of each OpenAPI
        # path. ``startswith(path)`` would already match
        # ``/api/foo/{id}`` for the prefix ``/api/foo/`` because the
        # first 9 chars are identical, so a plain startswith is enough.
        return any(
            p.startswith(path) and method in methods
            for p, methods in openapi_methods.items()
        )
    raise ValueError(f"unknown match mode: {match!r}")


def test_every_backend_path_exists_in_openapi(
    manifest: dict[str, Any],
    openapi_methods: dict[str, set[str]],
) -> None:
    failures: list[str] = []
    for entry in manifest["backend_paths"]:
        path = entry.get("path", "<missing>")
        match = entry.get("match", "exact")
        rationale = (entry.get("rationale") or "").strip()
        registered_in = entry.get("registered_in") or []
        method = _entry_method(entry)

        if not rationale:
            failures.append(
                f"backend_paths entry {path!r}: no rationale (Task #887 requires one)."
            )
            continue
        if not (isinstance(registered_in, list) and registered_in):
            failures.append(
                f"backend_paths entry {path!r}: empty registered_in list."
            )
            continue
        if match not in ("exact", "prefix"):
            failures.append(
                f"backend_paths entry {path!r}: invalid match mode {match!r} "
                "(use 'exact' or 'prefix')."
            )
            continue
        if method not in _ALLOWED_METHODS:
            failures.append(
                f"backend_paths entry {path!r}: invalid method {method!r} "
                f"(allowed: {sorted(_ALLOWED_METHODS)}). Task #916 — annotate "
                "with the uppercase HTTP verb the worker actually sends."
            )
            continue
        if not _path_resolves(path, match, method, openapi_methods):
            # Tailor the failure message to whether the path itself is
            # missing (Task #877) or only the method is missing (Task
            # #916). The two failure modes call for different fixes so
            # the on-call should not have to guess.
            path_known = path in openapi_methods or any(
                p.startswith(path) for p in openapi_methods
            )
            if path_known:
                failures.append(
                    f"backend_paths entry {path!r} (match={match}, "
                    f"registered in {registered_in}) resolves to a real "
                    f"FastAPI route, but no route under it accepts {method!r}. "
                    "Either fix the manifest's `method` to match what the "
                    "route actually exposes, or fix the worker to send the "
                    "right verb (Task #916 — a probe that GETs a POST-only "
                    "endpoint will 405 forever, same silent-failure shape "
                    "as Task #877)."
                )
            else:
                failures.append(
                    f"backend_paths entry {path!r} (match={match}, "
                    f"method={method}, registered in {registered_in}) does "
                    "NOT resolve to any FastAPI route in the live OpenAPI "
                    "schema. Either the route was renamed/removed (update "
                    "the hard-coded URL in the file above to match the new "
                    "path AND update monitored-urls.json), or the entry is "
                    "stale and should be removed from the manifest."
                )

    assert not failures, (
        "monitored-URL drift detected — see Task #877 / Task #916 for the "
        "failure modes this test guards against:\n  - " + "\n  - ".join(failures)
    )


# ─── Negative test — the method gate actually catches wrong-verb drift ──
#
# Task #916 — without this, a future refactor that accidentally
# loosens `_path_resolves` (e.g. dropping the method check from the
# prefix branch) would silently re-open the gap. Drive the resolver
# against a hand-built openapi_methods view so the assertions don't
# depend on which routes the live FastAPI app happens to expose at
# any given moment.


def test_path_resolves_enforces_method() -> None:
    fake_openapi: dict[str, set[str]] = {
        "/api/livez": {"GET"},
        "/api/ai/chat": {"POST"},
        "/api/ai/chat/stream": {"POST"},
        "/api/auth/me": {"GET"},
        "/api/auth/login": {"POST"},
    }

    # Exact match — verb must be present on the literal path.
    assert _path_resolves("/api/livez", "exact", "GET", fake_openapi), (
        "sanity: /api/livez exposes GET in the planted schema"
    )
    assert not _path_resolves("/api/livez", "exact", "POST", fake_openapi), (
        "Task #916 gate is broken: a probe that POSTs a GET-only endpoint "
        "should be flagged."
    )

    # Prefix match — verb must be present on at least one path under
    # the prefix, but NOT on every one.
    assert _path_resolves("/api/ai/chat", "prefix", "POST", fake_openapi), (
        "sanity: /api/ai/chat covers POST routes"
    )
    assert not _path_resolves("/api/ai/chat", "prefix", "GET", fake_openapi), (
        "Task #916 prefix gate is broken: no route under /api/ai/chat "
        "exposes GET, so a worker GETting this prefix should be flagged."
    )
    # Mixed-method prefix: /api/auth has both verbs; either should pass.
    assert _path_resolves("/api/auth", "prefix", "GET", fake_openapi)
    assert _path_resolves("/api/auth", "prefix", "POST", fake_openapi)
    # And a prefix that matches nothing must fail regardless of method.
    assert not _path_resolves("/api/missing/", "prefix", "GET", fake_openapi)


def test_entry_method_defaults_to_get() -> None:
    # Backward-compat: existing manifest entries that omit `method`
    # must continue to behave as GET probes — anything else would
    # silently break every entry in the manifest.
    assert _entry_method({}) == "GET"
    assert _entry_method({"method": "post"}) == "POST"  # case-insensitive
    assert _entry_method({"method": "  PUT  "}) == "PUT"  # whitespace tolerant


def test_planted_wrong_method_is_caught_against_live_openapi(
    openapi_methods: dict[str, set[str]],
) -> None:
    # Drive the resolver against a manifest entry that points at a real
    # path but lies about the method. This proves the gate is wired up
    # end-to-end against the live FastAPI app, not just the synthetic
    # fake above.
    livez_methods = openapi_methods.get("/api/livez", set())
    if not livez_methods:
        pytest.skip(
            "live FastAPI app does not expose /api/livez — skipping the "
            "live-schema half of the Task #916 gate. The synthetic "
            "test_path_resolves_enforces_method test above still proves "
            "the resolver behaves correctly."
        )
    assert "GET" in livez_methods, (
        "fixture sanity: /api/livez should still be a GET healthcheck."
    )
    # If the manifest claimed /api/livez accepts POST, the resolver
    # must say "no" — the gate is what stops a future probe refactor
    # from quietly POSTing the healthcheck.
    assert not _path_resolves("/api/livez", "exact", "POST", openapi_methods), (
        "Task #916 — a manifest entry claiming /api/livez accepts POST "
        "must be flagged, otherwise a probe that POSTs a GET-only "
        "healthcheck would silently 405 forever (same outage shape as "
        "Task #877)."
    )


# ─── In-process probe smoke — every backend_paths entry returns < 500 ──
#
# Task #917 — the Task #877/#887/#901/#916 gates prove a path exists,
# is referenced by the right source file, and exposes the declared
# verb. None of them actually CALL the route. A handler that's
# registered but raises 500 on every request (broken DI, missing
# collection, malformed config, await on a non-awaitable) would pass
# every existing gate and only blow up in production. This test boots
# the FastAPI app under TestClient and hits each manifest entry
# in-process, asserting the response is not 5xx.
#
# Auth-gated routes (e.g. /api/admin/diagnostics) are expected to
# return 401/403 — that's < 500 and so satisfies the gate. POST
# routes hit with an empty body typically return 422 / 401 / 405,
# also < 500. Prefix entries that don't match a literal route (e.g.
# /api/content/chapters/ → real route is /api/content/chapters/{id})
# return 404, which is also fine: the gate is "does the app crash
# when this URL is hit", not "does the URL serve real data".
#
# Skip-list — entries whose handler 5xxs only because of a
# tests/_deps_stub.py limitation (e.g. motor cursor patterns the
# stub does not yet model) declare ``smoke_skip_reason`` in the
# manifest. That reason is surfaced verbatim in pytest -v output so
# a future reader can decide whether to fix the stub or fix the route.


def test_every_backend_probe_does_not_5xx(
    manifest: dict[str, Any],
    test_client,
    request: pytest.FixtureRequest,
) -> None:
    failures: list[str] = []
    skipped: list[str] = []

    for entry in manifest["backend_paths"]:
        path = entry.get("path", "<missing>")
        method = (entry.get("method") or "GET").strip().upper()
        skip_reason = (entry.get("smoke_skip_reason") or "").strip()

        if skip_reason:
            skipped.append(f"{method} {path} — skipped: {skip_reason}")
            continue

        try:
            response = test_client.request(
                method,
                path,
                follow_redirects=False,
            )
        except Exception as exc:  # noqa: BLE001  (surface ANY crash as a probe-smoke failure)
            failures.append(
                f"{method} {path} raised {type(exc).__name__}: {exc!r} "
                "(handler crashed before producing a response — would "
                "be a 502/503 from the worker in production)."
            )
            continue

        if response.status_code >= 500:
            body_preview = response.text[:200].replace("\n", " ").replace("\r", " ")
            failures.append(
                f"{method} {path} → HTTP {response.status_code}: {body_preview}"
            )

    # Surface skips so a reviewer can spot a manifest entry that's
    # been silently skipping for too long. Pytest's `--capture=no`
    # surfaces this; with default capture it shows up on failure.
    if skipped:
        terminalreporter = request.config.pluginmanager.get_plugin("terminalreporter")
        if terminalreporter is not None:
            terminalreporter.write_line(
                f"\n[probe-smoke] skipped {len(skipped)} entr{'y' if len(skipped) == 1 else 'ies'} "
                f"with smoke_skip_reason:"
            )
            for line in skipped:
                terminalreporter.write_line(f"  - {line}")

    assert not failures, (
        "Task #917 — at least one monitored backend_paths probe target "
        "raised a 5xx response under the in-process TestClient. The "
        "route is registered (so the Task #877/#887/#901/#916 gates "
        "pass) but broken in a way that would only show up in "
        "production. Either fix the route, or — if the failure is a "
        "known stub artifact (e.g. the handler awaits a motor cursor "
        "the test stub does not model) — annotate the manifest entry "
        "with `smoke_skip_reason` explaining why and pointing at the "
        "tracking ticket:\n  - " + "\n  - ".join(failures)
    )


# ─── Manifest entries actually point at the files they claim to ───────
#
# Soft check — if a `registered_in` file no longer exists, the manifest
# entry is stale. This catches "we deleted synthetic-probe.ts but forgot
# to remove its monitored-urls.json entry" before the dead entry rots
# for months.


def test_registered_in_files_exist(manifest: dict[str, Any]) -> None:
    missing: list[str] = []
    for section in ("backend_paths", "intentionally_external"):
        for entry in manifest[section]:
            label = entry.get("path") or entry.get("url") or "<unknown>"
            for rel in entry.get("registered_in", []):
                full = _REPO_ROOT / rel
                if not full.exists():
                    missing.append(f"{section}:{label!r} → {rel} (not found)")
    assert not missing, (
        "monitored-urls.json references files that no longer exist — the "
        "entry is stale and should be deleted (or the path corrected):\n  - "
        + "\n  - ".join(missing)
    )


# ─── Manifest entries are still actually USED by the files they claim ──
#
# Task #901 — the `registered_in` existence check above proves the file
# is still on disk, but says nothing about whether the file still
# references the path. A common drift mode is: somebody refactors
# `synthetic-probe.ts` to call a different path (or moves the constant
# elsewhere) but forgets to update `monitored-urls.json`. The dead
# manifest entry then rots silently for months — the OpenAPI gate keeps
# passing because the path itself still exists, but nothing in the
# worker actually hits it anymore, so the probe it was meant to guard
# is gone.
#
# This check closes the gap by grepping each `registered_in` file for
# either the literal path/URL string OR the declared `runtime_constant`
# export name. Files that compute the path via concatenation (e.g.
# `BACKEND_URL + SYNTHETIC_PROBE_PATH`) opt into the constant-name
# variant by setting `runtime_constant` on the manifest entry.


def _check_entry_referenced_in_files(
    entry: dict[str, Any],
    base_dir: Path,
) -> list[str]:
    """Return human-readable failure strings for one manifest entry.

    Empty list ⇒ every `registered_in` file mentions the path (or its
    declared runtime constant). The function is pure (no I/O outside
    reading the listed files) so the negative test below can drive it
    against a planted entry under a tmp directory.
    """
    needle_path = entry.get("path") or entry.get("url")
    if not needle_path:
        return [f"entry {entry!r} has neither 'path' nor 'url'"]
    runtime_constant = (entry.get("runtime_constant") or "").strip()
    failures: list[str] = []
    for rel in entry.get("registered_in", []):
        full = base_dir / rel
        if not full.exists():
            # A separate test (`test_registered_in_files_exist`) covers
            # the missing-file case with a clearer error message — skip
            # here so we don't double-report.
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            failures.append(
                f"entry {needle_path!r}: could not read {rel} ({exc})."
            )
            continue
        if needle_path in text:
            continue
        if runtime_constant and runtime_constant in text:
            continue
        if runtime_constant:
            failures.append(
                f"entry {needle_path!r}: file {rel} contains neither the "
                f"literal path nor the declared runtime_constant "
                f"{runtime_constant!r}. Either restore the reference, "
                "update `runtime_constant` to the new export name, or "
                "remove this entry from monitored-urls.json."
            )
        else:
            failures.append(
                f"entry {needle_path!r}: file {rel} no longer contains "
                "the literal path string. If the file now reaches the "
                "path through an imported constant, add "
                "`\"runtime_constant\": \"<EXPORT_NAME>\"` to this "
                "manifest entry. Otherwise the entry is stale — remove it."
            )
    return failures


def test_registered_in_files_still_reference_path(manifest: dict[str, Any]) -> None:
    failures: list[str] = []
    for section in ("backend_paths", "intentionally_external"):
        for entry in manifest[section]:
            failures.extend(_check_entry_referenced_in_files(entry, _REPO_ROOT))
    assert not failures, (
        "monitored-urls.json has entries whose registered_in file no "
        "longer references the path (Task #901 — silent manifest rot). "
        "Either fix the file, update the manifest, or remove the entry:"
        "\n  - " + "\n  - ".join(failures)
    )


# ─── Negative test — the new check actually fails on stale entries ────
#
# Without this, a future refactor that accidentally short-circuits
# `_check_entry_referenced_in_files` (e.g. a stray `return []`) would
# silently re-open the gap. Plant a stale entry under a tmp directory
# and assert the helper flags it.


def test_drift_check_flags_stale_registered_in(tmp_path: Path) -> None:
    # File exists but does NOT mention the path or the declared
    # runtime constant — the canonical "manifest rot" failure mode.
    # NB: keep the file body free of the path string (even in comments)
    # so a substring match cannot accidentally satisfy the check.
    stale_file = tmp_path / "src" / "fake-probe.ts"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text(
        "// Refactored: this file no longer references the old endpoint.\n"
        "export function noop() { return 0; }\n",
        encoding="utf-8",
    )

    stale_entry = {
        "path": "/api/old/path",
        "match": "exact",
        "rationale": "(test fixture)",
        "registered_in": ["src/fake-probe.ts"],
    }
    failures = _check_entry_referenced_in_files(stale_entry, tmp_path)
    assert failures, (
        "_check_entry_referenced_in_files must flag a registered_in "
        "file that no longer mentions the path — the Task #901 gate "
        "depends on this returning a non-empty list."
    )
    assert any("/api/old/path" in msg for msg in failures), (
        f"failure message should name the offending path; got {failures!r}"
    )

    # Sanity: planting the literal back into the file makes the check pass.
    stale_file.write_text(
        "// Restored: hits /api/old/path on every cron tick.\n"
        "export const PATH = \"/api/old/path\";\n",
        encoding="utf-8",
    )
    assert _check_entry_referenced_in_files(stale_entry, tmp_path) == [], (
        "after restoring the literal path string, the check should pass."
    )

    # Sanity: declaring a runtime_constant is also enough — the file
    # mentions the export name even though the literal path is absent.
    stale_file.write_text(
        "import { OLD_PATH } from \"./constants\";\n"
        "export const target = OLD_PATH;\n",
        encoding="utf-8",
    )
    entry_with_constant = {**stale_entry, "runtime_constant": "OLD_PATH"}
    assert _check_entry_referenced_in_files(entry_with_constant, tmp_path) == [], (
        "runtime_constant escape hatch should let the check pass when "
        "the file references the declared export name instead of the "
        "literal path."
    )

    # And: a runtime_constant whose name is also missing must still fail.
    entry_with_missing_constant = {
        **stale_entry,
        "runtime_constant": "DEFINITELY_NOT_IN_THE_FILE",
    }
    stale_file.write_text(
        "// Refactored to use a different constant entirely.\n"
        "export function noop() { return 0; }\n",
        encoding="utf-8",
    )
    failures = _check_entry_referenced_in_files(entry_with_missing_constant, tmp_path)
    assert failures, (
        "when neither the literal path nor the declared runtime_constant "
        "appears in the file, the check must fail loudly."
    )
    assert any("DEFINITELY_NOT_IN_THE_FILE" in msg for msg in failures), (
        f"failure message should mention the missing runtime_constant; got {failures!r}"
    )

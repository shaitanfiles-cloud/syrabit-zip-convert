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
def openapi_paths() -> set[str]:
    """Return the set of paths the live FastAPI app exposes.

    We import ``server`` lazily inside the fixture (rather than at module
    load) so collection of this test file does not pay the multi-second
    cost of standing up the LLM key diagnostic, vertex client, etc.
    """
    # Mirror the dummy-env / deps-stub setup the dump script uses, so this
    # test runs in the same environment as the production drift check
    # (which calls dump_openapi.py directly in CI).
    #
    # ``config.py`` requires:
    #   * ``JWT_SECRET`` and ``ADMIN_JWT_SECRET`` each ≥64 chars,
    #   * the two values to be DISTINCT (reusing one raises
    #     ``ADMIN_JWT_SECRET must be different from JWT_SECRET``).
    # Two independent ``token_hex(48)`` calls satisfy both rules.
    #
    # We overwrite (not ``setdefault``) so a runner with stale
    # placeholders inherited from a parent shell (e.g.
    # ``JWT_SECRET=test``) doesn't break the gate.
    import secrets as _secrets

    os.environ["MONGO_URL"] = "mongodb://localhost:27017/openapi-test"
    os.environ["JWT_SECRET"] = _secrets.token_hex(48)
    os.environ["ADMIN_JWT_SECRET"] = _secrets.token_hex(48)
    os.environ["ADMIN_PASSWORDS"] = "openapi-test-no-real-password"

    from tests._deps_stub import install_deps_stub  # type: ignore[import-not-found]

    stub = install_deps_stub(force=True)
    if not hasattr(stub, "mongo_client"):
        stub.mongo_client = None  # type: ignore[attr-defined]

    import server  # noqa: WPS433  (intentional in-fixture import)

    return set(server.app.openapi().get("paths", {}).keys())


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


def _path_resolves(path: str, match: str, openapi_paths: set[str]) -> bool:
    """Does ``path`` correspond to a real FastAPI route?

    ``exact``  — the path string must appear verbatim in the OpenAPI
                 schema. This is the strictest mode and the right
                 default for healthcheck / probe targets.
    ``prefix`` — the path string must be a prefix of at least one
                 OpenAPI path. Use this for paths the worker treats as
                 a routing prefix (e.g. ``/api/content/chapters/`` is a
                 valid prefix for ``/api/content/chapters/{chapter_id}``).
                 Path-parameter segments (``{id}``) are honoured during
                 the prefix comparison so the literal text up to the
                 first ``{`` decides the match.
    """
    if match == "exact":
        return path in openapi_paths
    if match == "prefix":
        # Compare against the literal-prefix portion of each OpenAPI
        # path. ``startswith(path)`` would already match
        # ``/api/foo/{id}`` for the prefix ``/api/foo/`` because the
        # first 9 chars are identical, so a plain startswith is enough.
        return any(p.startswith(path) for p in openapi_paths)
    raise ValueError(f"unknown match mode: {match!r}")


def test_every_backend_path_exists_in_openapi(
    manifest: dict[str, Any],
    openapi_paths: set[str],
) -> None:
    failures: list[str] = []
    for entry in manifest["backend_paths"]:
        path = entry.get("path", "<missing>")
        match = entry.get("match", "exact")
        rationale = (entry.get("rationale") or "").strip()
        registered_in = entry.get("registered_in") or []

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
        if not _path_resolves(path, match, openapi_paths):
            failures.append(
                f"backend_paths entry {path!r} (match={match}, "
                f"registered in {registered_in}) does NOT resolve to any "
                "FastAPI route in the live OpenAPI schema. Either the route "
                "was renamed/removed (update the hard-coded URL in the file "
                "above to match the new path AND update monitored-urls.json), "
                "or the entry is stale and should be removed from the manifest."
            )

    assert not failures, (
        "monitored-URL drift detected — see Task #877 for the failure mode "
        "this test guards against:\n  - " + "\n  - ".join(failures)
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

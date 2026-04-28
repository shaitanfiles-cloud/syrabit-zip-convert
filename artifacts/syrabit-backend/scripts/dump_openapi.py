"""Dump the FastAPI OpenAPI schema to stdout as JSON.

Task #887 — used by the monitoring-URL drift check
(``tests/test_monitoring_url_drift.py``) and by anyone who wants the
canonical list of routes the backend serves without spinning up the
real container.

Usage::

    python artifacts/syrabit-backend/scripts/dump_openapi.py > openapi.json

Implementation notes
--------------------
The real ``server`` import requires a fully-configured environment
(Mongo URL, JWT secrets, etc.) plus a number of optional integrations
(Cerebras, Sarvam, Groq) it eagerly initialises at module load. To make
this script runnable on a vanilla CI runner without leaking any of
those secrets, we:

* set the four required env vars to high-entropy throwaway values that
  satisfy ``config.py``'s length checks;
* pre-install the synthetic ``deps`` stub from ``tests/_deps_stub.py``
  so ``from deps import ...`` resolves to in-memory mocks instead of
  trying to dial real Mongo / Postgres / Redis;
* fill in the few attributes the stub does not yet ship (``mongo_client``)
  so ``server`` can ``from deps import mongo_client`` without raising;
* silence INFO-level startup noise on stderr so the only thing on
  stdout is the JSON document the caller is waiting for.

The script does NOT start the FastAPI lifespan handler, which means the
Mongo / Vertex / Sarvam clients are not actually opened. That is by
design — the only thing this script needs is ``app.openapi()``, which
is computed from the in-process route registry and does not perform any
I/O.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sys
from pathlib import Path


def _silence_startup_logs() -> None:
    """Mute the INFO-level startup chatter so stdout stays clean JSON."""
    logging.disable(logging.CRITICAL)


def _set_dummy_env() -> None:
    """Satisfy ``config.py``'s _require_secret length checks.

    Rules ``config.py`` enforces (and that this helper has to honour):

    * ``JWT_SECRET`` and ``ADMIN_JWT_SECRET`` must each be ≥64 chars of
      high-entropy randomness — short / placeholder values raise.
    * ``ADMIN_JWT_SECRET`` must be **distinct** from ``JWT_SECRET`` —
      reusing the same value raises ``ADMIN_JWT_SECRET must be
      different from JWT_SECRET``. Two independent ``token_hex(48)``
      calls satisfy this.
    * ``ADMIN_PASSWORDS`` must be set and non-empty.

    We **overwrite** these vars unconditionally rather than using
    ``setdefault`` so that a runner with stale / bad placeholders
    inherited from a parent shell (e.g. ``JWT_SECRET=test`` left over
    from an earlier debug session) still produces a clean OpenAPI dump.
    The dummy values are throwaway randomness — nothing the FastAPI app
    is going to *use* for auth, since we never start the lifespan.
    """
    from config import Configurator
    Configurator.set_runtime_env("MONGO_URL", "mongodb://localhost:27017/openapi-dump")
    Configurator.set_runtime_env("JWT_SECRET", secrets.token_hex(48))
    Configurator.set_runtime_env("ADMIN_JWT_SECRET", secrets.token_hex(48))
    Configurator.set_runtime_env("ADMIN_PASSWORDS", "openapi-dump-no-real-password")


def _install_deps_stub() -> None:
    """Replace ``deps`` with the in-memory mock the backend test suite uses.

    The stub already covers the vast majority of names ``server`` and
    every route module import. The only gap relevant to ``server.py``'s
    ``from deps import (...mongo_client...)`` statement is
    ``mongo_client`` itself; we patch it to ``None`` after the stub
    install (the live shutdown handler tolerates a ``None`` client).
    """
    backend_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(backend_root))
    sys.path.insert(0, str(backend_root / "tests"))

    from _deps_stub import install_deps_stub  # noqa: E402  (path setup above)

    stub = install_deps_stub(force=True)
    if not hasattr(stub, "mongo_client"):
        stub.mongo_client = None  # type: ignore[attr-defined]


def main() -> int:
    _silence_startup_logs()
    _set_dummy_env()
    _install_deps_stub()

    # Importing ``server`` triggers ``_validate_env()`` and the LLM key
    # diagnostic. Both are silenced by ``_silence_startup_logs()`` above.
    import server  # noqa: E402

    schema = server.app.openapi()
    json.dump(schema, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

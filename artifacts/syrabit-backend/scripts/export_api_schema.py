"""Export the FastAPI OpenAPI schema to a JSON file.

Task #4 — connect test stubs to real API contracts.

Writes the canonical OpenAPI JSON to the path given as the first CLI
argument (defaults to ``artifacts/syrabit/tests/api-schema.json``
relative to the repo root).

Compared to ``dump_openapi.py`` (task #887, writes to stdout) this
script:

* Silences ``print()`` calls fired during module-level config
  initialisation — some config helpers call ``print()`` directly
  (not ``logging``), which would corrupt a redirected stdout stream.
* Writes the output to a **file** rather than stdout so CI pipelines
  can invoke it without complex shell redirection.

Usage::

    python artifacts/syrabit-backend/scripts/export_api_schema.py
    python artifacts/syrabit-backend/scripts/export_api_schema.py /path/to/out.json
"""

from __future__ import annotations

import builtins
import json
import logging
import os
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "artifacts" / "syrabit" / "tests" / "api-schema.json"


def _noop_print(*_args, **_kwargs) -> None:  # noqa: ANN002
    pass


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT

    logging.disable(logging.CRITICAL)

    backend_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(backend_root))
    sys.path.insert(0, str(backend_root / "tests"))

    original_print = builtins.print
    builtins.print = _noop_print  # type: ignore[assignment]

    try:
        from config import Configurator  # noqa: E402 (path setup above)

        Configurator.set_runtime_env("MONGO_URL", "mongodb://localhost:27017/openapi-dump")
        Configurator.set_runtime_env("JWT_SECRET", secrets.token_hex(48))
        Configurator.set_runtime_env("ADMIN_JWT_SECRET", secrets.token_hex(48))

        from _deps_stub import install_deps_stub  # noqa: E402

        stub = install_deps_stub(force=True)
        if not hasattr(stub, "mongo_client"):
            stub.mongo_client = None  # type: ignore[attr-defined]

        import server  # noqa: E402

        schema = server.app.openapi()
    finally:
        builtins.print = original_print  # type: ignore[assignment]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(schema, fh, sort_keys=True, indent=2)
        fh.write("\n")

    print(f"OpenAPI schema written to {out_path} ({out_path.stat().st_size:,} bytes, {len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

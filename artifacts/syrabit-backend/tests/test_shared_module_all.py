"""Task #449: lock down the public surface of the seven shared backend
modules (`config`, `deps`, `cache`, `db_ops`, `rag`, `utils`,
`analytics_helpers`).

Task #443 was a backend-down outage caused by a wildcard
`from config import *` re-exporting `pathlib.Path` into a route module
that also imported `fastapi.Path`. Task #447 removed every wildcard
import from route modules. This test makes the protection durable:

1. Each shared module defines an `__all__` list. We assert every name
   in `__all__` is actually a real attribute of the module — so a
   rename/removal of a shared symbol surfaces here instead of at
   gunicorn boot.
2. None of these modules contains `from X import *` itself, so they
   cannot transitively re-leak third-party top-level names (the
   pathlib/os/json/asyncio class of #443).
"""
from __future__ import annotations

import ast
import importlib
import pathlib

import pytest


SHARED_MODULES = [
    "config",
    "deps",
    "cache",
    "db_ops",
    "rag",
    "utils",
    "analytics_helpers",
]

BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("module_name", SHARED_MODULES)
def test_shared_module_declares_all(module_name: str):
    mod = importlib.import_module(module_name)
    assert hasattr(mod, "__all__"), (
        f"{module_name}.py must define `__all__` — it is part of the "
        f"project's shared API surface (see Task #449)."
    )
    assert isinstance(mod.__all__, list), (
        f"{module_name}.__all__ must be a list, got {type(mod.__all__)!r}."
    )
    assert mod.__all__, f"{module_name}.__all__ must not be empty."


@pytest.mark.parametrize("module_name", SHARED_MODULES)
def test_shared_module_all_names_resolve(module_name: str):
    mod = importlib.import_module(module_name)
    missing = [name for name in mod.__all__ if not hasattr(mod, name)]
    assert not missing, (
        f"{module_name}.__all__ lists names not defined in the module: "
        f"{missing}. Either define them or remove from __all__."
    )


@pytest.mark.parametrize("module_name", SHARED_MODULES)
def test_shared_module_no_wildcard_imports(module_name: str):
    src = (BACKEND_DIR / f"{module_name}.py").read_text()
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    offenders.append(
                        f"line {node.lineno}: from {node.module} import *"
                    )
    assert not offenders, (
        f"{module_name}.py must not use `from X import *` — wildcard "
        f"imports re-export every top-level name in X and caused the "
        f"#443 outage. Offending lines: {offenders}"
    )

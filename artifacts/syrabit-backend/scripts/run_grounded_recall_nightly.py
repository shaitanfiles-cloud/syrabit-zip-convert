"""Standalone runner for the nightly grounded-recall benchmark (Task #587).

This is the entry point a Railway scheduled job (or any external cron /
GitHub Action shelling into the deployed backend container) calls to:

  1. Run ``bench.grounded_recall`` against the *live* retrievers.
  2. Persist ``bench/results/latest.json`` so the admin tile reflects
     the production retrievers, not the committed offline baseline.
  3. Compare ``recall@5`` against the committed baseline and, when the
     drop exceeds the configured gate, fire ``metrics._dispatch_alert``
     so admins get an email + Slack ping with the metric delta and the
     list of misses.

The same ``run_and_alert_live`` helper is used by the in-process
scheduler in ``server.py``; this script exists so ops can run the bench
on demand or wire it to an external scheduler without going through the
admin HTTP surface.

Exit codes:
    0  bench ran and stayed within the gate
    2  bench ran but recall@5 regressed past the gate
    3  bench failed to run (dependency/env error)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bench.nightly.cli")


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gate", type=float, default=None,
                        help="Max allowed recall@5 drop vs baseline. "
                             "Defaults to GROUNDED_RECALL_NIGHTLY_GATE or 0.05.")
    parser.add_argument("--no-save", action="store_true",
                        help="Do not write bench/results/latest.json (debug only).")
    parser.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON to stdout.")
    args = parser.parse_args()

    try:
        from bench.grounded_recall import run_and_alert_live
    except Exception as exc:
        logger.error(f"failed to import bench.grounded_recall: {exc}")
        return 3

    try:
        result = asyncio.run(run_and_alert_live(gate=args.gate, save=not args.no_save))
    except Exception as exc:
        logger.exception(f"nightly bench crashed: {exc}")
        return 3

    if args.json:
        json.dump(
            {k: v for k, v in result.items() if k != "report"} | {
                "metrics": (result.get("report") or {}).get("metrics", {}),
                "total_cases": (result.get("report") or {}).get("total_cases"),
            },
            sys.stdout, indent=2,
        )
        print()
    else:
        metrics = (result.get("report") or {}).get("metrics", {})
        logger.info(
            "nightly grounded-recall finished: gate_failed=%s drop=%.4f "
            "metrics=%s alert_dispatched=%s saved_to=%s",
            result.get("gate_failed"), result.get("drop", 0.0),
            json.dumps(metrics), result.get("alert_dispatched"),
            result.get("saved_to"),
        )

    return 2 if result.get("gate_failed") else 0


if __name__ == "__main__":
    sys.exit(_main())

#!/usr/bin/env python3
"""Cloudflare WAF emergency-override orchestrator (Task #825).

Companion to ``cf_ray_lookup.py`` (which is read-only). This script
performs the **write** operations needed to defuse a managed-ruleset
false positive without leaving the zone in a permanently-degraded
state. Every step is idempotent and saves enough state to a local file
so the operator can rollback to the original action without manually
remembering values.

Why this is its own script
--------------------------
The runbook in ``docs/CLOUDFLARE_ZERO_TRUST.md`` §8.4 documents the raw
``curl`` calls. Those work fine for a single override but they do NOT
record the original action of the rules being modified, so the
"restore to Execute (Block)" step in §8.5 is reduced to "remember what
the dashboard said before you changed it" — which is exactly the kind
of thing that goes wrong at 11pm on a Saturday. This script writes a
state file ``cf_waf_override_state.json`` (next to the script) on every
mutating call and uses it to drive the restore step.

Token requirements
------------------
The Cloudflare Ruleset API requires Account-level scope to PATCH zone-
phase rulesets — Zone:Read alone is not enough. Mint a token at
Cloudflare → My Profile → API Tokens with **all of**:

    Zone        | Zone     | Read
    Zone        | WAF      | Edit
    Account     | Rulesets | Edit
    Zone        | Analytics| Read    (already covered by the existing
                                      analytics token used by
                                      cf_ray_lookup.py — included so
                                      one token suffices for both
                                      lookup + override)

The token is read from the env var ``CF_WAF_OVERRIDE_TOKEN`` (with
``CLOUDFLARE_API_TOKEN`` honoured as a fallback for operators who have
already minted a single super-token). ``CF_ZONE_ID`` is reused from
the existing analytics setup.

Subcommands
-----------

    status      — print current managed-ruleset bindings and rate-limit
                  rule actions (read-only; safe to run any time).
    step0       — flip both managed-ruleset entrypoint bindings to
                  ``action: log`` so all WAF blocks stop within seconds
                  while the targeted fix is prepared. Saves the
                  pre-change action for step6.
    step3 RULE  — disable the named rule inside the OWASP Core
                  ruleset binding (default: 6179ae15870a4bb7b2d480d4843b323c
                  — OWASP 949110 Inbound Anomaly Score Exceeded).
    step4       — change the "Leaked credential check" rate-limit rule
                  from action ``block`` to ``managed_challenge``.
    step6       — restore the entrypoint bindings flipped in step0
                  back to their original action (typically
                  ``execute``). Step3's per-rule disable stays in
                  place — that is the whole point of the targeted fix.
    rollback3   — undo step3 (re-enable the disabled rule).
    rollback4   — undo step4 (revert rate-limit action).

All subcommands accept ``--dry-run`` to print the intended PATCH body
without sending it.

Usage example (full incident workflow)
--------------------------------------

    export CF_WAF_OVERRIDE_TOKEN=<scoped-token>

    # 1. Confirm we can talk to the API and see the current state
    python scripts/cf_waf_override.py status

    # 2. Stop all blocks immediately (1-2s round-trip; effective
    #    at the edge within ~30s)
    python scripts/cf_waf_override.py step0

    # 3. Apply the targeted fix
    python scripts/cf_waf_override.py step3

    # 4. Soften the leaked-credential rule
    python scripts/cf_waf_override.py step4

    # 5. Restore Execute (Block) on the entrypoint bindings
    python scripts/cf_waf_override.py step6

    # Verify
    python scripts/cf_waf_override.py status
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

API_BASE = "https://api.cloudflare.com/client/v4"
STATE_FILE = Path(__file__).resolve().parent / "cf_waf_override_state.json"

# Default rule to disable inside the OWASP Core Ruleset binding. Both
# Ray IDs reported in Task #825 (9f1537aba88aaa6a, 9f14bccc891a6ebf)
# fired this rule, and the 24h blast-radius query at task time showed
# it firing across every public path including /favicon.ico and /sw.js
# — i.e. it is the OWASP "aggregate score exceeded" trip-rule and is
# essentially blocking every IN/Airtel visitor whose CRS score crosses
# the paranoia-level threshold. Disabling just this one rule keeps the
# underlying CRS detections active (they continue to count score) but
# stops the threshold from translating to a 403.
DEFAULT_OWASP_TRIP_RULE = "6179ae15870a4bb7b2d480d4843b323c"

# Substring matches used to find the right rule binding inside an
# entrypoint ruleset's `rules` array. The Cloudflare API does not
# expose stable human names for the bindings, so we match on the
# `description` and the deployed ruleset's `action_parameters.id`.
OWASP_RULESET_NAME_HINTS = ("owasp",)  # description contains 'OWASP'
CF_MANAGED_RULESET_NAME_HINTS = ("cloudflare managed", "managed ruleset")
RATE_LIMIT_LEAKED_CRED_HINTS = ("leaked", "credential")


# ─── HTTP plumbing ──────────────────────────────────────────────────────────

def _resolve_token() -> str:
    for name in ("CF_WAF_OVERRIDE_TOKEN", "CLOUDFLARE_API_TOKEN"):
        v = os.environ.get(name)
        if v:
            return v.strip()
    raise SystemExit(
        "error: set CF_WAF_OVERRIDE_TOKEN (preferred) or CLOUDFLARE_API_TOKEN "
        "to a Cloudflare API token with Account Rulesets:Edit + Zone WAF:Edit"
    )


def _zone_id() -> str:
    z = os.environ.get("CF_ZONE_ID") or os.environ.get("CLOUDFLARE_ZONE_ID")
    if not z:
        raise SystemExit("error: CF_ZONE_ID is not set")
    return z.strip()


def _request(method: str, url: str, token: str, body: Optional[dict] = None,
             dry_run: bool = False) -> dict:
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    if dry_run:
        print(f"[dry-run] {method} {url}")
        if body is not None:
            print(json.dumps(body, indent=2))
        return {"dry_run": True}
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        text = exc.read()[:600].decode("utf-8", errors="replace")
        raise SystemExit(
            f"error: Cloudflare API HTTP {exc.code} on {method} {url}\n"
            f"body: {text}"
        ) from exc
    if isinstance(payload, dict) and not payload.get("success", True):
        raise SystemExit(
            f"error: Cloudflare API error on {method} {url}: "
            f"{payload.get('errors')}"
        )
    return payload


def _get(url: str, token: str) -> dict:
    return _request("GET", url, token)


def _patch(url: str, token: str, body: dict, dry_run: bool = False) -> dict:
    return _request("PATCH", url, token, body=body, dry_run=dry_run)


# ─── State file helpers ─────────────────────────────────────────────────────

def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    # State file may contain rule IDs but no secrets; keep it readable.


# ─── Ruleset discovery ──────────────────────────────────────────────────────

def _entrypoint(token: str, zone: str, phase: str) -> dict:
    """Return the deployed entrypoint ruleset for ``phase``.

    For free / pro plans, ``http_request_firewall_managed`` is the
    phase that holds the bindings to CF's Managed Ruleset and OWASP
    Core Ruleset; ``http_ratelimit`` is the phase that holds operator
    rate-limit rules.
    """
    url = f"{API_BASE}/zones/{zone}/rulesets/phases/{phase}/entrypoint"
    payload = _get(url, token)
    return payload.get("result") or {}


def _find_rule(rules: list, hints: tuple, also_action: Optional[str] = None) -> Optional[dict]:
    """Pick the first rule whose description (case-insensitive) contains
    *all* of ``hints``. If ``also_action`` is given, the rule's current
    action must match too — used to find e.g. the rate-limit rule
    currently set to ``block``.
    """
    needles = tuple(h.lower() for h in hints)
    for r in rules:
        desc = (r.get("description") or "").lower()
        if all(n in desc for n in needles):
            if also_action and r.get("action") != also_action:
                continue
            return r
    return None


# ─── Subcommands ────────────────────────────────────────────────────────────

def cmd_status(args) -> int:
    token = _resolve_token()
    zone = _zone_id()

    fw = _entrypoint(token, zone, "http_request_firewall_managed")
    rl = _entrypoint(token, zone, "http_ratelimit")

    print(f"=== zone {zone} ===")
    print(f"http_request_firewall_managed entrypoint: id={fw.get('id')!r}")
    for r in fw.get("rules") or []:
        ap = r.get("action_parameters") or {}
        print(
            f"  - rule_id={r.get('id')} action={r.get('action')!r} "
            f"deployed_ruleset={ap.get('id')!r} "
            f"description={r.get('description')!r} enabled={r.get('enabled')}"
        )
        # Also show any per-rule overrides already in place
        for ov in (ap.get("overrides") or {}).get("rules") or []:
            print(
                f"      override rule={ov.get('id')} "
                f"enabled={ov.get('enabled')} action={ov.get('action')}"
            )
    print()
    print(f"http_ratelimit entrypoint: id={rl.get('id')!r}")
    for r in rl.get("rules") or []:
        print(
            f"  - rule_id={r.get('id')} action={r.get('action')!r} "
            f"description={r.get('description')!r} enabled={r.get('enabled')}"
        )
    return 0


def cmd_step0(args) -> int:
    """Flip both managed-ruleset entrypoint bindings to action: log.

    Saves the pre-change action of every binding so step6 can restore.
    Idempotent: if a binding is already ``log``, it is left alone but
    the saved-state record is still written (using whatever value was
    saved on the *first* invocation, never overwritten by a later
    "log" reading).
    """
    token = _resolve_token()
    zone = _zone_id()

    fw = _entrypoint(token, zone, "http_request_firewall_managed")
    state = _load_state()
    saved = state.get("step0_pre_change") or {}

    targets = []
    for r in fw.get("rules") or []:
        desc = (r.get("description") or "").lower()
        is_owasp = any(h in desc for h in OWASP_RULESET_NAME_HINTS)
        is_cf_managed = any(h in desc for h in CF_MANAGED_RULESET_NAME_HINTS)
        if is_owasp or is_cf_managed:
            targets.append(r)

    if not targets:
        raise SystemExit(
            "error: no managed-ruleset bindings found in "
            "http_request_firewall_managed entrypoint — has the "
            "ruleset already been customized? Run `status` first."
        )

    for r in targets:
        rid = r["id"]
        current = r.get("action")
        # Only write the original action the FIRST time we touch it.
        if rid not in saved:
            saved[rid] = {
                "action": current,
                "description": r.get("description"),
            }
        if current == "log":
            print(f"step0: rule {rid} ({r.get('description')!r}) already action=log — skipped")
            continue
        url = f"{API_BASE}/zones/{zone}/rulesets/{fw['id']}/rules/{rid}"
        body = {"action": "log"}
        _patch(url, token, body, dry_run=args.dry_run)
        print(f"step0: rule {rid} ({r.get('description')!r}) set action=log")

    state["step0_pre_change"] = saved
    state["entrypoint_id"] = fw["id"]
    if not args.dry_run:
        _save_state(state)
    return 0


def cmd_step3(args) -> int:
    """Disable a single OWASP rule inside the OWASP ruleset binding.

    The override is added to ``action_parameters.overrides.rules`` —
    we PATCH the binding rule (NOT the underlying ruleset) so the
    change is scoped to syrabit.ai only and shows up in the dashboard
    as a normal "Override" row.
    """
    token = _resolve_token()
    zone = _zone_id()
    rule_to_disable = args.rule_id

    fw = _entrypoint(token, zone, "http_request_firewall_managed")
    binding = None
    for r in fw.get("rules") or []:
        desc = (r.get("description") or "").lower()
        if any(h in desc for h in OWASP_RULESET_NAME_HINTS):
            binding = r
            break
    if binding is None:
        raise SystemExit(
            "error: could not find OWASP Core Ruleset binding in "
            "http_request_firewall_managed entrypoint."
        )

    ap = binding.get("action_parameters") or {}
    overrides = (ap.get("overrides") or {})
    rules_overrides = list(overrides.get("rules") or [])

    # Idempotent merge: if an override for this rule_id already exists,
    # update it; otherwise append.
    found = False
    for ov in rules_overrides:
        if ov.get("id") == rule_to_disable:
            ov["enabled"] = False
            ov.pop("action", None)  # action is irrelevant when disabled
            found = True
            break
    if not found:
        rules_overrides.append({"id": rule_to_disable, "enabled": False})

    new_action_parameters = dict(ap)
    new_action_parameters["overrides"] = {
        **overrides,
        "rules": rules_overrides,
    }

    url = f"{API_BASE}/zones/{zone}/rulesets/{fw['id']}/rules/{binding['id']}"
    body = {
        "action": binding.get("action") or "execute",
        "action_parameters": new_action_parameters,
        "expression": binding.get("expression") or "true",
        "description": binding.get("description"),
        "enabled": binding.get("enabled", True),
    }
    _patch(url, token, body, dry_run=args.dry_run)
    print(
        f"step3: OWASP binding {binding['id']} now disables rule "
        f"{rule_to_disable} ({len(rules_overrides)} total override(s))"
    )

    state = _load_state()
    state.setdefault("step3", {})
    state["step3"][rule_to_disable] = {
        "binding_id": binding["id"],
        "entrypoint_id": fw["id"],
    }
    if not args.dry_run:
        _save_state(state)
    return 0


def cmd_step4(args) -> int:
    """Change Leaked-Credential rate-limit rule from block → managed_challenge."""
    token = _resolve_token()
    zone = _zone_id()

    rl = _entrypoint(token, zone, "http_ratelimit")
    rules = rl.get("rules") or []
    target = _find_rule(rules, RATE_LIMIT_LEAKED_CRED_HINTS)
    if target is None:
        raise SystemExit(
            "error: could not find a rate-limit rule whose description "
            "contains both 'leaked' and 'credential'. Run `status` to "
            "inspect the current rate-limit entrypoint."
        )

    current = target.get("action")
    if current == "managed_challenge":
        print(
            f"step4: rule {target['id']} already action=managed_challenge — skipped"
        )
        state = _load_state()
        state.setdefault("step4", {})
        state["step4"].setdefault(target["id"], {"action": current})
        if not args.dry_run:
            _save_state(state)
        return 0

    url = f"{API_BASE}/zones/{zone}/rulesets/{rl['id']}/rules/{target['id']}"
    body = {
        "action": "managed_challenge",
        "action_parameters": target.get("action_parameters") or {},
        "expression": target.get("expression"),
        "description": target.get("description"),
        "enabled": target.get("enabled", True),
        "ratelimit": target.get("ratelimit") or {},
    }
    _patch(url, token, body, dry_run=args.dry_run)
    print(
        f"step4: rate-limit rule {target['id']} ({target.get('description')!r}) "
        f"action {current!r} → 'managed_challenge'"
    )

    state = _load_state()
    state.setdefault("step4", {})
    if target["id"] not in state["step4"]:
        state["step4"][target["id"]] = {
            "action": current,
            "ratelimit_entrypoint_id": rl["id"],
            "description": target.get("description"),
        }
    if not args.dry_run:
        _save_state(state)
    return 0


def cmd_step6(args) -> int:
    """Restore the entrypoint bindings flipped in step0 to their original action."""
    token = _resolve_token()
    zone = _zone_id()

    state = _load_state()
    saved = state.get("step0_pre_change") or {}
    entrypoint_id = state.get("entrypoint_id")
    if not saved or not entrypoint_id:
        raise SystemExit(
            "error: no step0 state on file — refusing to guess what "
            "the original action was. If you know the right action, "
            "edit the bindings in the dashboard manually."
        )

    for rule_id, original in saved.items():
        url = f"{API_BASE}/zones/{zone}/rulesets/{entrypoint_id}/rules/{rule_id}"
        body = {"action": original.get("action") or "execute"}
        _patch(url, token, body, dry_run=args.dry_run)
        print(
            f"step6: rule {rule_id} ({original.get('description')!r}) "
            f"restored to action={body['action']!r}"
        )
    return 0


def cmd_rollback3(args) -> int:
    """Re-enable a rule previously disabled by step3."""
    token = _resolve_token()
    zone = _zone_id()
    rule_to_re_enable = args.rule_id

    fw = _entrypoint(token, zone, "http_request_firewall_managed")
    binding = None
    for r in fw.get("rules") or []:
        desc = (r.get("description") or "").lower()
        if any(h in desc for h in OWASP_RULESET_NAME_HINTS):
            binding = r
            break
    if binding is None:
        raise SystemExit("error: OWASP binding not found.")

    ap = binding.get("action_parameters") or {}
    overrides = ap.get("overrides") or {}
    rules_overrides = [
        ov for ov in (overrides.get("rules") or [])
        if ov.get("id") != rule_to_re_enable
    ]

    new_ap = dict(ap)
    new_ap["overrides"] = {**overrides, "rules": rules_overrides}

    url = f"{API_BASE}/zones/{zone}/rulesets/{fw['id']}/rules/{binding['id']}"
    body = {
        "action": binding.get("action") or "execute",
        "action_parameters": new_ap,
        "expression": binding.get("expression") or "true",
        "description": binding.get("description"),
        "enabled": binding.get("enabled", True),
    }
    _patch(url, token, body, dry_run=args.dry_run)
    print(f"rollback3: rule {rule_to_re_enable} override removed from OWASP binding")
    return 0


def cmd_rollback4(args) -> int:
    """Restore step4's rate-limit rule to its saved original action."""
    token = _resolve_token()
    zone = _zone_id()

    state = _load_state()
    saved = (state.get("step4") or {})
    if not saved:
        raise SystemExit("error: no step4 state on file.")

    rl = _entrypoint(token, zone, "http_ratelimit")
    by_id = {r["id"]: r for r in (rl.get("rules") or [])}

    for rule_id, original in saved.items():
        rule = by_id.get(rule_id)
        if not rule:
            print(f"rollback4: rule {rule_id} not found in current ruleset — skipped")
            continue
        url = f"{API_BASE}/zones/{zone}/rulesets/{rl['id']}/rules/{rule_id}"
        body = {
            "action": original.get("action") or "block",
            "action_parameters": rule.get("action_parameters") or {},
            "expression": rule.get("expression"),
            "description": rule.get("description"),
            "enabled": rule.get("enabled", True),
            "ratelimit": rule.get("ratelimit") or {},
        }
        _patch(url, token, body, dry_run=args.dry_run)
        print(
            f"rollback4: rule {rule_id} action restored to {body['action']!r}"
        )
    return 0


# ─── CLI wiring ─────────────────────────────────────────────────────────────

def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="print the intended PATCH body without sending it",
    )

    sub.add_parser("status", help="print current zone ruleset state")

    sub.add_parser("step0", parents=[common],
                   help="flip both managed-ruleset bindings to action=log")

    p3 = sub.add_parser("step3", parents=[common],
                        help="disable a rule inside the OWASP binding")
    p3.add_argument("--rule-id", default=DEFAULT_OWASP_TRIP_RULE,
                    help=f"OWASP rule id to disable (default {DEFAULT_OWASP_TRIP_RULE})")

    sub.add_parser("step4", parents=[common],
                   help="leaked-credential rate-limit rule: block → managed_challenge")

    sub.add_parser("step6", parents=[common],
                   help="restore entrypoint bindings flipped by step0")

    pr3 = sub.add_parser("rollback3", parents=[common], help="undo step3")
    pr3.add_argument("--rule-id", default=DEFAULT_OWASP_TRIP_RULE)

    sub.add_parser("rollback4", parents=[common], help="undo step4")

    args = p.parse_args(argv)
    return {
        "status":     cmd_status,
        "step0":      cmd_step0,
        "step3":      cmd_step3,
        "step4":      cmd_step4,
        "step6":      cmd_step6,
        "rollback3":  cmd_rollback3,
        "rollback4":  cmd_rollback4,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())

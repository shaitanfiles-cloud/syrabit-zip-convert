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

State-file lifecycle (read this before re-using across incidents)
-----------------------------------------------------------------
``cf_waf_override_state.json`` is a **per-incident operational
artifact, not a durable repo file**. It is gitignored on purpose. The
correct lifecycle is:

  1. Operator runs ``step0`` → snapshot of the pre-incident binding
     state is written to the file.
  2. Operator runs ``step3`` / ``step4`` → entries are appended.
  3. Operator runs ``step6`` (after the verification gate in §8.7.3
     of the runbook) → the file's ``step0_pre_change`` snapshot is
     consumed to restore.
  4. Once the incident is fully closed (status confirms the
     steady-state config), **delete the file**:
     ``rm artifacts/syrabit-backend/scripts/cf_waf_override_state.json``

If the file from a prior incident is left on disk and you start a new
incident, ``step0`` will detect that no binding is currently in
force-log mode and refresh the snapshot automatically (see the
"State-freshness check" in ``cmd_step0``). That guard exists exactly
because forgetting to clean up step 4 is a realistic operator
failure. The guard is belt-and-braces; the discipline is still to
delete the file.

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

# Stable Cloudflare-shipped deployed-ruleset IDs. These IDs are
# tenant-stable across all CF zones (they identify the ruleset that
# Cloudflare publishes, not the per-zone binding to it). Preferring
# these over the brittle description substring match makes the
# orchestrator robust to Cloudflare renaming the ruleset in the
# dashboard — which they have done historically. Verified for the
# syrabit.ai zone via `status` on 2026-04-24 and recorded in
# docs/CLOUDFLARE_ZERO_TRUST.md §8.7.2.
CF_OWASP_DEPLOYED_RULESET_ID = "4814384a9e5d4991b9815dcfc25d2f1f"
CF_MANAGED_DEPLOYED_RULESET_ID = "efb7b8c949ac4650a09736fc376e9aee"


def _binding_is_owasp(rule: dict) -> bool:
    """Identify the OWASP Core Ruleset binding by stable id, with
    description-substring fallback for forward-compat."""
    deployed = (rule.get("action_parameters") or {}).get("id")
    if deployed == CF_OWASP_DEPLOYED_RULESET_ID:
        return True
    desc = (rule.get("description") or "").lower()
    return any(h in desc for h in OWASP_RULESET_NAME_HINTS)


def _binding_is_cf_managed(rule: dict) -> bool:
    """Identify the Cloudflare Managed Ruleset binding by stable id,
    with description-substring fallback for forward-compat."""
    deployed = (rule.get("action_parameters") or {}).get("id")
    if deployed == CF_MANAGED_DEPLOYED_RULESET_ID:
        return True
    desc = (rule.get("description") or "").lower()
    return any(h in desc for h in CF_MANAGED_RULESET_NAME_HINTS)


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
    """Read the orchestrator state file, failing loudly on corruption.

    Silently swallowing a JSON parse error is dangerous: rollback
    paths use this state to know what to restore, so a corrupt file
    that returns ``{}`` would make the script "succeed" while
    actually losing the pre-change snapshot. Better to abort and let
    the operator decide whether to delete the file.
    """
    if not STATE_FILE.exists():
        return {}
    raw = STATE_FILE.read_text()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"error: state file {STATE_FILE} is corrupt ({exc}). "
            f"Inspect it, copy out anything you need, then delete it "
            f"and re-run from `status`. Refusing to continue with an "
            f"empty state because that would mask rollback data."
        )


def _save_state(state: dict) -> None:
    """Atomically persist state via temp-file + rename.

    Without this, a Ctrl-C / OOM / disk-full midway through
    ``write_text`` would leave a half-written file that
    ``_load_state`` then refuses to read — losing the rollback
    snapshot for the in-flight incident.
    """
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(payload)
    os.replace(tmp, STATE_FILE)
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
    """Force-log both managed-ruleset entrypoint bindings.

    The Cloudflare Ruleset API does NOT allow a managed-firewall
    binding's primary ``action`` to be set to anything other than
    ``execute`` — that's what tells CF to actually run the deployed
    ruleset. To turn the whole binding into "log mode" you instead
    set ``action_parameters.overrides.action = "log"``, which CF
    applies as a global "rewrite every rule's action to log" on top
    of the deployed ruleset. We preserve any existing per-rule
    overrides (e.g. step3 may have already disabled rule 949110).

    Idempotent: if a binding already has ``overrides.action == "log"``
    the binding is left alone but its pre-step0 override.action value
    is still recorded in the state file (only on the FIRST
    invocation, never overwritten).
    """
    token = _resolve_token()
    zone = _zone_id()

    fw = _entrypoint(token, zone, "http_request_firewall_managed")
    state = _load_state()
    saved = state.get("step0_pre_change") or {}

    targets = []
    for r in fw.get("rules") or []:
        if _binding_is_owasp(r) or _binding_is_cf_managed(r):
            targets.append(r)

    if not targets:
        raise SystemExit(
            "error: no managed-ruleset bindings found in "
            "http_request_firewall_managed entrypoint — has the "
            "ruleset already been customized? Run `status` first."
        )

    # ── State-freshness check (architect feedback, Task #825) ──
    # If the saved snapshot is from a previous incident that has
    # already been resolved (i.e. NO target binding currently has
    # overrides.action="log"), then carrying that snapshot forward
    # would teach step6 to restore values that may no longer be the
    # "natural" pre-incident state of this NEW incident. Detect
    # that case and re-snapshot so step6 always restores to the
    # state that existed at the start of the *current* incident.
    any_currently_log = any(
        ((t.get("action_parameters") or {}).get("overrides") or {}).get("action") == "log"
        for t in targets
    )
    if saved and not any_currently_log:
        print(
            "step0: detected stale step0 snapshot from a previous "
            "incident (no binding is currently in force-log mode). "
            "Refreshing snapshot from live state so step6 restores "
            "to the correct pre-incident values."
        )
        saved = {}
        # Drop the stale step3 marker too — it's specific to whichever
        # rule the previous incident disabled, and we don't want
        # step6's precondition gate to fail just because we kept a
        # stale rule id around.
        state["step3"] = {}

    for r in targets:
        rid = r["id"]
        ap = r.get("action_parameters") or {}
        overrides = dict(ap.get("overrides") or {})
        prior_override_action = overrides.get("action")  # may be None
        # Only write the original override.action the FIRST time we
        # touch this binding — so re-running step0 doesn't lose the
        # pre-step0 value behind another "log".
        if rid not in saved:
            saved[rid] = {
                "override_action": prior_override_action,
                "binding_action": r.get("action"),
                "description": r.get("description"),
            }
        if prior_override_action == "log":
            print(
                f"step0: rule {rid} ({r.get('description')!r}) "
                f"already overrides.action='log' — skipped"
            )
            continue

        new_overrides = dict(overrides)
        new_overrides["action"] = "log"
        new_ap = dict(ap)
        new_ap["overrides"] = new_overrides

        url = f"{API_BASE}/zones/{zone}/rulesets/{fw['id']}/rules/{rid}"
        body = {
            "action": r.get("action") or "execute",
            "action_parameters": new_ap,
            "expression": r.get("expression") or "true",
            "description": r.get("description"),
            "enabled": r.get("enabled", True),
        }
        _patch(url, token, body, dry_run=args.dry_run)
        print(
            f"step0: rule {rid} ({r.get('description')!r}) "
            f"overrides.action set to 'log'"
        )

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
        if _binding_is_owasp(r):
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
    """Undo step0's force-log on the managed-firewall bindings.

    Reads each binding LIVE (rather than from a stale snapshot in the
    state file) so that any per-rule overrides added between step0
    and step6 — most importantly step3's disable of OWASP 949110 —
    are preserved. Only ``action_parameters.overrides.action`` is
    rewritten back to its pre-step0 value (``None`` in the common
    case → key removed → ruleset reverts to executing every rule's
    own action, which is what blocks attacks).
    """
    token = _resolve_token()
    zone = _zone_id()

    state = _load_state()
    saved = state.get("step0_pre_change") or {}
    if not saved:
        raise SystemExit(
            "error: no step0 state on file — refusing to guess what "
            "the original override.action was. If you know the right "
            "value, edit the bindings in the dashboard manually."
        )

    fw = _entrypoint(token, zone, "http_request_firewall_managed")
    by_id = {r["id"]: r for r in (fw.get("rules") or [])}

    # ── Precondition gate (architect feedback, Task #825) ──
    # Lifting force-log restores `execute` semantics, which means the
    # OWASP ruleset will start blocking again the moment we PATCH. If
    # step3 silently failed — wrong binding, manual revert in the
    # dashboard, an operator running `rollback3` and forgetting —
    # then step6 would re-block the very users we just unblocked.
    # Refuse unless the trip rule is still disabled in the OWASP
    # binding, or --force is passed.
    expect_rule = getattr(args, "expect_disabled_rule", None) or DEFAULT_OWASP_TRIP_RULE
    if not getattr(args, "force", False):
        owasp_binding = next(
            (r for r in (fw.get("rules") or []) if _binding_is_owasp(r)),
            None,
        )
        per_rule_overrides = []
        if owasp_binding:
            per_rule_overrides = (
                ((owasp_binding.get("action_parameters") or {}).get("overrides") or {}).get("rules")
                or []
            )
        disabled = any(
            (o.get("id") == expect_rule and o.get("enabled") is False)
            for o in per_rule_overrides
        )
        if not disabled:
            raise SystemExit(
                f"error: refusing to lift force-log because OWASP rule "
                f"{expect_rule} is NOT currently disabled in the OWASP "
                f"binding. Lifting force-log now would re-block users "
                f"the moment the PATCH lands. Either:\n"
                f"  • re-run `step3 --rule-id {expect_rule}` and verify "
                f"with `status`, then re-run step6, or\n"
                f"  • if you have hand-applied an equivalent fix in the "
                f"dashboard, re-run step6 with --force."
            )

    for rule_id, original in saved.items():
        binding = by_id.get(rule_id)
        if binding is None:
            print(
                f"step6: rule {rule_id} ({original.get('description')!r}) "
                f"not found in current entrypoint — skipped (was it "
                f"removed in the dashboard?)"
            )
            continue
        ap = dict(binding.get("action_parameters") or {})
        overrides = dict(ap.get("overrides") or {})
        prior_override_action = original.get("override_action")
        if prior_override_action is None:
            overrides.pop("action", None)
        else:
            overrides["action"] = prior_override_action
        # If the overrides dict has nothing left, omit it so we don't
        # leave an empty {} that the API might reject.
        if not overrides:
            ap.pop("overrides", None)
        else:
            ap["overrides"] = overrides

        url = f"{API_BASE}/zones/{zone}/rulesets/{fw['id']}/rules/{rule_id}"
        body = {
            "action": original.get("binding_action") or binding.get("action") or "execute",
            "action_parameters": ap,
            "expression": binding.get("expression") or "true",
            "description": binding.get("description") or original.get("description"),
            "enabled": binding.get("enabled", True),
        }
        _patch(url, token, body, dry_run=args.dry_run)
        print(
            f"step6: rule {rule_id} ({binding.get('description')!r}) "
            f"overrides.action restored to {prior_override_action!r}"
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
        if _binding_is_owasp(r):
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

    p6 = sub.add_parser("step6", parents=[common],
                        help="restore entrypoint bindings flipped by step0")
    p6.add_argument("--force", action="store_true",
                    help="skip the precondition that step3's per-rule "
                         "disable is still in place. Only use this if "
                         "you have manually re-verified the OWASP "
                         "binding in the dashboard.")
    p6.add_argument("--expect-disabled-rule", default=DEFAULT_OWASP_TRIP_RULE,
                    help="OWASP rule id that must currently be "
                         "disabled before step6 will lift force-log. "
                         "Defaults to the Task #825 trip rule.")

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

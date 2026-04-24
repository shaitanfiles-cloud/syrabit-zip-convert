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
    bot_skip    — add (idempotent) a Skip Rules custom-phase rule that
                  exempts ``/api/*`` and ``/sitemap.xml`` from the CF
                  Managed Ruleset's bot-management rule
                  ``874a3e315c344b1281ad4f00046aab6f`` ("manage
                  definite bots"). Task #826 — the bot rule was
                  managed-challenging legitimate API and sitemap
                  traffic (see runbook §8.6 row for #826).
    aggregate   — query firewallEventsAdaptiveGroups over a window
                  for a given ``--rule-id`` and print a count
                  breakdown by path / action / source. Used as the
                  24h post-fix verification gate (Task #826 done-
                  criterion: rule no longer fires on affected paths).
    rollback3   — undo step3 (re-enable the disabled rule).
    rollback4   — undo step4 (revert rate-limit action).
    rollback_bot_skip
                — undo bot_skip (delete the Skip Rules custom-phase
                  rule by description tag).

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

# ─── Task #826 — bot-management rule exemption ──────────────────────────────
# The "manage definite bots" rule inside the Cloudflare Managed Ruleset
# binding was observed managed_challenge-ing legitimate `/api/*` and
# `/sitemap.xml` traffic during the Task #825 24h aggregation. The fix
# is a path-scoped Skip Rules custom-phase rule (rather than a global
# disable) so the bot rule keeps protecting the rest of the zone.
#
# The Skip Rules ``action_parameters.rules`` map is keyed by the
# *deployed* ruleset id (the Cloudflare-shipped ruleset that contains
# the rule), NOT by the per-zone binding id. That is intentional in the
# CF API: a Skip rule says "when you encounter ruleset X, skip rule Y
# inside it" — independent of how X is deployed in the current zone.
BOT_DEFINITE_RULE_ID = "874a3e315c344b1281ad4f00046aab6f"

# Path-scoped exemption for the bot rule. Matches the Task #826 done-
# criterion verbatim ("/api/* and /sitemap.xml"). If you need to widen
# the exemption (e.g. add /sitemap-index.xml), edit this constant and
# re-run `bot_skip` — the command is idempotent on the description tag
# below, so it will PATCH the existing rule rather than duplicate it.
BOT_SKIP_EXPRESSION = (
    '(starts_with(http.request.uri.path, "/api/") '
    'or http.request.uri.path eq "/sitemap.xml")'
)

# Stable description tag used by `bot_skip` and `rollback_bot_skip` to
# find the rule on subsequent runs. The tag MUST stay in the
# description even if the human-readable prose around it changes —
# `rollback_bot_skip` is a substring lookup against this exact string.
BOT_SKIP_DESCRIPTION_TAG = "Task #826"
BOT_SKIP_DESCRIPTION = (
    f"{BOT_SKIP_DESCRIPTION_TAG}: skip CF managed bot rule "
    f"{BOT_DEFINITE_RULE_ID} for /api/* and /sitemap.xml "
    f"(legitimate-traffic false-positive exemption)"
)

# GraphQL endpoint reused by the `aggregate` subcommand. Same dataset
# the read-only `cf_ray_lookup.py` script uses; we just query the
# *Groups* variant for count-by-dimension aggregation.
GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"


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
             dry_run: bool = False, allow_404: bool = False) -> Optional[dict]:
    """Call the Cloudflare API. Returns the parsed JSON payload, or
    ``None`` when ``allow_404=True`` and the server returns 404 (the
    only place we currently use that is the optional GET of the
    custom-firewall entrypoint, which may not exist on a fresh zone).
    """
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
            raw = resp.read()
            payload = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
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


def _entrypoint_optional(token: str, zone: str, phase: str) -> Optional[dict]:
    """Like ``_entrypoint`` but returns ``None`` when the phase has no
    entrypoint ruleset yet.

    The ``http_request_firewall_custom`` phase often does not exist
    on a fresh zone — Cloudflare lazily creates it the first time you
    add a custom rule via the dashboard. The orchestrator therefore
    has to handle the "no entrypoint yet" case by creating one before
    POSTing the first Skip rule. (See ``cmd_bot_skip``.)
    """
    url = f"{API_BASE}/zones/{zone}/rulesets/phases/{phase}/entrypoint"
    payload = _request("GET", url, token, allow_404=True)
    if payload is None:
        return None
    return payload.get("result") or {}


def _create_phase_entrypoint(token: str, zone: str, phase: str,
                             dry_run: bool = False) -> dict:
    """Create an empty entrypoint ruleset for ``phase``.

    Used by ``cmd_bot_skip`` only when the custom-firewall phase has
    no entrypoint yet. Body shape is the documented Cloudflare
    minimum: ``kind=zone``, the phase name, an empty ``rules`` array,
    and a human-readable name. A subsequent POST adds the actual
    Skip rule — we do NOT inline the rule here so the create + add
    paths stay separable (idempotency is then driven by the
    description-tag lookup on the rule, not on the entrypoint).
    """
    url = f"{API_BASE}/zones/{zone}/rulesets"
    body = {
        "name": "default",
        "description": (
            "Custom-firewall entrypoint auto-created by "
            "scripts/cf_waf_override.py for Task #826 (path-scoped "
            "bot-rule exemption). See docs/CLOUDFLARE_ZERO_TRUST.md "
            "§8.7.5."
        ),
        "kind": "zone",
        "phase": phase,
        "rules": [],
    }
    payload = _request("POST", url, token, body=body, dry_run=dry_run)
    return (payload or {}).get("result") or {}


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
    # Custom-firewall phase is created on-demand by `bot_skip` (Task
    # #826), so it may not exist on every zone. Fetch with the
    # 404-tolerant helper and skip the section entirely if absent.
    cf = _entrypoint_optional(token, zone, "http_request_firewall_custom")

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
    print()
    if cf is None:
        print(
            "http_request_firewall_custom entrypoint: (none — no custom "
            "rules deployed; the `bot_skip` subcommand will create one "
            "on first run)"
        )
    else:
        print(f"http_request_firewall_custom entrypoint: id={cf.get('id')!r}")
        for r in cf.get("rules") or []:
            ap = r.get("action_parameters") or {}
            skipped = (ap.get("rules") or {}) if r.get("action") == "skip" else {}
            print(
                f"  - rule_id={r.get('id')} action={r.get('action')!r} "
                f"description={r.get('description')!r} "
                f"enabled={r.get('enabled')}"
            )
            if skipped:
                # Show which managed rules each skip rule disables
                # (keys are deployed-ruleset ids; values are rule-id
                # lists). This is what makes the custom phase
                # consistent with the runbook §8.7.5 description.
                for ds_id, rule_ids in skipped.items():
                    print(
                        f"      skips deployed_ruleset={ds_id!r} rules={rule_ids}"
                    )
                expr = r.get("expression")
                if expr:
                    print(f"      expression={expr}")
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


def cmd_verify(args) -> int:
    """Assert post-incident steady-state invariants and exit non-zero on drift.

    This is the smoke-test the runbook §8.7.3 verification gate
    points at: after running step0 → step3 → step4 → step6 the live
    Cloudflare config should match the four invariants below. Wire
    this into a cron / CI job to catch silent drift (a teammate
    re-enables 949110 in the dashboard, an external script overwrites
    the rate-limit rule, etc.) without waiting for the next user
    report.

    Invariants (all five must hold, else exit 1):
      1. The Cloudflare Managed Ruleset binding is `action=execute`
         AND `overrides.action` is unset (no force-log left over).
      2. The OWASP Core Ruleset binding is `action=execute` AND
         `overrides.action` is unset AND it has a per-rule override
         for ``--expect-disabled-rule`` (default = the trip rule)
         with ``enabled=False``.
      3. The leaked-credential rate-limit rule's action is
         ``managed_challenge`` (not ``block``).
      4. None of the bindings above are themselves ``enabled=false``
         (a disabled binding does NOT execute the deployed ruleset
         at all, which would silently drop ALL WAF protection).
      5. (Task #826) The custom-firewall phase carries a Skip rule
         tagged ``BOT_SKIP_DESCRIPTION_TAG`` that lists the bot rule
         in ``--expect-skip-bot-rule`` (default
         ``874a3e315c344b1281ad4f00046aab6f``) under the CF Managed
         deployed ruleset id, with ``enabled=true``. Pass
         ``--no-check-bot-skip`` to relax this invariant only when
         intentionally rolling back to the pre-#826 baseline.
    """
    token = _resolve_token()
    zone = _zone_id()
    expect_rule = getattr(args, "expect_disabled_rule", None) or DEFAULT_OWASP_TRIP_RULE
    expect_bot_rule = getattr(args, "expect_skip_bot_rule", None) or BOT_DEFINITE_RULE_ID
    check_bot_skip = not getattr(args, "no_check_bot_skip", False)

    fw = _entrypoint(token, zone, "http_request_firewall_managed")
    rl = _entrypoint(token, zone, "http_ratelimit")
    custom = _entrypoint_optional(token, zone, "http_request_firewall_custom") if check_bot_skip else None

    cf_managed = next((r for r in (fw.get("rules") or []) if _binding_is_cf_managed(r)), None)
    owasp = next((r for r in (fw.get("rules") or []) if _binding_is_owasp(r)), None)
    leaked = _find_rule(rl.get("rules") or [], RATE_LIMIT_LEAKED_CRED_HINTS)

    failures = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        marker = "PASS" if cond else "FAIL"
        line = f"  [{marker}] {label}"
        if detail and not cond:
            line += f" — {detail}"
        print(line)
        if not cond:
            failures.append(label)

    print("=== Steady-state invariant verification ===")

    # Invariant 1: CF Managed binding
    if cf_managed is None:
        check("CF Managed Ruleset binding present", False,
              "binding not found at all")
    else:
        ap = cf_managed.get("action_parameters") or {}
        ovr = (ap.get("overrides") or {}).get("action")
        check(
            "CF Managed Ruleset binding action=execute, no force-log",
            cf_managed.get("action") == "execute"
                and ovr is None
                and cf_managed.get("enabled", True),
            f"action={cf_managed.get('action')!r} "
            f"overrides.action={ovr!r} enabled={cf_managed.get('enabled')!r}",
        )

    # Invariant 2: OWASP binding + trip-rule disable override
    if owasp is None:
        check("OWASP Core Ruleset binding present", False,
              "binding not found at all")
    else:
        ap = owasp.get("action_parameters") or {}
        overrides = ap.get("overrides") or {}
        ovr_action = overrides.get("action")
        check(
            "OWASP binding action=execute, no force-log",
            owasp.get("action") == "execute"
                and ovr_action is None
                and owasp.get("enabled", True),
            f"action={owasp.get('action')!r} "
            f"overrides.action={ovr_action!r} enabled={owasp.get('enabled')!r}",
        )
        per_rule = overrides.get("rules") or []
        trip_disabled = any(
            o.get("id") == expect_rule and o.get("enabled") is False
            for o in per_rule
        )
        check(
            f"OWASP binding has trip-rule {expect_rule} disabled",
            trip_disabled,
            f"per-rule overrides currently: "
            f"{[(o.get('id'), o.get('enabled')) for o in per_rule]}",
        )

    # Invariant 3: leaked-credential rate-limit rule
    if leaked is None:
        check("Leaked-credential rate-limit rule present", False,
              "rule not found in http_ratelimit phase")
    else:
        check(
            "Leaked-credential rate-limit rule action=managed_challenge",
            leaked.get("action") == "managed_challenge"
                and leaked.get("enabled", True),
            f"action={leaked.get('action')!r} enabled={leaked.get('enabled')!r}",
        )

    # Invariant 5 (Task #826): bot-management Skip rule for safe paths.
    # We DO NOT short-circuit when --no-check-bot-skip is set — instead
    # we record an explicit "skipped" line so the verify output still
    # shows what was (and wasn't) checked, which matters when the
    # output is pasted into incident tickets.
    if not check_bot_skip:
        print("  [SKIP] Bot-management Skip rule check disabled via --no-check-bot-skip")
    elif custom is None:
        check(
            f"Bot-management Skip rule for {expect_bot_rule} present (custom phase)",
            False,
            "no http_request_firewall_custom entrypoint exists at all — "
            "run `bot_skip` to create it",
        )
    else:
        skip = _find_bot_skip_rule(custom)
        if skip is None:
            check(
                f"Bot-management Skip rule for {expect_bot_rule} present",
                False,
                f"no rule with description containing "
                f"{BOT_SKIP_DESCRIPTION_TAG!r} found in custom phase",
            )
        else:
            ap = skip.get("action_parameters") or {}
            rules_map = ap.get("rules") or {}
            listed = rules_map.get(CF_MANAGED_DEPLOYED_RULESET_ID) or []
            expr = skip.get("expression") or ""
            # Drift guard (architect feedback, Task #826 review):
            # also assert the expression itself matches the canonical
            # BOT_SKIP_EXPRESSION so an over-broad expression (e.g.
            # someone widened it in the dashboard to
            # `not http.request.uri.path eq "/"`) is detected here
            # instead of silently passing.
            check(
                f"Skip rule disables bot rule {expect_bot_rule} on safe paths",
                skip.get("action") == "skip"
                    and skip.get("enabled", True)
                    and expect_bot_rule in listed
                    and expr == BOT_SKIP_EXPRESSION,
                f"action={skip.get('action')!r} "
                f"enabled={skip.get('enabled')!r} "
                f"deployed_ruleset_id_listed={list(rules_map.keys())} "
                f"rules_under_cf_managed={listed} "
                f"expression_matches_canonical={expr == BOT_SKIP_EXPRESSION} "
                f"(actual={expr!r})",
            )

    if failures:
        print(f"\nverify: {len(failures)} invariant(s) failed.")
        return 1
    print("\nverify: all invariants hold.")
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


# ─── Task #826 — bot-management Skip rule ───────────────────────────────────

def _find_bot_skip_rule(custom_entrypoint: dict) -> Optional[dict]:
    """Locate a previously-applied bot-skip rule by description tag.

    Idempotency is anchored on ``BOT_SKIP_DESCRIPTION_TAG`` (a
    substring match). The Cloudflare API gives custom rules a UUID
    on creation that we can't predict, so we cannot key off id —
    description-tag matching is the only stable handle.
    """
    tag = BOT_SKIP_DESCRIPTION_TAG
    for r in custom_entrypoint.get("rules") or []:
        if tag in (r.get("description") or ""):
            return r
    return None


def cmd_bot_skip(args) -> int:
    """Add (idempotent) a Skip Rules custom-phase rule that exempts
    ``/api/*`` and ``/sitemap.xml`` from the CF Managed Ruleset's
    bot-management rule ``874a3e315c344b1281ad4f00046aab6f``.

    Why a Skip rule and not a per-rule disable on the binding
    (step3-style)? The per-rule disable is *global* — it would turn
    bot management off for the entire zone. The bot rule is mostly
    correct — it only false-positives on the SEO/API surface where
    legitimate clients (search engines, our own internal scripts,
    the Razorpay webhook IPs) get score-flagged. A Skip rule keeps
    the bot rule active everywhere except the two surfaces named in
    the Task #826 done-criterion.

    The Cloudflare Skip rule body shape is:

        action: "skip"
        action_parameters:
          rules:
            <DEPLOYED_RULESET_ID>: ["<rule_id>"]
        expression: "<filter that selects the requests to exempt>"

    where ``DEPLOYED_RULESET_ID`` is the *Cloudflare-published*
    ruleset id (``CF_MANAGED_DEPLOYED_RULESET_ID``), NOT the per-zone
    binding id. CF's Skip semantics are "when ruleset X is about to
    fire, skip rule Y inside it" — which is exactly what we want.

    State-file note: this writes ``state["bot_skip"][rule_id] = {
    custom_entrypoint_id, custom_rule_id, expression }`` so
    ``rollback_bot_skip`` can be run on a different operator's
    machine using the orchestrator's standard discovery (description-
    tag lookup) without depending on the local state file.
    """
    token = _resolve_token()
    zone = _zone_id()
    rule_to_skip = args.rule_id

    custom = _entrypoint_optional(token, zone, "http_request_firewall_custom")
    if custom is None:
        if args.dry_run:
            print(
                "[dry-run] http_request_firewall_custom entrypoint does "
                "not exist yet — would POST a new one before adding the "
                "skip rule"
            )
            entrypoint_id = "<would-be-created>"
            existing_rules: list = []
        else:
            print(
                "bot_skip: http_request_firewall_custom entrypoint not "
                "found — creating an empty one"
            )
            created = _create_phase_entrypoint(
                token, zone, "http_request_firewall_custom", dry_run=False
            )
            entrypoint_id = created.get("id") or ""
            existing_rules = created.get("rules") or []
            if not entrypoint_id:
                raise SystemExit(
                    "error: created custom-firewall entrypoint but the "
                    "API response had no id; refusing to continue"
                )
            print(f"bot_skip: created custom-firewall entrypoint {entrypoint_id}")
    else:
        entrypoint_id = custom["id"]
        existing_rules = custom.get("rules") or []

    existing = _find_bot_skip_rule({"rules": existing_rules})

    body = {
        "action": "skip",
        "action_parameters": {
            "rules": {
                CF_MANAGED_DEPLOYED_RULESET_ID: [rule_to_skip],
            },
        },
        "expression": BOT_SKIP_EXPRESSION,
        "description": BOT_SKIP_DESCRIPTION,
        "enabled": True,
    }

    if existing:
        rid = existing["id"]
        url = f"{API_BASE}/zones/{zone}/rulesets/{entrypoint_id}/rules/{rid}"
        _patch(url, token, body, dry_run=args.dry_run)
        print(
            f"bot_skip: updated existing skip rule {rid} "
            f"(managed-rule {rule_to_skip}, expression unchanged)"
        )
        custom_rule_id = rid
    else:
        url = f"{API_BASE}/zones/{zone}/rulesets/{entrypoint_id}/rules"
        result = _request("POST", url, token, body=body, dry_run=args.dry_run)
        custom_rule_id = None
        if not args.dry_run:
            res = (result or {}).get("result") or {}
            for r in res.get("rules") or []:
                if BOT_SKIP_DESCRIPTION_TAG in (r.get("description") or ""):
                    custom_rule_id = r["id"]
                    break
        print(
            f"bot_skip: added new skip rule {custom_rule_id} "
            f"(managed-rule {rule_to_skip}) on custom-firewall "
            f"entrypoint {entrypoint_id}"
        )

    state = _load_state()
    state.setdefault("bot_skip", {})
    state["bot_skip"][rule_to_skip] = {
        "custom_entrypoint_id": entrypoint_id,
        "custom_rule_id": custom_rule_id,
        "expression": BOT_SKIP_EXPRESSION,
        "deployed_ruleset_id": CF_MANAGED_DEPLOYED_RULESET_ID,
    }
    if not args.dry_run:
        _save_state(state)
    return 0


def cmd_rollback_bot_skip(args) -> int:
    """Remove the bot-skip Skip Rules entry added by ``bot_skip``.

    Locates the rule by ``BOT_SKIP_DESCRIPTION_TAG`` substring in the
    rule's description, NOT by the state file — so this works even
    if a different operator runs the rollback on a fresh checkout.
    """
    token = _resolve_token()
    zone = _zone_id()

    custom = _entrypoint_optional(token, zone, "http_request_firewall_custom")
    if custom is None:
        print(
            "rollback_bot_skip: no http_request_firewall_custom "
            "entrypoint exists — nothing to do"
        )
        return 0

    entrypoint_id = custom["id"]
    existing = _find_bot_skip_rule(custom)
    if existing is None:
        print(
            f"rollback_bot_skip: no rule with description containing "
            f"{BOT_SKIP_DESCRIPTION_TAG!r} found — already gone"
        )
        return 0

    rid = existing["id"]
    url = f"{API_BASE}/zones/{zone}/rulesets/{entrypoint_id}/rules/{rid}"
    _request("DELETE", url, token, dry_run=args.dry_run)
    print(
        f"rollback_bot_skip: deleted skip rule {rid} "
        f"({existing.get('description')!r})"
    )

    if not args.dry_run:
        state = _load_state()
        bs = state.get("bot_skip") or {}
        # Drop any entries that pointed to this rule id.
        for k, v in list(bs.items()):
            if (v or {}).get("custom_rule_id") == rid:
                bs.pop(k, None)
        if bs:
            state["bot_skip"] = bs
        else:
            state.pop("bot_skip", None)
        _save_state(state)
    return 0


# ─── Task #826 — post-fix WAF event aggregation ─────────────────────────────

_AGGREGATE_QUERY = """
query Aggregate(
  $zoneTag: String!,
  $since: Time!,
  $until: Time!,
  $rule: String!,
  $limit: Int!
) {
  viewer {
    zones(filter: {zoneTag: $zoneTag}) {
      firewallEventsAdaptiveGroups(
        limit: $limit,
        filter: {datetime_geq: $since, datetime_leq: $until, ruleId: $rule},
        orderBy: [count_DESC]
      ) {
        count
        dimensions {
          action
          source
          ruleId
          clientRequestPath
          clientRequestHTTPHost
        }
      }
    }
  }
}
"""

# CF firewallEventsAdaptiveGroups caps `limit` at 10000. We default
# to 5000 so even very high-cardinality (path, action, host) result
# sets fit in a single page without truncating low-volume exempt-
# path challenge events (which are exactly the events we MUST see
# to fail the gate). If a future incident spans more than 5000
# distinct (path,action,host,source) combinations, override with
# `--graphql-limit 10000`. The aggregator detects boundary hits
# (count == limit) and prints a warning so operators know to widen.
_AGGREGATE_DEFAULT_LIMIT = 5000
_AGGREGATE_MAX_LIMIT = 10000


def _path_is_exempt(path: str, prefixes, exact) -> bool:
    """True if ``path`` matches any of the bot-skip exemption clauses.

    Mirrors ``BOT_SKIP_EXPRESSION`` in pure Python so the aggregator
    can bucket GraphQL results into "should be challenged" vs
    "should be exempt". ``prefixes`` and ``exact`` are iterables of
    strings sourced from CLI flags so callers can verify other
    exemptions later without re-coding the matcher.
    """
    if not isinstance(path, str):
        return False
    if path in exact:
        return True
    for p in prefixes:
        if p and path.startswith(p):
            return True
    return False


def cmd_aggregate(args) -> int:
    """Aggregate firewall events for ``--rule-id`` over a window.

    Used as the 24h post-fix verification gate documented in
    runbook §8.7.6. After ``bot_skip`` (Task #826) or ``step3``
    (Task #825) has been live for ~24h, run::

        python3 scripts/cf_waf_override.py aggregate \\
            --rule-id 874a3e315c344b1281ad4f00046aab6f --hours 24

    Bot management is intentionally still active on every surface
    *outside* the bot-skip exemption (homepage, /degree/*, login,
    etc.), so non-zero events for the bot rule on those paths is
    correct behaviour — not a regression. The aggregator therefore
    buckets results by path against the exemption expression
    (``--exempt-prefix`` / ``--exempt-exact``, default values match
    ``BOT_SKIP_EXPRESSION``) and only fails when challenge-style
    events appear on the *exempt* paths.

    Exit code is 0 when no challenge-style events hit any exempt
    path (the fix held — non-exempt-path activity is reported but
    accepted), 1 when challenge-style events are still landing on
    the exempt paths (the fix did NOT hold), and 2 on configuration
    or network errors. This is suitable for wiring into a daily
    cron alongside ``verify`` for drift detection.

    The set of "challenge-style" actions counted as a fix-broken
    signal is ``managed_challenge``, ``challenge``, ``js_challenge``
    and ``block``. Other actions (``log``, ``skip``, ``allow``) are
    informational and never fail the gate.
    """
    from datetime import datetime, timedelta, timezone

    zone = _zone_id()
    token = _resolve_token()
    rule_id = args.rule_id
    hours = max(1, args.hours)
    # Defaults mirror BOT_SKIP_EXPRESSION exactly.
    exempt_prefixes = tuple(args.exempt_prefix or ["/api/"])
    exempt_exact = set(args.exempt_exact or ["/sitemap.xml"])
    fail_actions = {"managed_challenge", "challenge", "js_challenge", "block"}
    # Clamp limit into [1, _AGGREGATE_MAX_LIMIT] — CF rejects values
    # above 10000.
    limit = max(1, min(args.graphql_limit, _AGGREGATE_MAX_LIMIT))

    now = datetime.now(timezone.utc)
    until = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    since = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    body = json.dumps(
        {
            "query": _AGGREGATE_QUERY,
            "variables": {
                "zoneTag": zone,
                "since": since,
                "until": until,
                "rule": rule_id,
                "limit": limit,
            },
        }
    ).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        method="POST",
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
        print(
            f"error: Cloudflare GraphQL HTTP {exc.code}: {text}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: Cloudflare GraphQL transport error: {exc}", file=sys.stderr)
        return 2

    errors = payload.get("errors")
    if errors:
        print(f"error: Cloudflare GraphQL errors: {errors}", file=sys.stderr)
        return 2

    zones = (payload.get("data") or {}).get("viewer", {}).get("zones") or []
    groups = zones[0].get("firewallEventsAdaptiveGroups", []) if zones else []

    print(
        f"=== firewallEventsAdaptive aggregation for rule {rule_id} ==="
    )
    print(f"window: {since} → {until}  ({hours}h)")
    print(
        f"exempt prefixes: {list(exempt_prefixes)}   "
        f"exempt exact paths: {sorted(exempt_exact)}"
    )
    # Truncation guard (architect feedback, Task #826 review):
    # CF returns at most `limit` group rows ordered by count_DESC,
    # which means low-volume exempt-path challenge events could be
    # invisibly dropped from the tail when the result set is very
    # high-cardinality. We surface that risk explicitly so operators
    # can re-run with --graphql-limit 10000 (the CF max) and, if
    # still saturated, narrow with --hours.
    if len(groups) >= limit:
        print(
            f"WARNING: result set hit the {limit}-row GraphQL page "
            "limit. Low-volume exempt-path events may be truncated "
            "from the tail. Re-run with `--graphql-limit "
            f"{_AGGREGATE_MAX_LIMIT}` (or shorter `--hours`) before "
            "trusting an exit-0 result."
        )

    if not groups:
        print("0 events matched. Fix held.")
        return 0

    # Bucket by (path-is-exempt, action-is-fail) so we can:
    #   - print non-exempt activity as informational (correct
    #     bot-management behaviour outside the exemption)
    #   - fail the gate ONLY when challenge-style events still hit
    #     exempt paths (which is what Task #826 was meant to stop)
    exempt_fail = []
    exempt_other = []
    nonexempt_fail = []
    nonexempt_other = []

    for g in groups:
        d = g.get("dimensions") or {}
        path = d.get("clientRequestPath") or ""
        action = d.get("action") or ""
        is_exempt = _path_is_exempt(path, exempt_prefixes, exempt_exact)
        is_fail_action = action in fail_actions
        bucket = (
            exempt_fail if (is_exempt and is_fail_action)
            else exempt_other if is_exempt
            else nonexempt_fail if is_fail_action
            else nonexempt_other
        )
        bucket.append(g)

    def _print_bucket(label: str, rows) -> None:
        if not rows:
            return
        subtotal = sum(int(r.get("count") or 0) for r in rows)
        print(f"\n{label}  (subtotal {subtotal}):")
        for r in rows:
            d = r.get("dimensions") or {}
            print(
                f"  count={r.get('count'):>5}  "
                f"action={(d.get('action') or ''):<18} "
                f"source={(d.get('source') or ''):<18} "
                f"host={(d.get('clientRequestHTTPHost') or ''):<24} "
                f"path={d.get('clientRequestPath')!r}"
            )

    _print_bucket(
        "EXEMPT PATHS — challenge-style actions (FIX BROKEN if any)",
        exempt_fail,
    )
    _print_bucket(
        "EXEMPT PATHS — non-challenge actions (informational; expected "
        "to be skip/log post-fix)",
        exempt_other,
    )
    _print_bucket(
        "NON-EXEMPT PATHS — challenge-style actions (expected; bot "
        "protection still active outside the exemption)",
        nonexempt_fail,
    )
    _print_bucket(
        "NON-EXEMPT PATHS — non-challenge actions (informational)",
        nonexempt_other,
    )

    if exempt_fail:
        broken_total = sum(int(r.get("count") or 0) for r in exempt_fail)
        print(
            f"\nFAIL: {broken_total} challenge-style event(s) on exempt "
            "paths. The Skip rule did NOT take effect — re-run "
            "`status` and confirm the http_request_firewall_custom "
            "Skip rule is enabled and references the bot rule under "
            "the correct deployed-ruleset id."
        )
        return 1

    print(
        "\nFix held: zero challenge-style events on exempt paths "
        "during the window. Bot protection on non-exempt paths is "
        "operating normally."
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

    # Task #826 — bot-management Skip rule.
    pbs = sub.add_parser(
        "bot_skip",
        parents=[common],
        help="add a Skip Rules custom-phase rule that exempts /api/* "
             "and /sitemap.xml from a managed bot rule (default = "
             "the Task #826 'manage definite bots' rule)",
    )
    pbs.add_argument(
        "--rule-id",
        default=BOT_DEFINITE_RULE_ID,
        help=f"managed-rule id to skip on the safe paths "
             f"(default {BOT_DEFINITE_RULE_ID})",
    )

    sub.add_parser(
        "rollback_bot_skip",
        parents=[common],
        help="delete the bot_skip Skip rule (idempotent; uses "
             "description-tag lookup so it works without a state file)",
    )

    pa = sub.add_parser(
        "aggregate",
        help="count firewallEventsAdaptive matches for a rule over a "
             "window — the 24h post-fix verification gate "
             "(exit 0 = zero events, 1 = still firing, 2 = error)",
    )
    pa.add_argument(
        "--rule-id",
        default=BOT_DEFINITE_RULE_ID,
        help=f"rule id to aggregate (default {BOT_DEFINITE_RULE_ID})",
    )
    pa.add_argument(
        "--hours", type=int, default=24,
        help="lookback window in hours (default 24)",
    )
    pa.add_argument(
        "--exempt-prefix",
        action="append",
        default=None,
        help="path prefix considered exempt from the rule (repeat "
             "for multiple). Default mirrors BOT_SKIP_EXPRESSION: "
             "['/api/']. Challenge-style events on these paths fail "
             "the gate.",
    )
    pa.add_argument(
        "--exempt-exact",
        action="append",
        default=None,
        help="exact path considered exempt from the rule (repeat "
             "for multiple). Default mirrors BOT_SKIP_EXPRESSION: "
             "['/sitemap.xml']. Challenge-style events on these "
             "paths fail the gate.",
    )
    pa.add_argument(
        "--graphql-limit",
        type=int,
        default=_AGGREGATE_DEFAULT_LIMIT,
        help=f"max grouped rows requested from CF GraphQL (default "
             f"{_AGGREGATE_DEFAULT_LIMIT}, hard CF cap "
             f"{_AGGREGATE_MAX_LIMIT}). Bump to "
             f"{_AGGREGATE_MAX_LIMIT} if the run prints a "
             "page-limit WARNING.",
    )

    pv = sub.add_parser(
        "verify",
        help="assert post-incident steady-state invariants "
             "(exits non-zero on drift; safe to run from cron / CI)",
    )
    pv.add_argument(
        "--expect-disabled-rule",
        default=DEFAULT_OWASP_TRIP_RULE,
        help="OWASP rule id that must be disabled in the OWASP "
             "binding (default = the Task #825 trip rule).",
    )
    pv.add_argument(
        "--expect-skip-bot-rule",
        default=BOT_DEFINITE_RULE_ID,
        help="bot-management rule id that must be listed in the "
             "custom-phase Skip rule (default = the Task #826 "
             "'manage definite bots' rule).",
    )
    pv.add_argument(
        "--no-check-bot-skip",
        action="store_true",
        help="relax invariant 5 (the Task #826 bot-skip rule). Use "
             "ONLY when intentionally rolling back to the pre-#826 "
             "baseline; the verify output will record [SKIP] on that "
             "line so it is visible in incident tickets.",
    )

    args = p.parse_args(argv)
    return {
        "status":             cmd_status,
        "step0":              cmd_step0,
        "step3":              cmd_step3,
        "step4":              cmd_step4,
        "step6":              cmd_step6,
        "bot_skip":           cmd_bot_skip,
        "rollback_bot_skip":  cmd_rollback_bot_skip,
        "aggregate":          cmd_aggregate,
        "rollback3":          cmd_rollback3,
        "rollback4":          cmd_rollback4,
        "verify":             cmd_verify,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())

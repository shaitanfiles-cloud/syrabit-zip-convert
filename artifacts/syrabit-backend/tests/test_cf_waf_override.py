"""Pytest coverage for ``scripts/cf_waf_override.py`` (Task #829).

Why these tests exist
---------------------
``cf_waf_override.py`` is incident-response code we reach for under
pressure (Tasks #825 and #826). A typo in the idempotency logic, the
JSON body shape, or the description-tag matcher could brick our zone's
firewall during the next emergency. These tests pin the behaviour of
the four critical subcommands — ``bot_skip``, ``rollback_bot_skip``,
``verify``, and ``aggregate`` — by stubbing the only two seams the
script has against the live Cloudflare API:

  * ``cf_waf_override._request`` — the universal REST helper that
    every mutating subcommand routes through.
  * ``urllib.request.urlopen`` — used directly by ``cmd_aggregate``
    for the GraphQL call.

State-file writes are redirected to ``tmp_path`` so a flaky test can
never touch the real ``cf_waf_override_state.json`` next to the
script.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
from pathlib import Path

import pytest


# ─── Module loader ───────────────────────────────────────────────────────────
# The script lives in `scripts/` and is normally invoked as `python
# scripts/cf_waf_override.py`. It is NOT on the syrabit-backend import
# path. Load it as a one-off module spec so we can monkeypatch the
# internals.

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "cf_waf_override.py"
)


@pytest.fixture(scope="module")
def cwo():
    """Import the script once per module — it's pure-python and side-
    effect-free at import time (no top-level network calls)."""
    spec = importlib.util.spec_from_file_location(
        "cf_waf_override_under_test", _SCRIPT_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ─── Common test plumbing ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _env_and_state(monkeypatch, tmp_path, cwo):
    """Set the env vars the script requires, and redirect the state
    file into ``tmp_path`` so tests cannot pollute the real file next
    to the script."""
    monkeypatch.setenv("CF_WAF_OVERRIDE_TOKEN", "test-token")
    monkeypatch.setenv("CF_ZONE_ID", "test-zone")
    monkeypatch.setattr(
        cwo, "STATE_FILE", tmp_path / "cf_waf_override_state.json",
    )
    yield


def _ns(**kwargs):
    """Tiny argparse-Namespace stand-in for the four cmd_* entrypoints.
    Defaults match the CLI defaults in ``main()``."""
    base = {
        "dry_run": False,
        "rule_id": None,
        "expect_disabled_rule": None,
        "expect_skip_bot_rule": None,
        "no_check_bot_skip": False,
        "hours": 24,
        "exempt_prefix": None,
        "exempt_exact": None,
        "graphql_limit": 5000,
    }
    base.update(kwargs)
    return types.SimpleNamespace(**base)


class FakeRequest:
    """Capture-and-replay stand-in for ``cwo._request``.

    Use ``.expect(method, url_substring, response)`` to register a
    response for any call whose URL contains ``url_substring``. The
    same handler can serve many calls (PATCH-then-GET test paths).
    Pass ``response="404"`` to simulate the 404-tolerant branch in
    ``_entrypoint_optional`` (returns ``None`` when the caller passed
    ``allow_404=True``, raises otherwise — same as the real script).

    Every call is recorded in ``self.calls`` so tests can assert on
    method, URL substring, body shape, and dry-run flag.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self._handlers: list[tuple[str, str, object]] = []

    def expect(self, method: str, url_substr: str, response):
        self._handlers.append((method, url_substr, response))

    def __call__(self, method, url, token, body=None, dry_run=False, allow_404=False):
        self.calls.append({
            "method": method,
            "url": url,
            "body": body,
            "dry_run": dry_run,
            "allow_404": allow_404,
        })
        if dry_run:
            # Mirror the real script: dry_run short-circuits before
            # touching any handler.
            return {"dry_run": True}
        for h_method, h_substr, response in self._handlers:
            if h_method == method and h_substr in url:
                if response == "404":
                    if allow_404:
                        return None
                    raise SystemExit(
                        f"FakeRequest: 404 not allowed on {method} {url}"
                    )
                return response
        raise AssertionError(
            f"FakeRequest: unmatched call {method} {url} "
            f"(handlers: {[(m, s) for m, s, _ in self._handlers]})"
        )

    def calls_for(self, method: str, url_substr: str = "") -> list[dict]:
        return [
            c for c in self.calls
            if c["method"] == method and url_substr in c["url"]
        ]


@pytest.fixture
def fake_req(monkeypatch, cwo):
    """Replace the script's ``_request`` with a FakeRequest. All
    REST-going code paths in cmd_bot_skip / cmd_rollback_bot_skip /
    cmd_verify funnel through _request, so a single monkeypatch
    suffices."""
    fr = FakeRequest()
    monkeypatch.setattr(cwo, "_request", fr)
    return fr


# ═════════════════════════════════════════════════════════════════════════════
# bot_skip
# ═════════════════════════════════════════════════════════════════════════════


def test_bot_skip_creates_rule_when_entrypoint_exists_and_no_prior_rule(
    cwo, fake_req, capsys,
):
    """Happy path: the custom-firewall entrypoint already exists and
    contains no prior bot-skip rule → a single POST creates the rule.

    Asserts the body shape Cloudflare requires:
      - action = "skip"
      - action_parameters.rules[<DEPLOYED_RULESET_ID>] = [<rule_id>]
      - expression matches the canonical BOT_SKIP_EXPRESSION
      - description carries the BOT_SKIP_DESCRIPTION_TAG
    """
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        {"result": {"id": "ENTRY1", "rules": []}},
    )
    fake_req.expect(
        "POST", "/rulesets/ENTRY1/rules",
        {"result": {"id": "ENTRY1", "rules": [{
            "id": "NEWRULE1",
            "description": cwo.BOT_SKIP_DESCRIPTION,
            "action": "skip",
        }]}},
    )

    rc = cwo.cmd_bot_skip(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID))
    assert rc == 0

    posts = fake_req.calls_for("POST", "/rulesets/ENTRY1/rules")
    assert len(posts) == 1, f"expected exactly one POST, got: {fake_req.calls}"
    body = posts[0]["body"]
    assert body["action"] == "skip"
    assert body["enabled"] is True
    assert body["expression"] == cwo.BOT_SKIP_EXPRESSION
    assert cwo.BOT_SKIP_DESCRIPTION_TAG in body["description"]
    rules_map = body["action_parameters"]["rules"]
    assert cwo.CF_MANAGED_DEPLOYED_RULESET_ID in rules_map
    assert rules_map[cwo.CF_MANAGED_DEPLOYED_RULESET_ID] == [cwo.BOT_DEFINITE_RULE_ID]

    # State file must record the new rule for follow-on rollbacks.
    state = json.loads(cwo.STATE_FILE.read_text())
    saved = state["bot_skip"][cwo.BOT_DEFINITE_RULE_ID]
    assert saved["custom_entrypoint_id"] == "ENTRY1"
    assert saved["custom_rule_id"] == "NEWRULE1"
    assert saved["expression"] == cwo.BOT_SKIP_EXPRESSION
    assert saved["deployed_ruleset_id"] == cwo.CF_MANAGED_DEPLOYED_RULESET_ID

    out = capsys.readouterr().out
    assert "added new skip rule" in out


def test_bot_skip_is_idempotent_patches_existing_rule(cwo, fake_req, capsys):
    """Idempotency: when a rule with ``BOT_SKIP_DESCRIPTION_TAG`` is
    already present, the script must PATCH it in place — not POST a
    duplicate. Re-running ``bot_skip`` repeatedly is a documented
    operator workflow (e.g. to widen the rule_id list)."""
    existing_rule = {
        "id": "EXISTING1",
        "description": (
            f"{cwo.BOT_SKIP_DESCRIPTION_TAG}: prior incarnation, expression "
            "may have drifted"
        ),
        "action": "skip",
        "expression": "stale_expression",
    }
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        {"result": {"id": "ENTRY1", "rules": [existing_rule]}},
    )
    fake_req.expect(
        "PATCH", "/rulesets/ENTRY1/rules/EXISTING1",
        {"result": existing_rule},
    )

    rc = cwo.cmd_bot_skip(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID))
    assert rc == 0

    # Critical: NO POST against the rules collection — we must not
    # duplicate the rule.
    assert not fake_req.calls_for("POST", "/rulesets/ENTRY1/rules"), (
        "bot_skip duplicated the rule instead of PATCHing the existing one: "
        f"{fake_req.calls}"
    )

    patches = fake_req.calls_for("PATCH", "/rulesets/ENTRY1/rules/EXISTING1")
    assert len(patches) == 1
    body = patches[0]["body"]
    # PATCH must restore the canonical expression even when the prior
    # one had drifted — that's the whole point of re-running bot_skip.
    assert body["expression"] == cwo.BOT_SKIP_EXPRESSION
    assert body["action"] == "skip"

    out = capsys.readouterr().out
    assert "updated existing skip rule" in out


def test_bot_skip_creates_entrypoint_when_phase_has_none(cwo, fake_req, capsys):
    """The custom-firewall phase often does not exist on a fresh zone —
    Cloudflare lazily creates it on first use. The script must POST
    a new entrypoint (kind=zone, phase=http_request_firewall_custom,
    rules=[]) before posting the skip rule.

    Asserts the entrypoint-create body shape and the order of calls
    (entrypoint POST → rule POST)."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        "404",
    )
    fake_req.expect(
        "POST", "/zones/test-zone/rulesets",
        {"result": {"id": "NEWENTRY", "rules": []}},
    )
    fake_req.expect(
        "POST", "/rulesets/NEWENTRY/rules",
        {"result": {"id": "NEWENTRY", "rules": [{
            "id": "NEWRULE",
            "description": cwo.BOT_SKIP_DESCRIPTION,
        }]}},
    )

    rc = cwo.cmd_bot_skip(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID))
    assert rc == 0

    # Verify call ordering: entrypoint create THEN rule create.
    methods_urls = [(c["method"], c["url"]) for c in fake_req.calls]
    create_entry_idx = next(
        i for i, (m, u) in enumerate(methods_urls)
        if m == "POST" and u.endswith("/zones/test-zone/rulesets")
    )
    create_rule_idx = next(
        i for i, (m, u) in enumerate(methods_urls)
        if m == "POST" and "/rulesets/NEWENTRY/rules" in u
    )
    assert create_entry_idx < create_rule_idx, (
        "entrypoint POST must precede rule POST"
    )

    # Verify the entrypoint body shape Cloudflare requires.
    create_call = fake_req.calls[create_entry_idx]
    body = create_call["body"]
    assert body["kind"] == "zone"
    assert body["phase"] == "http_request_firewall_custom"
    assert body["rules"] == []
    assert body["name"]  # human-readable name required by CF

    out = capsys.readouterr().out
    assert "creating an empty one" in out
    assert "created custom-firewall entrypoint NEWENTRY" in out


def test_bot_skip_dry_run_does_not_write_state_file(cwo, fake_req):
    """``--dry-run`` must NOT write the state file — operators rely on
    that when previewing a change they intend to back out of."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        {"result": {"id": "ENTRY1", "rules": []}},
    )
    # No POST handler registered — dry_run short-circuits before
    # FakeRequest's match step (it returns {"dry_run": True} for any
    # call with dry_run=True).
    rc = cwo.cmd_bot_skip(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID, dry_run=True))
    assert rc == 0
    assert not cwo.STATE_FILE.exists(), (
        "dry_run must not write the state file"
    )


def test_bot_skip_dry_run_when_entrypoint_absent_uses_placeholder_id(
    cwo, fake_req, capsys,
):
    """Distinct branch: dry-run AND the custom-firewall entrypoint
    does not yet exist. The script must NOT call out to create the
    entrypoint, must NOT write the state file, and must print the
    ``<would-be-created>`` placeholder so operators can preview the
    full sequence end-to-end."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        "404",
    )
    # No POST handler registered for /zones/test-zone/rulesets — if
    # the script attempted to create the entrypoint for real,
    # FakeRequest would assert.
    rc = cwo.cmd_bot_skip(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID, dry_run=True))
    assert rc == 0

    # Confirm no real POST against /zones/test-zone/rulesets happened
    # (the dry_run short-circuit must have absorbed any such call).
    real_creates = [
        c for c in fake_req.calls
        if c["method"] == "POST"
        and "/zones/test-zone/rulesets" in c["url"]
        and not c["url"].endswith("/rules")
        and not c["dry_run"]
    ]
    assert real_creates == [], (
        f"dry_run must not really POST the entrypoint create: {real_creates}"
    )
    assert not cwo.STATE_FILE.exists()

    out = capsys.readouterr().out
    assert "would POST a new one" in out


# ═════════════════════════════════════════════════════════════════════════════
# rollback_bot_skip
# ═════════════════════════════════════════════════════════════════════════════


def test_rollback_bot_skip_deletes_rule_by_description_tag(
    cwo, fake_req, capsys,
):
    """Rollback is keyed off the description tag (NOT the state file),
    so it must work on a fresh checkout where the operator never ran
    ``bot_skip`` locally."""
    skip_rule = {
        "id": "DEL1",
        "description": f"{cwo.BOT_SKIP_DESCRIPTION_TAG}: from a prior incident",
        "action": "skip",
    }
    other_rule = {
        "id": "KEEP1",
        "description": "unrelated custom rule that must not be touched",
    }
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        {"result": {"id": "ENTRY1", "rules": [skip_rule, other_rule]}},
    )
    fake_req.expect(
        "DELETE", "/rulesets/ENTRY1/rules/DEL1",
        {"result": {}},
    )

    rc = cwo.cmd_rollback_bot_skip(_ns())
    assert rc == 0

    deletes = fake_req.calls_for("DELETE")
    assert len(deletes) == 1
    assert "/rulesets/ENTRY1/rules/DEL1" in deletes[0]["url"]
    # Critical: must not delete the unrelated KEEP1 rule.
    assert not any("KEEP1" in c["url"] for c in deletes)

    out = capsys.readouterr().out
    assert "deleted skip rule DEL1" in out


def test_rollback_bot_skip_noop_when_entrypoint_missing(
    cwo, fake_req, capsys,
):
    """If the custom-firewall phase has no entrypoint at all (e.g.
    rolling back on a zone where ``bot_skip`` was never run), the
    rollback must exit 0 without attempting any DELETE — not crash."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        "404",
    )

    rc = cwo.cmd_rollback_bot_skip(_ns())
    assert rc == 0
    assert not fake_req.calls_for("DELETE"), (
        "rollback must not attempt a DELETE when the entrypoint is absent"
    )
    out = capsys.readouterr().out
    assert "nothing to do" in out


def test_rollback_bot_skip_noop_when_tag_rule_absent(cwo, fake_req, capsys):
    """Entrypoint exists but contains no rule tagged with the bot-skip
    description tag — the rollback must exit 0, not crash, not delete
    arbitrary rules."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        {"result": {
            "id": "ENTRY1",
            "rules": [{"id": "OTHER1", "description": "unrelated"}],
        }},
    )
    rc = cwo.cmd_rollback_bot_skip(_ns())
    assert rc == 0
    assert not fake_req.calls_for("DELETE")
    out = capsys.readouterr().out
    assert "already gone" in out


def test_rollback_bot_skip_clears_matching_state_entry(
    cwo, fake_req, tmp_path,
):
    """Successful rollback must remove the matching ``bot_skip`` entry
    from the state file (so the operator's local state mirrors the
    live config)."""
    # Pre-seed state from a hypothetical prior bot_skip run.
    cwo.STATE_FILE.write_text(json.dumps({
        "bot_skip": {
            cwo.BOT_DEFINITE_RULE_ID: {
                "custom_entrypoint_id": "ENTRY1",
                "custom_rule_id": "DEL1",
                "expression": cwo.BOT_SKIP_EXPRESSION,
                "deployed_ruleset_id": cwo.CF_MANAGED_DEPLOYED_RULESET_ID,
            },
        },
        "step0_pre_change": {"some": "snapshot"},
    }))

    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        {"result": {"id": "ENTRY1", "rules": [{
            "id": "DEL1",
            "description": cwo.BOT_SKIP_DESCRIPTION,
        }]}},
    )
    fake_req.expect("DELETE", "/rulesets/ENTRY1/rules/DEL1", {"result": {}})

    rc = cwo.cmd_rollback_bot_skip(_ns())
    assert rc == 0

    state = json.loads(cwo.STATE_FILE.read_text())
    assert "bot_skip" not in state, (
        "rollback must drop the now-empty bot_skip section"
    )
    # Unrelated state must survive.
    assert state["step0_pre_change"] == {"some": "snapshot"}


# ═════════════════════════════════════════════════════════════════════════════
# verify
# ═════════════════════════════════════════════════════════════════════════════


def _passing_fw_entrypoint(cwo) -> dict:
    """Build a managed-firewall entrypoint where invariants 1, 2 and 4 hold."""
    return {"result": {"id": "FW1", "rules": [
        {
            "id": "BIND_CFM",
            "action": "execute",
            "enabled": True,
            "action_parameters": {
                "id": cwo.CF_MANAGED_DEPLOYED_RULESET_ID,
                "overrides": {},
            },
            "description": "Cloudflare Managed Ruleset binding",
        },
        {
            "id": "BIND_OWASP",
            "action": "execute",
            "enabled": True,
            "action_parameters": {
                "id": cwo.CF_OWASP_DEPLOYED_RULESET_ID,
                "overrides": {
                    "rules": [
                        {"id": cwo.DEFAULT_OWASP_TRIP_RULE, "enabled": False},
                    ],
                },
            },
            "description": "OWASP Core Ruleset binding",
        },
    ]}}


def _passing_rl_entrypoint() -> dict:
    return {"result": {"id": "RL1", "rules": [{
        "id": "LCRED",
        "description": "Leaked credential check (managed)",
        "action": "managed_challenge",
        "enabled": True,
    }]}}


def _passing_custom_entrypoint(cwo) -> dict:
    return {"result": {"id": "CF1", "rules": [{
        "id": "SKIP1",
        "action": "skip",
        "enabled": True,
        "description": cwo.BOT_SKIP_DESCRIPTION,
        "expression": cwo.BOT_SKIP_EXPRESSION,
        "action_parameters": {
            "rules": {
                cwo.CF_MANAGED_DEPLOYED_RULESET_ID: [cwo.BOT_DEFINITE_RULE_ID],
            },
        },
    }]}}


def test_verify_all_invariants_hold_returns_zero(cwo, fake_req, capsys):
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _passing_fw_entrypoint(cwo),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint",
        _passing_rl_entrypoint(),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        _passing_custom_entrypoint(cwo),
    )
    rc = cwo.cmd_verify(_ns())
    assert rc == 0
    out = capsys.readouterr().out
    assert "all invariants hold" in out
    # Every line must show PASS, no FAIL line.
    assert "[FAIL]" not in out


def test_verify_fails_when_cf_managed_binding_in_force_log(cwo, fake_req, capsys):
    """Invariant 1 drift: someone left the CF Managed binding in
    force-log mode (overrides.action='log') after a step0. Verify
    must catch it (exit 1) — otherwise the zone has no managed-WAF
    protection at all, silently."""
    fw = _passing_fw_entrypoint(cwo)
    cf_managed = next(
        r for r in fw["result"]["rules"] if r["id"] == "BIND_CFM"
    )
    cf_managed["action_parameters"]["overrides"] = {"action": "log"}

    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint", fw,
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint",
        _passing_rl_entrypoint(),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        _passing_custom_entrypoint(cwo),
    )

    rc = cwo.cmd_verify(_ns())
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "CF Managed Ruleset binding action=execute, no force-log" in out
    assert "overrides.action='log'" in out


def test_verify_fails_when_leaked_credential_rule_still_blocks(
    cwo, fake_req, capsys,
):
    """Invariant 3 drift: the leaked-credential rate-limit rule was
    flipped back to ``block`` (the pre-step4 state). Verify must
    catch it (exit 1) — a real user typing their real password into
    a phishing-mirror would get hard-blocked instead of challenged."""
    rl = _passing_rl_entrypoint()
    rl["result"]["rules"][0]["action"] = "block"

    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _passing_fw_entrypoint(cwo),
    )
    fake_req.expect("GET", "/rulesets/phases/http_ratelimit/entrypoint", rl)
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        _passing_custom_entrypoint(cwo),
    )

    rc = cwo.cmd_verify(_ns())
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "Leaked-credential rate-limit rule action=managed_challenge" in out
    assert "action='block'" in out


def test_verify_fails_when_owasp_trip_rule_not_disabled(cwo, fake_req, capsys):
    """Drift case: someone re-enabled the OWASP trip rule in the
    dashboard. Verify must catch it (exit 1)."""
    fw = _passing_fw_entrypoint(cwo)
    # Remove the per-rule disable override.
    owasp = next(
        r for r in fw["result"]["rules"]
        if r["id"] == "BIND_OWASP"
    )
    owasp["action_parameters"]["overrides"]["rules"] = []

    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint", fw,
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint",
        _passing_rl_entrypoint(),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        _passing_custom_entrypoint(cwo),
    )

    rc = cwo.cmd_verify(_ns())
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "trip-rule" in out


def test_verify_fails_on_expression_drift(cwo, fake_req, capsys):
    """Architect's invariant-5 drift guard: if the bot-skip rule's
    expression has been widened in the dashboard (e.g. to a global
    skip), verify must catch it even though the rule is otherwise
    well-formed."""
    custom = _passing_custom_entrypoint(cwo)
    custom["result"]["rules"][0]["expression"] = (
        '(not http.request.uri.path eq "/")'  # over-broad
    )

    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _passing_fw_entrypoint(cwo),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint",
        _passing_rl_entrypoint(),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        custom,
    )
    rc = cwo.cmd_verify(_ns())
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "expression_matches_canonical=False" in out


def test_verify_fails_when_custom_phase_missing(cwo, fake_req, capsys):
    """Invariant 5 must FAIL when the custom-firewall phase does not
    exist at all (i.e. the bot_skip rule was never created on this zone)."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _passing_fw_entrypoint(cwo),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint",
        _passing_rl_entrypoint(),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        "404",
    )
    rc = cwo.cmd_verify(_ns())
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "no http_request_firewall_custom entrypoint" in out


def test_verify_no_check_bot_skip_relaxes_invariant_5(cwo, fake_req, capsys):
    """``--no-check-bot-skip`` is the documented escape hatch when
    intentionally rolling back to the pre-#826 baseline. Verify must
    return 0 and emit a [SKIP] line for invariant 5 even though the
    custom phase is absent."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _passing_fw_entrypoint(cwo),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint",
        _passing_rl_entrypoint(),
    )
    # Note: NO handler for the custom-phase GET — the script must not
    # call it when --no-check-bot-skip is set.
    rc = cwo.cmd_verify(_ns(no_check_bot_skip=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "[SKIP]" in out
    assert "all invariants hold" in out
    # Confirm the script did not even make the custom-phase GET.
    custom_gets = fake_req.calls_for(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
    )
    assert custom_gets == [], (
        "--no-check-bot-skip must skip the custom-phase GET entirely"
    )


# ═════════════════════════════════════════════════════════════════════════════
# aggregate
# ═════════════════════════════════════════════════════════════════════════════


class _FakeUrlopen:
    """Context-manager-compatible stand-in for ``urllib.request.urlopen``.

    Stores the (url, body, headers) of the request it was called with
    so tests can assert on the GraphQL variables. ``payload`` is the
    JSON body the test wants the server to return; the script reads
    it via ``resp.read()`` then ``json.loads(...)``."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.last_request_body: bytes | None = None
        self.last_url: str | None = None

    def __call__(self, request, timeout=None):
        # The script calls urlopen(req) where req is a urllib.request.Request.
        self.last_request_body = request.data
        self.last_url = request.full_url
        return _FakeResponseCM(self._payload)


class _FakeResponseCM:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._raw


def _wire_aggregate(monkeypatch, payload: dict) -> _FakeUrlopen:
    """Patch the urlopen the script uses for its GraphQL call."""
    fake = _FakeUrlopen(payload)
    # The script calls `urllib.request.urlopen(req, timeout=30)` directly.
    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fake


def test_aggregate_returns_zero_when_no_events(cwo, monkeypatch, capsys):
    """Empty result set → fix held (exit 0)."""
    _wire_aggregate(monkeypatch, {
        "data": {"viewer": {"zones": [{"firewallEventsAdaptiveGroups": []}]}},
    })
    rc = cwo.cmd_aggregate(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID, hours=24))
    assert rc == 0
    out = capsys.readouterr().out
    assert "0 events matched" in out
    assert "Fix held" in out


def test_aggregate_zero_when_only_nonexempt_path_challenges(
    cwo, monkeypatch, capsys,
):
    """Bot protection is intentionally still active outside the
    exemption (homepage, /degree/*, login). Challenge-style events on
    NON-exempt paths are correct behaviour and must NOT fail the
    gate."""
    _wire_aggregate(monkeypatch, {
        "data": {"viewer": {"zones": [{"firewallEventsAdaptiveGroups": [
            {
                "count": 42,
                "dimensions": {
                    "action": "managed_challenge",
                    "source": "firewallmanaged",
                    "ruleId": cwo.BOT_DEFINITE_RULE_ID,
                    "clientRequestPath": "/login",  # NOT exempt
                    "clientRequestHTTPHost": "syrabit.ai",
                },
            },
        ]}]}},
    })
    rc = cwo.cmd_aggregate(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID, hours=24))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Fix held" in out
    # Non-exempt activity must be reported as informational.
    assert "NON-EXEMPT PATHS" in out
    assert "/login" in out


def test_aggregate_fails_on_challenge_against_exempt_path(
    cwo, monkeypatch, capsys,
):
    """The headline failure mode the gate exists to catch: a
    challenge-style action firing on an exempt path means the Skip
    rule did NOT take effect."""
    _wire_aggregate(monkeypatch, {
        "data": {"viewer": {"zones": [{"firewallEventsAdaptiveGroups": [
            {
                "count": 7,
                "dimensions": {
                    "action": "managed_challenge",
                    "source": "firewallmanaged",
                    "ruleId": cwo.BOT_DEFINITE_RULE_ID,
                    "clientRequestPath": "/api/chat/stream",  # EXEMPT
                    "clientRequestHTTPHost": "syrabit.ai",
                },
            },
            {
                "count": 1,
                "dimensions": {
                    "action": "managed_challenge",
                    "source": "firewallmanaged",
                    "ruleId": cwo.BOT_DEFINITE_RULE_ID,
                    "clientRequestPath": "/sitemap.xml",  # EXEMPT (exact)
                    "clientRequestHTTPHost": "syrabit.ai",
                },
            },
        ]}]}},
    })
    rc = cwo.cmd_aggregate(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID, hours=24))
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL: 8 challenge-style event" in out
    assert "EXEMPT PATHS" in out
    assert "/api/chat/stream" in out
    assert "/sitemap.xml" in out


def test_aggregate_log_action_on_exempt_path_does_not_fail(
    cwo, monkeypatch, capsys,
):
    """Non-challenge actions on exempt paths (log/skip/allow) are
    informational and must NOT fail the gate — they're the expected
    post-fix steady state."""
    _wire_aggregate(monkeypatch, {
        "data": {"viewer": {"zones": [{"firewallEventsAdaptiveGroups": [
            {
                "count": 99,
                "dimensions": {
                    "action": "log",
                    "source": "firewallmanaged",
                    "ruleId": cwo.BOT_DEFINITE_RULE_ID,
                    "clientRequestPath": "/api/health",
                    "clientRequestHTTPHost": "syrabit.ai",
                },
            },
        ]}]}},
    })
    rc = cwo.cmd_aggregate(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID, hours=24))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Fix held" in out


def test_aggregate_returns_two_on_graphql_error_payload(
    cwo, monkeypatch, capsys,
):
    """A GraphQL error in the response body must surface as exit 2 —
    distinct from the exit-1 'rule still firing' path so cron alerting
    can branch on it."""
    _wire_aggregate(monkeypatch, {
        "errors": [{"message": "rate limited"}],
    })
    rc = cwo.cmd_aggregate(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID, hours=24))
    assert rc == 2
    err = capsys.readouterr().err
    assert "Cloudflare GraphQL errors" in err


def test_aggregate_returns_two_on_transport_error(cwo, monkeypatch, capsys):
    """Network failures must surface as exit 2."""
    def _boom(*a, **kw):
        raise OSError("connection refused")
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    rc = cwo.cmd_aggregate(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID, hours=24))
    assert rc == 2
    err = capsys.readouterr().err
    assert "transport error" in err


def test_aggregate_returns_two_on_http_error(cwo, monkeypatch, capsys):
    """HTTP-level errors from the GraphQL endpoint (e.g. token revoked
    → 401, account quota → 429, CF outage → 5xx) must surface as exit
    2 with the body excerpt visible to the operator. The script's
    HTTPError branch is distinct from the generic transport-exception
    branch so cron alerting can distinguish 'CF said no' from 'we
    couldn't reach CF at all'."""
    import urllib.error

    def _http_boom(*a, **kw):
        raise urllib.error.HTTPError(
            url="https://api.cloudflare.com/client/v4/graphql",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b'{"errors":[{"message":"rate limited"}]}'),
        )
    monkeypatch.setattr("urllib.request.urlopen", _http_boom)
    rc = cwo.cmd_aggregate(_ns(rule_id=cwo.BOT_DEFINITE_RULE_ID, hours=24))
    assert rc == 2
    err = capsys.readouterr().err
    assert "HTTP 429" in err
    # The body excerpt must be surfaced — operators paste this into
    # incident tickets verbatim.
    assert "rate limited" in err


def test_aggregate_clamps_graphql_limit_to_cf_max(cwo, monkeypatch):
    """Operator-requested ``--graphql-limit`` above the documented CF
    cap (10000) must be clamped — sending a higher value would error
    out of the API."""
    fake = _wire_aggregate(monkeypatch, {
        "data": {"viewer": {"zones": [{"firewallEventsAdaptiveGroups": []}]}},
    })
    cwo.cmd_aggregate(_ns(
        rule_id=cwo.BOT_DEFINITE_RULE_ID, hours=24, graphql_limit=99999,
    ))
    sent = json.loads(fake.last_request_body.decode())
    assert sent["variables"]["limit"] == cwo._AGGREGATE_MAX_LIMIT


def test_aggregate_warns_when_result_set_saturates_page(
    cwo, monkeypatch, capsys,
):
    """When the GraphQL response returns exactly ``limit`` rows (likely
    truncated tail), the aggregator must print a WARNING — silently
    trusting a saturated page would be unsafe (a low-volume exempt-
    path event could be invisibly dropped)."""
    # Build 'limit' rows of non-exempt non-challenge events so the
    # gate still passes but the saturation warning fires.
    rows = [
        {
            "count": 1,
            "dimensions": {
                "action": "log",
                "source": "firewallmanaged",
                "ruleId": cwo.BOT_DEFINITE_RULE_ID,
                "clientRequestPath": f"/some/path/{i}",
                "clientRequestHTTPHost": "syrabit.ai",
            },
        }
        for i in range(5)
    ]
    _wire_aggregate(monkeypatch, {
        "data": {"viewer": {"zones": [{"firewallEventsAdaptiveGroups": rows}]}},
    })
    rc = cwo.cmd_aggregate(_ns(
        rule_id=cwo.BOT_DEFINITE_RULE_ID,
        hours=24,
        graphql_limit=5,  # match the row count exactly to trigger warning
    ))
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "page" in out.lower() or "limit" in out.lower()


def test_aggregate_custom_exempt_lists_override_defaults(
    cwo, monkeypatch, capsys,
):
    """``--exempt-prefix`` / ``--exempt-exact`` must replace the
    defaults so operators can verify other exemptions later."""
    _wire_aggregate(monkeypatch, {
        "data": {"viewer": {"zones": [{"firewallEventsAdaptiveGroups": [
            {
                "count": 3,
                "dimensions": {
                    "action": "managed_challenge",
                    "source": "firewallmanaged",
                    "ruleId": cwo.BOT_DEFINITE_RULE_ID,
                    "clientRequestPath": "/widget/",  # exempt under custom prefix
                    "clientRequestHTTPHost": "syrabit.ai",
                },
            },
        ]}]}},
    })
    rc = cwo.cmd_aggregate(_ns(
        rule_id=cwo.BOT_DEFINITE_RULE_ID,
        hours=24,
        exempt_prefix=["/widget/"],
        exempt_exact=["/robots.txt"],
    ))
    # /widget/ is exempt under our custom list AND it received a
    # challenge → fix-broken (exit 1).
    assert rc == 1
    out = capsys.readouterr().out
    assert "/widget/" in out
    # The default '/api/' must not appear in the printed exempt-prefix list.
    assert "/api/" not in out


# ═════════════════════════════════════════════════════════════════════════════
# Path-matcher helper (used by aggregate; pure function — easy to lock in)
# ═════════════════════════════════════════════════════════════════════════════


def test_path_is_exempt_prefix_match(cwo):
    assert cwo._path_is_exempt("/api/chat/stream", ["/api/"], set()) is True
    assert cwo._path_is_exempt("/api/", ["/api/"], set()) is True
    assert cwo._path_is_exempt("/apidocs", ["/api/"], set()) is False
    assert cwo._path_is_exempt("/login", ["/api/"], set()) is False


def test_path_is_exempt_exact_match(cwo):
    assert cwo._path_is_exempt("/sitemap.xml", [], {"/sitemap.xml"}) is True
    assert cwo._path_is_exempt("/sitemap.xml/", [], {"/sitemap.xml"}) is False


def test_path_is_exempt_handles_non_string_inputs(cwo):
    assert cwo._path_is_exempt(None, ["/api/"], {"/x"}) is False
    assert cwo._path_is_exempt(123, ["/api/"], {"/x"}) is False


# ═════════════════════════════════════════════════════════════════════════════
# status (Task #832)
# ═════════════════════════════════════════════════════════════════════════════
#
# `status` is the only read-only subcommand and is the operator's first
# move on every incident. The tests below pin two things that have bitten
# us before:
#   1. the printed output surfaces every dimension the rest of the
#      orchestrator keys off (rule ids, deployed-ruleset ids, the per-rule
#      override list, and the Skip-rule expression — operators paste this
#      verbatim into incident tickets);
#   2. the custom-firewall phase being absent must NOT crash the
#      command — it's the on-demand phase created by `bot_skip` and
#      will not exist on a fresh zone.


def test_status_prints_all_three_entrypoints(cwo, fake_req, capsys):
    """Happy path: status fetches the managed-firewall, rate-limit, and
    custom-firewall entrypoints and prints every dimension the rest of
    the orchestrator keys off (rule ids, deployed-ruleset ids, per-rule
    overrides, Skip-rule expression)."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _passing_fw_entrypoint(cwo),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint",
        _passing_rl_entrypoint(),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        _passing_custom_entrypoint(cwo),
    )

    rc = cwo.cmd_status(_ns())
    assert rc == 0
    out = capsys.readouterr().out

    # Managed-firewall section: both bindings rendered with rule_id +
    # deployed_ruleset id.
    assert "BIND_CFM" in out
    assert "BIND_OWASP" in out
    assert cwo.CF_MANAGED_DEPLOYED_RULESET_ID in out
    assert cwo.CF_OWASP_DEPLOYED_RULESET_ID in out
    # Per-rule override on the OWASP binding (the trip rule disable)
    # must be visible — operators eyeball this to confirm step3 took.
    assert cwo.DEFAULT_OWASP_TRIP_RULE in out

    # Rate-limit section: leaked-cred rule rendered.
    assert "LCRED" in out
    assert "managed_challenge" in out

    # Custom-firewall section: Skip rule with deployed_ruleset id and
    # the canonical bot-skip expression.
    assert "SKIP1" in out
    assert cwo.BOT_DEFINITE_RULE_ID in out
    assert cwo.BOT_SKIP_EXPRESSION in out


def test_status_handles_missing_custom_phase_gracefully(cwo, fake_req, capsys):
    """Drift / fresh-zone case: the custom-firewall phase has no
    entrypoint yet (the `bot_skip` subcommand creates it lazily). The
    read-only `status` command must NOT crash — it must print the
    "(none)" sentinel and still return 0 so an operator can run it
    safely on any zone shape."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _passing_fw_entrypoint(cwo),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint",
        _passing_rl_entrypoint(),
    )
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_custom/entrypoint",
        "404",
    )

    rc = cwo.cmd_status(_ns())
    assert rc == 0
    out = capsys.readouterr().out
    assert "(none" in out
    # Operator hint pointing at `bot_skip` is part of the runbook —
    # pin it so a casual rewording of this string doesn't lose it.
    assert "bot_skip" in out


# ═════════════════════════════════════════════════════════════════════════════
# step0  (and the step0 ↔ step6 round-trip)
# ═════════════════════════════════════════════════════════════════════════════
#
# step0 is the most blast-radius-heavy mutation in the script: it flips
# both managed-ruleset bindings to force-log, dropping the zone's WAF
# protection until step6 lifts it. The tests below pin:
#   1. the PATCH body shape CF requires (action stays "execute"; only
#      action_parameters.overrides.action becomes "log");
#   2. the snapshot written to the state file has enough information
#      for step6 to faithfully restore the original action;
#   3. the idempotency rules — re-running step0 must NOT re-PATCH a
#      binding already in force-log mode, and must NOT overwrite the
#      first-call snapshot;
#   4. the state-freshness check that protects against a stale
#      previous-incident snapshot teaching step6 to restore wrong
#      values;
#   5. the abort path when the entrypoint contains no managed bindings
#      — silently doing nothing on a customised zone would be a worse
#      outcome than aborting and asking a human to look.


def _fw_pre_step0(cwo) -> dict:
    """A managed-firewall entrypoint in the pre-incident steady state:
    both bindings exist, action=execute, no overrides.action set, OWASP
    has no per-rule overrides yet. Used by every step0/step6 test."""
    return {"result": {"id": "FW1", "rules": [
        {
            "id": "BIND_CFM",
            "action": "execute",
            "enabled": True,
            "action_parameters": {
                "id": cwo.CF_MANAGED_DEPLOYED_RULESET_ID,
                "overrides": {},
            },
            "expression": "true",
            "description": "Cloudflare Managed Ruleset binding",
        },
        {
            "id": "BIND_OWASP",
            "action": "execute",
            "enabled": True,
            "action_parameters": {
                "id": cwo.CF_OWASP_DEPLOYED_RULESET_ID,
                "overrides": {},
            },
            "expression": "true",
            "description": "OWASP Core Ruleset binding",
        },
    ]}}


def test_step0_flips_both_bindings_and_snapshots_for_step6(
    cwo, fake_req, capsys,
):
    """Happy path: both managed-ruleset bindings get
    ``overrides.action='log'`` while the binding's primary
    ``action`` stays ``execute`` (CF rejects the alternative). The
    pre-change action of each is recorded in the state file so step6
    knows what to restore."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _fw_pre_step0(cwo),
    )
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_CFM", {"result": {}})
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_OWASP", {"result": {}})

    rc = cwo.cmd_step0(_ns())
    assert rc == 0

    # Both bindings PATCHed exactly once.
    cfm = fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_CFM")
    owasp = fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_OWASP")
    assert len(cfm) == 1 and len(owasp) == 1, fake_req.calls

    # CF Ruleset API contract: managed-firewall bindings MUST keep
    # action="execute"; the force-log behaviour is opted into via
    # action_parameters.overrides.action="log".
    for body in (cfm[0]["body"], owasp[0]["body"]):
        assert body["action"] == "execute"
        assert body["action_parameters"]["overrides"]["action"] == "log"
        # The binding must remain enabled — disabling it would drop
        # WAF entirely instead of force-logging it.
        assert body["enabled"] is True

    # Snapshot for step6: must record both binding ids with their
    # ORIGINAL (pre-step0) override.action and binding action.
    state = json.loads(cwo.STATE_FILE.read_text())
    saved = state["step0_pre_change"]
    assert set(saved.keys()) == {"BIND_CFM", "BIND_OWASP"}
    for snap in saved.values():
        assert snap["override_action"] is None  # was unset pre-incident
        assert snap["binding_action"] == "execute"
    assert state["entrypoint_id"] == "FW1"


def test_step0_idempotent_skips_binding_already_in_force_log(
    cwo, fake_req, capsys,
):
    """Re-running step0 mid-incident must NOT re-PATCH a binding that
    is already in force-log mode (no-op'd by the idempotency guard),
    and must NOT overwrite the snapshot recorded on the FIRST call —
    losing that would teach step6 to restore the wrong value."""
    fw = _fw_pre_step0(cwo)
    cfm = next(r for r in fw["result"]["rules"] if r["id"] == "BIND_CFM")
    cfm["action_parameters"]["overrides"] = {"action": "log"}

    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint", fw,
    )
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_OWASP", {"result": {}})

    rc = cwo.cmd_step0(_ns())
    assert rc == 0

    # CFM was already in force-log → must not be re-PATCHed.
    assert not fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_CFM"), (
        "step0 must NOT re-PATCH a binding already in force-log mode"
    )
    # OWASP was clean → must be PATCHed.
    assert fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_OWASP")

    # The snapshot still records BOTH bindings — including CFM's
    # pre-step0 override.action='log' so step6 restores the
    # genuinely-original value rather than blindly removing the key.
    state = json.loads(cwo.STATE_FILE.read_text())
    saved = state["step0_pre_change"]
    assert saved["BIND_CFM"]["override_action"] == "log"
    assert saved["BIND_OWASP"]["override_action"] is None

    out = capsys.readouterr().out
    assert "already overrides.action='log'" in out


def test_step0_aborts_when_no_managed_bindings_found(cwo, fake_req):
    """Drift case: the managed-firewall entrypoint contains no OWASP
    or CF-Managed binding (e.g. heavily-customised zone). step0 must
    SystemExit cleanly — silently doing nothing would mean the
    operator believes WAF is in force-log mode when it actually
    isn't."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        {"result": {"id": "FW1", "rules": [
            {
                "id": "OTHER",
                "action": "execute",
                "action_parameters": {"id": "irrelevant-deployed-id"},
                "description": "some unrelated custom binding",
            },
        ]}},
    )
    with pytest.raises(SystemExit) as exc:
        cwo.cmd_step0(_ns())
    assert "no managed-ruleset bindings found" in str(exc.value)


def test_step0_refreshes_stale_snapshot_from_previous_incident(
    cwo, fake_req, capsys,
):
    """State-freshness guard: if the state file contains a snapshot
    from a PREVIOUS incident (no binding currently in force-log), it
    must be refreshed from live state — otherwise step6 would restore
    values that are no longer the natural pre-incident state of THIS
    incident. The associated stale step3 marker must also be dropped
    so step6's precondition gate doesn't fail on a phantom rule id."""
    cwo.STATE_FILE.write_text(json.dumps({
        "step0_pre_change": {
            "BIND_CFM": {
                "override_action": "log",  # stale; live state is None
                "binding_action": "execute",
                "description": "stale CFM entry from prior incident",
            },
        },
        "step3": {
            "some-old-rule-from-last-incident": {
                "binding_id": "BIND_OWASP",
                "entrypoint_id": "FW1",
            },
        },
        "entrypoint_id": "FW1",
    }))
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _fw_pre_step0(cwo),
    )
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_CFM", {"result": {}})
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_OWASP", {"result": {}})

    rc = cwo.cmd_step0(_ns())
    assert rc == 0

    state = json.loads(cwo.STATE_FILE.read_text())
    saved = state["step0_pre_change"]
    # Stale CFM entry replaced with LIVE values.
    assert saved["BIND_CFM"]["override_action"] is None
    assert "BIND_OWASP" in saved
    # Stale step3 marker cleared so step6's precondition gate isn't
    # checking against a rule that the previous incident disabled.
    assert state["step3"] == {}

    out = capsys.readouterr().out
    assert "stale step0 snapshot" in out


def test_step0_dry_run_does_not_write_state_file(cwo, fake_req):
    """``--dry-run`` must not persist anything to the state file —
    operators rely on that when previewing a step0 they intend to
    back out of."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _fw_pre_step0(cwo),
    )
    rc = cwo.cmd_step0(_ns(dry_run=True))
    assert rc == 0
    assert not cwo.STATE_FILE.exists()


# ═════════════════════════════════════════════════════════════════════════════
# step3 / rollback3
# ═════════════════════════════════════════════════════════════════════════════


def test_step3_appends_per_rule_disable_override(cwo, fake_req, capsys):
    """Happy path: step3 PATCHes the OWASP binding to add a per-rule
    override that disables ``--rule-id``. The override is the
    {"id": <rule>, "enabled": False} shape CF requires; the binding's
    primary action stays ``execute``."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _fw_pre_step0(cwo),
    )
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_OWASP", {"result": {}})

    rc = cwo.cmd_step3(_ns(rule_id=cwo.DEFAULT_OWASP_TRIP_RULE))
    assert rc == 0

    patches = fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_OWASP")
    assert len(patches) == 1
    body = patches[0]["body"]
    assert body["action"] == "execute"  # CF requires this on managed bindings
    rules_overrides = body["action_parameters"]["overrides"]["rules"]
    assert len(rules_overrides) == 1
    assert rules_overrides[0] == {
        "id": cwo.DEFAULT_OWASP_TRIP_RULE, "enabled": False,
    }

    state = json.loads(cwo.STATE_FILE.read_text())
    assert state["step3"][cwo.DEFAULT_OWASP_TRIP_RULE] == {
        "binding_id": "BIND_OWASP",
        "entrypoint_id": "FW1",
    }


def test_step3_idempotent_updates_existing_override_in_place(
    cwo, fake_req, capsys,
):
    """If the rule already has an override entry (e.g. someone left it
    enabled=True in the dashboard), step3 must UPDATE that entry in
    place rather than appending a duplicate — duplicate entries with
    the same id are a documented source of CF Ruleset API errors."""
    fw = _fw_pre_step0(cwo)
    owasp = next(r for r in fw["result"]["rules"] if r["id"] == "BIND_OWASP")
    owasp["action_parameters"]["overrides"] = {
        "rules": [
            {"id": cwo.DEFAULT_OWASP_TRIP_RULE, "enabled": True, "action": "block"},
        ],
    }
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint", fw,
    )
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_OWASP", {"result": {}})

    rc = cwo.cmd_step3(_ns(rule_id=cwo.DEFAULT_OWASP_TRIP_RULE))
    assert rc == 0

    body = fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_OWASP")[0]["body"]
    overrides = body["action_parameters"]["overrides"]["rules"]
    # Exactly one entry — the existing one was UPDATED, not appended.
    matching = [o for o in overrides if o["id"] == cwo.DEFAULT_OWASP_TRIP_RULE]
    assert len(matching) == 1, (
        f"step3 duplicated the override instead of updating in place: {overrides}"
    )
    # The updated entry must be disabled, and the now-irrelevant
    # ``action`` key must be removed (the script does this explicitly).
    assert matching[0]["enabled"] is False
    assert "action" not in matching[0]


def test_step3_aborts_when_owasp_binding_missing(cwo, fake_req):
    """Drift case: the OWASP binding has been removed (or never
    existed on this zone). step3 must SystemExit — silently doing
    nothing would let the operator believe the trip rule is disabled
    when it isn't, and step6's precondition gate would then refuse to
    lift force-log."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        {"result": {"id": "FW1", "rules": [
            {
                "id": "BIND_CFM",
                "action": "execute",
                "action_parameters": {"id": cwo.CF_MANAGED_DEPLOYED_RULESET_ID},
                "description": "Cloudflare Managed Ruleset binding",
            },
        ]}},
    )
    with pytest.raises(SystemExit) as exc:
        cwo.cmd_step3(_ns(rule_id=cwo.DEFAULT_OWASP_TRIP_RULE))
    assert "OWASP" in str(exc.value)


def test_rollback3_removes_override_for_named_rule(cwo, fake_req, capsys):
    """Happy path: rollback3 PATCHes the OWASP binding with the
    targeted rule id removed from the per-rule overrides list. Other
    overrides on the same binding must be preserved."""
    fw = _fw_pre_step0(cwo)
    owasp = next(r for r in fw["result"]["rules"] if r["id"] == "BIND_OWASP")
    owasp["action_parameters"]["overrides"] = {
        "rules": [
            {"id": cwo.DEFAULT_OWASP_TRIP_RULE, "enabled": False},
            {"id": "unrelated-rule-id", "enabled": False},
        ],
    }
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint", fw,
    )
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_OWASP", {"result": {}})

    rc = cwo.cmd_rollback3(_ns(rule_id=cwo.DEFAULT_OWASP_TRIP_RULE))
    assert rc == 0

    body = fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_OWASP")[0]["body"]
    remaining = body["action_parameters"]["overrides"]["rules"]
    assert all(o["id"] != cwo.DEFAULT_OWASP_TRIP_RULE for o in remaining)
    # Critical: the unrelated override must NOT have been collateral-
    # damaged. (A naive implementation that wipes the whole list
    # would re-enable an unrelated rule we still want disabled.)
    assert any(o["id"] == "unrelated-rule-id" for o in remaining)


def test_rollback3_aborts_when_owasp_binding_missing(cwo, fake_req):
    """Drift case mirroring the step3 abort: rollback3 must
    SystemExit if the OWASP binding can't be found."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        {"result": {"id": "FW1", "rules": []}},
    )
    with pytest.raises(SystemExit) as exc:
        cwo.cmd_rollback3(_ns(rule_id=cwo.DEFAULT_OWASP_TRIP_RULE))
    assert "OWASP" in str(exc.value)


# ═════════════════════════════════════════════════════════════════════════════
# step4 / rollback4
# ═════════════════════════════════════════════════════════════════════════════


def _rl_pre_step4() -> dict:
    """A rate-limit entrypoint where the leaked-credential rule is
    currently action=block (the pre-step4 state)."""
    return {"result": {"id": "RL1", "rules": [{
        "id": "LCRED",
        "description": "Leaked credential check (managed)",
        "action": "block",
        "enabled": True,
        "expression": "true",
        "ratelimit": {"period": 10, "requests_per_period": 5},
    }]}}


def test_step4_changes_block_to_managed_challenge(cwo, fake_req, capsys):
    """Happy path: step4 PATCHes the leaked-credential rate-limit rule
    from action=block → managed_challenge. The ``ratelimit`` block is
    forwarded verbatim (CF rejects PATCHes that drop it)."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint",
        _rl_pre_step4(),
    )
    fake_req.expect("PATCH", "/rulesets/RL1/rules/LCRED", {"result": {}})

    rc = cwo.cmd_step4(_ns())
    assert rc == 0

    body = fake_req.calls_for("PATCH", "/rulesets/RL1/rules/LCRED")[0]["body"]
    assert body["action"] == "managed_challenge"
    # Forwarded verbatim — the script reuses the existing rule's
    # ratelimit dict instead of reconstructing it.
    assert body["ratelimit"] == {"period": 10, "requests_per_period": 5}

    state = json.loads(cwo.STATE_FILE.read_text())
    saved = state["step4"]["LCRED"]
    assert saved["action"] == "block"  # original action recorded for rollback4
    assert saved["ratelimit_entrypoint_id"] == "RL1"


def test_step4_idempotent_no_patch_when_already_managed_challenge(
    cwo, fake_req, capsys,
):
    """If the rule is already managed_challenge (e.g. step4 ran
    earlier in the same incident), step4 must skip the PATCH but
    still ensure the state file has an entry — otherwise rollback4
    would have nothing to restore from."""
    rl = _rl_pre_step4()
    rl["result"]["rules"][0]["action"] = "managed_challenge"
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint", rl,
    )
    # No PATCH handler registered — if the script attempted a PATCH,
    # FakeRequest would assert.

    rc = cwo.cmd_step4(_ns())
    assert rc == 0
    assert not fake_req.calls_for("PATCH", "/rulesets/RL1/rules/LCRED")

    state = json.loads(cwo.STATE_FILE.read_text())
    assert "LCRED" in state["step4"]
    out = capsys.readouterr().out
    assert "already action=managed_challenge" in out


def test_step4_aborts_when_leaked_cred_rule_not_found(cwo, fake_req):
    """Drift case: the rate-limit entrypoint has no rule whose
    description contains both 'leaked' and 'credential'. step4 must
    SystemExit so the operator investigates rather than silently
    leaving a phishing-mirror block in place."""
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint",
        {"result": {"id": "RL1", "rules": [
            {"id": "RL_OTHER", "description": "an unrelated rate limit",
             "action": "block", "enabled": True},
        ]}},
    )
    with pytest.raises(SystemExit) as exc:
        cwo.cmd_step4(_ns())
    assert "leaked" in str(exc.value).lower()


def test_rollback4_restores_action_from_state(cwo, fake_req, capsys):
    """Happy path: rollback4 reads the saved action from the state
    file and PATCHes the rule back to it."""
    cwo.STATE_FILE.write_text(json.dumps({
        "step4": {
            "LCRED": {
                "action": "block",
                "ratelimit_entrypoint_id": "RL1",
                "description": "Leaked credential check (managed)",
            },
        },
    }))
    rl = _rl_pre_step4()
    rl["result"]["rules"][0]["action"] = "managed_challenge"
    fake_req.expect("GET", "/rulesets/phases/http_ratelimit/entrypoint", rl)
    fake_req.expect("PATCH", "/rulesets/RL1/rules/LCRED", {"result": {}})

    rc = cwo.cmd_rollback4(_ns())
    assert rc == 0

    body = fake_req.calls_for("PATCH", "/rulesets/RL1/rules/LCRED")[0]["body"]
    assert body["action"] == "block"
    # ratelimit must be forwarded — CF requires it on rate-limit rule
    # PATCHes.
    assert body["ratelimit"] == {"period": 10, "requests_per_period": 5}


def test_rollback4_aborts_when_no_state(cwo, fake_req):
    """Drift case: rollback4 invoked without a prior step4 (state file
    has no ``step4`` key). Must SystemExit — there's nothing to
    restore TO and guessing 'block' would be unsafe (the operator
    might have intentionally moved the rule to ``js_challenge``)."""
    # No state file written at all.
    with pytest.raises(SystemExit) as exc:
        cwo.cmd_rollback4(_ns())
    assert "no step4 state" in str(exc.value)


def test_rollback4_skips_rule_no_longer_in_ruleset(cwo, fake_req, capsys):
    """Edge case: the rate-limit rule recorded in state has been
    deleted from the live ruleset (e.g. rule rotation). rollback4 must
    print a "skipped" notice and exit 0 — not crash, not PATCH a
    URL that no longer exists."""
    cwo.STATE_FILE.write_text(json.dumps({
        "step4": {
            "GHOST_RULE": {
                "action": "block",
                "ratelimit_entrypoint_id": "RL1",
                "description": "deleted long ago",
            },
        },
    }))
    fake_req.expect(
        "GET", "/rulesets/phases/http_ratelimit/entrypoint",
        {"result": {"id": "RL1", "rules": []}},
    )
    rc = cwo.cmd_rollback4(_ns())
    assert rc == 0
    assert not fake_req.calls_for("PATCH"), (
        "rollback4 must not PATCH a rule that no longer exists"
    )
    out = capsys.readouterr().out
    assert "GHOST_RULE" in out and "skipped" in out


# ═════════════════════════════════════════════════════════════════════════════
# step6  (and the step0 → step6 round-trip)
# ═════════════════════════════════════════════════════════════════════════════
#
# step6 is the inverse of step0 — it lifts the force-log override and
# re-enables blocking. The most consequential thing it does is read
# the snapshot written by step0 and use it to decide what to put back.
# A wrong restored value here means an incident is "fixed" but actually
# left the zone in a different state from the one it started in.
# Particular pins:
#   1. the precondition gate that refuses to lift force-log unless
#      step3's per-rule disable is still in place (otherwise step6
#      would re-block the very users the incident response just
#      unblocked);
#   2. the ``--force`` escape hatch when the operator has hand-applied
#      an equivalent fix in the dashboard;
#   3. the abort path when the state file is empty (refusing to guess);
#   4. the round-trip test below: a snapshot written by step0 must be
#      faithfully consumed by step6 to restore the original action.


def _fw_post_step0_step3(cwo) -> dict:
    """Live state AFTER step0+step3 ran: both bindings have
    overrides.action='log', and OWASP additionally has the trip-rule
    disable override (so step6's precondition gate accepts the call)."""
    return {"result": {"id": "FW1", "rules": [
        {
            "id": "BIND_CFM",
            "action": "execute",
            "enabled": True,
            "action_parameters": {
                "id": cwo.CF_MANAGED_DEPLOYED_RULESET_ID,
                "overrides": {"action": "log"},
            },
            "expression": "true",
            "description": "Cloudflare Managed Ruleset binding",
        },
        {
            "id": "BIND_OWASP",
            "action": "execute",
            "enabled": True,
            "action_parameters": {
                "id": cwo.CF_OWASP_DEPLOYED_RULESET_ID,
                "overrides": {
                    "action": "log",
                    "rules": [
                        {"id": cwo.DEFAULT_OWASP_TRIP_RULE, "enabled": False},
                    ],
                },
            },
            "expression": "true",
            "description": "OWASP Core Ruleset binding",
        },
    ]}}


def test_step6_restores_overrides_from_step0_snapshot(cwo, fake_req, capsys):
    """Happy path: with a clean step0 snapshot on file (override_action
    was None pre-incident), step6 PATCHes both bindings such that
    overrides.action is removed entirely. step3's per-rule disable
    survives because step6 reads the binding LIVE rather than from a
    stale snapshot."""
    cwo.STATE_FILE.write_text(json.dumps({
        "step0_pre_change": {
            "BIND_CFM": {"override_action": None, "binding_action": "execute",
                         "description": "CFM binding"},
            "BIND_OWASP": {"override_action": None, "binding_action": "execute",
                           "description": "OWASP binding"},
        },
        "entrypoint_id": "FW1",
    }))
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _fw_post_step0_step3(cwo),
    )
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_CFM", {"result": {}})
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_OWASP", {"result": {}})

    rc = cwo.cmd_step6(_ns())
    assert rc == 0

    cfm_body = fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_CFM")[0]["body"]
    owasp_body = fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_OWASP")[0]["body"]

    # CFM had no per-rule overrides AND its pre-step0 override.action
    # was None → the whole `overrides` dict should be omitted.
    cfm_ap = cfm_body["action_parameters"]
    assert "overrides" not in cfm_ap, (
        f"CFM step6 left empty overrides dict: {cfm_ap}"
    )

    # OWASP had a per-rule override that step6 must PRESERVE — only
    # the override.action key is removed.
    owasp_ap = owasp_body["action_parameters"]
    assert "action" not in owasp_ap["overrides"]
    rule_overrides = owasp_ap["overrides"]["rules"]
    assert any(
        o["id"] == cwo.DEFAULT_OWASP_TRIP_RULE and o["enabled"] is False
        for o in rule_overrides
    ), (
        "step6 must preserve step3's per-rule disable when lifting "
        f"force-log: {rule_overrides}"
    )


def test_step0_step6_round_trip_restores_nondefault_pre_action(
    cwo, monkeypatch, capsys,
):
    """End-to-end round-trip for the failure mode the snapshot exists
    to prevent: a binding whose override.action was NOT None
    pre-incident (e.g. CFM was already in 'log' for an unrelated
    long-running experiment). step0 must capture that value, and
    step6 must restore it — NOT silently flip it to None.

    This is the interaction the task description specifically called
    out as 'a regression there could mean an incident is recovered
    with the wrong original action'."""
    # Pre-incident state: CFM is in custom 'log' mode for an unrelated
    # reason; OWASP is clean.
    fw_pre = _fw_pre_step0(cwo)
    cfm_pre = next(r for r in fw_pre["result"]["rules"] if r["id"] == "BIND_CFM")
    cfm_pre["action_parameters"]["overrides"] = {"action": "log"}

    # Phase 1: run step0 → snapshot must capture override_action='log'
    # for CFM.
    fr1 = FakeRequest()
    monkeypatch.setattr(cwo, "_request", fr1)
    fr1.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint", fw_pre,
    )
    fr1.expect("PATCH", "/rulesets/FW1/rules/BIND_OWASP", {"result": {}})
    # (CFM is already in force-log → step0 won't PATCH it.)

    rc0 = cwo.cmd_step0(_ns())
    assert rc0 == 0
    snap = json.loads(cwo.STATE_FILE.read_text())["step0_pre_change"]
    assert snap["BIND_CFM"]["override_action"] == "log", (
        "step0 must record the genuine pre-incident override value; "
        "got snapshot " + json.dumps(snap)
    )
    assert snap["BIND_OWASP"]["override_action"] is None

    # Phase 2: between step0 and step6, the operator runs step3 and
    # the OWASP trip rule is now disabled. CFM and OWASP are both in
    # force-log mode in live state.
    fw_post = _fw_post_step0_step3(cwo)

    # Phase 3: run step6 with a fresh FakeRequest (so we can inspect
    # only the step6-issued calls). step6 must:
    #   • restore CFM's overrides.action to 'log' (the saved value),
    #   • REMOVE OWASP's overrides.action entirely (the saved value
    #     was None) while preserving the per-rule disable.
    fr2 = FakeRequest()
    monkeypatch.setattr(cwo, "_request", fr2)
    fr2.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint", fw_post,
    )
    fr2.expect("PATCH", "/rulesets/FW1/rules/BIND_CFM", {"result": {}})
    fr2.expect("PATCH", "/rulesets/FW1/rules/BIND_OWASP", {"result": {}})

    rc6 = cwo.cmd_step6(_ns())
    assert rc6 == 0

    cfm_body = fr2.calls_for("PATCH", "/rulesets/FW1/rules/BIND_CFM")[0]["body"]
    assert cfm_body["action_parameters"]["overrides"]["action"] == "log", (
        "step6 silently flipped CFM back to None instead of "
        "restoring the genuine pre-incident 'log'"
    )
    owasp_body = fr2.calls_for("PATCH", "/rulesets/FW1/rules/BIND_OWASP")[0]["body"]
    owasp_overrides = owasp_body["action_parameters"]["overrides"]
    assert "action" not in owasp_overrides
    assert any(
        o["id"] == cwo.DEFAULT_OWASP_TRIP_RULE and o["enabled"] is False
        for o in owasp_overrides["rules"]
    )


def test_step6_aborts_when_no_state_on_file(cwo, fake_req):
    """Drift case: step6 invoked without a prior step0. The script
    must SystemExit rather than guess what the original action was —
    guessing here would be the worst kind of silent failure."""
    # No state file on disk.
    with pytest.raises(SystemExit) as exc:
        cwo.cmd_step6(_ns())
    assert "no step0 state" in str(exc.value)


def test_step6_precondition_gate_refuses_when_trip_rule_re_enabled(
    cwo, fake_req,
):
    """Architect-feedback gate: step6 must REFUSE to lift force-log
    when the OWASP trip rule is no longer disabled. Lifting force-log
    in that state would re-block the very users the incident response
    just unblocked."""
    cwo.STATE_FILE.write_text(json.dumps({
        "step0_pre_change": {
            "BIND_CFM": {"override_action": None, "binding_action": "execute",
                         "description": "CFM"},
            "BIND_OWASP": {"override_action": None, "binding_action": "execute",
                           "description": "OWASP"},
        },
        "entrypoint_id": "FW1",
    }))
    # Live state: force-log is in place but the per-rule disable is
    # GONE (someone re-enabled it in the dashboard, or rollback3 ran).
    fw = _fw_post_step0_step3(cwo)
    owasp = next(r for r in fw["result"]["rules"] if r["id"] == "BIND_OWASP")
    owasp["action_parameters"]["overrides"]["rules"] = []
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint", fw,
    )
    # No PATCH handler — if the script proceeded past the gate,
    # FakeRequest would assert on the unmatched call.

    with pytest.raises(SystemExit) as exc:
        cwo.cmd_step6(_ns())
    msg = str(exc.value)
    assert "refusing to lift force-log" in msg
    assert cwo.DEFAULT_OWASP_TRIP_RULE in msg


def test_step6_force_bypasses_precondition_gate(cwo, fake_req, capsys):
    """``--force`` is the documented escape hatch when the operator
    has hand-applied an equivalent fix in the dashboard. With force=True
    step6 must proceed even though the per-rule disable is missing."""
    cwo.STATE_FILE.write_text(json.dumps({
        "step0_pre_change": {
            "BIND_CFM": {"override_action": None, "binding_action": "execute",
                         "description": "CFM"},
            "BIND_OWASP": {"override_action": None, "binding_action": "execute",
                           "description": "OWASP"},
        },
        "entrypoint_id": "FW1",
    }))
    fw = _fw_post_step0_step3(cwo)
    owasp = next(r for r in fw["result"]["rules"] if r["id"] == "BIND_OWASP")
    owasp["action_parameters"]["overrides"]["rules"] = []  # gate would normally fail
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint", fw,
    )
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_CFM", {"result": {}})
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_OWASP", {"result": {}})

    rc = cwo.cmd_step6(_ns(force=True))
    assert rc == 0
    # Both PATCHes happened despite the missing per-rule disable.
    assert fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_CFM")
    assert fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_OWASP")


def test_step6_skips_binding_no_longer_in_entrypoint(cwo, fake_req, capsys):
    """Edge case: the snapshot references a binding id that no longer
    exists in the live entrypoint (someone deleted it in the dashboard
    mid-incident). step6 must print a "skipped" notice and continue
    with the remaining bindings — not crash, not PATCH a URL that
    points at a deleted resource."""
    cwo.STATE_FILE.write_text(json.dumps({
        "step0_pre_change": {
            "GHOST_BIND": {"override_action": None, "binding_action": "execute",
                           "description": "deleted in dashboard"},
            "BIND_OWASP": {"override_action": None, "binding_action": "execute",
                           "description": "OWASP"},
        },
        "entrypoint_id": "FW1",
    }))
    fake_req.expect(
        "GET", "/rulesets/phases/http_request_firewall_managed/entrypoint",
        _fw_post_step0_step3(cwo),
    )
    fake_req.expect("PATCH", "/rulesets/FW1/rules/BIND_OWASP", {"result": {}})

    rc = cwo.cmd_step6(_ns())
    assert rc == 0
    # OWASP got its PATCH; GHOST_BIND did not.
    assert fake_req.calls_for("PATCH", "/rulesets/FW1/rules/BIND_OWASP")
    assert not any("GHOST_BIND" in c["url"] for c in fake_req.calls)
    out = capsys.readouterr().out
    assert "GHOST_BIND" in out and "skipped" in out

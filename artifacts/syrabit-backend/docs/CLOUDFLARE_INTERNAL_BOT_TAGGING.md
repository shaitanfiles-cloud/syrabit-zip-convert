# Identifying Syrabit-internal bot traffic in Cloudflare (Task #820)

## Why this exists

Several backend processes hit `syrabit.ai` through Cloudflare with
self-identifying User-Agents:

| Source                                    | UA substring             |
|-------------------------------------------|--------------------------|
| Sitemap self-check / deep-scan            | `SyrabitSEOHealth/1.0`   |
| Edge KV bot-cache prewarm                 | `syrabit-prewarm/1.0`    |
| RAG / web content fetcher                 | `SyrabitBot/1.0`         |
| Google Suggest probe                      | `SyrabitSEOBot/1.0`      |

Until Task #820, each call-site duplicated its own UA literal and
nothing tied them together. Cloudflare bot analytics scored every
self-check as `likely automated` and bucketed them under "unknown bot",
which made it impossible to tell our own internal traffic apart from
real third-party crawlers when reading dashboards or investigating
spikes. Worse — the prewarm UA intentionally *spoofs* Googlebot to
seed the edge bot cache, so it inflated Googlebot's own count in our
per-UA report.

## What changed

1. **Single source of truth** — `internal_user_agents.py`
   - One UA constant + one header factory per call-site.
   - Every UA carries the canonical `SyrabitInternal` marker.
   - Every header factory injects `X-Syrabit-Internal: 1`.
2. **Per-UA report** — `cf_bot_report._classify_ua` now returns `None`
   for any UA matching the registry, *before* the search-bot pattern
   list runs. So the prewarm-Googlebot-spoof no longer inflates the
   Googlebot bucket.
3. **Call-sites updated** to import from the registry:
   - `routes/bot_discovery.py` (prewarm + SEO self-check)
   - `web_content.py` (RAG / web-content fetcher)
   - `google_suggest_client.py` (SEO probe)
   - `rag.py` (rag fetch helper)

## What still needs operator action in Cloudflare

The Cloudflare API token currently bound to the runtime
(`CLOUDFLARE_ANALYTICS_TOKEN` / legacy `CLOUDFLARE_API_TOKEN`) is
read-only — it has `Account Analytics:Read`, `Zone Analytics:Read` and
`Zone:Read` only. It cannot create WAF / Custom Rules. So the rule
below has to be added through the Cloudflare dashboard by hand.

### Custom Rule — "Tag Syrabit-internal self-check traffic"

**Path:** Cloudflare dashboard → `syrabit.ai` zone → Security → WAF →
Custom rules → **Create rule**.

| Field        | Value                                                                                                                                   |
|--------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| Rule name    | `Tag Syrabit-internal self-check traffic`                                                                                               |
| When incoming requests match | Custom filter expression (see below)                                                                                    |
| Action       | **Skip** → all remaining custom rules + Super Bot Fight Mode + Bot Fight Mode (so SBFM stops scoring our own traffic as "likely bot")   |
| Logging      | Leave **enabled** — the request stays visible in Security Events with the rule label `internal_self_check`                             |

**Expression (Wireshark/CF Filter syntax):**

```text
(http.request.headers["x-syrabit-internal"][0] eq "1")
or (http.user_agent contains "SyrabitInternal")
or (http.user_agent contains "SyrabitSEOHealth")
or (http.user_agent contains "syrabit-prewarm")
or (http.user_agent contains "SyrabitSEOBot")
or (http.user_agent contains "SyrabitBot")
```

The header check is the long-term canonical match — anything we add
in the future only needs to carry the header. The UA `contains`
clauses are defence-in-depth in case a request reaches the edge with
the header stripped (some intermediate proxies do that).

### Why this works

- **Bot Analytics** — once the SBFM skip kicks in, the request stops
  being scored, drops out of the "Likely automated" bucket, and shows
  up in **Security Events** under your custom rule with action `skip`.
  The "Bot traffic" tile then represents only real third-party bots.
- **Logpush / Logpull** — the `RuleID` and `Description` fields on the
  request log let downstream tooling group all `internal_self_check`
  hits in one query.
- **GraphQL Analytics** — `firewallEventsAdaptiveGroups` exposes the
  `ruleId` dimension, so reports that want to chart self-check volume
  over time can pivot on it directly.

### Verifying the rule

After adding the rule, send a request that matches it and look it up
in **Security Events**:

```bash
curl -sI 'https://syrabit.ai/sitemap.xml' \
     -H 'X-Syrabit-Internal: 1' \
     -H 'User-Agent: Mozilla/5.0 (compatible; SyrabitSEOHealth/1.0; +https://syrabit.ai/api/seo/health; SyrabitInternal)'
```

Expected: `HTTP/2 200`, plus a Security Events entry tagged with
your rule name and action `skip`.

If you instead see a `403` or a managed challenge, the SBFM skip
ordering is wrong — rules execute top-to-bottom and the
`internal_self_check` rule must sit ABOVE any block / challenge rule.

## Adding a new internal bot

1. Add its UA constant + header factory to `internal_user_agents.py`,
   including the `SyrabitInternal` marker in the UA string.
2. If the new UA introduces a brand-new distinguishing substring (one
   not already covered by `SyrabitInternal`), append the lower-cased
   form to `INTERNAL_UA_TOKENS`.
3. The Cloudflare Custom Rule above does **not** need updating — the
   `X-Syrabit-Internal: 1` header that every new factory injects is
   already covered by the first clause of the expression.

## Future hardening

When `CF_ZONE_ID` gains a write-capable token (`Zone WAF:Edit`), the
manual step above can be replaced by a deploy-time `wrangler` /
Terraform run that PUTs the rule via
`POST /zones/{zone_id}/firewall/rules`. The rule body the deploy job
should send is the JSON equivalent of the table above; the expression
above is already in the canonical CF Filter syntax that the API
accepts.

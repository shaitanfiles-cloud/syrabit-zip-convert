# Vertex AI / Gemini Setup for Syrabit

`vertex_services.py` powers every Gemini-backed feature on the backend:
embeddings (Vectorize ingestion + RAG), translation, vision OCR, MCQ /
flashcard generation, content enhancement, SEO meta, gap analysis and
the long-document reader.

It supports three credential modes, detected at import time and chosen
in this priority order:

| Priority | Mode | Trigger env var | Endpoint |
|----------|------|-----------------|----------|
| 1 | Vertex AI service account | `VERTEX_SERVICE_ACCOUNT` (or `GEMINI_API_KEY` containing JSON) | `{region}-aiplatform.googleapis.com` |
| 2 | Google AI Studio API key | `GEMINI_API_KEY=AIza…` | `generativelanguage.googleapis.com` |
| 3 | BYOK via Cloudflare AI Gateway | `CF_AI_GATEWAY_ACCOUNT_ID` + `CF_AI_GATEWAY_ID` (no local credential) | gateway injects |

Whichever mode is active, requests are additionally routed through the
Cloudflare AI Gateway when `CF_AI_GATEWAY_ACCOUNT_ID` and
`CF_AI_GATEWAY_ID` are both set. URLs are rewritten to:

- `…/google-ai-studio/v1beta/models/<model>:<op>` for AI Studio mode
- `…/google-vertex-ai/v1/projects/<proj>/locations/<loc>/publishers/google/models/<model>:<op>` for SA mode

## Required Railway env vars

Set the trigger for whichever mode you want, plus the gateway vars if you
want gateway routing (recommended — gives logs, caching and BYOK).

### Mode 1 — Vertex AI service account (recommended for production)

```bash
VERTEX_SERVICE_ACCOUNT='{"type":"service_account","project_id":"…","private_key":"…",…}'
VERTEX_PROJECT_ID=syrabit-prod        # optional, overrides project_id from JSON
VERTEX_LOCATION=us-central1           # optional, defaults to us-central1
```

The SA needs:
- `roles/aiplatform.user` on the project
- "Vertex AI API" enabled in GCP Console

### Mode 2 — Google AI Studio API key (simplest)

```bash
GEMINI_API_KEY=AIzaSy…                # from https://aistudio.google.com/apikey
```

### Mode 3 — BYOK via CF AI Gateway (no local credential)

```bash
CF_AI_GATEWAY_ACCOUNT_ID=<account-id>
CF_AI_GATEWAY_ID=syrabit
CF_AI_GATEWAY_TOKEN=<authenticated-gateway-token>   # if gateway auth is on
CF_AI_GATEWAY_BYOK=1                                # default; set 0 to disable
```

In the Cloudflare dashboard → AI Gateway → `syrabit` → Bring Your Own
Keys, add a binding for `google-ai-studio` (or `google-vertex-ai`) with
the upstream key.

## Optional knobs

```bash
EMBED_MAX_CONCURRENT=8                # in-flight embed cap (Task #545)
EMBED_RETRY_MAX_ATTEMPTS=3
EMBED_RETRY_BASE_MS=400               # exponential backoff base
CF_AI_GATEWAY_CACHE_TTL=3600          # cf-aig-cache-ttl hint
```

## Verifying

After deploy, hit the admin health endpoint:

```bash
curl https://api.syrabit.ai/admin/cms/sarvam-health/vertex/health
```

Expected response with `auth_mode` set to one of
`vertex_ai_service_account`, `google_ai_studio_api_key`, or
`cf_ai_gateway_byok`, plus `embeddings: true` and `generation: true`.

If `auth_mode` is `disabled`, no credential is being picked up — check
that the env var is actually present in Railway and that the SA JSON is
valid (one-line, no smart quotes).

## Embedding fallback

The embed path falls back to Cloudflare Workers AI
(`@cf/baai/bge-base-en-v1.5`, 768-dim) when the primary Gemini call
fails transiently. Vectorize `syllabus-index-v2` is a 1024-dim index, so
fallback vectors land in a side path — the syllabus embedder
dimension-checks via `_current_embed_model` before upserting. This keeps
the seed loop moving during Vertex outages without polluting the primary
index.

# Vertex AI / Gemini Setup

`vertex_services.py` powers Gemini-backed features: embeddings,
translation, vision OCR, MCQ + flashcard generation, content
enhancement, SEO meta, gap analysis, and the long-document reader.

## Auth modes (priority order)

| Mode | Trigger env var |
|------|-----------------|
| Vertex AI service account | `VERTEX_SERVICE_ACCOUNT` (or `GEMINI_API_KEY` containing JSON) |
| Google AI Studio API key  | `GEMINI_API_KEY=AIza…` |
| BYOK via CF AI Gateway    | `CF_AI_GATEWAY_ACCOUNT_ID` + `CF_AI_GATEWAY_ID` (no local creds) |

When `CF_AI_GATEWAY_ACCOUNT_ID` + `CF_AI_GATEWAY_ID` are both set,
requests are routed through the gateway by URL rewriting and
`cf-aig-authorization` / `cf-aig-cache-ttl` headers are attached.

## Required env vars

### Service account
```
VERTEX_SERVICE_ACCOUNT='{"type":"service_account",...}'
VERTEX_PROJECT_ID=syrabit-prod        # optional
VERTEX_LOCATION=us-central1           # optional
```
SA needs `roles/aiplatform.user` and the Vertex AI API enabled.

### API key
```
GEMINI_API_KEY=AIzaSy…
```

### BYOK
```
CF_AI_GATEWAY_ACCOUNT_ID=...
CF_AI_GATEWAY_ID=syrabit
CF_AI_GATEWAY_TOKEN=...               # if gateway auth is on
CF_AI_GATEWAY_BYOK=1                  # default
```
Add a `google-ai-studio` (or `google-vertex-ai`) BYOK binding in the CF
dashboard.

### Optional
```
EMBED_MAX_CONCURRENT=8                # in-flight embed cap
EMBED_RETRY_MAX_ATTEMPTS=3
EMBED_RETRY_BASE_MS=400
CF_AI_GATEWAY_CACHE_TTL=3600
VERTEX_REQUIRED=1                     # raise on boot if no creds
```

## Verifying

```
GET /admin/cms/sarvam-health/vertex/health
```
Expect `auth_mode` in
{`vertex_ai_service_account`, `google_ai_studio_api_key`, `cf_ai_gateway_byok`},
`embeddings: true`, `generation: true`, `embed_dimensions: 1024`.

If `auth_mode` is `disabled`, no credential is configured. Check Railway
env vars and confirm SA JSON is valid (single-line, no smart quotes).

## Embedding contract

`embed_text` returns `Optional[List[float]]` — a 1024-dim vector
(`gemini-embedding-001`) or `None` on failure. Vectorize
`syllabus-index-v2` is 1024-dim; this module never returns a
dimension-mismatched fallback. Callers must handle `None`.

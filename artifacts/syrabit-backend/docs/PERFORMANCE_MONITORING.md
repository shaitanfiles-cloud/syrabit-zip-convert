# Performance Monitoring & Distributed Tracing — Task #610

Two complementary stacks now ship telemetry from a Syrabit chat request:

| Layer            | Tool                            | Signal                                     |
| ---------------- | ------------------------------- | ------------------------------------------ |
| Browser RUM      | Firebase Performance Monitoring | LCP, INP, CLS, TTFB, FCP, page loads, custom chat traces |
| Edge → Backend   | W3C `traceparent` header        | Single trace ID per chat request           |
| Backend / LLM    | OpenTelemetry → Cloud Trace     | FastAPI request span + `chat.first_token` + `chat.total_ms` + downstream httpx |

Everything is **production-only and sampled**: development builds, local
Railway origins, and unconfigured deploys see zero overhead because every
SDK is gated behind an env-var check that no-ops when the values are
missing.

---

## 1. Configuration

### Frontend (Cloudflare Pages)

Set these `VITE_FIREBASE_*` env vars **only on the production Pages
project** (see `artifacts/syrabit/.env.example`):

```
VITE_FIREBASE_API_KEY=…
VITE_FIREBASE_AUTH_DOMAIN=syrabit.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=syrabit-prod
VITE_FIREBASE_STORAGE_BUCKET=syrabit-prod.appspot.com
VITE_FIREBASE_MESSAGING_SENDER_ID=…
VITE_FIREBASE_APP_ID=…
VITE_FIREBASE_MEASUREMENT_ID=G-…
VITE_FIREBASE_PERF_SAMPLE_RATE=0.2
```

Sample rate `0.2` traces ~20% of sessions. The bucket is sticky for the
page-view (sessionStorage) so all metrics from one visit ship together.

### Backend (Cloud Run / Railway)

Set on the Cloud Run service env (or via `gcloud run services update`):

```
TRACING_ENABLED=1
TRACE_SAMPLE_RATIO=0.1
OTEL_SERVICE_NAME=syrabit-backend
OTEL_EXPORTER=cloud_trace
GCP_PROJECT_ID=syrabit-prod
DEPLOYMENT_ENV=production
```

For non-GCP backends (e.g. Honeycomb), use:

```
OTEL_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io
```

---

## 2. Spans emitted by the chat flow

Every `POST /api/ai/chat/stream` request creates one trace with these
attributes on the FastAPI request span:

| Attribute                         | Example      | Notes                                   |
| --------------------------------- | ------------ | --------------------------------------- |
| `syrabit.chat.intent`             | `notes`      | from `classify_intent`                  |
| `syrabit.chat.model`              | `openai/gpt-oss-20b` | model id forwarded to LLM         |
| `syrabit.chat.path`               | `instant` / `cache` / `early-cache` / `main` | which fast-path won |
| `syrabit.chat.is_anon`            | `true`       | anonymous (Turnstile) vs user          |
| `syrabit.chat.has_subject`        | `false`      | subject context present                |
| `syrabit.chat.message_chars`      | `42`         | input length                           |
| `syrabit.chat.first_token_ms`    | `820.5`      | TTFT (recorded once)                    |
| `syrabit.chat.first_token_source`| `llm` / `cache` / `early-cache` / `instant` | what produced the first chunk |
| `syrabit.chat.total_ms`          | `4 320`      | wall-clock send→done                    |
| `syrabit.chat.retrieval_ms`      | `380`        | wall-clock for retrieval phase (Phase 0+1+2 + cache lookup + prompt build); 0 on instant path |
| `syrabit.chat.cached`            | `true`       | RAG-cache hit                           |
| `syrabit.chat.web_used`          | `false`      | speculative web search consumed         |
| `syrabit.chat.rag_source`        | `internal` / `web` / `cache` / `none` |                              |
| `syrabit.chat.provider`          | `groq`       | LLM provider that won the hedge        |

`chat.first_token` is also emitted as a span event so it's plottable on
the timeline view.

### 2.1 Phase child spans

The request span has up to three explicit child spans so the trace
waterfall in Cloud Trace shows where time is being spent. Each carries
`phase.duration_ms` plus the same `syrabit.chat.*` attributes that are
relevant to that phase:

| Span name              | Covers                                                                 |
|------------------------|------------------------------------------------------------------------|
| `chat.retrieval`       | request start → prompt handed to LLM (Phase 0+1+2, cache lookup, build) |
| `chat.llm_call`        | first byte sent to provider → last token received                       |
| `chat.post_processing` | last token → done event (Indic sanitize, cache write, persist, log)     |

Cache-hit / early-cache / instant short paths emit only the spans that
make sense (e.g. instant path emits a single `chat.post_processing`
because there is no retrieval or LLM work).

### 2.2 Sampling policy

The backend uses `TraceIdRatioBased(TRACE_SAMPLE_RATIO)` **without**
`ParentBased`. This means: a client always sending `traceparent` with
the sampled flag set (`01`) cannot force the backend to record 100% of
requests — `TRACE_SAMPLE_RATIO` (default `0.1`) is the authoritative
sampling rate. The trace_id is still preserved end-to-end so
cross-service correlation works for the requests both ends decide to
sample.

---

## 3. Cloud Trace dashboard recipe

1. **Cloud Trace → Trace Explorer**, filter:
   `service.name = syrabit-backend AND span:/api/ai/chat/stream`.
2. Save as **"Chat — All paths"**. Group-by `syrabit.chat.path` for
   instant / cache / early-cache / main breakdown.
3. Open **Cloud Monitoring → Dashboards → Create**, add charts:
   - **Chat TTFT p95** — metric:
     `custom.googleapis.com/opentelemetry/syrabit.chat.first_token_ms`,
     aggregator `99th` and `95th` percentile, group-by `path`.
   - **Chat total p95** — same metric, key `syrabit.chat.total_ms`.
   - **Request rate** — `cloudtrace.googleapis.com/spans` count.
4. Save dashboard as **"Syrabit · Chat Latency"**.

---

## 4. Firebase Performance dashboard recipe

In the Firebase console for the production project:

1. **Performance → Dashboard**: built-in tiles for LCP / INP / CLS /
   TTFB / FCP populate within ~30 min after the first sampled session.
2. **Performance → Custom traces**:
   - `chat_send_first_token` — TTFT as observed by the browser.
   - `chat_send_total` — full send→done.
   - Per-trace attributes: `model`, `auth`, `has_subject`, `error`.
3. Group-by `model` to compare provider performance.

---

## 5. Starter alerts

Both alerts fire on degradation, not absolute thresholds, so they keep
working as the product evolves.

### A. Cloud Monitoring — chat p95 latency

- Condition: `syrabit.chat.total_ms` p95 over 10-min window
  `> 8 000` ms for chat path `main` (excludes cache / instant).
- Notification channel: `#alerts-syrabit` Slack.
- Auto-close after 5 min healthy.

### B. Firebase Performance — LCP regression

- Trace: `_app_start` (built-in) + `web_vital_LCP` custom trace.
- Threshold: 75th-percentile LCP `> 2 500 ms` for any URL pattern
  matching `/chat*` or `/`.
- Notification: same Slack channel.

### C. (Optional) Cloud Trace anomaly

- Trace anomaly alert on `/api/ai/chat/stream` p95 latency increase
  `> 25%` week-over-week.

---

## 6. Verifying instrumentation

```bash
# Backend — should print "[tracing] initialized service=syrabit-backend …"
TRACING_ENABLED=1 OTEL_EXPORTER=console TRACE_SAMPLE_RATIO=1.0 \
  uvicorn server:app --host 0.0.0.0 --port 8000

# In another shell, send one chat request and watch the span print:
curl -N -X POST http://localhost:8000/api/ai/chat/stream \
  -H 'Content-Type: application/json' \
  -H 'x-anon-id: anon_00000000000000000000000000000000' \
  -H 'traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01' \
  -d '{"message":"hi","conversation_id":null}'
```

The console exporter dumps spans with their `traceparent` linked back to
the client-supplied trace ID — proving end-to-end propagation.

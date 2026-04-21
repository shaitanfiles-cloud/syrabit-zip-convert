"""Syrabit.ai — OpenTelemetry distributed tracing (Task #610).

Production-only, sampled distributed tracing for the chat flow. When
``TRACING_ENABLED`` is set (and the optional OpenTelemetry packages are
installed), this module wires up:

  * a TracerProvider with ``ParentBased(TraceIdRatioBased(ratio))`` sampler
    so we trace ~10–20% of requests by default and zero overhead on the
    rest,
  * a W3C ``tracecontext`` + ``baggage`` propagator so trace IDs flow
    edge-worker → backend → Vertex,
  * the FastAPI / httpx auto-instrumentations,
  * an exporter — Google Cloud Trace by default, or OTLP over gRPC/HTTP
    when ``OTEL_EXPORTER=otlp`` is set, falling back to a no-op console
    exporter when neither is available.

The whole module is failure-tolerant: a missing dependency, mis-configured
exporter, or unset GCP project never raises — ``init_tracing`` just
returns ``False`` and the rest of the app keeps running unchanged.

Custom span helpers (``chat_span``, ``record_chat_attrs``,
``record_first_token``) are no-ops until init succeeds, so call sites in
``routes/ai_chat.py`` stay clean and pay zero cost when tracing is off.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "init_tracing",
    "is_tracing_enabled",
    "chat_span",
    "emit_phase_span",
    "record_chat_attrs",
    "record_first_token",
    "get_current_trace_id",
]

_INITIALIZED = False
_ENABLED = False
_TRACER: Any = None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def is_tracing_enabled() -> bool:
    return _ENABLED


def _load_sa_credentials_from_env_json():
    """Parse a Google service-account JSON from `GOOGLE_APPLICATION_CREDENTIALS_JSON`.

    Returns a `google.oauth2.service_account.Credentials` instance, or None
    if the env var is unset, the JSON is unparseable, or google-auth is not
    installed. Tolerant of common copy-paste mistakes (leading/trailing
    whitespace, missing outer braces, trailing comma).
    """
    raw = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "") or "").strip()
    if not raw:
        return None
    import json as _json
    info = None
    try:
        info = _json.loads(raw)
    except _json.JSONDecodeError:
        # Tolerate: user pasted the inside of the JSON file without the
        # outer `{` and `}` (a recurring footgun on most secret-manager UIs).
        s = raw
        if not s.startswith("{"):
            s = "{" + s
        if not s.rstrip().endswith("}"):
            s = s.rstrip().rstrip(",") + "}"
        try:
            info = _json.loads(s)
        except Exception as exc:
            logger.warning("[tracing] GOOGLE_APPLICATION_CREDENTIALS_JSON unparseable: %s", exc)
            return None
    if not isinstance(info, dict):
        logger.warning(
            "[tracing] GOOGLE_APPLICATION_CREDENTIALS_JSON parsed as %s, expected JSON object",
            type(info).__name__,
        )
        return None
    required = ("type", "project_id", "private_key", "client_email")
    missing = [f for f in required if not info.get(f)]
    if missing:
        logger.warning(
            "[tracing] GOOGLE_APPLICATION_CREDENTIALS_JSON missing required field(s): %s — re-paste the FULL JSON file",
            ", ".join(missing),
        )
        return None
    try:
        from google.oauth2 import service_account  # type: ignore
        return service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    except Exception as exc:
        logger.warning("[tracing] could not build SA credentials from env JSON: %s", exc)
        return None


def init_tracing(app: Any) -> bool:
    """Idempotent initialization. Returns True on successful wire-up.

    Reads:
      TRACING_ENABLED        — master gate ("1"/"true" to enable)
      TRACE_SAMPLE_RATIO     — float 0.0–1.0 (default 0.1)
      OTEL_SERVICE_NAME      — defaults to "syrabit-backend"
      OTEL_EXPORTER          — "cloud_trace" (default) | "otlp" | "console"
      GCP_PROJECT_ID         — required for cloud_trace exporter
                               (falls back to GOOGLE_CLOUD_PROJECT /
                                VERTEX_PROJECT_ID)
      OTEL_EXPORTER_OTLP_ENDPOINT — used by otlp exporter
    """
    global _INITIALIZED, _ENABLED, _TRACER
    if _INITIALIZED:
        return _ENABLED
    _INITIALIZED = True

    if not _env_bool("TRACING_ENABLED", False):
        logger.info("[tracing] disabled (TRACING_ENABLED not set)")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.propagators.composite import CompositePropagator
        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextTextMapPropagator,
        )
        from opentelemetry.baggage.propagation import W3CBaggagePropagator
    except Exception as exc:
        logger.warning(
            "[tracing] OpenTelemetry SDK not installed — tracing disabled (%s)",
            exc,
        )
        return False

    ratio = max(0.0, min(1.0, _env_float("TRACE_SAMPLE_RATIO", 0.1)))
    service_name = os.environ.get("OTEL_SERVICE_NAME", "syrabit-backend")

    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.environ.get("OTEL_SERVICE_VERSION", "2.0.0"),
        "deployment.environment": os.environ.get("DEPLOYMENT_ENV", "production"),
    })
    # Use TraceIdRatioBased *without* ParentBased so the backend
    # sampling decision is authoritative — a chat client that always
    # sends a `traceparent` with the sampled flag set ("01") cannot
    # force the backend to record 100% of requests. The trace_id from
    # the incoming traceparent is still preserved end-to-end (it's the
    # input to the deterministic ratio check), so cross-service
    # correlation works whenever both ends sample the same trace_id.
    sampler = TraceIdRatioBased(ratio)
    provider = TracerProvider(resource=resource, sampler=sampler)

    exporter_kind = (os.environ.get("OTEL_EXPORTER", "cloud_trace") or "").strip().lower()
    exporter = None
    if exporter_kind == "cloud_trace":
        project = (
            os.environ.get("GCP_PROJECT_ID")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("VERTEX_PROJECT_ID")
            or ""
        ).strip()
        if not project:
            logger.warning(
                "[tracing] OTEL_EXPORTER=cloud_trace but no GCP_PROJECT_ID set — falling back to console"
            )
            exporter = ConsoleSpanExporter()
        else:
            try:
                from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
                # On Cloud Run, the runtime service account provides
                # Application Default Credentials automatically — just grant
                # it `roles/cloudtrace.agent` and no JSON key is needed.
                # Outside Cloud Run (Railway, local prod, etc.) we accept a
                # `GOOGLE_APPLICATION_CREDENTIALS_JSON` env var carrying the
                # full SA-key JSON content, since most of those platforms
                # cannot mount a file for `GOOGLE_APPLICATION_CREDENTIALS`.
                creds = _load_sa_credentials_from_env_json()
                if creds is not None:
                    exporter = CloudTraceSpanExporter(project_id=project, credentials=creds)
                    logger.info(
                        "[tracing] using Cloud Trace exporter for project=%s (SA from env JSON)",
                        project,
                    )
                else:
                    exporter = CloudTraceSpanExporter(project_id=project)
                    logger.info(
                        "[tracing] using Cloud Trace exporter for project=%s (ADC)",
                        project,
                    )
            except Exception as exc:
                logger.warning(
                    "[tracing] Cloud Trace exporter unavailable (%s) — falling back to console",
                    exc,
                )
                exporter = ConsoleSpanExporter()
    elif exporter_kind == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
            exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
            logger.info("[tracing] using OTLP exporter endpoint=%s", endpoint or "(default)")
        except Exception as exc:
            logger.warning("[tracing] OTLP exporter unavailable (%s) — falling back to console", exc)
            exporter = ConsoleSpanExporter()
    else:
        exporter = ConsoleSpanExporter()
        logger.info("[tracing] using console exporter (debug only)")

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    set_global_textmap(CompositePropagator([
        TraceContextTextMapPropagator(),
        W3CBaggagePropagator(),
    ]))

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="/health,/api/health,/api/metrics,/api/admin/health,/favicon.ico",
        )
    except Exception as exc:
        logger.warning("[tracing] FastAPI auto-instrumentation failed: %s", exc)

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except Exception as exc:
        logger.debug("[tracing] httpx instrumentation skipped: %s", exc)

    _TRACER = trace.get_tracer("syrabit.chat")
    _ENABLED = True
    logger.info(
        "[tracing] initialized service=%s sampler=ratio(%.2f) exporter=%s",
        service_name, ratio, exporter_kind,
    )
    return True


@contextmanager
def chat_span(name: str, **attrs: Any) -> Iterator[Any]:
    """Start a custom span that nests under the current request span.

    No-op (yields None) when tracing is disabled, so call sites can
    always wrap interesting work without checking flags first.
    """
    if not _ENABLED or _TRACER is None:
        yield None
        return
    span = _TRACER.start_span(name)
    try:
        for k, v in attrs.items():
            try:
                span.set_attribute(k, v)
            except Exception:
                pass
        yield span
    except Exception as exc:
        try:
            span.record_exception(exc)
            from opentelemetry.trace import Status, StatusCode
            span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
        except Exception:
            pass
        raise
    finally:
        try:
            span.end()
        except Exception:
            pass


def record_chat_attrs(**attrs: Any) -> None:
    """Attach arbitrary key/value attributes to the *current* span
    (the one auto-created by FastAPIInstrumentor for the HTTP request)."""
    if not _ENABLED:
        return
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span is None:
            return
        for k, v in attrs.items():
            try:
                if v is not None:
                    span.set_attribute(k, v)
            except Exception:
                pass
    except Exception:
        pass


def record_first_token(elapsed_ms: float, *, source: str = "llm") -> None:
    """Record chat first-token latency on the current request span."""
    if not _ENABLED:
        return
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span is None:
            return
        try:
            # Canonical keys (match dashboard/alert contract documented
            # in docs/PERFORMANCE_MONITORING.md).
            span.set_attribute("syrabit.chat.first_token_ms", float(elapsed_ms))
            span.set_attribute("syrabit.chat.first_token_source", source)
            # Legacy keys preserved for backwards compatibility with any
            # ad-hoc queries that may already reference them.
            span.set_attribute("chat.first_token_ms", float(elapsed_ms))
            span.set_attribute("chat.first_token_source", source)
            span.add_event("chat.first_token", {"elapsed_ms": float(elapsed_ms), "source": source})
        except Exception:
            pass
    except Exception:
        pass


def emit_phase_span(name: str, start_ts: float, end_ts: float, **attrs: Any) -> None:
    """Emit a child span retroactively for a chat-flow phase using the
    captured wall-clock start/end timestamps (``time.time()``).

    Used by ``routes/ai_chat.py`` to materialize ``chat.retrieval``,
    ``chat.llm_call`` and ``chat.post_processing`` as proper nested
    spans without restructuring the streaming generator. The start/end
    pair is converted to nanoseconds (OTel's native unit) and passed
    via ``start_time`` / ``end_time``. No-op when tracing is disabled
    or when ``end_ts < start_ts``.
    """
    if not _ENABLED or _TRACER is None:
        return
    try:
        if end_ts < start_ts:
            return
        start_ns = int(start_ts * 1_000_000_000)
        end_ns = int(end_ts * 1_000_000_000)
        span = _TRACER.start_span(name, start_time=start_ns)
        try:
            span.set_attribute("phase.duration_ms", round((end_ts - start_ts) * 1000.0, 3))
            for k, v in attrs.items():
                try:
                    if v is not None:
                        span.set_attribute(k, v)
                except Exception:
                    pass
        finally:
            try:
                span.end(end_time=end_ns)
            except Exception:
                pass
    except Exception:
        pass


def get_current_trace_id() -> str:
    """Hex trace-id of the active span, or "" if tracing inactive."""
    if not _ENABLED:
        return ""
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span is None:
            return ""
        ctx = span.get_span_context()
        if not ctx or not ctx.is_valid:
            return ""
        return format(ctx.trace_id, "032x")
    except Exception:
        return ""

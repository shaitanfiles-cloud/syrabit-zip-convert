"""Syrabit.ai — Metrics collection, health check infrastructure."""
import time as _time_mod, threading as _threading, logging, asyncio, os
from typing import Dict
from collections import defaultdict as _defaultdict
from datetime import datetime, timezone, timedelta
import httpx
import deps as _deps_mod
from deps import db, redis_client, supa, logger as _dep_logger
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY, EMAIL_FROM, LLM_MODEL
import cache as _cache_mod
from cache import _redis_get_search

logger = logging.getLogger(__name__)

__all__ = [
    "_ALERT_COOLDOWN_S", "_ALERT_THRESHOLDS", "_ALERT_THRESHOLDS_DEFAULT",
    "_ALERT_EXPIRATION_DEFAULT", "_alert_expiration",
    "_HEALTH_CACHE_TTL_S",
    "_METRICS_HISTORY_MAX", "_MetricsStore", "_alert_last_fired", "_alerting_loop",
    "_bg_health_loop", "_cache_stats_log_counter", "_check_health_deps",
    "_dispatch_alert", "_health_deps_cache", "_health_deps_cache_at",
    "_load_alert_settings", "_auto_expire_alerts",
    "_metrics", "_metrics_history", "_metrics_history_lock",
    "_snapshot_metrics", "_start_metrics_collector", "_startup_time",
]

_startup_time = _time_mod.time()

# ── Background health-check cache ─────────────────────────────────────────────
# _check_health_deps() costs ~500 ms per call (Supabase round-trip).
# A background task runs it every 25 s and stores the result here so the
# admin dashboard always reads from cache (~0 ms).
_health_deps_cache: dict = {}
_health_deps_cache_at: float = 0.0
_HEALTH_CACHE_TTL_S: float = 30.0      # max age before falling back to live call

class _MetricsStore:
    def __init__(self):
        self._lock = _threading.Lock()
        self.request_count = 0
        self.error_count = 0
        self.active_requests = 0
        self.active_users: Dict[str, float] = {}
        self.chat_count = 0
        self.endpoint_counts: Dict[str, int] = _defaultdict(int)
        self.status_counts: Dict[int, int] = _defaultdict(int)
        self._rps_window: list = []
        self.spoof_count = 0
        self.spoof_by_bot: Dict[str, int] = _defaultdict(int)
        self._spoof_window: list = []

    def record_request(self, path: str, status: int, user_id: str = None):
        now = _time_mod.time()
        with self._lock:
            self.request_count += 1
            self.status_counts[status] += 1
            if status >= 400:
                self.error_count += 1
            bucket = path.split("?")[0]
            if bucket.startswith("/api/"):
                self.endpoint_counts[bucket] += 1
            if path.startswith("/api/chat"):
                self.chat_count += 1
            if user_id:
                self.active_users[user_id] = now
            self._rps_window.append(now)

    def inc_active(self):
        with self._lock:
            self.active_requests += 1

    def dec_active(self):
        with self._lock:
            self.active_requests -= 1

    def get_rps(self) -> float:
        now = _time_mod.time()
        cutoff = now - 60
        with self._lock:
            self._rps_window = [t for t in self._rps_window if t > cutoff]
            count = len(self._rps_window)
        return round(count / 60.0, 2) if count else 0.0

    def get_active_users(self, window_seconds: int = 300) -> int:
        cutoff = _time_mod.time() - window_seconds
        with self._lock:
            self.active_users = {uid: ts for uid, ts in self.active_users.items() if ts > cutoff}
            return len(self.active_users)

    def get_top_endpoints(self, n: int = 10) -> list:
        with self._lock:
            return sorted(self.endpoint_counts.items(), key=lambda x: -x[1])[:n]

    def record_spoof(self, claimed_bot: str = "unknown"):
        now = _time_mod.time()
        with self._lock:
            self.spoof_count += 1
            self.spoof_by_bot[claimed_bot] += 1
            self._spoof_window.append(now)

    def get_spoof_rpm(self) -> float:
        now = _time_mod.time()
        cutoff = now - 60
        with self._lock:
            self._spoof_window = [t for t in self._spoof_window if t > cutoff]
            return float(len(self._spoof_window))

    def get_spoof_stats(self) -> dict:
        now = _time_mod.time()
        cutoff = now - 60
        with self._lock:
            self._spoof_window = [t for t in self._spoof_window if t > cutoff]
            return {
                "total": self.spoof_count,
                "by_bot": dict(self.spoof_by_bot),
                "rpm": float(len(self._spoof_window)),
            }

_metrics = _MetricsStore()

_METRICS_HISTORY_MAX = 1440
_metrics_history: list = []
_metrics_history_lock = _threading.Lock()

def _snapshot_metrics():
    """Take a point-in-time snapshot of key metrics for graphing."""
    import datetime
    from llm import _llm_batcher
    now = datetime.datetime.utcnow()
    batch_s = _llm_batcher.stats
    spoof_stats = _metrics.get_spoof_stats()
    snap = {
        "t": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ts": int(_time_mod.time()),
        "active_5m": _metrics.get_active_users(300),
        "active_15m": _metrics.get_active_users(900),
        "active_60m": _metrics.get_active_users(3600),
        "rps": _metrics.get_rps(),
        "requests": _metrics.request_count,
        "errors": _metrics.error_count,
        "chats": _metrics.chat_count,
        "in_flight": _metrics.active_requests,
        "llm_batched": batch_s["batched"],
        "llm_deduped": batch_s["deduped"],
        "llm_pending": batch_s["pending"],
        "spoof_total": spoof_stats["total"],
        "spoof_rpm": spoof_stats["rpm"],
    }
    with _metrics_history_lock:
        _metrics_history.append(snap)
        if len(_metrics_history) > _METRICS_HISTORY_MAX:
            del _metrics_history[:len(_metrics_history) - _METRICS_HISTORY_MAX]
    return snap

def _start_metrics_collector():
    """Background thread that snapshots metrics every 60 seconds."""
    def _run():
        while True:
            try:
                _snapshot_metrics()
            except Exception:
                pass
            _time_mod.sleep(60)
    t = _threading.Thread(target=_run, daemon=True)
    t.start()

_start_metrics_collector()


async def _check_health_deps():
    result = {}
    try:
        t0 = _time_mod.time()
        await db.command("ping")
        result["mongodb"] = {"status": "ok", "latencyMs": round((_time_mod.time() - t0) * 1000, 1)}
    except Exception:
        result["mongodb"] = {"status": "error", "latencyMs": 0}
    try:
        if _deps_mod.pg_pool:
            t0 = _time_mod.time()
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute("SELECT 1")
            result["postgresql"] = {"status": "ok", "latencyMs": round((_time_mod.time() - t0) * 1000, 1)}
        else:
            result["postgresql"] = {"status": "not_configured", "latencyMs": 0}
    except Exception:
        result["postgresql"] = {"status": "error", "latencyMs": 0}
    try:
        t0 = _time_mod.time()
        _redis_get_search("__healthcheck__")
        result["redis"] = {"status": "ok", "latencyMs": round((_time_mod.time() - t0) * 1000, 1)}
    except Exception:
        result["redis"] = {"status": "error", "latencyMs": 0}
    try:
        if supa and SUPABASE_URL:
            # Use the best available key: service key → anon key.
            # Direct HTTP GET to /rest/v1/ — no SQL round-trip, just TLS keep-alive.
            _supa_key        = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
            _supa_health_url = SUPABASE_URL.rstrip("/") + "/rest/v1/"
            _supa_headers    = {"apikey": _supa_key, "Authorization": f"Bearer {_supa_key}"}
            t0 = _time_mod.time()
            async with httpx.AsyncClient(
                http2=True,
                timeout=httpx.Timeout(connect=2.0, read=4.0, write=2.0, pool=1.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10, keepalive_expiry=60),
            ) as _hc:
                _r = await _hc.get(_supa_health_url, headers=_supa_headers)
                _r.raise_for_status()
            result["supabase"] = {"status": "ok", "latencyMs": round((_time_mod.time() - t0) * 1000, 1)}
        else:
            result["supabase"] = {"status": "not_configured", "latencyMs": 0}
    except Exception as _se:
        logger.debug(f"Supabase health check failed: {_se}")
        result["supabase"] = {"status": "error", "latencyMs": 0}
    return result


_cache_stats_log_counter = 0   # increments each 25 s cycle; log every 12 cycles = 5 min

async def _bg_health_loop():
    """Warm the health-deps cache every 25 s so dashboard reads are near-instant.
    Also emits a structured cache_stats log every 5 minutes."""
    global _health_deps_cache, _health_deps_cache_at, _cache_stats_log_counter
    await asyncio.sleep(8)                  # let startup settle first
    while True:
        try:
            fresh = await asyncio.wait_for(_check_health_deps(), timeout=10)
            _health_deps_cache    = fresh
            _health_deps_cache_at = _time_mod.time()
        except Exception as _e:
            logger.debug(f"Health bg loop: {_e}")

        # Emit cache hit-rate log every 5 minutes
        _cache_stats_log_counter += 1
        if _cache_stats_log_counter % 12 == 0:
            total = _cache_mod._redis_hit_count + _cache_mod._redis_miss_count
            hit_rate = round(_cache_mod._redis_hit_count / max(1, total), 3)
            logger.info(
                f"cache_stats hit_rate={hit_rate} "
                f"hits={_cache_mod._redis_hit_count} misses={_cache_mod._redis_miss_count} total={total}"
            )

        await asyncio.sleep(25)


# ─────────────────────────────────────────────
# PRODUCTION ALERTING SYSTEM
# ─────────────────────────────────────────────

_ALERT_COOLDOWN_S = 1800   # 30 min between same alert type
_alert_last_fired: dict = {}   # { "alert_key": timestamp }
_ALERT_THRESHOLDS_DEFAULT = {
    "latency_p95_ms": 2000,
    "error_rate_pct": 5.0,
    "fallback_rate_pct": 50.0,
    "spoof_rpm": 50,
}
_ALERT_EXPIRATION_DEFAULT = {
    "enabled": False,
    "days": 7,
}
_ALERT_THRESHOLDS = dict(_ALERT_THRESHOLDS_DEFAULT)
_alert_expiration = dict(_ALERT_EXPIRATION_DEFAULT)

async def _load_alert_settings():
    """Load alert thresholds and expiration settings from db.api_config, falling back to defaults."""
    global _ALERT_THRESHOLDS, _alert_expiration
    try:
        new_thresholds = dict(_ALERT_THRESHOLDS_DEFAULT)
        new_expiration = dict(_ALERT_EXPIRATION_DEFAULT)
        cfg = await db.api_config.find_one({}, {"_id": 0})
        if cfg and "alert_settings" in cfg:
            s = cfg["alert_settings"]
            thresholds = s.get("thresholds", {})
            for k in _ALERT_THRESHOLDS_DEFAULT:
                if k in thresholds:
                    try:
                        new_thresholds[k] = float(thresholds[k])
                    except (ValueError, TypeError):
                        pass
            exp = s.get("expiration", {})
            if "enabled" in exp and isinstance(exp["enabled"], bool):
                new_expiration["enabled"] = exp["enabled"]
            if "days" in exp:
                try:
                    new_expiration["days"] = max(1, int(exp["days"]))
                except (ValueError, TypeError):
                    pass
        _ALERT_THRESHOLDS = new_thresholds
        _alert_expiration = new_expiration
    except Exception as e:
        logger.debug(f"Failed to load alert settings from db: {e}")

async def _auto_expire_alerts():
    """Auto-acknowledge alerts older than the configured expiration period."""
    if not _alert_expiration.get("enabled"):
        return
    days = _alert_expiration.get("days", 7)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        result = await db.alerts.update_many(
            {"acknowledged": False, "fired_at": {"$lt": cutoff}},
            {"$set": {"acknowledged": True, "acknowledged_at": datetime.now(timezone.utc).isoformat(), "acknowledged_by": "auto-expiration"}},
        )
        if result.modified_count > 0:
            logger.info(f"Auto-expired {result.modified_count} alerts older than {days} days")
    except Exception as e:
        logger.debug(f"Alert auto-expiration error: {e}")

async def _dispatch_alert(alert_type: str, title: str, body: str):
    """Send alert via email (Resend) and/or webhook. Respects cooldown."""
    now = _time_mod.time()
    if now - _alert_last_fired.get(alert_type, 0) < _ALERT_COOLDOWN_S:
        return
    _alert_last_fired[alert_type] = now
    logger.warning(f"ALERT [{alert_type}] {title}: {body}")

    # 1) Email alert via Resend (to admin)
    try:
        admin_email = os.environ.get("ALERT_EMAIL", "").strip()
        resend_key = os.environ.get("RESEND_API_KEY", "").strip()
        if admin_email and resend_key:
            import resend as _resend_sdk
            _resend_sdk.api_key = resend_key
            _resend_sdk.Emails.send({
                "from": EMAIL_FROM,
                "to": [admin_email],
                "subject": f"🚨 Syrabit Alert: {title}",
                "html": f"<h2>{title}</h2><p>{body}</p><p style='color:#888'>Alert type: {alert_type}<br>Cooldown: {_ALERT_COOLDOWN_S // 60} min</p>",
            })
    except Exception as e:
        logger.debug(f"Alert email failed: {e}")

    # 2) Webhook alert (Slack / Discord / generic)
    try:
        webhook_url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
        if webhook_url:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(webhook_url, json={
                    "text": f"🚨 *{title}*\n{body}",
                    "alert_type": alert_type,
                    "service": "syrabit-api",
                })
    except Exception as e:
        logger.debug(f"Alert webhook failed: {e}")

    # 3) Persist to db.alerts for admin dashboard visibility
    try:
        await db.alerts.insert_one({
            "type": alert_type,
            "title": title,
            "body": body,
            "fired_at": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        })
    except Exception:
        pass


async def _alerting_loop():
    """Background loop: checks metrics every 2 minutes for alert conditions."""
    await asyncio.sleep(60)   # let startup + first metrics settle
    _prev_errors = 0
    _prev_requests = 0
    _prev_fallbacks = 0
    _prev_llm_calls = 0
    _expire_counter = 0
    while True:
        try:
            await _load_alert_settings()

            _expire_counter += 1
            if _expire_counter >= 15:
                await _auto_expire_alerts()
                _expire_counter = 0
            # ── 1. Error rate in last window ──
            curr_errors = _metrics.error_count
            curr_requests = _metrics.request_count
            delta_err = curr_errors - _prev_errors
            delta_req = curr_requests - _prev_requests
            _prev_errors = curr_errors
            _prev_requests = curr_requests
            if delta_req > 20:   # need minimum sample
                err_rate = (delta_err / delta_req) * 100
                if err_rate > _ALERT_THRESHOLDS["error_rate_pct"]:
                    await _dispatch_alert(
                        "high_error_rate",
                        "Error rate spike",
                        f"{err_rate:.1f}% errors in last 2 min ({delta_err}/{delta_req} requests)",
                    )

            # ── 2. LLM latency (p95 from _chat_latencies ring buffer) ──
            try:
                from rag import _chat_latencies
                recent_lats = [e["latency_ms"] for e in _chat_latencies[-100:]]
                if len(recent_lats) >= 5:
                    lats_sorted = sorted(recent_lats)
                    p95 = lats_sorted[int(len(lats_sorted) * 0.95)]
                    if p95 > _ALERT_THRESHOLDS["latency_p95_ms"]:
                        await _dispatch_alert(
                            "high_latency",
                            "LLM latency spike",
                            f"p95={int(p95)}ms (threshold: {_ALERT_THRESHOLDS['latency_p95_ms']}ms, sample={len(recent_lats)})",
                        )
            except Exception:
                pass

            # ── 3. Spoofed bot UA rate ──
            spoof_rpm = _metrics.get_spoof_rpm()
            if spoof_rpm >= _ALERT_THRESHOLDS["spoof_rpm"]:
                spoof_stats = _metrics.get_spoof_stats()
                top_bots = sorted(spoof_stats["by_bot"].items(), key=lambda x: -x[1])[:5]
                top_str = ", ".join(f"{b}={c}" for b, c in top_bots)
                await _dispatch_alert(
                    "spoofed_bot_surge",
                    "Spoofed bot UA surge detected",
                    f"{spoof_rpm:.0f} spoofed requests/min (threshold: {_ALERT_THRESHOLDS['spoof_rpm']}). "
                    f"Total lifetime: {spoof_stats['total']}. Top claimed bots: {top_str}",
                )

            # ── 4. Fallback rate (from cost log provider != primary) ──
            from routes.admin_advanced import _llm_cost_log
            recent_cost = _llm_cost_log[-100:]
            if len(recent_cost) >= 10:
                primary_model = LLM_MODEL
                fallbacks = sum(1 for e in recent_cost if e.get("model") != primary_model)
                fb_rate = (fallbacks / len(recent_cost)) * 100
                if fb_rate > _ALERT_THRESHOLDS["fallback_rate_pct"]:
                    await _dispatch_alert(
                        "high_fallback_rate",
                        "LLM fallback rate high",
                        f"{fb_rate:.0f}% of last {len(recent_cost)} calls used fallback models "
                        f"(primary: {primary_model})",
                    )

        except Exception as exc:
            logger.debug(f"Alerting loop error: {exc}")

        await asyncio.sleep(120)   # check every 2 minutes


# Admin endpoints for alert management

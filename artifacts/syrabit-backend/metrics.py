"""Syrabit.ai — Metrics collection, health check infrastructure."""
import time as _time_mod, threading as _threading, logging, asyncio, os, uuid
from typing import Dict
from collections import defaultdict as _defaultdict
from datetime import datetime, timezone, timedelta
import httpx
import deps as _deps_mod
from deps import db, supa
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY, EMAIL_FROM, LLM_MODEL
import cache as _cache_mod
from cache import _redis_get_search

logger = logging.getLogger(__name__)

__all__ = [
    "_ALERT_COOLDOWN_S", "_ALERT_THRESHOLDS", "_ALERT_THRESHOLDS_DEFAULT",
    "_ALERT_EXPIRATION_DEFAULT", "_alert_expiration",
    "_NOTIFICATION_CHANNELS_DEFAULT", "_notification_channels",
    "_CHANNEL_STATUS_DEFAULT", "_channel_status",
    "_HEALTH_CACHE_TTL_S",
    "_METRICS_HISTORY_MAX", "_MetricsStore", "_alert_last_fired", "_alerting_loop",
    "_bg_health_loop", "_cache_stats_log_counter", "_check_health_deps",
    "_dispatch_alert", "_health_deps_cache", "_health_deps_cache_at",
    "_load_alert_settings", "_auto_expire_alerts",
    "_metrics", "_metrics_history", "_metrics_history_lock",
    "_snapshot_metrics", "_start_metrics_collector", "_startup_time",
    "record_assamese_refresh_success", "get_assamese_refresh_age_seconds",
    "_asm_last_refresh_at",
]

_startup_time = _time_mod.time()

# ── Task #432: Assamese-purity override refresh heartbeat ─────────────────
# Each gunicorn worker runs `_assamese_purity_refresh_loop` (15s cadence)
# to pick up override PATCH/DELETE made on sibling workers. If that loop
# silently dies (mongo auth error, motor exception spiral, etc.) the only
# signal today is sporadic warnings — on-call won't notice until a
# customer complains. We record a per-worker timestamp of the last
# successful refresh tick and the alerting loop pages on-call when it
# falls behind the configured budget (default 60s = 4× the poll cadence).
#
# Initialised to startup time so the staleness window starts ticking from
# boot — that way a worker that crashes the loop on its very first tick
# still trips the alarm after `assamese_refresh_stale_seconds`.
_asm_last_refresh_at: float = _startup_time


def record_assamese_refresh_success() -> None:
    """Called by `_assamese_purity_refresh_loop` after each successful
    mongo poll. Updates this worker's heartbeat timestamp so the
    alerting loop can detect a stalled refresh loop."""
    global _asm_last_refresh_at
    _asm_last_refresh_at = _time_mod.time()


def get_assamese_refresh_age_seconds() -> float:
    """Seconds since this worker last successfully refreshed the
    Assamese-purity override from mongo. Exposed for the admin
    dashboard / health endpoint and consumed by `_alerting_loop`."""
    return max(0.0, _time_mod.time() - _asm_last_refresh_at)

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
# Task #453: per-alert-type debounce for the inline "no working browser
# push endpoints" warning that gets attached to email/webhook bodies when
# Task #452's pre-check finds zero active admin push subs. Without this,
# every alert burst would re-warn on the still-healthy channels.
_PUSH_SILENT_WARN_COOLDOWN_S = 24 * 3600
_push_silent_warning_last_at: dict = {}   # { "alert_key": timestamp }
_ALERT_THRESHOLDS_DEFAULT = {
    "latency_p95_ms": 2000,
    "error_rate_pct": 5.0,
    "fallback_rate_pct": 50.0,
    "spoof_rpm": 50,
    "auto_block_threshold": 100,
    "auto_block_expiry_hours": 168,
    "endpoint_down_minutes": 60,
    "endpoint_down_check_minutes": 15,
    "collection_growth_per_day": 500,
    "url_404_spike_pct": 20.0,
    "hydrate_failure_per_hour": 50,
    "hydrate_recovery_min_rate_pct": 50.0,
    "hydrate_recovery_min_attempts": 10,
    # Task #656: review-prompt CTR floor alert. Fires when, over the last
    # 7d, ``review_prompt_shown`` >= ``review_prompt_ctr_min_shown`` AND
    # ``ctr_pct`` < ``review_prompt_ctr_floor_pct``. Modeled on the
    # hydrate_recovery_low pair above so admins can tune both knobs from
    # the existing Alert Settings panel without a deploy.
    "review_prompt_ctr_min_shown": 50,
    "review_prompt_ctr_floor_pct": 5.0,
    # Task #661: per-trigger-reason CTR collapse alert. Fires when, over
    # the last 7d, an individual trigger reason's CTR drops by ≥
    # ``review_prompt_reason_ctr_drop_pp`` percentage points vs the
    # prior 7d AND both windows have at least
    # ``review_prompt_reason_ctr_min_shown`` shown events for that
    # reason (so a low-volume reason can't trip the alert on noise).
    # Catches regressions confined to one surface (e.g. answer_helpful)
    # before they wash out the aggregate ``review_prompt_ctr_low``.
    "review_prompt_reason_ctr_drop_pp": 5.0,
    "review_prompt_reason_ctr_min_shown": 30,
    # Task #670: auto-tune the per-reason CTR collapse threshold from
    # baseline noise. The evaluator computes the per-reason CTR mean +
    # sample stddev across the last
    # ``review_prompt_reason_ctr_baseline_weeks`` weeks (excluding the
    # current week) and additionally requires the WoW drop to exceed
    # ``review_prompt_reason_ctr_drop_sigma`` × stddev before paging.
    # A volatile reason whose CTR routinely swings ±10 pp won't trip on
    # an ordinary 6 pp dip; a rock-steady reason will page on a much
    # smaller absolute move once it clears the absolute pp floor. When
    # stddev is 0 or < 2 weekly samples are available, the sigma gate
    # is skipped so behaviour matches the original absolute-only check.
    "review_prompt_reason_ctr_drop_sigma": 2.0,
    "review_prompt_reason_ctr_baseline_weeks": 4,
    # Task #432: page on-call when this worker's Assamese-purity override
    # refresh loop hasn't ticked successfully in this many seconds. The
    # poll cadence is 15s so 60s == 4 missed ticks before paging.
    "assamese_refresh_stale_seconds": 60,
    # Task #707: silent-lockout watcher. Fires
    # `cf_access_admin_silent_lockout` when the CF_ACCESS_* env state has
    # changed but no admin login has succeeded for this many hours since
    # the change. Operator-tunable from the existing Alert Settings table
    # so a noisy / urgent rollout can shorten the window without a deploy.
    "cf_access_silent_lockout_hours": 24,
}
_ALERT_EXPIRATION_DEFAULT = {
    "enabled": False,
    "days": 7,
}
_ALERT_THRESHOLDS = dict(_ALERT_THRESHOLDS_DEFAULT)
_alert_expiration = dict(_ALERT_EXPIRATION_DEFAULT)
_NOTIFICATION_CHANNELS_DEFAULT = {
    "email": "",
    "webhook_url": "",
    # Per-alert-type webhook toggles. When False, the Slack/Discord webhook
    # is suppressed for that alert type even if a webhook URL is configured.
    # (Email, persisted alerts, and browser push are unaffected.)
    "seo_slack_enabled": True,
    # Task #414: per-category webhook toggle for the new hydrate /
    # stale-build alerts. Email + persisted alerts + browser push are
    # unaffected when False — only the Slack/Discord webhook is muted.
    "hydrate_slack_enabled": True,
    # Task #660: separate recipient list for the Monday review-prompt
    # weekly digest (distinct from the incident-alert ``email`` channel).
    # Stored as a list of trimmed lowercase emails. Empty list → fall
    # back to ``email`` then ``ALERT_EMAIL`` so behaviour is unchanged
    # for existing installs that haven't configured the new field.
    "review_prompt_digest_emails": [],
}
# Alert types treated as "SEO incidents" for the Slack webhook toggle.
_SEO_WEBHOOK_ALERT_TYPES = ("seo_health_degraded", "seo_url_spike")
_SEO_DASHBOARD_URL = "https://syrabit.ai/admin/seo"
# Task #414: alert types that get a custom hydrate Slack card.
_HYDRATE_WEBHOOK_ALERT_TYPES = ("hydrate_failure_spike", "hydrate_recovery_low")
_HYDRATE_DASHBOARD_URL = "https://syrabit.ai/admin/dashboard?tab=overview#hydrate-health"
_notification_channels: dict = dict(_NOTIFICATION_CHANNELS_DEFAULT)

# Task #418: per-channel delivery status surfaced on the Alert Settings page so
# admins can confirm their Slack/email/push integrations actually work without
# having to wait for a real incident. Updated by ``_dispatch_alert`` after each
# attempt and persisted to ``db.api_config["alert_channel_status"]`` so it
# survives process restarts.
_CHANNEL_STATUS_KEYS = ("email", "webhook", "persisted", "push")
_CHANNEL_STATUS_DEFAULT = {
    k: {
        "last_attempt_at": None,
        "last_success_at": None,
        "last_error": None,
        "last_alert_type": None,
    } for k in _CHANNEL_STATUS_KEYS
}
_channel_status: dict = {k: dict(v) for k, v in _CHANNEL_STATUS_DEFAULT.items()}

async def _load_alert_settings():
    """Load alert thresholds, expiration, and notification channel settings from db.api_config, falling back to defaults."""
    global _ALERT_THRESHOLDS, _alert_expiration, _notification_channels, _channel_status
    try:
        new_thresholds = dict(_ALERT_THRESHOLDS_DEFAULT)
        new_expiration = dict(_ALERT_EXPIRATION_DEFAULT)
        new_channels = dict(_NOTIFICATION_CHANNELS_DEFAULT)
        cfg = await db.api_config.find_one({}, {"_id": 0})
        if cfg and "alert_channel_status" in cfg and isinstance(cfg["alert_channel_status"], dict):
            saved_status = cfg["alert_channel_status"]
            for k in _CHANNEL_STATUS_KEYS:
                entry = saved_status.get(k)
                if isinstance(entry, dict):
                    _channel_status[k] = {
                        "last_attempt_at": entry.get("last_attempt_at"),
                        "last_success_at": entry.get("last_success_at"),
                        "last_error": entry.get("last_error"),
                        "last_alert_type": entry.get("last_alert_type"),
                    }
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
            channels = s.get("notification_channels", {})
            if isinstance(channels.get("email"), str):
                new_channels["email"] = channels["email"].strip()
            if isinstance(channels.get("webhook_url"), str):
                new_channels["webhook_url"] = channels["webhook_url"].strip()
            if isinstance(channels.get("seo_slack_enabled"), bool):
                new_channels["seo_slack_enabled"] = channels["seo_slack_enabled"]
            if isinstance(channels.get("hydrate_slack_enabled"), bool):
                new_channels["hydrate_slack_enabled"] = channels["hydrate_slack_enabled"]
            # Task #660: review-prompt digest recipient list. Accept a
            # list (preferred) or a comma-separated string for tolerance
            # with older configs / hand-edited DB rows. Filter out blanks
            # and dedupe while preserving order so the saved list stays
            # stable across reloads.
            raw_digest = channels.get("review_prompt_digest_emails")
            if isinstance(raw_digest, str):
                raw_digest = [p for p in raw_digest.split(",")]
            if isinstance(raw_digest, list):
                seen: set = set()
                cleaned: list = []
                for entry in raw_digest:
                    if not isinstance(entry, str):
                        continue
                    e = entry.strip()
                    if not e or "@" not in e:
                        continue
                    key = e.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    cleaned.append(e)
                new_channels["review_prompt_digest_emails"] = cleaned
        _ALERT_THRESHOLDS = new_thresholds
        _alert_expiration = new_expiration
        _notification_channels = new_channels
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

def _build_seo_slack_payload(alert_type: str, title: str, body: str, snap: dict) -> dict:
    """Build a Slack-friendly message for SEO health alerts.

    Uses Slack Block Kit so the message shows severity, sitemap counts, and a
    "Open SEO Manager" button. Slack, Discord (via `text` fallback), and
    generic webhooks all accept the `text` field, while Slack additionally
    renders `blocks` for the rich layout.
    """
    status = str(snap.get("actual", "")).lower() or "degraded"
    severity_label = {
        "critical": ":rotating_light: CRITICAL",
        "degraded": ":warning: DEGRADED",
    }.get(status, f":warning: {status.upper() or 'DEGRADED'}")

    valid_sm = snap.get("valid_sitemaps", "N/A")
    total_sm = snap.get("total_sitemaps", "N/A")
    url_rate = snap.get("url_check_success_rate", "N/A")
    sitemap_line = f"Sitemaps valid: *{valid_sm} / {total_sm}*"
    url_line = f"URL spot-check success: *{url_rate}%*"

    text_fallback = (
        f":rotating_light: *{title}*\n"
        f"{severity_label}\n"
        f"{body}\n"
        f"{sitemap_line} · {url_line}\n"
        f"Dashboard: {_SEO_DASHBOARD_URL}"
    )

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🚨 {title}", "emoji": True}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Severity*\n{severity_label}"},
            {"type": "mrkdwn", "text": f"*Alert type*\n`{alert_type}`"},
            {"type": "mrkdwn", "text": f"*{sitemap_line.split(':',1)[0]}*\n{valid_sm} / {total_sm}"},
            {"type": "mrkdwn", "text": f"*URL spot-checks*\n{url_rate}%"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": body or "SEO health degraded."}},
        {"type": "actions", "elements": [
            {"type": "button",
             "text": {"type": "plain_text", "text": "Open SEO Manager", "emoji": True},
             "url": _SEO_DASHBOARD_URL,
             "style": "primary"},
        ]},
    ]

    return {
        "text": text_fallback,
        "blocks": blocks,
        "alert_type": alert_type,
        "service": "syrabit-api",
        "threshold_snapshot": snap,
    }


def _build_hydrate_slack_payload(alert_type: str, title: str, body: str, snap: dict) -> dict:
    """Build a Slack-friendly message for hydrate / stale-build alerts
    (Task #414). Mirrors ``_build_seo_slack_payload`` so admins on Slack
    get the same depth of context as the dashboard email — failure count
    vs threshold, top failing chunk kind, sample error message, and a
    one-click button to the admin Analytics tile.
    """
    metric = snap.get("metric") or alert_type
    configured = snap.get("value", "N/A")
    actual = snap.get("actual", "N/A")
    top_kind = snap.get("top_kind") or "n/a"
    attempts = snap.get("auto_reload_attempts")
    recoveries = snap.get("auto_reload_recoveries")

    # Pretty units per alert type so the Slack card reads naturally.
    if alert_type == "hydrate_failure_spike":
        actual_str = f"{actual} events/hr"
        threshold_str = f"> {configured}/hr"
        severity_label = ":rotating_light: SPIKE"
    elif alert_type == "hydrate_recovery_low":
        actual_str = f"{actual}%"
        threshold_str = f"< {configured}%"
        severity_label = ":warning: RECOVERY LOW"
    else:  # defensive — should not happen; routing gates on the tuple.
        actual_str = str(actual)
        threshold_str = str(configured)
        severity_label = ":warning: HYDRATE"

    recovery_line = ""
    if attempts is not None and recoveries is not None:
        recovery_line = f"Auto-reload: *{recoveries}/{attempts}* recovered in last hour"

    text_fallback = (
        f":rotating_light: *{title}*\n"
        f"{severity_label} · `{metric}` actual *{actual_str}* (threshold {threshold_str})\n"
        f"{body}\n"
        f"Dashboard: {_HYDRATE_DASHBOARD_URL}"
    )

    fields = [
        {"type": "mrkdwn", "text": f"*Severity*\n{severity_label}"},
        {"type": "mrkdwn", "text": f"*Alert type*\n`{alert_type}`"},
        {"type": "mrkdwn", "text": f"*Threshold*\n{threshold_str}"},
        {"type": "mrkdwn", "text": f"*Actual*\n{actual_str}"},
        {"type": "mrkdwn", "text": f"*Top failing kind*\n{top_kind}"},
    ]
    if recovery_line:
        fields.append({"type": "mrkdwn", "text": f"*Recovery*\n{recovery_line.split(': ',1)[1]}"})

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🚨 {title}", "emoji": True}},
        {"type": "section", "fields": fields},
        {"type": "section", "text": {"type": "mrkdwn", "text": body or "Hydration regression detected."}},
        {"type": "actions", "elements": [
            {"type": "button",
             "text": {"type": "plain_text", "text": "Open Analytics tile", "emoji": True},
             "url": _HYDRATE_DASHBOARD_URL,
             "style": "primary"},
        ]},
    ]

    return {
        "text": text_fallback,
        "blocks": blocks,
        "alert_type": alert_type,
        "service": "syrabit-api",
        "threshold_snapshot": snap,
    }


def _make_outcome():
    return {"attempted": False, "ok": False, "error": None, "skipped_reason": None}


def _summarize_push_failure(doc: dict) -> str:
    """Build a human-readable error string from a push_delivery_log entry."""
    if not doc:
        return "unknown error"
    if doc.get("error"):
        return str(doc["error"])[:200]
    failed = int(doc.get("failed") or 0)
    expired = int(doc.get("expired") or 0)
    total = int(doc.get("total") or 0)
    if total == 0:
        return "no subscribers received the push"
    parts = []
    if failed:
        parts.append(f"{failed} failed")
    if expired:
        parts.append(f"{expired} expired")
    return ", ".join(parts) or "delivery failed"


async def _recompute_push_channel_status() -> None:
    """Refresh _channel_status['push'] from db.push_delivery_log so the Alert
    Settings UI shows the truth (per Task #427) instead of the optimistic
    queued-task signal that just confirms the dispatch coroutine started.

    Scoped to ``target="admin-only"`` because the Alert Settings panel reports
    on admin alert delivery health. Broadcast pushes (``target="all"``) sent
    via /admin/notifications or the exam-reminder loop go to general users
    and must not mask a broken admin push pipeline.
    """
    try:
        admin_filter = {"target": "admin-only"}
        latest = await db.push_delivery_log.find_one(
            admin_filter, {"_id": 0}, sort=[("dispatched_at", -1)]
        )
        latest_success = await db.push_delivery_log.find_one(
            {**admin_filter, "sent": {"$gt": 0}},
            {"_id": 0},
            sort=[("dispatched_at", -1)],
        )
        latest_failure = await db.push_delivery_log.find_one(
            {
                **admin_filter,
                "$or": [
                    {"skipped": True},
                    {"error": {"$exists": True, "$ne": None}},
                    {"$and": [{"sent": 0}, {"$or": [
                        {"failed": {"$gt": 0}},
                        {"expired": {"$gt": 0}},
                        {"total": 0},
                    ]}]},
                ],
            },
            {"_id": 0},
            sort=[("dispatched_at", -1)],
        )
        entry = _channel_status.setdefault("push", dict(_CHANNEL_STATUS_DEFAULT["push"]))
        if latest:
            entry["last_attempt_at"] = latest.get("dispatched_at") or entry.get("last_attempt_at")
            entry["last_alert_type"] = latest.get("alert_type") or entry.get("last_alert_type")
        entry["last_success_at"] = latest_success.get("dispatched_at") if latest_success else None
        if latest_failure and (
            not latest_success
            or (latest_failure.get("dispatched_at") or "") > (latest_success.get("dispatched_at") or "")
        ):
            entry["last_error"] = _summarize_push_failure(latest_failure)
        else:
            entry["last_error"] = None
    except Exception as exc:
        logger.debug(f"Failed to recompute push channel status: {exc}")


async def _persist_channel_status():
    """Best-effort write of in-memory _channel_status to db.api_config."""
    try:
        await db.api_config.update_one(
            {},
            {"$set": {"alert_channel_status": _channel_status}},
            upsert=True,
        )
    except Exception as exc:
        logger.debug(f"Failed to persist channel status: {exc}")


def _record_outcome(channel: str, outcome: dict, alert_type: str, now_iso: str):
    """Update in-memory _channel_status from a single channel outcome."""
    if channel not in _channel_status:
        return
    if not outcome.get("attempted"):
        return
    entry = _channel_status[channel]
    entry["last_attempt_at"] = now_iso
    entry["last_alert_type"] = alert_type
    if outcome.get("ok"):
        entry["last_success_at"] = now_iso
        entry["last_error"] = None
    else:
        entry["last_error"] = outcome.get("error") or outcome.get("skipped_reason") or "unknown error"


async def _dispatch_alert(alert_type: str, title: str, body: str, threshold_snapshot: dict = None,
                          force: bool = False, mark_synthetic: bool = False):
    """Send alert via email (Resend), webhook, persisted alert, and browser push.

    Respects cooldown unless ``force=True`` (test deliveries from the admin
    dashboard bypass cooldown so admins can re-test on demand).

    When ``mark_synthetic=True`` the persisted alert and push notification are
    tagged as test traffic so they can be filtered out and don't pollute the
    real alert feed.

    Returns a dict of per-channel outcomes::

        {
            "email":     {"attempted": bool, "ok": bool, "error": str|None, "skipped_reason": str|None},
            "webhook":   {...},
            "persisted": {...},
            "push":      {...},
            "skipped_cooldown": bool,
        }

    Also updates the in-memory ``_channel_status`` and persists it to
    ``db.api_config["alert_channel_status"]`` so the Alert Settings UI can
    surface per-channel last-success timestamps (Task #418).
    """
    outcomes = {k: _make_outcome() for k in _CHANNEL_STATUS_KEYS}
    outcomes["skipped_cooldown"] = False

    now = _time_mod.time()
    if not force and now - _alert_last_fired.get(alert_type, 0) < _ALERT_COOLDOWN_S:
        outcomes["skipped_cooldown"] = True
        return outcomes
    _alert_last_fired[alert_type] = now
    logger.warning(f"ALERT [{alert_type}] {title}: {body}")

    # Task #453: detect zero active admin push endpoints up-front so the
    # email/webhook channels can carry an inline "browser push is silent"
    # warning. The push step (#4 below) reuses ``active_admin_subs`` to
    # short-circuit. Inline warning is debounced per-alert-type
    # (_PUSH_SILENT_WARN_COOLDOWN_S = 24h) so an alert burst doesn't spam
    # every still-healthy channel. -1 means the check itself errored — we
    # then fall through to the legacy dispatch path so we never silently
    # drop a real alert.
    active_admin_subs = -1
    try:
        active_admin_subs = await db.push_subscriptions.count_documents({
            "$or": [{"role": "admin"}, {"is_admin": True}],
            "active": {"$ne": False},
        })
        if active_admin_subs == 0:
            admin_docs = await db.users.find(
                {"is_admin": True}, {"_id": 0, "id": 1}
            ).to_list(500)
            legacy_admin_ids = [str(d["id"]) for d in admin_docs if d.get("id")]
            if legacy_admin_ids:
                active_admin_subs = await db.push_subscriptions.count_documents({
                    "user_id": {"$in": legacy_admin_ids},
                    "active": {"$ne": False},
                })
    except Exception as exc:
        logger.debug(f"Push pre-check (active admin subs) failed: {exc}")

    push_silent_warn_text = ""
    push_silent_warn_html = ""
    if active_admin_subs == 0:
        last_warn = _push_silent_warning_last_at.get(alert_type, 0)
        if force or now - last_warn >= _PUSH_SILENT_WARN_COOLDOWN_S:
            _push_silent_warning_last_at[alert_type] = now
            push_silent_warn_text = (
                "\n\n⚠️ No working browser push endpoints — "
                "re-enable notifications at /admin/notifications"
            )
            push_silent_warn_html = (
                "<p style=\"margin:14px 0;padding:12px 14px;border-left:4px solid #f59e0b;"
                "background:#fff7ed;color:#92400e;font-weight:600;border-radius:4px\">"
                "&#9888;&#65039; No working browser push endpoints &mdash; "
                "re-enable notifications at "
                "<a href=\"/admin/notifications\" style=\"color:#92400e;text-decoration:underline\">"
                "/admin/notifications</a>"
                "</p>"
            )

    # 1) Email alert via Resend (to admin)
    try:
        admin_email = (_notification_channels.get("email") or os.environ.get("ALERT_EMAIL", "")).strip()
        resend_key = os.environ.get("RESEND_API_KEY", "").strip()
        if not admin_email:
            outcomes["email"]["skipped_reason"] = "no admin email configured"
        elif not resend_key:
            outcomes["email"]["skipped_reason"] = "RESEND_API_KEY not set"
        if admin_email and resend_key:
            outcomes["email"]["attempted"] = True
            import resend as _resend_sdk
            _resend_sdk.api_key = resend_key
            threshold_html = ""
            if threshold_snapshot:
                metric = threshold_snapshot.get("metric", "N/A")
                configured = threshold_snapshot.get("value", "N/A")
                actual = threshold_snapshot.get("actual", "N/A")
                threshold_html = (
                    "<table style='border-collapse:collapse;margin:12px 0;width:100%;max-width:480px'>"
                    "<tr style='background:#f8d7da'>"
                    "<th style='text-align:left;padding:8px;border:1px solid #ddd'>Metric</th>"
                    "<th style='text-align:left;padding:8px;border:1px solid #ddd'>Threshold</th>"
                    "<th style='text-align:left;padding:8px;border:1px solid #ddd'>Actual</th>"
                    "</tr>"
                    f"<tr>"
                    f"<td style='padding:8px;border:1px solid #ddd'><code>{metric}</code></td>"
                    f"<td style='padding:8px;border:1px solid #ddd'>{configured}</td>"
                    f"<td style='padding:8px;border:1px solid #ddd;color:#c0392b;font-weight:bold'>{actual}</td>"
                    f"</tr></table>"
                )
            # Optional rich extra HTML block (e.g. per-sitemap breakdown for
            # the seo_url_spike alert). Callers may attach pre-rendered HTML
            # via threshold_snapshot["extra_html"] or the older
            # threshold_snapshot["by_sitemap_html"] alias.
            extra_html = ""
            if threshold_snapshot:
                extra_html = (
                    threshold_snapshot.get("extra_html")
                    or threshold_snapshot.get("by_sitemap_html")
                    or ""
                )
            # Render newlines in the body as <br> so multi-line bodies (e.g.
            # the seo_url_spike text fallback) read cleanly in HTML email.
            body_html = (body or "").replace("\n", "<br>")
            _resend_sdk.Emails.send({
                "from": EMAIL_FROM,
                "to": [admin_email],
                "subject": f"🚨 Syrabit Alert: {title}",
                "html": f"<h2>{title}</h2><p>{body_html}</p>{push_silent_warn_html}{threshold_html}{extra_html}<p style='color:#888'>Alert type: {alert_type}<br>Cooldown: {_ALERT_COOLDOWN_S // 60} min</p>",
            })
            outcomes["email"]["ok"] = True
    except Exception as e:
        outcomes["email"]["error"] = str(e)
        logger.debug(f"Alert email failed: {e}")

    # 2) Webhook alert (Slack / Discord / generic)
    try:
        webhook_url = (_notification_channels.get("webhook_url") or os.environ.get("ALERT_WEBHOOK_URL", "")).strip()
        # Per-category opt-out: admins can silence SEO alerts on Slack
        # without affecting email or push delivery.
        seo_slack_enabled = bool(_notification_channels.get("seo_slack_enabled", True))
        hydrate_slack_enabled = bool(_notification_channels.get("hydrate_slack_enabled", True))
        if alert_type in _SEO_WEBHOOK_ALERT_TYPES and not seo_slack_enabled:
            outcomes["webhook"]["skipped_reason"] = "seo_slack_enabled disabled"
            webhook_url = ""
        elif alert_type in _HYDRATE_WEBHOOK_ALERT_TYPES and not hydrate_slack_enabled:
            outcomes["webhook"]["skipped_reason"] = "hydrate_slack_enabled disabled"
            webhook_url = ""
        elif not webhook_url:
            outcomes["webhook"]["skipped_reason"] = "no webhook URL configured"
        if webhook_url:
            outcomes["webhook"]["attempted"] = True
            if alert_type in _SEO_WEBHOOK_ALERT_TYPES:
                webhook_payload = _build_seo_slack_payload(
                    alert_type, title, body, threshold_snapshot or {}
                )
            elif alert_type in _HYDRATE_WEBHOOK_ALERT_TYPES:
                webhook_payload = _build_hydrate_slack_payload(
                    alert_type, title, body, threshold_snapshot or {}
                )
            else:
                webhook_payload = {
                    "text": f"🚨 *{title}*\n{body}",
                    "alert_type": alert_type,
                    "service": "syrabit-api",
                }
                if threshold_snapshot:
                    webhook_payload["threshold_snapshot"] = threshold_snapshot
                    webhook_payload["text"] += (
                        f"\n📊 Metric: `{threshold_snapshot.get('metric', 'N/A')}` "
                        f"| Threshold: {threshold_snapshot.get('value', 'N/A')} "
                        f"| Actual: *{threshold_snapshot.get('actual', 'N/A')}*"
                    )
            # Task #453: append the "browser push is silent" advisory to
            # generic and SEO/hydrate Slack payloads alike. The branded
            # _build_*_slack_payload helpers also expose a top-level
            # ``text`` field, so this works uniformly.
            if push_silent_warn_text and isinstance(webhook_payload.get("text"), str):
                webhook_payload["text"] = webhook_payload["text"] + push_silent_warn_text
                webhook_payload["push_silent"] = True
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(webhook_url, json=webhook_payload)
                if 200 <= resp.status_code < 300:
                    outcomes["webhook"]["ok"] = True
                else:
                    outcomes["webhook"]["error"] = f"HTTP {resp.status_code}"
                    logger.debug(f"Alert webhook returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        outcomes["webhook"]["error"] = str(e)
        logger.debug(f"Alert webhook failed: {e}")

    # 3) Persist to db.alerts for admin dashboard visibility
    try:
        outcomes["persisted"]["attempted"] = True
        _now_dt = datetime.now(timezone.utc)
        doc = {
            "type": alert_type,
            "title": title,
            "body": body,
            "fired_at": _now_dt.isoformat(),
            "acknowledged": False,
        }
        if threshold_snapshot:
            doc["threshold_snapshot"] = threshold_snapshot
        if mark_synthetic:
            doc["synthetic"] = True
            # Task #433: stamp a BSON Date `expires_at` so the partial TTL
            # index on db.alerts can prune synthetic test alerts ~7 days
            # after they fire. The string `fired_at` is kept as-is for
            # back-compat with the dashboard feed.
            from routes.admin_notifications import _SYNTHETIC_ALERT_TTL_SECONDS
            doc["expires_at"] = _now_dt + timedelta(seconds=_SYNTHETIC_ALERT_TTL_SECONDS)
        await db.alerts.insert_one(doc)
        outcomes["persisted"]["ok"] = True
    except Exception as e:
        outcomes["persisted"]["error"] = str(e)

    # 4) Browser push notification — filtered by per-admin prefs (push_enabled + push_severities)
    #
    # Task #427: Real per-subscriber delivery health is sourced from
    # ``db.push_delivery_log`` after the dispatch completes (or, for queued
    # fire-and-forget alerts, from the most recent prior dispatch). The
    # outcomes["push"] entry below is only used as the immediate response
    # signal for the test-delivery flow — the persisted _channel_status["push"]
    # is recomputed from the log via ``_recompute_push_channel_status``.
    try:
        outcomes["push"]["attempted"] = True
        from routes.admin_notifications import _dispatch_push_to_admins
        push_body = body
        if threshold_snapshot:
            metric = threshold_snapshot.get("metric", "N/A")
            configured = threshold_snapshot.get("value", "N/A")
            actual = threshold_snapshot.get("actual", "N/A")
            push_body = f"{body}\n📊 {metric}: {actual} (threshold: {configured})"
        push_payload = {
            "title": f"\u26a0\ufe0f {title}",
            "body": push_body,
            "icon": "/icons/icon-192.png",
            "url": "/admin",
            "tag": f"{'test' if mark_synthetic else 'critical'}-alert-{alert_type}-{int(now)}",
            "severity": "critical",
            "alert_type": alert_type,
        }
        if mark_synthetic:
            push_payload["synthetic"] = True

        # Task #452 / #453: ``active_admin_subs`` was already counted at the
        # top of _dispatch_alert (so the email/webhook bodies can carry the
        # "browser push is silent" warning). Reuse that result here to
        # short-circuit the push step.
        if active_admin_subs == 0:
            skip_reason = "no active push subscribers"
            try:
                await db.push_delivery_log.insert_one({
                    "dispatch_id": str(uuid.uuid4()),
                    "dispatched_at": datetime.now(timezone.utc).isoformat(),
                    "target": "admin-only",
                    "payload_title": push_payload.get("title", ""),
                    "payload_body": push_payload.get("body", "")[:500],
                    "alert_type": alert_type,
                    "total": 0,
                    "sent": 0,
                    "failed": 0,
                    "expired": 0,
                    "results": [],
                    "skipped": True,
                    "error": skip_reason,
                })
            except Exception as log_exc:
                logger.warning(f"Failed to persist push skip log: {log_exc}")
            outcomes["push"]["skipped_reason"] = skip_reason
        elif force:
            # Test deliveries: await so we can surface failures synchronously.
            try:
                await _dispatch_push_to_admins(push_payload)
                outcomes["push"]["ok"] = True
            except Exception as e:
                outcomes["push"]["error"] = str(e)
        else:
            # Real alerts dispatch fire-and-forget — we cannot await without
            # blocking the alerting loop. The queued-task signal is no longer
            # used for _channel_status["push"]; truth is read from
            # db.push_delivery_log via _recompute_push_channel_status (Task
            # #427). The outcomes["push"] entry below stays unset (ok=False)
            # because no synchronous result is available for the immediate
            # response.
            asyncio.create_task(_dispatch_push_to_admins(push_payload))
            outcomes["push"]["skipped_reason"] = "queued — see push delivery log for result"
    except Exception as e:
        outcomes["push"]["error"] = str(e)
        logger.debug(f"Alert push dispatch failed: {e}")

    # Record per-channel outcomes to in-memory + persisted status for the
    # Alert Settings UI (Task #418). The push channel is sourced from
    # db.push_delivery_log instead of the optimistic queued-task signal so
    # admins see real delivery health (Task #427).
    now_iso = datetime.now(timezone.utc).isoformat()
    for ch in _CHANNEL_STATUS_KEYS:
        if ch == "push":
            continue
        _record_outcome(ch, outcomes[ch], alert_type, now_iso)
    await _recompute_push_channel_status()
    await _persist_channel_status()

    return outcomes


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
                        threshold_snapshot={"metric": "error_rate_pct", "value": _ALERT_THRESHOLDS["error_rate_pct"], "actual": round(err_rate, 1)},
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
                            threshold_snapshot={"metric": "latency_p95_ms", "value": _ALERT_THRESHOLDS["latency_p95_ms"], "actual": int(p95)},
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
                    threshold_snapshot={"metric": "spoof_rpm", "value": _ALERT_THRESHOLDS["spoof_rpm"], "actual": round(spoof_rpm)},
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
                        threshold_snapshot={"metric": "fallback_rate_pct", "value": _ALERT_THRESHOLDS["fallback_rate_pct"], "actual": round(fb_rate, 1)},
                    )

            # ── 5. Collection size growth rate ──
            try:
                _growth_threshold = _ALERT_THRESHOLDS.get("collection_growth_per_day", 500)
                if _growth_threshold > 0:
                    _now_growth = datetime.now(timezone.utc)
                    _yesterday = (_now_growth - timedelta(days=1)).strftime("%Y-%m-%d")
                    _today_str = _now_growth.strftime("%Y-%m-%d")
                    _snapshots = await db.collection_size_history.find(
                        {"collection": "bot_spoof_attempts", "date": {"$in": [_yesterday, _today_str]}},
                        {"_id": 0, "date": 1, "size": 1},
                    ).to_list(2)
                    if len(_snapshots) == 2:
                        _snap_map = {s["date"]: s["size"] for s in _snapshots}
                        if _yesterday in _snap_map and _today_str in _snap_map:
                            _daily_growth = _snap_map[_today_str] - _snap_map[_yesterday]
                            if _daily_growth > _growth_threshold:
                                await _dispatch_alert(
                                    "collection_growth_spike",
                                    "Collection size growing fast",
                                    f"bot_spoof_attempts grew by {_daily_growth:,} docs in 1 day "
                                    f"(threshold: {_growth_threshold:,}/day)",
                                    threshold_snapshot={
                                        "metric": "collection_growth_per_day",
                                        "value": _growth_threshold,
                                        "actual": _daily_growth,
                                    },
                                )
            except Exception:
                pass

            # ── 6. Assamese-purity override refresh staleness (Task #432) ──
            # Each gunicorn worker polls mongo every ~15s; a stalled loop
            # means PATCH/DELETE on the override never propagates to
            # this worker. Page on-call once we're 4× past the budget.
            try:
                _stale_threshold = float(_ALERT_THRESHOLDS.get("assamese_refresh_stale_seconds", 60) or 0)
                if _stale_threshold > 0:
                    _age = get_assamese_refresh_age_seconds()
                    if _age > _stale_threshold:
                        _worker_pid = os.getpid()
                        await _dispatch_alert(
                            "assamese_override_refresh_stalled",
                            "Assamese override refresh loop stalled",
                            f"Worker pid={_worker_pid} has not refreshed the Assamese-purity override "
                            f"from mongo for {int(_age)}s (threshold: {int(_stale_threshold)}s, "
                            f"poll cadence: 15s). PATCH/DELETE on /admin/assamese-purity will not "
                            f"propagate to this worker until the loop recovers. Check api logs for "
                            f"'[INDIC-SANITIZE] refresh loop tick failed' warnings and verify mongo "
                            f"connectivity. See RUNBOOK.md › Assamese purity override propagation.",
                            threshold_snapshot={
                                "metric": "assamese_refresh_stale_seconds",
                                "value": _stale_threshold,
                                "actual": int(_age),
                                "worker_pid": _worker_pid,
                            },
                        )
            except Exception:
                pass

        except Exception as exc:
            logger.debug(f"Alerting loop error: {exc}")

        await asyncio.sleep(120)   # check every 2 minutes


# Admin endpoints for alert management
